from bse import BSE
import json

bse = BSE(download_folder="./")

print("=== Fetching BSE security list (Equity, Active) ===")
secs = bse.listSecurities(segment="Equity", status="Active")
print(f"Total securities returned: {len(secs)}\n")

print("=== Sample record (first one) ===")
print(json.dumps(secs[0], indent=2))

print("\n=== Sample record (5th one, for a 2nd data point) ===")
print(json.dumps(secs[4], indent=2))

bse.exit()

groups = set(s.get("GROUP") for s in secs)
print("\nDistinct GROUP values returned:", groups)
