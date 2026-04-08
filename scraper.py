"""
Congress Trade Scraper
======================
Fetches ALL congress members' trades from FMP (Financial Modeling Prep).
Free tier: 250 API calls/day — more than enough for hourly polling.
"""

import json
import os
import re
from datetime import datetime, timedelta

import requests

from config import DATA_DIR, TRADES_FILE, TICKER_BLACKLIST

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com/api/v4"

HEADERS = {
    "User-Agent": "CongressTracker/1.0",
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_existing_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    return []


def save_trades(trades):
    ensure_data_dir()
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2, default=str)


def normalise_type(raw):
    r = raw.lower().strip()
    if any(k in r for k in ("purchase", "buy")):
        return "buy"
    if any(k in r for k in ("sale", "sell")):
        return "sell"
    if "exchange" in r:
        return "exchange"
    return "other"


def clean_ticker(raw):
    t = raw.strip().upper().replace("--", "").replace(" ", "")
    if not t or t == "N/A" or len(t) > 6:
        return ""
    if not re.match(r"^[A-Z.]{1,6}$", t):
        return ""
    return t


def is_valid_stock_trade(trade):
    ticker = trade.get("ticker", "")
    if not ticker:
        return False
    if ticker in TICKER_BLACKLIST:
        return False
    desc = trade.get("asset_description", "").lower()
    skip_keywords = ["option", "bond", "fund", "note", "municipal", "treasury", "etf"]
    if any(kw in desc for kw in skip_keywords):
        return False
    return True


def fetch_fmp_senate():
    if not FMP_API_KEY:
        print("[FMP] No API key set - add FMP_API_KEY to env vars")
        return []
    trades = []
    url = f"{FMP_BASE}/senate-trading?page=0&apikey={FMP_API_KEY}"
    try:
        print("[Senate] Fetching from FMP...")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        print(f"[Senate] Raw trades: {len(raw)}")
        for t in raw:
            ticker = clean_ticker(t.get("asset", "") or t.get("ticker", ""))
            if not ticker:
                continue
            trade = {
                "source": "fmp_senate",
                "politician": (t.get("firstName", "") + " " + t.get("lastName", "")).strip(),
                "ticker": ticker,
                "type": normalise_type(t.get("type", "")),
                "date": t.get("transactionDate", ""),
                "disclosure_date": t.get("disclosureDate", ""),
                "amount": t.get("amount", ""),
                "asset_description": t.get("assetDescription", ""),
            }
            if is_valid_stock_trade(trade):
                trades.append(trade)
    except requests.RequestException as e:
        print(f"[Senate] Error: {e}")
    print(f"[Senate] Valid stock trades: {len(trades)}")
    return trades


def fetch_fmp_house():
    if not FMP_API_KEY:
        print("[FMP] No API key set - add FMP_API_KEY to env vars")
        return []
    trades = []
    url = f"{FMP_BASE}/senate-trading-rss-feed?page=0&apikey={FMP_API_KEY}"
    try:
        print("[House] Fetching from FMP...")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        print(f"[House] Raw trades: {len(raw)}")
        for t in raw:
            ticker = clean_ticker(t.get("asset", "") or t.get("ticker", ""))
            if not ticker:
                continue
            trade = {
                "source": "fmp_house",
                "politician": (t.get("firstName", "") + " " + t.get("lastName", "")).strip(),
                "ticker": ticker,
                "type": normalise_type(t.get("type", "")),
                "date": t.get("transactionDate", ""),
                "disclosure_date": t.get("disclosureDate", ""),
                "amount": t.get("amount", ""),
                "asset_description": t.get("assetDescription", ""),
            }
            if is_valid_stock_trade(trade):
                trades.append(trade)
    except requests.RequestException as e:
        print(f"[House] Error: {e}")
    print(f"[House] Valid stock trades: {len(trades)}")
    return trades


def fetch_all_trades():
    all_trades = []
    all_trades.extend(fetch_fmp_senate())
    all_trades.extend(fetch_fmp_house())
    all_trades.sort(key=lambda t: t.get("date", "1970-01-01"), reverse=True)
    members = {t["politician"] for t in all_trades}
    tickers = {t["ticker"] for t in all_trades}
    print(f"\n[Total] {len(all_trades)} trades from {len(members)} members across {len(tickers)} tickers")
    return all_trades


def get_recent_trades(trades, days=90):
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [t for t in trades if t.get("date", "9999") >= cutoff]
