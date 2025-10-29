import urllib.parse
import requests
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import reverse
from .qb_oauth import save_tokens_to_session


def _get_redirect_uri(request):
    """Always build redirect URI from the incoming request host/path.

    This avoids mismatch with Intuit settings if the .env value is stale.
    Ensure this exact URL is added to your Intuit app Redirect URIs.
    """
    built = request.build_absolute_uri(reverse("quickbooks_callback"))
    print(f"[QB] Using request-derived redirect URI: {built}")
    return built


def quickbooks_auth(request):
    if not settings.QB_CLIENT_ID:
        return render(request, "error.html", {"message": "QuickBooks Client ID is not configured (QB_CLIENT_ID)."})

    redirect_uri = _get_redirect_uri(request)
    params = {
        "client_id": settings.QB_CLIENT_ID,
        "response_type": "code",
        "scope": settings.QB_SCOPE,
        "redirect_uri": redirect_uri,
        "state": "state123",  # could sign+verify if you want CSRF protection
        "prompt": "consent",  # optional, forces re-consent
    }
    auth_url = f"{settings.QB_AUTH_BASE}?{urllib.parse.urlencode(params)}"
    print(f"[QB] Authorize URL: {auth_url}")
    return redirect(auth_url)


def quickbooks_callback(request):
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    if not code or not realm_id:
        return render(request, "error.html", {"message": "Missing code or realmId from QuickBooks callback."})

    if not settings.QB_CLIENT_ID or not settings.QB_CLIENT_SECRET:
        return render(request, "error.html", {"message": "QuickBooks keys not configured (QB_CLIENT_ID / QB_CLIENT_SECRET)."})

    redirect_uri = _get_redirect_uri(request)
    print(f"[QB] Callback received. realmId={realm_id} code_present={bool(code)} redirect_uri={redirect_uri}")

    try:
        resp = requests.post(
            settings.QB_OAUTH_TOKEN_URL,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            auth=(settings.QB_CLIENT_ID, settings.QB_CLIENT_SECRET),
            headers={"Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as ex:
        return render(request, "error.html", {"message": f"Token exchange request failed: {ex}"})

    if resp.status_code != 200:
        return render(request, "error.html", {"message": f"Token exchange failed: HTTP {resp.status_code} - {resp.text}"})

    tokens = resp.json()
    print("[QB] Token exchange succeeded.")

    save_tokens_to_session(request, tokens, realm_id)
    return redirect("report")
