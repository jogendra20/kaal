"""
kaal_deterministic_scorers.py
Every scoring strategy that does NOT call the LLM: bulk deals, promoter
pit, budget/policy/USFDA signal keyword scoring, negative proxy, proxy
signals, news velocity. Pure rule-based math on structured input -
matches the project rule that LLM is for classification only, never
for scoring.
"""
from kaal_config import TIER1_MIN_SCORE, SKIP_BELOW, FNO_UNIVERSE_HINT

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
        from kaal_market_data import fetch_preopen_gainers
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
