content = open('kaal_morning.py').read()

old = '''    for s in final:
        sym = s.get('symbol', '')
        price = price_map.get(sym, 0)
        prev_close = prev_close_map.get(sym, 0)'''

new = '''    for s in final:
        sym = s.get('symbol', '')
        price = price_map.get(sym, 0)
        if price <= 0:
            # price_map only covers pre-open GAP movers. Catalysts that
            # don't move price pre-market (buybacks, M&A, most Tier1
            # corporate actions) are absent from it, which was silently
            # resetting their days_since_catalyst/first_seen/hist_status
            # to "brand new" every single run regardless of how old the
            # signal actually was. Fall back to yesterday's bhavcopy close
            # so real history still gets tracked for these.
            price = bhavcopy_yday.get(sym, {}).get('close', 0)
        prev_close = prev_close_map.get(sym, 0)'''

assert old in content, "signal-history loop header not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_morning.py', 'w').write(content)
print("Done: non-gapping Tier1 catalysts (buybacks, M&A) now fall back to bhavcopy close price, so they keep real days_since_catalyst/first_seen instead of always showing FRESH.")
