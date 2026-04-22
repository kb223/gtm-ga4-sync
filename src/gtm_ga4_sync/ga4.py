"""GA4 custom dimension / metric registration via the Admin API."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from google.analytics.admin_v1beta import (
    AnalyticsAdminServiceClient,
    CustomDimension,
    CustomMetric,
)
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.oauth2.credentials import Credentials

from .config import EventsConfig


@dataclass
class Ga4Stats:
    created: int = 0
    skipped_existing: int = 0
    errors: list[str] = field(default_factory=list)


def apply_ga4(
    creds: Credentials,
    config: EventsConfig,
    property_id: str,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> Ga4Stats:
    """Register custom dimensions (string params) + custom metrics (numeric params).

    GA4 uses `parameter_name` as the natural key — two dimensions can't share a
    parameter_name at the same scope, so the existence check IS the semantic
    duplicate check. No separate fingerprint layer needed.

    Args:
        dry_run: if True, don't call any write API — just show what would happen.
    """
    stats = Ga4Stats()
    property_name = (
        property_id if property_id.startswith("properties/") else f"properties/{property_id}"
    )
    client = AnalyticsAdminServiceClient(credentials=creds)

    existing_dims = {
        d.parameter_name: d for d in client.list_custom_dimensions(parent=property_name)
    }
    existing_metrics = {
        m.parameter_name: m for m in client.list_custom_metrics(parent=property_name)
    }

    if dry_run:
        log("  DRY RUN — no writes will be made")

    log(f"[GA4 1/2] Custom dimensions on {property_name}")
    for param in config.dimension_params():
        if param in existing_dims:
            log(f"  [skip] dimension '{param}' already registered (name='{existing_dims[param].display_name}')")
            stats.skipped_existing += 1
            continue
        if param in existing_metrics:
            msg = (
                f"dimension '{param}': parameter already registered as a METRIC — "
                f"rename the param in events.yml OR remove it from `metrics:`"
            )
            log(f"  [err]  {msg}")
            stats.errors.append(msg)
            continue
        if dry_run:
            log(f"  [+]   dimension '{param}'  (would create)")
            stats.created += 1
            continue
        try:
            dim = CustomDimension(
                parameter_name=param,
                display_name=config.display_name(param),
                scope=CustomDimension.DimensionScope.EVENT,
            )
            client.create_custom_dimension(parent=property_name, custom_dimension=dim)
            log(f"  [+]   dimension '{param}'")
            stats.created += 1
        except AlreadyExists:
            log(f"  [skip] dimension '{param}' (race)")
            stats.skipped_existing += 1
        except GoogleAPICallError as e:
            msg = f"dimension '{param}': {e.message}"
            log(f"  [err]  {msg}")
            stats.errors.append(msg)
        time.sleep(1.0)

    log("\n[GA4 2/2] Custom metrics")
    for param in config.metrics:
        if param in existing_metrics:
            log(f"  [skip] metric '{param}' already registered (name='{existing_metrics[param].display_name}')")
            stats.skipped_existing += 1
            continue
        if param in existing_dims:
            msg = (
                f"metric '{param}': parameter already registered as a DIMENSION — "
                f"rename the param in events.yml OR remove it from `metrics:`"
            )
            log(f"  [err]  {msg}")
            stats.errors.append(msg)
            continue
        if dry_run:
            log(f"  [+]   metric '{param}'  (would create)")
            stats.created += 1
            continue
        try:
            metric = CustomMetric(
                parameter_name=param,
                display_name=config.display_name(param),
                scope=CustomMetric.MetricScope.EVENT,
                measurement_unit=CustomMetric.MeasurementUnit.STANDARD,
            )
            client.create_custom_metric(parent=property_name, custom_metric=metric)
            log(f"  [+]   metric '{param}'")
            stats.created += 1
        except AlreadyExists:
            log(f"  [skip] metric '{param}' (race)")
            stats.skipped_existing += 1
        except GoogleAPICallError as e:
            msg = f"metric '{param}': {e.message}"
            log(f"  [err]  {msg}")
            stats.errors.append(msg)
        time.sleep(1.0)

    return stats


def list_properties(creds: Credentials, log: Callable[[str], None] = print) -> None:
    """List every GA4 property accessible to the authenticated user."""
    client = AnalyticsAdminServiceClient(credentials=creds)
    accounts = list(client.list_account_summaries())
    if not accounts:
        log("(no GA4 accounts accessible)")
        return
    for acc in accounts:
        log(f"{acc.display_name}  (account={acc.account.split('/')[-1]})")
        for prop in acc.property_summaries:
            property_id = prop.property.split("/")[-1]
            log(f"  - {prop.display_name}  (propertyId={property_id})")
