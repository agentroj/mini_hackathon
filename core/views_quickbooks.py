import urllib.parse
import requests
from django.shortcuts import redirect, render
from django.conf import settings
from .qb_oauth import save_tokens_to_session


def quickbooks_auth(request):
    params = {
        "client_id": settings.QB_CLIENT_ID,
        "response_type": "code",
        "scope": settings.QB_SCOPE,
        "redirect_uri": settings.QB_REDIRECT_URI,
        "state": "state123",  # could sign+verify if you want CSRF protection
        "prompt": "consent",  # optional, forces re-consent
    }
    return redirect(f"{settings.QB_AUTH_BASE}?{urllib.parse.urlencode(params)}")


def quickbooks_callback(request):
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    if not code or not realm_id:
        return render(request, "error.html", {"message": "Missing code or realmId from QuickBooks callback."})

    resp = requests.post(
        settings.QB_OAUTH_TOKEN_URL,
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.QB_REDIRECT_URI},
        auth=(settings.QB_CLIENT_ID, settings.QB_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=20,
    )
    if resp.status_code != 200:
        return render(request, "error.html", {"message": f"Token exchange failed: {resp.text}"})

    tokens = resp.json()
    
    print(">>> CALLBACK realmId:", realm_id)
    print(">>> CALLBACK code:", code)
    print(">>> TOKEN RESPONSE:", tokens)
    
    save_tokens_to_session(request, tokens, realm_id)
    return redirect("report")
