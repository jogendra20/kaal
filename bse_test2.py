from bse import BSE
import inspect

bse = BSE(download_folder="./")

# 1. Check the actual method signature for hidden params (page, limit, etc.)
print("=== listSecurities signature ===")
print(inspect.signature(bse.listSecurities))

# 2. Try common BSE group codes one by one, see counts
groups_to_try = ["", "A", "B", "T", "TS", "M", "MT", "SM", "ST", "Z", "P"]
total_seen = set()
for g in groups_to_try:
    try:
        secs = bse.listSecurities(segment="Equity", status="Active", group=g)
        codes = set(s.get("SCRIP_CD") for s in secs)
        new = codes - total_seen
        total_seen |= codes
        print(f"group='{g}': {len(secs)} returned, {len(new)} new, running total unique = {len(total_seen)}")
    except Exception as e:
        print(f"group='{g}': FAILED - {e}")

bse.exit()
