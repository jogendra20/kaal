"""
compare_snapshots.py
Diffs two watchlist snapshots (by default, the two most recent) for symbols
that appear in both. Shows the price move between them against the EARLIER
snapshot's tags -- this is the actual "did the signal predict anything"
check, repeated daily, that builds real evidence over time.
"""
import json, glob, sys


def load_snapshot(path):
    with open(path) as f:
        data = json.load(f)
    return data["generated_at"], {p["symbol"]: p for p in data["picks"]}


def main():
    files = sorted(glob.glob("watchlist_snapshot_*.json"))
    if len(files) < 2:
        print(f"Only {len(files)} snapshot(s) on disk -- need at least 2 to compare.")
        print(f"Files found: {files}")
        return

    if len(sys.argv) == 3:
        earlier_file, later_file = sys.argv[1], sys.argv[2]
    else:
        earlier_file, later_file = files[-2], files[-1]

    earlier_time, earlier = load_snapshot(earlier_file)
    later_time, later = load_snapshot(later_file)

    print(f"Comparing:")
    print(f"  EARLIER: {earlier_file} ({earlier_time})")
    print(f"  LATER:   {later_file} ({later_time})\n")

    common = sorted(set(earlier.keys()) & set(later.keys()))
    if not common:
        print("No overlapping symbols between these two snapshots.")
        return

    print(f"{len(common)} symbols appear in both snapshots:\n")
    print(f"{'='*90}")

    rows = []
    for sym in common:
        e, l = earlier[sym], later[sym]
        if e["ltp"] is None or l["ltp"] is None:
            continue
        move_pct = round((l["ltp"] - e["ltp"]) / e["ltp"] * 100, 2)
        rows.append((sym, move_pct, e["tags"], e["ltp"], l["ltp"]))

    rows.sort(key=lambda x: -abs(x[1]))

    for sym, move_pct, tags, ltp_e, ltp_l in rows:
        tag_str = "+".join(tags) if tags else "no tags"
        flag = "  <-- big move" if abs(move_pct) >= 3.0 else ""
        print(f"{sym:12s} {ltp_e:>10.2f} -> {ltp_l:>10.2f}  ({move_pct:+.2f}%)  "
              f"[was: {tag_str}]{flag}")

    print(f"\n{'-'*90}")
    print("Read this as: did symbols with MORE tags (esp. OI_SPURT + SCREEN_CONFIRMED")
    print("together) move more than symbols with fewer/no tags? One comparison isn't")
    print("enough to conclude anything -- keep running this daily and look for the")
    print("pattern to hold up across many snapshots before trusting it.")

    tagged = [r for r in rows if len(r[2]) >= 2]
    untagged = [r for r in rows if len(r[2]) < 2]
    if tagged and untagged:
        avg_tagged = sum(abs(r[1]) for r in tagged) / len(tagged)
        avg_untagged = sum(abs(r[1]) for r in untagged) / len(untagged)
        print(f"\nAvg |move| for multi-tag picks (n={len(tagged)}): {avg_tagged:.2f}%")
        print(f"Avg |move| for single/no-tag picks (n={len(untagged)}): {avg_untagged:.2f}%")


if __name__ == "__main__":
    main()
