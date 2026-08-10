import requests

session = requests.Session()

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quote/equity/KIRLPNU/Kirloskar-Pneumatic-Company-Limited",
}

session.headers.update(headers)

# Hit homepage first to get valid cookies — direct API calls without this get blocked
session.get("https://www.nseindia.com", timeout=5)
session.get("https://www.nseindia.com/get-quote/equity/KIRLPNU/Kirloskar-Pneumatic-Company-Limited", timeout=5)

url = "https://www.nseindia.com/api/corporate-announcements"
params = {"index": "equities", "symbol": "KIRLPNU"}

resp = session.get(url, params=params, timeout=5)

if resp.status_code == 200:
    data = resp.json()
    for item in data:
        print(item.get("an_dt", ""), "-", item.get("desc", ""), "-", item.get("attchmntText", ""))
else:
    print(f"Failed: status {resp.status_code}")
    print(resp.text[:500])
