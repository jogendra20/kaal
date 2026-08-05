"""
daily_snapshot.py
Generalized version of weekend_results_momentum.py -- works for any evening
or morning run, not just after-Friday. Skips news re-checks for symbols
already checked in the most recent prior snapshot, to conserve Tavily/
Serper quota after today's burnout. Adds delivery % when run after market
close (available then; NOT available intraday, same limitation flagged
before).
"""
import os, json, csv, glob
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
LOOKBACK_HOURS = 20  # since last evening/morning run -- adjust if you run at odd times
SNAPSHOT_FILE = f"watchlist_snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.json"


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


def fetch_midcap_universe():
    url = "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            return set()
        reader = csv.DictReader(r.text.splitlines())
        syms = {(row.get("Symbol") or row.get("SYMBOL") or "").strip() for row in reader}
        syms.discard("")
        return syms
    except Exception:
        return set()


def fetch_recent_results(session, universe, hours_back=LOOKBACK_HOURS):
    now = datetime.now()
    from_date = now - timedelta(hours=hours_back)
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={now.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=20)
        anns = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[WARN] announcement fetch failed: {e}")
        return []

    seen, out = set(), []
    for a in anns:
        if not isinstance(a, dict):
            continue
        subject = (a.get("desc") or a.get("subject") or "").lower()
        if not any(k in subject for k in RESULTS_KEYWORDS):
            continue
        symbol = a.get("symbol", "")
        if symbol not in universe or symbol in seen:
            continue
        an_dt_str = a.get("an_dt", "")
        try:
            an_dt = datetime.strptime(an_dt_str, "%d-%b-%Y %H:%M:%S")
        except Exception:
            continue
        if an_dt < from_date:
            continue
        seen.add(symbol)
        out.append({"symbol": symbol, "an_dt": an_dt, "subject": a.get("desc") or a.get("subject")})
    return out


def get_deliv_pct(symbol):
    """Delivery % -- only meaningful/available after ~6:30 PM once NSE
    publishes it. Returns None harmlessly if run before that, or before
    the file for today exists yet."""
    date_str = datetime.now().strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        reader = csv.DictReader(r.text.splitlines())
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("SYMBOL") == symbol and row.get("SERIES") == "EQ":
                dp = row.get("DELIV_PER", "-").strip()
                return float(dp) if dp != "-" else None
        return None
    except Exception:
        return None


def load_previously_checked_symbols():
    """Symbols already news-checked in the most recent prior snapshot --
    skip re-checking these today to conserve Tavily/Serper quota."""
    files = sorted(glob.glob("watchlist_snapshot_*.json"))
    if not files:
        return {}
    try:
        with open(files[-1]) as f:
            data = json.load(f)
        return {p["symbol"]: p.get("news_count", 0) for p in data.get("picks", [])}
    except Exception:
        return {}


def confirm_via_news(symbol):
    articles = []
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": f"{symbol} NSE quarterly results",
                      "max_results": 5, "search_depth": "basic", "topic": "news", "days": 2},
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
                json={"q": f"{symbol} NSE quarterly results", "num": 5}, timeout=10,
            )
            if r.status_code == 200:
                for item in r.json().get("organic", []):
                    articles.append({"source": "SERPER", "title": item.get("title", "")})
        except Exception as e:
            print(f"  [WARN] Serper error for {symbol}: {e}")
    return articles


def main():
    now = datetime.now()
    is_evening = now.hour >= 16
    print(f"Daily snapshot ({'EVENING' if is_evening else 'MORNING'}) -- {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Looking back {LOOKBACK_HOURS}h for midcap results\n")

    session = nse_session()
    universe = fetch_midcap_universe()
    print(f"Midcap universe: {len(universe)} symbols\n")

    print("Fetching Chartink screeners (gap_up excluded)...")
    screeners = fetch_chartink_screeners()
    screeners.pop("gap_up", None)
    high_volume_symbols = set()
    for name, symbols in screeners.items():
        high_volume_symbols.update(symbols)
    print(f"  {len(high_volume_symbols)} symbols across {len(screeners)} screener(s)\n")

    print("Fetching OI spurts...")
    oi_data = fetch_oi_spurts()
    print()

    print("Fetching recent midcap results...")
    results = fetch_recent_results(session, universe)
    print(f"  {len(results)} results filings found\n")

    if not results:
        print("No midcap results filings in this window.")
        return

    already_checked = load_previously_checked_symbols()
    print(f"{len(already_checked)} symbols already news-checked in the last snapshot -- skipping those.\n")

    provider = AngelOneProvider()
    output = []

    for r in results:
        symbol = r["symbol"]
        print(f"{symbol} (filed {r['an_dt'].strftime('%Y-%m-%d %H:%M')})...")

        in_screen = symbol in high_volume_symbols
        oi = oi_data.get(symbol)

        if symbol in already_checked:
            news_count = already_checked[symbol]
            print(f"  (news skipped -- already checked last run, had {news_count})")
        else:
            news = confirm_via_news(symbol)
            news_count = len(news)

        quote = provider.get_ltp(symbol)
        ltp_pct_change = None
        if quote and quote.get("close"):
            ltp_pct_change = round((quote["ltp"] - quote["close"]) / quote["close"] * 100, 2)

        deliv_pct = get_deliv_pct(symbol) if is_evening else None

        tags = []
        if ltp_pct_change is not None and abs(ltp_pct_change) >= BIG_MOVE_THRESHOLD:
            tags.append("BIG_MOVE")
        if in_screen:
            tags.append("SCREEN_CONFIRMED")
        if news_count >= 3:
            tags.append("WATCH_HEAVY_NEWS")
        if oi and oi.get("avg_oi_pct", 0) > 10:
            tags.append("OI_SPURT")
        if deliv_pct and deliv_pct > 60:
            tags.append("HIGH_DELIVERY")

        entry = {
            "symbol": symbol, "filed_at": r["an_dt"].strftime("%Y-%m-%d %H:%M"),
            "ltp": quote.get("ltp") if quote else None, "ltp_pct_change": ltp_pct_change,
            "in_high_volume_screen": in_screen, "news_count": news_count,
            "oi_change": oi.get("oi_change") if oi else None,
            "oi_avg_pct": oi.get("avg_oi_pct") if oi else None,
            "deliv_pct": deliv_pct, "tags": tags,
            "verdict": " + ".join(tags) if tags else "quiet",
        }
        output.append(entry)
        print(f"  LTP={entry['ltp']}  change={ltp_pct_change}%  screen={in_screen}  "
              f"news={news_count}  OI%={entry['oi_avg_pct']}  deliv%={deliv_pct}  -> {entry['verdict']}\n")

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump({"generated_at": now.strftime("%Y-%m-%d %H:%M"),
                    "session": "EVENING" if is_evening else "MORNING", "picks": output}, f, indent=2)

    print(f"Snapshot saved: {SNAPSHOT_FILE}")
    print("Run compare_snapshots.py after your next run to see overnight moves.")


if __name__ == "__main__":
    main()
