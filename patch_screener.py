content = open('kaal_sources.py').read()

new_func = '''
# ── CHARTINK SCREENERS ────────────────────────────────────────────────────────
CHARTINK_SCANS = {
    "gap_up": (
        "( {cash} ( latest close > 1.02 * 1 day ago close ) "
        "and ( latest volume > 100000 ) "
        "and ( latest close > 20 ) )"
    ),
    "52w_high": (
        "( {cash} ( latest high >= ( max( 52 , 1 week ago high ) ) ) "
        "and ( latest volume > 100000 ) "
        "and ( latest close > 20 ) )"
    ),
    "high_delivery": (
        "( {cash} ( latest volume > 2 * ( average( 20 , latest volume ) ) ) "
        "and ( latest close > latest open ) "
        "and ( latest close > 20 ) "
        "and ( latest volume > 300000 ) )"
    ),
    "momentum": (
        "( {cash} ( latest close > latest \"200 day EMA\" ) "
        "and ( latest \"RSI\" ( 14 ) > 60 ) "
        "and ( latest volume > 2 * ( average( 20 , latest volume ) ) ) "
        "and ( latest close > 20 ) )"
    ),
}


def fetch_chartink_screeners() -> dict:
    """
    Fetch stocks from Chartink public screeners.
    Returns dict of {screener_name: [symbols]}
    """
    import re
    results = {}
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://chartink.com/screener/",
        "X-Requested-With": "XMLHttpRequest",
    })

    try:
        r = session.get("https://chartink.com/screener/", timeout=10)
        csrf_match = re.search(r\'csrf-token"\\s+content="([^"]+)"\', r.text)
        if not csrf_match:
            print("[SRC] Chartink: no CSRF token")
            return {}
        csrf = csrf_match.group(1)
        session.headers.update({
            "X-CSRF-TOKEN": csrf,
            "Content-Type": "application/x-www-form-urlencoded",
        })
    except Exception as e:
        print(f"[SRC] Chartink session failed: {e}")
        return {}

    for name, clause in CHARTINK_SCANS.items():
        try:
            r2 = session.post(
                "https://chartink.com/screener/process",
                data={"_token": csrf, "scan_clause": clause},
                timeout=15
            )
            data = r2.json()
            if data.get("scan_error"):
                print(f"[SRC] Chartink {name}: error — {data['scan_error'][:50]}")
                continue
            stocks = [d.get("nsecode", "") for d in data.get("data", []) if d.get("nsecode")]
            # Filter out index symbols
            stocks = [s for s in stocks if not any(x in s for x in ["NIFTY", "CNX", "SENSEX", "BSE"])]
            results[name] = stocks[:30]
            print(f"[SRC] Chartink {name}: {len(stocks)} stocks")
            if stocks[:5]:
                print(f"  Top 5: {stocks[:5]}")
        except Exception as e:
            print(f"[SRC] Chartink {name} failed: {e}")
            results[name] = []

    return results

'''

old = "def fetch_preopen_gainers"
content = content.replace(old, new_func + "def fetch_preopen_gainers")
open('kaal_sources.py', 'w').write(content)
print('Done')
