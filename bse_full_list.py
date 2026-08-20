from bse import BSE
import time, json

bse = BSE(download_folder="./")

groups = ["A", "B", "T", "TS", "M", "MT", "Z", "P", "X", "XT", "W", "IL", "S"]

all_secs = {}  # keyed by SCRIP_CD to dedupe
failed = []

for g in groups:
    ok = False
    for attempt in range(3):
        try:
            secs = bse.listSecurities(segment="Equity", status="Active", group=g)
            for s in secs:
                code = s.get("SCRIP_CD")
                if code:
                    all_secs[code] = s
            print(f"group='{g}': {len(secs)} returned, running unique total = {len(all_secs)}")
            ok = True
            break
        except Exception as e:
            print(f"group='{g}' attempt {attempt+1} failed: {e}, retrying...")
            time.sleep(3)
    if not ok:
        failed.append(g)

bse.exit()

print(f"\n=== FINAL: {len(all_secs)} unique BSE equity securities across {len(groups)-len(failed)} groups ===")
if failed:
    print(f"Groups that failed after 3 retries: {failed}")

json.dump(list(all_secs.values()), open("bse_full_list.json", "w"))
print("Saved to bse_full_list.json")
