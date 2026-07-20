content = open('kaal_evening.py').read()

old = '''    # Fetch bhavcopy and store delivery % for watchlist stocks
    today_str = datetime.now().strftime('%d%m%Y')
    bhavcopy = fetch_bhavcopy(today_str)
    if bhavcopy:'''

new = '''    # Fetch bhavcopy and store delivery % for watchlist stocks
    today_str = datetime.now().strftime('%d%m%Y')
    bhavcopy = fetch_bhavcopy(today_str)
    if not bhavcopy:
        # NSE publishes bhavcopy ~7PM; this run happens earlier, so today's
        # file often isn't live yet. Fall back to the last published
        # trading day (fetch_bhavcopy()'s own weekend-skip default) rather
        # than silently skipping delivery data for the whole brief.
        print(f"[SRC] Today's bhavcopy ({today_str}) not live yet — falling back to last published day")
        bhavcopy = fetch_bhavcopy()
    if bhavcopy:'''

assert old in content, "bhavcopy call site not found in kaal_evening.py — file may have changed"
content = content.replace(old, new, 1)

open('kaal_evening.py', 'w').write(content)
print("Done: evening scan now falls back to the last published bhavcopy if today's 404s.")
