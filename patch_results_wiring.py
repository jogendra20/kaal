f = "kaal_scorer.py"
c = open(f).read()

old1 = '''from kaal_llm import call_llm
from kaal_sources import download_pdf_text
from kaal_event_classifier import classify_event_type, classify_announcement

def _build_results_prompt(subject, details, pdf_text, macro_context):'''
new1 = '''from kaal_llm import call_llm
from kaal_sources import download_pdf_text
from kaal_event_classifier import classify_event_type, classify_announcement
from kaal_results_history import record_result


def _fiscal_quarter_label(an_dt: str):
    """Best-effort 'Q1FY27'-style label from an announcement's filing
    date, buffered back ~45 days so a results filing (usually 3-6 weeks
    after quarter-end) maps to the quarter it REPORTS on, not the
    quarter it was FILED in. Format of an_dt is not fully verified
    against live data - falls back to the raw string as a dedup key
    (still functions, just less readable) rather than raising."""
    from datetime import datetime, timedelta
    if not an_dt:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(an_dt.strip()[:len(fmt) + 2], fmt)
            break
        except Exception:
            dt = None
    if dt is None:
        return an_dt.strip()[:20]
    dt -= timedelta(days=45)
    if dt.month in (4, 5, 6):
        q, fy = 1, dt.year + 1
    elif dt.month in (7, 8, 9):
        q, fy = 2, dt.year + 1
    elif dt.month in (10, 11, 12):
        q, fy = 3, dt.year + 1
    else:
        q, fy = 4, dt.year
    return f"Q{q}FY{str(fy)[2:]}"


def _build_results_prompt(subject, details, pdf_text, macro_context):'''
assert old1 in c, "imports block doesn't match - paste me lines 1-27 of kaal_scorer.py"
c = c.replace(old1, new1)

old2 = '''            return {
                "symbol":          symbol,
                "subject":         subject,
                "score":           score,
                "tier":            tier,
                "skip":            score < SKIP_BELOW,
                "catalyst":        llm.get("catalyst_type", cat),
                "direction":       llm.get("direction", "BULLISH"),
                "key":             llm.get("key_detail", subject[:80]),
                "reason":          llm.get("reason", "") + liquidity_note,
                "macro_note":      llm.get("macro_impact", ""),
                "value_cr":        llm.get("deal_value_cr", 0),
                "pdf_read":        bool(pdf_text),
                "source":          source,
                "signal_sources":  [source],
                "an_dt":           ann.get("an_dt", "") if isinstance(ann, dict) else "",
                "event_type":      ann.get("event_type", "MOMENTUM_CATALYST") if isinstance(ann, dict) else "MOMENTUM_CATALYST",
            }'''
new2 = '''            pat_growth_pct = llm.get("pat_growth_pct") if is_results else None
            revenue_growth_pct = llm.get("revenue_growth_pct") if is_results else None
            if is_results and pat_growth_pct is not None and revenue_growth_pct is not None:
                an_dt_val = ann.get("an_dt", "") if isinstance(ann, dict) else ""
                quarter_label = _fiscal_quarter_label(an_dt_val)
                try:
                    record_result(symbol, quarter_label, pat_growth_pct, revenue_growth_pct)
                except Exception as e:
                    print(f"[SCORER] failed to record results history for {symbol}: {e}")

            return {
                "symbol":          symbol,
                "subject":         subject,
                "score":           score,
                "tier":            tier,
                "skip":            score < SKIP_BELOW,
                "catalyst":        llm.get("catalyst_type", cat),
                "direction":       llm.get("direction", "BULLISH"),
                "key":             llm.get("key_detail", subject[:80]),
                "reason":          llm.get("reason", "") + liquidity_note,
                "macro_note":      llm.get("macro_impact", ""),
                "value_cr":        llm.get("deal_value_cr", 0),
                "pdf_read":        bool(pdf_text),
                "source":          source,
                "signal_sources":  [source],
                "an_dt":           ann.get("an_dt", "") if isinstance(ann, dict) else "",
                "event_type":      ann.get("event_type", "MOMENTUM_CATALYST") if isinstance(ann, dict) else "MOMENTUM_CATALYST",
                "pat_growth_pct":       pat_growth_pct,
                "revenue_growth_pct":   revenue_growth_pct,
            }'''
assert old2 in c, "return-dict block doesn't match - paste me the block around the llm-success 'return {' in score_announcement"
c = c.replace(old2, new2)

open(f, "w").write(c)
print("patched kaal_scorer.py")
