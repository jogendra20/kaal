"""
angel_provider.py
Implements get_intraday_bars() against Angel One's candle API - the
piece factors_intraday.py has been stubbed out waiting for all night.
NOT a full OHLCDataProvider - NSEBhavcopyProvider still covers EOD data;
this is used alongside it, only for the intraday piece bhavcopy can't do.
"""
import time
from datetime import datetime, timedelta

from angel_session import get_authenticated_client
from angel_scrip_master import load_scrip_master, build_token_lookup

INTERVAL_MAP = {
    "1min": "ONE_MINUTE",
    "3min": "THREE_MINUTE",
    "5min": "FIVE_MINUTE",
    "10min": "TEN_MINUTE",
    "15min": "FIFTEEN_MINUTE",
    "30min": "THIRTY_MINUTE",
    "1hour": "ONE_HOUR",
}

_APPROX_BARS_PER_DAY = {
    "1min": 375, "3min": 125, "5min": 75, "10min": 37,
    "15min": 25, "30min": 12, "1hour": 6,
}


class AngelOneProvider:
    def __init__(self, env_path: str = ".env"):
        self._client = None
        self._env_path = env_path
        self._token_lookup = None

    def _client_lazy(self):
        if self._client is None:
            self._client = get_authenticated_client(self._env_path)
        return self._client

    def _token_lookup_lazy(self):
        if self._token_lookup is None:
            master = load_scrip_master()
            self._token_lookup = build_token_lookup(master, exchange="NSE")
        return self._token_lookup

    def get_intraday_bars(self, symbol: str, interval: str = "5min", n: int = 75) -> list:
        angel_interval = INTERVAL_MAP.get(interval)
        if angel_interval is None:
            raise ValueError(f"Unknown interval {interval!r} - expected one of {list(INTERVAL_MAP)}")

        token = self._token_lookup_lazy().get(symbol)
        if not token:
            return []

        bars_per_day = _APPROX_BARS_PER_DAY[interval]
        days_needed = max(1, (n // bars_per_day) + 2)

        to_date = datetime.now()
        # NSE doesn't trade on weekends - querying a non-trading day as
        # the range endpoint produced corrupted/garbage candle data in
        # testing (confirmed 2026-07-26: Saturday's "data" was
        # internally impossible, the same request scoped to the prior
        # real trading day was clean and accurate). Does not yet
        # account for NSE holidays (a fixed calendar KAAL doesn't have
        # loaded anywhere), only weekends - a real but rarer gap.
        while to_date.weekday() >= 5:
            to_date -= timedelta(days=1)
        from_date = to_date - timedelta(days=days_needed * 2)

        client = self._client_lazy()
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": angel_interval,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        # Angel One's own forum has an open thread ("API Rate Limit
        # checks are not perfect") acknowledging their rate-limit
        # enforcement sometimes rejects requests well within the
        # documented 3-req/sec limit for getCandleData. Retry with
        # backoff is the fix other developers report working.
        response = None
        exception_occurred = False
        for attempt in range(3):
            exception_occurred = False
            try:
                response = client.getCandleData(params)
            except Exception as e:
                response = {"status": False, "message": str(e)}
                exception_occurred = True

            if response and response.get("status"):
                break
            error_text = str(response.get("message", "")) if response else ""
            is_rate_limit = "exceeding access rate" in error_text.lower() or "access denied" in error_text.lower()
            # Retry on the known rate-limit message AND on any raised
            # exception (timeouts, connection errors) - a real M&M
            # request timed out live (2026-07-28, read timeout=7) with
            # no rate-limit wording at all, same run where SUNPHARMA
            # separately recovered from an actual rate-limit failure.
            if is_rate_limit or exception_occurred:
                wait = 2 ** (attempt + 1)
                reason = "rate limit" if is_rate_limit else "network error"
                print(f"[ANGEL] {reason} for {symbol}, retrying in {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
                continue
            break

        if not response or not response.get("status"):
            print(f"[ANGEL] getCandleData failed for {symbol}: {response}")
            return []

        raw_candles = response.get("data", [])
        bars = []
        for candle in raw_candles:
            try:
                ts, o, h, l, c, v = candle
                bars.append({
                    "timestamp": ts,
                    "open": float(o), "high": float(h), "low": float(l),
                    "close": float(c), "volume": int(v),
                })
            except (ValueError, TypeError) as e:
                print(f"[ANGEL] skipping malformed candle for {symbol}: {candle} ({e})")
                continue

        return bars[-n:]
