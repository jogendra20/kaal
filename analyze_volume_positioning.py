import csv, glob, json, time
from datetime import datetime, timedelta
import requests

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

_bhav_cache = {}

def get_bhavcopy_day(d):
    """Same NSE archives file every prior script used — but this time reading
    DELIV_PER and TTL_TRD_QNTY, which were sitting in the same CSV unused."""
    key = d.strftime("%Y-%m-%d")
    if key in _bhav_cache:
        return _bhav_cache[key]
    date_str = d.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            _bhav_cache[key] = {}
            return {}
        reader = csv.DictReader(r.text.splitlines())
        result = {}
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("SERIES") != "EQ":
                continue
            sym = row.get("SYMBOL", "")
            if not sym:
                continue
            try:
                result[sym] = {
                    "volume": float(row.get("TTL_TRD_QNTY", 0) or 0),
                    "deliv_pct": float(row.get("DELIV_PER", 0) or 0) if row.get("DELIV_PER", "-").strip() != "-" else None,
                    "close": float(row.get("CLOSE_PRICE", 0) or 0),
                    "prev_close": float(row.get("PREV_CLOSE", 0) or 0),
                    "open": float(row.get("OPEN_PRICE", 0) or 0),
                }
            except (ValueError, TypeError):
                continue
        _bhav_cache[key] = result
        return result
    except Exception as e:
        print(f"  [WARN] bhavcopy fetch failed for {key}: {e}")
        _bhav_cache[key] = {}
        return {}


def nearby_trading_days(center, back=0, fwd=0):
    days = []
    d = center - timedelta(days=back * 2 + 5)
    while d <= center + timedelta(days=fwd * 2 + 5):
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def compute_volume_signals(symbol, result_date):
    """RVOL and delivery% context around a results date, using only data
    available BEFORE the event (trailing days strictly before result_date) —
    plus the day-of and next-day gap, which are the actual reaction, not a
    predictive input."""
    prior_days = [d for d in nearby_trading_days(result_date, back=12) if d < result_date][-10:]
    prior_vols, prior_delivs = [], []
    for d in prior_days:
        bar = get_bhavcopy_day(d).get(symbol)
        if bar and bar["volume"] > 0:
            prior_vols.append(bar["volume"])
            if bar["deliv_pct"] is not None:
                prior_delivs.append(bar["deliv_pct"])

    if len(prior_vols) < 5:
        return None  # not enough trailing data to trust an average

    avg_trailing_vol = sum(prior_vols) / len(prior_vols)
    avg_trailing_deliv = sum(prior_delivs) / len(prior_delivs) if prior_delivs else None

    # day-of and next-day figures (the announcement day itself, and the reaction day)
    result_bar = get_bhavcopy_day(result_date).get(symbol)
    fwd_days = [d for d in nearby_trading_days(result_date, fwd=3) if d > result_date]
    next_bar = None
    for d in fwd_days:
        b = get_bhavcopy_day(d).get(symbol)
        if b:
            next_bar = b
            break

    out = {"avg_trailing_vol": avg_trailing_vol, "avg_trailing_deliv_pct": avg_trailing_deliv}

    if result_bar and result_bar["volume"] > 0:
        out["result_day_rvol"] = round(result_bar["volume"] / avg_trailing_vol, 2)
        out["result_day_deliv_pct"] = result_bar["deliv_pct"]
    if next_bar and next_bar["volume"] > 0:
        out["next_day_rvol"] = round(next_bar["volume"] / avg_trailing_vol, 2)
        out["next_day_deliv_pct"] = next_bar["deliv_pct"]
        if result_bar and result_bar["close"]:
            out["next_day_gap_pct"] = round((next_bar["open"] - result_bar["close"]) / result_bar["close"] * 100, 2)

    return out


def load_all_picks():
    files = sorted(glob.glob("fy27_backtest_results*.json"))
    seen = set()
    picks = []
    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)
        except Exception:
            continue
        for r in data:
            key = (r.get("symbol"), r.get("date"))
            if key in seen:
                continue
            seen.add(key)
            picks.append(r)
    return picks


MOVE_THRESHOLD = 10.0

def is_mover(r):
    nd = r.get("next_day_oc")
    td = r.get("three_day_cc")
    return (nd is not None and abs(nd) >= MOVE_THRESHOLD) or (td is not None and abs(td) >= MOVE_THRESHOLD)


def main():
    picks = load_all_picks()
    print(f"{len(picks)} unique symbol+date events to check\n")

    enriched = []
    for i, r in enumerate(picks, 1):
        symbol, date_str = r.get("symbol"), r.get("date")
        if not symbol or not date_str:
            continue
        try:
            result_date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        print(f"[{i}/{len(picks)}] {symbol} {date_str}...")
        sig = compute_volume_signals(symbol, result_date)
        if sig:
            enriched.append({**r, **sig})
        time.sleep(0.3)

    with open("volume_positioning_enriched.json", "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"\n{len(enriched)} events had enough trailing volume history\n")

    movers = [r for r in enriched if is_mover(r)]
    non_movers = [r for r in enriched if not is_mover(r)]

    def summarize(label, subset):
        n = len(subset)
        if n == 0:
            print(f"  {label}: n=0")
            return
        rvols = [r["result_day_rvol"] for r in subset if r.get("result_day_rvol") is not None]
        next_rvols = [r["next_day_rvol"] for r in subset if r.get("next_day_rvol") is not None]
        delivs = [r["result_day_deliv_pct"] for r in subset if r.get("result_day_deliv_pct") is not None]
        avg_delivs = [r["avg_trailing_deliv_pct"] for r in subset if r.get("avg_trailing_deliv_pct") is not None]
        gaps = [abs(r["next_day_gap_pct"]) for r in subset if r.get("next_day_gap_pct") is not None]

        print(f"  {label}: n={n}")
        if rvols:
            print(f"    avg result-day RVOL: {sum(rvols)/len(rvols):.2f}  (n={len(rvols)})")
        if next_rvols:
            print(f"    avg next-day RVOL:   {sum(next_rvols)/len(next_rvols):.2f}  (n={len(next_rvols)})")
        if delivs:
            print(f"    avg result-day deliv%%: {sum(delivs)/len(delivs):.1f}%%  (n={len(delivs)})")
        if avg_delivs:
            print(f"    avg TRAILING (normal) deliv%%: {sum(avg_delivs)/len(avg_delivs):.1f}%%  (n={len(avg_delivs)})")
        if gaps:
            print(f"    avg |next-day gap%%|: {sum(gaps)/len(gaps):.2f}%%  (n={len(gaps)})")

    print("=" * 70)
    print("VOLUME/POSITIONING SIGNALS — MOVERS vs NON-MOVERS")
    print("=" * 70)
    summarize("MOVERS (>=10%)", movers)
    print()
    summarize("NON-MOVERS", non_movers)

    print(f"\n{'-'*70}")
    print("Movers detail, sorted by result-day RVOL (highest first):\n")
    def sort_key(r):
        return r.get("result_day_rvol") or 0
    for r in sorted(movers, key=sort_key, reverse=True):
        print(f"{r.get('date')} {r.get('symbol',''):12s} "
              f"RVOL={r.get('result_day_rvol','N/A')}  next_RVOL={r.get('next_day_rvol','N/A')}  "
              f"deliv%={r.get('result_day_deliv_pct','N/A')} (normal={r.get('avg_trailing_deliv_pct','N/A')})  "
              f"gap%={r.get('next_day_gap_pct','N/A')}  "
              f"actual_move: next_day={r.get('next_day_oc')} 3day={r.get('three_day_cc')}")


if __name__ == "__main__":
    main()
