"""
kaal_market_data.py
Market-technical data: bhavcopy, OI, sector strength, chartink screeners,
preopen gainers, EOD prices, bulk deals, option chain / PCR.
Shares the NSE session from kaal_http.py rather than keeping its own.
"""
import requests, time, io

from datetime import datetime, timedelta
from kaal_config import MIN_VOLUME_CR
from kaal_http import nse_session, reset_session, HEADERS_NSE, HEADERS_BSE

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
        # Use last TRADING day by default (today's file not published till
        # 7PM, and simple "yesterday" breaks on Mon/holidays - e.g. on a
        # Monday, calendar-yesterday is Sunday, a non-trading day with no
        # real bhavcopy). Walk back skipping Sat/Sun.
        d = datetime.now() - timedelta(days=1)
        while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            d -= timedelta(days=1)
        date_str = d.strftime("%d%m%Y")

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
                turnover_lacs = float(row.get("TURNOVER_LACS", 0) or 0)
                # VWAP proxy: prior day's actual volume-weighted average price,
                # computed from real traded value/quantity - not a live intraday
                # VWAP (KAAL has no tick feed for that), but a genuine reference
                # point for "already extended vs where most volume actually
                # traded", which is more robust than a single close/prev_close print.
                vwap = round((turnover_lacs * 100000) / volume, 2) if volume else close
                # Real traded value in crore for the day - crude but genuine
                # liquidity proxy (a full 15-day rolling average would need
                # 15x the API calls; this is the "cheap version" using data
                # already being fetched for VWAP).
                liquidity_cr = round(turnover_lacs / 100, 2)
                result[symbol] = {
                    "close":      close,
                    "prev_close": prev_close,
                    "chg_pct":    chg_pct,
                    "deliv_qty":  deliv_qty,
                    "deliv_per":  deliv_per,
                    "volume":     volume,
                    "vwap":       vwap,
                    "liquidity_cr": liquidity_cr,
                }
            except Exception:
                continue

        print(f"[SRC] Bhavcopy {date_str}: {len(result)} EQ stocks loaded")
        return result

    except Exception as e:
        print(f"[SRC] Bhavcopy error: {e}")
        return {}

def fetch_oi_from_bhavcopy(date_str: str = None) -> dict:
    """
    Replaces fetch_oi_spurts() for the PRE-MARKET morning run.
    fetch_oi_spurts() hits NSE's "live-analysis-oi-spurts-underlyings"
    endpoint, which only has data once today's derivatives session is
    live (from market open) - called at ~8:58 AM (before 9:15 open) it
    has nothing to serve and 404s every time, making the OI signal
    silently dead weight in the morning brief.

    This pulls yesterday's F&O bhavcopy instead (published ~7PM, so it's
    always ready well before the next morning's run).

    NOTE: NSE discontinued the old "fo_bhavdata_full_DDMMYYYY.csv" report
    on July 8, 2024 (NSE Circular 62424, June 12 2024) in favour of the
    new UDiFF ("Unified Distilled File Format") zip. This function targets
    that current format: a zipped CSV at a YYYYMMDD-dated URL, with
    columns FinInstrmTp/TckrSymb/OptnTp/OpnIntrst/ChngInOpnIntrst/
    TtlTradgVol rather than the old INSTRUMENT/SYMBOL/OPEN_INT/CHG_IN_OI/
    CONTRACTS names. Futures rows have a blank OptnTp (vs CE/PE for
    options), which is used to isolate futures without relying on the
    exact FinInstrmTp code NSE uses for stock futures.
    """
    import csv
    import io
    import zipfile
    from datetime import datetime, timedelta
    import requests as req

    if not date_str:
        # Same last-trading-day walk-back as fetch_bhavcopy(), so this is
        # always looking at the most recent published session.
        d = datetime.now() - timedelta(days=1)
        while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            d -= timedelta(days=1)
        date_str = d.strftime("%Y%m%d")  # UDiFF uses YYYYMMDD, not DDMMYYYY

    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # NSE indices that trade futures - excluded since we only want stock OI
    INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}

    try:
        r = req.get(url, headers=headers, timeout=(5, 15))
        if r.status_code != 200:
            print(f"[SRC] FO UDiFF Bhavcopy {date_str}: HTTP {r.status_code}")
            return {}

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                text = f.read().decode("utf-8", errors="ignore")

        reader = csv.DictReader(text.splitlines())
        agg = {}  # symbol -> {open_int_total, chg_oi_total, volume_total}
        seen_types = set()
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            seen_types.add(row.get("FinInstrmTp", ""))
            if row.get("OptnTp", "").strip():
                continue  # options carry CE/PE here; futures leave it blank
            symbol = row.get("TckrSymb", "")
            if not symbol or symbol in INDEX_SYMBOLS:
                continue
            try:
                open_int = float(row.get("OpnIntrst", 0) or 0)
                chg_oi   = float(row.get("ChngInOpnIntrst", 0) or 0)
                vol      = int(float(row.get("TtlTradgVol", 0) or 0))
            except Exception:
                continue
            a = agg.setdefault(symbol, {"open_int": 0.0, "chg_oi": 0.0, "vol": 0})
            a["open_int"] += open_int
            a["chg_oi"]   += chg_oi
            a["vol"]      += vol

        oi_map = {}
        for symbol, a in agg.items():
            prev_oi = a["open_int"] - a["chg_oi"]  # OpnIntrst is post-change; back out prior day's OI
            avg_oi_pct = round((a["chg_oi"] / prev_oi) * 100, 2) if prev_oi else 0
            oi_map[symbol] = {
                "oi_change":  int(a["chg_oi"]),
                "avg_oi_pct": avg_oi_pct,
                "volume":     a["vol"],
            }

        high_oi = {s: v for s, v in oi_map.items() if v["avg_oi_pct"] > 10}
        print(f"[SRC] FO UDiFF Bhavcopy OI: {len(oi_map)} stock-future symbols | {len(high_oi)} high conviction (>10%) | types seen: {seen_types}")
        if high_oi:
            top = sorted(high_oi.items(), key=lambda x: -x[1]["avg_oi_pct"])[:5]
            print(f"[SRC] Top OI: {[(s, round(v['avg_oi_pct'],1)) for s,v in top]}")
        return oi_map

    except Exception as e:
        print(f"[SRC] FO UDiFF Bhavcopy error: {e}")
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

def fetch_eod_prices(symbols: list) -> dict:
    """
    Fetch today's closing prices for a list of symbols using NSE quote API.
    Called from evening run to store catalyst-day close in signal_history.
    Returns: {symbol: {"close": float, "prev_close": float, "change_pct": float}}
    """
    s = nse_session()
    prices = {}
    consecutive_failures = 0
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
                consecutive_failures = 0
            else:
                consecutive_failures += 1
        except Exception as e:
            print(f"[SRC] EOD price error {symbol}: {e}")
            consecutive_failures += 1
            # A bad/invalid symbol (or NSE's WAF flagging the session) can
            # poison the shared session for every subsequent request in this
            # loop - recreate it after repeated failures so one bad symbol
            # doesn't take down the whole batch silently.
            if consecutive_failures >= 3:
                print(f"[SRC] {consecutive_failures} consecutive failures - recreating session")
                _nse_session = None   # force a real rebuild, not the cached singleton
                s = nse_session()
                consecutive_failures = 0
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

def fetch_option_chain(symbol: str, is_index: bool = False) -> dict:
    """
    Fetch raw NSE option-chain JSON for an index (NIFTY/BANKNIFTY) or an
    F&O-eligible stock. Returns {} on any failure.
    """
    s = nse_session()
    endpoint = "option-chain-indices" if is_index else "option-chain-equities"
    try:
        r = s.get(
            f"https://www.nseindia.com/api/{endpoint}?symbol={symbol}",
            timeout=12
        )
        if r.status_code != 200:
            print(f"[SRC] Option chain {symbol}: HTTP {r.status_code}")
            return {}
        return r.json()
    except Exception as e:
        print(f"[SRC] Option chain {symbol} error: {e}")
        return {}

def compute_pcr_max_pain(chain_data: dict) -> dict:
    """
    Parses raw NSE option-chain JSON (nearest expiry only) into PCR
    (put/call OI ratio) and Max Pain strike (the strike that minimizes
    total payout to option buyers -- price tends to gravitate here close
    to expiry). Returns {} on any parsing failure or empty chain.
    """
    try:
        records = chain_data.get("records", {})
        expiry_dates = records.get("expiryDates", [])
        if not expiry_dates:
            return {}
        nearest_expiry = expiry_dates[0]
        underlying     = float(records.get("underlyingValue", 0))

        rows = [r for r in records.get("data", []) if r.get("expiryDate") == nearest_expiry]
        if not rows:
            return {}

        strikes = []
        total_call_oi = 0
        total_put_oi  = 0
        for r in rows:
            strike = r.get("strikePrice")
            ce_oi  = int((r.get("CE") or {}).get("openInterest", 0))
            pe_oi  = int((r.get("PE") or {}).get("openInterest", 0))
            strikes.append({"strike": strike, "ce_oi": ce_oi, "pe_oi": pe_oi})
            total_call_oi += ce_oi
            total_put_oi  += pe_oi

        if total_call_oi == 0:
            return {}

        pcr = round(total_put_oi / total_call_oi, 2)

        best_strike = None
        min_pain    = None
        for candidate in strikes:
            k = candidate["strike"]
            pain = 0
            for st in strikes:
                if st["strike"] <= k:
                    pain += st["ce_oi"] * (k - st["strike"])
                if st["strike"] >= k:
                    pain += st["pe_oi"] * (st["strike"] - k)
            if min_pain is None or pain < min_pain:
                min_pain    = pain
                best_strike = k

        from datetime import datetime as _dt
        exp_dt      = _dt.strptime(nearest_expiry, "%d-%b-%Y")
        days_to_exp = (exp_dt - _dt.now()).days

        return {
            "pcr":              pcr,
            "max_pain_strike":  best_strike,
            "underlying":       underlying,
            "distance_to_pain": round(((underlying - best_strike) / best_strike) * 100, 2) if best_strike else 0,
            "nearest_expiry":   nearest_expiry,
            "days_to_expiry":   days_to_exp,
        }
    except Exception as e:
        print(f"[SRC] PCR/Max Pain parse error: {e}")
        return {}

def fetch_pcr_map(symbols: list) -> dict:
    """
    Fetches PCR/Max Pain for a specific list of F&O-eligible symbols only
    (not the whole ~180-stock F&O universe) -- keeps this to a handful of
    calls per run, scoped to stocks that already have another reason to
    be considered today (announcement, screener, etc).
    Returns {symbol: {pcr, max_pain_strike, distance_to_pain, days_to_expiry}}.
    """
    result = {}
    for sym in symbols:
        chain = fetch_option_chain(sym, is_index=False)
        if not chain:
            continue
        parsed = compute_pcr_max_pain(chain)
        if parsed:
            result[sym] = parsed
    if result:
        print(f"[SRC] PCR/Max Pain: {len(result)}/{len(symbols)} symbols resolved")
    return result
