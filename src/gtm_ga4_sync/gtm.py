"""Idempotent GTM resource provisioning via the Tag Manager API.

Two layers of duplicate detection:
  1. NAME match  — existing resource has the exact name we'd create → skip
  2. FUNCTION match — existing resource does the same thing under a different name
     (DLV reads the same dataLayer key, trigger matches the same event name, GA4 tag
     sends the same eventName) → skip and reuse, warn in output
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import EventsConfig


@dataclass
class ApplyStats:
    created: int = 0
    skipped_by_name: int = 0
    reused_existing: int = 0
    errors: list[str] = field(default_factory=list)


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
                wait = 2 ** (attempt + 3)
                print(f"      [rate-limited] sleeping {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("throttled execute: exhausted retries")


# ---------------------------------------------------------------------------
# GTM API payload builders
# ---------------------------------------------------------------------------


def _dlv_body(param_name: str) -> dict:
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
# Fingerprint extractors — find existing resources by what they DO
# ---------------------------------------------------------------------------


def _param_value(resource: dict, key: str) -> str | None:
    """Get a top-level parameter value by key from a GTM resource body."""
    for p in resource.get("parameter", []):
        if p.get("key") == key:
            return p.get("value")
    return None


def _dlv_fingerprint(variable: dict) -> str | None:
    """For a Data Layer Variable (type='v'), return the dataLayer key it reads."""
    if variable.get("type") != "v":
        return None
    return _param_value(variable, "name")


def _ce_trigger_fingerprint(trigger: dict) -> str | None:
    """For a Custom Event trigger, return the {{_event}} string it matches.

    Only fingerprints simple `{{_event}} equals <name>` filters — more complex
    regex triggers are treated as non-matching (safer to create ours alongside).
    """
    if trigger.get("type") != "customEvent":
        return None
    filters = trigger.get("customEventFilter", [])
    if len(filters) != 1 or filters[0].get("type") != "equals":
        return None
    params = {p.get("key"): p.get("value") for p in filters[0].get("parameter", [])}
    if params.get("arg0") != "{{_event}}":
        return None
    return params.get("arg1")


def _ga4_tag_fingerprint(tag: dict) -> str | None:
    """For a GA4 Event tag, return its eventName — what it sends to GA4."""
    if tag.get("type") != "gaawe":
        return None
    return _param_value(tag, "eventName")


def _build_existing_map(
    items: list[dict],
    fingerprint_fn: Callable[[dict], str | None],
    id_key: str,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (by_name, by_fingerprint) lookups for a list of GTM resources."""
    by_name = {i["name"]: i for i in items}
    by_fp: dict[str, dict] = {}
    for item in items:
        fp = fingerprint_fn(item)
        if fp is None:
            continue
        # First-seen wins if two existing resources have the same fingerprint
        by_fp.setdefault(fp, item)
    return by_name, by_fp


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _default_workspace_path(svc, account_id: str, container_id: str) -> str:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_gtm(
    creds: Credentials,
    config: EventsConfig,
    account_id: str,
    container_id: str,
    measurement_id_override: str | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> ApplyStats:
    """Create DLVs, CE triggers, and GA4 Event tags for everything in config.

    Args:
        dry_run: if True, don't call any write API — just show what would happen.
    """
    stats = ApplyStats()
    svc = build("tagmanager", "v2", credentials=creds, cache_discovery=False)
    ws_path = _default_workspace_path(svc, account_id, container_id)
    measurement_ref = _resolve_measurement_id_ref(svc, ws_path, measurement_id_override)
    log(f"  workspace: {ws_path}")
    log(f"  measurement id: {measurement_ref}")
    if dry_run:
        log("  DRY RUN — no writes will be made")
    log("")

    ws = svc.accounts().containers().workspaces()

    # --- Data Layer Variables ---
    log("[GTM 1/3] Data Layer Variables")
    vars_by_name, vars_by_fp = _build_existing_map(
        ws.variables().list(parent=ws_path).execute().get("variable", []),
        _dlv_fingerprint,
        "variableId",
    )
    for param in config.all_params:
        target_name = f"DLV - {param}"
        if target_name in vars_by_name:
            log(f"  [skip] {target_name} (name exists)")
            stats.skipped_by_name += 1
        elif param in vars_by_fp:
            existing = vars_by_fp[param]
            log(
                f"  [reuse] param '{param}' already read by existing variable "
                f"'{existing['name']}' — not creating {target_name}"
            )
            stats.reused_existing += 1
        elif dry_run:
            log(f"  [+]   {target_name}  (would create)")
            stats.created += 1
        else:
            try:
                _throttle(ws.variables().create(parent=ws_path, body=_dlv_body(param)))
                log(f"  [+]   {target_name}")
                stats.created += 1
            except HttpError as e:
                msg = f"variable {target_name}: {e}"
                log(f"  [err]  {msg}")
                stats.errors.append(msg)

    # --- Custom Event Triggers ---
    log("\n[GTM 2/3] Custom Event Triggers")
    triggers = ws.triggers().list(parent=ws_path).execute().get("trigger", [])
    triggers_by_name, triggers_by_fp = _build_existing_map(
        triggers, _ce_trigger_fingerprint, "triggerId"
    )
    trigger_ids: dict[str, str] = {}
    for event_name in config.events:
        target_name = f"CE - {event_name}"
        if target_name in triggers_by_name:
            log(f"  [skip] {target_name} (name exists)")
            trigger_ids[event_name] = triggers_by_name[target_name]["triggerId"]
            stats.skipped_by_name += 1
        elif event_name in triggers_by_fp:
            existing = triggers_by_fp[event_name]
            log(
                f"  [reuse] event '{event_name}' already matched by existing trigger "
                f"'{existing['name']}' — not creating {target_name}"
            )
            trigger_ids[event_name] = existing["triggerId"]
            stats.reused_existing += 1
        elif dry_run:
            log(f"  [+]   {target_name}  (would create)")
            trigger_ids[event_name] = f"dryrun:{event_name}"
            stats.created += 1
        else:
            try:
                result = _throttle(
                    ws.triggers().create(parent=ws_path, body=_ce_trigger_body(event_name))
                )
                trigger_ids[event_name] = result["triggerId"]
                log(f"  [+]   {target_name}")
                stats.created += 1
            except HttpError as e:
                msg = f"trigger {target_name}: {e}"
                log(f"  [err]  {msg}")
                stats.errors.append(msg)

    # --- GA4 Event Tags ---
    log("\n[GTM 3/3] GA4 Event Tags")
    tags_by_name, tags_by_fp = _build_existing_map(
        ws.tags().list(parent=ws_path).execute().get("tag", []),
        _ga4_tag_fingerprint,
        "tagId",
    )
    for event_name, params in config.events.items():
        target_name = f"GA4 - {event_name}"
        if target_name in tags_by_name:
            log(f"  [skip] {target_name} (name exists)")
            stats.skipped_by_name += 1
            continue
        if event_name in tags_by_fp:
            existing = tags_by_fp[event_name]
            log(
                f"  [reuse] event '{event_name}' already sent to GA4 by existing tag "
                f"'{existing['name']}' — not creating {target_name}"
            )
            stats.reused_existing += 1
            continue
        if event_name not in trigger_ids:
            msg = f"tag {target_name}: no trigger_id resolved (dry-run or earlier error)"
            log(f"  [err]  {msg}")
            stats.errors.append(msg)
            continue
        if dry_run:
            log(f"  [+]   {target_name}  (would create)")
            stats.created += 1
            continue
        try:
            _throttle(
                ws.tags().create(
                    parent=ws_path,
                    body=_ga4_tag_body(event_name, params, trigger_ids[event_name], measurement_ref),
                )
            )
            log(f"  [+]   {target_name}")
            stats.created += 1
        except HttpError as e:
            msg = f"tag {target_name}: {e}"
            log(f"  [err]  {msg}")
            stats.errors.append(msg)

    return stats


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
