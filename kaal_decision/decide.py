"""
kaal_decision/decide.py
Catalyst-led decision layer. The catalyst score is the primary driver.
Momentum and Regime can only ADJUST conviction up or down from that
starting point - neither can promote a stock the catalyst engine didn't
already flag, and neither can override catalyst entirely.
"""

CONVICTION_MULTIPLIERS = {
    "vix_high":        0.5,
    "choppy":          0.7,
    "momentum_confirmed": 1.15,
    "momentum_weak":   0.8,
}


def apply_regime_filter(catalyst_pick: dict, regime_state: dict) -> dict:
    result = dict(catalyst_pick)
    multiplier = 1.0
    notes = []

    vix = (regime_state or {}).get("vix")
    if vix and vix.get("regime") == "HIGH":
        multiplier *= CONVICTION_MULTIPLIERS["vix_high"]
        notes.append(f"VIX high ({vix['vix']:.1f}) - conviction reduced")

    trend = (regime_state or {}).get("trend")
    if trend and trend.get("regime") == "CHOPPY":
        multiplier *= CONVICTION_MULTIPLIERS["choppy"]
        notes.append(f"Market choppy (efficiency ratio {trend['efficiency_ratio']}) - conviction reduced")

    result["conviction_multiplier"] = round(multiplier, 3)
    result["regime_notes"] = notes
    result["adjusted_score"] = round(catalyst_pick.get("score", 0) * multiplier, 2)
    return result


def apply_momentum_filter(catalyst_pick: dict, momentum_ranked_symbols: set,
                           momentum_universe_symbols: set) -> dict:
    result = dict(catalyst_pick)
    symbol = catalyst_pick.get("symbol")
    multiplier = result.get("conviction_multiplier", 1.0)
    notes = list(result.get("regime_notes", []))

    if symbol in momentum_ranked_symbols:
        multiplier *= CONVICTION_MULTIPLIERS["momentum_confirmed"]
        notes.append("Momentum: confirmed (in today's momentum Top-N)")
        momentum_status = "CONFIRMED"
    elif symbol in momentum_universe_symbols:
        multiplier *= CONVICTION_MULTIPLIERS["momentum_weak"]
        notes.append("Momentum: weak (scored, but not in today's Top-N)")
        momentum_status = "WEAK"
    else:
        notes.append("Momentum: no data (outside current momentum test universe)")
        momentum_status = "NO_DATA"

    result["conviction_multiplier"] = round(multiplier, 3)
    result["regime_notes"] = notes
    result["momentum_status"] = momentum_status
    result["adjusted_score"] = round(catalyst_pick.get("score", 0) * multiplier, 2)
    return result


def rank_decisions(catalyst_picks: list, regime_state: dict,
                    momentum_ranked_symbols: set = None,
                    momentum_universe_symbols: set = None, top_n: int = 3) -> list:
    momentum_ranked_symbols = momentum_ranked_symbols or set()
    momentum_universe_symbols = momentum_universe_symbols or set()

    decided = []
    for pick in catalyst_picks:
        after_regime = apply_regime_filter(pick, regime_state)
        after_momentum = apply_momentum_filter(after_regime, momentum_ranked_symbols,
                                                 momentum_universe_symbols)
        decided.append(after_momentum)

    decided.sort(key=lambda p: p["adjusted_score"], reverse=True)
    return decided[:top_n]
