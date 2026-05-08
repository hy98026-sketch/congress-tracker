"""
Congress Trade Scraper
======================
Scrapes Capitol Trades (capitoltrades.com) for ALL congress trades.
No API key needed — free public data.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, TRADES_FILE, TICKER_BLACKLIST, SCRAPER_PAGES

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    ),
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


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
    return "other"


# Match TICKER:US or TICKER.SUFFIX:US (e.g. BRK.B:US).
# Anything without the :US country code is rejected — this is what
# was letting European listings (VASML, LCSTE etc.) and fund share
# classes through and polluting the pie.
_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z])?):US\b")


def clean_ticker(raw):
    if not raw:
        return ""
    match = _TICKER_RE.search(raw)
    if match:
        return match.group(1)
    return ""


def is_valid_stock_trade(trade):
    ticker = trade.get("ticker", "")
    if not ticker or ticker in TICKER_BLACKLIST:
        return False
    return True


def scrape_capitol_trades(pages=None):
    """Scrape recent trades from Capitol Trades website."""
    if pages is None:
        pages = SCRAPER_PAGES

    all_trades = []
    base_url = "https://www.capitoltrades.com/trades"

    for page in range(1, pages + 1):
        try:
            url = f"{base_url}?page={page}" if page > 1 else base_url
            print(f"[Capitol Trades] Fetching page {page}...")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table tbody tr")

            if not rows:
                print(f"[Capitol Trades] No rows found on page {page}, stopping")
                break

            page_valid = 0
            for row in rows:
                cells = row.select("td")
                if len(cells) < 8:
                    continue

                try:
                    politician_el = cells[0]
                    issuer_el = cells[1]
                    traded_el = cells[3]
                    type_el = cells[6]
                    size_el = cells[7]

                    politician = politician_el.get_text(strip=True)
                    issuer_text = issuer_el.get_text(strip=True)
                    ticker = clean_ticker(issuer_text)
                    traded = traded_el.get_text(strip=True)
                    trade_type = normalise_type(type_el.get_text(strip=True))
                    size = size_el.get_text(strip=True)

                    if not ticker:
                        continue

                    # Clean politician name (remove party/state suffix)
                    politician = re.sub(
                        r"(Republican|Democrat|Independent)(Senate|House)[A-Z]{2}$",
                        "",
                        politician,
                    ).strip()

                    trade = {
                        "source": "capitol_trades",
                        "politician": politician,
                        "ticker": ticker,
                        "type": trade_type,
                        "date": _parse_date(traded),
                        "amount": size,
                        "asset_description": issuer_text,
                    }

                    if is_valid_stock_trade(trade):
                        all_trades.append(trade)
                        page_valid += 1
                except (IndexError, AttributeError):
                    continue

            print(f"[Capitol Trades] Page {page}: {len(rows)} rows, {page_valid} valid US trades")

        except requests.RequestException as e:
            print(f"[Capitol Trades] Error on page {page}: {e}")
            break

    print(f"[Capitol Trades] Total valid trades: {len(all_trades)}")
    return all_trades


def _parse_date(date_str):
    """Parse Capitol Trades date format into YYYY-MM-DD."""
    date_str = date_str.strip()
    try:
        clean = " ".join(date_str.split())
        for fmt in ["%d %b %Y", "%d %B %Y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass
    return date_str


def fetch_all_trades():
    all_trades = scrape_capitol_trades()
    all_trades.sort(key=lambda t: t.get("date", "1970-01-01"), reverse=True)
    members = {t["politician"] for t in all_trades}
    tickers = {t["ticker"] for t in all_trades}
    print(f"\n[Total] {len(all_trades)} trades from {len(members)} members across {len(tickers)} tickers")
    return all_trades


def get_recent_trades(trades, days=90):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return [t for t in trades if t.get("date", "9999") >= cutoff]
