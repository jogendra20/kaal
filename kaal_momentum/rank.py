"""
kaal_momentum/rank.py
Combines factor scores across a universe into a ranked list.

Method: percentile-rank each factor across the universe (0-1), then a
weighted average of percentiles - not a weighted sum of raw z-scores.
NSE mid/small-caps are illiquid enough that one stock can have a
wildly outlying raw factor value and a z-score approach lets it
dominate the composite. Percentile rank caps every factor's influence
at "how it compares to peers today". Trade-off: throws away magnitude
information - acceptable since Phase 1's goal is top 1-3 candidates,
not a smooth continuous score.
"""
from kaal_momentum import factors_eod as fe

DEFAULT_WEIGHTS = {
    "rs_vs_index":   0.25,
    "rs_vs_sector":  0.20,
    "atr_expansion": 0.20,
    "trend":         0.15,
    "liquidity":     0.10,
    "volatility":    0.10,
}

MIN_BARS_REQUIRED = 71  # atr_expansion needs atr_period(14)+baseline(50)+1


def _percentile_ranks(values: dict) -> dict:
    valid = {s: v for s, v in values.items() if v is not None}
    if not valid:
        return {}
    ordered = sorted(valid.items(), key=lambda kv: kv[1])
    n = len(ordered)
    out = {}
    for i, (sym, _) in enumerate(ordered):
        out[sym] = i / (n - 1) if n > 1 else 1.0
    return out


def _band_percentile_ranks(values: dict, target_pctl: float = 0.6) -> dict:
    raw = _percentile_ranks(values)
    return {s: 1 - abs(p - target_pctl) / max(target_pctl, 1 - target_pctl)
            for s, p in raw.items()}


def compute_universe_scores(symbols: list, provider, index_symbol: str = "NIFTY 50",
                             sector_map: dict = None, weights: dict = None,
                             lookback: int = 120) -> list:
    weights = dict(weights or DEFAULT_WEIGHTS)
    index_bars = provider.get_index_bars(index_symbol, lookback)

    bars_by_symbol = {}
    for sym in symbols:
        bars = provider.get_daily_bars(sym, lookback)
        if len(bars) >= MIN_BARS_REQUIRED:
            bars_by_symbol[sym] = bars

    sector_bars_cache = {}
    if sector_map:
        for sector in set(sector_map.values()):
            members = [s for s in bars_by_symbol if sector_map.get(s) == sector]
            if len(members) < 2:
                continue
            n = min(len(bars_by_symbol[m]) for m in members)
            proxy = []
            for i in range(-n, 0):
                avg_close = sum(bars_by_symbol[m][i]["close"] for m in members) / len(members)
                proxy.append({"close": avg_close})
            sector_bars_cache[sector] = proxy

    raw = {
        "rs_vs_index": {}, "rs_vs_sector": {}, "atr_expansion": {},
        "trend": {}, "liquidity": {}, "volatility": {},
    }
    for sym, bars in bars_by_symbol.items():
        raw["rs_vs_index"][sym] = fe.relative_strength(bars, index_bars)
        sector = sector_map.get(sym) if sector_map else None
        sector_bars = sector_bars_cache.get(sector)
        raw["rs_vs_sector"][sym] = fe.relative_strength(bars, sector_bars) if sector_bars else None
        raw["atr_expansion"][sym] = fe.atr_expansion(bars)
        raw["trend"][sym] = fe.trend_continuation(bars)
        raw["liquidity"][sym] = fe.liquidity_score(bars)
        raw["volatility"][sym] = fe.volatility(bars)

    if not sector_map or not any(v is not None for v in raw["rs_vs_sector"].values()):
        weights["rs_vs_index"] += weights.pop("rs_vs_sector", 0)
        weights.pop("rs_vs_sector", None)

    pctl = {}
    for factor in list(weights):
        if factor == "volatility":
            pctl[factor] = _band_percentile_ranks(raw[factor])
        else:
            pctl[factor] = _percentile_ranks(raw[factor])

    results = []
    for sym in bars_by_symbol:
        total_weight = 0.0
        score = 0.0
        contributing_factors = {}
        for factor, w in weights.items():
            p = pctl.get(factor, {}).get(sym)
            if p is None:
                continue
            score += w * p
            total_weight += w
            contributing_factors[factor] = round(p, 3)
        if total_weight == 0:
            continue
        results.append({
            "symbol": sym,
            "score": round(score / total_weight, 4),
            "factors": contributing_factors,
            "raw": {f: raw[f][sym] for f in raw if raw[f].get(sym) is not None},
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def build_watchlist(symbols: list, provider, top_n: int = 3,
                     max_per_sector: int = 1, **kwargs) -> dict:
    """
    max_per_sector=1 (default): walk the full ranked list best-first and
    take the top_n, skipping any stock whose sector already has a pick -
    raw percentile ranking within one universe can't tell "this stock
    genuinely outperformed" apart from "this stock's whole sector moved
    together". Needs sector_map passed through kwargs; with no
    sector_map, this is a no-op (falls back to plain top_n).
    Set max_per_sector=None to disable and take the raw top_n instead.
    """
    sector_map = kwargs.get("sector_map")
    scores = compute_universe_scores(symbols, provider, **kwargs)
    ranked_symbols = {r["symbol"] for r in scores}
    excluded = [s for s in symbols if s not in ranked_symbols]

    skipped_for_diversity = []
    if max_per_sector and sector_map:
        picked = []
        sector_counts = {}
        for r in scores:
            sector = sector_map.get(r["symbol"], "UNKNOWN")
            if sector_counts.get(sector, 0) >= max_per_sector:
                skipped_for_diversity.append(r["symbol"])
                continue
            picked.append(r)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if len(picked) >= top_n:
                break
        ranked = picked
    else:
        ranked = scores[:top_n]

    return {"ranked": ranked, "excluded": excluded,
            "skipped_for_sector_diversity": skipped_for_diversity}
