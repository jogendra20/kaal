from angel_provider import AngelOneProvider
from kaal_market_data import fetch_clean_bulk_deals
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


def main():
    now = datetime.now()
    print(f"Live watchlist check (Angel One LTP) -- {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    session = nse_session()
    provider = AngelOneProvider()

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

    print("=" * 70)
    print("LIVE LTP CHECK (Angel One) for watchlist symbols")
    print("=" * 70 + "\n")

    for sym, subjects in watchlist:
        quote = provider.get_ltp(sym)
        if not quote:
            print(f"{sym:12s} -> LTP fetch failed, see [ANGEL] warning above")
            continue
        pct_change = ((quote["ltp"] - quote["close"]) / quote["close"] * 100) if quote["close"] else None
        pct_str = f"{pct_change:+.2f}%" if pct_change is not None else "N/A"
        print(f"{sym:12s} LTP={quote['ltp']}  change_vs_prev_close={pct_str}  "
              f"day_high={quote['high']}  day_low={quote['low']}  prev_close={quote['close']}")
        print(f"             announcement: {subjects[0][:90] if subjects else 'n/a'}")

    print("\n" + "-" * 70)
    print("Checking bulk deals (real endpoint, from your own kaal_market_data.py)...")
    deals = fetch_clean_bulk_deals()
    watchlist_symbols = {sym for sym, _ in watchlist}
    relevant = [d for d in deals if d["symbol"] in watchlist_symbols]
    if relevant:
        print(f"Bulk deals matching watchlist: {relevant}")
    else:
        print(f"No clean net-buy bulk deals today for your current watchlist ({len(deals)} total deals checked).")

    print("\n" + "-" * 70)
    print("Delivery % NOT shown -- NSE only releases it after market close.")
    print("This confirms the full pipe: announcements -> watchlist -> live LTP")
    print("(Angel One) -> bulk deals. Not a signal or backtest result.")


if __name__ == "__main__":
    main()
