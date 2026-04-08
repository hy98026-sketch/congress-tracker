"""
Telegram Notifier
=================
Sends alerts when new trades are detected or portfolio changes.
"""

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(text, parse_mode="HTML", disable_preview=True):
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


def notify_new_trades(trades):
    if not trades:
        return
    lines = ["🏛️ <b>New Congress Trades Detected</b>\n"]
    for t in trades[:15]:
        politician = t.get("politician", "Unknown")
        ticker = t.get("ticker", "???")
        action = t.get("type", "?")
        amount = t.get("amount", "N/A")
        date = t.get("date", "?")
        emoji = "🟢" if "buy" in action else "🔴" if "sell" in action else "⚪"
        lines.append(f"{emoji} <b>{politician}</b> → {action.upper()} <code>{ticker}</code> ({amount}) on {date}")
    if len(trades) > 15:
        lines.append(f"\n... and {len(trades) - 15} more trades")
    send_message("\n".join(lines))


def notify_portfolio_update(changes, allocations):
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
            lines.append(f"  <code>{ticker}</code> {info['old']:.1f}% → {info['new']:.1f}%")
    lines.append(f"\n📈 Total stocks in pie: {len(allocations)}")
    send_message("\n".join(lines))


def notify_pie_synced(result, available, unavailable):
    lines = ["✅ <b>T212 Pie Synced</b>\n"]
    lines.append(f"Instruments in pie: {available}")
    if unavailable:
        lines.append(f"\n⚠️ Not available on T212: {', '.join(unavailable[:10])}")
    send_message("\n".join(lines))


def notify_error(error):
    send_message(f"❌ <b>Error</b>\n\n<code>{error[:500]}</code>")


def notify_startup():
    from config import WEIGHTING_METHOD, POLL_INTERVAL
    send_message(
        f"🚀 <b>Congress Tracker Started</b>\n\n"
        f"Tracking ALL trading members of Congress\n\n"
        f"Weighting: {WEIGHTING_METHOD}\n"
        f"Poll interval: {POLL_INTERVAL}s"
    )
