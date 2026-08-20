#!/usr/bin/env python3
"""
Tier 1/2 Delivery % + RVOL Checker
Angel SmartAPI -> RVOL (today vol vs 20D avg)
NSE quote-equity -> today's delivery %
Reads credentials from .env
"""

import os, re, time
import requests, pyotp, pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from SmartApi import SmartConnect

# ---------------- CONFIG ----------------
load_dotenv()

def clean_totp_secret(raw: str) -> str:
    if not raw:
        raise ValueError("ANGEL_TOTP_SECRET not found in .env")
    cleaned = re.sub(r'[^A-Za-z2-7]', '', raw).upper()
    if not cleaned:
        raise ValueError("TOTP secret empty after cleaning — check .env value isn't the QR URL or a placeholder.")
    return cleaned

API_KEY     = os.getenv("ANGEL_API_KEY")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE")
PASSWORD    = os.getenv("ANGEL_PIN")
TOTP_SECRET = clean_totp_secret(os.getenv("ANGEL_TOTP_SECRET"))

assert API_KEY, "ANGEL_API_KEY missing from .env"
assert CLIENT_CODE, "ANGEL_CLIENT_CODE missing from .env"
assert PASSWORD, "ANGEL_PIN missing from .env"

TIER_STOCKS = {
    "MANAPPURAM": "Manappuram Finance",
    "TDPOWERSYS": "TD Power Systems",
    "MANINDS":    "Man Industries",
    "JNKINDIA":   "JNK India",
    "ASHOKA":     "Ashoka Buildcon",
    "PIIND":      "PI Industries",
}

NSE_TIMEOUT = 30
NSE_RETRIES = 3

# ---------------- ANGEL LOGIN ----------------
def angel_login():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    data = obj.generateSession(CLIENT_CODE, PASSWORD, totp)
    assert data.get('status'), f"Angel login failed: {data}"
    return obj

# ---------------- INSTRUMENT MASTER ----------------
def load_instrument_master():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def get_token(instruments, symbol):
    for inst in instruments:
        if inst.get("exch_seg") == "NSE" and inst.get("symbol") == f"{symbol}-EQ":
            return inst["token"]
    return None

# ---------------- RVOL VIA ANGEL CANDLE DATA ----------------
def get_rvol(obj, token, lookback_days=20):
    to_date = datetime.now()
    from_date = to_date - timedelta(days=lookback_days + 15)

    params = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": "ONE_DAY",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }
    candles = obj.getCandleData(params)
    assert candles.get('status'), f"Candle fetch failed: {candles}"

    data = candles['data']
    if len(data) < lookback_days + 1:
        return None, None, None

    df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume"])
    today_vol = df.iloc[-1]["volume"]
    avg_vol = df.iloc[-(lookback_days+1):-1]["volume"].mean()
    rvol = today_vol / avg_vol if avg_vol else None
    return today_vol, avg_vol, rvol

# ---------------- DELIVERY % VIA NSE (with retries + longer timeout) ----------------
def get_nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
        "X-Requested-With": "XMLHttpRequest",
    })
    for attempt in range(NSE_RETRIES):
        try:
            s.get("https://www.nseindia.com", timeout=NSE_TIMEOUT)
            time.sleep(1.5)
            s.get("https://www.nseindia.com/get-quotes/equity", timeout=NSE_TIMEOUT)
            time.sleep(1.5)
            return s
        except requests.exceptions.RequestException as e:
            print(f"NSE session handshake attempt {attempt+1} failed: {e}")
            time.sleep(3)
    raise RuntimeError("Could not establish NSE session after retries")

def get_delivery_pct(session, symbol):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=trade_info"
    for attempt in range(NSE_RETRIES):
        try:
            r = session.get(url, timeout=NSE_TIMEOUT)
            if r.status_code == 200:
                try:
                    return float(r.json()["securityWiseDP"]["deliveryToTradedQuantity"])
                except (KeyError, TypeError, ValueError):
                    return None
            else:
                print(f"{symbol}: NSE returned status {r.status_code}, retrying...")
        except requests.exceptions.RequestException as e:
            print(f"{symbol}: NSE request attempt {attempt+1} failed: {e}")
        time.sleep(3)
    return None

# ---------------- MAIN ----------------
def main():
    print(f"{'Symbol':<14}{'Delivery %':<12}{'Today Vol':<14}{'20D Avg':<14}{'RVOL':<8}")
    print("-" * 62)

    obj = angel_login()
    instruments = load_instrument_master()
    nse_session = get_nse_session()

    for symbol, name in TIER_STOCKS.items():
        token = get_token(instruments, symbol)
        if not token:
            print(f"{symbol:<14}token not found")
            continue

        try:
            today_vol, avg_vol, rvol = get_rvol(obj, token)
        except Exception as e:
            print(f"{symbol:<14}RVOL error: {e}")
            today_vol = avg_vol = rvol = None

        dp = get_delivery_pct(nse_session, symbol)

        dv = f"{dp:.2f}%" if dp is not None else "N/A"
        tv = f"{today_vol:,.0f}" if today_vol else "N/A"
        av = f"{avg_vol:,.0f}" if avg_vol else "N/A"
        rv = f"{rvol:.2f}x" if rvol else "N/A"
        print(f"{symbol:<14}{dv:<12}{tv:<14}{av:<14}{rv:<8}")

        time.sleep(1)  # be polite to NSE between symbols

if __name__ == "__main__":
    main()
