import time
import requests
from django.conf import settings


def save_tokens_to_session(request, tokens: dict, realm_id: str):
    # tokens has: access_token, refresh_token, expires_in (seconds)
    now = int(time.time())
    expires_at = now + int(tokens.get("expires_in", 3600)) - 30  # renew 30s early
    request.session["QB_REALM_ID"] = realm_id
    request.session["QB_ACCESS_TOKEN"] = tokens.get("access_token")
    request.session["QB_REFRESH_TOKEN"] = tokens.get("refresh_token")
    request.session["QB_EXPIRES_AT"] = expires_at
    request.session.modified = True


def get_session_creds(request):
    return {
        "realm_id": request.session.get("QB_REALM_ID"),
        "access_token": request.session.get("QB_ACCESS_TOKEN"),
        "refresh_token": request.session.get("QB_REFRESH_TOKEN"),
        "expires_at": request.session.get("QB_EXPIRES_AT", 0),
    }


def is_access_token_expired(request) -> bool:
    now = int(time.time())
    return now >= int(request.session.get("QB_EXPIRES_AT", 0))


def refresh_access_token(request) -> dict:
    refresh_token = request.session.get("QB_REFRESH_TOKEN")
    if not refresh_token:
        raise RuntimeError("No refresh token in session")

    resp = requests.post(
        settings.QB_OAUTH_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(settings.QB_CLIENT_ID, settings.QB_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    tokens = resp.json()
    # Intuit may rotate the refresh token — always save the new one
    realm_id = request.session.get("QB_REALM_ID")
    save_tokens_to_session(request, tokens, realm_id)
    return tokens


def ensure_valid_access_token(request):
    """
    Ensures session has realmId and a valid (non-expired) access token.
    Returns (realm_id, access_token). Raises if missing.
    """
    creds = get_session_creds(request)
    if not creds["realm_id"]:
        raise RuntimeError("No QuickBooks realmId in session")
    if not creds["access_token"]:
        raise RuntimeError("No QuickBooks access token in session")
    if is_access_token_expired(request):
        tokens = refresh_access_token(request)
        return creds["realm_id"], tokens["access_token"]
    return creds["realm_id"], creds["access_token"]
