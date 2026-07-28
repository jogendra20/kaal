"""
kaal_momentum/factors_intraday.py
RVOL and VWAP position, now real (Angel One connection verified
working 2026-07-26, weekend-date bug fixed). ORB and gap quality still
pending - separate build.

RVOL does NOT fetch multiple prior days of intraday data from Angel
One to build its baseline - deliberately. It compares today's
cumulative volume-so-far against the stock's own average daily volume
(from kaal_momentum's EOD bhavcopy data), scaled by session elapsed.
Keeps Angel One's role limited to what only it can provide - today's
live numbers.

Every function returns None on insufficient data - never a fake
number standing in for "don't know".
"""
from datetime import datetime, time as dtime, timedelta

SESSION_START = dtime(9, 15)
SESSION_END = dtime(15, 30)


def _parse_bar_time(bar: dict) -> dtime:
    ts = bar["timestamp"]
    dt = datetime.fromisoformat(ts)
    return dt.time()


def _today_bars(bars: list) -> list:
    """
    Bug found live, pre-market, 2026-07-27: before market open, Angel
    One's API returns the most recent available session (e.g. Friday's
    full day) instead of nothing. The old version only checked that
    all returned bars shared the same date as each other - it never
    checked that date was actually today's real calendar date. Result:
    it silently treated Friday's closing price as "live now" data.
    """
    if not bars:
        return []
    real_today = datetime.now().strftime("%Y-%m-%d")
    latest_date = bars[-1]["timestamp"][:10]
    if latest_date != real_today:
        return []
    return [b for b in bars if b["timestamp"][:10] == latest_date]


def relative_volume(symbol: str, provider, avg_daily_volume: float,
                     interval: str = "5min", bars: list = None) -> dict:
    if not avg_daily_volume or avg_daily_volume <= 0:
        return None

    if bars is None:
        bars = provider.get_intraday_bars(symbol, interval=interval, n=100)
    today_bars = _today_bars(bars)
    if not today_bars:
        return None

    cumulative_volume = sum(b["volume"] for b in today_bars)
    latest_time = _parse_bar_time(today_bars[-1])

    session_seconds = (
        datetime.combine(datetime.today(), SESSION_END) -
        datetime.combine(datetime.today(), SESSION_START)
    ).total_seconds()
    elapsed_seconds = (
        datetime.combine(datetime.today(), latest_time) -
        datetime.combine(datetime.today(), SESSION_START)
    ).total_seconds()

    if elapsed_seconds <= 0:
        return None

    fraction_elapsed = min(elapsed_seconds / session_seconds, 1.0)
    expected_volume_by_now = avg_daily_volume * fraction_elapsed
    if expected_volume_by_now <= 0:
        return None

    rvol = cumulative_volume / expected_volume_by_now
    return {
        "rvol": round(rvol, 3),
        "cumulative_volume_today": cumulative_volume,
        "expected_volume_by_now": round(expected_volume_by_now, 0),
        "fraction_session_elapsed": round(fraction_elapsed, 3),
    }


def vwap_position(symbol: str, provider, interval: str = "5min", bars: list = None) -> dict:
    if bars is None:
        bars = provider.get_intraday_bars(symbol, interval=interval, n=100)
    today_bars = _today_bars(bars)
    if not today_bars:
        return None

    total_volume = sum(b["volume"] for b in today_bars)
    if total_volume <= 0:
        return None

    weighted_sum = sum(((b["high"] + b["low"] + b["close"]) / 3) * b["volume"] for b in today_bars)
    vwap = weighted_sum / total_volume
    if vwap <= 0:
        return None

    last_price = today_bars[-1]["close"]
    position_pct = (last_price - vwap) / vwap * 100

    return {
        "vwap": round(vwap, 2),
        "last_price": last_price,
        "position_pct": round(position_pct, 3),
        "regime": "ABOVE_VWAP" if position_pct > 0 else "BELOW_VWAP",
    }


def opening_range_breakout(symbol: str, provider, range_minutes: int = 15,
                            interval: str = "5min", bars: list = None) -> dict:
    """
    Opening range = high/low of the first `range_minutes` of trading.
    Returns None if the opening range window itself isn't complete yet
    (e.g. called very early in the session) - a partial range would
    understate the true high/low and produce a false breakout signal.
    """
    if bars is None:
        bars = provider.get_intraday_bars(symbol, interval=interval, n=100)
    today_bars = _today_bars(bars)
    if not today_bars:
        return None

    session_start_dt = datetime.combine(datetime.today(), SESSION_START)
    range_end_dt = session_start_dt + timedelta(minutes=range_minutes)

    opening_bars = [b for b in today_bars
                    if datetime.combine(datetime.today(), _parse_bar_time(b)) < range_end_dt]
    if not opening_bars:
        return None

    latest_bar_dt = datetime.combine(datetime.today(), _parse_bar_time(today_bars[-1]))
    if latest_bar_dt < range_end_dt:
        return None

    range_high = max(b["high"] for b in opening_bars)
    range_low = min(b["low"] for b in opening_bars)
    current_price = today_bars[-1]["close"]

    if current_price > range_high:
        direction = "BREAKOUT_UP"
        breakout_pct = (current_price - range_high) / range_high * 100
    elif current_price < range_low:
        direction = "BREAKOUT_DOWN"
        breakout_pct = (range_low - current_price) / range_low * 100
    else:
        direction = "INSIDE_RANGE"
        breakout_pct = 0.0

    return {
        "opening_range_high": round(range_high, 2),
        "opening_range_low": round(range_low, 2),
        "current_price": current_price,
        "direction": direction,
        "breakout_pct": round(breakout_pct, 3),
    }


def gap_quality(symbol: str, provider, prior_close: float, interval: str = "5min", bars: list = None) -> dict:
    """
    prior_close: yesterday's close, from kaal_momentum's EOD bhavcopy
    data (NOT fetched fresh from Angel One).
    Distinguishes a gap that's holding/extending from one that's
    fading back toward (or through) yesterday's close.
    """
    if not prior_close or prior_close <= 0:
        return None

    if bars is None:
        bars = provider.get_intraday_bars(symbol, interval=interval, n=100)
    today_bars = _today_bars(bars)
    if not today_bars:
        return None

    today_open = today_bars[0]["open"]
    current_price = today_bars[-1]["close"]

    gap_pct = (today_open - prior_close) / prior_close * 100
    if gap_pct == 0:
        return {"gap_pct": 0.0, "regime": "NO_GAP", "current_price": current_price}

    direction = "UP" if gap_pct > 0 else "DOWN"
    current_vs_open_pct = (current_price - today_open) / today_open * 100

    if direction == "UP":
        filled = current_price <= prior_close
        extending = current_vs_open_pct > 0
    else:
        filled = current_price >= prior_close
        extending = current_vs_open_pct < 0

    if filled:
        regime = "FILLED"
    elif extending:
        regime = "HELD_AND_EXTENDING"
    else:
        regime = "HELD_FADING"

    return {
        "gap_pct": round(gap_pct, 3),
        "direction": direction,
        "today_open": today_open,
        "current_price": current_price,
        "current_vs_open_pct": round(current_vs_open_pct, 3),
        "regime": regime,
    }
