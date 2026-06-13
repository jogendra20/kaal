content = open('kaal_sources.py').read()

new_func = '''
def fetch_preopen_gainers() -> list:
    """
    Fetch pre-open market data from NSE.
    Returns list of stocks with gap % sorted by gainers.
    Best called between 9:00-9:15AM.
    """
    results = []
    seen = set()
    keys = ["NIFTY", "FO", "ALL"]
    s = nse_session()

    for key in keys:
        try:
            r = s.get(
                f"https://www.nseindia.com/api/market-data-pre-open?key={key}",
                timeout=10
            )
            if r.status_code != 200:
                continue
            data = r.json().get("data", [])
            for item in data:
                meta = item.get("metadata", {})
                symbol = meta.get("symbol", "")
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                prev_close = float(meta.get("previousClose") or meta.get("prevClose") or 0)
                final_price = float(meta.get("finalPrice") or meta.get("iep") or 0)
                if not prev_close or not final_price:
                    continue
                gap_pct = round(((final_price - prev_close) / prev_close) * 100, 2)
                total_vol = float(meta.get("totalTradedVolume") or 0)
                results.append({
                    "symbol":     symbol,
                    "gap_pct":    gap_pct,
                    "price":      final_price,
                    "prev_close": prev_close,
                    "volume":     total_vol,
                    "source":     "NSE_PREOPEN",
                })
        except Exception as e:
            print(f"[SRC] Pre-open {key} error: {e}")

    # Sort by gap descending
    results.sort(key=lambda x: -x["gap_pct"])
    gainers = [r for r in results if r["gap_pct"] >= 2.0]
    losers  = [r for r in results if r["gap_pct"] <= -2.0]
    print(f"[SRC] Pre-open: {len(gainers)} gap-up, {len(losers)} gap-down stocks")
    return results

'''

# Add before fetch_news
old = "def fetch_news():"
content = content.replace(old, new_func + "def fetch_news():")
open('kaal_sources.py', 'w').write(content)
print('Done')
