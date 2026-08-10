import requests
from datetime import datetime, timedelta

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}

url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"

today = datetime.now()
from_date = (today - timedelta(days=30)).strftime("%Y%m%d")
to_date = today.strftime("%Y%m%d")

params = {
    "pageno": 1,
    "strCat": -1,
    "strPrevDate": from_date,
    "strScrip": "505283",   # Kirloskar Pneumatic BSE scrip code
    "strSearch": "P",
    "strToDate": to_date,
    "strType": "C",
    "subcategory": -1,
}

resp = requests.get(url, headers=headers, params=params, timeout=10)
resp.raise_for_status()
data = resp.json()

rows = data.get("Table", [])
print(f"Found {len(rows)} announcements (last 30 days)\n")

for item in rows:
    dt = item.get("News_submission_dt", "")
    cat = item.get("CATEGORYNAME", "")
    subcat = item.get("SUBCATNAME", "")
    headline = item.get("HEADLINE") or subcat
    print(f"{dt} | {cat} | {headline}")
