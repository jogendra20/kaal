"""
kaal_fy27_news.py
Standalone FY27 news & announcement gatherer.

Takes announcement/news lists KAAL already fetches (fetch_nse_announcements,
fetch_news - no new network calls here) and filters them down to items
genuinely about FY27, checks each one's freshness, and produces one
consolidated report.

Deterministic pattern matching, no LLM - this is a relevance filter,
not a judgment call about materiality or novelty.

KNOWN LIMITATION: pure pattern matching cannot tell "FY27 is the real
subject" apart from "FY27 mentioned in passing" (e.g. a historical
reference like "the company has grown since FY27"). This will
occasionally over-report, not under-report - accepted tradeoff for
staying deterministic rather than adding an LLM call per article.
"""
import re
from datetime import datetime

from kaal_scorer import check_results_freshness

FY27_PATTERNS = [
    r'\bFY\s*-?\s*27\b',
    r'\bFY\s*2026\s*-\s*27\b',
    r'\bFY\s*26\s*-\s*27\b',
    r'\bFinancial\s+Year\s+2026\s*-\s*27\b',
    r'\b2026\s*-\s*27\b',
    r'\bQ[1-4]\s*FY\s*-?\s*27\b',
]
_FY27_REGEX = re.compile("|".join(FY27_PATTERNS), re.IGNORECASE)


def is_fy27_relevant(text: str) -> bool:
    if not text:
        return False
    return bool(_FY27_REGEX.search(text))


def gather_fy27_items(announcements: list, news: list) -> list:
    """
    announcements: from fetch_nse_announcements()
    news: from fetch_news()
    Returns a list of {source, symbol, headline, an_dt, freshness} dicts.
    News articles get freshness UNKNOWN, not guessed - they don't carry
    a reliable per-company filing date the way NSE announcements do.
    """
    results = []

    for ann in announcements or []:
        subject = ann.get("subject", "") if isinstance(ann, dict) else ""
        details = ann.get("details", "") if isinstance(ann, dict) else ""
        combined = f"{subject} {details}"
        if not is_fy27_relevant(combined):
            continue
        an_dt = ann.get("an_dt", "") if isinstance(ann, dict) else ""
        freshness = check_results_freshness(an_dt)
        results.append({
            "source": "NSE_ANNOUNCEMENT",
            "symbol": ann.get("symbol", "") if isinstance(ann, dict) else "",
            "headline": subject or details[:100],
            "an_dt": an_dt,
            "freshness": freshness,
        })

    for item in news or []:
        title = item.get("title", "") if isinstance(item, dict) else ""
        summary = item.get("summary", item.get("description", "")) if isinstance(item, dict) else ""
        combined = f"{title} {summary}"
        if not is_fy27_relevant(combined):
            continue
        results.append({
            "source": "NEWS",
            "symbol": item.get("symbol", "") if isinstance(item, dict) else "",
            "headline": title or summary[:100],
            "an_dt": item.get("published", item.get("date", "")) if isinstance(item, dict) else "",
            "freshness": {"status": "UNKNOWN", "days_old": None,
                          "reason": "news articles don't carry a reliable filing date - not guessed"},
        })

    return results


def build_fy27_report(items: list) -> str:
    if not items:
        return "No FY27-relevant announcements or news found today."

    def sort_key(item):
        d = item["freshness"].get("days_old")
        return d if d is not None else 9999

    items = sorted(items, key=sort_key)

    lines = [f"{'='*60}", f"FY27 NEWS REPORT — {len(items)} item(s) found", f"{'='*60}"]
    for item in items:
        f = item["freshness"]
        status_str = f["status"]
        if f["days_old"] is not None:
            status_str += f" ({f['days_old']}d old)"
        symbol_str = f"[{item['symbol']}] " if item["symbol"] else ""
        lines.append(f"\n{symbol_str}({item['source']}) — {status_str}")
        lines.append(f"  {item['headline']}")
    lines.append(f"\n{'-'*60}")
    return "\n".join(lines)
