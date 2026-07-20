content = open('kaal_morning.py').read()

old_import = "fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners, fetch_oi_spurts, fetch_clean_bulk_deals,"
new_import = "fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners, fetch_oi_from_bhavcopy, fetch_clean_bulk_deals,"
assert old_import in content, "import line not found — file may have changed"
content = content.replace(old_import, new_import, 1)

old_call = "    oi_map    = fetch_oi_spurts()"
new_call = "    oi_map    = fetch_oi_from_bhavcopy()"
assert old_call in content, "oi_map call site not found — file may have changed"
content = content.replace(old_call, new_call, 1)

open('kaal_morning.py', 'w').write(content)
print('Done: kaal_morning.py now uses fetch_oi_from_bhavcopy() instead of the pre-market-dead live endpoint.')
