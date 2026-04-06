"""
Trading 212 API Integration
============================
Manages the "Congress Top 10 Tracker" pie via the T212 public API.

API docs: https://t212public-api-docs.redoc.ly/
Auth: Basic auth with API key + secret (base64 encoded)

IMPORTANT: 
- Generate API keys from the Trading 212 app (Settings > API)
- Start with the DEMO environment to test!
- The live API currently only supports Market Orders
- Pies can hold up to 50 instruments
"""

import base64
import json
import time
from typing import Optional

import requests

from config import T212_API_KEY, T212_API_SECRET, T212_BASE_URL, PIE_NAME


def _get_auth_header() -> dict:
    """Build the Authorization header for T212 API."""
    if not T212_API_KEY or not T212_API_SECRET:
        raise ValueError(
            "T212_API_KEY and T212_API_SECRET must be set as environment variables. "
            "Generate them from the Trading 212 app under Settings > API."
        )
    credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }


def _make_request(
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    """Make an authenticated request to the T212 API."""
    url = f"{T212_BASE_URL}{endpoint}"
    headers = _get_auth_header()

    try:
        resp = requests.request(
            method,
            url,
            headers=headers,
            json=data,
            params=params,
            timeout=15,
        )

        if resp.status_code == 429:
            # Rate limited — wait and retry
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


# ─── Account ─────────────────────────────────────────────────────────

def get_account_cash() -> dict:
    """Get account cash balance."""
    return _make_request("GET", "/equity/account/cash")


def get_account_info() -> dict:
    """Get account metadata (ID, currency, etc)."""
    return _make_request("GET", "/equity/account/info")


# ─── Instruments ─────────────────────────────────────────────────────

def get_instruments() -> list[dict]:
    """Get all tradeable instruments. Cache this — it's a big list."""
    return _make_request("GET", "/equity/metadata/instruments")


def get_exchanges() -> list[dict]:
    """Get all exchanges and their schedules."""
    return _make_request("GET", "/equity/metadata/exchanges")


def find_instrument(ticker: str, instruments: Optional[list] = None) -> Optional[dict]:
    """
    Find a T212 instrument by ticker symbol.
    T212 uses tickers like 'AAPL_US_EQ' for US equities.
    """
    if instruments is None:
        instruments = get_instruments()

    # T212 ticker format varies, try common patterns
    search_patterns = [
        f"{ticker}_US_EQ",      # Most US stocks
        f"{ticker}_EQ",         # Some variants
        ticker,                 # Direct match
    ]

    for inst in instruments:
        t212_ticker = inst.get("ticker", "")
        short_name = inst.get("shortName", "")
        for pattern in search_patterns:
            if t212_ticker == pattern or short_name == ticker:
                return inst

    return None


# ─── Pies ────────────────────────────────────────────────────────────

def get_all_pies() -> list[dict]:
    """Get all pies in the account."""
    return _make_request("GET", "/equity/pies")


def get_pie(pie_id: int) -> dict:
    """Get details for a specific pie."""
    return _make_request("GET", f"/equity/pies/{pie_id}")


def find_congress_pie() -> Optional[dict]:
    """Find our Congress tracker pie by name."""
    pies = get_all_pies()
    for pie in pies:
        if pie.get("settings", {}).get("name", "") == PIE_NAME:
            return pie
    return None


def create_pie(allocations: dict[str, float], instruments: list[dict]) -> dict:
    """
    Create a new pie with the given allocations.
    
    allocations: {"AAPL": 25.0, "NVDA": 15.0, ...} (percentages)
    instruments: Full instrument list from get_instruments()
    """
    # Convert ticker allocations to T212 instrument format
    instrument_shares = {}
    skipped = []

    for ticker, pct in allocations.items():
        inst = find_instrument(ticker, instruments)
        if inst:
            t212_ticker = inst["ticker"]
            instrument_shares[t212_ticker] = round(pct / 100, 4)  # T212 uses 0-1 not 0-100
        else:
            skipped.append(ticker)

    if skipped:
        print(f"[T212] Skipped (not available on T212): {', '.join(skipped)}")

    if not instrument_shares:
        raise ValueError("No valid instruments found for the allocation")

    # Normalise to sum to 1.0
    total = sum(instrument_shares.values())
    instrument_shares = {k: round(v / total, 4) for k, v in instrument_shares.items()}

    payload = {
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",  # Reinvest dividends
        "endDate": None,
        "goal": 0,
        "icon": "Sparkles",
        "instrumentShares": instrument_shares,
    }

    result = _make_request("POST", "/equity/pies", data=payload)
    print(f"[T212] Created pie '{PIE_NAME}' with {len(instrument_shares)} instruments")
    return result


def update_pie(pie_id: int, allocations: dict[str, float], instruments: list[dict]) -> dict:
    """
    Update an existing pie's allocations.
    
    This replaces ALL allocations — any tickers not included will be removed.
    """
    instrument_shares = {}
    skipped = []

    for ticker, pct in allocations.items():
        inst = find_instrument(ticker, instruments)
        if inst:
            t212_ticker = inst["ticker"]
            instrument_shares[t212_ticker] = round(pct / 100, 4)
        else:
            skipped.append(ticker)

    if skipped:
        print(f"[T212] Skipped (not available on T212): {', '.join(skipped)}")

    if not instrument_shares:
        raise ValueError("No valid instruments found for the allocation")

    # Normalise
    total = sum(instrument_shares.values())
    instrument_shares = {k: round(v / total, 4) for k, v in instrument_shares.items()}

    payload = {
        "name": PIE_NAME,
        "dividendCashAction": "REINVEST",
        "instrumentShares": instrument_shares,
    }

    result = _make_request("POST", f"/equity/pies/{pie_id}", data=payload)
    print(f"[T212] Updated pie with {len(instrument_shares)} instruments")
    return result


def delete_pie(pie_id: int) -> dict:
    """Delete a pie (careful!)."""
    return _make_request("DELETE", f"/equity/pies/{pie_id}")


# ─── High-Level Operations ───────────────────────────────────────────

def sync_pie(allocations: dict[str, float]) -> dict:
    """
    Sync the Congress tracker pie with new allocations.
    Creates the pie if it doesn't exist, updates if it does.
    
    Returns the pie data.
    """
    print("[T212] Syncing pie...")

    # Get instrument list (cache for the session)
    instruments = get_instruments()
    print(f"[T212] {len(instruments)} instruments available")

    # Check which tickers are available
    available = {}
    unavailable = []
    for ticker, pct in allocations.items():
        inst = find_instrument(ticker, instruments)
        if inst:
            available[ticker] = pct
        else:
            unavailable.append(ticker)

    if unavailable:
        print(f"[T212] Not available on T212: {', '.join(unavailable)}")
        # Redistribute unavailable allocation proportionally
        if available:
            total_available = sum(available.values())
            factor = 100.0 / total_available
            available = {t: round(p * factor, 2) for t, p in available.items()}

    # Find or create pie
    existing_pie = find_congress_pie()

    if existing_pie:
        pie_id = existing_pie.get("settings", {}).get("id") or existing_pie.get("id")
        print(f"[T212] Found existing pie (ID: {pie_id}), updating...")
        result = update_pie(pie_id, available, instruments)
    else:
        print("[T212] No existing pie found, creating new one...")
        result = create_pie(available, instruments)

    return result


if __name__ == "__main__":
    import sys

    if not T212_API_KEY:
        print("=" * 60)
        print("T212_API_KEY and T212_API_SECRET not set!")
        print()
        print("To set up:")
        print("1. Open the Trading 212 app")
        print("2. Go to Settings > API (beta)")
        print("3. Generate API keys")
        print("4. Set environment variables:")
        print("   export T212_API_KEY='your_key'")
        print("   export T212_API_SECRET='your_secret'")
        print()
        print("Start with DEMO mode:")
        print("   export T212_ENVIRONMENT='demo'")
        print("=" * 60)
        sys.exit(1)

    # Test connection
    try:
        info = get_account_info()
        print(f"Connected to T212: {info}")
        cash = get_account_cash()
        print(f"Cash balance: {cash}")

        instruments = get_instruments()
        print(f"Available instruments: {len(instruments)}")

        # Test finding some congress stocks
        test_tickers = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]
        for t in test_tickers:
            inst = find_instrument(t, instruments)
            if inst:
                print(f"  {t} -> {inst['ticker']} ({inst.get('name', 'N/A')})")
            else:
                print(f"  {t} -> NOT FOUND")

    except Exception as e:
        print(f"Error: {e}")
