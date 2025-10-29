from django.shortcuts import render, redirect
from django.conf import settings

import urllib.parse
import requests
from datetime import date, timedelta

from .weather_client import get_weather_data
from .quickbooks_client import get_pnl_data_from_qb
from .qb_oauth import ensure_valid_access_token, refresh_access_token, get_session_creds


def about(request):
    return render(request, 'about.html', {'title': 'About Me'})


def projects(request):
    return render(request, 'projects.html', {'title': 'Projects'})


def report(request):
    zipcode = request.GET.get('zipcode', '10001')

    # Ensure we have a realmId and a valid access token (refresh if expired)
    try:
        realm_id, access_token = ensure_valid_access_token(request)
    except RuntimeError:
        return redirect('quickbooks_auth')

    end = date.today()
    start = end - timedelta(days=365)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    # Call QBO; if 401, refresh once and retry
    try:
        pnl_data = get_pnl_data_from_qb(realm_id, access_token, start_str, end_str)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            # Access token likely expired but our “expired” check missed by a hair — refresh and retry once
            tokens = refresh_access_token(request)
            realm_id = get_session_creds(request)["realm_id"]
            access_token = tokens["access_token"]
            pnl_data = get_pnl_data_from_qb(realm_id, access_token, start_str, end_str)
        else:
            raise

    temp_data = get_weather_data(zipcode)

    # Build chart dataset (keep your existing template)
    months = list(pnl_data.keys())
    report_data = [
        {"month": m, "pnl": pnl_data.get(m, 0), "temp": temp_data.get(m, 0)}
        for m in months
    ]

    context = {
        "title": "Report",
        "zipcode": zipcode,
        "report": report_data,
        "months": [r["month"] for r in report_data],
        "pnl_values": [r["pnl"] for r in report_data],
        "temp_values": [r["temp"] for r in report_data],
    }
    return render(request, "report.html", context)


def quickbooks_auth(request):
    base = "https://appcenter.intuit.com/connect/oauth2"
    params = {
        "client_id": settings.QB_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": settings.QB_REDIRECT_URI,
        "state": "some-random-state"
    }
    url = f"{base}?{urllib.parse.urlencode(params)}"
    return redirect(url)


def quickbooks_callback(request):
    code = request.GET.get("code")
    realmId = request.GET.get("realmId")
    if not code or not realmId:
        return render(request, "error.html", {"message": "QuickBooks authorization failed."})

    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    auth = (settings.QB_CLIENT_ID, settings.QB_CLIENT_SECRET)
    headers = {"Accept": "application/json"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.QB_REDIRECT_URI
    }
    resp = requests.post(token_url, auth=auth, headers=headers, data=data)
    resp.raise_for_status()
    tokens = resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    # store tokens + realmId in your DB or secure storage
    # ...
    return redirect("report")  # or wherever
