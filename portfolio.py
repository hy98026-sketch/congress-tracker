"""
Portfolio Builder v2 — Improved congress trade scoring.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from config import (
    WEIGHTING_METHOD,
    MIN_MEMBER_OVERLAP,
    WHALE_TRADE_THRESHOLD,
    MAX_PIE_STOCKS,
    LOOKBACK_DAYS,
    MAX_SINGLE_PCT,
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


def _utcnow():
    return datetime.now(timezone.utc)


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
    """Append a history entry, but skip if the last entry is < 24h old.
    With hourly polling we'd otherwise blow through the 365-cap in 15 days."""
    os.makedirs(DATA_DIR, exist_ok=True)
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)

    # De-dupe within 24h
    if history:
        try:
            last_ts = datetime.fromisoformat(history[-1]["timestamp"].replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            new_ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if new_ts.tzinfo is None:
                new_ts = new_ts.replace(tzinfo=timezone.utc)
            if (new_ts - last_ts).total_seconds() < 23 * 3600 and not entry.get("has_changes"):
                # Update the last entry instead of adding a new one
                history[-1] = entry
                with open(HISTORY_FILE, "w") as f:
                    json.dump(history, f, indent=2, default=str)
                return
        except (ValueError, KeyError):
            pass

    history.append(entry)
    history = history[-365:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def recency_mult(date_str):
    try:
        days = (_utcnow() - datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
        # Bands shifted out to account for the 45-day STOCK Act
        # reporting lag — "30 days old" trade is often brand-new info
        # from our point of view.
        if days <= 60: return 3.0
        if days <= 120: return 2.0
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


def _apply_cap(scores, cap_pct, max_iter=20):
    """Iteratively cap any single score's % at cap_pct, redistributing
    the excess proportionally to uncapped names. Returns dict of
    ticker -> %, summing to 100."""
    if not scores:
        return {}
    total = sum(scores.values())
    if total <= 0:
        return {}
    pcts = {t: (s / total) * 100 for t, s in scores.items()}

    for _ in range(max_iter):
        over = {t: p for t, p in pcts.items() if p > cap_pct + 0.001}
        if not over:
            break
        excess = sum(p - cap_pct for p in over.values())
        for t in over:
            pcts[t] = cap_pct
        # Redistribute to under-cap names, weighted by their current %
        under = {t: p for t, p in pcts.items() if p < cap_pct - 0.001}
        under_total = sum(under.values())
        if under_total <= 0:
            # Everything is capped — flat distribute the leftover
            # (shouldn't really happen unless cap * n_stocks < 100)
            break
        for t, p in under.items():
            pcts[t] = p + excess * (p / under_total)

    return pcts


def build_portfolio(trades, lookback_days=None):
    lookback_days = lookback_days or LOOKBACK_DAYS
    cutoff = (_utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    recent = [
        t for t in trades
        if t.get("date", "1970") >= cutoff
        and t.get("ticker")
        and t["type"] in ("buy", "sell")
    ]
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

    # Penalty for tickers that have been sold (other members exiting
    # is bearish signal)
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

    for t in consensus:
        tdata[t]["tier"] = "consensus"
    for t in whale:
        tdata[t]["tier"] = "whale"

    eligible = {**consensus, **whale}
    if not eligible:
        return _empty(lookback_days, total_trades=len(recent),
                      active_members=len(positions),
                      unique_tickers=len(tdata))

    print(f"[Portfolio] Consensus: {len(consensus)}, Whale: {len(whale)}")

    # Rank by score and take top N
    ranked = sorted(eligible.items(), key=lambda x: x[1]["score"], reverse=True)[:MAX_PIE_STOCKS]
    score_map = {t: d["score"] for t, d in ranked}

    # Apply iterative cap so no single position exceeds MAX_SINGLE_PCT
    pcts = _apply_cap(score_map, MAX_SINGLE_PCT)

    # Drop sub-0.5% positions (T212 doesn't really do tiny allocations)
    alloc = {t: round(p, 2) for t, p in pcts.items() if p >= 0.5}

    # Renormalise after dropping small positions, then re-cap (the
    # drop can push other positions higher).
    if alloc:
        s = sum(alloc.values())
        if s > 0 and abs(s - 100) > 0.01:
            alloc = {t: p / s * 100 for t, p in alloc.items()}
            alloc = _apply_cap(alloc, MAX_SINGLE_PCT)
            alloc = {t: round(p, 2) for t, p in alloc.items()}

        # Fix rounding drift to land exactly on 100
        diff = round(100.0 - sum(alloc.values()), 2)
        if diff != 0:
            # Add the diff to the largest position that has room under the cap
            for t in sorted(alloc, key=alloc.get, reverse=True):
                if alloc[t] + diff <= MAX_SINGLE_PCT + 0.01:
                    alloc[t] = round(alloc[t] + diff, 2)
                    break

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
            "weighting": WEIGHTING_METHOD,
            "lookback_days": lookback_days,
            "total_trades": len(recent),
            "active_members": len(positions),
            "unique_tickers": len(tdata),
            "eligible_tickers": len(eligible),
            "consensus_picks": len(consensus),
            "whale_picks": len(whale),
            "pie_stocks": len(alloc),
        },
        "updated_at": _utcnow().isoformat(),
    }


def _empty(lookback_days, total_trades=0, active_members=0, unique_tickers=0):
    return {
        "allocations": {},
        "holdings_detail": {},
        "member_summary": {},
        "metadata": {
            "method": "conviction_v2",
            "weighting": WEIGHTING_METHOD,
            "lookback_days": lookback_days,
            "total_trades": total_trades,
            "active_members": active_members,
            "unique_tickers": unique_tickers,
            "eligible_tickers": 0,
            "consensus_picks": 0,
            "whale_picks": 0,
            "pie_stocks": 0,
        },
        "updated_at": _utcnow().isoformat(),
    }


def compare_portfolios(old, new):
    oa = old.get("allocations", {})
    na = new.get("allocations", {})
    added = {t: p for t, p in na.items() if t not in oa}
    removed = {t: p for t, p in oa.items() if t not in na}
    changed = {}
    for t in set(oa) & set(na):
        if abs(oa[t] - na[t]) > 0.5:
            changed[t] = {"old": oa[t], "new": na[t]}
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "has_changes": bool(added or removed or changed),
    }
