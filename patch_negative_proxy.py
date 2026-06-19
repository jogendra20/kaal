content = open('kaal_config.py').read()

negative_proxy = '''
# ── NEGATIVE PROXY MAP ───────────────────────────────────────────────────────
# When trigger found in news → these stocks get BEARISH flag + score penalized
NEGATIVE_PROXY_MAP = {
    # Global IT bellwether misses → Indian IT falls
    "ACCENTURE MISS":       ["WIPRO", "INFY", "TCS", "HCLTECH", "TECHM", "LTIM", "MPHASIS"],
    "ACCENTURE RESULTS":    ["WIPRO", "INFY", "TCS", "HCLTECH", "TECHM"],
    "IBM MISS":             ["WIPRO", "INFY", "TCS", "HCLTECH"],
    "COGNIZANT MISS":       ["WIPRO", "INFY", "TCS", "HCLTECH", "TECHM"],
    "NASDAQ CRASH":         ["WIPRO", "INFY", "TCS", "HCLTECH", "TECHM", "LTIM"],

    # US pharma/FDA negative → Indian pharma falls
    "FDA WARNING LETTER":   ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA"],
    "FDA IMPORT ALERT":     ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA"],

    # China slowdown → metal stocks fall
    "CHINA SLOWDOWN":       ["TATASTEEL", "HINDALCO", "JSWSTEEL", "SAIL", "NALCO"],
    "CHINA DEMAND FALL":    ["TATASTEEL", "HINDALCO", "JSWSTEEL"],

    # Crude spike → aviation, paint, tyre fall
    "CRUDE SPIKE":          ["INDIGO", "SPICEJET", "ASIANPAINT", "BERGER", "MRF", "APOLLOTYRE"],
    "OIL PRICE RISE":       ["INDIGO", "SPICEJET", "ASIANPAINT", "BERGER"],

    # US recession fears → export-heavy IT/pharma fall
    "US RECESSION":         ["WIPRO", "INFY", "TCS", "SUNPHARMA", "DRREDDY"],
    "FED RATE HIKE":        ["BANKBARODA", "PNB", "SBIN", "HDFC", "ICICIBANK"],
}

'''

old = "# ── PROXY/INDIRECT BENEFICIARY MAP"
new = negative_proxy + "# ── PROXY/INDIRECT BENEFICIARY MAP"
content = content.replace(old, new)
open('kaal_config.py', 'w').write(content)
print('Done')
