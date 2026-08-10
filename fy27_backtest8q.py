"""
fy27_backtest_8q.py

Extends the existing FY27 results checklist backtest:
  1. Two SEPARATE universes: large-cap (real NIFTY 100 constituents) and
     mid/small-cap (reuses existing fetch_liquid_universe). Never merged -
     they behaved oppositely in prior runs (large-cap had a real edge,
     mid/small-cap inverted), so mixing them would hide which one is
     driving any result.
  2. 8 quarters lookback per symbol, not 1.
  3. Staleness filter: dedupes announcements referencing the same quarter
     (corrigendum/revised/re-submitted filings) - keeps only the first
     genuine filing per symbol per quarter.
  4. guidance_upgrade tracked as its own explicit true/false field,
     separate from the overall ENTER_LONG/SKIP decision, so you can slice
     "beat alone" vs "beat + guidance upgrade" after the fact.
  5. Reports the FULL distribution (sorted moves, count of >=10% events),
     not just mean/win-rate - a single outlier should never look like a
     working strategy again.

Reuses working infra from fy27_backtest.py (announcement fetch, PDF text
extraction, price lookups, LLM calls) via import - does not duplicate it.

Usage:
    python fy27_backtest_8q.py --universe large
    python fy27_backtest_8q.py --universe midsmall
"""

import argparse
import json
import re
import statistics
from datetime import datetime, timedelta

# Reuse working, already-tested infra instead of duplicating it.
import fy27_backtest as base


NIFTY100_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
QUARTERS_LOOKBACK = 8
MONTHS_LOOKBACK = QUARTERS_LOOKBACK * 3 + 2  # small buffer either side


def fetch_large_cap_universe(min_turnover_cr=100, top_n=50):
    """Real NIFTY 100 constituents, liquidity-filtered the same way
    fetch_liquid_universe() does for mid/small-cap - so both universes
    are built by a comparable method, not one real and one arbitrary."""
    probe_date = datetime.now() - timedelta(days=3)
    day_data = {}
    for _ in range(7):
        day_data = base.get_bhavcopy_day(probe_date)
        if day_data:
            break
        probe_date -= timedelta(days=1)
    if not day_data:
        print("  [WARN] could not find a recent bhavcopy day - universe will be empty")
        return []

    syms = base.fetch_index_constituents(NIFTY100_URL)
    if not syms:
        print("  [WARN] NIFTY 100 constituent list fetch failed")
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
    print(f"  NIFTY 100: {len(top)} liquid large-caps (of {len(syms)} constituents), "
          f"turnover range {top[-1][1]:.0f}-{top[0][1]:.0f} Cr" if top else "  0 names cleared bar")
    return sorted(s for s, _ in top)


def dedupe_stale_filings(announcements):
    """Keep only the first genuine results filing per (symbol, quarter-ish
    date bucket). A quarter bucket is a 75-day window - if two 'financial
    result' announcements for the same symbol land within 75 days of each
    other, the second is almost certainly a corrigendum/revision/re-filing
    of the same quarter, not a new quarter's result."""
    by_symbol = {}
    for a in announcements:
        sym = a.get("symbol")
        by_symbol.setdefault(sym, []).append(a)

    kept = []
    for sym, anns in by_symbol.items():
        anns_sorted = sorted(anns, key=lambda a: a.get("_parsed_date"))
        last_kept_date = None
        for a in anns_sorted:
            d = a["_parsed_date"]
            if last_kept_date is None or (d - last_kept_date).days > 75:
                kept.append(a)
                last_kept_date = d
            # else: within 75 days of the last genuine filing - treat as
            # stale/duplicate, skip it
    return kept


def build_checklist_prompt_v2(symbol, pdf_text, pre_move_pct):
    """Same checklist logic as base.build_checklist_prompt, but the JSON
    response now includes an explicit guidance_upgrade boolean, separate
    from the overall decision - so 'beat + guidance up' can be sliced out
    and analyzed on its own instead of only being buried inside whether
    ENTER_LONG fired."""
    base_prompt = base.build_checklist_prompt(symbol, pdf_text, pre_move_pct)
    # Splice an extra required field into the JSON response instructions.
    addition = (
        '\n\nADDITIONALLY, always include this field regardless of decision:\n'
        '"guidance_upgrade": true if management commentary explicitly raises '
        'outlook, guidance, or growth expectations for future quarters '
        '(not just describes the current quarter) - false otherwise.\n'
    )
    marker = 'Respond with ONLY this JSON, no other text:\n{{'
    if marker in base_prompt:
        base_prompt = base_prompt.replace(
            'Respond with ONLY this JSON, no other text:\n{{',
            addition + 'Respond with ONLY this JSON, no other text:\n{{'
        )
    else:
        base_prompt += addition
    base_prompt = base_prompt.replace(
        '"reasoning": "<1-2 sentences citing the specific numbers/phrases that drove this>"}}',
        '"reasoning": "<1-2 sentences citing the specific numbers/phrases that drove this>",\n'
        '  "guidance_upgrade": true | false}}'
    )
    return base_prompt


def run_universe(universe_name, symbols):
    print(f"\n{'='*70}\nUniverse: {universe_name} ({len(symbols)} symbols), "
          f"{QUARTERS_LOOKBACK} quarters lookback\n{'='*70}")

    session = base.nse_session()
    to_date = datetime.now() - timedelta(days=3)
    from_date = to_date - timedelta(days=MONTHS_LOOKBACK * 30)

    results = []
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {symbol}...")
        anns = base.fetch_results_announcements(session, symbol, from_date, to_date)
        if not anns:
            continue

        parsed = []
        for a in anns:
            date_str = a.get("an_dt") or a.get("date") or ""
            try:
                d = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except Exception:
                try:
                    d = datetime.strptime(date_str[:10], "%d-%b-%Y")
                except Exception:
                    continue
            a["_parsed_date"] = d
            a["symbol"] = symbol
            parsed.append(a)

        fresh = dedupe_stale_filings(parsed)
        fresh.sort(key=lambda a: a["_parsed_date"])
        fresh = fresh[-QUARTERS_LOOKBACK:]  # most recent N quarters only

        stale_count = len(parsed) - len(fresh)
        if stale_count > 0:
            print(f"    filtered {stale_count} stale/duplicate filing(s)")

        for a in fresh:
            result_date = a["_parsed_date"]
            pdf_url = a.get("attchmntFile") or a.get("pdf") or "-"
            pdf_text = base.download_pdf_text(pdf_url)
            if len(pdf_text) < 200:
                continue

            pre_move = base.pre_result_move_pct(symbol, result_date)
            fwd = base.forward_returns(symbol, result_date)
            if fwd is None:
                continue

            prompt = build_checklist_prompt_v2(symbol, pdf_text, pre_move)
            verdict = base.call_groq_with_retry(prompt)
            if verdict is None:
                continue

            results.append({
                "symbol": symbol,
                "date": result_date.strftime("%Y-%m-%d"),
                "decision": verdict.get("decision"),
                "guidance_upgrade": verdict.get("guidance_upgrade"),
                "pre_move_pct": pre_move,
                "revenue_yoy_pct": verdict.get("revenue_yoy_pct"),
                "profit_yoy_pct": verdict.get("profit_yoy_pct"),
                "next_day_oc": fwd["next_day_oc"],
                "three_day_cc": fwd["three_day_cc"],
                "reasoning": verdict.get("reasoning", ""),
            })

        out_file = f"fy27_backtest_8q_{universe_name}.json"
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)

    return results


def report_distribution(label, subset, field):
    vals = [r[field] for r in subset if r.get(field) is not None]
    if not vals:
        print(f"  {label}: no data")
        return
    n = len(vals)
    wins = sum(1 for v in vals if v > 0)
    over10 = [v for v in vals if abs(v) >= 10]
    print(f"  {label}: n={n}  win_rate={wins}/{n} ({wins/n*100:.1f}%)  "
          f"mean={statistics.mean(vals):+.2f}%  median={statistics.median(vals):+.2f}%")
    print(f"    events with |move|>=10%: {len(over10)}/{n} "
          f"({len(over10)/n*100:.1f}%)")
    if over10:
        top_sorted = sorted(vals, reverse=True)[:5]
        bottom_sorted = sorted(vals)[:5]
        print(f"    top 5 moves: {[round(v,2) for v in top_sorted]}")
        print(f"    bottom 5 moves: {[round(v,2) for v in bottom_sorted]}")


def print_report(universe_name, results):
    print(f"\n{'='*70}\nRESULTS: {universe_name}  (total events: {len(results)})\n{'='*70}")

    for decision in ("ENTER_LONG", "ENTER_SHORT", "SKIP"):
        subset = [r for r in results if r["decision"] == decision]
        if not subset:
            continue
        print(f"\n{decision} (n={len(subset)})")
        report_distribution("  next-day O->C", subset, "next_day_oc")
        report_distribution("  3-day C->C   ", subset, "three_day_cc")

    # The actual hypothesis test: beat alone vs beat + guidance upgrade
    enter_long = [r for r in results if r["decision"] == "ENTER_LONG"]
    beat_with_guidance = [r for r in enter_long if r.get("guidance_upgrade") is True]
    beat_without_guidance = [r for r in enter_long if r.get("guidance_upgrade") is False]

    print(f"\n--- Hypothesis check: does guidance_upgrade sharpen ENTER_LONG? ---")
    print(f"\nENTER_LONG + guidance_upgrade=True (n={len(beat_with_guidance)})")
    report_distribution("  next-day O->C", beat_with_guidance, "next_day_oc")
    report_distribution("  3-day C->C   ", beat_with_guidance, "three_day_cc")

    print(f"\nENTER_LONG + guidance_upgrade=False (n={len(beat_without_guidance)})")
    report_distribution("  next-day O->C", beat_without_guidance, "next_day_oc")
    report_distribution("  3-day C->C   ", beat_without_guidance, "three_day_cc")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", choices=["large", "midsmall"], required=True)
    args = parser.parse_args()

    if args.universe == "large":
        symbols = fetch_large_cap_universe()
    else:
        symbols = base.fetch_liquid_universe()

    if not symbols:
        print("Universe is empty - aborting.")
        return

    results = run_universe(args.universe, symbols)
    print_report(args.universe, results)
    print(f"\nSaved to fy27_backtest_8q_{args.universe}.json")


if __name__ == "__main__":
    main()
