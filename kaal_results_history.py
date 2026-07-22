"""
kaal_results_history.py
Append-only storage for the PAT/revenue YoY growth numbers score_announcement
already extracts for every results filing. One JSON file per symbol -
same pattern as kaal_momentum's bhavcopy cache, for the same reason:
each quarter's number is published once and never changes, so write once,
read many times.

This module does zero LLM work and zero scoring - it only remembers
numbers that score_announcement already computed, so results_growth_trend()
(in kaal_deterministic_scorers.py) has something to compare against.
"""
import json
import os
from datetime import datetime

STORE_DIR = os.path.join(os.path.dirname(__file__), "data", "results_history")


def _path_for(symbol: str) -> str:
    os.makedirs(STORE_DIR, exist_ok=True)
    return os.path.join(STORE_DIR, f"{symbol}.json")


def record_result(symbol: str, quarter_label: str,
                   pat_growth_pct, revenue_growth_pct) -> None:
    """
    Idempotent on quarter_label: if this quarter was already recorded
    (e.g. a corrected/revised filing re-triggers scoring), the existing
    entry is overwritten in place rather than duplicated - a duplicate
    entry would double-count that quarter in the trailing average.
    Silently no-ops if either growth number is missing (LLM didn't
    return one, or this wasn't actually a results filing) - partial,
    unverified numbers don't belong in a stored trend history.
    """
    if pat_growth_pct is None or revenue_growth_pct is None:
        return
    if not quarter_label:
        quarter_label = f"UNLABELED_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    path = _path_for(symbol)
    history = []
    if os.path.exists(path):
        try:
            history = json.load(open(path))
        except Exception:
            history = []

    history = [h for h in history if h.get("quarter") != quarter_label]
    history.append({
        "quarter": quarter_label,
        "pat_growth_pct": pat_growth_pct,
        "revenue_growth_pct": revenue_growth_pct,
        "recorded_date": datetime.now().strftime("%Y-%m-%d"),
    })
    history.sort(key=lambda h: h["recorded_date"])

    json.dump(history, open(path, "w"), indent=2)


def get_result_history(symbol: str) -> list:
    """Oldest-first list of {quarter, pat_growth_pct, revenue_growth_pct,
    recorded_date} for this symbol. Empty list if nothing recorded yet -
    which, for most symbols, will be true for a long time after this is
    first deployed. That's expected: this only accumulates going forward,
    it has no way to backfill quarters that were scored before it existed."""
    path = _path_for(symbol)
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path))
    except Exception:
        return []
