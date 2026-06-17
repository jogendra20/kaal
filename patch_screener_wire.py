content = open('kaal_morning.py').read()

# Add import
old = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength,"
new = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners,"
content = content.replace(old, new)

# Add screener fetch after sector fetch
old = "    sectors  = fetch_sector_strength()"
new = (
    "    sectors   = fetch_sector_strength()\n"
    "    screeners = fetch_chartink_screeners()\n"
    "    # All screener symbols in one set\n"
    "    screener_stocks = set()\n"
    "    for name, stocks in screeners.items():\n"
    "        screener_stocks.update(stocks)\n"
    "    log(f'Screener universe: {len(screener_stocks)} unique stocks across {len(screeners)} screeners')"
)
content = content.replace(old, new)

# Add screener signal into annotation
old = "        ann['sector_hot']  = any(w in text for w in hot_kw)\n        ann['sector_cold'] = any(w in text for w in cold_kw)"
new = (
    "        ann['sector_hot']   = any(w in text for w in hot_kw)\n"
    "        ann['sector_cold']  = any(w in text for w in cold_kw)\n"
    "        ann['in_screener']  = ann.get('symbol','') in screener_stocks"
)
content = content.replace(old, new)

open('kaal_morning.py', 'w').write(content)
print('Done')
