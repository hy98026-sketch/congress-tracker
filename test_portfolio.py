"""
Test the portfolio builder with realistic mock data.
Run this to verify the logic works before deploying.
"""

from datetime import datetime, timedelta
from portfolio import build_portfolio, compare_portfolios

# ── Generate realistic mock trades ──
# Simulates what the House/Senate Stock Watcher APIs return
# Based on actual 2025 congressional trading patterns

def make_trade(politician, ticker, trade_type, amount, days_ago):
    date = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {
        "source": "test",
        "politician": politician,
        "ticker": ticker,
        "type": trade_type,
        "date": date,
        "amount": amount,
        "asset_description": f"{ticker} common stock",
    }


MOCK_TRADES = [
    # ── NVDA — bought by many members (high conviction) ──
    make_trade("Nancy Pelosi", "NVDA", "buy", "$1,000,001 - $5,000,000", 30),
    make_trade("Terri Sewell", "NVDA", "buy", "$100,001 - $250,000", 45),
    make_trade("Ro Khanna", "NVDA", "buy", "$50,001 - $100,000", 60),
    make_trade("Tommy Tuberville", "NVDA", "buy", "$250,001 - $500,000", 20),
    make_trade("Josh Gottheimer", "NVDA", "buy", "$50,001 - $100,000", 55),
    make_trade("Michael McCaul", "NVDA", "buy", "$15,001 - $50,000", 40),
    make_trade("Tom McClintock", "NVDA", "buy", "$50,001 - $100,000", 35),
    make_trade("Rick Scott", "NVDA", "buy", "$100,001 - $250,000", 25),

    # ── AAPL — also popular ──
    make_trade("Nancy Pelosi", "AAPL", "buy", "$500,001 - $1,000,000", 30),
    make_trade("Ro Khanna", "AAPL", "buy", "$100,001 - $250,000", 50),
    make_trade("Josh Gottheimer", "AAPL", "buy", "$50,001 - $100,000", 40),
    make_trade("Nick LaLota", "AAPL", "buy", "$15,001 - $50,000", 35),
    make_trade("Donald Norcross", "AAPL", "buy", "$50,001 - $100,000", 60),

    # ── MSFT — moderate conviction ──
    make_trade("Josh Gottheimer", "MSFT", "buy", "$100,001 - $250,000", 30),
    make_trade("Nancy Pelosi", "MSFT", "buy", "$250,001 - $500,000", 45),
    make_trade("Michael McCaul", "MSFT", "buy", "$50,001 - $100,000", 55),

    # ── GOOGL — a few members ──
    make_trade("Nancy Pelosi", "GOOGL", "buy", "$500,001 - $1,000,000", 20),
    make_trade("Ro Khanna", "GOOGL", "buy", "$50,001 - $100,000", 40),
    make_trade("Terri Sewell", "GOOGL", "buy", "$15,001 - $50,000", 50),

    # ── AMZN ──
    make_trade("Nancy Pelosi", "AMZN", "buy", "$250,001 - $500,000", 25),
    make_trade("Tommy Tuberville", "AMZN", "buy", "$100,001 - $250,000", 35),

    # ── GS — Rick Scott's big winner ──
    make_trade("Rick Scott", "GS", "buy", "$500,001 - $1,000,000", 90),
    make_trade("Josh Gottheimer", "GS", "buy", "$100,001 - $250,000", 60),
    make_trade("Rick Scott", "GS", "sell", "$250,001 - $500,000", 15),  # Partial sell

    # ── PLTR — committee members buying (suspicious timing) ──
    make_trade("Tommy Tuberville", "PLTR", "buy", "$50,001 - $100,000", 40),
    make_trade("Michael McCaul", "PLTR", "buy", "$15,001 - $50,000", 35),

    # ── Some single-member SMALL trades (should be filtered out — noise) ──
    make_trade("Tom McClintock", "CRBL", "buy", "$15,001 - $50,000", 20),
    make_trade("Nick LaLota", "ABNB", "buy", "$15,001 - $50,000", 30),

    # ── WHALE PICKS: single member, BIG trade on obscure stock ──
    # This is exactly the "suspicious insider trade" scenario:
    # One member quietly drops $500K on a random defence contractor
    make_trade("Tommy Tuberville", "LMT", "buy", "$500,001 - $1,000,000", 15),

    # Another whale: one member buys $250K of a small biotech
    make_trade("Rick Scott", "MRNA", "buy", "$250,001 - $500,000", 25),

    # This one is below the $100K threshold — should NOT be a whale pick
    make_trade("Tom McClintock", "RKLB", "buy", "$50,001 - $100,000", 20),

    # ── A full sell (should remove from portfolio) ──
    make_trade("Nancy Pelosi", "DIS", "buy", "$100,001 - $250,000", 90),
    make_trade("Nancy Pelosi", "DIS", "sell", "$100,001 - $250,000", 10),  # Exited
]


def test_portfolio():
    print("=" * 60)
    print("  Testing Portfolio Builder with Mock Data")
    print("=" * 60)

    portfolio = build_portfolio(MOCK_TRADES, lookback_days=180)

    meta = portfolio["metadata"]
    print(f"\nMetadata:")
    print(f"  Total trades analysed: {meta['total_trades']}")
    print(f"  Active members: {meta['active_members']}")
    print(f"  Unique tickers: {meta['unique_tickers']}")
    print(f"  Consensus picks: {meta['consensus_picks']}")
    print(f"  Whale picks: {meta['whale_picks']}")
    print(f"  Stocks in pie: {meta['pie_stocks']}")

    print(f"\nAllocations:")
    total = 0
    for ticker, pct in sorted(
        portfolio["allocations"].items(), key=lambda x: x[1], reverse=True
    ):
        detail = portfolio["holdings_detail"][ticker]
        members = detail["members"]
        tier = detail["tier"]
        vol = detail["buy_volume"]
        total += pct
        tier_icon = "🐋" if tier == "whale" else "🤝"
        print(
            f"  {tier_icon} {ticker:6s} {pct:5.2f}%  "
            f"({detail['member_count']} members, ${vol:,.0f})  "
            f"[{tier.upper()}] [{', '.join(members[:3])}]"
        )
    print(f"\n  Total: {total:.2f}%")

    # ── Assertions ──
    assert abs(total - 100.0) < 0.1, f"Should sum to ~100%, got {total}"

    # Consensus picks should be present
    assert "NVDA" in portfolio["allocations"], "NVDA should be in (8 members)"
    assert "AAPL" in portfolio["allocations"], "AAPL should be in (5 members)"

    # Whale picks should be present (single member, big trade)
    assert "LMT" in portfolio["allocations"], "LMT should be a whale pick ($500K+, Tuberville)"
    assert "MRNA" in portfolio["allocations"], "MRNA should be a whale pick ($250K+, Scott)"
    assert portfolio["holdings_detail"]["LMT"]["tier"] == "whale"
    assert portfolio["holdings_detail"]["MRNA"]["tier"] == "whale"

    # Small single-member trades should be filtered OUT
    assert "CRBL" not in portfolio["allocations"], "CRBL should be filtered ($32.5K < $50K threshold)"
    assert "ABNB" not in portfolio["allocations"], "ABNB should be filtered ($32.5K < $50K threshold)"

    # RKLB at $75K is now ABOVE the $50K whale threshold — should be included
    assert "RKLB" in portfolio["allocations"], "RKLB should be a whale pick ($75K > $50K threshold)"
    assert portfolio["holdings_detail"]["RKLB"]["tier"] == "whale"

    # Whale picks should have LOWER allocation than consensus picks
    assert portfolio["allocations"]["NVDA"] > portfolio["allocations"]["LMT"], \
        "Consensus NVDA should outweigh whale LMT"

    # NVDA should still be #1 (8 members = massive consensus)
    top_ticker = max(portfolio["allocations"], key=portfolio["allocations"].get)
    assert top_ticker == "NVDA", f"NVDA should be top, got {top_ticker}"

    print("\n✅ All assertions passed!")
    print("   - Consensus picks included and weighted high")
    print("   - Whale picks ($50K+ single-member trades) included at lower weight")
    print("   - Small single-member trades (<$50K) correctly filtered out")

    # Test portfolio comparison
    print("\n── Testing Portfolio Diff ──")
    old_portfolio = {
        "allocations": {"NVDA": 30, "AAPL": 25, "TSLA": 20, "MSFT": 25}
    }
    changes = compare_portfolios(old_portfolio, portfolio)
    print(f"  Added:   {list(changes['added'].keys())}")
    print(f"  Removed: {list(changes['removed'].keys())}")
    print(f"  Changed: {list(changes['changed'].keys())}")
    assert changes["has_changes"], "Should detect changes"
    assert "TSLA" in changes["removed"], "TSLA should be removed (not in new portfolio)"

    print("\n✅ Diff test passed!")

    # Show member summary
    print("\n── Member Summary ──")
    for member, info in sorted(
        portfolio["member_summary"].items(),
        key=lambda x: x[1]["holdings_count"],
        reverse=True,
    ):
        print(f"  {member}: {info['holdings_count']} holdings → {', '.join(info['tickers'][:6])}")


if __name__ == "__main__":
    test_portfolio()
