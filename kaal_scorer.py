"""
kaal_scorer.py
LLM-based announcement scorer. Builds a REASON CHAIN so you know WHY a
stock is bullish/bearish.
Deterministic keyword classification lives in kaal_event_classifier.py -
this file only holds the part that actually calls the LLM.
Every scored dict has:
  - score      : 0-100
  - tier       : 1 / 2 / 3
  - direction  : BULLISH / BEARISH / NEUTRAL
  - catalyst   : type of event
  - reason     : human-readable explanation (the "why")
  - signal_sources: list of what triggered it (announcement / bulk_deal / promoter / news)
"""
import re
from kaal_config import (
    TIER1_MIN_SCORE, TIER2_MIN_SCORE, SKIP_BELOW,
    FNO_UNIVERSE_HINT,
    PCR_BULLISH_THRESHOLD, PCR_BEARISH_THRESHOLD, MAX_PAIN_EXPIRY_WINDOW_DAYS,
    VWAP_EXTENDED_THRESHOLD_PCT, VWAP_DISCOUNT_THRESHOLD_PCT,
    MIN_VOLUME_CR,
)
from kaal_llm import call_llm
from kaal_sources import download_pdf_text
from kaal_event_classifier import classify_event_type, classify_announcement
from kaal_results_history import record_result


def _fiscal_quarter_label(an_dt: str):
    """Best-effort 'Q1FY27'-style label from an announcement's filing
    date, buffered back ~45 days so a results filing (usually 3-6 weeks
    after quarter-end) maps to the quarter it REPORTS on, not the
    quarter it was FILED in. Format of an_dt is not fully verified
    against live data - falls back to the raw string as a dedup key
    (still functions, just less readable) rather than raising."""
    from datetime import datetime, timedelta
    if not an_dt:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(an_dt.strip()[:len(fmt) + 2], fmt)
            break
        except Exception:
            dt = None
    if dt is None:
        return an_dt.strip()[:20]
    dt -= timedelta(days=45)
    if dt.month in (4, 5, 6):
        q, fy = 1, dt.year + 1
    elif dt.month in (7, 8, 9):
        q, fy = 2, dt.year + 1
    elif dt.month in (10, 11, 12):
        q, fy = 3, dt.year + 1
    else:
        q, fy = 4, dt.year
    return f"Q{q}FY{str(fy)[2:]}"


def _build_results_prompt(subject, details, pdf_text, macro_context):
    ctx = "Subject: " + subject + "\nDetails: " + details[:600]
    if pdf_text:
        ctx += "\nPDF Excerpt:\n" + pdf_text[:3000]

    macro_str = ""
    if macro_context:
        macro_str = (
            "\nMARKET CONTEXT: VIX=" + str(macro_context.get("vix","N/A")) +
            ", GIFT Nifty=" + macro_context.get("gift_nifty_bias","Neutral") +
            ", SPX=" + str(macro_context.get("spx_chg",0)) + "%"
        )

    schema = (
        "{\n"
        "  \"score\": <0-100 intraday long potential>,\n"
        "  \"pat_growth_pct\": <PAT this quarter vs same quarter last year number>,\n"
        "  \"revenue_growth_pct\": <Revenue YoY growth number>,\n"
        "  \"margin_expanded\": <true if EBITDA margin improved vs last year>,\n"
        "  \"exceptional_item\": <true if one-time item inflated PAT>,\n"
        "  \"dividend_announced\": <true if dividend declared with results>,\n"
        "  \"guidance_tone\": \"<POSITIVE|NEGATIVE|NEUTRAL|NONE>\",\n"
        "  \"is_beat\": <true if PAT growth >20% AND no exceptional items>,\n"
        "  \"is_fresh\": <true if announced after 3:30PM market close>,\n"
        "  \"announced_time\": \"<AFTER_HOURS|DURING_MARKET|UNKNOWN>\",\n"
        "  \"company_size\": \"<LARGE_CAP|MID_CAP|SMALL_CAP>\",\n"
        "  \"catalyst_type\": \"RESULTS_BEAT or RESULTS_MISS\",\n"
        "  \"direction\": \"<BULLISH|BEARISH|NEUTRAL>\",\n"
        "  \"key\": \"<PAT +X% YoY | Revenue +X% YoY | Margin expanded/contracted>\",\n"
        "  \"reason\": \"<Line1: beat magnitude. Line2: why it will/wont move intraday>\",\n"
        "  \"skip_reason\": \"<if score<40 why, else empty>\",\n"
        "  \"offer_price\": 0,\n"
        "  \"buyback_type\": \"NA\"\n"
        "}"
    )

    rules = (
        "SCORING RULES:\n"
        "- PAT >50% + no exceptional + after-hours = 82-90\n"
        "- PAT 30-50% + no exceptional + after-hours = 72-80\n"
        "- PAT 20-30% + no exceptional = 62-70\n"
        "- Dividend + PAT beat = +8 bonus\n"
        "- Guidance POSITIVE = +5 bonus\n"
        "- Exceptional item inflated PAT = MAX score 35, direction BEARISH\n"
        "- Revenue miss despite PAT beat = -10\n"
        "- Guidance NEGATIVE = -15, direction BEARISH\n"
        "- Announced during market hours = -15\n"
        "- LARGE_CAP = MAX score 60\n"
        "- PAT <20% = MAX score 45\n"
        "- PAT decline = MAX score 25, direction BEARISH\n"
        "HARD RULES:\n"
        "- Never BULLISH if exceptional items inflated PAT\n"
        "- Never score >60 for LARGE_CAP\n"
    )

    return (
        "You are NSE/BSE intraday trader analyzing quarterly results."
        + macro_str + "\n\n" + ctx
        + "\n\nExtract numbers from PDF only. Do NOT invent."
        + "\n\nReturn ONLY JSON:\n" + schema
        + "\n\n" + rules
    )


def _build_prompt(subject: str, details: str, pdf_text: str, macro_context: dict) -> str:
    ctx = f"Subject: {subject}\nDetails: {details[:600]}"
    if pdf_text:
        ctx += f"\nPDF Excerpt:\n{pdf_text[:2000]}"

    macro_str = ""
    if macro_context:
        macro_str = (
            f"\nMARKET CONTEXT: VIX={macro_context.get('vix', 'N/A')}, "
            f"GIFT Nifty Bias={macro_context.get('gift_nifty_bias', 'Neutral')}, "
            f"SPX Change={macro_context.get('spx_chg', 0):+.1f}%"
        )

    return f"""You are an expert NSE/BSE intraday trader analyzing corporate announcements.
{macro_str}

{ctx}

Return ONLY a JSON object with exactly these keys:
{{
  "score": <integer 0-100>,
  "is_fresh": <true if this is new info, false if repeat/routine>,
  "catalyst_type": "<OPEN_OFFER|BUYBACK|USFDA|MERGER|ACQUISITION|ORDER_WIN|RESULTS_BEAT|RESULTS_MISS|CLARIFICATION|KMP_CHANGE|DEBT_EVENT|CREDIT_UPGRADE|CREDIT_DOWNGRADE|QIP|RIGHTS_ISSUE|OTHER>",
  "direction": "<BULLISH|BEARISH|NEUTRAL>",
  "deal_value_cr": <number or 0>,
  "key_detail": "<single most important fact in one line, be specific>",
  "reason": "<2-3 sentences: WHY this is bullish/bearish, what the market reaction typically is, what trader should watch for>",
  "skip_reason": "<if score < 40, why. else empty>",
  "offer_price": <for open offers: the offer price per share as number, else 0>,
  "buyback_type": "<TENDER|OPEN_MARKET|NA> — TENDER=fixed price fixed date, OPEN_MARKET=company buys daily from market",
  "macro_impact": "<one line: how current market context affects this stock's setup>"
}}

CRITICAL: Only state a specific number (price, %, ₹ crore amount, share count) in "key_detail", "reason", "offer_price", or "macro_impact" if that exact figure literally appears in the Subject/Details/PDF Excerpt above. Never invent or estimate a plausible-sounding number for a detail that wasn't actually given. If a figure isn't present in the source text, describe it qualitatively instead (e.g. "at a premium to CMP", "value not disclosed") and leave the numeric field at 0.

Scoring reference (adjust for macro context):
- USFDA / EMA approval (genuine): 78-88
- Open offer by external acquirer: 85-95
- Buyback board approval (fresh): 72-82
- Acquisition with deal value: 65-78
- Large order > 10% revenue: 65-75
- Results beat > 15% PAT growth: 62-72
- Results miss / loss: 15-30 (BEARISH)
- Exchange clarification (rumour): 58-70
- QIP / rights issue: 40-55 (dilution risk)
- KMP resignation (CEO/CFO): 35-55 (BEARISH signal)
- Routine board meeting outcome: 20-40
- Debt restructuring / NCLT: 30-55 (check direction)
- is_fresh=false: cap score at 25 regardless
"""


# ── MAIN ANNOUNCEMENT SCORER ─────────────────────────────────────────────────
def score_announcement(ann: dict, skip_set: set, macro_context: dict = None, use_pdf: bool = True) -> dict:
    symbol  = (ann.get("symbol") or str(ann.get("SCRIP_CD", "")) or "").upper().strip()
    subject = (ann.get("desc") or ann.get("subject") or ann.get("NEWSSUB") or "").strip()
    details = (ann.get("attchmntText") or ann.get("LONGDESC") or "").strip()
    pdf_url = (ann.get("attchmntFile") or ann.get("ATTACHMENTNAME") or "").strip()
    source  = "NSE" if "symbol" in ann else "BSE"

    empty = {"symbol": symbol, "score": 0, "tier": 3, "skip": True}
    if not symbol or not subject:
        return empty
    if symbol in skip_set:
        return {**empty, "reason": "Stock under ASM/GSM/F&O ban"}

    # Check if open offer is already closed
    try:
        from kaal_config import CLOSED_OPEN_OFFERS
        from datetime import datetime
        if symbol in CLOSED_OPEN_OFFERS:
            close_date = datetime.strptime(CLOSED_OPEN_OFFERS[symbol], '%Y-%m-%d')
            if datetime.now() > close_date:
                return {**empty, 'reason': f'Open offer closed on {CLOSED_OPEN_OFFERS[symbol]} — stale'}
    except Exception:
        pass

    cat, base_score, tier = classify_announcement(subject, details)

    # Event-type gate - runs before any further scoring/LLM cost
    event_type = classify_event_type(subject, details)
    if event_type == "REGULATORY_SCRUTINY":
        # Pure exchange clarification/rumour-verification - no inherent
        # trade edge. Cap below Tier1 regardless of what subject-matching
        # assigned, so it can never masquerade as high-conviction.
        base_score = min(base_score, 50)
        tier = max(tier, 2)
    elif event_type == "CORPORATE_ACTION" and isinstance(ann, dict):
        # Trading suspension tied to scheme completion - the entity is
        # being absorbed/delisted, not re-rated. Tag it so _entry_plan()
        # shows an arbitrage-only note instead of a momentum entry plan.
        ann['event_type'] = 'CORPORATE_ACTION'

    # Liquidity gate — a catalyst score with no volume confirmation is a
    # news filter, not a momentum filter. Crude proxy: yesterday's actual
    # traded value from bhavcopy (already fetched for VWAP) vs a floor.
    # 0 means no data found (not necessarily illiquid) - don't penalize
    # on missing data, only on confirmed low liquidity.
    liquidity_cr = ann.get('liquidity_cr', 0) if isinstance(ann, dict) else 0
    if 0 < liquidity_cr < MIN_VOLUME_CR:
        base_score = min(base_score, 45)
        tier = max(tier, 2)

    # Order wins hard cap — never Tier1
    if cat in ('BAGGING_RECEIVING_OF_ORDE', 'AWARDING_OF_ORDER(S)_CONT', 'ORDER_WIN'):
        base_score = min(base_score, 65)
        tier = max(tier, 2)

    # Sale/disposal hard cap — only valuable if deal size is disclosed
    if cat == 'SALE_OR_DISPOSAL':
        combined = (subject + details).lower()
        has_value = any(kw in combined for kw in ['crore', 'cr.', 'lakh', 'million', 'billion', 'rs.', '₹'])
        if not has_value:
            return {**empty, 'reason': 'Sale/disposal with no deal value disclosed — insufficient detail'}
        base_score = min(base_score, 60)
        tier = max(tier, 2)

    # Buyback type detection
    if isinstance(ann, dict):
        _bt = (ann.get('desc','') + ann.get('attchmntText','') + subject).lower()
        _is_buyback = 'BUYBACK' in cat.upper() or 'buyback' in _bt
        if _is_buyback:
            if 'tender' in _bt:
                ann['buyback_type'] = 'TENDER'
                base_score = min(base_score, 55)
                cat = 'BUYBACK'
            elif 'open market' in _bt or 'stock exchange' in _bt:
                ann['buyback_type'] = 'OPEN_MARKET'
                base_score = max(base_score, 75)
                cat = 'BUYBACK'

    # Pre-open gap boost
    preopen_gap = ann.get('preopen_gap', 0.0) if isinstance(ann, dict) else 0.0
    if preopen_gap > 8.0:
        return {**empty, 'reason': f'Gap already {preopen_gap:.1f}% — edge consumed, skip'}
    if 2.0 <= preopen_gap <= 8.0:
        base_score = min(base_score + 8, 95)

    # Sector strength boost/penalty
    if isinstance(ann, dict):
        if ann.get('sector_hot'):
            base_score = min(base_score + 6, 95)
        if ann.get('sector_cold'):
            base_score = max(base_score - 8, 0)
        # Screener confirmation boost
        if ann.get('in_screener'):
            base_score = min(base_score + 10, 95)
        # OI spurt boost — smart money positioning
        oi_pct = ann.get('oi_spurt', 0)
        if oi_pct > 20:
            base_score = min(base_score + 12, 95)
        elif oi_pct > 10:
            base_score = min(base_score + 6, 95)

        # PCR / Max Pain boost -- F&O positioning context.
        # PCR shifts score a little either way (contrarian read: high PCR =
        # oversold/bullish, low PCR = overbought/bearish). Max Pain pinning
        # only applies as a directional nudge within a few days of expiry --
        # outside that window a stale max-pain figure is not predictive.
        pcr           = ann.get('pcr', 0)
        days_to_exp   = ann.get('days_to_expiry', 99)
        pain_distance = ann.get('max_pain_distance', 0)
        if pcr:
            if pcr > PCR_BULLISH_THRESHOLD:
                base_score = min(base_score + 5, 95)
            elif pcr < PCR_BEARISH_THRESHOLD:
                base_score = max(base_score - 5, 0)
            if days_to_exp <= MAX_PAIN_EXPIRY_WINDOW_DAYS and abs(pain_distance) > 3:
                if pain_distance > 0:
                    base_score = max(base_score - 6, 0)
                else:
                    base_score = min(base_score + 6, 95)

        # VWAP distance boost — mean-reversion filter using yesterday's
        # actual volume-weighted average price (not live intraday VWAP).
        # Catches stocks that are more overextended than a simple gap%
        # suggests, since VWAP reflects where most volume actually traded.
        vwap_dist = ann.get('vwap_distance', 0)
        if vwap_dist:
            if vwap_dist > VWAP_EXTENDED_THRESHOLD_PCT:
                base_score = max(base_score - 8, 0)
            elif vwap_dist < VWAP_DISCOUNT_THRESHOLD_PCT:
                base_score = min(base_score + 4, 95)

    # Subsidiary AGM upgrade — if parent owns majority, treat as Tier1
    if cat == "AGM_POSSIBLE":
        from kaal_config import SUBSIDIARY_MAP
        if symbol in SUBSIDIARY_MAP:
            cat, base_score, tier = "AGM_SUBSIDIARY", 65, 1
        else:
            return {**empty, "reason": "Routine AGM — no parent stake"}

    if cat == "SKIP":
        return {**empty, "reason": "Routine/low-value announcement"}

    # Only call LLM for Tier 1 and Tier 2
    # Skip LLM for Tier 2 with no details — rule score is enough, saves calls
    if tier == 2 and not details and cat not in ("VAGUE", "OUTCOME_OF_BOARD_MEETING"):
        return {
            "symbol": symbol, "subject": subject, "score": base_score,
            "tier": tier, "skip": base_score < SKIP_BELOW,
            "catalyst": cat, "key": subject[:80],
            "reason": f"Rule-based: {cat}. No details, LLM skipped.",
            "direction": "BULLISH", "source": source, "signal_sources": [source],
        }

    if tier <= 2:
        pdf_text = ""
        # Read PDF for Tier 1 OR vague announcements (to get actual content)
        if use_pdf and pdf_url and (tier == 1 or cat in ("VAGUE", "OUTCOME_OF_BOARD_MEETING")):
            pdf_text = download_pdf_text(pdf_url)

        # Stock-specific Tavily news for Tier1 — added June 24 2026
        # Fetches today's news for the specific stock to give LLM more context
        stock_news_context = ""
        if tier == 1:
            try:
                from kaal_config import TAVILY_API_KEY
                if TAVILY_API_KEY:
                    import requests as _req
                    company_name = ann.get("sm_name", symbol) if isinstance(ann, dict) else symbol
                    _resp = _req.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key":      TAVILY_API_KEY,
                            "query":        f"{company_name} {symbol} stock news today India",
                            "topic":        "news",
                            "days":         2,
                            "max_results":  3,
                            "search_depth": "basic",
                        },
                        timeout=8,
                    )
                    if _resp.status_code == 200:
                        _results = _resp.json().get("results", [])
                        if _results:
                            snippets = []
                            for r in _results:
                                t = r.get("title", "")
                                s = r.get("content", "")[:200]
                                snippets.append(f"- {t}: {s}")
                            stock_news_context = "\n\nRECENT NEWS FOR THIS STOCK:\n" + "\n".join(snippets)
            except Exception:
                pass

        # Staleness check disabled June 21 2026 — Tavily news search consistently
        # returned irrelevant articles even with company name + domain restriction
        # + advanced depth. Relying instead on CLOSED_OPEN_OFFERS static map
        # (kaal_config.py) and signal_history.json days_old/pct_change tracking,
        # both of which are proven reliable and cost zero extra API credits.
        if False and tier == 1 and any(k in (subject+details).lower() for k in ["open offer","buyback","merger"]):
            try:
                from kaal_llm import search_staleness
                company_name = ann.get("sm_name", "") if isinstance(ann, dict) else ""
                stale_result = search_staleness(symbol, cat, company_name)
                if not stale_result.get("is_fresh", True):
                    return {
                        "symbol": symbol, "score": 10, "tier": 3,
                        "skip": True, "catalyst": cat,
                        "reason": f"STALE: {stale_result.get('note','')[:100]}",
                        "direction": "NEUTRAL", "source": source,
                        "signal_sources": [source],
                    }
            except Exception:
                pass

        # Use results-specific prompt for financial results
        results_keywords = [
            'financial result', 'outcome of board', 'results_beat',
            'results_miss', 'quarterly result', 'annual result'
        ]
        is_results = any(k in (subject + details).lower() for k in results_keywords)
        if is_results:
            prompt = _build_results_prompt(subject, details, pdf_text, macro_context)
        else:
            prompt = _build_prompt(subject, details, pdf_text, macro_context)
        prompt += stock_news_context
        llm = call_llm(prompt, fast=(tier == 2))

        if llm.get("_cap_reached"):
            # LLM budget exhausted for this run - previously this fell
            # through to the rule-based fallback below and returned the
            # SAME identical base_score for every capped announcement
            # (the "eight identical 72s" bug from July 9). Emitting
            # fake-precision numbers is worse than no score at all -
            # label it explicitly and exclude it from Tier1/Tier2 rather
            # than pretend it was meaningfully differentiated.
            return {
                "symbol":         symbol,
                "subject":        subject,
                "score":          0,
                "tier":           3,
                "skip":           True,
                "catalyst":       cat,
                "key":            details[:80] if details else subject,
                "reason":         "UNSCORED — LLM call cap reached this run, no differentiation available",
                "direction":      "BULLISH",
                "source":         source,
                "signal_sources": [source],
                "an_dt":          ann.get("an_dt", "") if isinstance(ann, dict) else "",
                "buyback_type":   ann.get("buyback_type", "NA") if isinstance(ann, dict) else "NA",
                "event_type":     ann.get("event_type", "MOMENTUM_CATALYST") if isinstance(ann, dict) else "MOMENTUM_CATALYST",
                "unscored":       True,
            }

        if llm:
            score = llm.get("score", base_score)

            # Re-apply buyback type cap AFTER LLM (LLM overrides our pre-cap)
            if isinstance(ann, dict) and ann.get('buyback_type') == 'TENDER':
                score = min(score, 55)
            elif isinstance(ann, dict) and ann.get('buyback_type') == 'OPEN_MARKET':
                score = max(score, 75)

            # Staleness penalty
            if not llm.get("is_fresh", True):
                score = min(score, 25)

            # Open offer price check — if offer price < market price, arbitrage is dead
            # NOTE: LLM can return "catalyst_type": null explicitly (key present,
            # value None), which bypasses .get()'s default arg entirely — that
            # crashed the July 10 morning run. Guard with `or` instead.
            catalyst_type = (llm.get("catalyst_type") or cat or "OTHER").upper()
            if "OPEN_OFFER" in catalyst_type:
                deal_val = llm.get("deal_value_cr", 0)
                offer_price = llm.get("offer_price", 0)
                if offer_price and offer_price > 0:
                    try:
                        from kaal_sources import check_liquidity
                        liq = check_liquidity(symbol)
                        # rough market price from liquidity check not available
                        # flag for manual check instead
                        pass
                    except Exception:
                        pass
                # If LLM says not fresh, hard cap
                if not llm.get("is_fresh", True):
                    score = min(score, 15)

            # Macro adjustment — skip for structural floor catalysts
            FLOOR_CATALYSTS = {"OPEN_OFFER", "BUYBACK", "BUY_BACK", "BUY-BACK", "TAKEOVER", "DELISTING"}
            catalyst_type = (llm.get("catalyst_type") or cat).upper()
            has_floor = any(fc in catalyst_type for fc in FLOOR_CATALYSTS)

            if macro_context and not has_floor:
                bias = macro_context.get("gift_nifty_bias", "Neutral")
                direction = llm.get("direction", "BULLISH")
                if bias == "Bearish" and direction == "BULLISH":
                    score = max(score - 12, 0)
                elif bias == "Bullish" and direction == "BULLISH":
                    score = min(score + 5, 100)
                elif bias == "Bearish" and direction == "BEARISH":
                    score = min(score + 5, 100)  # bearish setup confirmed by macro

            tier = 1 if score >= TIER1_MIN_SCORE else (2 if score >= TIER2_MIN_SCORE else 3)
            is_liquid = symbol in FNO_UNIVERSE_HINT
            liquidity_note = "" if is_liquid else " ⚠️ Verify liquidity before entry."

            pat_growth_pct = llm.get("pat_growth_pct") if is_results else None
            revenue_growth_pct = llm.get("revenue_growth_pct") if is_results else None
            if is_results and pat_growth_pct is not None and revenue_growth_pct is not None:
                an_dt_val = ann.get("an_dt", "") if isinstance(ann, dict) else ""
                quarter_label = _fiscal_quarter_label(an_dt_val)
                try:
                    record_result(symbol, quarter_label, pat_growth_pct, revenue_growth_pct)
                except Exception as e:
                    print(f"[SCORER] failed to record results history for {symbol}: {e}")

            return {
                "symbol":          symbol,
                "subject":         subject,
                "score":           score,
                "tier":            tier,
                "skip":            score < SKIP_BELOW,
                "catalyst":        llm.get("catalyst_type", cat),
                "direction":       llm.get("direction", "BULLISH"),
                "key":             llm.get("key_detail", subject[:80]),
                "reason":          llm.get("reason", "") + liquidity_note,
                "macro_note":      llm.get("macro_impact", ""),
                "value_cr":        llm.get("deal_value_cr", 0),
                "pdf_read":        bool(pdf_text),
                "source":          source,
                "signal_sources":  [source],
                "an_dt":           ann.get("an_dt", "") if isinstance(ann, dict) else "",
                "event_type":      ann.get("event_type", "MOMENTUM_CATALYST") if isinstance(ann, dict) else "MOMENTUM_CATALYST",
                "pat_growth_pct":       pat_growth_pct,
                "revenue_growth_pct":   revenue_growth_pct,
            }



    return {
        "symbol":         symbol,
        "subject":        subject,
        "score":          base_score,
        "tier":           tier,
        "skip":           base_score < SKIP_BELOW,
        "catalyst":       cat,
        "key":            details[:80] if details else subject,
        "reason":         f"Rule-based match: {cat}. No LLM used (low tier).",
        "direction":      "BULLISH",
        "source":         source,
        "signal_sources": [source],
        "an_dt":          ann.get("an_dt", "") if isinstance(ann, dict) else "",
        "buyback_type":   ann.get("buyback_type", "NA") if isinstance(ann, dict) else "NA",
        "event_type":     ann.get("event_type", "MOMENTUM_CATALYST") if isinstance(ann, dict) else "MOMENTUM_CATALYST",
    }


# ── BULK / BLOCK DEAL SCORER ─────────────────────────────────────────────────
