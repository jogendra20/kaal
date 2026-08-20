import requests, time, json
from bse import BSE
from datetime import date, timedelta

symbols = [
    "533316.BO", "SAMBANDAM.NS", "BI.NS", "PANSARI.NS", "AUSTENG.NS",
    "513436.BO", "SHIPROCKET.NS", "PRABHA.NS", "MKEXIM.NS", "ORIENTHOT.NS",
    "EXCELINDUS.NS", "NILKAMAL.NS", "ZODIAC.NS", "SONAMLTD.NS", "522261.BO",
    "GFLLIMITED.NS"
]

def get_nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    })
    s.get("https://www.nseindia.com", timeout=10)
    time.sleep(1)
    return s

s = get_nse_session()
bse = BSE(download_folder="./")
today = date.today().strftime("%Y%m%d")
weekago = (date.today() - timedelta(days=7)).strftime("%Y%m%d")

bse_sample_printed = False

for sym in symbols:
    base = sym.replace(".NS", "").replace(".BO", "")
    print(f"\n--- {sym} ---")
    if sym.endswith(".NS"):
        try:
            r = s.get("https://www.nseindia.com/api/corporate-announcements",
                       params={"index": "equities", "symbol": base}, timeout=10)
            data = r.json()
            if data:
                print("Timestamp (an_dt):", data[0].get("an_dt"))
                print("Desc:", data[0].get("desc"))
            else:
                print("No announcement found")
        except Exception as e:
            print("NSE fetch failed:", e)
    else:
        try:
            ann = bse.announcements(scripcode=base, fromDate=weekago, toDate=today)
            if ann:
                if not bse_sample_printed:
                    print("RAW BSE RECORD (for field confirmation):")
                    print(json.dumps(ann[0], indent=2))
                    bse_sample_printed = True
                else:
                    print("Keys available:", list(ann[0].keys()))
            else:
                print("No announcement found")
        except Exception as e:
            print("BSE fetch failed:", e)
    time.sleep(1)

bse.exit()
