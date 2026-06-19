content = open('kaal_scorer.py').read()

new_func = '''
def score_negative_proxy(news_articles: list) -> list:
    """
    Scan news for negative proxy triggers.
    When found, flag affected stocks as BEARISH with score penalty.
    """
    import os
    from datetime import datetime
    from kaal_config import NEGATIVE_PROXY_MAP

    dedup_file = os.path.join(os.path.dirname(__file__), "data", "neg_proxy_dedup.txt")
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

    for article in news_articles:
        text = (article.get("title","") + " " + article.get("summary","")).upper()
        for trigger, symbols in NEGATIVE_PROXY_MAP.items():
            if trigger in text and trigger not in found_triggers and trigger not in already_triggered:
                found_triggers.add(trigger)
                print(f"[NEG_PROXY] Trigger: {trigger}")
                for symbol in symbols:
                    results.append({
                        "symbol":         symbol,
                        "score":          20,
                        "tier":           3,
                        "skip":           True,
                        "catalyst":       "NEGATIVE_PROXY",
                        "direction":      "BEARISH",
                        "key":            f"AVOID — {trigger} = sector headwind",
                        "reason":         f"Negative proxy: {trigger} news hurts {symbol}. Avoid long positions today.",
                        "source":         "NEG_PROXY",
                        "signal_sources": ["NEG_PROXY"],
                    })

    if found_triggers:
        with open(dedup_file, "a") as f:
            for trigger in found_triggers:
                f.write(f"{today}|{trigger}\\n")
        print(f"[NEG_PROXY] {len(results)} stocks flagged BEARISH")

    return results

'''

old = "def score_proxy_signals"
content = content.replace(old, new_func + "def score_proxy_signals")
open('kaal_scorer.py', 'w').write(content)
print('Done')
