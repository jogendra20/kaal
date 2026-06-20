content = open('kaal_morning.py').read()

start = content.find('def build_morning_brief')
end = content.find('\ndef ', start + 10)

new_func = '''def _status_emoji(status: str) -> str:
    return {"FRESH": "🟢 FRESH", "AGING": "🟡 AGING", "STALE": "🔴 STALE"}.get(status, "🟢 FRESH")


def _signal_time(s: dict) -> str:
    """Returns NSE filing timestamp if available, else first_seen date."""
    raw_time = s.get("an_dt", "") or s.get("announcement_time", "")
    if raw_time:
        try:
            dt = datetime.strptime(raw_time[:20], "%d-%b-%Y %H:%M:%S")
            return dt.strftime("%I:%M %p")
        except Exception:
            pass
    first_seen = s.get("first_seen", "")
    if first_seen:
        try:
            dt = datetime.strptime(first_seen, "%Y-%m-%d")
            return dt.strftime("%b %d")
        except Exception:
            pass
    return "—"


def _format_signal_block(s: dict) -> list:
    de       = direction_emoji(s.get("direction", "NEUTRAL"))
    status   = _status_emoji(s.get("hist_status", "FRESH"))
    pct      = s.get("pct_change", 0.0)
    catalyst = s.get("catalyst", "").replace("_", " ")
    time_str = _signal_time(s)

    pct_str = f" | {pct:+.1f}% since trigger" if pct != 0 else ""

    lines = [
        "",
        f"<code>[{time_str}]</code> <b>{s['symbol']}</b> — {catalyst} {de}",
        f"Score: <code>{s['score']}/100</code>{pct_str} {status}",
        f"└─ {s.get('key', '')[:100]}",
        f"└─ {s.get('reason', '')[:150]}",
        f"└─ 🎯 {_entry_plan(s)}",
    ]
    return lines


def build_morning_brief(tier1: list, tier2: list, macro: dict) -> str:
    now   = datetime.now().strftime("%d %b %Y %I:%M %p")
    vix   = macro.get("vix", 0)
    bias  = macro_bias_label(macro)
    gift  = macro.get("gift_nifty_bias", "Neutral")
    giftp = macro.get("gift_nifty_pct", 0)

    lines = [
        "<b>⚔️ KAAL MORNING BRIEF</b>",
        f"<code>{now}</code>",
        "",
        "<b>🌐 MACRO</b>",
        f"VIX: <code>{vix:.1f}</code>  |  Bias: {bias}",
        f"GIFT Nifty: <code>{giftp:+.2f}%</code> ({gift})",
        f"SPX: <code>{macro.get('spx_chg', 0):+.1f}%</code>  "
        f"Crude: <code>${macro.get('crude', 0):.0f}</code>  "
        f"Gold: <code>${macro.get('gold', 0):.0f}</code>  "
        f"USD/INR: <code>{macro.get('usdinr', 0):.2f}</code>",
        "─" * 34,
    ]

    if tier1:
        lines.append("\\n🔥 <b>TIER 1 — HIGH CONVICTION</b>")
        for s in tier1:
            lines += _format_signal_block(s)
    else:
        lines.append("\\n⚠️ No Tier 1 stocks today — consider staying in cash")

    if tier2:
        lines.append("\\n👀 <b>TIER 2 — WATCHLIST</b>")
        for s in tier2:
            lines += _format_signal_block(s)

    if not tier1 and not tier2:
        lines.append("\\n⚠️ No qualifying stocks today — stay in cash, protect capital")

    if vix > VIX_HIGH:
        lines.append(f"\\n⚠️ <b>VIX {vix:.1f} &gt; {VIX_HIGH} — Tier 1 only, 50% position size</b>")

    lines += [
        "",
        "─" * 34,
        "<i>Observe 9:15–9:30. Enter only after 9:30. No new entries after 11 AM.</i>",
    ]
    return "\\n".join(l for l in lines if l is not None)
'''

content = content[:start] + new_func + content[end:]
open('kaal_morning.py', 'w').write(content)
print('Done')
