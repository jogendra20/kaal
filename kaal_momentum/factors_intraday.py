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
from datetime import datetime, time as dtime

SESSION_START = dtime(9, 15)
SESSION_END = dtime(15, 30)


def _parse_bar_time(bar: dict) -> dtime:
    ts = bar["timestamp"]
    dt = datetime.fromisoformat(ts)
    return dt.time()


def _today_bars(bars: list) -> list:
    if not bars:
        return []
    latest_date = bars[-1]["timestamp"][:10]
    return [b for b in bars if b["timestamp"][:10] == latest_date]


def relative_volume(symbol: str, provider, avg_daily_volume: float,
                     interval: str = "5min") -> dict:
    if not avg_daily_volume or avg_daily_volume <= 0:
        return None

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


def vwap_position(symbol: str, provider, interval: str = "5min") -> dict:
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


def opening_range_breakout(symbol: str, provider, range_minutes: int = 15) -> dict:
    """Not yet implemented - next increment."""
    raise NotImplementedError("ORB not yet built - separate step")


def gap_quality(symbol: str, provider) -> dict:
    """Not yet implemented - next increment."""
    raise NotImplementedError("gap_quality not yet built - separate step")
