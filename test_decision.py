import sys
sys.path.insert(0, '.')
from kaal_decision.decide import apply_regime_filter, apply_momentum_filter, rank_decisions

base_pick = {"symbol": "TESTCO", "score": 80, "tier": 1, "reason": "some catalyst"}

calm_regime = {"vix": {"vix": 13.0, "regime": "NORMAL"}, "trend": {"efficiency_ratio": 0.8, "regime": "TRENDING"}}
result = apply_regime_filter(base_pick, calm_regime)
assert result["adjusted_score"] == 80.0
print("PASS: calm regime = no adjustment")

stressed_regime = {"vix": {"vix": 28.0, "regime": "HIGH"}, "trend": {"efficiency_ratio": 0.8, "regime": "TRENDING"}}
result = apply_regime_filter(base_pick, stressed_regime)
assert result["adjusted_score"] == 40.0
print("PASS: high VIX halves conviction")

choppy_and_stressed = {"vix": {"vix": 28.0, "regime": "HIGH"}, "trend": {"efficiency_ratio": 0.1, "regime": "CHOPPY"}}
result = apply_regime_filter(base_pick, choppy_and_stressed)
assert abs(result["adjusted_score"] - 80 * 0.5 * 0.7) < 0.01
print("PASS: VIX + choppy compound correctly")

after_regime = apply_regime_filter(base_pick, calm_regime)
outside_universe = apply_momentum_filter(after_regime, momentum_ranked_symbols={"OTHERCO"},
                                           momentum_universe_symbols={"OTHERCO", "THIRDCO"})
assert outside_universe["momentum_status"] == "NO_DATA"
assert outside_universe["adjusted_score"] == 80.0
print("PASS: stock outside momentum universe is untouched (NO_DATA != penalty)")

confirmed = apply_momentum_filter(after_regime, momentum_ranked_symbols={"TESTCO"},
                                    momentum_universe_symbols={"TESTCO"})
assert confirmed["momentum_status"] == "CONFIRMED"
assert confirmed["adjusted_score"] == 80 * 1.15
print("PASS: momentum confirmation boosts conviction")

weak = apply_momentum_filter(after_regime, momentum_ranked_symbols={"OTHERCO"},
                               momentum_universe_symbols={"TESTCO", "OTHERCO"})
assert weak["momentum_status"] == "WEAK"
assert weak["adjusted_score"] == 80 * 0.8
print("PASS: weak momentum downgrades conviction")

picks = [
    {"symbol": "STRONG_ALL_ROUND", "score": 70, "tier": 1},
    {"symbol": "HIGH_SCORE_BUT_RISKY", "score": 95, "tier": 1},
]
result = rank_decisions(
    picks, regime_state=choppy_and_stressed,
    momentum_ranked_symbols={"STRONG_ALL_ROUND"},
    momentum_universe_symbols={"STRONG_ALL_ROUND", "HIGH_SCORE_BUT_RISKY"},
    top_n=2,
)
assert result[0]["symbol"] == "STRONG_ALL_ROUND"
print("PASS: corroborated pick correctly outranks unconfirmed higher-score pick")

print("\nALL DECISION ENGINE TESTS PASSED")
