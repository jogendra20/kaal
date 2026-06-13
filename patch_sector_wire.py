content = open('kaal_morning.py').read()

# Add import
old = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers,"
new = "from kaal_sources import (\n    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength,"
content = content.replace(old, new)

# Add sector fetch after preopen
old = "    preopen  = fetch_preopen_gainers()\n    # Build gap map for quick lookup\n    gap_map  = {s['symbol']: s['gap_pct'] for s in preopen if abs(s['gap_pct']) >= 2.0}"
new = (
    "    preopen  = fetch_preopen_gainers()\n"
    "    # Build gap map for quick lookup\n"
    "    gap_map  = {s['symbol']: s['gap_pct'] for s in preopen if abs(s['gap_pct']) >= 2.0}\n"
    "    sectors  = fetch_sector_strength()\n"
    "    hot_kw   = set(w.upper() for w in sectors.get('hot_keywords', []))\n"
    "    cold_kw  = set()\n"
    "    for sec in sectors.get('cold_sectors', []):\n"
    "        from kaal_sources import SECTOR_MAP\n"
    "        cold_kw.update(SECTOR_MAP.get(sec['sector'], []))\n"
    "    ann['sector_hot']  = any(w in (ann.get('subject','') + ann.get('attchmntText','')).upper() for w in hot_kw)\n"
    "    ann['sector_cold'] = any(w in (ann.get('subject','') + ann.get('attchmntText','')).upper() for w in cold_kw)"
)
content = content.replace(old, new)

open('kaal_morning.py', 'w').write(content)
print('Done')
