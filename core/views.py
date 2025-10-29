from django.shortcuts import render, redirect
from django.conf import settings

import urllib.parse
import requests
from datetime import date, timedelta
import calendar

from .weather_client import get_weather_data
from .quickbooks_client import get_pnl_data_from_qb
from .qb_oauth import ensure_valid_access_token, refresh_access_token, get_session_creds


def about(request):
    return render(request, 'about.html', {'title': 'About Me'})


def projects(request):
    return render(request, 'projects.html', {'title': 'Projects'})


def report(request):
    zipcode = request.GET.get('zipcode', '10001')
    month_str = (request.GET.get('month') or '').strip()
    year_str = (request.GET.get('year') or '').strip()

    # Parse filters
    selected_month = int(month_str) if month_str.isdigit() and 1 <= int(month_str) <= 12 else None
    selected_year = int(year_str) if year_str.isdigit() and 1900 <= int(year_str) <= 3000 else None

    today = date.today()
    current_year = today.year

    # Ensure we have a realmId and a valid access token (refresh if expired)
    try:
        realm_id, access_token = ensure_valid_access_token(request)
    except RuntimeError:
        return redirect('quickbooks_auth')

    # Determine date range based on filters
    if selected_year and selected_month:
        start = date(selected_year, selected_month, 1)
        last_day = calendar.monthrange(selected_year, selected_month)[1]
        end = date(selected_year, selected_month, last_day)
    elif selected_year:
        start = date(selected_year, 1, 1)
        end = date(selected_year, 12, 31)
    else:
        # No filters: full current year
        start = date(current_year, 1, 1)
        end = date(current_year, 12, 31)

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

    temp_data = get_weather_data(zipcode, selected_year if selected_year else current_year, selected_month)

    # Build chart dataset; ensure months show for selection
    month_labels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    if selected_month:
        months = [month_labels[selected_month - 1]]
    else:
        months = month_labels
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
        "no_pnl": not bool(pnl_data),
        "selected_month": selected_month,
        "selected_year": selected_year if selected_year else current_year,
        "year_options": [current_year - i for i in range(0, 6)],
    }
    return render(request, "report.html", context)


"""
QuickBooks auth/callback are implemented in core/views_quickbooks.py and wired via core/urls.py.
The duplicates previously here caused confusion and could lead to redirect loops
when the wrong callback didn’t persist tokens. They have been removed.
"""
