"""
kaal_morning.py
Morning scan: runs at ~8:50 AM.
Generates today's intraday watchlist from live announcements + deals + promoter activity.
Sends Telegram brief with full REASON CHAIN (why bullish/bearish per stock).
No hardcoded watchlist. Watchlist is purely scan output.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from kaal_log import log, log_section
from collections import defaultdict

from kaal_sources import (
    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners, fetch_oi_spurts,
    fetch_macro, fetch_asm_gsm_ban,
    fetch_news, check_liquidity,
)
from kaal_scorer import (
    classify_announcement, score_announcement,
    score_bulk_deal, score_promoter_pit, score_news_velocity,
    score_proxy_signals, score_negative_proxy, score_usfda_signals, score_budget_signals,
)
from kaal_telegram import send
from kaal_config import check_keys,\
     MAX_TIER1, MAX_TIER2, VIX_HIGH
from kaal_llm import reset_call_count

DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
SEEN_FILE      = os.path.join(DATA_DIR, "seen_ids.txt")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.txt")



def load_seen():
    if not os.path.exists(SEEN_FILE): return set()
    return set(open(SEEN_FILE).read().splitlines())

def save_seen(ids):
    os.makedirs(DATA_DIR, exist_ok=True)
    open(SEEN_FILE, "w").write("\n".join(sorted(ids)))

def save_watchlist(symbols: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    open(WATCHLIST_FILE, "w").write("\n".join(symbols))

def get_ann_id(ann):
    return (
        (ann.get("an_dt") or ann.get("dt") or "") + "_" +
        (ann.get("symbol") or str(ann.get("SCRIP_CD", "")) or "")
    )

def macro_bias_label(macro: dict) -> str:
    score = 0
    vix = macro.get("vix", 15)
    if vix < 14:    score += 2
    elif vix > 20:  score -= 2
    gift = macro.get("gift_nifty_bias", "Neutral")
    if gift == "Bullish":  score += 2
    elif gift == "Bearish": score -= 2
    if macro.get("spx_chg", 0) > 0.3:   score += 1
    elif macro.get("spx_chg", 0) < -0.5: score -= 1
    if score >= 2:   return "📈 BULLISH"
    if score <= -1:  return "📉 BEARISH"
    return "➡️ NEUTRAL"

def _entry_plan(s: dict) -> str:
    cat = s.get("catalyst", "").upper()
    vix = 15  # default fallback
    if "OPEN_OFFER" in cat or "TAKEOVER" in cat:
        return "Entry: pullback to VWMA20 only | SL: 15M body low | Target: 1:3"
    elif "BUYBACK" in cat:
        buyback_type = s.get("buyback_type", "OPEN_MARKET")
        if buyback_type == "TENDER":
            return "TENDER buyback — arbitrage only. Buy below offer price, tender shares. Not intraday tradeable."
        return "OPEN MARKET buyback — daily buying pressure. Entry: breakout or VWMA20 retest | SL: 15M low | Target: 1:2"
    elif "MERGER" in cat or "AMALGAM" in cat or "DEMERGER" in cat:
        return "Entry: pullback after gap-up | SL: 15M low | Target: 1:2.5"
    elif "USFDA" in cat or "ORDER_WIN" in cat:
        return "Entry: 9:30 breakout or VWMA20 retest | SL: 15M low | Target: 1:2"
    elif "RESULTS" in cat:
        return "Entry: wait for 9:30 candle direction | SL: 15M low | Target: 1:2"
    elif "NEWS_MOMENTUM" in cat:
        return "Attention flag only — confirm with price + volume before entry"
    elif "ACQUISITION" in cat:
        return "Entry: pullback to VWMA20 | SL: 15M low | Target: 1:2"
    else:
        return "Entry after 9:30 AM | SL: 15M low | Target: 2x SL"


def direction_emoji(direction: str) -> str:
    return {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(direction, "⚪")

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
        lines.append("\n🔥 <b>TIER 1 — HIGH CONVICTION</b>")
        for i, s in enumerate(tier1, 1):
            de = direction_emoji(s.get("direction", "NEUTRAL"))
            lines += [
                "",
                f"<b>#{i}  {s['symbol']}</b>  {de}  Score: <code>{s['score']}/100</code>",
                f"📌 <b>Catalyst:</b> {s.get('catalyst', '').replace('_', ' ')}",
                f"📊 <b>Signal from:</b> {', '.join(s.get('signal_sources', []))}",
                f"💡 <b>Key fact:</b> {s.get('key', '')[:110]}",
                f"🧠 <b>Why {s.get('direction','?')}:</b> {s.get('reason', '')[:200]}",
                f"🌍 <b>Macro:</b> {s.get('macro_note', '')[:90]}" if s.get("macro_note") else "",
                f"🎯 {_entry_plan(s)}",
            ]
    else:
        lines.append("\n⚠️ No Tier 1 stocks today — consider staying in cash")

    if tier2:
        lines.append("\n👀 <b>TIER 2 — WATCHLIST (confirm at open)</b>")
        for s in tier2:
            de = direction_emoji(s.get("direction", "NEUTRAL"))
            lines.append(
                f"• <b>{s['symbol']}</b> {de} [{s['score']}]  "
                f"{s.get('catalyst', '').replace('_', ' ')} — "
                f"{s.get('key', '')[:70]}"
            )
            if s.get("reason"):
                lines.append(f"  ↳ {s['reason'][:120]}")

    if not tier1 and not tier2:
        lines.append("\n⚠️ No qualifying stocks today — stay in cash, protect capital")

    if vix > VIX_HIGH:
        lines.append(f"\n⚠️ <b>VIX {vix:.1f} &gt; {VIX_HIGH} — Tier 1 only, 50% position size</b>")

    lines += [
        "",
        "─" * 34,
        "<i>Observe 9:15–9:30. Enter only after 9:30. No new entries after 11 AM.</i>",
    ]
    return "\n".join(l for l in lines if l is not None)


def run():
    check_keys()
    reset_call_count()
    t0 = time.time()
    log("═══ KAAL MORNING RUN ═══")

    seen     = load_seen()
    filters  = fetch_asm_gsm_ban()
    skip_set = filters["asm"] | filters["gsm"] | filters["ban"]
    macro    = fetch_macro()
    log(f"Macro: VIX={macro.get('vix', 0):.1f}, Bias={macro.get('gift_nifty_bias')}, SPX={macro.get('spx_chg', 0):+.1f}%")

    nse_anns = fetch_nse_announcements()
    news     = fetch_news()
    preopen  = fetch_preopen_gainers()
    # Build gap map for quick lookup
    gap_map  = {s['symbol']: s['gap_pct'] for s in preopen if abs(s['gap_pct']) >= 2.0}
    sectors   = fetch_sector_strength()
    screeners = fetch_chartink_screeners()
    oi_map    = fetch_oi_spurts()
    # All screener symbols in one set
    screener_stocks = set()
    for name, stocks in screeners.items():
        screener_stocks.update(stocks)
    log(f'Screener universe: {len(screener_stocks)} unique stocks across {len(screeners)} screeners')
    hot_kw   = set(w.upper() for w in sectors.get('hot_keywords', []))
    cold_kw  = set()
    for sec in sectors.get('cold_sectors', []):
        from kaal_sources import SECTOR_MAP
        cold_kw.update(SECTOR_MAP.get(sec['sector'], []))


    log(f"Fetched: {len(nse_anns)} NSE announcements")
    log(f"Seen IDs loaded: {len(seen)} — new announcements will be scored")

    new_seen   = set(seen)
    all_signals = []

    # ── Score announcements — Tier 1 first, then Tier 2 ──
    from kaal_scorer import classify_announcement as _classify
    tier1_anns, tier2_anns, new_anns = [], [], []
    for ann in nse_anns:
        # Pre-open gap boost
        sym = ann.get('symbol', '')
        ann['preopen_gap'] = gap_map.get(sym, 0.0)
        # Sector signals
        text = (ann.get('subject','') + ann.get('attchmntText','')).upper()
        ann['sector_hot']   = any(w in text for w in hot_kw)
        ann['sector_cold']  = any(w in text for w in cold_kw)
        ann['in_screener']  = ann.get('symbol','') in screener_stocks
        oi_data = oi_map.get(ann.get('symbol',''), {})
        ann['oi_spurt']    = oi_data.get('avg_oi_pct', 0)
        aid = get_ann_id(ann)
        if aid in seen:
            continue
        new_seen.add(aid)
        new_anns.append(ann)
        subj = (ann.get("desc") or ann.get("subject") or ann.get("NEWSSUB") or "").strip()
        det  = (ann.get("attchmntText") or ann.get("LONGDESC") or "").strip()
        _, _, tier = _classify(subj, det)
        if tier == 1:
            tier1_anns.append(ann)
        elif tier == 2:
            tier2_anns.append(ann)

    # Speed fix: cap Tier2 at 40 to avoid slow runs
    tier2_anns = tier2_anns[:40]
    log(f"New: {len(new_anns)} | Tier1 candidates: {len(tier1_anns)} | Tier2 candidates: {len(tier2_anns)}")

    for ann in tier1_anns + tier2_anns:
        result = score_announcement(ann, skip_set, macro_context=macro, use_pdf=True)
        if not result.get("skip") and result["score"] >= 40:
            all_signals.append(result)


    # ── Score news velocity (attention flags only) ────────
    news_signals = score_news_velocity(news)
    all_signals.extend(news_signals)

    # ── Budget day sector signals ─────────────────────────
    budget_signals = score_budget_signals(news)
    all_signals.extend(budget_signals)

    # ── USFDA special signals ────────────────────────────
    usfda_signals = score_usfda_signals(nse_anns, news)
    # Remove USFDA warnings from all_signals
    usfda_warn_syms = {s['symbol'] for s in usfda_signals if s['catalyst'] == 'USFDA_WARNING'}
    if usfda_warn_syms:
        log(f'USFDA warnings: removing {usfda_warn_syms}')
        all_signals = [s for s in all_signals if s['symbol'] not in usfda_warn_syms]
    all_signals.extend([s for s in usfda_signals if not s['skip']])

    # ── Proxy/indirect beneficiary signals ───────────────
    proxy_signals = score_proxy_signals(news, nse_anns)
    all_signals.extend(proxy_signals)

    # ── Negative proxy signals (sector headwinds) ─────────
    neg_signals = score_negative_proxy(news)
    # Use negative signals to REMOVE affected stocks from all_signals
    bearish_symbols = {s['symbol'] for s in neg_signals}
    if bearish_symbols:
        log(f'Negative proxy: removing {bearish_symbols} from watchlist')
        all_signals = [s for s in all_signals if s['symbol'] not in bearish_symbols]

    # ── OI spurt signals (smart money positioning) ────────
    announced_syms = {s['symbol'] for s in all_signals}
    for symbol, oi_data in oi_map.items():
        if symbol in announced_syms:
            continue
        if oi_data['avg_oi_pct'] < 15:
            continue
        score = 60 if oi_data['avg_oi_pct'] > 20 else 55
        all_signals.append({
            'symbol':         symbol,
            'score':          score,
            'tier':           2,
            'skip':           False,
            'catalyst':       'OI_SPURT',
            'direction':      'BULLISH',
            'key':            f'OI spurt {oi_data["avg_oi_pct"]:.1f}% above avg — smart money positioning',
            'reason':         'Unusual OI buildup detected. Confirm with price action and news catalyst before entry.',
            'source':         'NSE_OI',
            'signal_sources': ['NSE_OI'],
        })

    # ── Screener-only signals (technical breakout, no announcement) ───
    announced_symbols = {s['symbol'] for s in all_signals}
    for name, stocks in screeners.items():
        for symbol in stocks[:20]:
            if symbol in announced_symbols:
                continue  # already covered by announcement
            score = 58 if name == 'gap_up' else 55
            all_signals.append({
                'symbol':         symbol,
                'score':          score,
                'tier':           2,
                'skip':           False,
                'catalyst':       f'SCREENER_{name.upper()}',
                'direction':      'BULLISH',
                'key':            f'Chartink {name.replace("_"," ").title()} — technical signal only',
                'reason':         f'Stock in {name} screener. Confirm with price action and volume before entry.',
                'source':         'CHARTINK',
                'signal_sources': ['CHARTINK'],
            })

    # ── Merge by symbol: best score + source bonus ────────
    by_symbol = defaultdict(list)
    for s in all_signals:
        by_symbol[s["symbol"]].append(s)

    final = []
    for symbol, sigs in by_symbol.items():
        if symbol in skip_set:
            continue
        best         = max(sigs, key=lambda x: x["score"])
        all_sources  = []
        for s in sigs:
            all_sources.extend(s.get("signal_sources", []))
        unique_sources = list(dict.fromkeys(all_sources))  # deduplicated, order preserved
        source_bonus   = (len(set(unique_sources)) - 1) * 5  # +5 per additional source type

        best = dict(best)
        best["score"]          = min(best["score"] + source_bonus, 100)
        best["signal_sources"] = unique_sources

        # Multi-source confirmation note
        if len(set(unique_sources)) > 1:
            best["reason"] = (
                f"[MULTI-SOURCE CONFIRMATION: {', '.join(set(unique_sources))}] "
                + best.get("reason", "")
            )

        final.append(best)

    # ── Pre-filter before Gemini (max 15 signals) ─────────
    # Sort by score, keep top 15 only
    final.sort(key=lambda x: -x["score"])
    # Always keep Tier1 catalysts
    STRONG_CATS = {"OPEN_OFFER","BUYBACK","MERGER","DEMERGER","USFDA","PROXY_PLAY","ACQUISITION"}
    tier1_final = [s for s in final if s.get("catalyst","").upper() in STRONG_CATS][:8]
    other_final = [s for s in final if s.get("catalyst","").upper() not in STRONG_CATS][:7]
    final = tier1_final + other_final
    log(f"Pre-filter: {len(final)} signals sent to Gemini")

    # ── Gemini Final Judge ──────────────────────────────────
    log("Running Gemini final judge...")
    try:
        from kaal_llm import gemini_final_judge
        judged = gemini_final_judge(final, macro)
        if judged and isinstance(judged, list) and len(judged) > 0:
            final = judged
            log(f"Gemini judge done: {len(final)} signals remain")
        else:
            raise Exception("Gemini returned empty")
    except Exception as e:
        log(f"Gemini unavailable: {e} — rule-based fallback")
        SKIP_CATS = {"NEWS_MOMENTUM", "OTHER", "PARTNERSHIP", "CLARIFICATION"}
        ORDER_CATS = {"ORDER_WIN", "BAGGING_RECEIVING_OF_ORDE", "AWARDING_OF_ORDER(S)_CONT"}
        WEAK_ACQ   = {"JUBLFOOD", "BIOCON", "INDIACEM"}  # known small acquisitions
        KEEP_CATS  = {"OPEN_OFFER", "BUYBACK", "MERGER", "AMALGAMATION",
                      "USFDA", "DEMERGER", "SCHEME_OF_ARRANGEMENT", "AGM_SUBSIDIARY"}
        filtered = []
        for s in final:
            cat    = s.get("catalyst", "").upper()
            score  = s.get("score", 0)
            symbol = s.get("symbol", "")
            if cat in SKIP_CATS:
                continue
            if cat in ORDER_CATS and score < 80:
                continue
            if symbol in WEAK_ACQ:
                continue
            if cat == "ACQUISITION" and score < 75:
                continue
            if score < 65:
                continue
            filtered.append(s)
        final = filtered
        log(f"Fallback done: {len(final)} signals remain")

    # ── Sort and tier ─────────────────────────────────────
    final.sort(key=lambda x: -x["score"])

    from kaal_config import TIER1_MIN_SCORE, TIER2_MIN_SCORE
    tier1 = [s for s in final if s["score"] >= TIER1_MIN_SCORE][:MAX_TIER1]
    tier2 = [s for s in final if TIER2_MIN_SCORE <= s["score"] < TIER1_MIN_SCORE][:MAX_TIER2]

    # ── Save outputs ──────────────────────────────────────
    save_seen(new_seen)
    # Watchlist = symbols for monitor to watch during the day
    watchlist_symbols = [s["symbol"] for s in tier1 + tier2]
    save_watchlist(watchlist_symbols)
    log(f"Watchlist saved: {watchlist_symbols}")

    # ── Send Telegram ─────────────────────────────────────
    msg = build_morning_brief(tier1, tier2, macro)
    # Save brief to file
    import os
    brief_file = os.path.join(os.path.dirname(__file__), "data", "latest_brief.txt")
    with open(brief_file, "w") as f:
        f.write(msg)
    send(msg)
    log(f"Brief sent: {len(tier1)} Tier1, {len(tier2)} Tier2 | Time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
