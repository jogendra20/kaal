"""
check_confirmations.py

Takes a list of up to 5 symbols and checks each against three live
confirmation signals, using Angel One intraday data:
  1. Gap % vs previous close
  2. RVOL - current 5-min volume vs recent average
  3. VWAP position - is price currently above or below VWAP

This is observation only - reports what each stock is currently doing,
does not decide buy/sell/hold, no position sizing. Standalone script.

Usage:
    python check_confirmations.py RELIANCE TCS INFY HDFCBANK TITAN
    python check_confirmations.py RELIANCE TCS --vol-lookback 20
"""

import argparse
import sys
from datetime import datetime

import load_env
load_env.load_env()

from angel_provider import AngelOneProvider

VOL_LOOKBACK_DEFAULT = 20


def compute_vwap(bars):
    """Cumulative VWAP from the bars provided (typical price x volume,
    summed and divided by total volume) - approximates session VWAP
    using whatever intraday bars are available, not tick-level data."""
    total_pv = 0.0
    total_v = 0
    for b in bars:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        total_pv += typical * b["volume"]
        total_v += b["volume"]
    if total_v == 0:
        return None
    return total_pv / total_v


def check_symbol(provider, symbol, vol_lookback):
    result = {"symbol": symbol, "error": None}

    ltp_data = provider.get_ltp(symbol)
    if not ltp_data or ltp_data.get("ltp") is None:
        result["error"] = "could not fetch LTP"
        return result
    current_price = ltp_data["ltp"]
    result["current_price"] = current_price

    bars = provider.get_intraday_bars(symbol, interval="5min", n=vol_lookback + 10)
    if not bars or len(bars) < vol_lookback + 1:
        result["error"] = f"insufficient bar history ({len(bars) if bars else 0} bars)"
        return result

    # Gap vs previous close: use the earliest bar in this session as a
    # proxy for today's open, and the close of the bar before that block
    # as previous-close. This is an approximation from available candles,
    # not NSE's official previous-close field - fine for observation,
    # would need a dedicated previous-close fetch for anything stricter.
    today_str = datetime.now().strftime("%Y-%m-%d")
    todays_bars = [b for b in bars if str(b["timestamp"]).startswith(today_str)]
    if todays_bars:
        session_open = todays_bars[0]["open"]
        prior_bars = [b for b in bars if not str(b["timestamp"]).startswith(today_str)]
        prev_close = prior_bars[-1]["close"] if prior_bars else None
    else:
        session_open = None
        prev_close = None

    if session_open and prev_close and prev_close != 0:
        gap_pct = (session_open - prev_close) / prev_close * 100
        result["gap_pct"] = round(gap_pct, 2)
    else:
        result["gap_pct"] = None
        result["gap_note"] = "not enough same-day bars yet to compute gap"

    # RVOL: latest candle's volume vs average of the prior N
    latest = bars[-1]
    history = bars[-(vol_lookback + 1):-1]
    avg_vol = sum(b["volume"] for b in history) / len(history) if history else 0
    if avg_vol > 0:
        result["rvol"] = round(latest["volume"] / avg_vol, 2)
    else:
        result["rvol"] = None

    # VWAP position: computed from today's bars only (session VWAP)
    vwap = compute_vwap(todays_bars) if todays_bars else None
    if vwap:
        result["vwap"] = round(vwap, 2)
        result["vwap_position"] = "above" if current_price > vwap else "below"
        result["vwap_distance_pct"] = round((current_price - vwap) / vwap * 100, 2)
    else:
        result["vwap"] = None
        result["vwap_position"] = None

    return result


def print_result(r):
    if r.get("error"):
        print(f"{r['symbol']:<12} ERROR: {r['error']}")
        return

    gap = f"{r['gap_pct']:+.2f}%" if r.get("gap_pct") is not None else "n/a"
    rvol = f"{r['rvol']:.2f}x" if r.get("rvol") is not None else "n/a"
    vwap_pos = r.get("vwap_position") or "n/a"
    vwap_dist = f"({r['vwap_distance_pct']:+.2f}%)" if r.get("vwap_distance_pct") is not None else ""

    confirmations = []
    if r.get("gap_pct") is not None and abs(r["gap_pct"]) >= 1.0:
        confirmations.append(f"gap {'up' if r['gap_pct'] > 0 else 'down'}")
    if r.get("rvol") is not None and r["rvol"] >= 2.0:
        confirmations.append("high volume")
    if r.get("vwap_position") == "above":
        confirmations.append("above VWAP")
    elif r.get("vwap_position") == "below":
        confirmations.append("below VWAP")

    conf_str = ", ".join(confirmations) if confirmations else "no notable confirmations"

    print(f"{r['symbol']:<12} price={r['current_price']:<10} gap={gap:<8} "
          f"rvol={rvol:<8} vwap={vwap_pos}{vwap_dist}")
    print(f"{'':12} -> {conf_str}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+", help="up to 5 NSE symbols")
    parser.add_argument("--vol-lookback", type=int, default=VOL_LOOKBACK_DEFAULT)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols][:5]
    if len(args.symbols) > 5:
        print(f"Note: only checking the first 5 symbols given ({symbols})")

    provider = AngelOneProvider()

    print(f"{'='*70}")
    print(f"CONFIRMATION CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Observation only - not a trade signal. Gap/RVOL/VWAP thresholds")
    print(f"below are just display flags (gap>=1%, RVOL>=2x), not filters.")
    print(f"{'='*70}\n")

    results = []
    for symbol in symbols:
        r = check_symbol(provider, symbol, args.vol_lookback)
        results.append(r)
        print_result(r)
        print()

    return results


if __name__ == "__main__":
    main()
