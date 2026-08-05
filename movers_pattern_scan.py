import csv, json, time
from datetime import datetime, timedelta
import requests

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

SCAN_DAYS = 40
MOVE_THRESHOLD = 7.0
MIN_TURNOVER_CR = 30
CHECKPOINT_FILE = "movers_pattern_scan.json"


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


_bhav_cache = {}

def get_bhavcopy_day(d):
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
                close = float(row.get("CLOSE_PRICE", 0) or 0)
                prev_close = float(row.get("PREV_CLOSE", 0) or 0)
                turnover_cr = float(row.get("TURNOVER_LACS", 0) or 0) / 100.0
                pct_move = ((close - prev_close) / prev_close * 100) if prev_close else None
                result[sym] = {"close": close, "prev_close": prev_close,
                                "turnover_cr": turnover_cr, "pct_move": pct_move}
            except (ValueError, TypeError):
                continue
        _bhav_cache[key] = result
        return result
    except Exception as e:
        print(f"  [WARN] bhavcopy fetch failed for {key}: {e}")
        _bhav_cache[key] = {}
        return {}


def trading_days_back(from_date, n):
    out = []
    d = from_date
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    out.reverse()
    return out


def fetch_announcements_window(session, symbol, center_date):
    from_date = center_date - timedelta(days=1)
    to_date = center_date
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&symbol={symbol}"
           f"&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={to_date.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"    [WARN] announcement fetch failed for {symbol}: {e}")
        return []


PROMOTER_KEYWORDS = [
    "pledge", "pledged", "pledging", "release of pledge", "revocation of pledge",
    "promoter shareholding", "stake sale", "stake sold", "stake acquired by promoter",
    "buyback", "insider trading", "sast", "acquisition of shares by promoter",
    "encumbrance", "invocation",
]

CATALYST_KEYWORDS = [
    "financial result", "quarterly result", "outcome of board meeting",
    "acquisition", "order win", "bags order", "contract", "capacity expansion",
    "capex", "joint venture", "merger", "demerger", "scheme of arrangement",
    "credit rating", "dividend", "new product", "regulatory approval",
    "qualified institutional", "rights issue", "preferential issue",
]


def classify_movers_announcements(anns):
    if not anns:
        return "UNEXPLAINED", []

    matched = []
    is_promoter = False
    is_catalyst = False
    for a in anns:
        if not isinstance(a, dict):
            continue
        text = ((a.get("desc") or a.get("subject") or "") + " " +
                (a.get("attchmntText") or "")).lower()
        if any(kw in text for kw in PROMOTER_KEYWORDS):
            is_promoter = True
            matched.append(a.get("desc") or a.get("subject") or "")
        elif any(kw in text for kw in CATALYST_KEYWORDS):
            is_catalyst = True
            matched.append(a.get("desc") or a.get("subject") or "")

    if is_promoter:
        return "PROMOTER", matched
    if is_catalyst:
        return "CATALYST", matched
    return "UNEXPLAINED", matched


def fetch_liquid_universe(min_turnover_cr=50, per_index_top_n=15):
    index_urls = {
        "NIFTY MIDCAP 150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        "NIFTY SMALLCAP 250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    }
    probe_date = datetime.now() - timedelta(days=3)
    day_data = {}
    for _ in range(7):
        day_data = get_bhavcopy_day(probe_date)
        if day_data:
            break
        probe_date -= timedelta(days=1)
    if not day_data:
        print("  [WARN] could not find a recent bhavcopy day with data")
        return []

    universe = []
    for idx_name, url in index_urls.items():
        try:
            r = requests.get(url, headers=NSE_HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"  [WARN] {idx_name} constituent list fetch failed: {r.status_code}")
                continue
            reader = csv.DictReader(r.text.splitlines())
            syms = [row.get("Symbol") or row.get("SYMBOL") for row in reader]
            syms = [s.strip() for s in syms if s]
        except Exception as e:
            print(f"  [WARN] {idx_name} exception: {e}")
            continue
        ranked = []
        for sym in syms:
            bar = day_data.get(sym)
            if bar and bar["turnover_cr"] >= min_turnover_cr:
                ranked.append((sym, bar["turnover_cr"]))
        ranked.sort(key=lambda x: -x[1])
        top = ranked[:per_index_top_n]
        if top:
            print(f"  {idx_name}: {len(top)} liquid names")
        universe.extend(s for s, _ in top)
    return sorted(set(universe))


def save_checkpoint(events):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(events, f, indent=2)


def main():
    print(f"Scanning last {SCAN_DAYS} trading days for movers >= {MOVE_THRESHOLD}%\n")

    universe = fetch_liquid_universe()
    print(f"\nUniverse: {len(universe)} liquid mid/small-caps\n")

    session = nse_session()
    latest_usable = datetime.now() - timedelta(days=3)
    scan_dates = trading_days_back(latest_usable, SCAN_DAYS)

    events = []
    days_with_data = 0
    days_empty = 0

    for i, d in enumerate(scan_dates, 1):
        day_data = get_bhavcopy_day(d)
        if not day_data:
            days_empty += 1
            print(f"[{i}/{len(scan_dates)}] {d.strftime('%Y-%m-%d')} -> no bhavcopy data")
            continue
        days_with_data += 1

        movers_today = []
        for sym in universe:
            bar = day_data.get(sym)
            if not bar or bar["pct_move"] is None:
                continue
            if bar["turnover_cr"] < MIN_TURNOVER_CR:
                continue
            if abs(bar["pct_move"]) >= MOVE_THRESHOLD:
                movers_today.append((sym, bar["pct_move"]))

        print(f"[{i}/{len(scan_dates)}] {d.strftime('%Y-%m-%d')} -> {len(movers_today)} movers")

        for sym, pct_move in movers_today:
            anns = fetch_announcements_window(session, sym, d)
            time.sleep(0.4)
            category, matched = classify_movers_announcements(anns)
            events.append({
                "date": d.strftime("%Y-%m-%d"), "symbol": sym,
                "pct_move": round(pct_move, 2), "category": category,
                "matched_announcements": matched[:2],
            })
            save_checkpoint(events)
            tag = "!" if category != "UNEXPLAINED" else " "
            print(f"    {tag} {sym:12s} {pct_move:+.2f}%  -> {category}")

    print(f"\n{'='*70}")
    print(f"{days_with_data} days with bhavcopy data, {days_empty} empty")
    if days_with_data < SCAN_DAYS * 0.5:
        print("WARNING: many days came back empty. Before scaling SCAN_DAYS up,")
        print("check whether this is holiday-normal or a real data gap.")
    print(f"{'='*70}\n")

    total = len(events)
    if total == 0:
        print("No mover events found — nothing to report.")
        return

    by_cat = {}
    for e in events:
        by_cat.setdefault(e["category"], []).append(e)

    print(f"SUMMARY over {total} mover events ({MOVE_THRESHOLD}%+ moves)\n")
    for cat in ("CATALYST", "PROMOTER", "UNEXPLAINED"):
        subset = by_cat.get(cat, [])
        pct = len(subset) / total * 100
        print(f"  {cat:12s}: {len(subset)} events ({pct:.1f}%)")

    print(f"\n{'-'*70}")
    print("UNEXPLAINED movers (no catalyst or promoter filing found) — these are")
    print("the ones worth checking with intraday volume data in Phase B:\n")
    for e in by_cat.get("UNEXPLAINED", []):
        print(f"{e['date']} {e['symbol']:12s} {e['pct_move']:+.2f}%")


if __name__ == "__main__":
    main()
