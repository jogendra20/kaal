content = open('kaal_sources.py').read()

old = '''    s = nse_session()
    prices = {}
    consecutive_failures = 0
    for symbol in symbols:'''

new = '''    global _nse_session
    s = nse_session()
    prices = {}
    consecutive_failures = 0
    for symbol in symbols:'''

assert old in content, "fetch_eod_prices header not found — file may have changed"
content = content.replace(old, new, 1)

old2 = '''            if consecutive_failures >= 3:
                print(f"[SRC] {consecutive_failures} consecutive failures - recreating session")
                s = nse_session()
                consecutive_failures = 0'''

new2 = '''            if consecutive_failures >= 3:
                print(f"[SRC] {consecutive_failures} consecutive failures - recreating session")
                _nse_session = None   # force a real rebuild, not the cached singleton
                s = nse_session()
                consecutive_failures = 0'''

assert old2 in content, "recreate-session block not found — file may have changed"
content = content.replace(old2, new2, 1)

open('kaal_sources.py', 'w').write(content)
print('Done: fetch_eod_prices now actually rebuilds the NSE session on repeated failure.')
