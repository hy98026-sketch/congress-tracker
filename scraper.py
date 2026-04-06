"""
Congress Trade Scraper
======================
Fetches ALL congress members' trades from free public APIs:
  1. House Stock Watcher (S3 JSON dump — all House trades)
  2. Senate Stock Watcher (S3 JSON dump — all Senate trades)

No filtering by member — we grab everything and let the portfolio
builder decide what makes it into the pie.
"""

import json
import os
import re
from datetime import datetime, timedelta

import requests

from config import DATA_DIR, TRADES_FILE, TICKER_BLACKLIST


HOUSE_API = (
    "https://house-stock-watcher-data.s3-us-west-2"
    ".amazonaws.com/data/all_transactions.json"
)
SENATE_API = (
    "https://senate-stock-watcher-data.s3-us-west-2"
    ".amazonaws.com/aggregate/all_transactions.json"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    ),
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_existing_trades() -> list[dict]:
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    return []


def save_trades(trades: list[dict]):
    ensure_data_dir()
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2, default=str)


# ─── Normalisation ───────────────────────────────────────────────────

def normalise_type(raw: str) -> str:
    """Normalise trade type to 'buy', 'sell', or 'other'."""
    r = raw.lower().strip()
    if any(k in r for k in ("purchase", "buy")):
        return "buy"
    if any(k in r for k in ("sale_full", "sale_partial", "sale", "sell")):
        return "sell"
    if "exchange" in r:
        return "exchange"
    return "other"


def clean_ticker(raw: str) -> str:
    """Clean ticker symbol — strip whitespace, dashes, known junk."""
    t = raw.strip().upper().replace("--", "").replace(" ", "")
    # Remove anything after a dot (e.g. BRK.B -> BRK is wrong, keep BRK.B)
    # Actually keep dots for class shares
    if not t or t == "N/A" or len(t) > 6:
        return ""
    # Must be letters (and optionally a dot for class shares)
    if not re.match(r"^[A-Z.]{1,6}$", t):
        return ""
    return t


def is_valid_stock_trade(trade: dict) -> bool:
    """Filter out non-stock trades, blacklisted tickers, etc."""
    ticker = trade.get("ticker", "")
    if not ticker:
        return False
    if ticker in TICKER_BLACKLIST:
        return False
    # Skip if asset description mentions options, bonds, funds
    desc = trade.get("asset_description", "").lower()
    skip_keywords = ["option", "bond", "fund", "note", "municipal", "treasury", "etf"]
    if any(kw in desc for kw in skip_keywords):
        return False
    return True


# ─── House Stock Watcher ─────────────────────────────────────────────

def fetch_house_trades() -> list[dict]:
    """Fetch ALL House member trades."""
    trades = []
    try:
        print("[House] Fetching all transactions...")
        resp = requests.get(HOUSE_API, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        print(f"[House] Raw trades: {len(raw)}")

        for t in raw:
            ticker = clean_ticker(t.get("ticker", ""))
            if not ticker:
                continue

            trade = {
                "source": "house",
                "politician": t.get("representative", "Unknown"),
                "ticker": ticker,
                "type": normalise_type(t.get("type", "")),
                "date": t.get("transaction_date", ""),
                "disclosure_date": t.get("disclosure_date", ""),
                "amount": t.get("amount", ""),
                "asset_description": t.get("asset_description", ""),
            }

            if is_valid_stock_trade(trade):
                trades.append(trade)

    except requests.RequestException as e:
        print(f"[House] Error: {e}")
    except json.JSONDecodeError as e:
        print(f"[House] JSON error: {e}")

    print(f"[House] Valid stock trades: {len(trades)}")
    return trades


# ─── Senate Stock Watcher ────────────────────────────────────────────

def fetch_senate_trades() -> list[dict]:
    """Fetch ALL Senate member trades."""
    trades = []
    try:
        print("[Senate] Fetching all transactions...")
        resp = requests.get(SENATE_API, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        print(f"[Senate] Raw trades: {len(raw)}")

        for t in raw:
            ticker = clean_ticker(t.get("ticker", ""))
            if not ticker:
                continue

            name = f"{t.get('first_name', '')} {t.get('last_name', '')}".strip()

            trade = {
                "source": "senate",
                "politician": name or "Unknown",
                "ticker": ticker,
                "type": normalise_type(t.get("type", "")),
                "date": t.get("transaction_date", ""),
                "disclosure_date": t.get("disclosure_date", ""),
                "amount": t.get("amount", ""),
                "asset_description": t.get("asset_description", ""),
            }

            if is_valid_stock_trade(trade):
                trades.append(trade)

    except requests.RequestException as e:
        print(f"[Senate] Error: {e}")
    except json.JSONDecodeError as e:
        print(f"[Senate] JSON error: {e}")

    print(f"[Senate] Valid stock trades: {len(trades)}")
    return trades


# ─── Combined ────────────────────────────────────────────────────────

def fetch_all_trades() -> list[dict]:
    """Fetch from all sources, merge, sort by date."""
    all_trades = []
    all_trades.extend(fetch_house_trades())
    all_trades.extend(fetch_senate_trades())

    # Sort newest first
    all_trades.sort(key=lambda t: t.get("date", "1970-01-01"), reverse=True)

    # Summary
    members = {t["politician"] for t in all_trades}
    tickers = {t["ticker"] for t in all_trades}
    print(f"\n[Total] {len(all_trades)} trades from {len(members)} members across {len(tickers)} tickers")

    return all_trades


def get_recent_trades(trades: list[dict], days: int = 90) -> list[dict]:
    """Filter to last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [t for t in trades if t.get("date", "9999") >= cutoff]


if __name__ == "__main__":
    trades = fetch_all_trades()
    save_trades(trades)

    recent = get_recent_trades(trades, days=90)
    print(f"\nLast 90 days: {len(recent)} trades")

    # Top traded tickers
    from collections import Counter
    ticker_counts = Counter(t["ticker"] for t in recent if t["type"] == "buy")
    print("\nTop 20 bought tickers (last 90 days):")
    for ticker, count in ticker_counts.most_common(20):
        print(f"  {ticker:6s} — {count} buy trades")
