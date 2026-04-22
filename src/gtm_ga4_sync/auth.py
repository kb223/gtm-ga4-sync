"""OAuth2 auth for GTM + GA4 Admin APIs via a Desktop OAuth client.

One-time browser consent, then a cached refresh token is reused silently.
Uses the user's own OAuth client so there's no "unverified app" friction
on sensitive scopes.
"""
from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "gtm-ga4-sync"
DEFAULT_TOKEN_PATH = DEFAULT_CONFIG_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/analytics.edit",
]


class MissingClientSecretError(Exception):
    """Raised when we need to auth but no client_secret.json was provided."""


def get_credentials(
    client_secret_path: Path | None = None,
    token_path: Path = DEFAULT_TOKEN_PATH,
    force_reauth: bool = False,
) -> Credentials:
    """Return cached creds, refresh if expired, or run the browser OAuth flow.

    Args:
        client_secret_path: path to the downloaded OAuth client JSON from GCP.
            Only required on first run OR when --force-reauth is set; refreshes
            use the client_id/client_secret embedded in the cached token.
        token_path: where to cache the refresh token. Created if missing.
        force_reauth: skip the cache and run the browser flow again.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds: Credentials | None = None
    if not force_reauth and token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token and not force_reauth:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        token_path.chmod(0o600)
        return creds

    # Need to run the browser flow — requires client_secret_path.
    if client_secret_path is None or not client_secret_path.exists():
        raise MissingClientSecretError(
            "No valid cached token and no --client-secret provided. Run:\n"
            "  gtm-ga4-sync auth --client-secret /path/to/client_secret.json\n"
            "(Download the OAuth Desktop client JSON from GCP Console → APIs & "
            "Services → Credentials.)"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
    return creds
