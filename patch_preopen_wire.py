content = open('kaal_morning.py').read()

# Add import
old = "from kaal_sources import (\n    fetch_nse_announcements,"
new = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers,"
content = content.replace(old, new)

# Add pre-open fetch after news fetch
old = "    news     = fetch_news()"
new = (
    "    news     = fetch_news()\n"
    "    preopen  = fetch_preopen_gainers()\n"
    "    # Build gap map for quick lookup\n"
    "    gap_map  = {s['symbol']: s['gap_pct'] for s in preopen if abs(s['gap_pct']) >= 2.0}"
)
content = content.replace(old, new)

# Add pre-open confirmation to scoring — boost score if announcement stock also gapping up
old = "    for ann in nse_anns:"
new = (
    "    for ann in nse_anns:\n"
    "        # Pre-open gap boost\n"
    "        sym = ann.get('symbol', '')\n"
    "        ann['preopen_gap'] = gap_map.get(sym, 0.0)"
)
content = content.replace(old, new)

open('kaal_morning.py', 'w').write(content)
print('Done')
