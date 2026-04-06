"""
Portfolio Builder
=================
Builds a pie allocation from ALL congress members' trades.

TWO-TIER SYSTEM:
  Tier 1 — CONSENSUS PICKS: 2+ members buying the same stock.
           High weight. These are the "everyone knows" plays.
  Tier 2 — WHALE PICKS: A single member drops $100K+ on a stock
           nobody else is buying. Lower weight but included. This
           catches the suspicious one-off trades on obscure stocks
           where the real insider money is made.

Workflow:
  1. Take all trades from the lookback period
  2. Figure out who's holding what (last trade = buy → holding)
  3. Tier 1: score by member count. Tier 2: score by volume.
  4. Combine, take top N, normalise to 100%
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


# ─── Amount Parsing ──────────────────────────────────────────────────
# STOCK Act disclosures give ranges, not exact amounts

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
}


def parse_amount(raw: str) -> float:
    for pattern, midpoint in AMOUNT_MIDPOINTS.items():
        if pattern in raw:
            return midpoint
    return 8_000  # default to smallest


# ─── Persistence ─────────────────────────────────────────────────────

def load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return {}


def save_portfolio(portfolio: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)


def save_history(entry: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    history.append(entry)
    # Keep last 365 entries max
    history = history[-365:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


# ─── Portfolio Construction ──────────────────────────────────────────

def build_portfolio(trades: list[dict], lookback_days: int = None) -> dict:
    """
    Build portfolio from ALL members' trades.

    Returns:
    {
        "allocations": {"NVDA": 8.5, "AAPL": 6.2, ...},
        "holdings_detail": {
            "NVDA": {
                "members": ["Pelosi", "Tuberville", ...],
                "member_count": 15,
                "buy_volume": 45000000,
                "latest_buy": "2026-03-15"
            }
        },
        "member_summary": {
            "Nancy Pelosi": {"trades": 19, "tickers": ["NVDA", "AAPL", ...]}
        },
        "metadata": {...},
        "updated_at": "..."
    }
    """
    lookback_days = lookback_days or LOOKBACK_DAYS
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # Filter to recent trades with valid tickers
    recent = [
        t for t in trades
        if t.get("date", "1970") >= cutoff
        and t.get("ticker")
        and t["type"] in ("buy", "sell")
    ]

    if not recent:
        return _empty_portfolio(lookback_days)

    # ── Step 1: Build each member's current positions ──
    # Sort oldest→newest so the latest trade per ticker wins
    recent.sort(key=lambda t: t.get("date", "1970"))

    # member → {ticker → latest_trade_info}
    positions = defaultdict(dict)

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
            # Remove position on any sell. We don't know exact sizes
            # from STOCK Act disclosures, so it's safest to assume
            # they're reducing/exiting. If they still hold shares and
            # buy more later, that buy will re-add the position.
            positions[member].pop(ticker, None)

    # ── Step 2: Aggregate across all members ──
    ticker_data = defaultdict(lambda: {
        "members": set(),
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

    # ── Step 3: Two-tier filtering ──
    # Tier 1 — CONSENSUS: multiple members buying (high confidence)
    consensus = {
        t: d for t, d in ticker_data.items()
        if len(d["members"]) >= MIN_MEMBER_OVERLAP
    }

    # Tier 2 — WHALE: single member, but big trade (suspicious/high conviction)
    # These are the obscure picks where one person quietly drops serious money
    whale = {}
    if WHALE_TRADE_THRESHOLD > 0:
        for t, d in ticker_data.items():
            if len(d["members"]) == 1 and d["buy_volume"] >= WHALE_TRADE_THRESHOLD:
                whale[t] = d

    # Tag tiers for detail output
    for t in consensus:
        ticker_data[t]["tier"] = "consensus"
    for t in whale:
        ticker_data[t]["tier"] = "whale"

    eligible = {**consensus, **whale}

    if not eligible:
        print(f"[Portfolio] No qualifying tickers")
        return _empty_portfolio(lookback_days)

    print(f"[Portfolio] Consensus picks: {len(consensus)}, Whale picks: {len(whale)}")

    # ── Step 4: Score and weight ──
    # Consensus picks score much higher than whale picks, so the pie
    # is mostly stable consensus stocks with a smaller allocation to
    # the high-risk/high-reward whale picks.
    method = WEIGHTING_METHOD

    scores = {}
    if method == "conviction":
        for t, d in eligible.items():
            mc = len(d["members"])
            vol_score = min(d["buy_volume"] / 1_000_000, 10)

            if t in consensus:
                # Consensus: member count is the primary driver
                scores[t] = mc * 10 + vol_score
            else:
                # Whale: volume is the signal (bigger bet = more conviction)
                # Score of ~5-8 means whale picks get roughly the weight
                # of a 1-member consensus pick — present but not dominant
                scores[t] = 5 + vol_score

    elif method == "volume":
        scores = {t: d["buy_volume"] for t, d in eligible.items()}

    elif method == "equal":
        scores = {t: 1.0 for t in eligible}

    else:
        scores = {t: 1.0 for t in eligible}

    # ── Step 5: Top N, normalise to 100% ──
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = ranked[:MAX_PIE_STOCKS]

    total_score = sum(s for _, s in top)
    allocations = {}
    for ticker, score in top:
        pct = round((score / total_score) * 100, 2)
        if pct >= 0.5:  # T212 minimum
            allocations[ticker] = pct

    # Fix rounding to exactly 100%
    if allocations:
        diff = 100.0 - sum(allocations.values())
        biggest = max(allocations, key=allocations.get)
        allocations[biggest] = round(allocations[biggest] + diff, 2)

    # ── Build detail & summary ──
    holdings_detail = {}
    for t in allocations:
        d = ticker_data[t]
        holdings_detail[t] = {
            "members": sorted(d["members"]),
            "member_count": len(d["members"]),
            "buy_volume": d["buy_volume"],
            "latest_buy": d["latest_buy"],
            "tier": d.get("tier", "unknown"),
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
            "method": method,
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


def _empty_portfolio(lookback_days: int) -> dict:
    return {
        "allocations": {},
        "holdings_detail": {},
        "member_summary": {},
        "metadata": {"lookback_days": lookback_days, "pie_stocks": 0},
        "updated_at": datetime.utcnow().isoformat(),
    }


def compare_portfolios(old: dict, new: dict) -> dict:
    """Diff two portfolios — what changed?"""
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
