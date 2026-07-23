import sys
sys.path.insert(0, '.')
from kaal_regime import classify as rc

assert rc.classify_vix(25)["regime"] == "HIGH"
assert rc.classify_vix(15)["regime"] == "NORMAL"
assert rc.classify_vix(10)["regime"] == "LOW"
assert rc.classify_vix(None) is None
print("PASS: classify_vix")

assert rc.classify_expiry_proximity(0)["is_expiry_day"] is True
assert rc.classify_expiry_proximity(1)["is_near_expiry"] is True
assert rc.classify_expiry_proximity(10)["is_near_expiry"] is False
assert rc.classify_expiry_proximity(None) is None
print("PASS: classify_expiry_proximity")

trending_bars = [{"close": 100 + i} for i in range(20)]
er_trend = rc.efficiency_ratio(trending_bars, period=14)
assert abs(er_trend - 1.0) < 1e-9

choppy_bars = []
price = 100
for i in range(20):
    price += 5 if i % 2 == 0 else -5
    choppy_bars.append({"close": price})
er_choppy = rc.efficiency_ratio(choppy_bars, period=14)
assert er_choppy < 0.3
print("PASS: efficiency_ratio")

assert rc.classify_trend_choppy(trending_bars)["regime"] == "TRENDING"
assert rc.classify_trend_choppy(choppy_bars)["regime"] == "CHOPPY"
print("PASS: classify_trend_choppy")

sector_scores = {"IT": 2.5, "BANK": -1.2, "AUTO": 0.8, "METAL": 3.1, "PHARMA": -0.5}
rotation = rc.classify_sector_rotation(sector_scores, top_n=2)
assert rotation["leading"][0][0] == "METAL"
assert rotation["breadth_pct"] == 60.0
print("PASS: classify_sector_rotation")

today = {"A": {"close": 105}, "B": {"close": 98}, "C": {"close": 100}, "D": {"close": 110}}
prior = {"A": {"close": 100}, "B": {"close": 100}, "C": {"close": 100}, "D": {"close": 100}}
breadth = rc.classify_breadth(today, prior)
assert breadth["advancing"] == 2
assert breadth["pct_advancing"] == 50.0
print("PASS: classify_breadth")

liq_low = rc.classify_market_liquidity(400, [900, 950, 1000, 1050, 1100])
assert liq_low["regime"] == "LOW_LIQUIDITY"
print("PASS: classify_market_liquidity")

print("\nALL REGIME CLASSIFICATION TESTS PASSED")
