"""
weekend_results_momentum.py (v2)
Mid-cap only. Quarterly results after Friday 3:20 PM, cross-checked with
Tavily/Serper news, Chartink screeners (momentum/52w_high/high_volume_breakout
-- gap_up dropped per instruction), real OI-change via fetch_oi_spurts(), and
live Angel One LTP. Saves a dated snapshot so an evening/next-day run can
check what actually happened to today's picks -- that comparison, repeated
over time, is the only real way to trust this list, not any single run.
"""
import os, json
import requests
from datetime import datetime, timedelta

from kaal_market_data import fetch_chartink_screeners, fetch_oi_spurts
from angel_provider import AngelOneProvider

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

RESULTS_KEYWORDS = ("financial result", "quarterly result", "outcome of board meeting")
BIG_MOVE_THRESHOLD = 5.0
HEAVY_NEWS_THRESHOLD = 3
SNAPSHOT_FILE = f"watchlist_snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.json"


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


def last_friday_320pm(now=None):
    now = now or datetime.now()
    days_since_friday = (now.weekday() - 4) % 7
    friday = now - timedelta(days=days_since_friday)
    return friday.replace(hour=15, minute=20, second=0, microsecond=0)


def fetch_midcap_universe():
    import csv
    url = "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[WARN] midcap list fetch failed: {r.status_code}")
            return set()
        reader = csv.DictReader(r.text.splitlines())
        syms = {(row.get("Symbol") or row.get("SYMBOL") or "").strip() for row in reader}
        syms.discard("")
        return syms
    except Exception as e:
        print(f"[WARN] midcap list exception: {e}")
        return set()


def fetch_all_recent_announcements(session, from_date, to_date, universe):
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={to_date.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=20)
        anns = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[WARN] announcement fetch failed: {e}")
        return []

    seen_symbols = set()
    out = []
    for a in anns:
        if not isinstance(a, dict):
            continue
        subject = (a.get("desc") or a.get("subject") or "").lower()
        if not any(k in subject for k in RESULTS_KEYWORDS):
            continue
        symbol = a.get("symbol", "")
        if symbol not in universe:
            continue
        if symbol in seen_symbols:
            continue  # dedupe -- keep only the first (most relevant) filing per symbol
        an_dt_str = a.get("an_dt", "")
        try:
            an_dt = datetime.strptime(an_dt_str, "%d-%b-%Y %H:%M:%S")
        except Exception:
            continue
        if an_dt < from_date:
            continue
        seen_symbols.add(symbol)
        out.append({"symbol": symbol, "an_dt": an_dt, "subject": a.get("desc") or a.get("subject")})
    return out


def confirm_via_news(symbol):
    articles = []
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": f"{symbol} NSE quarterly results Q1 FY27",
                    "max_results": 5,
                    "search_depth": "basic",
                    "topic": "news",
                    "days": 3,
                },
                timeout=10,
            )
            if r.status_code == 200:
                for item in r.json().get("results", []):
                    articles.append({"source": "TAVILY", "title": item.get("title", "")})
        except Exception as e:
            print(f"  [WARN] Tavily error for {symbol}: {e}")

    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key and len(articles) < 3:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": f"{symbol} NSE quarterly results", "num": 5},
                timeout=10,
            )
            if r.status_code == 200:
                for item in r.json().get("organic", []):
                    articles.append({"source": "SERPER", "title": item.get("title", "")})
        except Exception as e:
            print(f"  [WARN] Serper error for {symbol}: {e}")

    return articles


def main():
    now = datetime.now()
    cutoff = last_friday_320pm(now)
    print(f"Now: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Scanning results filed after: {cutoff.strftime('%Y-%m-%d %H:%M')} (last Friday 3:20 PM)")
    print(f"Universe: NIFTY MIDCAP 150 only\n")

    session = nse_session()
    universe = fetch_midcap_universe()
    print(f"Midcap universe: {len(universe)} symbols\n")

    print("Fetching Chartink screeners (momentum, 52w_high, high_volume_breakout -- gap_up excluded)...")
    screeners = fetch_chartink_screeners()
    screeners.pop("gap_up", None)
    high_volume_symbols = set()
    for name, symbols in screeners.items():
        high_volume_symbols.update(symbols)
    print(f"  {len(high_volume_symbols)} unique symbols across {len(screeners)} screener(s)\n")

    print("Fetching OI spurts (real OI-change data, not a PCR snapshot)...")
    oi_data = fetch_oi_spurts()
    print()

    print("Fetching NSE results announcements since the cutoff, midcap only...")
    results = fetch_all_recent_announcements(session, cutoff, now, universe)
    print(f"  {len(results)} unique midcap results filings found\n")

    if not results:
        print("No midcap results filings found in this window.")
        return

    provider = AngelOneProvider()
    output = []

    print("=" * 70)
    print("CHECKING EACH RESULT")
    print("=" * 70 + "\n")

    for r in results:
        symbol = r["symbol"]
        print(f"{symbol} (filed {r['an_dt'].strftime('%Y-%m-%d %H:%M')})...")

        in_screen = symbol in high_volume_symbols
        news = confirm_via_news(symbol)
        oi = oi_data.get(symbol)

        quote = provider.get_ltp(symbol)
        ltp_pct_change = None
        if quote and quote.get("close"):
            ltp_pct_change = round((quote["ltp"] - quote["close"]) / quote["close"] * 100, 2)

        is_big_move = ltp_pct_change is not None and abs(ltp_pct_change) >= BIG_MOVE_THRESHOLD
        is_heavy_news = len(news) >= HEAVY_NEWS_THRESHOLD

        tags = []
        if is_big_move:
            tags.append("BIG_MOVE")
        if in_screen:
            tags.append("SCREEN_CONFIRMED")
        if is_heavy_news:
            tags.append("WATCH_HEAVY_NEWS")
        if oi and oi.get("avg_oi_pct", 0) > 10:
            tags.append("OI_SPURT")

        verdict = " + ".join(tags) if tags else "quiet"

        entry = {
            "symbol": symbol,
            "filed_at": r["an_dt"].strftime("%Y-%m-%d %H:%M"),
            "subject": r["subject"],
            "ltp": quote.get("ltp") if quote else None,
            "ltp_pct_change": ltp_pct_change,
            "in_high_volume_screen": in_screen,
            "news_count": len(news),
            "news_titles": [n["title"] for n in news][:3],
            "oi_change": oi.get("oi_change") if oi else None,
            "oi_avg_pct": oi.get("avg_oi_pct") if oi else None,
            "tags": tags,
            "verdict": verdict,
        }
        output.append(entry)

        print(f"  LTP={entry['ltp']}  change={ltp_pct_change}%  screen={in_screen}  "
              f"news={len(news)}  OI_change={entry['oi_change']}  -> {verdict}\n")

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump({"generated_at": now.strftime("%Y-%m-%d %H:%M"), "picks": output}, f, indent=2)

    print("=" * 70)
    print("FINAL LIST")
    print("=" * 70 + "\n")

    flagged = [e for e in output if e["tags"]]
    quiet = [e for e in output if not e["tags"]]

    print(f"FLAGGED FOR OBSERVATION ({len(flagged)}):")
    for e in sorted(flagged, key=lambda x: -(x["ltp_pct_change"] or 0)):
        print(f"  {e['symbol']:12s} LTP={e['ltp']} ({e['ltp_pct_change']}%)  "
              f"news={e['news_count']}  OI_change={e['oi_change']}  -> {e['verdict']}")

    print(f"\nQUIET ({len(quiet)}): {[e['symbol'] for e in quiet]}")

    print(f"\nSnapshot saved: {SNAPSHOT_FILE}")
    print("Run this again at end of day / tomorrow morning and compare LTP moves")
    print("against these tags -- that comparison, repeated over multiple days,")
    print("is what actually tells you whether these tags mean anything.")


if __name__ == "__main__":
    main()
