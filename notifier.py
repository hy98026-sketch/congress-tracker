"""
Telegram Notifier
=================
Sends notifications to your Telegram chat when:
- New trades are detected from tracked members
- Portfolio allocations change
- Pie is updated on Trading 212
- Errors occur

Same pattern as your Vinted monitoring bots.
"""

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(text: str, parse_mode: str = "HTML", disable_preview: bool = True):
    """Send a message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram] Not configured, would send:\n{text[:200]}...")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Telegram] Error sending message: {e}")


def notify_new_trades(trades: list[dict]):
    """Notify about newly detected trades."""
    if not trades:
        return

    lines = ["🏛️ <b>New Congress Trades Detected</b>\n"]

    for t in trades[:15]:  # Limit to 15 per message
        politician = t.get("politician", "Unknown")
        ticker = t.get("ticker", "???")
        action = t.get("type_normalised", t.get("type", "?"))
        amount = t.get("amount", "N/A")
        date = t.get("date", t.get("traded", "?"))

        emoji = "🟢" if "buy" in action else "🔴" if "sell" in action else "⚪"
        lines.append(
            f"{emoji} <b>{politician}</b> → {action.upper()} "
            f"<code>{ticker}</code> ({amount}) on {date}"
        )

    if len(trades) > 15:
        lines.append(f"\n... and {len(trades) - 15} more trades")

    send_message("\n".join(lines))


def notify_portfolio_update(changes: dict, allocations: dict):
    """Notify about portfolio allocation changes."""
    if not changes.get("has_changes"):
        return

    lines = ["📊 <b>Portfolio Update</b>\n"]

    added = changes.get("added", {})
    removed = changes.get("removed", {})
    changed = changes.get("changed", {})

    if added:
        lines.append("➕ <b>Added:</b>")
        for ticker, pct in added.items():
            lines.append(f"  <code>{ticker}</code> at {pct:.1f}%")

    if removed:
        lines.append("➖ <b>Removed:</b>")
        for ticker, pct in removed.items():
            lines.append(f"  <code>{ticker}</code> (was {pct:.1f}%)")

    if changed:
        lines.append("🔄 <b>Reweighted:</b>")
        for ticker, info in changed.items():
            lines.append(
                f"  <code>{ticker}</code> {info['old']:.1f}% → {info['new']:.1f}%"
            )

    lines.append(f"\n📈 Total stocks in pie: {len(allocations)}")
    top_5 = sorted(allocations.items(), key=lambda x: x[1], reverse=True)[:5]
    lines.append("Top 5:")
    for ticker, pct in top_5:
        lines.append(f"  <code>{ticker}</code> {pct:.1f}%")

    send_message("\n".join(lines))


def notify_pie_synced(result: dict, available: int, unavailable: list):
    """Notify that the T212 pie was synced."""
    lines = ["✅ <b>T212 Pie Synced</b>\n"]
    lines.append(f"Instruments in pie: {available}")

    if unavailable:
        lines.append(f"\n⚠️ Not available on T212: {', '.join(unavailable[:10])}")

    send_message("\n".join(lines))


def notify_error(error: str):
    """Notify about errors."""
    send_message(f"❌ <b>Error</b>\n\n<code>{error[:500]}</code>")


def notify_startup():
    """Send a startup message."""
    from config import TRACKED_MEMBERS, WEIGHTING_METHOD, POLL_INTERVAL

    members_list = "\n".join(
        f"  {'⭐' * m['tier']} {m['name']} ({m['party']}-{m['state']})"
        for m in TRACKED_MEMBERS
    )

    send_message(
        f"🚀 <b>Congress Tracker Started</b>\n\n"
        f"Tracking {len(TRACKED_MEMBERS)} members:\n{members_list}\n\n"
        f"Weighting: {WEIGHTING_METHOD}\n"
        f"Poll interval: {POLL_INTERVAL}s"
    )
