content = open('kaal_morning.py').read()

# Add import
old = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners,"
new = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners, fetch_oi_spurts,"
content = content.replace(old, new)

# Fetch OI after screeners
old = "    screeners = fetch_chartink_screeners()"
new = (
    "    screeners = fetch_chartink_screeners()\n"
    "    oi_map    = fetch_oi_spurts()"
)
content = content.replace(old, new)

# Add OI signal to each announcement
old = "        ann['in_screener']  = ann.get('symbol','') in screener_stocks"
new = (
    "        ann['in_screener']  = ann.get('symbol','') in screener_stocks\n"
    "        oi_data = oi_map.get(ann.get('symbol',''), {})\n"
    "        ann['oi_spurt']    = oi_data.get('avg_oi_pct', 0)"
)
content = content.replace(old, new)

open('kaal_morning.py', 'w').write(content)
print('Done')
