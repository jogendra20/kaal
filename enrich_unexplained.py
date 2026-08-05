import json, time
from datetime import datetime, timedelta
import requests

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

INPUT_FILE = "movers_pattern_scan.json"
OUTPUT_FILE = "movers_pattern_scan_enriched.json"

SECTOR_MAP = {
    "MRPL": "OIL_GAS", "CHENNPETRO": "OIL_GAS", "BPCL": "OIL_GAS", "HFCL": "TELECOM",
    "KPITTECH": "IT_SERVICES", "PERSISTENT": "IT_SERVICES", "COFORGE": "IT_SERVICES",
    "REDINGTON": "IT_SERVICES", "ZENSARTECH": "IT_SERVICES",
    "SUZLON": "RENEWABLE", "WAAREEENER": "RENEWABLE", "POWERINDIA": "RENEWABLE",
    "LAURUSLABS": "PHARMA", "EXIDEIND": "AUTO_ANCILLARY", "BALKRISIND": "AUTO_ANCILLARY",
    "SONACOMS": "AUTO_ANCILLARY", "KFINTECH": "FINANCIAL_SERVICES", "ANGELONE": "FINANCIAL_SERVICES",
    "PCBL": "CHEMICALS", "DEEPAKFERT": "CHEMICALS", "PPLPHARMA": "PHARMA", "SYNGENE": "PHARMA",
    "GODFRYPHLP": "FMCG", "RADICO": "FMCG", "PATANJALI": "FMCG",
    "SWIGGY": "CONSUMER_INTERNET", "MEESHO": "CONSUMER_INTERNET", "PAYTM": "CONSUMER_INTERNET",
    "GROWW": "FINANCIAL_SERVICES", "BSE": "FINANCIAL_SERVICES",
    "KALYANKJIL": "JEWELLERY", "KAYNES": "ELECTRONICS_MFG", "DATAPATTNS": "ELECTRONICS_MFG",
    "PINELABS": "FINTECH", "NETWEB": "IT_HARDWARE", "NEWGEN": "IT_SERVICES",
}


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


def fetch_bulk_block_deals(session, symbol, date):
    from_date = date - timedelta(days=2)
    to_date = date
    results = {"bulk": [], "block": []}
    for deal_type, url_path in (("bulk", "bulk-deals"), ("block", "block-deals")):
        url = (f"https://www.nseindia.com/api/historical/{url_path}"
               f"?symbol={symbol}&from={from_date.strftime('%d-%m-%Y')}"
               f"&to={to_date.strftime('%d-%m-%Y')}")
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(rows, list):
                    results[deal_type] = rows
            else:
                results[deal_type] = {"_error_status": r.status_code}
        except Exception as e:
            results[deal_type] = {"_error_exception": str(e)}
    return results


def diagnose_bulk_block_endpoint(session):
    print("Checking bulk/block-deals endpoint before running the full patch...")
    test = fetch_bulk_block_deals(session, "RELIANCE", datetime.now() - timedelta(days=3))
    bulk_ok = isinstance(test["bulk"], list)
    block_ok = isinstance(test["block"], list)
    print(f"  bulk-deals endpoint: {'OK (list returned)' if bulk_ok else test['bulk']}")
    print(f"  block-deals endpoint: {'OK (list returned)' if block_ok else test['block']}")
    if not bulk_ok or not block_ok:
        print("  [WARN] endpoint did not return a usable list -- bulk/block deal")
        print("  enrichment below will likely be empty for everything, not because")
        print("  no deals happened, but because the URL/params are probably wrong.")
        print("  Worth checking NSE's site directly for the current endpoint before trusting results.\n")
    else:
        print("  Endpoint looks usable.\n")
    return bulk_ok and block_ok


def main():
    with open(INPUT_FILE) as f:
        events = json.load(f)

    session = nse_session()
    diagnose_bulk_block_endpoint(session)

    unexplained = [e for e in events if e["category"] == "UNEXPLAINED"]
    print(f"Re-checking {len(unexplained)} UNEXPLAINED events for bulk/block deals + sector correlation...\n")

    for e in unexplained:
        d = datetime.strptime(e["date"], "%Y-%m-%d")
        deals = fetch_bulk_block_deals(session, e["symbol"], d)
        time.sleep(0.5)
        has_bulk = isinstance(deals["bulk"], list) and len(deals["bulk"]) > 0
        has_block = isinstance(deals["block"], list) and len(deals["block"]) > 0
        if has_bulk or has_block:
            e["category"] = "INSTITUTIONAL_DEAL"
            e["deal_evidence"] = {"bulk": deals["bulk"][:3], "block": deals["block"][:3]}
            print(f"  ! {e['symbol']:12s} {e['date']} -> reclassified INSTITUTIONAL_DEAL "
                  f"({'bulk' if has_bulk else ''}{'+block' if has_block else ''})")
        else:
            e["deal_evidence"] = None

    by_date = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e)

    for e in unexplained:
        if e["category"] != "UNEXPLAINED":
            continue
        sector = SECTOR_MAP.get(e["symbol"])
        if not sector:
            e["sector"] = None
            continue
        e["sector"] = sector
        same_day = by_date.get(e["date"], [])
        same_sector_same_day = [
            o for o in same_day
            if o["symbol"] != e["symbol"] and SECTOR_MAP.get(o["symbol"]) == sector
        ]
        if same_sector_same_day:
            e["category"] = "SECTOR_CORRELATED"
            e["sector_peers_same_day"] = [o["symbol"] for o in same_sector_same_day]
            print(f"  ~ {e['symbol']:12s} {e['date']} -> reclassified SECTOR_CORRELATED "
                  f"(with {[o['symbol'] for o in same_sector_same_day]}, sector={sector})")

    remaining_unexplained = [e for e in events if e["category"] == "UNEXPLAINED"]
    symbol_counts = {}
    for e in remaining_unexplained:
        symbol_counts[e["symbol"]] = symbol_counts.get(e["symbol"], 0) + 1
    concentrated = {s: c for s, c in symbol_counts.items() if c >= 2}

    with open(OUTPUT_FILE, "w") as f:
        json.dump(events, f, indent=2)

    print(f"\n{'='*70}")
    print("REVISED SUMMARY after patching all three blind spots")
    print(f"{'='*70}\n")

    total = len(events)
    by_cat = {}
    for e in events:
        by_cat.setdefault(e["category"], []).append(e)
    for cat in ("CATALYST", "PROMOTER", "INSTITUTIONAL_DEAL", "SECTOR_CORRELATED", "UNEXPLAINED"):
        subset = by_cat.get(cat, [])
        pct = len(subset) / total * 100 if total else 0
        print(f"  {cat:20s}: {len(subset)} events ({pct:.1f}%)")

    print(f"\n{'-'*70}")
    if concentrated:
        print("Symbols appearing 2+ times in the remaining UNEXPLAINED bucket")
        print("(these skew the sample -- treat them as one repeated stock's")
        print("behavior, not evidence of a broad pattern, until checked individually):\n")
        for s, c in sorted(concentrated.items(), key=lambda x: -x[1]):
            print(f"  {s}: {c} occurrences")
    else:
        print("No symbol appears more than once in the remaining UNEXPLAINED bucket.")

    print(f"\n{'-'*70}")
    print("Final TRULY UNEXPLAINED list (no catalyst, no promoter filing, no")
    print("bulk/block deal, no same-sector same-day peer):\n")
    for e in by_cat.get("UNEXPLAINED", []):
        print(f"{e['date']} {e['symbol']:12s} {e['pct_move']:+.2f}%  sector={e.get('sector', 'unmapped')}")


if __name__ == "__main__":
    main()
