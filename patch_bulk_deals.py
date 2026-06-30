content = open('kaal_sources.py').read()

new_func = '''
def fetch_clean_bulk_deals() -> list:
    """
    Fetch NSE bulk deals and filter to clean one-sided net buys only
    (no same-day offsetting sell from the same client — excludes
    arbitrage/market-making noise that dominates raw bulk deal data).
    Returns list of {symbol, client, qty, price, is_fund} dicts.
    """
    from collections import defaultdict
    from datetime import datetime, timedelta
    s = nse_session()

    today = datetime.now().strftime("%d-%m-%Y")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")

    try:
        r = s.get(
            f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
            f"?optionType=bulk_deals&from={yesterday}&to={today}",
            timeout=10
        )
        if r.status_code != 200:
            print(f"[SRC] Bulk deals: HTTP {r.status_code}")
            return []
        data = r.json().get("data", [])
    except Exception as e:
        print(f"[SRC] Bulk deals error: {e}")
        return []

    net = defaultdict(lambda: {"buy": 0, "sell": 0, "price": 0})
    for d in data:
        key = (d.get("BD_SYMBOL", ""), d.get("BD_CLIENT_NAME", ""))
        qty = d.get("BD_QTY_TRD", 0)
        if d.get("BD_BUY_SELL") == "BUY":
            net[key]["buy"] += qty
            net[key]["price"] = d.get("BD_TP_WATP", 0)
        else:
            net[key]["sell"] += qty

    # Known fund/institution name patterns — weight these higher
    FUND_KEYWORDS = ["MUTUAL FUND", "FLAGSHIP", "GROWTH FUND", "PMS",
                      "CAPITAL", "VENTURES", "INVESTMENTS", "ASSET MANAGEMENT"]

    clean_buys = []
    for (symbol, client), v in net.items():
        if v["buy"] > 0 and v["sell"] == 0:
            is_fund = any(kw in client.upper() for kw in FUND_KEYWORDS)
            clean_buys.append({
                "symbol":  symbol,
                "client":  client,
                "qty":     v["buy"],
                "price":   v["price"],
                "is_fund": is_fund,
            })

    print(f"[SRC] Bulk deals: {len(data)} raw → {len(clean_buys)} clean net buys")
    return clean_buys

'''

old = "def fetch_chartink_screeners"
content = content.replace(old, new_func + "def fetch_chartink_screeners")
open('kaal_sources.py', 'w').write(content)
print('Done')
