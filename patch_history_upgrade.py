content = open('kaal_history.py').read()

old = '''def update_signal_history(symbol: str, current_price: float, catalyst: str) -> dict:
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
    }'''

new = '''def update_signal_history(symbol: str, current_price: float, catalyst: str,
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
            return 0'''

content = content.replace(old, new)
open('kaal_history.py', 'w').write(content)
print('Done')
