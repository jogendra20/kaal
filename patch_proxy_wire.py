content = open('kaal_morning.py').read()

# Add import
old = "from kaal_scorer import score_announcement, score_news_velocity"
new = "from kaal_scorer import score_announcement, score_news_velocity, score_proxy_signals"
content = content.replace(old, new)

# Add proxy scoring after news velocity
old = "    news_signals = score_news_velocity(news)\n    all_signals.extend(news_signals)"
new = (
    "    news_signals = score_news_velocity(news)\n"
    "    all_signals.extend(news_signals)\n"
    "\n"
    "    # ── Proxy/indirect beneficiary signals ───────────────\n"
    "    proxy_signals = score_proxy_signals(news, nse_anns)\n"
    "    all_signals.extend(proxy_signals)"
)
content = content.replace(old, new)
open('kaal_morning.py', 'w').write(content)
print('Done')
