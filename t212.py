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
    for inst in instruments:
        t = inst.get("ticker", "")
        s = inst.get("shortName", "")
        if t == f"{ticker}_US_EQ" or t == f"{ticker}_EQ" or t == ticker or s == ticker:
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
            return result
        except Exception as e:
            print(f"[T212] Update failed: {e}")
            return {}

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
    return result
