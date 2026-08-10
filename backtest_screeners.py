"""
Screener Backtester — compares two Chartink-style screener logics
against historical forward returns using yfinance daily data.

SCREENER A: 7-day range expansion + trend stack (20/50/200 SMA)
SCREENER B: Close > prev day high breakout + RSI>50 + volume + trend

Usage (in Termux):
    pip install yfinance pandas numpy --break-system-packages
    python3 backtest_screeners.py --symbols symbols.txt

symbols.txt should have one NSE symbol per line, WITHOUT .NS suffix
(e.g. RELIANCE, TCS, INFY...). If you don't have a list handy, this
script falls back to a small built-in Nifty 50 list.

Output:
    - Prints summary stats (win rate, avg return) for each screener
      at 1-day, 3-day, 5-day, 10-day forward horizons
    - Saves matched-signal details to backtest_results.csv
"""

import argparse
import sys
import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance --break-system-packages")
    sys.exit(1)

# Fallback universe if no symbol file is given — liquid, non-penny Nifty 50 names
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC", "LT", "AXISBANK",
    "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "ASIANPAINT", "NESTLEIND", "WIPRO", "M&M", "ADANIENT", "TATASTEEL",
    "POWERGRID", "NTPC", "HCLTECH", "TATAMOTORS", "JSWSTEEL",
    "BAJAJFINSV", "ONGC", "COALINDIA", "GRASIM", "TECHM", "CIPLA",
    "DRREDDY", "EICHERMOT", "BRITANNIA", "HEROMOTOCO", "DIVISLAB",
    "APOLLOHOSP", "BPCL", "HINDALCO", "SBILIFE", "INDUSINDBK",
    "TATACONSUM", "UPL", "BAJAJ-AUTO", "SHREECEM", "ADANIPORTS", "LTIM",
]

MIN_PRICE = 50  # "not penny stock" floor, matches your screener's own filter


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def screener_a_signals(df: pd.DataFrame) -> pd.Series:
    """7-day range expansion + trend stack (20/50/200 SMA)."""
    rng = df["High"] - df["Low"]
    range_expanding = pd.Series(True, index=df.index)
    for i in range(1, 8):
        range_expanding &= rng > rng.shift(i)

    sma20 = df["Close"].rolling(20).mean()
    sma50 = df["Close"].rolling(50).mean()
    sma200 = df["Close"].rolling(200).mean()
    vol_sma20 = df["Volume"].rolling(20).mean()

    weekly = df["Close"].resample("W").agg(["first", "last"])
    weekly_bullish_daily = (weekly["last"] > weekly["first"]).reindex(
        df.index, method="ffill"
    )
    monthly = df["Close"].resample("ME").agg(["first", "last"])
    monthly_bullish_daily = (monthly["last"] > monthly["first"]).reindex(
        df.index, method="ffill"
    )

    cond = (
        range_expanding
        & (df["Close"] > df["Open"])
        & (df["Close"] > df["Close"].shift(1))
        & weekly_bullish_daily.fillna(False)
        & monthly_bullish_daily.fillna(False)
        & (sma20 > sma50)
        & (sma50 > sma200)
        & (df["Volume"] > 300000)
        & (df["Volume"] > 2 * vol_sma20)
    )
    return cond.fillna(False)


def screener_b_signals(df: pd.DataFrame) -> pd.Series:
    """Close > prev day high breakout + RSI>50 + volume + trend."""
    sma20 = df["Close"].rolling(20).mean()
    sma50 = df["Close"].rolling(50).mean()
    vol_sma20 = df["Volume"].rolling(20).mean()
    rsi = compute_rsi(df["Close"], 14)

    cond = (
        (df["Close"] > MIN_PRICE)
        & (df["Volume"] > vol_sma20)
        & (sma20 > sma50)
        & (rsi > 50)
        & (df["Close"] > sma50)
        & (df["Close"] > df["High"].shift(1))
        & (vol_sma20 > 500000)
    )
    return cond.fillna(False)


def forward_returns(df: pd.DataFrame, horizons=(1, 3, 5, 10)) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for h in horizons:
        out[f"fwd_{h}d"] = df["Close"].shift(-h) / df["Close"] - 1
    return out


def backtest_symbol(symbol: str, period="2y") -> pd.DataFrame:
    ticker = symbol.strip().upper() + ".NS"
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    except Exception as e:
        print(f"  skip {symbol}: {e}")
        return pd.DataFrame()

    if df.empty or len(df) < 210:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    sig_a = screener_a_signals(df)
    sig_b = screener_b_signals(df)
    fwd = forward_returns(df)

    rows = []
    for date in df.index:
        if sig_a.loc[date] or sig_b.loc[date]:
            row = {
                "symbol": symbol,
                "date": date,
                "screener_a": bool(sig_a.loc[date]),
                "screener_b": bool(sig_b.loc[date]),
            }
            for h in (1, 3, 5, 10):
                row[f"fwd_{h}d"] = fwd.loc[date, f"fwd_{h}d"]
            rows.append(row)
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame, screener_col: str, label: str):
    sub = results[results[screener_col]]
    print(f"\n=== {label} ===")
    print(f"Total signals: {len(sub)}")
    if len(sub) == 0:
        return
    for h in (1, 3, 5, 10):
        col = f"fwd_{h}d"
        valid = sub[col].dropna()
        if len(valid) == 0:
            continue
        win_rate = (valid > 0).mean() * 100
        avg_ret = valid.mean() * 100
        print(f"  {h}d fwd -> win rate: {win_rate:5.1f}%  avg return: {avg_ret:+.2f}%  (n={len(valid)})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default=None, help="Path to txt file, one NSE symbol per line")
    parser.add_argument("--period", type=str, default="2y", help="yfinance period, e.g. 1y, 2y, 5y")
    args = parser.parse_args()

    if args.symbols:
        with open(args.symbols) as f:
            symbols = [line.strip() for line in f if line.strip()]
    else:
        symbols = DEFAULT_SYMBOLS
        print(f"No --symbols file given, using built-in {len(symbols)}-stock Nifty 50 list.\n")

    all_results = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] fetching {sym}...")
        res = backtest_symbol(sym, period=args.period)
        if not res.empty:
            all_results.append(res)

    if not all_results:
        print("No signals found across any symbol. Try a longer period or check data access.")
        return

    combined = pd.concat(all_results, ignore_index=True)
    combined.to_csv("backtest_results.csv", index=False)

    summarize(combined, "screener_a", "Screener A: Range Expansion + Trend Stack")
    summarize(combined, "screener_b", "Screener B: Breakout + RSI + Volume")

    both = combined[combined["screener_a"] & combined["screener_b"]]
    if len(both) > 0:
        summarize(combined.assign(both=combined["screener_a"] & combined["screener_b"]), "both", "Both Screeners Agree (overlap)")

    print(f"\nFull signal log saved to backtest_results.csv ({len(combined)} rows)")


if __name__ == "__main__":
    main()
