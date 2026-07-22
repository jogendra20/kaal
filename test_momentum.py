"""
Synthetic-data tests. No network calls - builds fake OHLCV series with
known properties and checks the factors respond the way the math says
they should.
"""
import random
from kaal_momentum import factors_eod as fe
from kaal_momentum.providers import OHLCDataProvider
from kaal_momentum.rank import compute_universe_scores


def make_bars(n, start=100.0, daily_drift=0.0, daily_vol=0.01, seed=0):
    random.seed(seed)
    bars = []
    price = start
    for i in range(n):
        ret = daily_drift + random.gauss(0, daily_vol)
        o = price
        price = price * (1 + ret)
        h = max(o, price) * (1 + abs(random.gauss(0, daily_vol / 3)))
        l = min(o, price) * (1 - abs(random.gauss(0, daily_vol / 3)))
        vol = int(random.gauss(500000, 50000))
        bars.append({"date": f"d{i}", "open": o, "high": h, "low": l,
                      "close": price, "volume": max(vol, 1000)})
    return bars


def test_relative_strength_direction():
    strong = make_bars(60, daily_drift=0.01, seed=1)
    flat = make_bars(60, daily_drift=0.0, seed=2)
    rs = fe.relative_strength(strong, flat)
    assert rs is not None and rs > 0, f"expected positive RS, got {rs}"
    rs_rev = fe.relative_strength(flat, strong)
    assert rs_rev < 0, f"expected negative RS in reverse, got {rs_rev}"
    print("PASS test_relative_strength_direction", rs, rs_rev)


def test_relative_strength_insufficient_history():
    short = make_bars(3)
    bench = make_bars(60)
    assert fe.relative_strength(short, bench) is None
    print("PASS test_relative_strength_insufficient_history")


def test_atr_expansion_detects_regime_change():
    quiet = make_bars(80, daily_vol=0.003, seed=3)
    volatile_tail = make_bars(20, start=quiet[-1]["close"], daily_vol=0.03, seed=4)
    combined = quiet[:-20] + volatile_tail
    expansion = fe.atr_expansion(combined)
    assert expansion is not None and expansion > 1.0, f"expected >1 expansion, got {expansion}"
    print("PASS test_atr_expansion_detects_regime_change", expansion)


def test_trend_continuation_penalizes_downtrend_bounce():
    downtrend = make_bars(60, daily_drift=-0.01, seed=5)
    uptrend = make_bars(60, daily_drift=0.01, seed=6)
    t_down = fe.trend_continuation(downtrend)
    t_up = fe.trend_continuation(uptrend)
    assert t_up > t_down, f"uptrend should score higher: up={t_up} down={t_down}"
    print("PASS test_trend_continuation_penalizes_downtrend_bounce", t_up, t_down)


def test_liquidity_uses_median_not_mean():
    bars = make_bars(20, seed=7)
    bars[-1]["volume"] = 50_000_000
    score = fe.liquidity_score(bars)
    normal_day_turnover = bars[-2]["close"] * bars[-2]["volume"] / 1e7
    assert abs(score - normal_day_turnover) < normal_day_turnover, (
        "median liquidity score got dragged too far by one outlier day")
    print("PASS test_liquidity_uses_median_not_mean", score)


class FakeProvider(OHLCDataProvider):
    def __init__(self, series: dict, index_bars: list):
        self.series = series
        self.index_bars = index_bars

    def get_daily_bars(self, symbol, n, as_of_date=None):
        return self.series.get(symbol, [])[-n:]

    def get_index_bars(self, index_symbol, n, as_of_date=None):
        return self.index_bars[-n:]


def test_rank_end_to_end_orders_strong_stock_first():
    index_bars = make_bars(150, daily_drift=0.0003, seed=10)
    strong = make_bars(150, daily_drift=0.006, seed=11)
    weak = make_bars(150, daily_drift=-0.002, seed=12)
    provider = FakeProvider({"STRONG": strong, "WEAK": weak}, index_bars)
    result = compute_universe_scores(["STRONG", "WEAK"], provider)
    symbols_in_order = [r["symbol"] for r in result]
    assert symbols_in_order[0] == "STRONG", f"expected STRONG first, got {symbols_in_order}"
    print("PASS test_rank_end_to_end_orders_strong_stock_first", result[0]["score"], result[1]["score"])


def test_rank_drops_insufficient_history_symbol():
    index_bars = make_bars(150, seed=20)
    ok = make_bars(150, seed=21)
    too_short = make_bars(10, seed=22)
    provider = FakeProvider({"OK": ok, "SHORT": too_short}, index_bars)
    from kaal_momentum.rank import build_watchlist
    wl = build_watchlist(["OK", "SHORT"], provider, top_n=3)
    assert "SHORT" in wl["excluded"], wl
    assert any(r["symbol"] == "OK" for r in wl["ranked"])
    print("PASS test_rank_drops_insufficient_history_symbol", wl["excluded"])


if __name__ == "__main__":
    test_relative_strength_direction()
    test_relative_strength_insufficient_history()
    test_atr_expansion_detects_regime_change()
    test_trend_continuation_penalizes_downtrend_bounce()
    test_liquidity_uses_median_not_mean()
    test_rank_end_to_end_orders_strong_stock_first()
    test_rank_drops_insufficient_history_symbol()
    print("\nALL TESTS PASSED")
