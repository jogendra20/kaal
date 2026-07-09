"""
kaal_evening.py
Evening scan: runs at ~9:00 PM.
Purpose: scan today's full announcements → build tomorrow's pre-watchlist.
Resets seen_ids so morning scan sees tomorrow's fresh announcements.
Sends Telegram with WHY each stock is on the list.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from kaal_log import log, log_section
from collections import defaultdict

from kaal_sources import (
    fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban,
    fetch_news, fetch_eod_prices, fetch_bhavcopy, classify_delivery,
)
from kaal_scorer import (
    score_announcement, score_bulk_deal,
    score_promoter_pit, score_news_velocity,
)
from kaal_telegram import send
from kaal_config import check_keys,\
     MAX_TIER1, MAX_TIER2, TIER1_MIN_SCORE, TIER2_MIN_SCORE
from kaal_llm import reset_call_count

DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.txt")
SEEN_FILE      = os.path.join(DATA_DIR, "seen_ids.txt")


def save_watchlist(symbols: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    open(WATCHLIST_FILE, "w").write("\n".join(symbols))

def reset_seen():
    os.makedirs(DATA_DIR, exist_ok=True)
    open(SEEN_FILE, "w").write("")

def direction_emoji(direction: str) -> str:
    return {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(direction, "⚪")

def build_evening_brief(tier1: list, tier2: list, macro: dict, llm_capped: bool = False) -> str:
    now      = datetime.now().strftime("%d %b %Y %I:%M %p")
    vix      = macro.get("vix", 0)

    lines = [
        "<b>🌙 KAAL EVENING BRIEF</b>",
        f"<code>{now}</code>  |  VIX: <code>{vix:.1f}</code>",
        f"Crude: <code>${macro.get('crude', 0):.0f}</code>  "
        f"USD/INR: <code>{macro.get('usdinr', 0):.2f}</code>",
        "─" * 34,
        "",
        "<b>📋 TOMORROW'S PRE-WATCHLIST</b>",
        "<i>(Morning scan will confirm with fresh announcements)</i>",
    ]

    if tier1:
        lines.append("\n🔥 <b>TIER 1</b>")
        for s in tier1:
            de  = direction_emoji(s.get("direction", "NEUTRAL"))
            # Show announcement timestamp if available
            an_dt = s.get("an_dt", "")
            if an_dt:
                try:
                    from datetime import datetime as _dt
                    ts = _dt.strptime(an_dt, "%d-%b-%Y %H:%M:%S")
                    time_str = f"<code>[{ts.strftime('%I:%M %p')}]</code> "
                except Exception:
                    time_str = ""
            else:
                time_str = ""
            lines += [
                f"",
                f"{time_str}<b>{s['symbol']}</b> — {s.get('catalyst','').replace('_',' ')} {de}",
                f"Score: <code>{s['score']}/100</code>",
                f"└─ {s.get('key','')[:100]}",
                f"└─ {s.get('reason','')[:180]}",
            ]
    if tier2:
        lines.append("\n👀 <b>TIER 2</b>")
        for s in tier2:
            de = direction_emoji(s.get("direction", "NEUTRAL"))
            lines.append(
                f"• <b>{s['symbol']}</b> {de} [{s['score']}] "
                f"{s.get('catalyst','').replace('_',' ')} — {s.get('key','')[:70]}"
            )
    if not tier1 and not tier2:
        lines.append("⚠️ No qualifying stocks for tomorrow. Start fresh.")

    # Promoter activity section
    promoter_signals = [s for s in (tier1 + tier2) if "PROMOTER" in s.get("signal_sources", [])]
    if promoter_signals:
        lines.append("\n🏦 <b>PROMOTER / INSIDER ACTIVITY</b>")
        for s in promoter_signals[:5]:
            de = direction_emoji(s.get("direction", "NEUTRAL"))
            lines.append(f"• {s['symbol']} {de} — {s.get('key','')[:80]}")

    if llm_capped:
        lines.append(
            "\n\u26a0\ufe0f <i>LLM call cap hit during this run \u2014 some Tier 2 scores "
            "are rule-based only (no AI differentiation). Treat identical "
            "scores in this batch with extra caution.</i>"
        )

    lines += [
        "",
        "─" * 34,
        "<i>Morning brief at 8:50 AM tomorrow.</i>",
    ]
    return "\n".join(l for l in lines if l is not None)


def run():
    check_keys()
    reset_call_count()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] KAAL Evening Run started")
    send("🔄 <b>KAAL: Evening scan running...</b>")

    filters  = fetch_asm_gsm_ban()
    skip_set = filters["asm"] | filters["gsm"] | filters["ban"]
    macro    = fetch_macro()
    nse_anns = fetch_nse_announcements()
    news     = fetch_news()

    all_signals = []

    for ann in nse_anns:
        result = score_announcement(ann, skip_set, macro_context=macro, use_pdf=True)
        if not result.get("skip") and result["score"] >= 40:
            all_signals.append(result)



    all_signals.extend(score_news_velocity(news))

    import kaal_llm as _kaal_llm_mod
    llm_capped = _kaal_llm_mod._call_count >= _kaal_llm_mod.MAX_LLM_CALLS_PER_RUN
    if llm_capped:
        print(f"[KAAL] \u26a0\ufe0f  LLM call cap ({_kaal_llm_mod.MAX_LLM_CALLS_PER_RUN}) reached this run \u2014 remaining signals used rule-based fallback only")

    by_symbol = defaultdict(list)
    for s in all_signals:
        by_symbol[s["symbol"]].append(s)

    final = []
    for symbol, sigs in by_symbol.items():
        if symbol in skip_set:
            continue
        best          = max(sigs, key=lambda x: x["score"])
        all_src       = []
        for s in sigs: all_src.extend(s.get("signal_sources", []))
        unique_src    = list(dict.fromkeys(all_src))
        best          = dict(best)
        if best.get("catalyst") == "NEWS_MOMENTUM":
            # News-outlet mention count is NOT independent confirmation —
            # keep the hard Tier-2 cap regardless of how many outlets ran the story
            best["score"] = min(best["score"], 62)
        else:
            source_bonus  = (len(set(unique_src)) - 1) * 5
            best["score"] = min(best["score"] + source_bonus, 100)
        best["signal_sources"] = unique_src
        if len(set(unique_src)) > 1:
            best["reason"] = f"[{'+'.join(set(unique_src))}] " + best.get("reason", "")
        final.append(best)

    final.sort(key=lambda x: -x["score"])
    tier1 = [s for s in final if s["score"] >= TIER1_MIN_SCORE][:MAX_TIER1]
    tier2 = [s for s in final if TIER2_MIN_SCORE <= s["score"] < TIER1_MIN_SCORE][:MAX_TIER2]

    # Save tomorrow's watchlist
    save_watchlist([s["symbol"] for s in tier1 + tier2])
    # Reset seen so morning scan processes tomorrow's fresh announcements
    reset_seen()

    # Update signal history with today's closing prices
    from kaal_history import update_eod_prices, load_history
    tracked_symbols = list(load_history().keys())
    if tracked_symbols:
        eod = fetch_eod_prices(tracked_symbols)
        update_eod_prices(eod)

    # Fetch bhavcopy and store delivery % for watchlist stocks
    today_str = datetime.now().strftime('%d%m%Y')
    bhavcopy = fetch_bhavcopy(today_str)
    if bhavcopy:
        import json, os
        hist_file = os.path.join(os.path.dirname(__file__), 'data', 'signal_history.json')
        hist = json.load(open(hist_file)) if os.path.exists(hist_file) else {}
        for sym in tracked_symbols:
            if sym in bhavcopy and sym in hist:
                b = bhavcopy[sym]
                hist[sym]['deliv_per']  = b['deliv_per']
                hist[sym]['deliv_chg_pct'] = b['chg_pct']
                dc = classify_delivery(b['deliv_per'], b['chg_pct'])
                hist[sym]['deliv_label'] = dc['label']
                hist[sym]['deliv_note']  = dc['note']
        json.dump(hist, open(hist_file, 'w'), indent=2)
        print(f'[HIST] Delivery data stored for {len(tracked_symbols)} symbols')

    msg = build_evening_brief(tier1, tier2, macro, llm_capped=llm_capped)
    import os
    brief_file = os.path.join(os.path.dirname(__file__), "data", "latest_brief.txt")
    with open(brief_file, "w") as f:
        f.write(msg)
    send(msg)
    print(f"Evening brief sent: {len(tier1)} Tier1, {len(tier2)} Tier2")


if __name__ == "__main__":
    run()
