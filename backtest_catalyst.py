"""
backtest_catalyst.py
Replays historical NSE corporate announcements through the SAME
deterministic classifier the live scanner uses on every announcement
before it ever reaches the LLM (kaal_event_classifier.classify_announcement).
Each announcement gets tagged Tier1/Tier2/skip exactly as it would live,
then this checks what the stock actually did the next trading day.

No LLM calls. This is deliberate: the deterministic tier assignment is
the foundation the LLM score sits on top of. If tier alone carries no
signal, the LLM layer on top is refining noise, and that's worth knowing
before trusting - or improving - anything upstream of it (FY27 scoring,
momentum/regime filters, etc).

Methodology mirrors backtest_momentum.py for comparability: next trading
day open->close only, alpha = pick return minus Nifty return same day.

CAVEAT - read before trusting the output: NSE's public
corporate-announcements endpoint is built to serve the website's "last
few days" view, not a historical archive. It may silently return empty
for from_date/to_date ranges more than a few days back. This script
reports days_with_data vs days_empty explicitly and warns loudly if
most days come back empty, rather than quietly showing a small sample
as if it were a full 60-day backtest. If that warning fires, the honest
next step is finding an actual historical announcements archive, not
trusting these numbers.
"""
import time
from datetime import datetime, timedelta

from kaal_http import nse_session
from kaal_event_classifier import classify_announcement
from kaal_momentum.providers import NSEBhavcopyProvider

INDEX_SYMBOL = "NIFTY 50"
LOOKBACK_DAYS = 60  # matches momentum engine's backtest window


def _trading_days_back(from_date: datetime, n: int) -> list:
    out = []
    d = from_date
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    out.reverse()
    return out


def fetch_announcements_for_date(day: datetime) -> list:
    """One day's NSE corporate announcements. Empty list on holiday/no-data/error."""
    date_str = day.strftime("%d-%m-%Y")
    try:
        s = nse_session()
        url = (f"https://www.nseindia.com/api/corporate-announcements"
               f"?index=equities&from_date={date_str}&to_date={date_str}")
        r = s.get(url, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [WARN] fetch failed for {date_str}: {e}")
        return []


def _next_trading_bar(provider, symbol: str, after_date: datetime):
    bars = provider.get_daily_bars(symbol, 10, as_of_date=after_date + timedelta(days=10))
    for b in bars:
        if b["date"] > after_date.strftime("%Y-%m-%d"):
            return b
    return None


def _next_trading_index_bar(provider, index_symbol: str, after_date: datetime):
    bars = provider.get_index_bars(index_symbol, 10, as_of_date=after_date + timedelta(days=10))
    for b in bars:
        if b["date"] > after_date.strftime("%Y-%m-%d"):
            return b
    return None


def run_backtest():
    provider = NSEBhavcopyProvider()
    latest_usable = datetime.now() - timedelta(days=3)
    test_dates = _trading_days_back(latest_usable, LOOKBACK_DAYS)

    picks = []
    days_with_data = 0
    days_empty = 0

    for i, d in enumerate(test_dates, 1):
        print(f"[{i}/{len(test_dates)}] {d.strftime('%Y-%m-%d')}...", flush=True)
        anns = fetch_announcements_for_date(d)
        time.sleep(0.5)  # be gentle with NSE, this is a lot of sequential hits
        if not anns:
            days_empty += 1
            print("  -> no data")
            continue
        days_with_data += 1

        nifty_nxt = _next_trading_index_bar(provider, INDEX_SYMBOL, d)
        nifty_oc = None
        if nifty_nxt and nifty_nxt["open"]:
            nifty_oc = (nifty_nxt["close"] - nifty_nxt["open"]) / nifty_nxt["open"] * 100

        seen_today = set()
        day_picks = 0
        for ann in anns:
            if not isinstance(ann, dict):
                continue
            symbol = (ann.get("symbol") or "").upper().strip()
            subject = (ann.get("desc") or ann.get("subject") or "").strip()
            details = (ann.get("attchmntText") or ann.get("LONGDESC") or "").strip()
            if not symbol or not subject or symbol in seen_today:
                continue

            category, base_score, tier = classify_announcement(subject, details)
            if category == "SKIP" or tier == 3:
                continue

            nxt = _next_trading_bar(provider, symbol, d)
            if not nxt or not nxt["open"]:
                continue
            seen_today.add(symbol)

            oc_pct = (nxt["close"] - nxt["open"]) / nxt["open"] * 100
            alpha = (oc_pct - nifty_oc) if nifty_oc is not None else None
            picks.append({
                "date": d.strftime("%Y-%m-%d"), "symbol": symbol, "category": category,
                "tier": tier, "score": base_score, "oc_pct": round(oc_pct, 2),
                "alpha": round(alpha, 2) if alpha is not None else None,
            })
            day_picks += 1
        print(f"  -> {day_picks} tier1/2 picks")

    print(f"\n{'='*70}")
    print(f"BACKTEST: {days_with_data} days with announcement data, {days_empty} empty")
    print(f"{'='*70}")
    if days_with_data < LOOKBACK_DAYS * 0.3:
        print("\nWARNING: most days returned no announcement data. NSE's public")
        print("endpoint most likely does not serve historical ranges this far")
        print("back - treat any results below as low-confidence, NOT a real")
        print(f"{LOOKBACK_DAYS}-day backtest. See the CAVEAT at the top of this file.\n")

    if not picks:
        print("\nNo picks evaluated - nothing to report.")
        return

    def _report(label, subset):
        if not subset:
            print(f"  {label}: no picks")
            return
        n = len(subset)
        wins = sum(1 for p in subset if p["oc_pct"] > 0)
        avg_oc = sum(p["oc_pct"] for p in subset) / n
        alphas = [p["alpha"] for p in subset if p["alpha"] is not None]
        line = (f"  {label}: n={n}  win_rate={wins}/{n} ({wins/n*100:.1f}%)  "
                f"avg_O->C={avg_oc:+.2f}%")
        if alphas:
            avg_a = sum(alphas) / len(alphas)
            beat = sum(1 for a in alphas if a > 0)
            line += (f"  avg_alpha={avg_a:+.2f}%  "
                     f"beat_market={beat}/{len(alphas)} ({beat/len(alphas)*100:.1f}%)")
        print(line)

    print(f"\nSUMMARY over {len(picks)} picks across {days_with_data} days with data\n")
    _report("TIER 1", [p for p in picks if p["tier"] == 1])
    _report("TIER 2", [p for p in picks if p["tier"] == 2])
    _report("ALL   ", picks)

    print(f"\n{'-'*70}")
    print("Per-pick detail:")
    for p in picks:
        a = f"  alpha {p['alpha']:+.2f}%" if p["alpha"] is not None else ""
        print(f"{p['date']} T{p['tier']} {p['symbol']:12s} {p['category']:20s} "
              f"O->C {p['oc_pct']:+.2f}%{a}")
    print(f"{'-'*70}\n")


if __name__ == "__main__":
    run_backtest()
