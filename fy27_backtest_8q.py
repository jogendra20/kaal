"""
fy27_backtest_8q.py

8-quarter large-cap / mid-small-cap results checklist backtest.

Adds two things beyond the original checklist:
  1. guidance_upgrade - explicit true/false field inside the real JSON
     schema (earlier version appended this outside the schema and the
     model silently ignored it - fixed).
  2. beat_vs_own_guidance - NEW. Extracts each quarter's forward guidance
     (guidance_given) via the LLM call itself, then feeds LAST quarter's
     guidance into THIS quarter's prompt and asks whether the company beat,
     met, or missed the specific target it set for itself. This targets
     the known mid/small-cap failure mode directly: large YoY growth is
     normal cadence for growth mid-caps, so comparing against trailing
     average (already tried, already failed) doesn't isolate a genuine
     surprise. Comparing against the company's own stated target does,
     without needing paid consensus data.

Uses nse_cache.py for announcements/PDFs/prices (immutable historical
data - cached once, never re-fetched). LLM calls are NEVER cached - each
run must re-evaluate live so prompt fixes actually take effect.

Usage:
    python fy27_backtest_8q.py --universe large
    python fy27_backtest_8q.py --universe midsmall
    (rerun same command to resume after a crash)
"""

import load_env
load_env.load_env()

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timedelta

import fy27_backtest as base
import nse_cache

NIFTY100_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
QUARTERS_LOOKBACK = 8
MONTHS_LOOKBACK = QUARTERS_LOOKBACK * 3 + 2
MAX_RETRIES = 5
BASE_DELAY = 5

COUNTS = {
    "symbols_total": 0, "symbols_with_raw_announcements": 0,
    "raw_announcements_total": 0, "announcements_after_date_parse": 0,
    "announcements_after_dedupe": 0, "pdf_fetch_attempted": 0,
    "pdf_fetch_ok": 0, "pdf_too_short": 0, "pre_move_none": 0,
    "fwd_returns_none": 0, "llm_called": 0, "llm_returned_none": 0,
    "llm_ok": 0,
}


def retry_with_backoff(fn, *args, label="request", **kwargs):
    delay = BASE_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            is_rl = "429" in msg or "rate" in msg or "too many" in msg
            if attempt == MAX_RETRIES:
                print(f"    [FAIL] {label}: giving up after {MAX_RETRIES} attempts ({e})")
                return None
            print(f"    [WARN] {label} {'rate-limited' if is_rl else 'error'} "
                  f"(attempt {attempt}/{MAX_RETRIES}): {e} - waiting {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 80)
    return None


def load_progress(universe_name):
    path = f"fy27_backtest_8q_{universe_name}_progress.json"
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        print(f"  Resuming: {len(data.get('processed_symbols', []))} symbols already processed.")
        return data
    return {"processed_symbols": [], "results": []}


def save_progress(universe_name, progress):
    path = f"fy27_backtest_8q_{universe_name}_progress.json"
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)
    with open(f"fy27_backtest_8q_{universe_name}.json", "w") as f:
        json.dump(progress["results"], f, indent=2)


def fetch_large_cap_universe(min_turnover_cr=100, top_n=50):
    probe_date = datetime.now() - timedelta(days=3)
    day_data = {}
    for _ in range(7):
        day_data = base.get_bhavcopy_day(probe_date)
        if day_data:
            break
        probe_date -= timedelta(days=1)
    if not day_data:
        print("  [WARN] no recent bhavcopy day found")
        return []
    syms = retry_with_backoff(base.fetch_index_constituents, NIFTY100_URL, label="NIFTY100 list")
    if not syms:
        return []
    ranked = []
    for sym in syms:
        bar = day_data.get(sym)
        if not bar:
            continue
        turnover_cr = bar["turnover_lacs"] / 100.0
        if turnover_cr >= min_turnover_cr:
            ranked.append((sym, turnover_cr))
    ranked.sort(key=lambda x: -x[1])
    top = ranked[:top_n]
    print(f"  NIFTY 100: {len(top)} liquid large-caps (of {len(syms)} constituents)")
    return sorted(s for s, _ in top)


def dedupe_stale_filings(announcements):
    by_symbol = {}
    for a in announcements:
        by_symbol.setdefault(a.get("symbol"), []).append(a)
    kept = []
    for sym, anns in by_symbol.items():
        anns_sorted = sorted(anns, key=lambda a: a["_parsed_date"])
        last_kept_date = None
        for a in anns_sorted:
            d = a["_parsed_date"]
            if last_kept_date is None or (d - last_kept_date).days > 75:
                kept.append(a)
                last_kept_date = d
    return kept


def build_checklist_prompt_v2(symbol, pdf_text, pre_move_pct, prior_guidance=None):
    """Extends base checklist: guidance_upgrade and guidance_given are now
    real fields inside the JSON schema. If prior_guidance is given (this
    symbol's own stated targets from LAST quarter), the model is also
    asked whether THIS quarter's actual results beat/met/missed that
    specific target - beat_vs_own_guidance - separate from the general
    YoY-beat criteria."""
    prompt = base.build_checklist_prompt(symbol, pdf_text, pre_move_pct)

    old_schema = '''{"decision": "ENTER_LONG" | "ENTER_SHORT" | "SKIP",
  "revenue_yoy_pct": <number or null>,
  "profit_yoy_pct": <number or null>,
  "beat_basis": "trend" | "fallback_threshold" | "not_applicable",
  "reasoning": "<1-2 sentences citing the specific numbers/phrases that drove this>"}'''

    new_schema = '''{"decision": "ENTER_LONG" | "ENTER_SHORT" | "SKIP",
  "revenue_yoy_pct": <number or null>,
  "profit_yoy_pct": <number or null>,
  "beat_basis": "trend" | "fallback_threshold" | "not_applicable",
  "guidance_upgrade": true | false,
  "guidance_given": "<short summary of any specific forward target management stated for FUTURE quarters, or none if nothing specific was stated>",
  "beat_vs_own_guidance": "beat" | "met" | "missed" | "no_prior_guidance",
  "reasoning": "<1-2 sentences citing the specific numbers/phrases that drove this, INCLUDING whether management raised outlook>"}'''

    if old_schema not in prompt:
        raise RuntimeError(
            "JSON schema marker not found - base.build_checklist_prompt may have "
            "changed. Update old_schema in build_checklist_prompt_v2 to match."
        )
    prompt = prompt.replace(old_schema, new_schema, 1)

    if prior_guidance and prior_guidance not in (None, "none", ""):
        prompt += (
            f'\n\nIMPORTANT - PRIOR GUIDANCE CHECK:\n'
            f'Last quarter, this company stated the following forward guidance/target: {prior_guidance}\n'
            f'Compare THIS quarter actual results against that SPECIFIC prior statement (not general YoY trend) '
            f'and set beat_vs_own_guidance to beat if actual results exceeded that target, met if in line, '
            f'missed if below it.\n'
        )
    else:
        prompt += (
            '\n\nNo specific prior-quarter guidance is available for comparison - '
            'set beat_vs_own_guidance to no_prior_guidance.\n'
        )

    return prompt


def run_universe(universe_name, symbols):
    print(f"\\n{'='*70}\\nUniverse: {universe_name} ({len(symbols)} symbols), "
          f"{QUARTERS_LOOKBACK} quarters\\n{'='*70}")

    progress = load_progress(universe_name)
    done = set(progress["processed_symbols"])
    results = progress["results"]
    remaining = [s for s in symbols if s not in done]
    COUNTS["symbols_total"] = len(symbols)

    # Seed per-symbol guidance history from already-saved results (handles
    # resume across separate runs, not just within one run's loop).
    guidance_history = {}  # symbol -> list of (date, guidance_given)
    for r in results:
        guidance_history.setdefault(r["symbol"], []).append(
            (r["date"], r.get("guidance_given"))
        )

    session = base.nse_session()
    to_date = datetime.now() - timedelta(days=3)
    from_date = to_date - timedelta(days=MONTHS_LOOKBACK * 30)
    print(f"  Announcement window: {from_date.date()} to {to_date.date()}")

    for i, symbol in enumerate(remaining, 1):
        print(f"[{i}/{len(remaining)}] {symbol}...")

        anns = retry_with_backoff(nse_cache.get_announcements, session, symbol,
                                   from_date, to_date, label=f"{symbol} announcements")
        if anns:
            COUNTS["symbols_with_raw_announcements"] += 1
            COUNTS["raw_announcements_total"] += len(anns)
        else:
            progress["processed_symbols"].append(symbol)
            save_progress(universe_name, progress)
            continue

        parsed = []
        for a in anns:
            date_str = a.get("sort_date") or ""
            d = None
            if date_str:
                try:
                    d = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except Exception:
                    d = None
            if d is None:
                an_dt = a.get("an_dt") or ""
                try:
                    d = datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S")
                except Exception:
                    continue
            a["_parsed_date"] = d
            a["symbol"] = symbol
            parsed.append(a)
        COUNTS["announcements_after_date_parse"] += len(parsed)

        fresh = dedupe_stale_filings(parsed)
        fresh.sort(key=lambda a: a["_parsed_date"])
        fresh = fresh[-QUARTERS_LOOKBACK:]
        COUNTS["announcements_after_dedupe"] += len(fresh)
        print(f"    announcements -> {len(anns)} raw -> {len(parsed)} parsed -> {len(fresh)} after dedupe")

        sym_history = guidance_history.setdefault(symbol, [])

        for a in fresh:
            result_date = a["_parsed_date"]
            pdf_url = a.get("attchmntFile") or a.get("pdf") or "-"
            COUNTS["pdf_fetch_attempted"] += 1
            pdf_text = retry_with_backoff(nse_cache.get_pdf_text, pdf_url,
                                           label=f"{symbol} {result_date.date()} PDF")
            if not pdf_text or len(pdf_text) < 200:
                COUNTS["pdf_too_short"] += 1
                continue
            COUNTS["pdf_fetch_ok"] += 1

            pre_move = nse_cache.get_pre_move(symbol, result_date)
            if pre_move is None:
                COUNTS["pre_move_none"] += 1

            fwd = nse_cache.get_forward_returns(symbol, result_date)
            if fwd is None:
                COUNTS["fwd_returns_none"] += 1
                continue

            # find the most recent PRIOR quarter's guidance for this symbol
            prior_entries = [h for h in sym_history if h[0] < result_date.strftime("%Y-%m-%d")]
            prior_guidance = sorted(prior_entries, key=lambda h: h[0])[-1][1] if prior_entries else None

            prompt = build_checklist_prompt_v2(symbol, pdf_text, pre_move, prior_guidance)
            COUNTS["llm_called"] += 1
            verdict = base.call_groq_with_retry(prompt)
            if verdict is None:
                COUNTS["llm_returned_none"] += 1
                continue
            COUNTS["llm_ok"] += 1

            entry = {
                "symbol": symbol, "date": result_date.strftime("%Y-%m-%d"),
                "decision": verdict.get("decision"),
                "guidance_upgrade": verdict.get("guidance_upgrade"),
                "guidance_given": verdict.get("guidance_given"),
                "beat_vs_own_guidance": verdict.get("beat_vs_own_guidance"),
                "pre_move_pct": pre_move,
                "revenue_yoy_pct": verdict.get("revenue_yoy_pct"),
                "profit_yoy_pct": verdict.get("profit_yoy_pct"),
                "next_day_oc": fwd["next_day_oc"],
                "three_day_cc": fwd["three_day_cc"],
                "reasoning": verdict.get("reasoning", ""),
            }
            results.append(entry)
            sym_history.append((entry["date"], entry.get("guidance_given")))

        progress["processed_symbols"].append(symbol)
        progress["results"] = results
        save_progress(universe_name, progress)

    return results


def print_funnel():
    print(f"\\n{'='*70}\\nFUNNEL DIAGNOSTICS\\n{'='*70}")
    for k, v in COUNTS.items():
        print(f"  {k}: {v}")


def report_distribution(label, subset, field):
    vals = [r[field] for r in subset if r.get(field) is not None]
    if not vals:
        print(f"  {label}: no data")
        return
    n = len(vals)
    wins = sum(1 for v in vals if v > 0)
    over10 = [v for v in vals if abs(v) >= 10]
    print(f"  {label}: n={n} win_rate={wins}/{n} ({wins/n*100:.1f}%) "
          f"mean={statistics.mean(vals):+.2f}% |>=10%|={len(over10)}")


def print_report(universe_name, results):
    print(f"\\n{'='*70}\\nRESULTS: {universe_name} (total events: {len(results)})\\n{'='*70}")

    for decision in ("ENTER_LONG", "ENTER_SHORT", "SKIP"):
        subset = [r for r in results if r["decision"] == decision]
        if subset:
            print(f"\\n{decision} (n={len(subset)})")
            report_distribution("  next-day", subset, "next_day_oc")
            report_distribution("  3-day", subset, "three_day_cc")

    enter_long = [r for r in results if r["decision"] == "ENTER_LONG"]

    print(f"\\n--- guidance_upgrade split (ENTER_LONG only) ---")
    for val in (True, False):
        subset = [r for r in enter_long if r.get("guidance_upgrade") is val]
        print(f"\\nguidance_upgrade={val} (n={len(subset)})")
        report_distribution("  next-day", subset, "next_day_oc")
        report_distribution("  3-day", subset, "three_day_cc")

    print(f"\\n--- beat_vs_own_guidance split (ENTER_LONG only) ---")
    for val in ("beat", "met", "missed", "no_prior_guidance"):
        subset = [r for r in enter_long if r.get("beat_vs_own_guidance") == val]
        if subset:
            print(f"\\n{val} (n={len(subset)})")
            report_distribution("  next-day", subset, "next_day_oc")
            report_distribution("  3-day", subset, "three_day_cc")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["large", "midsmall"], required=True)
    args = parser.parse_args()

    if args.universe == "large":
        symbols = fetch_large_cap_universe()
    else:
        symbols = retry_with_backoff(base.fetch_liquid_universe, label="universe")

    if not symbols:
        print("Universe is empty - aborting.")
        return

    results = run_universe(args.universe, symbols)
    print_funnel()
    print_report(args.universe, results)


if __name__ == "__main__":
    main()
