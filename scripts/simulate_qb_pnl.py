import argparse
import calendar
import os
import random
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv


def _cfg_from_env():
    load_dotenv()
    env = (os.getenv("QB_ENV", "sandbox") or "sandbox").lower()
    minor = os.getenv("QB_MINOR_VERSION", "70")
    if env == "production":
        api_base = "https://quickbooks.api.intuit.com/v3/company"
    else:
        api_base = "https://sandbox-quickbooks.api.intuit.com/v3/company"
    return {
        "env": env,
        "api_base": api_base,
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer", # noqa
        "client_id": os.getenv("QB_CLIENT_ID"),
        "client_secret": os.getenv("QB_CLIENT_SECRET"),
        "minor": minor,
    }


def _parse_month(s: str) -> date:
    try:
        # Expecting YYYY-MM
        dt = datetime.strptime(s, "%Y-%m")
        return date(dt.year, dt.month, 1)
    except ValueError:
        raise SystemExit("--month must be in YYYY-MM format, e.g. 2025-01")


def _refresh_access_token(cfg: dict, refresh_token: str) -> dict:
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise SystemExit("QB_CLIENT_ID / QB_CLIENT_SECRET must be set in .env to use --refresh-token") # noqa
    resp = requests.post(
        cfg["token_url"],
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(cfg["client_id"], cfg["client_secret"]),
        headers={"Accept": "application/json"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Failed to refresh token: HTTP {resp.status_code} - {resp.text}") # noqa
    return resp.json()


def _qbo_query(cfg: dict, realm_id: str, access_token: str, q: str) -> dict:
    url = f"{cfg['api_base']}/{realm_id}/query"
    params = {"query": q, "minorversion": cfg["minor"]}
    headers_base = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "mini-hackathon/1.0",
    }
    # Try GET first
    resp = requests.get(url, params=params, headers=headers_base, timeout=20)
    if resp.status_code >= 400:
        # Fallback to POST form (as per QBO docs) using application/text
        post_headers = dict(headers_base)
        post_headers["Content-Type"] = "application/text"
        resp = requests.post(url, params={"minorversion": cfg["minor"]}, data=q, headers=post_headers, timeout=20) # noqa
    if resp.status_code >= 400:
        tid = resp.headers.get("intuit_tid") or resp.headers.get("Intuit-Tid")
        raise SystemExit(f"QBO query failed: HTTP {resp.status_code} tid={tid} body={resp.text}") # noqa
    return resp.json()


def _pick_account(cfg: dict, realm_id: str, access_token: str, account_type: str) -> dict: # noqa
    q = f"select Id, Name from Account where AccountType = '{account_type}' and Active = true" # noqa
    data = _qbo_query(cfg, realm_id, access_token, q)
    accounts = (data.get("QueryResponse", {}) or {}).get("Account", [])
    if not accounts:
        raise SystemExit(f"No active {account_type} account found in company {realm_id}") # noqa
    return accounts[0]


def _validate_realm_id(realm_id: str):
    if not realm_id.isdigit():
        raise SystemExit("--realm-id must be the numeric Company ID (realmId) from Intuit, not a GUID. Example: 123145846915622") # noqa


def _post_journal_entry(cfg: dict, realm_id: str, access_token: str, *, txn_date: date, amount: float, bank_acct: dict, income_acct: dict, note: str): # noqa
    url = f"{cfg['api_base']}/{realm_id}/journalentry"
    params = {"minorversion": cfg["minor"]}
    body = {
        "TxnDate": txn_date.isoformat(),
        "PrivateNote": note,
        "Line": [
            {
                "Id": "1",
                "Description": note,
                "Amount": round(float(amount), 2),
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": str(bank_acct["Id"]), "name": bank_acct.get("Name")}, # noqa
                },
            },
            {
                "Id": "2",
                "Description": note,
                "Amount": round(float(amount), 2),
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": str(income_acct["Id"]), "name": income_acct.get("Name")}, # noqa
                },
            },
        ],
    }
    resp = requests.post(url, params=params, json=body, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }, timeout=20)
    if resp.status_code not in (200, 201):
        raise SystemExit(f"Failed to create JournalEntry: HTTP {resp.status_code} - {resp.text}") # noqa
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Simulate adding P&L data to a QuickBooks Sandbox via Journal Entries.") # noqa
    parser.add_argument("--count", "-n", type=int, required=True, help="How many journal entries to create") # noqa
    parser.add_argument("--zip", "-z", required=True, help="ZIP code tag to include in the note") # noqa
    parser.add_argument("--month", "-m", required=True, help="Target month in YYYY-MM (e.g., 2025-01)") # noqa
    parser.add_argument("--realm-id", required=True, help="QuickBooks company Realm ID (numeric)") # noqa
    tok = parser.add_mutually_exclusive_group(required=True)
    tok.add_argument("--access-token", help="Direct OAuth access token to call QuickBooks API") # noqa
    tok.add_argument("--refresh-token", help="OAuth refresh token; script will exchange for an access token using .env client keys") # noqa
    parser.add_argument("--min-amount", type=float, default=50.0, help="Minimum random amount (default 50.0)") # noqa
    parser.add_argument("--max-amount", type=float, default=500.0, help="Maximum random amount (default 500.0)") # noqa
    args = parser.parse_args()

    cfg = _cfg_from_env()
    _validate_realm_id(args.realm_id)
    month_start = _parse_month(args.month)
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]

    if args.min_amount <= 0 or args.max_amount <= 0 or args.min_amount > args.max_amount: # noqa
        raise SystemExit("Invalid amount range: ensure 0 < min <= max")

    # Acquire access token
    access_token = args.access_token
    if not access_token:
        tokens = _refresh_access_token(cfg, args.refresh_token)
        access_token = tokens.get("access_token")
        if not access_token:
            raise SystemExit("No access_token in refresh response")

    # Pick accounts (first active Bank and first active Income)
    bank_acct = _pick_account(cfg, args.realm_id, access_token, "Bank")
    income_acct = _pick_account(cfg, args.realm_id, access_token, "Income")

    print(f"Using Bank account: {bank_acct['Name']} (Id={bank_acct['Id']})")
    print(f"Using Income account: {income_acct['Name']} (Id={income_acct['Id']})") # noqa

    # Distribute entries across the month
    created = 0
    for i in range(args.count):
        day_offset = int((i * days_in_month) / max(args.count, 1))
        day_offset = min(day_offset, days_in_month - 1)
        txn_date = month_start + timedelta(days=day_offset)
        amount = round(random.uniform(args.min_amount, args.max_amount), 2)
        note = f"Simulated P&L for {args.month} zip {args.zip} entry #{i+1}/{args.count}" # noqa
        res = _post_journal_entry(cfg, args.realm_id, access_token, txn_date=txn_date, amount=amount, bank_acct=bank_acct, income_acct=income_acct, note=note) # noqa
        je = res.get("JournalEntry", {})
        print(f"Created JournalEntry Id={je.get('Id')} TxnDate={je.get('TxnDate')} Amount={amount}") # noqa
        created += 1

    print(f"Done. Created {created} journal entries in realm {args.realm_id} for {args.month}.") # noqa


if __name__ == "__main__":
    main()
