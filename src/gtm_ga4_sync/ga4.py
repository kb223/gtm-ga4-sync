"""GA4 custom dimension / metric registration via the Admin API."""
from __future__ import annotations

import time
from typing import Callable

from google.analytics.admin_v1beta import (
    AnalyticsAdminServiceClient,
    CustomDimension,
    CustomMetric,
)
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.oauth2.credentials import Credentials

from .config import EventsConfig


def apply_ga4(
    creds: Credentials,
    config: EventsConfig,
    property_id: str,
    log: Callable[[str], None] = print,
) -> None:
    """Register custom dimensions (string params) + custom metrics (numeric params).

    Args:
        property_id: GA4 property ID as a bare integer string (e.g. "123456789")
                     or the full "properties/123456789" form.
    """
    property_name = property_id if property_id.startswith("properties/") else f"properties/{property_id}"
    client = AnalyticsAdminServiceClient(credentials=creds)

    existing_dims = {d.parameter_name: d for d in client.list_custom_dimensions(parent=property_name)}
    existing_metrics = {m.parameter_name: m for m in client.list_custom_metrics(parent=property_name)}

    log(f"[GA4 1/2] Custom dimensions on {property_name}")
    for param in config.dimension_params():
        if param in existing_dims:
            log(f"  [skip] dimension '{param}'")
            continue
        try:
            dim = CustomDimension(
                parameter_name=param,
                display_name=config.display_name(param),
                scope=CustomDimension.DimensionScope.EVENT,
            )
            client.create_custom_dimension(parent=property_name, custom_dimension=dim)
            log(f"  [+]   dimension '{param}'")
        except AlreadyExists:
            log(f"  [skip] dimension '{param}' (race)")
        except GoogleAPICallError as e:
            log(f"  [err]  dimension '{param}': {e.message}")
        time.sleep(1.0)  # low Admin API write quota

    log("\n[GA4 2/2] Custom metrics")
    for param in config.metrics:
        if param in existing_metrics:
            log(f"  [skip] metric '{param}'")
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
        except AlreadyExists:
            log(f"  [skip] metric '{param}' (race)")
        except GoogleAPICallError as e:
            log(f"  [err]  metric '{param}': {e.message}")
        time.sleep(1.0)


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
