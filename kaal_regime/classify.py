"""
kaal_regime/classify.py
Pure classification functions over data KAAL already fetches elsewhere -
no new network calls. Each function takes already-available data and
returns a label/dict, nothing more. Does NOT touch scoring - combining
regime with Momentum/Catalyst scores is a Decision Engine (Phase 3)
decision, not this file's job.

Every function returns None when there isn't enough data to classify,
same discipline as kaal_momentum's factors - a missing/uncertain regime
read should never silently look like a specific regime.
"""
import math

from kaal_config import VIX_HIGH


def classify_vix(vix: float, high_threshold: float = VIX_HIGH, low_threshold: float = 12.0) -> dict:
    """
    Reuses VIX_HIGH from kaal_config (already the threshold live scoring
    uses for "Tier 1 only, half size") so the regime read and the
    existing risk logic agree on what "high" means.
    low_threshold=12 flags complacency (unusually low vol) as its own
    state - a market that quiet is itself information, often preceding
    a vol expansion.
    """
    if vix is None:
        return None
    if vix >= high_threshold:
        label = "HIGH"
    elif vix <= low_threshold:
        label = "LOW"
    else:
        label = "NORMAL"
    return {"vix": vix, "regime": label}


def classify_expiry_proximity(days_to_expiry, near_threshold: int = 2) -> dict:
    """
    days_to_expiry: from kaal_sources.fetch_option_chain's existing
    parsing of live NSE data - not recomputed from a hardcoded calendar
    rule, since NSE's own expiry-day conventions have changed before and
    trusting live option-chain data is more robust than assuming a fixed
    weekday.
    """
    if days_to_expiry is None:
        return None
    return {
        "days_to_expiry": days_to_expiry,
        "is_expiry_day": days_to_expiry == 0,
        "is_near_expiry": 0 <= days_to_expiry <= near_threshold,
    }


def efficiency_ratio(bars: list, period: int = 14) -> float:
    """
    Kaufman's Efficiency Ratio: net directional movement over `period`
    bars, divided by the total path length traveled to get there.
    Ranges 0-1. Near 1 = trending. Near 0 = choppy (lots of back-and-forth
    for little net progress). Returns None if insufficient bars.
    """
    if len(bars) < period + 1:
        return None
    closes = [b["close"] for b in bars[-(period + 1):]]
    net_change = abs(closes[-1] - closes[0])
    path_length = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path_length == 0:
        return None
    return net_change / path_length


def classify_trend_choppy(bars: list, period: int = 14, trending_threshold: float = 0.3) -> dict:
    """
    trending_threshold=0.3 is a commonly-used starting point for
    Kaufman's ER - not backtested specifically for NSE/Nifty yet.
    Treat as a reasonable default to validate, not a settled number.
    """
    er = efficiency_ratio(bars, period)
    if er is None:
        return None
    return {
        "efficiency_ratio": round(er, 4),
        "regime": "TRENDING" if er >= trending_threshold else "CHOPPY",
    }


def classify_sector_rotation(sector_scores: dict, top_n: int = 3) -> dict:
    """
    sector_scores: {sector_name: pct_change}, same shape
    fetch_sector_strength() already returns.
    breadth_pct: what fraction of sectors are positive today - broad
    participation reads very differently from a narrow rally carried by
    2-3 sectors while most are red.
    """
    if not sector_scores:
        return None
    ordered = sorted(sector_scores.items(), key=lambda kv: kv[1], reverse=True)
    positive = sum(1 for _, chg in sector_scores.items() if chg > 0)
    return {
        "leading": ordered[:top_n],
        "lagging": ordered[-top_n:],
        "breadth_pct": round(positive / len(sector_scores) * 100, 1),
    }


def classify_breadth(today_bhavcopy: dict, prior_bhavcopy: dict) -> dict:
    """
    today_bhavcopy / prior_bhavcopy: the full {symbol: {..., "close":}}
    dicts already produced by NSEBhavcopyProvider's per-day fetch - this
    reuses data already downloaded for the momentum engine, not a new
    fetch. Advances/declines measured close-vs-prior-close (the standard
    definition), only over symbols present in both days.
    """
    if not today_bhavcopy or not prior_bhavcopy:
        return None
    common = set(today_bhavcopy) & set(prior_bhavcopy)
    if not common:
        return None
    advancing = declining = unchanged = 0
    for sym in common:
        today_close = today_bhavcopy[sym]["close"]
        prior_close = prior_bhavcopy[sym]["close"]
        if today_close > prior_close:
            advancing += 1
        elif today_close < prior_close:
            declining += 1
        else:
            unchanged += 1
    total = len(common)
    return {
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "total": total,
        "advance_decline_ratio": round(advancing / declining, 2) if declining else None,
        "pct_advancing": round(advancing / total * 100, 1),
    }


def classify_market_liquidity(today_total_turnover_cr: float, trailing_turnovers_cr: list) -> dict:
    """
    Same "ratio to own trailing average" pattern as
    kaal_momentum.factors_eod.atr_expansion, applied market-wide: today's
    total EQ turnover vs its own recent average. A drop below trailing
    average (not a fixed cutoff) flags a genuinely thin session, since
    what counts as "low" turnover drifts over time.
    """
    if not trailing_turnovers_cr or today_total_turnover_cr is None:
        return None
    avg = sum(trailing_turnovers_cr) / len(trailing_turnovers_cr)
    if avg == 0:
        return None
    ratio = today_total_turnover_cr / avg
    return {
        "today_turnover_cr": round(today_total_turnover_cr, 1),
        "trailing_avg_turnover_cr": round(avg, 1),
        "ratio_to_trailing_avg": round(ratio, 3),
        "regime": "LOW_LIQUIDITY" if ratio < 0.6 else "NORMAL",
    }
