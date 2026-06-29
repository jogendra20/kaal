# Add fetch_eod_prices function to kaal_sources.py
content = open('kaal_sources.py').read()

new_func = '''
def fetch_eod_prices(symbols: list) -> dict:
    """
    Fetch today's closing prices for a list of symbols using NSE quote API.
    Called from evening run to store catalyst-day close in signal_history.
    Returns: {symbol: {"close": float, "prev_close": float, "change_pct": float}}
    """
    s = nse_session()
    prices = {}
    for symbol in symbols:
        try:
            r = s.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                pd = data.get("priceInfo", {})
                close      = pd.get("lastPrice", 0)
                prev_close = pd.get("previousClose", 0)
                chg_pct    = pd.get("pChange", 0)
                if close > 0:
                    prices[symbol] = {
                        "close":      close,
                        "prev_close": prev_close,
                        "change_pct": chg_pct,
                    }
        except Exception as e:
            print(f"[SRC] EOD price error {symbol}: {e}")
    print(f"[SRC] EOD prices fetched: {len(prices)}/{len(symbols)} symbols")
    return prices

'''

old = "def fetch_chartink_screeners"
content = content.replace(old, new_func + "def fetch_chartink_screeners")
open('kaal_sources.py', 'w').write(content)
print('Done')
