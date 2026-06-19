content = open('kaal_scorer.py').read()

# Find and remove entire broken score_proxy_signals function
start = content.find('\ndef score_proxy_signals')
end = content.find('\ndef score_news_velocity', start)
print(f"Removing function from {start} to {end}")

new_func = '''
def score_proxy_signals(news_articles: list, nse_announcements: list) -> list:
    """
    Scan news + announcements for proxy trigger keywords.
    When found, flag all indirect beneficiary stocks as Tier1.
    Deduplicates — only triggers once per keyword per day.
    """
    import os
    from datetime import datetime
    from kaal_config import PROXY_MAP

    # Load today already-triggered proxies
    dedup_file = os.path.join(os.path.dirname(__file__), "data", "proxy_dedup.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    already_triggered = set()
    if os.path.exists(dedup_file):
        for line in open(dedup_file):
            line = line.strip()
            if "|" in line:
                date, trigger = line.split("|", 1)
                if date == today:
                    already_triggered.add(trigger)

    results = []
    found_triggers = set()

    # Check news articles
    for article in news_articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[PROXY] Trigger found: {trigger}")
                for symbol in symbols:
                    results.append({
                        "symbol":         symbol,
                        "score":          78,
                        "tier":           1,
                        "skip":           False,
                        "catalyst":       "PROXY_PLAY",
                        "direction":      "BULLISH",
                        "key":            f"Indirect beneficiary of: {trigger}",
                        "reason":         f"Proxy play — {trigger} news benefits {symbol} indirectly. Check if stock already moved before entering.",
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    # Check NSE announcements
    for ann in nse_announcements:
        text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[PROXY] Trigger in announcement: {trigger}")
                for symbol in symbols:
                    results.append({
                        "symbol":         symbol,
                        "score":          80,
                        "tier":           1,
                        "skip":           False,
                        "catalyst":       "PROXY_PLAY",
                        "direction":      "BULLISH",
                        "key":            f"NSE announcement triggers proxy: {trigger}",
                        "reason":         f"Proxy play — {trigger} announcement benefits {symbol}. Fresh catalyst. Enter on pullback after confirmation.",
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    # Save triggered proxies to dedup file
    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\\n")
        print(f"[PROXY] Total proxy signals: {len(results)} from triggers: {found_triggers}")

    return results

'''

content = content[:start] + new_func + content[end:]
open('kaal_scorer.py', 'w').write(content)
print('Done')
