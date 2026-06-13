content = open('kaal_sources.py').read()

new_func = '''
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

'''

old = "def fetch_preopen_gainers"
content = content.replace(old, new_func + "def fetch_preopen_gainers")
open('kaal_sources.py', 'w').write(content)
print('Done')
