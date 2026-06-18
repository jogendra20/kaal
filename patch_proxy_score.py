content = open('kaal_scorer.py').read()

new_func = '''
def score_proxy_signals(news_articles: list, nse_announcements: list) -> list:
    """
    Scan news + announcements for proxy trigger keywords.
    When found, flag all indirect beneficiary stocks as Tier1 signals.
    """
    from kaal_config import PROXY_MAP
    results = []
    found_triggers = set()

    # Check news articles
    for article in news_articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers:
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
                        "reason":         (
                            f"Proxy play — {trigger} news benefits {symbol} indirectly. "
                            f"Check if stock already moved before entering."
                        ),
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    # Also check NSE announcements text
    for ann in nse_announcements:
        text = (ann.get("desc", "") + " " + ann.get("attchmntText", "")).upper()
        for trigger, symbols in PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers:
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
                        "reason":         (
                            f"Proxy play — {trigger} announcement benefits {symbol}. "
                            f"Fresh catalyst. Enter on pullback after confirmation."
                        ),
                        "source":         "PROXY",
                        "signal_sources": ["PROXY"],
                        "offer_price":    0,
                        "is_fresh":       True,
                    })

    if found_triggers:
        print(f"[PROXY] Total proxy signals: {len(results)} from triggers: {found_triggers}")
    return results

'''

old = "def score_news_velocity"
content = content.replace(old, new_func + "def score_news_velocity")
open('kaal_scorer.py', 'w').write(content)
print('Done')
