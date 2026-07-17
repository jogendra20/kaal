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


def update_signal_history(symbol: str, current_price: float, catalyst: str,
                           prev_close: float = 0.0, ann_dt: str = "") -> dict:
    """
    Records first price if new, calculates % change since first seen.
    Also computes days since catalyst announcement and yesterday change.
    Returns: {first_seen, first_price, days_old, pct_change, status,
              prev_day_chg, days_since_catalyst, already_moved}
    """
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")

    if symbol not in history:
        history[symbol] = {
            "first_seen":  today,
            "first_price": current_price,
            "catalyst":    catalyst,
        }
        save_history(history)
        return {
            "first_seen":          today,
            "first_price":         current_price,
            "days_old":            0,
            "pct_change":          0.0,
            "status":              "FRESH",
            "prev_day_chg":        _calc_prev_day_chg(current_price, prev_close),
            "days_since_catalyst": _calc_days_since_catalyst(ann_dt),
            "already_moved":       False,
        }

    entry = history[symbol]
    first_price = entry.get("first_price", current_price)
    first_seen  = entry.get("first_seen", today)

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

    prev_day_chg        = _calc_prev_day_chg(current_price, prev_close)
    days_since_catalyst = _calc_days_since_catalyst(ann_dt)
    already_moved       = (abs(pct_change) > 5.0 and days_old >= 1)

    return {
        "first_seen":          first_seen,
        "first_price":         first_price,
        "days_old":            days_old,
        "pct_change":          pct_change,
        "status":              status,
        "prev_day_chg":        prev_day_chg,
        "days_since_catalyst": days_since_catalyst,
        "already_moved":       already_moved,
    }


def _calc_prev_day_chg(current_price: float, prev_close: float) -> float:
    """Yesterday's price change as percentage."""
    if prev_close and prev_close > 0 and current_price > 0:
        return round(((current_price - prev_close) / prev_close) * 100, 2)
    return 0.0


def _calc_days_since_catalyst(ann_dt: str) -> int:
    """Days since the NSE announcement was filed."""
    if not ann_dt:
        return 0
    try:
        # an_dt format: "25-Jun-2026 02:41:00"
        dt = datetime.strptime(ann_dt[:11], "%d-%b-%Y")
        return (datetime.now() - dt).days
    except Exception:
        try:
            dt = datetime.strptime(ann_dt[:10], "%Y-%m-%d")
            return (datetime.now() - dt).days
        except Exception:
            return 0


def update_eod_prices(eod_prices: dict):
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
    first_seen         = entry.get("first_seen", "")

    try:
        days_old = (datetime.now() - datetime.strptime(first_seen, "%Y-%m-%d")).days
    except Exception:
        days_old = 0

    # Same-day-first-seen signals haven't had a real EOD close captured yet
    # (that only happens in tonight's evening run via update_eod_prices()) -
    # catalyst_day_move is genuinely ABSENT from the entry until then.
    # Defaulting it to 0 and classifying that as "market moved 0% today"
    # was a real bug - it can't be distinguished from a real flat day.
    if "catalyst_day_move" not in entry:
        return {
            "label":  "PENDING",
            "reason": "First seen today — catalyst-day move not available until tonight's update"
        }

    catalyst_day_move  = entry.get("catalyst_day_move", 0)

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
