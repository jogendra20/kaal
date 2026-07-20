"""
kaal_momentum/providers.py
Data provider interface for the Momentum Engine.

The engine's factor functions never call NSE/Angel One directly - they
take a `bars` list and compute. This file is the ONLY place that knows
where bars come from, so swapping the EOD bhavcopy source for the
Angel One intraday candle API later (Phase 5) means writing one new
provider class, not touching factor code.

Bar format (both daily and intraday): list of dicts, oldest first:
    {"date": "2026-07-20", "open": .., "high": .., "low": .., "close": .., "volume": ..}
"""
import csv
import io
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "bhavcopy_cache")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class OHLCDataProvider(ABC):
    """Anything that can hand the momentum engine price/volume history."""

    @abstractmethod
    def get_daily_bars(self, symbol: str, n: int) -> list:
        """Return up to n most recent daily bars, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def get_index_bars(self, index_symbol: str, n: int) -> list:
        """Same shape, for a benchmark index (e.g. 'NIFTY 50')."""
        raise NotImplementedError

    def get_intraday_bars(self, symbol: str, interval: str, n: int) -> list:
        """
        Optional. Not implemented by the EOD bhavcopy provider - only a
        live intraday source (Angel One SmartAPI) can serve this. Callers
        that need RVOL/VWAP/ORB must check for this capability first
        (see factors_intraday.py) rather than assume it exists.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support intraday bars"
        )


def _prev_trading_days(from_date: datetime, n: int) -> list:
    """n trading days strictly before from_date, most-recent-first, skipping Sat/Sun.
    Does NOT know about NSE holidays - a holiday just comes back as an empty
    fetch and is skipped by the caller, at the cost of one wasted HTTP call."""
    out = []
    d = from_date
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


class NSEBhavcopyProvider(OHLCDataProvider):
    """
    Daily bars from NSE's public bhavcopy archive, with on-disk caching -
    each date's file is published once and never changes, so we fetch it
    at most once ever, not once per run.
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _fetch_equity_bhavcopy_day(self, d: datetime) -> dict:
        date_str = d.strftime("%d%m%Y")
        cache_file = os.path.join(self.cache_dir, f"eq_{date_str}.json")
        if os.path.exists(cache_file):
            return json.load(open(cache_file))

        url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
        try:
            r = requests.get(url, headers=HEADERS, timeout=(5, 15))
            if r.status_code != 200:
                return {}
            reader = csv.DictReader(r.text.splitlines())
            result = {}
            for row in reader:
                row = {k.strip(): v.strip() for k, v in row.items()}
                if row.get("SERIES") != "EQ":
                    continue
                symbol = row.get("SYMBOL", "")
                if not symbol:
                    continue
                try:
                    result[symbol] = {
                        "date":   d.strftime("%Y-%m-%d"),
                        "open":   float(row.get("OPEN_PRICE", 0)),
                        "high":   float(row.get("HIGH_PRICE", 0)),
                        "low":    float(row.get("LOW_PRICE", 0)),
                        "close":  float(row.get("CLOSE_PRICE", 0)),
                        "volume": int(float(row.get("TTL_TRD_QNTY", 0))),
                        "turnover_lacs": float(row.get("TURNOVER_LACS", 0) or 0),
                    }
                except Exception:
                    continue
            json.dump(result, open(cache_file, "w"))
            return result
        except Exception as e:
            print(f"[MOMENTUM] bhavcopy fetch error {date_str}: {e}")
            return {}

    def get_daily_bars(self, symbol: str, n: int) -> list:
        bars = []
        d = datetime.now()
        attempts = 0
        while len(bars) < n and attempts < n * 3 + 15:
            d -= timedelta(days=1)
            attempts += 1
            if d.weekday() >= 5:
                continue
            day_data = self._fetch_equity_bhavcopy_day(d)
            if symbol in day_data:
                bars.append(day_data[symbol])
        bars.reverse()
        return bars

    def _fetch_index_bhavcopy_day(self, d: datetime) -> dict:
        date_str = d.strftime("%d%m%Y")
        cache_file = os.path.join(self.cache_dir, f"idx_{date_str}.json")
        if os.path.exists(cache_file):
            return json.load(open(cache_file))

        # NSE's daily "all indices closing" archive file. NOTE: this URL
        # pattern is inferred from NSE's standard archive naming - it has
        # NOT been hit against the live endpoint from this environment
        # (no network access here). Verify the first real run and tell me
        # if the response shape or URL differs.
        url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{date_str}.csv"
        try:
            r = requests.get(url, headers=HEADERS, timeout=(5, 15))
            if r.status_code != 200:
                return {}
            reader = csv.DictReader(r.text.splitlines())
            result = {}
            for row in reader:
                row = {k.strip(): v.strip() for k, v in row.items()}
                name = row.get("Index Name", "").strip()
                if not name:
                    continue
                try:
                    result[name] = {
                        "date":  d.strftime("%Y-%m-%d"),
                        "open":  float(row.get("Open Index Value", 0)),
                        "high":  float(row.get("High Index Value", 0)),
                        "low":   float(row.get("Low Index Value", 0)),
                        "close": float(row.get("Closing Index Value", 0)),
                        "volume": 0,
                    }
                except Exception:
                    continue
            json.dump(result, open(cache_file, "w"))
            return result
        except Exception as e:
            print(f"[MOMENTUM] index bhavcopy fetch error {date_str}: {e}")
            return {}

    def get_index_bars(self, index_symbol: str, n: int) -> list:
        bars = []
        d = datetime.now()
        attempts = 0
        while len(bars) < n and attempts < n * 3 + 15:
            d -= timedelta(days=1)
            attempts += 1
            if d.weekday() >= 5:
                continue
            day_data = self._fetch_index_bhavcopy_day(d)
            if index_symbol in day_data:
                bars.append(day_data[index_symbol])
        bars.reverse()
        return bars
