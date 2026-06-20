"""
kaal_history.py
Tracks first-seen price for each signal to calculate % move since trigger.
"""
import os, json
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "data", "signal_history.json")


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history: dict):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def update_signal_history(symbol: str, current_price: float, catalyst: str) -> dict:
    """
    Records first price if new, otherwise calculates % change since first seen.
    Returns: {first_seen, first_price, days_old, pct_change, status}
    """
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")

    if symbol not in history:
        history[symbol] = {
            "first_seen": today,
            "first_price": current_price,
            "catalyst": catalyst,
        }
        save_history(history)
        return {
            "first_seen": today,
            "first_price": current_price,
            "days_old": 0,
            "pct_change": 0.0,
            "status": "FRESH",
        }

    entry = history[symbol]
    first_price = entry.get("first_price", current_price)
    first_seen = entry.get("first_seen", today)

    try:
        days_old = (datetime.now() - datetime.strptime(first_seen, "%Y-%m-%d")).days
    except Exception:
        days_old = 0

    pct_change = 0.0
    if first_price and first_price > 0:
        pct_change = round(((current_price - first_price) / first_price) * 100, 2)

    if days_old == 0:
        status = "FRESH"
    elif days_old <= 5:
        status = "AGING"
    else:
        status = "STALE"

    return {
        "first_seen":  first_seen,
        "first_price": first_price,
        "days_old":    days_old,
        "pct_change":  pct_change,
        "status":      status,
    }


def cleanup_old_history(max_days: int = 30):
    """Remove entries older than max_days to keep file small."""
    history = load_history()
    today = datetime.now()
    cleaned = {}
    for symbol, entry in history.items():
        try:
            first_seen = datetime.strptime(entry.get("first_seen", ""), "%Y-%m-%d")
            if (today - first_seen).days <= max_days:
                cleaned[symbol] = entry
        except Exception:
            pass
    save_history(cleaned)
