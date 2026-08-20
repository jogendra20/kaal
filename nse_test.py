import requests, time, json

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

print("=== Step 1: session + homepage ===")
s = get_nse_session()
print("Session cookies set:", list(s.cookies.keys())[:5], "...")

print("\n=== Step 2: fetching EQUITY_L.csv ===")
r = s.get("https://nsearchives.nseindia.com/content/equity/EQUITY_L.csv", timeout=15)
print("Status:", r.status_code)
lines = r.text.splitlines()
print("Total lines:", len(lines))
print("Header:", lines[0])
print("Sample row:", lines[1])
syms = [l.split(",")[0].strip() for l in lines[1:] if l.strip()]
print("Total symbols parsed:", len(syms))

print("\n=== Step 3: test announcement endpoint (using RELIANCE) ===")
r2 = s.get("https://www.nseindia.com/api/corporate-announcements",
            params={"index": "equities", "symbol": "RELIANCE"}, timeout=10)
print("Status:", r2.status_code)
try:
    data = r2.json()
    print("Type:", type(data))
    if isinstance(data, list) and data:
        print("Sample record:")
        print(json.dumps(data[0], indent=2))
    else:
        print("Raw response (first 500 chars):", str(data)[:500])
except Exception as e:
    print("JSON parse failed:", e)
    print("Raw text (first 500 chars):", r2.text[:500])
