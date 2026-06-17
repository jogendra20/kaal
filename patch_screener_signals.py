content = open('kaal_morning.py').read()

old = "    # ── Score news velocity (attention flags only) ────────\n    news_signals = score_news_velocity(news)\n    all_signals.extend(news_signals)"
new = (
    "    # ── Score news velocity (attention flags only) ────────\n"
    "    news_signals = score_news_velocity(news)\n"
    "    all_signals.extend(news_signals)\n"
    "\n"
    "    # ── Screener-only signals (technical breakout, no announcement) ───\n"
    "    announced_symbols = {s['symbol'] for s in all_signals}\n"
    "    for name, stocks in screeners.items():\n"
    "        for symbol in stocks[:20]:\n"
    "            if symbol in announced_symbols:\n"
    "                continue  # already covered by announcement\n"
    "            score = 58 if name == 'gap_up' else 55\n"
    "            all_signals.append({\n"
    "                'symbol':         symbol,\n"
    "                'score':          score,\n"
    "                'tier':           2,\n"
    "                'skip':           False,\n"
    "                'catalyst':       f'SCREENER_{name.upper()}',\n"
    "                'direction':      'BULLISH',\n"
    "                'key':            f'Chartink {name.replace(\"_\",\" \").title()} — technical signal only',\n"
    "                'reason':         f'Stock in {name} screener. Confirm with price action and volume before entry.',\n"
    "                'source':         'CHARTINK',\n"
    "                'signal_sources': ['CHARTINK'],\n"
    "            })"
)
content = content.replace(old, new)
open('kaal_morning.py', 'w').write(content)
print('Done')
