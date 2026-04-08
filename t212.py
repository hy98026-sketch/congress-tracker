"""
Trading 212 API Integration
============================
Manages the Congress Tracker pie. Saves the pie ID to disk
so it can find and update the existing pie reliably.
"""

import base64
import json
import os
import time

import requests

from config import T212_API_KEY, T212_API_SECRET, T212_BASE_URL, PIE_NAME, DATA_DIR

PIE_ID_FILE = f"{DATA_DIR}/pie_id.json"


def _get_auth_header():
    if not T212_API_KEY or not T212_API_SECRET:
        raise ValueError("T212_API_KEY and T212_API_SECRET must be set")
    credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }


def _make_request(method, endpoint, data=None, params=None):
    url = f"{T212_BASE_URL}{endpoint}"
    headers = _get_auth_header()
    try:
        resp = requests.request(method, url, headers=headers, json=data, params=params, timeout=15)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"[T212] Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            return _make_request(method, endpoint, data, params)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except requests.RequestException as e:
        print(f"[T212] API error: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"[T212] Response: {e.response.text}")
        raise


def get_instruments():
    return _make_request("GET", "/equity/metadata/instruments")


def get_all_pies():
    return _make_request("GET", "/equity/pies")


def find_instrument(ticker, instruments):
    for inst in instruments:
        t = inst.get("ticker", "")
        s = inst.get("shortName", "")
        if t == f"{ticker}_US_EQ" or t == f"{ticker}_EQ" or t == ticker or s == ticker:
            return inst
    return None


def save_pie_id(pie_id):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PIE_ID_FILE, "w") as f:
        json.dump({"pie_id": pie_id}, f)
    print(f"[T212] Saved pie ID: {pie_id}")


def load_pie_id():
    if os.path.exists(PIE_ID_FILE):
        with open(PIE_ID_FILE, "r") as f:
            data = json.load(f)
            return data.get("pie_id")
    return None


def find_pie_id():
    """Find pie ID — check saved file first, then search T212."""
    saved = load_pie_id()
    if saved:
        print(f"[T212] Using saved pie ID: {saved}")
        return saved
    try:
        pies = get_all_pies()
        for pie in pies:
            name = pie.get("settings", {}).get("name", "")
            pid = pie.get("settings", {}).get("id") or pie.get("id")
            if name == PIE_NAME and pid:
                save_pie_id(pid)
                return pid
    except Exception as e:
        print(f"[T212] Error searching pies: {e}")
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
        print(f"[T212] Not available on T212: {', '.join(skipped)}")
    if not shares:
        raise ValueError("No valid instruments found")
    # Normalise to exactly 1.0
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


def create_pie(allocations, instruments):
    shares, skipped = _build_shares(allocations, instruments)
    payload = {
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",
        "endDate": None,
        "goal": 0,
        "icon": "Sparkles",
        "instrumentShares": shares,
    }
    result = _make_request("POST", "/equity/pies", data=payload)
    # Save the pie ID for future updates
    pid = result.get("settings", {}).get("id") or result.get("id")
    if pid:
        save_pie_id(pid)
    print(f"[T212] Created pie '{PIE_NAME}' with {len(shares)} instruments")
    return result


def update_pie(pie_id, allocations, instruments):
    shares, skipped = _build_shares(allocations, instruments)
    payload = {
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",
        "instrumentShares": shares,
    }
    result = _make_request("POST", f"/equity/pies/{pie_id}", data=payload)
    print(f"[T212] Updated pie with {len(shares)} instruments")
    return result


def sync_pie(allocations):
    print("[T212] Syncing pie...")
    instruments = get_instruments()
    print(f"[T212] {len(instruments)} instruments available")

    pie_id = find_pie_id()

    if pie_id:
        try:
            print(f"[T212] Updating existing pie (ID: {pie_id})...")
            return update_pie(pie_id, allocations, instruments)
        except Exception as e:
            print(f"[T212] Update failed: {e}, trying to create new...")
            # Clear saved ID if update fails
            if os.path.exists(PIE_ID_FILE):
                os.remove(PIE_ID_FILE)

    print("[T212] Creating new pie...")
    return create_pie(allocations, instruments)
