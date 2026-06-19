content = open('kaal_sources.py').read()

new_func = '''
def fetch_oi_spurts() -> dict:
    """
    Fetch stocks with unusual OI buildup from NSE.
    High OI spurt = smart money positioning = confirm catalyst.
    Returns dict: {symbol: {oi_change, avg_oi_pct, volume}}
    """
    s = nse_session()
    oi_map = {}
    try:
        r = s.get(
            "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings",
            timeout=10
        )
        if r.status_code != 200:
            print(f"[SRC] OI spurts: HTTP {r.status_code}")
            return {}
        data = r.json().get("data", [])
        for item in data:
            symbol = item.get("symbol", "")
            if not symbol or symbol == "NIFTY":
                continue
            avg_oi = float(item.get("avgInOI", 0))
            oi_map[symbol] = {
                "oi_change":  int(item.get("changeInOI", 0)),
                "avg_oi_pct": avg_oi,
                "volume":     int(item.get("volume", 0)),
            }
        # Filter high conviction — OI spurt > 10%
        high_oi = {s: v for s, v in oi_map.items() if v["avg_oi_pct"] > 10}
        print(f"[SRC] OI spurts: {len(data)} total | {len(high_oi)} high conviction (>10%)")
        if high_oi:
            top = sorted(high_oi.items(), key=lambda x: -x[1]["avg_oi_pct"])[:5]
            print(f"[SRC] Top OI: {[(s, round(v['avg_oi_pct'],1)) for s,v in top]}")
    except Exception as e:
        print(f"[SRC] OI spurts error: {e}")
    return oi_map

'''

old = "def fetch_chartink_screeners"
content = content.replace(old, new_func + "def fetch_chartink_screeners")
open('kaal_sources.py', 'w').write(content)
print('Done')
