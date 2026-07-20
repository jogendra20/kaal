"""
kaal_momentum/factors_eod.py
Momentum factors computable from daily OHLCV bars alone - no intraday
feed required. Each function takes bars (see providers.py for shape)
and returns a single float. None of them rank or weight anything;
that's rank.py's job. None of them touch an LLM.

Every function returns None (not 0) when there isn't enough history
to compute a real number - 0 would silently look like "no momentum"
instead of "insufficient data", and those are very different things
to rank on.
"""
import math


def _returns(bars: list, k: int):
    if len(bars) < k + 1:
        return None
    c_now, c_then = bars[-1]["close"], bars[-1 - k]["close"]
    if c_then == 0:
        return None
    return c_now / c_then - 1


def relative_strength(stock_bars: list, benchmark_bars: list,
                       short_k: int = 5, long_k: int = 20) -> float:
    """
    Blended relative strength vs a benchmark (index or sector proxy):
    0.5 * (short-term excess return) + 0.5 * (long-term excess return).
    Positive = outperforming the benchmark; the blend favors stocks
    trending into the catalyst window on both a 1-week and 1-month view,
    rather than a single lookback that could just be noise.
    """
    stock_short = _returns(stock_bars, short_k)
    stock_long = _returns(stock_bars, long_k)
    bench_short = _returns(benchmark_bars, short_k)
    bench_long = _returns(benchmark_bars, long_k)
    if None in (stock_short, stock_long, bench_short, bench_long):
        return None
    return 0.5 * (stock_short - bench_short) + 0.5 * (stock_long - bench_long)


def _true_range(bar: dict, prev_close: float) -> float:
    return max(
        bar["high"] - bar["low"],
        abs(bar["high"] - prev_close),
        abs(bar["low"] - prev_close),
    )


def _atr_series(bars: list, period: int = 14) -> list:
    if len(bars) < period + 1:
        return []
    trs = []
    for i in range(1, len(bars)):
        trs.append(_true_range(bars[i], bars[i - 1]["close"]))
    atrs = []
    for i in range(period - 1, len(trs)):
        atrs.append(sum(trs[i - period + 1:i + 1]) / period)
    return atrs


def atr_expansion(bars: list, atr_period: int = 14, baseline_period: int = 50) -> float:
    """
    Ratio of current ATR(14) to its own rolling average over the last
    `baseline_period` sessions. Deliberately NOT raw ATR - raw ATR is
    just a stock-size proxy (a Rs 3000 stock has bigger ATR than a
    Rs 300 one for no momentum-relevant reason). The ratio flags a
    volatility-regime change, which is what actually precedes a
    momentum move. >1 = expanding, <1 = contracting/quiet.
    """
    needed = atr_period + baseline_period + 1
    if len(bars) < needed:
        return None
    atrs = _atr_series(bars, atr_period)
    if len(atrs) < baseline_period + 1:
        return None
    current_atr = atrs[-1]
    baseline_atr = sum(atrs[-baseline_period - 1:-1]) / baseline_period
    if baseline_atr == 0:
        return None
    return current_atr / baseline_atr


def trend_continuation(bars: list, fast: int = 20, slow: int = 50) -> float:
    """
    (close - SMA_fast) / SMA_fast, but only counted as a continuation
    signal when SMA_fast > SMA_slow (structural uptrend) - a stock
    trading above a falling SMA20 is a bounce candidate, not a trend
    continuation candidate.
    """
    if len(bars) < slow:
        return None
    closes = [b["close"] for b in bars]
    sma_fast = sum(closes[-fast:]) / fast
    sma_slow = sum(closes[-slow:]) / slow
    if sma_fast == 0:
        return None
    distance = (closes[-1] - sma_fast) / sma_fast
    if sma_fast > sma_slow:
        return distance
    return -abs(distance) - 0.01


def liquidity_score(bars: list, lookback: int = 20) -> float:
    """
    Median daily turnover (close * volume) in crore over the lookback
    window. Median, not mean, so one outlier bulk-deal day doesn't make
    an otherwise illiquid stock look tradeable.
    """
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    turnovers = sorted(b["close"] * b["volume"] / 1e7 for b in window)
    mid = len(turnovers) // 2
    if len(turnovers) % 2:
        return turnovers[mid]
    return (turnovers[mid - 1] + turnovers[mid]) / 2


def volatility(bars: list, lookback: int = 20) -> float:
    """
    Stdev of daily log returns over the lookback window. NOT monotonic
    "higher is better" - a momentum candidate needs enough volatility
    to move, but extreme volatility is a risk flag, not an edge.
    rank.py treats this as a band filter, not a factor to maximize.
    """
    if len(bars) < lookback + 1:
        return None
    closes = [b["close"] for b in bars[-lookback - 1:]]
    log_rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] <= 0 or closes[i] <= 0:
            return None
        log_rets.append(math.log(closes[i] / closes[i - 1]))
    mean = sum(log_rets) / len(log_rets)
    var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(var)
