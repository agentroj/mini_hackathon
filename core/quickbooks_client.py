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


def _pnl_summary_url(realm_id, start_date, end_date):
    return (
        f"{settings.QB_API_BASE}/{realm_id}/reports/ProfitAndLoss"
        f"?start_date={start_date}&end_date={end_date}"
        f"&summarize_column_by=Month"
        f"&accounting_method=Accrual"
        f"&minorversion={settings.QB_MINOR_VERSION}"
    )


def get_pnl_matrix_from_qb(realm_id: str, access_token: str, start_date: str, end_date: str):
    """Return a matrix-like structure of the Profit & Loss by Month report.
    Output:
      {
        'columns': ['Jan', 'Feb', ...],
        'rows': [
           {'name': 'Income', 'values': [None,...], 'level': 0, 'is_total': False},
           {'name': 'Sales of Product Income', 'values': [123.45,...], 'level': 1, 'is_total': False},
           {'name': 'Total Income', 'values': [123.45,...], 'level': 0, 'is_total': True},
           ...
        ]
      }
    """
    url = _pnl_summary_url(realm_id, start_date, end_date)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 401:
        resp.raise_for_status()
    resp.raise_for_status()
    data = resp.json()

    columns = data.get("Columns", {}).get("Column", [])
    # Skip the first label column if present
    month_cols = [c.get("ColTitle", "").strip() for c in columns if (c.get("ColType") or "").lower() != "account"]
    # Some responses mark the first column as 'Account' or blank; ensure we only keep period columns
    # Fallback: if that filtered list is empty, keep all titles except possibly the first
    if not month_cols:
        titles = [c.get("ColTitle", "").strip() for c in columns]
        month_cols = titles[1:] if len(titles) > 1 else titles

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

    rows_out = []

    def parse_row(row, level=0):
        # If the row has a header, it's a section (e.g., Income, Expenses)
        header = row.get("Header") or {}
        header_cells = header.get("ColData") or []
        name = (header_cells[0].get("value") if header_cells else None) or None
        if name:
            rows_out.append({"name": name, "values": [None] * len(month_cols), "level": level, "is_total": False})

        # Account/detail row values (if any)
        coldata = row.get("ColData") or []
        if coldata:
            # Expect same number of columns as report columns; first col is label
            label = (coldata[0].get("value") if len(coldata) > 0 else None) or ""
            values = [_as_float(c.get("value")) for c in coldata[1:1+len(month_cols)]]
            # Pad if shorter
            if len(values) < len(month_cols):
                values += [0.0] * (len(month_cols) - len(values))
            rows_out.append({"name": label, "values": values, "level": level, "is_total": False})

        # Children
        for sub in (row.get("Rows", {}) or {}).get("Row", []) or []:
            parse_row(sub, level + (1 if name else level))

        # Summary row (totals) for sections/accounts
        summary = row.get("Summary") or {}
        scells = summary.get("ColData") or []
        if scells:
            # Usually first is label like 'Total Income'
            label = (scells[0].get("value") if len(scells) > 0 else "Total") or "Total"
            values = [_as_float(c.get("value")) for c in scells[1:1+len(month_cols)]]
            if len(values) < len(month_cols):
                values += [0.0] * (len(month_cols) - len(values))
            rows_out.append({"name": label, "values": values, "level": (level if name else max(level-1,0)), "is_total": True})

    for r in (data.get("Rows", {}) or {}).get("Row", []) or []:
        parse_row(r, level=0)

    return {"columns": month_cols, "rows": rows_out}
