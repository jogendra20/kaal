content = open('kaal_config.py').read()

proxy_map = '''
# ── PROXY/INDIRECT BENEFICIARY MAP ───────────────────────────────────────────
# When trigger keyword found in news → flag these listed stocks as Tier1
# Format: "news keyword": ["SYMBOL1", "SYMBOL2", ...]

PROXY_MAP = {
    # NSE IPO — companies selling NSE shares via OFS
    "NSE IPO": ["NIACL", "IFCI", "GICRE", "BSELTD", "MCX", "TATACONS"],
    "NSE DRHP": ["NIACL", "IFCI", "GICRE", "BSELTD", "MCX", "TATACONS"],
    "NSE LISTING": ["NIACL", "IFCI", "GICRE", "BSELTD", "MCX"],

    # Capital market theme — when NSE IPO files, these also benefit
    "NSE IPO FILING": ["CDSL", "CAMS", "KFINTECH", "BSE"],

    # Adani group — any Adani entity news benefits peers
    "ADANI ACQUISITION": ["ADANIPORTS", "ADANIENT", "ADANIGREEN", "ADANIPOWER"],
    "ADANI ORDER": ["ADANIPORTS", "ADANIENT", "ADANIGREEN"],

    # Defence sector — any large defence order benefits peers
    "DEFENCE ORDER": ["HAL", "BEL", "PARAS", "MIDHANI", "BHEL", "BEML"],
    "DEFENCE CONTRACT": ["HAL", "BEL", "PARAS", "MIDHANI", "BHEL"],
    "MILITARY ORDER": ["HAL", "BEL", "PARAS", "MTAR"],

    # PSU bank recapitalisation
    "PSU BANK RECAPITAL": ["SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK"],

    # Insurance sector — any insurance regulation benefits all
    "INSURANCE FDI": ["LICI", "GICRE", "NIACL", "STARHEALTH"],
    "INSURANCE REGULATION": ["LICI", "GICRE", "NIACL"],

    # Real estate — RERA or govt housing scheme benefits all
    "AFFORDABLE HOUSING": ["DLF", "GODREJPROP", "PRESTIGE", "OBEROIRLTY"],
    "RERA AMENDMENT": ["DLF", "GODREJPROP", "PRESTIGE"],

    # Pharma — USFDA clearance for one benefits sector
    "USFDA APPROVAL": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA"],

    # EV sector
    "EV POLICY": ["TATAMOTORS", "MAHINDRA", "OLECTRA", "TATAPOWER"],
    "EV SUBSIDY": ["TATAMOTORS", "MAHINDRA", "OLECTRA"],
}

# News keywords that trigger proxy scan
PROXY_TRIGGER_KEYWORDS = list(PROXY_MAP.keys())

'''

# Add before CLOSED_OPEN_OFFERS
old = "# Open offers with known close dates"
new = proxy_map + "# Open offers with known close dates"
content = content.replace(old, new)
open('kaal_config.py', 'w').write(content)
print('Done')
