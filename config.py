"""
Congress Trade Tracker - Configuration
=======================================
Tracks ALL trading Congress members. The portfolio is built from
everyone's trades, weighted by conviction (how many members hold it)
and volume. Re-evaluated periodically.

No curated list — the data picks the winners.
"""

import os

# ─── API Keys (use environment variables!) ───────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_API_SECRET = os.getenv("T212_API_SECRET", "")

# "demo" for paper trading, "live" for real money
T212_ENVIRONMENT = os.getenv("T212_ENVIRONMENT", "demo")
T212_BASE_URL = (
    "https://live.trading212.com/api/v0"
    if T212_ENVIRONMENT == "live"
    else "https://demo.trading212.com/api/v0"
)

# ─── Scraping ────────────────────────────────────────────────────────
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3600"))  # seconds
# Bumped from 20 to 60 — at ~12 trades/page that's ~720 trades, enough
# to actually cover the 180-day lookback at congressional volume.
SCRAPER_PAGES = int(os.getenv("SCRAPER_PAGES", "60"))

# ─── Portfolio ───────────────────────────────────────────────────────
WEIGHTING_METHOD = os.getenv("WEIGHTING_METHOD", "conviction")
# Default 2 — with 1 the filter is a no-op and single-member noise
# dominates the pie.
MIN_MEMBER_OVERLAP = int(os.getenv("MIN_MEMBER_OVERLAP", "2"))

# WHALE PICKS: Single-member trades above this $ amount bypass the
# overlap filter. This catches the suspicious one-off trades on obscure
# stocks where one member quietly drops serious money. That's where
# the real insider alpha is. Set to 0 to disable.
WHALE_TRADE_THRESHOLD = int(os.getenv("WHALE_TRADE_THRESHOLD", "50000"))

MAX_PIE_STOCKS = int(os.getenv("MAX_PIE_STOCKS", "50"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))
PIE_NAME = os.getenv("PIE_NAME", "Congress Tracker")

# Hard cap on any single position's % of the pie. Applied iteratively
# so it actually holds after renormalisation.
MAX_SINGLE_PCT = float(os.getenv("MAX_SINGLE_PCT", "15.0"))

# Skip broad ETFs (you want individual stock alpha, not index tracking)
TICKER_BLACKLIST = {
    "SPY", "QQQ", "IVV", "VOO", "VTI", "VT", "VXUS",
    "BND", "AGG", "TLT", "BNDX",
    "GLD", "SLV", "IAU",
}

# ─── Data Storage ────────────────────────────────────────────────────
DATA_DIR = os.getenv("DATA_DIR", "data")
TRADES_FILE = f"{DATA_DIR}/trades.json"
PORTFOLIO_FILE = f"{DATA_DIR}/portfolio.json"
HISTORY_FILE = f"{DATA_DIR}/history.json"
