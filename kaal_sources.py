"""
kaal_sources.py
Data acquisition layer.
Fixes: GIFT Nifty (real SGX/NSE futures proxy), liquidity gate, promoter PIT.
"""
import requests, time, feedparser, io
try:
    import yfinance as yf
    YFINANCE_OK = True
except Exception:
    YFINANCE_OK = False
from datetime import datetime, timedelta
from kaal_config import RSS_FEEDS, MIN_VOLUME_CR

try:
    from nselib import capital_market, derivatives
    NSELIB_OK = True
except Exception:
    NSELIB_OK = False

HEADERS_NSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
    "Referer":    "https://www.nseindia.com",
}
HEADERS_BSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
    "Origin":     "https://www.bseindia.com",
    "Referer":    "https://www.bseindia.com/",
}

_nse_session = None

def nse_session():
    global _nse_session
    if _nse_session is None:
        s = requests.Session()
        s.headers.update(HEADERS_NSE)
        try:
            s.get("https://www.nseindia.com", timeout=15)
            time.sleep(1)
        except Exception:
            pass
        _nse_session = s
    return _nse_session


# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────
def fetch_nse_announcements():
    today     = datetime.now().strftime("%d-%m-%Y")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
    try:
        s   = nse_session()
        url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={yesterday}&to_date={today}"
        r   = s.get(url, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[SRC] NSE announcements error: {e}")
        return []


def fetch_bse_bulk_block():
    today = datetime.now().strftime("%Y%m%d")
    deals = []
    for dtype in ["BulkDeal", "BlockDeal"]:
        try:
            url = f"https://api.bseindia.com/BseIndiaAPI/api/{dtype}/w?strDt={today}&strEDt={today}"
            r   = requests.get(url, headers=HEADERS_BSE, timeout=15)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                items = r.json().get("Table", [])
                for item in items:
                    item["_deal_type"] = dtype.replace("Deal", "").upper()
                deals.extend(items)
        except Exception:
            pass
    return deals


# ── MACRO DATA ────────────────────────────────────────────────────────────────
def _stooq_quote(symbol: str) -> tuple:
    """Returns (price, chg_pct) using Stooq — more reliable from India/Termux."""
    try:
        import csv, io
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return 0, 0
        reader = csv.DictReader(io.StringIO(r.text))
        rows = [row for row in reader if row.get("Close") and row["Close"] not in ("null","")]
        if len(rows) >= 2:
            prev  = float(rows[-2]["Close"])
            close = float(rows[-1]["Close"])
            chg   = round(((close - prev) / prev) * 100, 2)
            return round(close, 2), chg
    except Exception:
        pass
    return 0, 0


def _yahoo_quote(symbol: str) -> tuple:
    """Returns (price, chg_pct) — compares last two daily closes explicitly."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=(5, 10))
        if r.status_code != 200:
            return 0, 0
        data   = r.json()
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c, t in zip(closes, timestamps) if c is not None]
        timestamps = [t for c, t in zip(closes, timestamps) if c is not None]
        timestamps_clean = [t for t, c in zip(timestamps, closes) if c is not None]
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        # US markets close at 21:00 UTC (4PM ET)
        # If current UTC hour >= 21 or < 13: US markets closed — use last close
        # If current UTC hour 13-21: US markets open — use second to last close
        us_open = 13 <= now_utc.hour < 21
        # Sanity check: if latest close deviates >3% from prev, likely bad data
        def pick_closes(closes):
            if len(closes) >= 2:
                c = closes[-1]
                p = closes[-2]
                if p and abs((c - p) / p) > 0.03 and len(closes) >= 3:
                    # Suspicious — use prev two instead
                    return closes[-3], closes[-2]
                return p, c
            return 0, 0

        if us_open and len(closes) >= 3:
            prev  = closes[-3]
            close = closes[-2]
        else:
            prev, close = pick_closes(closes)
            if not prev:
                return 0, 0
        chg = round(((close - prev) / prev) * 100, 2)
        return round(close, 2), chg
        # fallback to meta
        meta  = result.get("meta", {})
        close = float(meta.get("regularMarketPrice") or 0)
        prev  = float(meta.get("chartPreviousClose") or 0)
        if close and prev:
            chg = round(((close - prev) / prev) * 100, 2)
            return round(close, 2), chg
    except Exception:
        pass
    return 0, 0


def fetch_macro():
    macro = {}

    # SPX — stooq symbol: ^spx
    price, chg = _stooq_quote("^spx")
    if not price:
        price, chg = _yahoo_quote("%5EGSPC")
    macro["spx"] = price
    macro["spx_chg"] = chg
    print(f"[SRC] SPX: {price} ({chg:+.2f}%)")

    # Crude — stooq symbol: cl.f
    price, chg = _stooq_quote("cl.f")
    if not price:
        price, chg = _yahoo_quote("CL=F")
    macro["crude"] = price
    macro["crude_chg"] = chg
    print(f"[SRC] Crude: {price} ({chg:+.2f}%)")

    # Gold — stooq symbol: gc.f
    price, chg = _stooq_quote("gc.f")
    if not price:
        price, chg = _yahoo_quote("GC=F")
    macro["gold"] = price
    macro["gold_chg"] = chg
    print(f"[SRC] Gold: {price} ({chg:+.2f}%)")

    # USD/INR — stooq symbol: inrusd (inverted, need to flip)
    price, chg = _stooq_quote("inr.usd")
    if price:
        usdinr = round(1 / price, 2) if price else 0
        chg    = -round(chg, 2)
        macro["usdinr"] = usdinr
        macro["usdinr_chg"] = chg
    else:
        price, chg = _yahoo_quote("INR=X")
        macro["usdinr"] = price
        macro["usdinr_chg"] = chg
    print(f"[SRC] USD/INR: {macro['usdinr']} ({macro['usdinr_chg']:+.2f}%)")

    # India VIX — live from NSE allIndices
    try:
        s = nse_session()
        r = s.get("https://www.nseindia.com/api/allIndices", timeout=10)
        indices = r.json().get("data", [])
        for idx in indices:
            if idx.get("indexSymbol", "").upper() == "INDIA VIX":
                macro["vix"] = float(idx.get("last", 15))
                print(f"[SRC] VIX (live NSE): {macro['vix']}")
                break
        else:
            raise Exception("VIX not found")
    except Exception:
        try:
            if NSELIB_OK:
                vix_data = capital_market.india_vix_data(period="1W")
                macro["vix"] = float(vix_data.iloc[-1]["CLOSE_INDEX_VAL"])
                print(f"[SRC] VIX (nselib): {macro['vix']}")
            else:
                raise Exception("nselib unavailable")
        except Exception:
            macro["vix"] = 15
            print(f"[SRC] VIX: fallback 15")

    # GIFT Nifty — stooq → Yahoo → SPX proxy
    gift_done = False

    try:
        import csv, io
        r = requests.get(
            "https://stooq.com/q/d/l/?s=nifty.f&i=d",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if r.status_code == 200:
            reader = csv.DictReader(io.StringIO(r.text))
            rows = [row for row in reader if row.get("Close") and row["Close"] not in ("null", "")]
            if len(rows) >= 2:
                prev  = float(rows[-2]["Close"])
                close = float(rows[-1]["Close"])
                chg   = round(((close - prev) / prev) * 100, 2)
                macro["gift_nifty_pct"]  = chg
                macro["gift_nifty_bias"] = "Bullish" if chg > 0.3 else ("Bearish" if chg < -0.3 else "Neutral")
                print(f"[SRC] GIFT Nifty (stooq): {chg:+.2f}% → {macro['gift_nifty_bias']}")
                gift_done = True
    except Exception as e:
        print(f"[SRC] stooq failed: {e}")

    if not gift_done:
        try:
            price, chg = _yahoo_quote("%5ENSEI")
            if chg is not None:
                macro["gift_nifty_pct"]  = round(chg, 2)
                macro["gift_nifty_bias"] = "Bullish" if chg > 0.3 else ("Bearish" if chg < -0.3 else "Neutral")
                print(f"[SRC] GIFT Nifty (Yahoo): {chg:+.2f}% → {macro['gift_nifty_bias']}")
                gift_done = True
        except Exception as e:
            print(f"[SRC] Yahoo Nifty failed: {e}")

    if not gift_done:
        spx_chg = macro.get("spx_chg", 0)
        macro["gift_nifty_bias"] = "Bullish" if spx_chg > 0.5 else ("Bearish" if spx_chg < -0.5 else "Neutral")
        macro["gift_nifty_pct"]  = round(spx_chg * 0.6, 2)
        print(f"[SRC] GIFT Nifty (SPX proxy): {macro['gift_nifty_pct']:+.2f}% → {macro['gift_nifty_bias']}")

    return macro

def fetch_asm_gsm_ban():
    s      = nse_session()
    result = {"asm": set(), "gsm": set(), "ban": set()}
    try:
        r    = s.get("https://www.nseindia.com/api/reportASM", timeout=10)
        data = r.json().get("longterm", {}).get("data", [])
        result["asm"] = {d.get("symbol", "").upper() for d in data}
    except Exception: pass
    try:
        r    = s.get("https://www.nseindia.com/api/reportGSM", timeout=10)
        data = r.json() if isinstance(r.json(), list) else []
        result["gsm"] = {d.get("symbol", "").upper() for d in data}
    except Exception: pass
    try:
        if NSELIB_OK:
            today = datetime.now().strftime("%d-%m-%Y")
            ban   = derivatives.fno_security_in_ban_period(trade_date=today)
            if ban is not None and hasattr(ban, "__iter__"):
                result["ban"] = {str(x).upper() for x in ban}
    except Exception: pass
    return result


# ── NEWS ─────────────────────────────────────────────────────────────────────


# Sector index to trading keywords mapping
SECTOR_MAP = {
    "NIFTY BANK":        ["BANK", "BANKING", "FINANCE"],
    "NIFTY PVT BANK":    ["BANK", "HDFC", "ICICI", "AXIS", "KOTAK"],
    "NIFTY PSU BANK":    ["PSU", "SBI", "PNB", "BOB", "CANARA"],
    "NIFTY FIN SERVICE": ["NBFC", "FINANCE", "FINSERV"],
    "NIFTY PHARMA":      ["PHARMA", "DRUG", "API", "MEDICINE"],
    "NIFTY HEALTHCARE":  ["HOSPITAL", "HEALTH", "DIAGNOSTIC"],
    "NIFTY IT":          ["IT", "SOFTWARE", "TECH", "INFOTECH"],
    "NIFTY AUTO":        ["AUTO", "VEHICLE", "EV", "TYRE"],
    "NIFTY METAL":       ["STEEL", "METAL", "ALUMINIUM", "COPPER"],
    "NIFTY REALTY":      ["REALTY", "REAL ESTATE", "HOUSING", "PROPERTY"],
    "NIFTY FMCG":        ["FMCG", "CONSUMER", "FOOD", "BEVERAGES"],
    "NIFTY OIL AND GAS": ["OIL", "GAS", "REFINERY", "PETROLEUM"],
    "NIFTY IND DEFENCE": ["DEFENCE", "DEFENSE", "MILITARY", "AEROSPACE"],
    "NIFTY CAPITAL MKT": ["EXCHANGE", "BROKER", "DEPOSITORY", "STOCK"],
    "NIFTY CHEMICALS":   ["CHEMICAL", "SPECIALTY", "AGROCHEMICAL"],
    "NIFTY CEMENT":      ["CEMENT", "CONSTRUCTION", "INFRA"],
    "NIFTY INTERNET":    ["INTERNET", "DIGITAL", "FINTECH", "ECOMMERCE"],
}


def fetch_sector_strength() -> dict:
    """
    Fetch all sector indices from NSE allIndices.
    Returns dict of hot sectors (>2% gain) and cold sectors (<-1% loss).
    Also returns keyword list for boosting stocks in hot sectors.
    """
    s = nse_session()
    hot_sectors    = []
    cold_sectors   = []
    hot_keywords   = set()
    sector_scores  = {}

    try:
        r = s.get("https://www.nseindia.com/api/allIndices", timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json().get("data", [])

        for idx in data:
            name = idx.get("indexSymbol", "")
            chg  = float(idx.get("percentChange", 0))
            if name not in SECTOR_MAP:
                continue
            sector_scores[name] = chg
            if chg >= 2.0:
                hot_sectors.append({"sector": name, "chg": chg})
                for kw in SECTOR_MAP[name]:
                    hot_keywords.add(kw)
            elif chg <= -1.0:
                cold_sectors.append({"sector": name, "chg": chg})

        hot_sectors.sort(key=lambda x: -x["chg"])
        cold_sectors.sort(key=lambda x: x["chg"])

        print(f"[SRC] Sectors: {len(hot_sectors)} hot, {len(cold_sectors)} cold")
        if hot_sectors:
            print(f"[SRC] Hot: {', '.join(s['sector'] + ' ' + str(s['chg']) + '%' for s in hot_sectors[:3])}")
        if cold_sectors:
            print(f"[SRC] Cold: {', '.join(s['sector'] + ' ' + str(s['chg']) + '%' for s in cold_sectors[:3])}")

    except Exception as e:
        print(f"[SRC] Sector fetch error: {e}")

    return {
        "hot_sectors":   hot_sectors,
        "cold_sectors":  cold_sectors,
        "hot_keywords":  list(hot_keywords),
        "sector_scores": sector_scores,
    }


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
    "high_volume_breakout": (
        "( {cash} ( latest close > 20 ) "
        "and ( latest volume > 500000 ) "
        "and ( latest close > 1 day ago close * 1.03 ) )"
    ),
    "momentum": (
        "( {cash} ( latest close > 20 ) "
        "and ( latest close > 1 month ago close ) "
        "and ( latest volume > 200000 ) )"
    ),
}



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
        csrf_match = re.search(r'csrf-token"\s+content="([^"]+)"', r.text)
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



def fetch_marketaux_news(limit: int = 20) -> list:
    """
    Fetch Indian stock market news from Marketaux.
    Returns articles with pre-tagged stock symbols and sentiment scores.
    Free tier: 100 requests/day.
    """
    from kaal_config import MARKETAUX_API_KEY
    if not MARKETAUX_API_KEY:
        return []

    try:
        import requests
        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "countries":    "in",
            "language":     "en",
            "limit":        limit,
            "filter_entities": "true",
            "api_token":    MARKETAUX_API_KEY,
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            print(f"[SRC] Marketaux error: {r.status_code}")
            return []

        data = r.json()
        articles = []
        for item in data.get("data", []):
            # Extract best entity (highest match_score)
            entities = item.get("entities", [])
            tagged_symbols = [
                e["symbol"] for e in entities
                if e.get("country") == "in"
                and e.get("type") == "equity"
                and e.get("match_score", 0) > 50
            ]
            sentiment = None
            if entities:
                best = max(entities, key=lambda e: e.get("match_score", 0))
                sentiment = best.get("sentiment_score")

            articles.append({
                "title":      item.get("title", ""),
                "summary":    item.get("description", "") or item.get("snippet", ""),
                "url":        item.get("url", ""),
                "source":     "MARKETAUX",
                "published":  item.get("published_at", ""),
                "symbols":    tagged_symbols,
                "sentiment":  sentiment,
            })

        print(f"[SRC] Marketaux: {len(articles)} articles")
        return articles

    except Exception as e:
        print(f"[SRC] Marketaux error: {e}")
        return []


def fetch_marketaux_news(limit: int = 20) -> list:
    """
    Fetch Indian stock market news from Marketaux.
    Returns articles with pre-tagged stock symbols and sentiment scores.
    Free tier: 100 requests/day.
    """
    from kaal_config import MARKETAUX_API_KEY
    if not MARKETAUX_API_KEY:
        return []
    try:
        import requests
        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "countries":       "in",
            "language":        "en",
            "limit":           limit,
            "filter_entities": "true",
            "api_token":       MARKETAUX_API_KEY,
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            print(f"[SRC] Marketaux error: {r.status_code}")
            return []
        data = r.json()
        articles = []
        for item in data.get("data", []):
            entities = item.get("entities", [])
            tagged_symbols = [
                e["symbol"] for e in entities
                if e.get("country") == "in"
                and e.get("type") == "equity"
                and e.get("match_score", 0) > 50
            ]
            sentiment = None
            if entities:
                best = max(entities, key=lambda e: e.get("match_score", 0))
                sentiment = best.get("sentiment_score")
            articles.append({
                "title":     item.get("title", ""),
                "summary":   item.get("description", "") or item.get("snippet", ""),
                "url":       item.get("url", ""),
                "source":    "MARKETAUX",
                "published": item.get("published_at", ""),
                "symbols":   tagged_symbols,
                "sentiment": sentiment,
            })
        print(f"[SRC] Marketaux: {len(articles)} articles")
        return articles
    except Exception as e:
        print(f"[SRC] Marketaux error: {e}")
        return []


def fetch_news():
    """
    Fetch news from:
    1. RSS feeds (ET, Mint, MC)
    2. Tavily active search for intraday movers
    3. Serper fallback
    """
    import os
    articles = []

    # --- RSS feeds ---
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                articles.append({
                    "source":    source,
                    "title":     entry.get("title", ""),
                    "summary":   entry.get("summary", ""),
                    "published": entry.get("published", ""),
                })
        except Exception:
            pass

    # --- Tavily active search ---
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        queries = [
            "NSE BSE stocks to buy today intraday",
            "NSE stocks breakout news today",
            "India stock market movers today",
            "anti-dumping duty safeguard duty India stock today",
            "DGTR India trade protection sector company today",
            "PLI scheme approved India company today",
            "import duty India domestic manufacturer stock today",
        ]
        for query in queries:
            try:
                r = requests.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": tavily_key,
                        "query": query,
                        "max_results": 5,
                        "search_depth": "basic",
                        "topic": "news",
                        "days": 1,
                    },
                    timeout=10
                )
                if r.status_code == 200:
                    for item in r.json().get("results", []):
                        articles.append({
                            "source":    "TAVILY",
                            "title":     item.get("title", ""),
                            "summary":   item.get("content", "")[:300],
                            "published": item.get("published_date", ""),
                            "url":       item.get("url", ""),
                        })
            except Exception as e:
                print(f"[SRC] Tavily news error: {e}")

    # --- Serper fallback ---
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key and len([a for a in articles if a["source"] == "TAVILY"]) == 0:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": "NSE BSE intraday stocks news today", "num": 10},
                timeout=10
            )
            if r.status_code == 200:
                for item in r.json().get("organic", []):
                    articles.append({
                        "source":    "SERPER",
                        "title":     item.get("title", ""),
                        "summary":   item.get("snippet", ""),
                        "published": "",
                        "url":       item.get("link", ""),
                    })
        except Exception as e:
            print(f"[SRC] Serper news error: {e}")

    print(f"[SRC] News: {len(articles)} articles (RSS + Tavily + Serper)")
    return articles


# ── SEBI PIT (promoter transactions) ─────────────────────────────────────────
def fetch_sebi_pit():
    today    = datetime.now().strftime("%d-%m-%Y")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%d-%m-%Y")
    try:
        s    = nse_session()
        url  = f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={week_ago}&to_date={today}"
        r    = s.get(url, timeout=15)
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception:
        return []


# ── LIQUIDITY CHECK ───────────────────────────────────────────────────────────
def check_liquidity(symbol: str) -> dict:
    """
    Returns avg 20-day traded value in crore.
    Returns {"value_cr": float, "liquid": bool, "note": str}
    Uses NSE quote API.
    """
    try:
        s   = nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        r   = s.get(url, timeout=10)
        if r.status_code != 200:
            return {"value_cr": 0, "liquid": False, "note": "Could not fetch"}
        data      = r.json()
        trade_vol = float(data.get("priceInfo", {}).get("totalTradedVolume", 0))
        ltp       = float(data.get("priceInfo", {}).get("lastPrice", 0))
        value_cr  = round((trade_vol * ltp) / 1e7, 2)
        liquid    = value_cr >= MIN_VOLUME_CR
        note      = f"₹{value_cr}Cr traded today" if liquid else f"LOW LIQUIDITY: only ₹{value_cr}Cr"
        return {"value_cr": value_cr, "liquid": liquid, "note": note}
    except Exception:
        return {"value_cr": 0, "liquid": False, "note": "Liquidity check failed"}


# ── PDF READER ────────────────────────────────────────────────────────────────
def download_pdf_text(url: str) -> str:
    import warnings, logging
    logging.getLogger("pdfminer").setLevel(logging.CRITICAL)
    logging.getLogger("pdfplumber").setLevel(logging.CRITICAL)
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore")
    if not url:
        return ""
    try:
        s = nse_session() if "nseindia.com" in url else requests.Session()
        s.headers.update({"Referer": "https://www.nseindia.com"})
        r = s.get(url, timeout=20)
        if r.status_code != 200 or not r.content:
            return ""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "".join(p.extract_text() or "" for p in pdf.pages[:3])
            if text.strip():
                return text[:3000]
        except Exception:
            pass
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(r.content))
            return "".join(p.extract_text() or "" for p in reader.pages[:3])[:3000]
        except Exception:
            pass
    except Exception:
        pass
    return ""
