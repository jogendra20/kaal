import json
import glob

MOVE_THRESHOLD = 10.0  # %

files = sorted(glob.glob("fy27_backtest_results*.json"))
print(f"Reading: {files}\n")

all_picks = []
seen = set()
for fpath in files:
    try:
        with open(fpath) as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [skip] {fpath}: {e}")
        continue
    for r in data:
        key = (r.get("symbol"), r.get("date"))
        if key in seen:
            continue  # same symbol+date appears across multiple checklist-variant files, count once
        seen.add(key)
        all_picks.append(r)

print(f"{len(all_picks)} unique symbol+date picks across all files\n")

def is_mover(r):
    nd = r.get("next_day_oc")
    td = r.get("three_day_cc")
    return (nd is not None and abs(nd) >= MOVE_THRESHOLD) or (td is not None and abs(td) >= MOVE_THRESHOLD)

movers = [r for r in all_picks if is_mover(r)]
non_movers = [r for r in all_picks if not is_mover(r)]

print(f"{len(movers)} picks moved >= {MOVE_THRESHOLD}% (next-day or 3-day)")
print(f"{len(non_movers)} picks did not\n")

def summarize(label, subset):
    n = len(subset)
    if n == 0:
        print(f"  {label}: n=0")
        return
    decisions = {}
    for r in subset:
        d = r.get("decision", "?")
        decisions[d] = decisions.get(d, 0) + 1
    pre_moves = [abs(r["pre_move_pct"]) for r in subset if r.get("pre_move_pct") is not None]
    zscores = [abs(r["z_score"]) for r in subset if r.get("z_score") is not None]
    avg_pre = sum(pre_moves) / len(pre_moves) if pre_moves else None
    avg_z = sum(zscores) / len(zscores) if zscores else None
    z_available_pct = len(zscores) / n * 100

    print(f"  {label}: n={n}")
    print(f"    decisions: {decisions}")
    if avg_pre is not None:
        print(f"    avg |pre_move_pct|: {avg_pre:.2f}%  (n={len(pre_moves)})")
    if avg_z is not None:
        print(f"    avg |z_score| (where available): {avg_z:.2f}  ({z_available_pct:.0f}% had a z-score)")
    else:
        print(f"    z_score available for {z_available_pct:.0f}% of picks")

print("=" * 70)
print("BIG MOVERS (>=10%) vs EVERYTHING ELSE — same metrics, compared")
print("=" * 70)
summarize("MOVERS", movers)
print()
summarize("NON-MOVERS", non_movers)

print(f"\n{'-'*70}")
print(f"Full list of movers, sorted by move size:\n")
def move_size(r):
    vals = [abs(v) for v in (r.get("next_day_oc"), r.get("three_day_cc")) if v is not None]
    return max(vals) if vals else 0

for r in sorted(movers, key=move_size, reverse=True):
    z = r.get("z_score")
    z_str = f"z={z:+.2f}" if z is not None else "z=N/A"
    print(f"{r.get('date')} {r.get('symbol',''):12s} {r.get('decision',''):11s} {z_str:8s} "
          f"pre_move={r.get('pre_move_pct')}  next_day={r.get('next_day_oc')}  3day={r.get('three_day_cc')}")
    print(f"    {r.get('reasoning','')[:110]}")
