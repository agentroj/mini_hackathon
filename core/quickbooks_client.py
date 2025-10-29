import requests
from django.conf import settings


def _pnl_url(realm_id, start_date, end_date):
    return (
        f"{settings.QB_API_BASE}/{realm_id}/reports/ProfitAndLoss"
        f"?start_date={start_date}&end_date={end_date}&minorversion={settings.QB_MINOR_VERSION}"
    )


def get_pnl_data_from_qb(realm_id: str, access_token: str, start_date: str, end_date: str):
    url = _pnl_url(realm_id, start_date, end_date)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 401:
        # Let caller decide to refresh and retry
        resp.raise_for_status()
    resp.raise_for_status()
    data = resp.json()

    # Parse the report format into { 'Jan': amount, ... }
    # QBO P&L report typically returns Columns (months) and a Total row or rows per category.
    # Simplify: take the "Net Income" row if present; else sum columns.
    months = []
    month_amounts = {}

    cols = data.get("Columns", {}).get("Column", [])
    for c in cols:
        if c.get("ColType") == "Month":
            months.append(c.get("ColTitle"))  # e.g. 'Jan-2025' or 'Jan'

    # Find Net Income row, otherwise sum amounts across rows
    total_by_col_index = [0.0] * len(months)
    rows = data.get("Rows", {}).get("Row", [])
    for row in rows:
        # Each row may be a Summary / Section / Data row
        cells = row.get("ColData") or []
        if not cells:
            # It might be a group; dive one level
            group_rows = row.get("Rows", {}).get("Row", [])
            for gr in group_rows:
                gcells = gr.get("ColData") or []
                for i, cell in enumerate(gcells):
                    try:
                        total_by_col_index[i] += float(cell.get("value", "0") or 0)
                    except Exception:
                        pass
            continue

        # Flat row — just add numbers
        for i, cell in enumerate(cells):
            try:
                total_by_col_index[i] += float(cell.get("value", "0") or 0)
            except Exception:
                pass

    # Normalize month labels like 'Jan-2025' -> 'Jan'
    def _short(m):
        return (m or "").split("-")[0][:3] if m else ""

    for i, m in enumerate(months):
        month_amounts[_short(m) or f"M{i+1}"] = round(total_by_col_index[i], 2)

    return month_amounts
