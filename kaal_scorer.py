"""
kaal_scorer.py
Scores every signal and builds a REASON CHAIN so you know WHY a stock is bullish/bearish.
Each scored dict now has:
  - score      : 0-100
  - tier       : 1 / 2 / 3
  - direction  : BULLISH / BEARISH / NEUTRAL
  - catalyst   : type of event
  - reason     : human-readable explanation (the "why")
  - signal_sources: list of what triggered it (announcement / bulk_deal / promoter / news)
"""
import re
from kaal_config import (
    NSE_SKIP_EXACT, NSE_SKIP_EXTRA, NSE_TIER1_EXACT, NSE_TIER2_EXACT,
    SKIP_SUBJECTS, SKIP_DETAILS,
    TIER1_DETAIL_KEYWORDS, TIER2_DETAIL_KEYWORDS,
    TIER1_SUBJECTS, TIER2_SUBJECTS,
    TIER1_MIN_SCORE, TIER2_MIN_SCORE, SKIP_BELOW,
    FNO_UNIVERSE_HINT,
)
from kaal_llm import call_llm
from kaal_sources import download_pdf_text


# ── RULE-BASED PRE-CLASSIFIER ─────────────────────────────────────────────────
def classify_announcement(subject: str, details: str) -> tuple:
    """Returns (category, base_score, tier)"""
    subj = subject.strip()
    subj_lower = subj.lower()
    det  = details.lower().strip()

    # Step 1: exact NSE desc match (highest precision)
    # AGM special case: if company is a subsidiary, don't skip — send to LLM
    if subj == "Shareholders meeting":
        return "AGM_POSSIBLE", 45, 2

    if subj in NSE_SKIP_EXACT:
        return "SKIP", 0, 3
    if subj in NSE_SKIP_EXTRA:
        return "SKIP", 0, 3

    # Disclosure under Takeover: skip all except genuine open offers
    if subj == "Disclosure under SEBI Takeover Regulations":
        det_low = det.lower()
        if any(kw in det_low for kw in ["open offer", "change of control"]):
            return "TAKEOVER_OPEN_OFFER", 70, 1
        return "SKIP", 0, 3

    if subj in NSE_TIER1_EXACT:
        cat = subj.upper().replace(" ", "_").replace("/","_")[:25]
        return cat, 72, 1
    if subj in NSE_TIER2_EXACT:
        cat = subj.upper().replace(" ", "_").replace("/","_")[:25]
        return cat, 50, 2

    # Step 2: keyword fallback for unknown desc values
    full = subj_lower + " " + det
    for kw in SKIP_SUBJECTS:
        if kw in subj_lower:
            return "SKIP", 0, 3
    for kw in SKIP_DETAILS:
        if kw in det:
            return "SKIP", 0, 3
    for kw in TIER1_DETAIL_KEYWORDS:
        if kw in full:
            cat = kw.upper().replace(" ", "_").replace("/", "_")[:20]
            return cat, 70, 1
    for kw in TIER2_DETAIL_KEYWORDS:
        if kw in full:
            cat = kw.upper().replace(" ", "_")[:20]
            return cat, 50, 2
    for kw in TIER1_SUBJECTS:
        if kw in subj_lower:
            return kw.upper().replace(" ", "_"), 68, 1
    for kw in TIER2_SUBJECTS:
        if kw in subj_lower:
            return kw.upper().replace(" ", "_"), 48, 2

    if len(subj.split()) <= 3:
        return "VAGUE", 40, 2
    return "GENERAL", 12, 3


# ── LLM SCORING PROMPT ───────────────────────────────────────────────────────
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
            results_keywords = ['financial result', 'outcome of board', 'quarterly result', 'annual result']
        is_results = any(k in (subject + details).lower() for k in results_keywords)
        if is_results:
            prompt = _build_results_prompt(subject, details, pdf_text, macro_context)
        else:
            prompt = _build_prompt(subject, details, pdf_text, macro_context)
        prompt += stock_news_context
        llm = call_llm(prompt, fast=(tier == 2))

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
            catalyst_type = llm.get("catalyst_type", cat).upper()
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
            catalyst_type = llm.get("catalyst_type", cat).upper()
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
    }


# ── BULK / BLOCK DEAL SCORER ─────────────────────────────────────────────────
def score_bulk_deal(deal: dict) -> dict:
    symbol    = (deal.get("SCRIP_NAME") or deal.get("symbol") or "").upper().strip()
    buy_sell  = (deal.get("BUYSELL") or deal.get("buy_sell") or "B").upper()
    qty       = int(deal.get("QTY") or deal.get("quantity_traded") or 0)
    price     = float(deal.get("PRICE") or deal.get("trade_price") or 0)
    client    = deal.get("CLIENT_NAME") or deal.get("client_name") or "Unknown"
    deal_type = deal.get("_deal_type", "BULK")
    value_cr  = round((qty * price) / 1e7, 2)

    # Block deals are more significant (negotiated, min ₹10Cr)
    base = 68 if deal_type == "BLOCK" else 52
    if value_cr > 100: base += 18
    elif value_cr > 50: base += 12
    elif value_cr > 10: base += 6

    direction = "BULLISH" if buy_sell == "B" else "BEARISH"
    action    = "buying" if buy_sell == "B" else "selling"

    reason = (
        f"Institutional {action} via {deal_type} deal: ₹{value_cr}Cr at ₹{price} by {client[:40]}. "
        f"{'Block deals are pre-negotiated large institutional moves — strong directional signal.' if deal_type == 'BLOCK' else 'Bulk deal shows concentrated institutional interest.'}"
    )

    score = min(base, 100)
    return {
        "symbol":          symbol,
        "score":           score,
        "tier":            1 if score >= TIER1_MIN_SCORE else 2,
        "skip":            not symbol or score < SKIP_BELOW,
        "catalyst":        f"{deal_type}_DEAL",
        "direction":       direction,
        "key":             f"{deal_type} {buy_sell} {qty:,} @ ₹{price} | {client[:35]}",
        "reason":          reason,
        "value_cr":        value_cr,
        "source":          "BSE_DEAL",
        "signal_sources":  ["INSTITUTIONAL_DEAL"],
    }


# ── PROMOTER ACTIVITY SCORER ─────────────────────────────────────────────────
def score_promoter_pit(pit_entry: dict) -> dict:
    """Score SEBI PIT (insider trading) data — promoter buy/sell."""
    symbol   = (pit_entry.get("symbol") or "").upper().strip()
    mode     = (pit_entry.get("acqMode") or "").strip()       # Market Purchase, Gift, etc.
    acquired = float(pit_entry.get("secAcq") or 0)
    disposed = float(pit_entry.get("secSale") or 0)
    name     = pit_entry.get("personName") or pit_entry.get("acqName") or "Promoter"

    if not symbol:
        return {"symbol": "", "skip": True, "score": 0}

    if acquired > 0 and disposed == 0:
        direction = "BULLISH"
        action    = f"buying {acquired:,.0f} shares"
        score     = 65
        reason    = (
            f"Promoter/Insider {name[:40]} is {action} via {mode}. "
            f"Insider buying = confidence in business outlook. Strong accumulation signal."
        )
    elif disposed > 0 and acquired == 0:
        direction = "BEARISH"
        action    = f"selling {disposed:,.0f} shares"
        score     = 55
        reason    = (
            f"Promoter/Insider {name[:40]} is {action} via {mode}. "
            f"Insider selling can signal valuation concerns or funding needs. Watch for confirmation."
        )
    else:
        return {"symbol": symbol, "skip": True, "score": 0}



    return {
        "symbol":         symbol,
        "score":          score,
        "tier":           2,
        "skip":           False,
        "catalyst":       "PROMOTER_ACTIVITY",
        "direction":      direction,
        "key":            f"Promoter {action} via {mode}",
        "reason":         reason,
        "source":         "SEBI_PIT",
        "signal_sources": ["PROMOTER"],
    }


# ── NEWS VELOCITY SCORER (FIXED) ─────────────────────────────────────────────
# Old version: matched any 3-10 char uppercase word = matched "RBI", "GDP", "VIX", etc.
# New version: cross-references against known F&O universe + rejects generic terms
_NOISE_WORDS = {
    "RBI", "SEBI", "NSE", "BSE", "GDP", "INR", "USD", "VIX", "FII", "DII",
    "IPO", "NFO", "ETF", "FED", "IMF", "PMI", "CPI", "WPI", "GST", "EMI",
    "NPA", "ROE", "EPS", "PAT", "EBIT", "EBITDA", "QoQ", "YoY", "MoM",
    "INDIA", "NIFTY", "SENSEX", "MARKET", "STOCK", "SHARE", "TRADE",
    "BUY", "SELL", "LONG", "SHORT", "CALL", "PUT", "OPTION",
}



def score_budget_signals(news_articles: list) -> list:
    """
    Scan news for budget day sector allocation keywords.
    When found, flag sector beneficiary stocks as Tier1/Tier2.
    Only triggers on budget day or day after.
    """
    import os
    from datetime import datetime
    from kaal_config import BUDGET_PROXY_MAP

    dedup_file = os.path.join(os.path.dirname(__file__), "data", "budget_dedup.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    already_triggered = set()
    if os.path.exists(dedup_file):
        for line in open(dedup_file):
            line = line.strip()
            if "|" in line:
                date, trigger = line.split("|", 1)
                if date == today:
                    already_triggered.add(trigger)

    results = []
    found_triggers = set()

    for article in news_articles:
        text = (article.get("title","") + " " + article.get("summary","")).upper()
        for trigger, symbols in BUDGET_PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[BUDGET] Trigger: {trigger}")
                for i, symbol in enumerate(symbols):
                    score = 80 if i == 0 else 68  # lead stock scores higher
                    results.append({
                        "symbol":         symbol,
                        "score":          score,
                        "tier":           1 if i == 0 else 2,
                        "skip":           False,
                        "catalyst":       "BUDGET_PLAY",
                        "direction":      "BULLISH",
                        "key":            f"Budget sector play: {trigger}",
                        "reason":         f"Budget allocated for {trigger.lower()} sector. Direct beneficiary. Enter after confirmation at 9:30.",
                        "source":         "NEWS",
                        "signal_sources": ["NEWS"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\n")
        print(f"[BUDGET] {len(results)} stocks flagged from {len(found_triggers)} triggers")

    return results


def score_usfda_signals(nse_announcements: list, news_articles: list) -> list:
    """
    Special handler for USFDA approvals and warnings.
    Approval = Tier1 bullish + sympathy plays
    Warning/Import Alert = Tier1 bearish flag
    """
    from kaal_config import (
        USFDA_APPROVAL_KEYWORDS, USFDA_WARNING_KEYWORDS,
        USFDA_SYMPATHY_MAP
    )
    results = []

    for ann in nse_announcements:
        text = (ann.get("desc","") + " " + ann.get("attchmntText","")).upper()
        symbol = ann.get("symbol","")

        # Check approval
        if any(kw in text for kw in USFDA_APPROVAL_KEYWORDS):
            results.append({
                "symbol":         symbol,
                "score":          85,
                "tier":           1,
                "skip":           False,
                "catalyst":       "USFDA_APPROVAL",
                "direction":      "BULLISH",
                "key":            f"USFDA approval — fresh catalyst",
                "reason":         "USFDA approval = immediate re-rating. Strong intraday move expected. Enter on pullback after gap-up.",
                "source":         "NSE",
                "signal_sources": ["NSE"],
                        "an_dt":          ann.get("an_dt", ""),
                "offer_price":    0,
                "is_fresh":       True,
            })
            # Add sympathy plays
            for peer in USFDA_SYMPATHY_MAP.get(symbol, []):
                results.append({
                    "symbol":         peer,
                    "score":          65,
                    "tier":           2,
                    "skip":           False,
                    "catalyst":       "USFDA_SYMPATHY",
                    "direction":      "BULLISH",
                    "key":            f"USFDA sympathy — {symbol} approval benefits sector",
                    "reason":         f"Peer {symbol} got USFDA approval. Sector sentiment positive. Watch for spillover.",
                    "source":         "NSE",
                    "signal_sources": ["NSE"],
                        "an_dt":          ann.get("an_dt", ""),
                    "offer_price":    0,
                    "is_fresh":       True,
                })

        # Check warning/import alert
        if any(kw in text for kw in USFDA_WARNING_KEYWORDS):
            results.append({
                "symbol":         symbol,
                "score":          10,
                "tier":           3,
                "skip":           True,
                "catalyst":       "USFDA_WARNING",
                "direction":      "BEARISH",
                "key":            f"USFDA WARNING/IMPORT ALERT — AVOID",
                "reason":         "USFDA warning = -15 to -25% move. Avoid all long positions. Consider short if allowed.",
                "source":         "NSE",
                "signal_sources": ["NSE"],
                        "an_dt":          ann.get("an_dt", ""),
                "offer_price":    0,
                "is_fresh":       True,
            })

    if results:
        approvals = [r for r in results if r["catalyst"] == "USFDA_APPROVAL"]
        warnings  = [r for r in results if r["catalyst"] == "USFDA_WARNING"]
        print(f"[USFDA] {len(approvals)} approvals, {len(warnings)} warnings, {len(results)} total signals")

    return results


def score_bulk_buying(clean_buys: list) -> list:
    """
    Scores clean net bulk-deal buys (no same-day offsetting sell)
    as Tier2 institutional accumulation signals.
    Fund/institution buyers score higher than individual/unknown entities.
    """
    results = []
    for d in clean_buys:
        symbol  = d.get("symbol", "")
        qty     = d.get("qty", 0)
        price   = d.get("price", 0)
        client  = d.get("client", "")
        is_fund = d.get("is_fund", False)

        if not symbol or qty < 50000:
            continue

        score = 62 if is_fund else 55
        value_cr = round((qty * price) / 1e7, 2) if price else 0

        results.append({
            "symbol":         symbol,
            "score":          score,
            "tier":           2,
            "skip":           False,
            "catalyst":       "BULK_BUYING",
            "direction":      "BULLISH",
            "key":            f"Net bulk buy: {qty:,} shares (~Rs {value_cr}Cr) by {client[:30]}",
            "reason":         f"{'Institutional' if is_fund else 'Large'} accumulation detected via NSE bulk deals. No offsetting sell same day. Confirm with price action before entry.",
            "source":         "NSE_BULK",
            "signal_sources": ["NSE_BULK"],
        })

    if results:
        fund_count = sum(1 for r in results if "Institutional" in r["reason"])
        print(f"[BULK] {len(results)} accumulation signals ({fund_count} from known funds)")

    return results


def score_negative_proxy(news_articles: list) -> list:
    """
    Scan news for negative proxy triggers.
    When found, flag affected stocks as BEARISH with score penalty.
    """
    import os
    from datetime import datetime
    from kaal_config import NEGATIVE_PROXY_MAP

    dedup_file = os.path.join(os.path.dirname(__file__), "data", "neg_proxy_dedup.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    already_triggered = set()
    if os.path.exists(dedup_file):
        for line in open(dedup_file):
            line = line.strip()
            if "|" in line:
                date, trigger = line.split("|", 1)
                if date == today:
                    already_triggered.add(trigger)

    results = []
    found_triggers = set()

    for article in news_articles:
        text = (article.get("title","") + " " + article.get("summary","")).upper()
        for trigger, symbols in NEGATIVE_PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[NEG_PROXY] Trigger: {trigger}")
                for symbol in symbols:
                    results.append({
                        "symbol":         symbol,
                        "score":          20,
                        "tier":           3,
                        "skip":           True,
                        "catalyst":       "NEGATIVE_PROXY",
                        "direction":      "BEARISH",
                        "key":            f"AVOID — {trigger} = sector headwind",
                        "reason":         f"Negative proxy: {trigger} news hurts {symbol}. Avoid long positions today.",
                        "source":         "NEG_PROXY",
                        "signal_sources": ["NEG_PROXY"],
                    })

    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\n")
        print(f"[NEG_PROXY] {len(results)} stocks flagged BEARISH")

    return results

def score_proxy_signals(news_articles: list, nse_announcements: list) -> list:
    """
    Scan news + announcements for proxy trigger keywords.
    When found, flag all indirect beneficiary stocks as Tier1.
    Deduplicates — only triggers once per keyword per day.
    """
    import os
    from datetime import datetime
    from kaal_config import PROXY_MAP

    # Load today already-triggered proxies
    dedup_file = os.path.join(os.path.dirname(__file__), "data", "proxy_dedup.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    today_dt = datetime.now()

    # Cooldown periods for different trigger types (days)
    COOLDOWN_DAYS = {
        "NSE IPO": 30,  # increased from 7 — NSE IPO is a long-running theme, re-firing every 7 days is noise
        "NSE DRHP": 7,
        "NSE LISTING": 3,
        "NSE IPO DRHP FILED": 30,    # once DRHP filed, next milestone is SEBI obs
        "NSE SEBI OBSERVATION": 30,  # once SEBI obs comes, next is price band
        "NSE IPO PRICE BAND": 7,
        "NSE IPO LISTING": 1,        # listing day fire every day
        "DEFAULT": 1,
    }

    already_triggered = set()
    if os.path.exists(dedup_file):
        for line in open(dedup_file):
            line = line.strip()
            if "|" in line:
                date_str, trigger = line.split("|", 1)
                try:
                    trigger_date = datetime.strptime(date_str, "%Y-%m-%d")
                    cooldown = COOLDOWN_DAYS.get(trigger, COOLDOWN_DAYS["DEFAULT"])
                    if (today_dt - trigger_date).days < cooldown:
                        already_triggered.add(trigger)
                except Exception:
                    pass

    # Fetch pre-open gap map for edge-consumed check
    try:
        from kaal_sources import fetch_preopen_gainers
        preopen_data = fetch_preopen_gainers()
        preopen_gap_map = {s["symbol"]: s["gap_pct"] for s in preopen_data}
    except Exception:
        preopen_gap_map = {}

    # Fetch signal history for days_old check
    import json
    history_file = os.path.join(os.path.dirname(__file__), "data", "signal_history.json")
    signal_history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                signal_history = json.load(f)
        except Exception:
            pass

    results = []
    found_triggers = set()

    # Check news articles
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    def _is_fresh_article(article: dict, max_hours: int = 36) -> bool:
        """Return True if article is within max_hours old."""
        pub = article.get("published", "")
        if not pub:
            return True  # no date = assume fresh (Tavily sometimes omits)
        try:
            pub_dt = parsedate_to_datetime(pub)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            hours_old = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
            return hours_old <= max_hours
        except Exception:
            return True

    for article in news_articles:
        if not _is_fresh_article(article):
            continue  # skip stale RSS articles
        text = (article.get("title", "") + " " + article.get("summary", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[PROXY] Trigger found: {trigger}")
                for symbol in symbols:
                    # Edge-consumed check
                    gap = preopen_gap_map.get(symbol, 0)
                    history = signal_history.get(symbol, {})
                    days_old = history.get("days_old", 0)

                    if gap > 8:
                        # Already gapped up hard today — edge consumed
                        print(f"[PROXY] {symbol} skipped — gap {gap:.1f}% too large, edge consumed")
                        continue
                    elif gap > 5 or days_old > 2:
                        # Partial move — downgrade to Tier2, lower score
                        score = 62
                        tier  = 2
                        note  = f"Partial move detected (gap {gap:.1f}%, {days_old}d old). Downgraded to Tier2."
                        print(f"[PROXY] {symbol} downgraded — gap {gap:.1f}%, days_old {days_old}")
                    else:
                        score = 78
                        tier  = 1
                        note  = f"Proxy play — {trigger} news benefits {symbol} indirectly. Check if stock already moved before entering."

                    results.append({
                        "symbol":         symbol,
                        "score":          score,
                        "tier":           tier,
                        "skip":           False,
                        "catalyst":       "PROXY_PLAY",
                        "direction":      "BULLISH",
                        "key":            f"Indirect beneficiary of: {trigger}",
                        "reason":         note,
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    # Check NSE announcements
    for ann in nse_announcements:
        text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[PROXY] Trigger in announcement: {trigger}")
                for symbol in symbols:
                    results.append({
                        "symbol":         symbol,
                        "score":          80,
                        "tier":           1,
                        "skip":           False,
                        "catalyst":       "PROXY_PLAY",
                        "direction":      "BULLISH",
                        "key":            f"NSE announcement triggers proxy: {trigger}",
                        "reason":         f"Proxy play — {trigger} announcement benefits {symbol}. Fresh catalyst. Enter on pullback after confirmation.",
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    # Save triggered proxies to dedup file
    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\n")
        print(f"[PROXY] Total proxy signals: {len(results)} from triggers: {found_triggers}")

    return results




def score_policy_signals(news_articles: list) -> list:
    """
    Detect government policy / trade protection catalysts from news.
    Examples: anti-dumping duty, PLI scheme approval, import duty, safeguard duty.
    These are NOT in NSE announcements — they come from Ministry/DGTR gazette.
    Scores as Tier1 POLICY_PROTECTION catalyst.
    """
    import os
    from datetime import datetime

    POLICY_TRIGGERS = {
        "ANTI_DUMPING": [
            "ANTI-DUMPING", "ANTIDUMPING", "ANTI DUMPING",
            "DGTR", "DIRECTORATE GENERAL OF TRADE REMEDIES",
            "DUMPING DUTY", "DUMPED IMPORTS",
        ],
        "SAFEGUARD_DUTY": [
            "SAFEGUARD DUTY", "SAFEGUARD TARIFF",
            "IMPORT DUTY HIKE", "CUSTOMS DUTY INCREASE",
        ],
        "PLI_APPROVAL": [
            "PLI SCHEME", "PRODUCTION LINKED INCENTIVE",
            "PLI APPROVED", "PLI BENEFICIARY",
        ],
        "TRADE_PROTECTION": [
            "IMPORT RESTRICTION", "IMPORT BAN",
            "MINIMUM IMPORT PRICE", "MIP IMPOSED",
            "COUNTERVAILING DUTY", "CVD IMPOSED",
        ],
    }

    POLICY_SECTOR_MAP = {
        "RUBBER": ["NOCIL"],
        "CHEMICAL": ["NOCIL", "TATACHEM", "DEEPAKNTR", "AARTI"],
        "TYRE": ["MRF", "CEATLTD", "APOLLOTYRE", "BALKRISIND"],
        "STEEL": ["TATASTEEL", "JSWSTEEL", "SAIL", "NMDC"],
        "ALUMINIUM": ["HINDALCO", "NALCO", "VEDL"],
        "TEXTILE": ["PAGEIND", "VARDHMAN", "TRIDENT"],
        "SOLAR": ["ADANIGREEN", "TATAPOWER", "SUZLON"],
        "CERAMIC": ["KAJARIA", "CERA", "SOMANYCER"],
        "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN"],
        "ELECTRONICS": ["DIXON", "AMBER", "KAYNES"],
        "TELECOM": ["TEJAS", "STLTECH", "HFCL", "KSOLVES"],
        "PAPER": ["TNPL", "WCOSIND"],
        "PLASTICS": ["SUPREMEIND", "ASTRAL"],
        "AGROCHEMICAL": ["PIIND", "RALLIS", "DHANUKA"],
    }

    SECTOR_DETECT = {
        "RUBBER": ["RUBBER", "VULCANI", "SULPHENAMIDE", "ACCELERATOR", "NOCIL"],
        "CHEMICAL": ["CHEMICAL", "SPECIALTY CHEM", "PIGMENT", "DYE"],
        "TYRE": ["TYRE", "TIRE", "RADIAL"],
        "STEEL": ["STEEL", "IRON", "HOT ROLLED", "COLD ROLLED"],
        "ALUMINIUM": ["ALUMINIUM", "ALUMINUM"],
        "TEXTILE": ["TEXTILE", "YARN", "FABRIC", "GARMENT"],
        "SOLAR": ["SOLAR", "PANEL", "MODULE", "PHOTOVOLTAIC"],
        "CERAMIC": ["CERAMIC", "TILE", "SANITARYWARE"],
        "PHARMA": ["API", "BULK DRUG", "FORMULATION"],
        "ELECTRONICS": ["ELECTRONICS", "PCB", "SEMICONDUCTOR"],
        "TELECOM": ["TELECOM EQUIPMENT", "TELECOMMUNICATION EQUIPMENT", "NETWORK EQUIPMENT", "5G EQUIPMENT", "OPTICAL FIBRE CABLE", "OFC"],
        "PAPER": ["PAPER", "NEWSPRINT", "PAPERBOARD"],
        "PLASTICS": ["PLASTIC", "PVC", "POLYMER"],
        "AGROCHEMICAL": ["AGROCHEMICAL", "PESTICIDE", "HERBICIDE", "FUNGICIDE"],
    }

    dedup_file = os.path.join(os.path.dirname(__file__), "data", "policy_dedup.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    already_triggered = set()
    if os.path.exists(dedup_file):
        for line in open(dedup_file):
            line = line.strip()
            if "|" in line:
                date, trigger = line.split("|", 1)
                if date == today:
                    already_triggered.add(trigger)

    results = []
    found_triggers = set()
    flagged_symbols_today = set()  # Fix 1: symbol-level dedup

    for article in news_articles:
        # Fix 2: freshness filter — skip articles older than 48 hours
        pub = article.get("published", "") or article.get("pub_date", "") or ""
        if pub:
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub)
                pub_dt = pub_dt.replace(tzinfo=None)
                age_hours = (datetime.now() - pub_dt).total_seconds() / 3600
                if age_hours > 96:  # 96h covers Thu gazette → Mon market reaction
                    continue
            except Exception:
                pass  # if can't parse date, allow through

        text = (article.get("title", "") + " " + article.get("summary", "")).upper()

        matched_policy = None
        for policy_type, keywords in POLICY_TRIGGERS.items():
            if any(kw in text for kw in keywords):
                matched_policy = policy_type
                break
        if not matched_policy:
            continue

        # PLI_APPROVAL needs company-specific trigger, not generic milestone
        if matched_policy == "PLI_APPROVAL":
            PLI_SPECIFIC = [
                "PLI APPROVED", "PLI SELECTED", "PLI ELIGIBLE",
                "PLI BENEFICIARY", "APPROVED UNDER PLI", "SELECTED UNDER PLI",
                "INCENTIVE APPROVED", "PLI APPLICATION APPROVED",
            ]
            if not any(kw in text for kw in PLI_SPECIFIC):
                continue

        matched_sectors = []
        for sector, sector_kws in SECTOR_DETECT.items():
            if any(kw in text for kw in sector_kws):
                matched_sectors.append(sector)

        if not matched_sectors:
            continue

        dedup_key = matched_policy + ":" + "+".join(sorted(matched_sectors))
        if dedup_key in already_triggered or dedup_key in found_triggers:
            continue
        found_triggers.add(dedup_key)

        headline = article.get("title", "")[:80]
        print(f"[POLICY] {matched_policy} | Sectors: {matched_sectors} | {headline}")

        beneficiary_stocks = []
        seen_symbols = set()
        for sector in matched_sectors:
            for sym in POLICY_SECTOR_MAP.get(sector, []):
                if sym not in seen_symbols:
                    beneficiary_stocks.append(sym)
                    seen_symbols.add(sym)

        for i, symbol in enumerate(beneficiary_stocks):
            if symbol in flagged_symbols_today:
                continue  # Fix 1: skip already flagged symbol
            flagged_symbols_today.add(symbol)
            score = 80 if i == 0 else 70
            results.append({
                "symbol":         symbol,
                "score":          score,
                "tier":           1 if i == 0 else 2,
                "skip":           False,
                "catalyst":       "POLICY_PROTECTION",
                "direction":      "BULLISH",
                "key":            f"{matched_policy} | {', '.join(matched_sectors)} sector | {headline}",
                "reason":         (
                    f"Government trade protection catalyst ({matched_policy.replace('_',' ')}) "
                    f"detected in news. Sector: {', '.join(matched_sectors)}. "
                    f"Domestic manufacturers benefit from reduced import competition. "
                    f"Enter only after 9:30 confirmation with volume."
                ),
                "source":         "NEWS",
                "signal_sources": [article.get("source", "NEWS")],
                "offer_price":    0,
                "is_fresh":       True,
            })

    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\n")
        print(f"[POLICY] {len(results)} stocks flagged from {len(found_triggers)} policy triggers")

    return results

def score_news_velocity(articles: list, known_symbols: set = None) -> list:
    """
    Count stock mentions across RSS + Tavily + Serper articles.
    Extracts stock symbols from titles and summaries.
    Only returns signals for stocks in F&O universe or known_symbols.
    """
    from collections import Counter
    if known_symbols is None:
        known_symbols = FNO_UNIVERSE_HINT

    mentions  = Counter()
    titles    = {}
    summaries = {}
    sources   = {}

    for a in articles:
        # Search both title and summary for stock names
        text = (a.get("title", "") + " " + a.get("summary", "")).upper()
        src  = a.get("source", "RSS")
        for word in re.findall(r'\b[A-Z]{3,12}\b', text):
            if word in _NOISE_WORDS:
                continue
            if word in known_symbols:
                mentions[word] += 1
                titles[word]    = a.get("title", "")
                summaries[word] = a.get("summary", "")[:150]
                if word not in sources:
                    sources[word] = set()
                sources[word].add(src)

    results = []
    for symbol, count in mentions.items():
        if count >= 2:
            # Higher score if mentioned in Tavily/Serper (active search = stronger signal)
            active_sources = sources.get(symbol, set())
            base  = 42 if "TAVILY" in active_sources or "SERPER" in active_sources else 36
            score = min(base + count * 4, 62)  # hard cap 62 — always Tier2
            src_list = list(active_sources)

            # Hard cap — news momentum never Tier1
            score = min(score, 62)
            results.append({
                "symbol":         symbol,
                "score":          score,
                "tier":           2,
                "skip":           False,
                "catalyst":       "NEWS_MOMENTUM",
                "direction":      "NEUTRAL",
                "key":            f"Mentioned {count}x across {', '.join(src_list)}: {titles[symbol][:70]}",
                "reason":         (
                    f"Stock appearing in {count} news articles today across {', '.join(src_list)}. "
                    f"Snippet: {summaries.get(symbol,'')[:100]}. "
                    f"Confirm with price action — news momentum alone is not a buy signal."
                ),
                "source":         "NEWS",
                "signal_sources": src_list if src_list else ["NEWS"],
            })

    results.sort(key=lambda x: -x["score"])
    return results
