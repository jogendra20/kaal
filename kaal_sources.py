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

def fetch_bse_announcements():
    today     = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
        f"?strCat=-1&strPrevDate={yesterday}&strScrip=&strSearch=P"
        f"&strToDate={today}&strType=C&subcategory=-1"
    )
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS_BSE, timeout=8)
            if r.status_code != 200:
                print(f"[SRC] BSE HTTP {r.status_code} — skipping")
                return []
            ct = r.headers.get("Content-Type", "")
            if "json" not in ct:
                print(f"[SRC] BSE returned non-JSON ({ct[:40]}) — blocked")
                return []
            data = r.json()
            if isinstance(data, dict):
                return data.get("Table", [])
            return []
        except requests.exceptions.Timeout:
            print(f"[SRC] BSE timeout (attempt {attempt+1}/2) — skipping")
            if attempt == 0:
                time.sleep(2)
        except Exception as e:
            print(f"[SRC] BSE error: {e}")
            break
    return []


# ── BULK / BLOCK DEALS ───────────────────────────────────────────────────────
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
def _yahoo_quote(symbol: str) -> tuple:
    """Returns (price, chg_pct) using Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return 0, 0
        data  = r.json()
        result = data["chart"]["result"][0]
        meta  = result.get("meta", {})
        close = float(meta.get("regularMarketPrice") or 0)
        prev  = float(meta.get("chartPreviousClose") or 0)
        if close and prev:
            chg = round(((close - prev) / prev) * 100, 2)
            return round(close, 2), chg
    except Exception as e:
        pass
    return 0, 0


def fetch_macro():
    macro = {}

    price, chg = _yahoo_quote("%5EGSPC")
    macro["spx"] = price
    macro["spx_chg"] = chg
    print(f"[SRC] SPX: {price} ({chg:+.2f}%)")

    price, chg = _yahoo_quote("CL=F")
    macro["crude"] = price
    macro["crude_chg"] = chg
    print(f"[SRC] Crude: {price} ({chg:+.2f}%)")

    price, chg = _yahoo_quote("GC=F")
    macro["gold"] = price
    macro["gold_chg"] = chg
    print(f"[SRC] Gold: {price} ({chg:+.2f}%)")

    price, chg = _yahoo_quote("INR=X")
    macro["usdinr"] = price
    macro["usdinr_chg"] = chg
    print(f"[SRC] USD/INR: {price} ({chg:+.2f}%)")

    # India VIX
    try:
        if NSELIB_OK:
            vix_data = capital_market.india_vix_data(period="1W")
            macro["vix"] = float(vix_data.iloc[-1]["CLOSE_INDEX_VAL"])
        else:
            raise Exception("nselib not available")
    except Exception:
        try:
            s = nse_session()
            r = s.get("https://www.nseindia.com/api/allIndices", timeout=10)
            indices = r.json().get("data", [])
            for idx in indices:
                if "VIX" in idx.get("indexSymbol", "").upper():
                    macro["vix"] = float(idx.get("last", 15))
                    break
        except Exception:
            macro["vix"] = 15

    # GIFT Nifty via Yahoo — Nifty50 spot vs previous close as proxy
    try:
        nifty_price, nifty_chg = _yahoo_quote("%5ENSEI")
        if nifty_price and nifty_chg is not None:
            macro["gift_nifty_pct"]  = round(nifty_chg, 2)
            macro["gift_nifty_bias"] = "Bullish" if nifty_chg > 0.3 else ("Bearish" if nifty_chg < -0.3 else "Neutral")
        else:
            raise Exception("no nifty data")
        print(f"[SRC] GIFT Nifty proxy: {nifty_chg:+.2f}% → {macro['gift_nifty_bias']}")
    except Exception:
        spx_chg = macro.get("spx_chg", 0)
        macro["gift_nifty_bias"] = "Bullish" if spx_chg > 0.5 else ("Bearish" if spx_chg < -0.5 else "Neutral")
        macro["gift_nifty_pct"]  = round(spx_chg * 0.6, 2)

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
def fetch_news():
    articles = []
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
        except Exception: pass
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
