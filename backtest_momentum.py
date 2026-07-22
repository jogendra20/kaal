"""
backtest_momentum.py
Walks through the last several months of trading days, on each day runs
build_watchlist() using ONLY data that would have existed as of that
day's close, then checks what actually happened on the VERY NEXT trading
day only. No multi-day holding - picks flagged the evening before,
traded the next session, matching how an intraday trader would use this.

Two measures per pick, both next-day-only:
  - open_to_close_pct: did the day trend the direction implied
  - open_to_high_pct:  how much upside was available to capture
                        intraday, regardless of where it closed

CAVEAT: this can only be as good as how far back the local bhavcopy
cache goes. If the cache is thin, there are only a handful of valid
backtest days (each needs 71+ prior trading days before the factors
can even be computed) - this script reports exactly how many valid
days it found rather than silently showing a misleadingly small sample.
"""
from datetime import datetime, timedelta

from kaal_momentum.providers import NSEBhavcopyProvider
from kaal_momentum.rank import build_watchlist, MIN_BARS_REQUIRED
from run_momentum import TEST_UNIVERSE

TEST_TRADING_DAYS = 60


def _trading_days_back(from_date: datetime, n: int) -> list:
    out = []
    d = from_date
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    out.reverse()
    return out


def _next_trading_bar(provider, symbol: str, after_date: datetime):
    bars = provider.get_daily_bars(symbol, 10, as_of_date=after_date + timedelta(days=10))
    for b in bars:
        if b["date"] > after_date.strftime("%Y-%m-%d"):
            return b
    return None


def run_backtest():
    provider = NSEBhavcopyProvider()
    symbols = list(TEST_UNIVERSE.keys())

    latest_usable_date = datetime.now() - timedelta(days=3)
    test_dates = _trading_days_back(latest_usable_date, TEST_TRADING_DAYS)

    picks_evaluated = []
    valid_days = 0
    skipped_days = 0

    for i, d in enumerate(test_dates, 1):
        print(f"[{i}/{len(test_dates)}] processing {d.strftime('%Y-%m-%d')}...", flush=True)
        result = build_watchlist(
            symbols=symbols, provider=provider, top_n=3,
            sector_map=TEST_UNIVERSE, as_of_date=d,
            lookback=75,  # MIN_BARS_REQUIRED is 71 - don't fetch 120
        )
        if not result["ranked"]:
            skipped_days += 1
            print(f"  -> skipped (insufficient history)")
            continue
        valid_days += 1
        picks_str = [r["symbol"] for r in result["ranked"]]
        print(f"  -> picks: {picks_str}")

        for r in result["ranked"]:
            nxt = _next_trading_bar(provider, r["symbol"], d)
            if not nxt or nxt["open"] == 0:
                continue
            open_close_pct = (nxt["close"] - nxt["open"]) / nxt["open"] * 100
            open_high_pct = (nxt["high"] - nxt["open"]) / nxt["open"] * 100
            picks_evaluated.append({
                "date": d.strftime("%Y-%m-%d"),
                "symbol": r["symbol"],
                "score": r["score"],
                "next_day": nxt["date"],
                "open_to_close_pct": round(open_close_pct, 2),
                "open_to_high_pct": round(open_high_pct, 2),
            })

    print(f"\n{'='*70}")
    print(f"BACKTEST: {valid_days} valid days, {skipped_days} skipped (insufficient history)")
    print(f"{'='*70}")

    if not picks_evaluated:
        print("\nNo picks could be evaluated. If skipped_days is high relative")
        print("to valid_days, your bhavcopy cache doesn't go back far enough -")
        print(f"each test day needs {MIN_BARS_REQUIRED} prior trading days of")
        print("history before the momentum factors can even be computed.")
        return

    for p in picks_evaluated:
        print(f"{p['date']} -> {p['symbol']:12s} (score {p['score']})  "
              f"next day {p['next_day']}: O->C {p['open_to_close_pct']:+.2f}%  "
              f"O->H {p['open_to_high_pct']:+.2f}%")

    n = len(picks_evaluated)
    wins = sum(1 for p in picks_evaluated if p["open_to_close_pct"] > 0)
    avg_oc = sum(p["open_to_close_pct"] for p in picks_evaluated) / n
    avg_oh = sum(p["open_to_high_pct"] for p in picks_evaluated) / n

    print(f"\n{'-'*70}")
    print(f"SUMMARY over {n} picks across {valid_days} days")
    print(f"  Win rate (next-day O->C positive): {wins}/{n} ({wins/n*100:.1f}%)")
    print(f"  Avg next-day open->close: {avg_oc:+.2f}%")
    print(f"  Avg next-day open->high:  {avg_oh:+.2f}%  (max intraday upside available)")
    print(f"{'-'*70}\n")


if __name__ == "__main__":
    run_backtest()
