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
    print()


if __name__ == "__main__":
    main()
