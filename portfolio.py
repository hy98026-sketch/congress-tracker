"""
Portfolio Builder v2 — Improved congress trade scoring.
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

MEGA_CAPS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "BRK.B", "JPM", "V", "MA", "JNJ", "UNH", "PG", "HD", "DIS",
    "BAC", "XOM", "CVX", "ABBV", "PFE", "KO", "PEP", "MRK",
    "AVGO", "COST", "TMO", "CSCO", "ACN", "WMT", "CRM",
    "GS", "MS", "C", "WFC", "BLK", "SCHW", "AXP",
}

MAX_SINGLE_PCT = 15.0

AMOUNT_MIDPOINTS = {
    "$1,001 - $15,000": 8000, "$1,001 -": 8000,
    "$15,001 - $50,000": 32500, "$15,001 -": 32500,
    "$50,001 - $100,000": 75000, "$50,001 -": 75000,
    "$100,001 - $250,000": 175000, "$100,001 -": 175000,
    "$250,001 - $500,000": 375000, "$250,001 -": 375000,
    "$500,001 - $1,000,000": 750000, "$500,001 -": 750000,
    "$1,000,001 - $5,000,000": 3000000, "$1,000,001 -": 3000000,
    "$5,000,001 - $25,000,000": 15000000, "$5,000,001 -": 15000000,
    "$25,000,001 - $50,000,000": 37500000, "$50,000,000+": 75000000,
    "1K-15K": 8000, "1K–15K": 8000,
    "15K-50K": 32500, "15K–50K": 32500,
    "50K-100K": 75000, "50K–100K": 75000,
    "100K-250K": 175000, "100K–250K": 175000,
    "250K-500K": 375000, "250K–500K": 375000,
    "500K-1M": 750000, "500K–1M": 750000,
    "1M-5M": 3000000, "1M–5M": 3000000,
    "5M-25M": 15000000, "5M–25M": 15000000,
}


def parse_amount(raw):
    for p, v in AMOUNT_MIDPOINTS.items():
        if p in raw:
            return v
    return 8000


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


def recency_mult(date_str):
    try:
        days = (datetime.utcnow() - datetime.strptime(date_str, "%Y-%m-%d")).days
        if days <= 30: return 3.0
        if days <= 90: return 2.0
        return 1.0
    except Exception:
        return 1.0


def size_score(amt):
    if amt >= 3000000: return 100
    if amt >= 750000: return 50
    if amt >= 375000: return 25
    if amt >= 175000: return 15
    if amt >= 75000: return 10
    if amt >= 32500: return 5
    return 1


def build_portfolio(trades, lookback_days=None):
    lookback_days = lookback_days or LOOKBACK_DAYS
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    recent = [t for t in trades if t.get("date", "1970") >= cutoff and t.get("ticker") and t["type"] in ("buy", "sell")]
    if not recent:
        return _empty(lookback_days)

    recent.sort(key=lambda t: t.get("date", "1970"))

    positions = defaultdict(dict)
    sell_counts = defaultdict(int)

    for t in recent:
        member = t["politician"]
        ticker = t["ticker"]
        amt = parse_amount(t.get("amount", ""))
        if t["type"] == "buy":
            positions[member][ticker] = {"action": "buy", "amount": amt, "date": t["date"]}
        elif t["type"] == "sell":
            positions[member].pop(ticker, None)
            sell_counts[ticker] += 1

    tdata = defaultdict(lambda: {"members": set(), "score": 0, "volume": 0, "latest": "1970"})

    for member, holdings in positions.items():
        for ticker, info in holdings.items():
            if info["action"] == "buy":
                tdata[ticker]["members"].add(member)
                tdata[ticker]["volume"] += info["amount"]
                if info["date"] > tdata[ticker]["latest"]:
                    tdata[ticker]["latest"] = info["date"]
                obscure = 3.0 if ticker not in MEGA_CAPS else 1.0
                tdata[ticker]["score"] += size_score(info["amount"]) * recency_mult(info["date"]) * obscure

    for ticker, sells in sell_counts.items():
        if ticker in tdata:
            penalty = max(0.1, 1.0 - sells * 0.3)
            tdata[ticker]["score"] *= penalty

    consensus = {t: d for t, d in tdata.items() if len(d["members"]) >= MIN_MEMBER_OVERLAP}
    whale = {}
    if WHALE_TRADE_THRESHOLD > 0:
        for t, d in tdata.items():
            if len(d["members"]) == 1 and d["volume"] >= WHALE_TRADE_THRESHOLD:
                whale[t] = d

    for t in consensus: tdata[t]["tier"] = "consensus"
    for t in whale: tdata[t]["tier"] = "whale"

    eligible = {**consensus, **whale}
    if not eligible:
        return _empty(lookback_days)

    print(f"[Portfolio] Consensus: {len(consensus)}, Whale: {len(whale)}")

    ranked = sorted(eligible.items(), key=lambda x: x[1]["score"], reverse=True)[:MAX_PIE_STOCKS]
    total = sum(d["score"] for _, d in ranked)

    alloc = {}
    for ticker, d in ranked:
        pct = round((d["score"] / total) * 100, 2)
        if pct > MAX_SINGLE_PCT:
            pct = MAX_SINGLE_PCT
        if pct >= 0.5:
            alloc[ticker] = pct

    # Normalise to 100
    s = sum(alloc.values())
    if s > 0 and s != 100:
        alloc = {t: round(p / s * 100, 2) for t, p in alloc.items()}

    # Fix rounding
    diff = 100.0 - sum(alloc.values())
    if alloc and diff != 0:
        top = max(alloc, key=alloc.get)
        alloc[top] = round(alloc[top] + diff, 2)

    detail = {}
    for t in alloc:
        d = tdata[t]
        detail[t] = {
            "members": sorted(d["members"]),
            "member_count": len(d["members"]),
            "buy_volume": d["volume"],
            "latest_buy": d["latest"],
            "tier": d.get("tier", "?"),
            "score": d["score"],
            "is_obscure": t not in MEGA_CAPS,
        }

    msummary = {}
    for member, holdings in positions.items():
        tickers = [t for t, i in holdings.items() if i["action"] == "buy"]
        if tickers:
            msummary[member] = {"holdings_count": len(tickers), "tickers": sorted(tickers)}

    return {
        "allocations": alloc,
        "holdings_detail": detail,
        "member_summary": msummary,
        "metadata": {
            "method": "conviction_v2",
            "lookback_days": lookback_days,
            "total_trades": len(recent),
            "active_members": len(positions),
            "consensus_picks": len(consensus),
            "whale_picks": len(whale),
            "pie_stocks": len(alloc),
        },
        "updated_at": datetime.utcnow().isoformat(),
    }


def _empty(lookback_days):
    return {"allocations": {}, "holdings_detail": {}, "member_summary": {}, "metadata": {"lookback_days": lookback_days, "pie_stocks": 0}, "updated_at": datetime.utcnow().isoformat()}


def compare_portfolios(old, new):
    oa = old.get("allocations", {})
    na = new.get("allocations", {})
    added = {t: p for t, p in na.items() if t not in oa}
    removed = {t: p for t, p in oa.items() if t not in na}
    changed = {}
    for t in set(oa) & set(na):
        if abs(oa[t] - na[t]) > 0.5:
            changed[t] = {"old": oa[t], "new": na[t]}
    return {"added": added, "removed": removed, "changed": changed, "has_changes": bool(added or removed or changed)}
