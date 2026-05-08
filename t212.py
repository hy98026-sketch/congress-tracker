"""
Trading 212 API Integration
"""

import base64
import os
import time

import requests

from config import T212_API_KEY, T212_API_SECRET, T212_BASE_URL, PIE_NAME

T212_PIE_ID = os.getenv("T212_PIE_ID", "")


def _get_auth_header():
    credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def _make_request(method, endpoint, data=None):
    url = f"{T212_BASE_URL}{endpoint}"
    try:
        resp = requests.request(method, url, headers=_get_auth_header(), json=data, timeout=15)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", 5)))
            return _make_request(method, endpoint, data)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except requests.RequestException as e:
        print(f"[T212] API error: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"[T212] Response: {e.response.text}")
        raise


def get_instruments():
    return _make_request("GET", "/equity/metadata/instruments")


def find_instrument(ticker, instruments):
    """Match a ticker against T212's instrument list. Handles dotted
    tickers (BRK.B → BRKb_US_EQ on T212) by trying a few variants."""
    # Build the candidate forms T212 might use
    base = ticker.replace(".", "")  # BRK.B → BRKB
    lower_suffix = ticker.replace(".", "").upper()

    # Some dotted tickers on T212 use lowercase suffix: BRK.B → BRKb
    dotted_lower = None
    if "." in ticker:
        head, tail = ticker.split(".", 1)
        dotted_lower = f"{head}{tail.lower()}"

    candidates = {ticker, base, lower_suffix}
    if dotted_lower:
        candidates.add(dotted_lower)

    suffixes = ["_US_EQ", "_EQ", ""]

    for inst in instruments:
        t = inst.get("ticker", "")
        s = inst.get("shortName", "")
        for c in candidates:
            for suf in suffixes:
                if t == f"{c}{suf}":
                    return inst
        if s == ticker or s == base:
            return inst
    return None


def _build_shares(allocations, instruments):
    shares = {}
    skipped = []
    for ticker, pct in allocations.items():
        inst = find_instrument(ticker, instruments)
        if inst:
            shares[inst["ticker"]] = pct / 100.0
        else:
            skipped.append(ticker)
    if skipped:
        print(f"[T212] Not on T212: {', '.join(skipped)}")
    if not shares:
        raise ValueError("No valid instruments")
    total = sum(shares.values())
    items = list(shares.items())
    result = {}
    running = 0.0
    for i, (t, v) in enumerate(items):
        if i == len(items) - 1:
            result[t] = round(1.0 - running, 4)
        else:
            norm = round(v / total, 4)
            result[t] = norm
            running += norm
    return result, skipped


def sync_pie(allocations):
    """Sync the pie. Returns (api_result, skipped_tickers)."""
    print("[T212] Syncing pie...")
    instruments = get_instruments()
    print(f"[T212] {len(instruments)} instruments available")
    shares, skipped = _build_shares(allocations, instruments)

    if T212_PIE_ID:
        try:
            print(f"[T212] Updating pie {T212_PIE_ID}...")
            result = _make_request("POST", f"/equity/pies/{T212_PIE_ID}", data={
                "dividendCashAction": "REINVEST",
                "instrumentShares": shares,
            })
            print(f"[T212] Updated pie with {len(shares)} instruments")
            return result, skipped
        except Exception as e:
            print(f"[T212] Update failed: {e}")
            return {}, skipped

    print("[T212] No T212_PIE_ID set. Creating new pie...")
    result = _make_request("POST", "/equity/pies", data={
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",
        "endDate": None,
        "goal": 0,
        "icon": "Sparkles",
        "instrumentShares": shares,
    })
    pid = result.get("settings", {}).get("id") or result.get("id")
    print(f"[T212] Created pie (ID: {pid}) — add T212_PIE_ID={pid} to Railway!")
    return result, skipped
