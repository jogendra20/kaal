"""
watchlist_view.py
Loads the most recent snapshot's watchlist, lets you add any extra symbols
by hand (stocks you researched yourself that the automated screeners/OI/
news pipeline didn't happen to surface), fetches live LTP + volume for
everything, and prints one clean table. Also saves the manual addition
back into the snapshot file so tomorrow's compare_snapshots.py tracks it
too, not just today's automated picks.

Usage:
  python3 watchlist_view.py                  -> just view today's watchlist
  python3 watchlist_view.py TATASTEEL         -> view + add TATASTEEL
  python3 watchlist_view.py TATASTEEL DIXON   -> view + add multiple
"""
import sys, json, glob
from angel_provider import AngelOneProvider


def load_latest_snapshot():
    files = sorted(glob.glob("watchlist_snapshot_*.json"))
    if not files:
        return None, []
    path = files[-1]
    with open(path) as f:
        data = json.load(f)
    return path, data.get("picks", [])


def main():
    manual_adds = [s.upper() for s in sys.argv[1:]]

    path, picks = load_latest_snapshot()
    if path is None:
        print("No snapshot found yet -- run daily_snapshot.py first.")
        return

    existing_symbols = {p["symbol"] for p in picks}
    new_symbols = [s for s in manual_adds if s not in existing_symbols]

    for sym in new_symbols:
        picks.append({
            "symbol": sym, "filed_at": None, "ltp": None, "ltp_pct_change": None,
            "in_high_volume_screen": False, "news_count": None,
            "oi_change": None, "oi_avg_pct": None, "deliv_pct": None,
            "tags": ["MANUAL_ADD"], "verdict": "MANUAL_ADD",
        })

    if new_symbols:
        with open(path) as f:
            data = json.load(f)
        data["picks"] = picks
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Added to watchlist: {new_symbols} (saved into {path})\n")

    already_flagged = [s for s in manual_adds if s in existing_symbols]
    if already_flagged:
        print(f"Already on the watchlist, no change needed: {already_flagged}\n")

    print(f"Loaded from: {path}")
    print(f"Fetching live LTP + volume for {len(picks)} symbols...\n")

    provider = AngelOneProvider()
    rows = []
    for p in picks:
        sym = p["symbol"]
        quote = provider.get_ltp(sym)
        volume = None
        try:
            bars = provider.get_intraday_bars(sym, n=1, interval="1min")
            if bars:
                volume = bars[-1].get("volume")
        except Exception:
            pass

        ltp = quote.get("ltp") if quote else None
        prev_close = quote.get("close") if quote else None
        pct_change = round((ltp - prev_close) / prev_close * 100, 2) if (ltp and prev_close) else None

        rows.append({
            "symbol": sym, "ltp": ltp, "pct_change": pct_change, "volume": volume,
            "tags": p.get("tags", []),
        })

    rows.sort(key=lambda r: -(abs(r["pct_change"]) if r["pct_change"] is not None else -1))

    print(f"{'SYMBOL':<12} {'LTP':>10} {'CHANGE':>9} {'VOLUME':>12}   TAGS")
    print("-" * 80)
    for r in rows:
        ltp_str = f"{r['ltp']:.2f}" if r["ltp"] is not None else "N/A"
        chg_str = f"{r['pct_change']:+.2f}%" if r["pct_change"] is not None else "N/A"
        vol_str = f"{r['volume']:,}" if r["volume"] is not None else "N/A"
        tag_str = ", ".join(r["tags"]) if r["tags"] else "-"
        print(f"{r['symbol']:<12} {ltp_str:>10} {chg_str:>9} {vol_str:>12}   {tag_str}")


if __name__ == "__main__":
    main()
