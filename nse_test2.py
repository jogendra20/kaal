import requests, time

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
})
s.get("https://www.nseindia.com", timeout=10)
time.sleep(1)

print("=== Mainboard EQUITY_L.csv ===")
r = s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=15)
print("Status:", r.status_code)
lines = r.text.splitlines()
print("Header:", lines[0])
print("Sample rows:", lines[1], "|", lines[2])
syms = [l.split(",")[0].strip() for l in lines[1:] if l.strip()]
print("Total symbols:", len(syms))

print("\n=== SME EQUITY_L.csv ===")
r2 = s.get("https://nsearchives.nseindia.com/content/equities/SME_EQUITY_L.csv", timeout=15)
print("Status:", r2.status_code)
lines2 = r2.text.splitlines()
syms2 = [l.split(",")[0].strip() for l in lines2[1:] if l.strip()]
print("Total SME symbols:", len(syms2))
