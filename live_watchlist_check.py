import requests
from datetime import datetime, timedelta

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "AXISBANK",
    "SUZLON", "KALYANKJIL", "SWIGGY", "KAYNES", "COFORGE", "PCBL",
]


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


def fetch_recent_announcements(session, symbol, hours_back=16):
    now = datetime.now()
    from_date = now - timedelta(hours=hours_back)
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&symbol={symbol}"
           f"&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={now.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [WARN] announcement fetch failed for {symbol}: {e}")
        return []


def fetch_live_quote(session, symbol):
    page_url = f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"
    try:
        session.get(page_url, timeout=15, headers={"Referer": "https://www.nseindia.com/"})
    except Exception:
        pass

    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    try:
        r = session.get(url, timeout=15, headers={"Referer": page_url})
        if r.status_code != 200:
            return {"_error_status": r.status_code}
        data = r.json()
        price = data.get("priceInfo", {})
        return {
            "ltp": price.get("lastPrice"),
            "day_high": price.get("intraDayHighLow", {}).get("max"),
            "day_low": price.get("intraDayHighLow", {}).get("min"),
            "prev_close": price.get("previousClose"),
            "pct_change": price.get("pChange"),
        }
    except Exception as e:
        return {"_error_exception": str(e)}


def main():
    now = datetime.now()
    print(f"Live watchlist check -- {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    session = nse_session()

    watchlist = []
    for sym in UNIVERSE:
        anns = fetch_recent_announcements(session, sym)
        if anns:
            subjects = [a.get("desc") or a.get("subject") or "" for a in anns if isinstance(a, dict)]
            watchlist.append((sym, subjects))
            print(f"  {sym}: {len(anns)} announcement(s) in last 16h -- {subjects[:1]}")

    print(f"\n{len(watchlist)} of {len(UNIVERSE)} symbols have recent announcements\n")

    if not watchlist:
        print("No announcements found for this starter universe right now.")
        return

    print(f"{'='*70}")
    print("LIVE QUOTE CHECK for watchlist symbols")
    print(f"{'='*70}\n")

    for sym, subjects in watchlist:
        quote = fetch_live_quote(session, sym)
        if "_error_status" in quote or "_error_exception" in quote:
            print(f"{sym:12s} -> quote fetch failed: {quote}")
            continue
        print(f"{sym:12s} LTP={quote['ltp']}  pct_change={quote['pct_change']}%  "
              f"day_high={quote['day_high']}  day_low={quote['day_low']}  "
              f"prev_close={quote['prev_close']}")
        print(f"             announcement: {subjects[0][:90] if subjects else 'n/a'}")

    print(f"\n{'-'*70}")
    print("Delivery % NOT shown -- NSE only releases it after market close.")
    print("This snapshot only confirms the pipe works. Not a signal or backtest result.")


if __name__ == "__main__":
    main()
