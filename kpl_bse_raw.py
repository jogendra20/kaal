import requests

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}

url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
params = {
    "pageno": 1,
    "strCat": -1,
    "strPrevDate": "20250801",
    "strScrip": "505283",   # BSE scrip code for Kirloskar Pneumatic
    "strSearch": "P",
    "strToDate": "20260810",
    "strType": "C",
    "subcategory": -1,
}

resp = requests.get(url, headers=headers, params=params, timeout=10)
print(resp.status_code)
print(resp.text[:1000])
