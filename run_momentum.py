"""
run_momentum.py
Manual test runner: pulls a small, hardcoded liquid F&O universe through
the Momentum Engine and prints a ranked watchlist you can eyeball.

This is NOT the Universe Engine from the original brief - it's a fixed
list of 20 liquid names for testing the ranking logic against real data.
The real Universe Engine (dynamic, liquidity-filtered, full NSE) is a
separate decision - don't mistake this list for that component.
"""
from kaal_momentum.providers import NSEBhavcopyProvider
from kaal_momentum.rank import build_watchlist
from kaal_momentum.factors_intraday import relative_volume, vwap_position, opening_range_breakout, gap_quality

TEST_UNIVERSE = {
    "RELIANCE":  "ENERGY",
    "ONGC":      "ENERGY",
    "BPCL":      "ENERGY",
    "HDFCBANK":  "BANK",
    "ICICIBANK": "BANK",
    "AXISBANK":  "BANK",
    "SBIN":      "BANK",
    "INFY":      "IT",
    "TCS":       "IT",
    "WIPRO":     "IT",
    "HCLTECH":   "IT",
    "TATASTEEL": "METAL",
    "JSWSTEEL":  "METAL",
    "HINDALCO":  "METAL",
    "SUNPHARMA": "PHARMA",
    "CIPLA":     "PHARMA",
    "DRREDDY":   "PHARMA",
    "MARUTI":    "AUTO",
    "TMPV": "AUTO",  # was TATAMOTORS, renamed after Oct 2025 demerger
    "M&M":       "AUTO",
}


def main():
    provider = NSEBhavcopyProvider()
    result = build_watchlist(
        symbols=list(TEST_UNIVERSE.keys()),
        provider=provider,
        top_n=3,
        sector_map=TEST_UNIVERSE,
        lookback=75,  # MIN_BARS_REQUIRED is 71 - no need to fetch 120
    )

    print(f"\n{'='*60}")
    print(f"TOP {len(result['ranked'])} MOMENTUM CANDIDATES")
    print(f"{'='*60}")
    for i, r in enumerate(result["ranked"], 1):
        print(f"\n#{i}  {r['symbol']}  (score: {r['score']})")
        print(f"    sector: {TEST_UNIVERSE.get(r['symbol'], '?')}")
        for factor, pctl in r["factors"].items():
            raw = r["raw"].get(factor)
            raw_str = f"{raw:.4f}" if raw is not None else "n/a"
            print(f"    {factor:15s} percentile={pctl:.2f}  raw={raw_str}")

    if result["excluded"]:
        print(f"\n{'-'*60}")
        print(f"EXCLUDED (insufficient history, need 71+ trading days):")
        print(f"  {', '.join(result['excluded'])}")
    if result.get("skipped_for_sector_diversity"):
        print(f"\n{'-'*60}")
        print(f"SKIPPED (would have ranked in top 3, but sector already picked):")
        print(f"  {', '.join(result['skipped_for_sector_diversity'])}")

    # --- Live intraday factors: INFORMATIONAL ONLY ---
    # Not blended into the score above - zero live verification yet
    # (first real market-hours run for all four). Watch whether the
    # numbers look sane before folding these into rank.py's weights.
    print(f"\n{'='*60}")
    print(f"LIVE INTRADAY FACTORS (informational only - NOT in the score above)")
    print(f"{'='*60}")
    try:
        from angel_provider import AngelOneProvider
        angel = AngelOneProvider()
    except Exception as e:
        print(f"Could not start Angel One provider: {e}")
        angel = None

    if angel:
        for r in result["ranked"]:
            symbol = r["symbol"]
            print(f"\n{symbol}:")
            try:
                daily_bars = provider.get_daily_bars(symbol, n=20)
                if len(daily_bars) < 2:
                    print("    not enough EOD history for avg volume / prior close")
                    continue
                avg_daily_volume = sum(b["volume"] for b in daily_bars) / len(daily_bars)
                prior_close = daily_bars[-1]["close"]

                # Fetch intraday bars ONCE, reuse across all four factors -
                # calling each factor without pre-fetched bars means 4
                # separate API calls per symbol, which tripped Angel One's
                # rate limit ("Access denied because of exceeding access
                # rate") on the live 2026-07-27 run after just 3 symbols.
                intraday_bars = angel.get_intraday_bars(symbol, interval="5min", n=100)

                rvol = relative_volume(symbol, angel, avg_daily_volume, bars=intraday_bars)
                vwap = vwap_position(symbol, angel, bars=intraday_bars)
                orb = opening_range_breakout(symbol, angel, bars=intraday_bars)
                gap = gap_quality(symbol, angel, prior_close, bars=intraday_bars)

                print(f"    RVOL:  {rvol}")
                print(f"    VWAP:  {vwap}")
                print(f"    ORB:   {orb}")
                print(f"    Gap:   {gap}")

                import time
                time.sleep(1)  # small buffer between symbols - cheap extra insurance
            except Exception as e:
                print(f"    error fetching intraday factors: {e}")
    print()


if __name__ == "__main__":
    main()
