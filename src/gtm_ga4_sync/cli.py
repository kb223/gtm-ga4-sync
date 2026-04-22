"""gtm-ga4-sync CLI."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .auth import DEFAULT_TOKEN_PATH, MissingClientSecretError, get_credentials
from .config import load_config
from .ga4 import apply_ga4, list_properties
from .gtm import apply_gtm, discover as discover_gtm


def _client_secret_option(required: bool):
    def decorator(f):
        return click.option(
            "--client-secret",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            required=required,
            default=None,
            envvar="GTM_GA4_SYNC_CLIENT_SECRET",
            help="Path to OAuth client JSON (Desktop type) from GCP Console. "
            "Required on first run; optional afterward (cached token is reused). "
            "Env: GTM_GA4_SYNC_CLIENT_SECRET.",
        )(f)

    return decorator


def _token_option(f):
    return click.option(
        "--token",
        type=click.Path(dir_okay=False, path_type=Path),
        default=DEFAULT_TOKEN_PATH,
        show_default=True,
        help="Where to cache the refresh token.",
    )(f)


def _creds_or_exit(client_secret: Path | None, token: Path, force_reauth: bool = False):
    try:
        return get_credentials(client_secret, token, force_reauth=force_reauth)
    except MissingClientSecretError as e:
        click.echo(str(e), err=True)
        sys.exit(2)


@click.group()
@click.version_option()
def main() -> None:
    """Declare dataLayer events in YAML, provision GTM + GA4 in one command."""


@main.command()
@_client_secret_option(required=True)
@_token_option
@click.option("--force-reauth", is_flag=True, help="Ignore cached token, reopen browser consent.")
def auth(client_secret: Path, token: Path, force_reauth: bool) -> None:
    """Run one-time OAuth consent and cache a refresh token."""
    creds = _creds_or_exit(client_secret, token, force_reauth=force_reauth)
    click.echo(f"Authenticated. Token cached at {token}")
    click.echo(f"Scopes: {list(creds.scopes or [])}")


@main.command()
@_client_secret_option(required=False)
@_token_option
def discover(client_secret: Path | None, token: Path) -> None:
    """List every GTM account/container and GA4 property accessible to you."""
    creds = _creds_or_exit(client_secret, token)
    click.echo("=== GTM ===")
    discover_gtm(creds)
    click.echo("\n=== GA4 ===")
    list_properties(creds)


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to events.yml",
)
@click.option("--gtm-account", required=True, help="GTM account ID (numeric).")
@click.option("--gtm-container", required=True, help="GTM container ID (numeric).")
@click.option("--ga4-property", "ga4_property", required=True, help="GA4 property ID (numeric).")
@click.option(
    "--measurement-id",
    default=None,
    help="GA4 measurement ID to hardcode into GA4 tags (e.g. G-XXXXXXX). "
    "Default: reference the existing {{CON - Measurement ID}} constant in the container.",
)
@click.option("--skip-gtm", is_flag=True, help="Only register GA4 dimensions/metrics.")
@click.option("--skip-ga4", is_flag=True, help="Only provision GTM resources.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be created/reused without making any writes.",
)
@_client_secret_option(required=False)
@_token_option
def apply(
    config_path: Path,
    gtm_account: str,
    gtm_container: str,
    ga4_property: str,
    measurement_id: str | None,
    skip_gtm: bool,
    skip_ga4: bool,
    dry_run: bool,
    client_secret: Path | None,
    token: Path,
) -> None:
    """Provision GTM resources + GA4 custom dimensions from an events.yml config."""
    if skip_gtm and skip_ga4:
        click.echo("--skip-gtm and --skip-ga4 are mutually exclusive.", err=True)
        sys.exit(2)

    config = load_config(config_path)
    creds = _creds_or_exit(client_secret, token)

    gtm_stats = None
    ga4_stats = None

    if not skip_gtm:
        click.echo("========== GTM ==========")
        gtm_stats = apply_gtm(
            creds, config, gtm_account, gtm_container, measurement_id, dry_run=dry_run
        )

    if not skip_ga4:
        click.echo("\n========== GA4 ==========")
        ga4_stats = apply_ga4(creds, config, ga4_property, dry_run=dry_run)

    # Summary
    click.echo("\n========== Summary ==========")
    if gtm_stats:
        click.echo(
            f"GTM: {gtm_stats.created} created, "
            f"{gtm_stats.skipped_by_name} skipped (name exists), "
            f"{gtm_stats.reused_existing} reused (functional duplicate), "
            f"{len(gtm_stats.errors)} errors"
        )
    if ga4_stats:
        click.echo(
            f"GA4: {ga4_stats.created} created, "
            f"{ga4_stats.skipped_existing} skipped (already registered), "
            f"{len(ga4_stats.errors)} errors"
        )

    errors = (gtm_stats.errors if gtm_stats else []) + (ga4_stats.errors if ga4_stats else [])
    if errors:
        click.echo("\nErrors:")
        for e in errors:
            click.echo(f"  - {e}")
        sys.exit(1)

    if dry_run:
        click.echo("\nDry run complete. Re-run without --dry-run to apply.")
    else:
        click.echo(
            f"\nDone. Review GTM in the UI before publishing:\n"
            f"  https://tagmanager.google.com/#/container/"
            f"accounts/{gtm_account}/containers/{gtm_container}"
        )


if __name__ == "__main__":
    main()
