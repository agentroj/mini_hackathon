import requests
from django.conf import settings
from datetime import datetime


def _pnl_url(realm_id, start_date, end_date):
    return (
        f"{settings.QB_API_BASE}/{realm_id}/reports/ProfitAndLossDetail"
        f"?start_date={start_date}&end_date={end_date}"
        f"&accounting_method=Accrual"
        f"&minorversion={settings.QB_MINOR_VERSION}"
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

    # Parse ProfitAndLossDetail rows and group by month via TxnDate/Amount columns
    month_amounts = {}

    cols = data.get("Columns", {}).get("Column", [])
    date_idx = None
    amount_idx = None
    for idx, c in enumerate(cols):
        title = (c.get("ColTitle") or "").lower()
        ctype = (c.get("ColType") or "").lower()
        if date_idx is None and ("date" in title or ctype == "date"):
            date_idx = idx
        if amount_idx is None and ("amount" in title or ctype == "money"):
            amount_idx = idx

    def _as_float(v):
        if v is None:
            return 0.0
        s = str(v).strip()
        if not s or s == "-":
            return 0.0
        s = s.replace(",", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            return float(s)
        except Exception:
            return 0.0

    if date_idx is None or amount_idx is None:
        print("[QB PnL] Could not find TxnDate/Amount columns in ProfitAndLossDetail report")
        return {}

    def add_cells(cells):
        if not cells:
            return
        if max(date_idx, amount_idx) >= len(cells):
            return
        date_val = (cells[date_idx] or {}).get("value")
        amt_val = (cells[amount_idx] or {}).get("value")
        # Parse date -> month key
        mkey = None
        s = (date_val or "").strip()
        if s:
            dt = None
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                try:
                    dt = datetime.strptime(s, "%m/%d/%Y")
                except Exception:
                    dt = None
            if dt:
                mkey = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.month - 1]
        if not mkey:
            return
        amt = _as_float(amt_val)
        month_amounts[mkey] = round(month_amounts.get(mkey, 0.0) + amt, 2)

    def walk(row):
        add_cells(row.get("ColData") or [])
        for sub in (row.get("Rows", {}) or {}).get("Row", []) or []:
            walk(sub)
        add_cells((row.get("Summary") or {}).get("ColData") or [])

    rows = data.get("Rows", {}).get("Row", [])
    for row in rows:
        walk(row)

    print(f"[QB PnL] Parsed month totals (detail): {month_amounts}")
    return month_amounts
