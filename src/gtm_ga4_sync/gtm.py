"""Idempotent GTM resource provisioning via the Tag Manager API."""
from __future__ import annotations

import time
from typing import Any, Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import EventsConfig


def _throttle(request, max_retries: int = 5, base_wait: float = 2.0) -> Any:
    """Execute a Tag Manager API request with a fixed ~2s throttle + 429 backoff.

    GTM caps writes around 30/min — a fixed 2s spacing keeps us under that,
    and exponential backoff covers any burst that still trips the quota.
    """
    for attempt in range(max_retries):
        try:
            result = request.execute()
            time.sleep(base_wait)
            return result
        except HttpError as e:
            if e.resp.status == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 3)  # 8, 16, 32, 64s
                print(f"      [rate-limited] sleeping {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("throttled execute: exhausted retries")


# ---------------------------------------------------------------------------
# GTM API payload builders
# ---------------------------------------------------------------------------


def _dlv_body(param_name: str) -> dict:
    """Data Layer Variable — reads dataLayer key by name, dataLayerVersion 2."""
    return {
        "name": f"DLV - {param_name}",
        "type": "v",
        "parameter": [
            {"type": "integer", "key": "dataLayerVersion", "value": "2"},
            {"type": "boolean", "key": "setDefaultValue", "value": "false"},
            {"type": "template", "key": "name", "value": param_name},
        ],
    }


def _ce_trigger_body(event_name: str) -> dict:
    """Custom Event trigger — fires on {{_event}} === event_name."""
    return {
        "name": f"CE - {event_name}",
        "type": "customEvent",
        "customEventFilter": [
            {
                "type": "equals",
                "parameter": [
                    {"type": "template", "key": "arg0", "value": "{{_event}}"},
                    {"type": "template", "key": "arg1", "value": event_name},
                ],
            }
        ],
    }


def _ga4_tag_body(
    event_name: str,
    param_names: list[str],
    trigger_id: str,
    measurement_id_ref: str,
) -> dict:
    """GA4 Event tag (gaawe) — bound to the CE trigger, sends every param."""
    event_params = [
        {
            "type": "map",
            "map": [
                {"type": "template", "key": "name", "value": p},
                {"type": "template", "key": "value", "value": f"{{{{DLV - {p}}}}}"},
            ],
        }
        for p in param_names
    ]
    parameters: list[dict] = [
        {"type": "template", "key": "eventName", "value": event_name},
        {"type": "template", "key": "measurementIdOverride", "value": measurement_id_ref},
    ]
    if event_params:
        parameters.append({"type": "list", "key": "eventParameters", "list": event_params})

    return {
        "name": f"GA4 - {event_name}",
        "type": "gaawe",
        "parameter": parameters,
        "firingTriggerId": [trigger_id],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _by_name(items: list[dict]) -> dict[str, dict]:
    return {i["name"]: i for i in items}


def _default_workspace_path(svc, account_id: str, container_id: str) -> str:
    """Resolve the Default Workspace path under the given container."""
    parent = f"accounts/{account_id}/containers/{container_id}"
    workspaces = svc.accounts().containers().workspaces().list(parent=parent).execute().get(
        "workspace", []
    )
    for ws in workspaces:
        if ws["name"] == "Default Workspace":
            return ws["path"]
    if workspaces:
        return workspaces[0]["path"]
    raise RuntimeError(f"No workspaces found under container {container_id}")


def _resolve_measurement_id_ref(svc, workspace_path: str, override: str | None) -> str:
    """Return either an explicit G-XXXX id or a reference to an existing constant."""
    if override:
        return override
    variables = svc.accounts().containers().workspaces().variables().list(
        parent=workspace_path
    ).execute().get("variable", [])
    for v in variables:
        if v["name"] == "CON - Measurement ID":
            return "{{CON - Measurement ID}}"
        if v["type"] == "c" and "measurement id" in v["name"].lower():
            return f"{{{{{v['name']}}}}}"
    raise RuntimeError(
        "No measurement ID found. Pass --measurement-id G-XXXXXXX, or create a GTM "
        "Constant variable named 'CON - Measurement ID' pointing at your GA4 "
        "measurement ID."
    )


def apply_gtm(
    creds: Credentials,
    config: EventsConfig,
    account_id: str,
    container_id: str,
    measurement_id_override: str | None = None,
    log: Callable[[str], None] = print,
) -> None:
    """Create DLVs, CE triggers, and GA4 Event tags for everything in config."""
    svc = build("tagmanager", "v2", credentials=creds, cache_discovery=False)
    ws_path = _default_workspace_path(svc, account_id, container_id)
    measurement_ref = _resolve_measurement_id_ref(svc, ws_path, measurement_id_override)
    log(f"  workspace: {ws_path}")
    log(f"  measurement id: {measurement_ref}")
    log("")

    ws = svc.accounts().containers().workspaces()

    log("[GTM 1/3] Data Layer Variables")
    existing_vars = _by_name(ws.variables().list(parent=ws_path).execute().get("variable", []))
    for param in config.all_params:
        name = f"DLV - {param}"
        if name in existing_vars:
            log(f"  [skip] {name}")
            continue
        _throttle(ws.variables().create(parent=ws_path, body=_dlv_body(param)))
        log(f"  [+]   {name}")

    log("\n[GTM 2/3] Custom Event Triggers")
    existing_triggers = _by_name(ws.triggers().list(parent=ws_path).execute().get("trigger", []))
    trigger_ids: dict[str, str] = {}
    for event_name in config.events:
        name = f"CE - {event_name}"
        if name in existing_triggers:
            log(f"  [skip] {name}")
            trigger_ids[event_name] = existing_triggers[name]["triggerId"]
            continue
        result = _throttle(
            ws.triggers().create(parent=ws_path, body=_ce_trigger_body(event_name))
        )
        trigger_ids[event_name] = result["triggerId"]
        log(f"  [+]   {name}")

    log("\n[GTM 3/3] GA4 Event Tags")
    existing_tags = _by_name(ws.tags().list(parent=ws_path).execute().get("tag", []))
    for event_name, params in config.events.items():
        name = f"GA4 - {event_name}"
        if name in existing_tags:
            log(f"  [skip] {name}")
            continue
        _throttle(
            ws.tags().create(
                parent=ws_path,
                body=_ga4_tag_body(event_name, params, trigger_ids[event_name], measurement_ref),
            )
        )
        log(f"  [+]   {name}")


def discover(creds: Credentials, log: Callable[[str], None] = print) -> None:
    """List every GTM account + container + workspace accessible to the user."""
    svc = build("tagmanager", "v2", credentials=creds, cache_discovery=False)
    accounts = svc.accounts().list().execute().get("account", [])
    for a in accounts:
        log(f"{a['name']}  (accountId={a['accountId']})")
        containers = svc.accounts().containers().list(parent=a["path"]).execute().get(
            "container", []
        )
        for c in containers:
            log(
                f"  - {c.get('name')}  "
                f"publicId={c.get('publicId')}  "
                f"containerId={c.get('containerId')}"
            )
