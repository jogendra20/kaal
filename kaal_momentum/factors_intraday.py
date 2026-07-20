"""
kaal_momentum/factors_intraday.py
RVOL, VWAP position, ORB, real gap quality - factors that genuinely
need intraday candle data. NOT usable yet: no provider currently
implements get_intraday_bars(). This file exists so the interface and
intent are visible now; functions raise clearly rather than silently
returning fake numbers.

Do not add these to rank.py's weights until a provider actually
implements get_intraday_bars().
"""


class IntradayDataUnavailable(Exception):
    pass


def _require_intraday(provider):
    try:
        provider.get_intraday_bars("__PROBE__", "5min", 0)
    except NotImplementedError:
        raise IntradayDataUnavailable(
            f"{type(provider).__name__} has no live intraday feed. "
            "These factors need Angel One SmartAPI historical-candle "
            "access before they can run."
        )
    except Exception:
        pass


def relative_volume(symbol: str, provider, interval: str = "5min") -> float:
    """Today's cumulative volume vs the N-day average for the same
    time-of-day. Requires intraday bars."""
    _require_intraday(provider)
    raise NotImplementedError("implement once an intraday provider exists")


def vwap_position(symbol: str, provider, interval: str = "5min") -> float:
    """(last price - running VWAP) / running VWAP. Requires intraday bars."""
    _require_intraday(provider)
    raise NotImplementedError("implement once an intraday provider exists")


def opening_range_breakout(symbol: str, provider, range_minutes: int = 15) -> dict:
    """Break of the first `range_minutes` high/low, and by how much."""
    _require_intraday(provider)
    raise NotImplementedError("implement once an intraday provider exists")


def gap_quality(symbol: str, provider) -> float:
    """Real gap quality needs today's actual open plus behavior since -
    a gap that holds is different from one that fades."""
    _require_intraday(provider)
    raise NotImplementedError("implement once an intraday provider exists")
