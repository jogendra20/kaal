"""
5-Min Volume Surge Scanner — replays today's intraday candles against
your Chartink formula:

    [0] 5 minute volume > 3 * [0] 5 minute sma(5 minute volume, 20)
    and close > 20
    and daily sma(daily volume, 10) > 100000

Runs on TODAY's 5-min data (yfinance keeps ~60 days of 5m history),
scans candle-by-candle from 9:30 to 15:20, and prints every symbol +
timestamp where the condition was satisfied.

Usage (Termux):
    pip install yfinance pandas numpy --break-system-packages
    python3 intraday_volume_surge.py
    python3 intraday_volume_surge.py --symbols my_list.txt
    python3 intraday_volume_surge.py --date 2026-08-10   # specific past day
"""

import argparse
import sys
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance --break-system-packages")
    sys.exit(1)

DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC", "LT", "AXISBANK",
    "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "ASIANPAINT", "WIPRO", "TATASTEEL", "ADANIENT", "POWERGRID",
    "TATAMOTORS", "JSWSTEEL", "COALINDIA", "TECHM", "CIPLA", "DRREDDY",
    "APOLLOHOSP", "HINDALCO", "INDUSINDBK", "BPCL", "SBILIFE",
]

MARKET_OPEN = dtime(9, 30)
MARKET_CUTOFF = dtime(15, 20)
SMA_PERIOD = 20
VOL_MULT = 3
PRICE_FLOOR = 20
DAILY_VOL_FLOOR = 100000


def check_symbol(symbol: str, target_date: str = None) -> pd.DataFrame:
    ticker = symbol.strip().upper() + ".NS"

    # daily liquidity check first (cheap, filters junk before pulling intraday)
    daily = yf.download(ticker, period="30d", interval="1d", progress=False, auto_adjust=True)
    if daily.empty or len(daily) < 10:
        return pd.DataFrame()
    if isinstance(daily.columns, pd.MultiIndex):
        daily.columns = daily.columns.get_level_values(0)
    daily_vol_sma10 = daily["Volume"].rolling(10).mean().iloc[-1]
    if pd.isna(daily_vol_sma10) or daily_vol_sma10 <= DAILY_VOL_FLOOR:
        return pd.DataFrame()

    intraday = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=True)
    if intraday.empty:
        return pd.DataFrame()
    if isinstance(intraday.columns, pd.MultiIndex):
        intraday.columns = intraday.columns.get_level_values(0)

    intraday.index = intraday.index.tz_convert("Asia/Kolkata")

    if target_date:
        day = pd.to_datetime(target_date).date()
    else:
        day = intraday.index[-1].date()

    day_data = intraday[intraday.index.date == day].copy()
    if day_data.empty:
        return pd.DataFrame()

    day_data["vol_sma20"] = day_data["Volume"].rolling(SMA_PERIOD, min_periods=5).mean()
    day_data["surge"] = day_data["Volume"] > VOL_MULT * day_data["vol_sma20"]
    day_data["price_ok"] = day_data["Close"] > PRICE_FLOOR

    matched = day_data[
        day_data["surge"]
        & day_data["price_ok"]
        & (day_data.index.time >= MARKET_OPEN)
        & (day_data.index.time <= MARKET_CUTOFF)
    ]

    rows = []
    for ts, row in matched.iterrows():
        rows.append({
            "time": ts.strftime("%H:%M"),
            "symbol": symbol,
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
            "vol_sma20": round(row["vol_sma20"], 0),
            "surge_ratio": round(row["Volume"] / row["vol_sma20"], 2),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD, defaults to most recent trading day")
    args = parser.parse_args()

    if args.symbols:
        with open(args.symbols) as f:
            symbols = [line.strip() for line in f if line.strip()]
    else:
        symbols = DEFAULT_SYMBOLS
        print(f"No --symbols file given, using built-in {len(symbols)}-stock list.\n")

    all_matches = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] checking {sym}...")
        res = check_symbol(sym, target_date=args.date)
        if not res.empty:
            all_matches.append(res)

    if not all_matches:
        print("\nNo volume surge signals matched today for this universe.")
        return

    combined = pd.concat(all_matches, ignore_index=True)
    combined = combined.sort_values("time")
    combined.to_csv("intraday_surge_results.csv", index=False)

    print("\n=== VOLUME SURGE MATCHES ===")
    for _, r in combined.iterrows():
        print(f"{r['time']}  {r['symbol']:<12} close={r['close']}  vol={r['volume']}  ratio={r['surge_ratio']}x avg")

    print(f"\nSaved to intraday_surge_results.csv ({len(combined)} matches)")


if __name__ == "__main__":
    main()
