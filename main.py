"""
Congress Trade Tracker — Main Loop
====================================
  python main.py              # Run once (dry run if no T212 keys)
  python main.py --loop       # Continuous (for Railway)
  python main.py --dry-run    # Never touch T212
"""

import sys
import time
import traceback
from datetime import datetime, timezone

from config import POLL_INTERVAL, T212_API_KEY
from scraper import fetch_all_trades, save_trades, get_recent_trades
from portfolio import (
    build_portfolio,
    compare_portfolios,
    load_portfolio,
    save_portfolio,
    save_history,
)
from notifier import (
    notify_new_trades,
    notify_portfolio_update,
    notify_pie_synced,
    notify_error,
    notify_startup,
)


def _utcnow():
    return datetime.now(timezone.utc)


def run_cycle(dry_run: bool = False):
    ts = _utcnow().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  Cycle start: {ts}")
    print(f"{'='*60}")

    # 1 — Fetch
    print("\n[1/4] Fetching trades...")
    all_trades = fetch_all_trades()
    save_trades(all_trades)

    if not all_trades:
        print("  No trades found. Sources may be down.")
        return

    # 2 — Build portfolio
    print("\n[2/4] Building portfolio...")
    new_portfolio = build_portfolio(all_trades)
    meta = new_portfolio["metadata"]

    print(f"  Active members:   {meta.get('active_members', 0)}")
    print(f"  Unique tickers:   {meta.get('unique_tickers', 0)}")
    print(f"  Eligible tickers: {meta.get('eligible_tickers', 0)}")
    print(f"  Consensus picks:  {meta.get('consensus_picks', 0)}")
    print(f"  Whale picks:      {meta.get('whale_picks', 0)}")
    print(f"  Pie stocks:       {meta.get('pie_stocks', 0)}")

    if not new_portfolio["allocations"]:
        print("  Empty portfolio. Skipping.")
        return

    # Show top 10
    top10 = sorted(
        new_portfolio["allocations"].items(), key=lambda x: x[1], reverse=True
    )[:10]
    print("\n  Top 10 allocations:")
    for ticker, pct in top10:
        detail = new_portfolio["holdings_detail"].get(ticker, {})
        mc = detail.get("member_count", 0)
        tier = detail.get("tier", "?")
        print(f"    {ticker:6s} {pct:5.1f}%  ({mc} members, {tier})")

    # 3 — Diff with previous
    print("\n[3/4] Comparing with previous...")
    old_portfolio = load_portfolio()
    changes = compare_portfolios(old_portfolio, new_portfolio)

    if changes["has_changes"]:
        added = list(changes["added"].keys())
        removed = list(changes["removed"].keys())
        changed = list(changes["changed"].keys())
        print(f"  Added:   {added[:10]}")
        print(f"  Removed: {removed[:10]}")
        print(f"  Changed: {changed[:10]}")

        recent = get_recent_trades(all_trades, days=7)
        if recent:
            notify_new_trades(recent[:15])
        notify_portfolio_update(changes, new_portfolio["allocations"])
    else:
        print("  No changes.")

    # 4 — Sync to T212
    print("\n[4/4] Trading 212 sync...")
    unavailable = []
    sync_count = 0
    if dry_run:
        print("  DRY RUN — skipped")
    elif not T212_API_KEY:
        print("  T212 not configured — skipped")
    elif changes["has_changes"]:
        try:
            from t212 import sync_pie
            result, unavailable = sync_pie(new_portfolio["allocations"])
            sync_count = len(new_portfolio["allocations"]) - len(unavailable)
            notify_pie_synced(result, sync_count, unavailable)
        except Exception as e:
            print(f"  ERROR: {e}")
            notify_error(str(e))
    else:
        print("  No changes to sync.")

    # Save
    save_portfolio(new_portfolio)
    save_history({
        "timestamp": _utcnow().isoformat(),
        "stock_count": len(new_portfolio["allocations"]),
        "active_members": meta.get("active_members", 0),
        "has_changes": changes["has_changes"],
    })
    print("\nCycle complete.")


def main():
    loop = "--loop" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  🏛️  Congress Trade Tracker")
    print("  Tracking ALL trading members of Congress")
    print("=" * 60)
    print(f"  Mode:     {'LOOP' if loop else 'SINGLE RUN'}")
    print(f"  Dry run:  {dry_run}")
    print(f"  T212:     {'configured' if T212_API_KEY else 'NOT SET'}")
    print(f"  Interval: {POLL_INTERVAL}s")
    print("=" * 60)

    if loop:
        notify_startup()

    while True:
        try:
            run_cycle(dry_run=dry_run)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception:
            print(f"\nERROR:\n{traceback.format_exc()}")
            notify_error(traceback.format_exc()[-300:])

        if not loop:
            break
        print(f"\nSleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
