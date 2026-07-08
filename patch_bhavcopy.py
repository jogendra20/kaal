content = open('kaal_sources.py').read()

new_func = '''
def fetch_bhavcopy(date_str: str = None) -> dict:
    """
    Fetch NSE bhavcopy for a given date (ddmmyyyy format).
    Returns dict: {symbol: {close, prev_close, chg_pct, deliv_qty, deliv_per, volume}}
    Published after market close (~7PM). Use previous trading day's date.
    """
    import csv
    from datetime import datetime, timedelta
    import requests as req

    if not date_str:
        # Use yesterday by default (today's file not published till 7PM)
        date_str = (datetime.now() - timedelta(days=1)).strftime("%d%m%Y")

    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        r = req.get(url, headers=headers, timeout=(5, 15))
        if r.status_code != 200:
            print(f"[SRC] Bhavcopy {date_str}: HTTP {r.status_code}")
            return {}

        reader = csv.DictReader(r.text.splitlines())
        result = {}
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("SERIES") != "EQ":
                continue
            symbol = row.get("SYMBOL", "")
            if not symbol:
                continue
            try:
                close      = float(row.get("CLOSE_PRICE", 0))
                prev_close = float(row.get("PREV_CLOSE", 0))
                chg_pct    = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
                deliv_qty  = int(float(row.get("DELIV_QTY", 0)))
                deliv_per  = float(row.get("DELIV_PER", 0))
                volume     = int(float(row.get("TTL_TRD_QNTY", 0)))
                result[symbol] = {
                    "close":      close,
                    "prev_close": prev_close,
                    "chg_pct":    chg_pct,
                    "deliv_qty":  deliv_qty,
                    "deliv_per":  deliv_per,
                    "volume":     volume,
                }
            except Exception:
                continue

        print(f"[SRC] Bhavcopy {date_str}: {len(result)} EQ stocks loaded")
        return result

    except Exception as e:
        print(f"[SRC] Bhavcopy error: {e}")
        return {}


def classify_delivery(deliv_per: float, chg_pct: float) -> dict:
    """
    Classify delivery % + price change into a signal type.
    Returns {label, emoji, note}
    """
    if deliv_per >= 60 and chg_pct > 0:
        return {"label": "GENUINE_DEMAND",  "emoji": "🟢", "note": f"High delivery {deliv_per:.1f}% + rising — real buyers accumulating"}
    if deliv_per >= 60 and chg_pct <= 0:
        return {"label": "ACCUMULATION",    "emoji": "🔵", "note": f"High delivery {deliv_per:.1f}% despite flat/down — institutions accumulating"}
    if deliv_per < 30 and chg_pct > 3:
        return {"label": "SHORT_SQUEEZE",   "emoji": "⚠️", "note": f"Low delivery {deliv_per:.1f}% + big rise — short covering, not real demand"}
    if deliv_per < 30 and chg_pct < 0:
        return {"label": "WEAK",            "emoji": "🔴", "note": f"Low delivery {deliv_per:.1f}% + falling — weak hands, avoid"}
    return {"label": "NEUTRAL",             "emoji": "⚪", "note": f"Delivery {deliv_per:.1f}% — mixed signal"}

'''

old = "def fetch_eod_prices"
content = content.replace(old, new_func + "def fetch_eod_prices")
open('kaal_sources.py', 'w').write(content)
print('Done')
