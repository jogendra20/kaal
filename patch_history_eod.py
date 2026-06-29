content = open('kaal_history.py').read()

# Add update_eod_prices function
old = "def cleanup_old_history"
new = '''def update_eod_prices(eod_prices: dict):
    """
    Called from evening run — stores today's closing price
    for any symbols that fired as signals today.
    Also calculates catalyst_day_move for new signals.
    """
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    updated = 0

    for symbol, price_data in eod_prices.items():
        if symbol not in history:
            continue
        entry = history[symbol]
        # Only store catalyst_day_close if this is the catalyst day
        if entry.get("first_seen") == today and "catalyst_day_close" not in entry:
            entry["catalyst_day_close"]  = price_data["close"]
            entry["catalyst_day_move"]   = price_data["change_pct"]
            updated += 1
        # Always update latest_close for freshness tracking
        entry["latest_close"] = price_data["close"]
        entry["latest_date"]  = today

    save_history(history)
    print(f"[HIST] EOD update: {updated} catalyst-day closes stored")


def classify_opportunity(symbol: str, current_price: float) -> dict:
    """
    Classifies whether a signal still has room to move or is priced in.
    Uses catalyst_day_move + total move + prev day change.
    Returns: {label, reason}
    """
    history = load_history()
    if symbol not in history:
        return {"label": "UNKNOWN", "reason": "No history"}

    entry              = history[symbol]
    first_price        = entry.get("first_price", current_price)
    catalyst_day_move  = entry.get("catalyst_day_move", 0)
    first_seen         = entry.get("first_seen", "")

    try:
        days_old = (datetime.now() - datetime.strptime(first_seen, "%Y-%m-%d")).days
    except Exception:
        days_old = 0

    total_move = 0.0
    if first_price > 0:
        total_move = round(((current_price - first_price) / first_price) * 100, 2)

    # Classification logic
    if catalyst_day_move > 10 and days_old >= 1:
        return {
            "label":  "PRICED_IN",
            "reason": f"Big move on catalyst day (+{catalyst_day_move:.1f}%) — likely fully priced in"
        }
    if catalyst_day_move < 3 and days_old <= 2:
        return {
            "label":  "UNDERREACTED",
            "reason": f"Market barely moved on catalyst day (+{catalyst_day_move:.1f}%) — more room ahead"
        }
    if total_move > 5 and days_old >= 1 and abs(total_move - catalyst_day_move) < 2:
        return {
            "label":  "CONSOLIDATING",
            "reason": f"Moved +{total_move:.1f}% then stabilized — possible second leg on breakout"
        }
    if total_move < 2 and days_old >= 2:
        return {
            "label":  "IGNORED",
            "reason": f"Market ignoring catalyst after {days_old} days — low conviction"
        }
    return {
        "label":  "ACTIVE",
        "reason": f"Catalyst still active, +{total_move:.1f}% total move over {days_old} days"
    }


def cleanup_old_history'''
content = content.replace(old, new)
open('kaal_history.py', 'w').write(content)
print('Done')
