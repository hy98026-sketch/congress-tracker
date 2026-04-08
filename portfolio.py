"""
Portfolio Builder — v2
======================
Improved scoring algorithm based on analysis of actual congress trading patterns.

KEY IMPROVEMENTS:
  1. OBSCURE STOCK BONUS: Non-mega-cap stocks get 3x score. That's where
     the insider alpha is — not NVDA/AAPL that everyone buys.
  2. TRADE SIZE WEIGHTING: $500K trade scores way more than $1K trade.
  3. RECENCY DECAY: Trades from last 30 days score 3x more than 90+ day old.
  4. SELL PENALTY: If members are selling a stock, it gets penalised.

TWO-TIER SYSTEM:
  Tier 1 — CONSENSUS: 2+ members buying the same stock.
  Tier 2 — WHALE: Single member drops $50K+ on a stock.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

from config import (
    WEIGHTING_METHOD,
    MIN_MEMBER_OVERLAP,
    WHALE_TRADE_THRESHOLD,
    MAX_PIE_STOCKS,
    LOOKBACK_DAYS,
    DATA_DIR,
    PORTFOLIO_FILE,
    HISTORY_FILE,
)


# ─── Mega-caps that everyone buys (low alpha signal) ─────────────────
# These are the most commonly traded stocks by Congress — basically
# index tracking. They still get included but at reduced weight.
MEGA_CAPS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "BRK.B", "JPM", "V", "MA", "JNJ", "UNH", "PG", "HD", "DIS",
    "BAC", "XOM", "CVX", "ABBV", "PFE", "KO", "PEP", "MRK",
    "AVGO", "COST", "TMO", "CSCO", "ACN", "WMT", "CRM",
}

# ─── Amount Parsing ──────────────────────────────────────────────────

AMOUNT_MIDPOINTS = {
    "$1,001 - $15,000": 8_000,
    "$1,001 -": 8_000,
    "$15,001 - $50,000": 32_500,
    "$15,001 -": 32_500,
    "$50,001 - $100,000": 75_000,
    "$50,001 -": 75_000,
    "$100,001 - $250,000": 175_000,
    "$100,001 -": 175_000,
    "$250,001 - $500,000": 375_000,
    "$250,001 -": 375_000,
    "$500,001 - $1,000,000": 750_000,
    "$500,001 -": 750_000,
    "$1,000,001 - $5,000,000": 3_000_000,
    "$1,000,001 -": 3_000_000,
    "$5,000,001 - $25,000,000": 15_000_000,
    "$5,000,001 -": 15_000_000,
    "$25,000,001 - $50,000,000": 37_500_000,
    "$50,000,000+": 75_000_000,
    "1K-15K": 8_000,
    "1K–15K": 8_000,
    "15K-50K": 32_500,
    "15K–50K": 32_500,
    "50K-100K": 75_000,
    "50K–100K": 75_000,
    "100K-250K": 175_000,
    "100K–250K": 175_000,
    "250K-500K": 375_000,
    "250K–500K": 375_000,
    "500K-1M": 750_000,
    "500K–1M": 750_000,
    "1M-5M": 3_000_000,
    "1M–5M": 3_000_000,
    "5M-25M": 15_000_000,
    "5M–25M": 15_000_000,
}


def parse_amount(raw):
    for pattern, midpoint in AMOUNT_MIDPOINTS.items():
        if pattern in raw:
            return midpoint
    return 8_000


# ─── Persistence ─────────────────────────────────────────────────────

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return {}


def save_portfolio(portfolio):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)


def save_history(entry):
    os.makedirs(DATA_DIR, exist_ok=True)
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    history.append(entry)
    history = history[-365:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


# ─── Scoring Helpers ─────────────────────────────────────────────────

def recency_multiplier(trade_date_str):
    """Recent trades score higher. Last 30 days = 3x, 30-90 = 2x, 90+ = 1x."""
    try:
        trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d")
        days_ago = (datetime.utcnow() - trade_date).days
        if days_ago <= 30:
            return 3.0
        elif days_ago <= 90:
            return 2.0
        else:
            return 1.0
    except (ValueError, TypeError):
        return 1.0


def size_score(amount):
    """
    Trade size scoring — exponential, not linear.
    $1K trade = 1 point, $100K = 10, $500K = 25, $1M+ = 50.
    """
    if amount >= 3_000_000:
        return 100
    elif amount >= 750_000:
        return 50
    elif amount >= 375_000:
        return 25
    elif amount >= 175_000:
        return 15
    elif amount >= 75_000:
        return 10
    elif amount >= 32_500:
        return 5
    else:
        return 1


def obscurity_multiplier(ticker):
    """
    Non-mega-cap stocks get a 3x bonus.
    Everyone buying NVDA is index tracking. One person buying
    a random defence contractor — that's the insider signal.
    """
    if ticker in MEGA_CAPS:
        return 1.0
    return 3.0


# ─── Portfolio Construction ──────────────────────────────────────────

def build_portfolio(trades, lookback_days=None):
    lookback_days = lookback_days or LOOKBACK_DAYS
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    recent = [
        t for t in trades
        if t.get("date", "1970") >= cutoff
        and t.get("ticker")
        and t["type"] in ("buy", "sell")
    ]

    if not recent:
        return _empty_portfolio(lookback_days)

    # Sort oldest first so latest trade per ticker wins
    recent.sort(key=lambda t: t.get("date", "1970"))

    # ── Step 1: Build positions + track sells ──
    positions = defaultdict(dict)
    sell_counts = defaultdict(int)  # How many members are selling each ticker

    for t in recent:
        member = t["politician"]
        ticker = t["ticker"]
        amount = parse_amount(t.get("amount", ""))

        if t["type"] == "buy":
            positions[member][ticker] = {
                "action": "buy",
                "amount": amount,
                "date": t["date"],
            }
        elif t["type"] == "sell":
            positions[member].pop(ticker, None)
            sell_counts[ticker] += 1

    # ── Step 2: Aggregate with improved scoring ──
    ticker_data = defaultdict(lambda: {
        "members": set(),
        "total_score": 0,
        "buy_volume": 0,
        "latest_buy": "1970-01-01",
    })

    for member, holdings in positions.items():
        for ticker, info in holdings.items():
            if info["action"] == "buy":
                ticker_data[ticker]["members"].add(member)
                ticker_data[ticker]["buy_volume"] += info["amount"]
                if info["date"] > ticker_data[ticker]["latest_buy"]:
                    ticker_data[ticker]["latest_buy"] = info["date"]

                # Calculate this holding's score
                trade_score = (
                    size_score(info["amount"])
                    * recency_multiplier(info["date"])
                    * obscurity_multiplier(ticker)
                )
                ticker_data[ticker]["total_score"] += trade_score

    # ── Step 3: Apply sell penalty ──
    for ticker in sell_counts:
        if ticker in ticker_data:
            sells = sell_counts[ticker]
            # Each sell reduces score by 30%
            penalty = max(0.1, 1.0 - (sells * 0.3))
            ticker_data[ticker]["total_score"] *= penalty
            print(f"[Portfolio] {ticker} sell penalty: {sells} sells, score x{penalty:.1f}")

    # ── Step 4: Two-tier filtering ──
    consensus = {
        t: d for t, d in ticker_data.items()
        if len(d["members"]) >= MIN_MEMBER_OVERLAP
    }

    whale = {}
    if WHALE_TRADE_THRESHOLD > 0:
        for t, d in ticker_data.items():
            if len(d["members"]) == 1 and d["buy_volume"] >= WHALE_TRADE_THRESHOLD:
                whale[t] = d

    for t in consensus:
        ticker_data[t]["tier"] = "consensus"
    for t in whale:
        ticker_data[t]["tier"] = "whale"

    eligible = {**consensus, **whale}

    if not eligible:
        print("[Portfolio] No qualifying tickers")
        return _empty_portfolio(lookback_days)

    print(f"[Portfolio] Consensus picks: {len(consensus)}, Whale picks: {len(whale)}")

    # ── Step 5: Score using the improved total_score ──
    scores = {}
    for t, d in eligible.items():
        scores[t] = d["total_score"]

    # ── Step 6: Top N, normalise to 100% ──
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = ranked[:MAX_PIE_STOCKS]

    total_score = sum(s for _, s in top)
    allocations = {}
    for ticker, score in top:
        pct = round((score / total_score) * 100, 2)
        if pct >= 0.5:
            allocations[ticker] = pct

    # Fix rounding
    if allocations:
        diff = 100.0 - sum(allocations.values())
        biggest = max(allocations, key=allocations.get)
        allocations[biggest] = round(allocations[biggest] + diff, 2)

    # ── Build detail ──
    holdings_detail = {}
    for t in allocations:
        d = ticker_data[t]
        holdings_detail[t] = {
            "members": sorted(d["members"]),
            "member_count": len(d["members"]),
            "buy_volume": d["buy_volume"],
            "latest_buy": d["latest_buy"],
            "tier": d.get("tier", "unknown"),
            "score": d["total_score"],
            "is_obscure": t not in MEGA_CAPS,
        }

    member_summary = {}
    for member, holdings in positions.items():
        tickers = [t for t, info in holdings.items() if info["action"] == "buy"]
        if tickers:
            member_summary[member] = {
                "holdings_count": len(tickers),
                "tickers": sorted(tickers),
            }

    return {
        "allocations": allocations,
        "holdings_detail": holdings_detail,
        "member_summary": member_summary,
        "metadata": {
            "method": "conviction_v2",
            "lookback_days": lookback_days,
            "total_trades": len(recent),
            "active_members": len(positions),
            "unique_tickers": len(ticker_data),
            "consensus_picks": len(consensus),
            "whale_picks": len(whale),
            "pie_stocks": len(allocations),
        },
        "updated_at": datetime.utcnow().isoformat(),
    }


def _empty_portfolio(lookback_days):
    return {
        "allocations": {},
        "holdings_detail": {},
        "member_summary": {},
        "metadata": {"lookback_days": lookback_days, "pie_stocks": 0},
        "updated_at": datetime.utcnow().isoformat(),
    }


def compare_portfolios(old, new):
    old_a = old.get("allocations", {})
    new_a = new.get("allocations", {})

    added = {t: p for t, p in new_a.items() if t not in old_a}
    removed = {t: p for t, p in old_a.items() if t not in new_a}
    changed = {}
    for t in set(old_a) & set(new_a):
        if abs(old_a[t] - new_a[t]) > 0.5:
            changed[t] = {"old": old_a[t], "new": new_a[t]}

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "has_changes": bool(added or removed or changed),
    }
