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


# Strict: matches a token that's *exactly* TICKER:US or TICKER.X:US.
# This is what Capitol Trades puts inside <span class="issuer-ticker">,
# e.g. "AVGO:US", "BRK.B:US", "TCNNF:US".
_TICKER_TOKEN_RE = re.compile(r"^([A-Z]{1,5}(?:\.[A-Z])?):US$")

# Fallback for when the dedicated ticker span isn't found and we have
# to regex-scan free text. Requires a non-uppercase (or string-start)
# character before the ticker so we don't grab the tail of an all-caps
# company name like "IBM CORPIBM:US".
_TICKER_FALLBACK_RE = re.compile(r"(?:^|[^A-Z])([A-Z]{1,5}(?:\.[A-Z])?):US\b")


def extract_ticker_from_cell(issuer_cell):
    """Pull the US ticker out of an issuer <td>.

    Capitol Trades renders the ticker inside its own dedicated element:
        <span class="q-field issuer-ticker">AVGO:US</span>
    So the reliable approach is to find that span directly. We fall
    back to a regex on the cell's text only if the span is missing
    (e.g. if Capitol Trades changes their markup).
    """
    # Primary path — the dedicated span
    span = issuer_cell.select_one(".issuer-ticker")
    if span is not None:
        text = span.get_text(strip=True)
        m = _TICKER_TOKEN_RE.match(text)
        if m:
            return m.group(1)
        # Span exists but isn't a US ticker (e.g. AVGO:NA for a foreign
        # listing). Reject — don't fall through to the regex.
        return ""

    # Fallback: span not found, scrape from the whole cell's text.
    # Use separator so siblings don't smush.
    raw = issuer_cell.get_text("|", strip=True)
    if not raw:
        return ""
    for token in raw.split("|"):
        m = _TICKER_TOKEN_RE.match(token.strip())
        if m:
            return m.group(1)
    m = _TICKER_FALLBACK_RE.search(raw)
    if m:
        return m.group(1)
    return ""


def clean_ticker(raw):
    """Legacy text-based ticker cleaner. Kept for the test suite and
    any callers that have only a string. Prefer extract_ticker_from_cell
    when you have a BeautifulSoup element."""
    if not raw:
        return ""
    for sep in ("|", "\n", "\t"):
        if sep in raw:
            for token in raw.split(sep):
                m = _TICKER_TOKEN_RE.match(token.strip())
                if m:
                    return m.group(1)
            break
    m = _TICKER_FALLBACK_RE.search(raw)
    if m:
        return m.group(1)
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
                    ticker = extract_ticker_from_cell(issuer_el)
                    traded = traded_el.get_text(strip=True)
                    trade_type = normalise_type(type_el.get_text(strip=True))
                    size = size_el.get_text(strip=True)

                    if not ticker:
                        continue

                    # Issuer name for logging only — not used for matching
                    issuer_name_el = issuer_el.select_one(".issuer-name")
                    issuer_name = (
                        issuer_name_el.get_text(strip=True)
                        if issuer_name_el is not None
                        else issuer_el.get_text(strip=True)
                    )

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
                        "asset_description": issuer_name,
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
