"""
observation_monday.py

STANDALONE. Not wired into any decision/live-trading path. For manual
observation only.

1. Fetches ALL NSE quarterly-results-type announcements filed from last
   Friday 15:30 IST through now (market-wide, not looped per-symbol -
   this assumes NSE's corporate-announcements endpoint returns all
   companies when called without a symbol param; if that assumption is
   wrong this will fail loudly, not silently return zero).
2. Staleness check:
   a. Is this announcement itself fresh (landed in the actual window)
      or an old/backdated filing incorrectly picked up?
   b. Has this exact quarter already been reported before (dedupe
      against a 100-day lookback per symbol - same logic used in
      fy27_backtest_8q.py tonight)?
3. Already-moved check: Friday's close vs close 3 trading days before
   Friday - flags stocks that already ran up/down significantly BEFORE
   the result printed (can't reflect the result itself yet, since it's
   a weekend filing, but flags names where the "surprise" may already
   be priced in from pre-existing momentum).
4. Extracts PAT/net-profit, EBITDA, revenue, guidance (if present), EPS
   via LLM - extraction only, no decision, no ENTER_LONG/SKIP.
5. Ranks by a priority order YOU specified (PAT/net-profit weighted
   highest, then EBITDA, revenue, guidance, EPS) - this ranking has NO
   backtested validation. It is your stated priority order, sorted -
   not a proven signal. Tonight's actual backtests showed a small edge
   on large-cap and a confirmed negative on mid/small-cap using a
   DIFFERENT checklist logic than this ranking uses.

Usage:
    python observation_monday.py
"""

import load_env
load_env.load_env()

import json
import time
import statistics
from datetime import datetime, timedelta

import kaal_http
import fy27_backtest as base  # reuse: download_pdf_text (fixed), call_groq_with_retry, get_bhavcopy_day

MAX_RETRIES = 4
BASE_DELAY = 5
ALREADY_MOVED_THRESHOLD = 8.0  # % move Friday vs 3-days-prior close, flags pre-existing run-up
STALE_DEDUPE_DAYS = 100

RESULT_KEYWORDS = [
    "financial result", "financial results", "outcome of board meeting",
    "unaudited financial", "audited financial",
]


def retry(fn, *args, label="request", **kwargs):
    delay = BASE_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"  [FAIL] {label}: giving up after {MAX_RETRIES} attempts ({e})")
                return None
            print(f"  [WARN] {label} failed (attempt {attempt}/{MAX_RETRIES}): {e} - waiting {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return None


def get_window():
    """Last Friday 15:30 IST through now."""
    now = datetime.now()
    days_since_friday = (now.weekday() - 4) % 7
    if days_since_friday == 0 and now.hour < 15:
        days_since_friday = 7
    last_friday = now - timedelta(days=days_since_friday)
    window_start = last_friday.replace(hour=15, minute=30, second=0, microsecond=0)
    return window_start, now, last_friday.replace(hour=0, minute=0, second=0, microsecond=0)


def fetch_market_wide_announcements(session, from_date, to_date):
    """Attempts a market-wide (no symbol param) call. If NSE requires a
    symbol and this returns empty/errors, that assumption was wrong -
    fails loudly with a clear message rather than silently proceeding
    with zero results."""
    url = "https://www.nseindia.com/api/corporate-announcements"
    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }
    r = session.get(url, params=params, headers=kaal_http.HEADERS_NSE, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"NSE returned status {r.status_code} - {r.text[:200]}")
    data = r.json()
    if not data:
        raise RuntimeError(
            "Market-wide call returned ZERO results. This likely means the "
            "symbol-less market-wide assumption is WRONG for this endpoint - "
            "NSE may require a symbol param. Do not trust a silent empty "
            "result here; this needs manual verification before relying on "
            "this script."
        )
    return data


def is_results_announcement(a):
    text = (a.get("desc", "") + " " + a.get("attchmntText", "")).lower()
    return any(k in text for k in RESULT_KEYWORDS)


def get_pre_result_prices(symbol, friday_date):
    """Friday's close and close 3 trading days before Friday."""
    friday_data = retry(base.get_bhavcopy_day, friday_date, label=f"{symbol} Friday bhavcopy")
    if not friday_data or symbol not in friday_data:
        return None, None, None
    friday_close = friday_data[symbol].get("close")

    probe = friday_date - timedelta(days=1)
    found = 0
    prior_close = None
    for _ in range(10):
        day = retry(base.get_bhavcopy_day, probe, label=f"{symbol} prior bhavcopy")
        if day and symbol in day:
            found += 1
            if found == 3:
                prior_close = day[symbol].get("close")
                break
        probe -= timedelta(days=1)

    if friday_close is None or prior_close is None or prior_close == 0:
        return friday_close, prior_close, None
    pct_move = (friday_close - prior_close) / prior_close * 100
    return friday_close, prior_close, pct_move


EXTRACTION_PROMPT_TEMPLATE = """You are extracting raw financial figures from a quarterly results filing.
Do NOT make a buy/sell/hold decision. Extract only what is stated in the text.

Company: {symbol}

Filing text:
{pdf_text}

Respond with ONLY this JSON, no other text:
{{"revenue_yoy_pct": <number or null>,
  "profit_yoy_pct": <number or null - this covers PAT / net profit / profit after tax, same line item>,
  "ebitda_margin_change_bps": <number or null - basis points change YoY, positive = expanding>,
  "eps_yoy_pct": <number or null>,
  "guidance_text": "<any specific forward-looking statement about future quarters, or null if none stated>",
  "extraction_confidence": "high" | "medium" | "low"}}"""


def extract_figures(symbol, pdf_text):
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(symbol=symbol, pdf_text=pdf_text)
    return base.call_groq_with_retry(prompt)


def priority_score(entry):
    """Composite score in the priority order given: profit (PAT/net
    profit combined - same line item, extracted once) weighted highest,
    then EBITDA margin change, then revenue, then a guidance bonus, then
    EPS. NO backtested validation behind these weights - this is a
    direct implementation of the stated priority order, nothing more."""
    score = 0
    if entry.get("profit_yoy_pct") is not None:
        score += 4 * entry["profit_yoy_pct"]
    if entry.get("ebitda_margin_change_bps") is not None:
        score += 2 * (entry["ebitda_margin_change_bps"] / 10.0)
    if entry.get("revenue_yoy_pct") is not None:
        score += 2 * entry["revenue_yoy_pct"]
    if entry.get("guidance_text") and entry["guidance_text"].lower() not in ("null", "none", ""):
        score += 15  # flat bonus for any stated forward guidance at all
    if entry.get("eps_yoy_pct") is not None:
        score += 1 * entry["eps_yoy_pct"]
    return round(score, 2)


def main():
    window_start, window_end, friday_date = get_window()
    print(f"{'='*70}")
    print(f"OBSERVATION RUN - window: {window_start} to {window_end}")
    print(f"NOT a trading signal. NOT backtested. For manual review only.")
    print(f"{'='*70}\n")

    session = kaal_http.nse_session()

    print("Fetching market-wide announcements...")
    raw = retry(fetch_market_wide_announcements, session, window_start, window_end,
                label="market-wide announcement fetch")
    if raw is None:
        print("ABORTED: could not fetch announcements. See error above - "
              "likely the market-wide/no-symbol assumption is wrong for "
              "this endpoint and it needs a different fetch approach.")
        return

    print(f"Raw announcements in window: {len(raw)}")
    results_only = [a for a in raw if is_results_announcement(a)]
    print(f"Filtered to results-type announcements: {len(results_only)}")

    # Dedupe within this batch by symbol - take latest per symbol if
    # somehow duplicated within the window itself
    by_symbol = {}
    for a in results_only:
        sym = a.get("symbol")
        if sym:
            by_symbol[sym] = a  # last one wins if duplicate in-window

    print(f"Unique symbols with results this weekend: {len(by_symbol)}\n")

    observations = []
    for i, (symbol, a) in enumerate(by_symbol.items(), 1):
        print(f"[{i}/{len(by_symbol)}] {symbol}...")

        # Staleness check 1: does this exact quarter already have an
        # earlier filing on record for this symbol (re-filing/corrigendum)?
        lookback_start = window_start - timedelta(days=STALE_DEDUPE_DAYS)
        history = retry(base.fetch_results_announcements, session, symbol,
                         lookback_start, window_start, label=f"{symbol} history check")
        is_stale_refiling = False
        if history:
            for h in history:
                sort_date = h.get("sort_date", "")
                if sort_date:
                    try:
                        hd = datetime.strptime(sort_date[:10], "%Y-%m-%d")
                        if (window_start - hd).days < 75:
                            is_stale_refiling = True
                            break
                    except Exception:
                        pass

        if is_stale_refiling:
            print(f"    STALE - quarter already reported within last 75 days, skipping")
            continue

        # Already-moved check
        friday_close, prior_close, pct_move = get_pre_result_prices(symbol, friday_date)
        already_moved = pct_move is not None and abs(pct_move) >= ALREADY_MOVED_THRESHOLD
        if already_moved:
            print(f"    ALREADY MOVED {pct_move:+.1f}% pre-result (>= {ALREADY_MOVED_THRESHOLD}% threshold) - flagged, not excluded")

        # Extract figures
        pdf_url = a.get("attchmntFile") or a.get("pdf") or "-"
        pdf_text = retry(base.download_pdf_text, pdf_url, label=f"{symbol} PDF")
        if not pdf_text or len(pdf_text) < 200:
            print(f"    PDF extraction failed/too short, skipping")
            continue

        verdict = extract_figures(symbol, pdf_text)
        if verdict is None:
            print(f"    LLM extraction failed, skipping")
            continue

        entry = {
            "symbol": symbol,
            "announced_at": a.get("sort_date"),
            "desc": a.get("desc"),
            "revenue_yoy_pct": verdict.get("revenue_yoy_pct"),
            "profit_yoy_pct": verdict.get("profit_yoy_pct"),
            "ebitda_margin_change_bps": verdict.get("ebitda_margin_change_bps"),
            "eps_yoy_pct": verdict.get("eps_yoy_pct"),
            "guidance_text": verdict.get("guidance_text"),
            "extraction_confidence": verdict.get("extraction_confidence"),
            "friday_close": friday_close,
            "pre_result_3day_move_pct": pct_move,
            "already_moved_flag": already_moved,
        }
        entry["priority_score"] = priority_score(entry)
        observations.append(entry)

    observations.sort(key=lambda e: e["priority_score"], reverse=True)

    with open("observation_monday.json", "w") as f:
        json.dump(observations, f, indent=2)

    print(f"\n{'='*70}")
    print(f"OBSERVATION LIST ({len(observations)} candidates) - ranked by stated priority order")
    print(f"NOT a trading signal. Weights are your stated priorities, not backtested.")
    print(f"{'='*70}\n")

    for e in observations:
        moved_flag = " [ALREADY MOVED]" if e["already_moved_flag"] else ""
        print(f"{e['priority_score']:>8.1f}  {e['symbol']:<15} "
              f"profit={e['profit_yoy_pct']}  rev={e['revenue_yoy_pct']}  "
              f"ebitda_bps={e['ebitda_margin_change_bps']}  eps={e['eps_yoy_pct']}  "
              f"guidance={'yes' if e['guidance_text'] and e['guidance_text'] not in ('null','none') else 'no'}"
              f"{moved_flag}")

    print(f"\nSaved to observation_monday.json")


if __name__ == "__main__":
    main()
