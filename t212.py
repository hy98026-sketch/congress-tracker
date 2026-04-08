"""
Trading 212 API Integration
============================
Manages the Congress Tracker pie via the T212 public API.
"""

import base64
import json
import time

import requests

from config import T212_API_KEY, T212_API_SECRET, T212_BASE_URL, PIE_NAME


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
    search_patterns = [f"{ticker}_US_EQ", f"{ticker}_EQ", ticker]
    for inst in instruments:
        t212_ticker = inst.get("ticker", "")
        short_name = inst.get("shortName", "")
        for pattern in search_patterns:
            if t212_ticker == pattern or short_name == ticker:
                return inst
    return None


def find_congress_pie():
    pies = get_all_pies()
    for pie in pies:
        if pie.get("settings", {}).get("name", "") == PIE_NAME:
            return pie
    return None


def _build_instrument_shares(allocations, instruments):
    """Convert ticker allocations to T212 format, ensuring shares sum to exactly 1.0"""
    instrument_shares = {}
    skipped = []

    for ticker, pct in allocations.items():
        inst = find_instrument(ticker, instruments)
        if inst:
            t212_ticker = inst["ticker"]
            instrument_shares[t212_ticker] = pct / 100.0
        else:
            skipped.append(ticker)

    if skipped:
        print(f"[T212] Not available on T212: {', '.join(skipped)}")

    if not instrument_shares:
        raise ValueError("No valid instruments found")

    # Normalise to sum to exactly 1.0
    total = sum(instrument_shares.values())
    shares = {}
    running_total = 0.0
    items = list(instrument_shares.items())

    for i, (ticker, val) in enumerate(items):
        if i == len(items) - 1:
            # Last item gets whatever is left to ensure exact 1.0
            shares[ticker] = round(1.0 - running_total, 4)
        else:
            normalised = round(val / total, 4)
            shares[ticker] = normalised
            running_total += normalised

    return shares, skipped


def create_pie(allocations, instruments):
    shares, skipped = _build_instrument_shares(allocations, instruments)
    payload = {
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",
        "endDate": None,
        "goal": 0,
        "icon": "Sparkles",
        "instrumentShares": shares,
    }
    result = _make_request("POST", "/equity/pies", data=payload)
    print(f"[T212] Created pie '{PIE_NAME}' with {len(shares)} instruments")
    return result


def update_pie(pie_id, allocations, instruments):
    shares, skipped = _build_instrument_shares(allocations, instruments)
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

    existing_pie = find_congress_pie()

    if existing_pie:
        pie_id = existing_pie.get("settings", {}).get("id") or existing_pie.get("id")
        print(f"[T212] Found existing pie (ID: {pie_id}), updating...")
        result = update_pie(pie_id, allocations, instruments)
    else:
        print("[T212] No existing pie found, creating new one...")
        result = create_pie(allocations, instruments)

    return result
