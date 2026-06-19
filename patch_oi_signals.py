content = open('kaal_morning.py').read()

old = "    # ── Proxy/indirect beneficiary signals ───────────────\n    proxy_signals = score_proxy_signals(news, nse_anns)\n    all_signals.extend(proxy_signals)"
new = (
    "    # ── Proxy/indirect beneficiary signals ───────────────\n"
    "    proxy_signals = score_proxy_signals(news, nse_anns)\n"
    "    all_signals.extend(proxy_signals)\n"
    "\n"
    "    # ── OI spurt signals (smart money positioning) ────────\n"
    "    announced_syms = {s['symbol'] for s in all_signals}\n"
    "    for symbol, oi_data in oi_map.items():\n"
    "        if symbol in announced_syms:\n"
    "            continue\n"
    "        if oi_data['avg_oi_pct'] < 15:\n"
    "            continue\n"
    "        score = 60 if oi_data['avg_oi_pct'] > 20 else 55\n"
    "        all_signals.append({\n"
    "            'symbol':         symbol,\n"
    "            'score':          score,\n"
    "            'tier':           2,\n"
    "            'skip':           False,\n"
    "            'catalyst':       'OI_SPURT',\n"
    "            'direction':      'BULLISH',\n"
    "            'key':            f'OI spurt {oi_data[\"avg_oi_pct\"]:.1f}% above avg — smart money positioning',\n"
    "            'reason':         'Unusual OI buildup detected. Confirm with price action and news catalyst before entry.',\n"
    "            'source':         'NSE_OI',\n"
    "            'signal_sources': ['NSE_OI'],\n"
    "        })"
)
content = content.replace(old, new)
open('kaal_morning.py', 'w').write(content)
print('Done')
