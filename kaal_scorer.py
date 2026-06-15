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
    ctx = 'Subject: ' + subject + '\nDetails: ' + details[:600]
    if pdf_text:
        ctx += '\nPDF Excerpt:\n' + pdf_text[:3000]
    macro_str = ''
    if macro_context:
        macro_str = ('\nMARKET CONTEXT: VIX=' + str(macro_context.get('vix','N/A'))
            + ', GIFT Nifty=' + macro_context.get('gift_nifty_bias','Neutral')
            + ', SPX=' + str(macro_context.get('spx_chg',0)) + '%')
    rules = (
        'Scoring rules:\n'
        '- PAT growth >50% + no exceptional items + after-hours = 80-90\n'
        '- PAT growth 20-50% + no exceptional items = 60-75\n'
        '- PAT growth <20% or exceptional items = 30-50\n'
        '- Revenue miss despite PAT beat = penalize 10\n'
        '- Guidance cut = penalize 15\n'
        '- Large cap >20000Cr = penalize 10\n'
    )
    schema = (
        '{\n'
        '  "score": <0-100>,\n'
        '  "pat_growth_pct": <PAT YoY growth as number>,\n'
        '  "revenue_growth_pct": <Revenue YoY growth as number>,\n'
        '  "margin_expanded": <true/false>,\n'
        '  "exceptional_item": <true if one-time item inflated PAT>,\n'
        '  "dividend_announced": <true/false>,\n'
        '  "guidance_tone": "<POSITIVE|NEGATIVE|NEUTRAL|NONE>",\n'
        '  "is_beat": <true if PAT >20% and no exceptional items>,\n'
        '  "is_fresh": <true if announced after market hours>,\n'
        '  "catalyst_type": "RESULTS_BEAT",\n'
        '  "direction": "<BULLISH|BEARISH|NEUTRAL>",\n'
        '  "key": "<PAT +X% YoY, Revenue +X% YoY, margin expanded/contracted>",\n'
        '  "reason": "<two lines: why this will or will not move intraday>",\n'
        '  "skip_reason": "<if score < 40 why, else empty>",\n'
        '  "offer_price": 0\n'
        '}'
    )
    return (
        'You are an expert NSE/BSE intraday trader analyzing quarterly results.'
        + macro_str + '\n\n' + ctx
        + '\n\nReturn ONLY a JSON object:\n' + schema
        + '\n\n' + rules
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

    # Pre-open gap check
    preopen_gap = ann.get('preopen_gap', 0.0) if isinstance(ann, dict) else 0.0
    if preopen_gap > 8.0:
        return {**empty, 'reason': f'Gap already {preopen_gap:.1f}% — edge consumed, skip'}

    cat, base_score, tier = classify_announcement(subject, details)
    # Order wins hard cap — never Tier1
    if cat in ('BAGGING_RECEIVING_OF_ORDE', 'AWARDING_OF_ORDER(S)_CONT', 'ORDER_WIN'):
        base_score = min(base_score, 65)
        tier = max(tier, 2)

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

        # Staleness check for open offers via Tavily/Serper
        if tier == 1 and any(k in (subject+details).lower() for k in ["open offer","buyback","merger"]):
            try:
                from kaal_llm import search_staleness
                stale_result = search_staleness(symbol, cat)
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
        llm = call_llm(prompt, fast=(tier == 2))

        if llm:
            score = llm.get("score", base_score)

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
            }

    # Boost if pre-open gap confirms catalyst
    if 2.0 <= preopen_gap <= 8.0:
        base_score = min(base_score + 8, 95)
        signals.append(f'Pre-open gap +{preopen_gap:.1f}% confirms catalyst')

    # Sector strength boost/penalty
    if isinstance(ann, dict):
        if ann.get('sector_hot'):
            base_score = min(base_score + 6, 95)
            signals.append('Sector tailwind — hot sector today')
        if ann.get('sector_cold'):
            base_score = max(base_score - 8, 0)
            signals.append('Sector headwind — cold sector today')

    # Hard cap for news momentum — never Tier1 regardless of boosts
    if cat == 'NEWS_MOMENTUM':
        base_score = min(base_score, 62)

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

    # Boost if pre-open gap confirms catalyst
    if 2.0 <= preopen_gap <= 8.0:
        base_score = min(base_score + 8, 95)
        signals.append(f'Pre-open gap +{preopen_gap:.1f}% confirms catalyst')

    # Sector strength boost/penalty
    if isinstance(ann, dict):
        if ann.get('sector_hot'):
            base_score = min(base_score + 6, 95)
            signals.append('Sector tailwind — hot sector today')
        if ann.get('sector_cold'):
            base_score = max(base_score - 8, 0)
            signals.append('Sector headwind — cold sector today')

    # Hard cap for news momentum — never Tier1 regardless of boosts
    if cat == 'NEWS_MOMENTUM':
        base_score = min(base_score, 62)

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
