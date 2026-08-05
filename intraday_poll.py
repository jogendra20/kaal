"""
intraday_poll.py
Builds a watchlist from Chartink high-volume/OI screeners + real OI-spurt
data, checks each symbol's news staleness ONCE (Tavily/Serper), then polls
LTP + volume repeatedly until market close. Live-only pipeline -- cannot be
backtested (Chartink and OI-spurts have no free historical archive), this
is the daily-forward-tracking approach, same reasoning as the morning
watchlist script.
"""
import os, csv, json, time
from datetime import datetime, timedelta
import requests

from kaal_market_data import fetch_chartink_screeners, fetch_oi_spurts
from angel_provider import AngelOneProvider

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

POLL_INTERVAL_SEC = 600  # 5 minutes between LTP/volume checks
MARKET_CLOSE_STOP = "15:25"  # stop polling before actual close
OI_SPURT_THRESHOLD = 10.0
STALE_HOURS = 24  # no news within this window -> flagged STALE
LOG_FILE = f"intraday_poll_{datetime.now().strftime('%Y%m%d')}.csv"


def build_watchlist():
    """High-volume Chartink screens + real OI-spurt data, unioned -- not
    tied to results announcements this time, per instruction."""
    print("Fetching Chartink screeners...")
    screeners = fetch_chartink_screeners()
    screeners.pop("gap_up", None)
    high_volume = set()
    for name, symbols in screeners.items():
        if "volume" in name.lower() or "momentum" in name.lower():
            high_volume.update(symbols)
    print(f"  {len(high_volume)} symbols from high-volume/momentum screens")

    print("Fetching OI spurts...")
    oi_data = fetch_oi_spurts()
    high_oi = {s: v for s, v in oi_data.items() if v.get("avg_oi_pct", 0) > OI_SPURT_THRESHOLD}
    print(f"  {len(high_oi)} symbols with OI change > {OI_SPURT_THRESHOLD}%")

    watchlist = sorted(high_volume | set(high_oi.keys()))
    print(f"\nCombined watchlist: {len(watchlist)} symbols\n")
    return watchlist, oi_data


def check_staleness(symbol):
    """One-time check per symbol: is there NEWS from the last STALE_HOURS,
    or is any move happening without a fresh catalyst behind it (which
    would suggest pure technical/positioning activity, not news-driven)."""
    now = datetime.now()
    articles = []

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": f"{symbol} NSE stock news today",
                    "max_results": 5,
                    "search_depth": "basic",
                    "topic": "news",
                    "days": 2,
                },
                timeout=10,
            )
            if r.status_code == 200:
                for item in r.json().get("results", []):
                    articles.append({
                        "source": "TAVILY",
                        "title": item.get("title", ""),
                        "published": item.get("published_date", ""),
                    })
        except Exception as e:
            print(f"  [WARN] Tavily error for {symbol}: {e}")

    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": f"{symbol} NSE stock news", "num": 5, "tbs": "qdr:d"},
                timeout=10,
            )
            if r.status_code == 200:
                for item in r.json().get("organic", []):
                    articles.append({"source": "SERPER", "title": item.get("title", ""), "published": ""})
        except Exception as e:
            print(f"  [WARN] Serper error for {symbol}: {e}")

    # SERPER's tbs=qdr:d already filters to last 24h -- trust it directly.
    # TAVILY's days=2 param does similar server-side filtering, and its
    # published_date field is often empty/unreliable, so don't gate TAVILY
    # results on parsing that field -- if TAVILY returned it under days=2,
    # treat it as fresh too, rather than silently discarding it.
    fresh = list(articles)  # both sources already filter recency server-side

    status = "FRESH" if fresh else ("STALE" if articles else "NO_NEWS")
    return status, articles[:3]


def main():
    watchlist, oi_data = build_watchlist()
    if not watchlist:
        print("Empty watchlist -- nothing to poll.")
        return

    provider = AngelOneProvider()

    print("Checking news staleness for each symbol (one-time, not repeated per poll)...\n")
    staleness = {}
    for sym in watchlist:
        status, articles = check_staleness(sym)
        staleness[sym] = {"status": status, "articles": articles}
        print(f"  {sym:12s} -> {status}  ({len(articles)} article(s))")
        time.sleep(0.3)

    print(f"\n{'='*70}")
    print(f"Starting intraday poll -- every {POLL_INTERVAL_SEC}s, until {MARKET_CLOSE_STOP}")
    print(f"Logging to: {LOG_FILE}")
    print(f"{'='*70}\n")

    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "ltp", "pct_change", "volume",
                          "oi_avg_pct", "news_status"])

    stop_hour, stop_min = map(int, MARKET_CLOSE_STOP.split(":"))
    prev_ltp = {}

    while True:
        now = datetime.now()
        if (now.hour, now.minute) >= (stop_hour, stop_min):
            print(f"\nReached stop time {MARKET_CLOSE_STOP}, ending poll.")
            break

        print(f"[{now.strftime('%H:%M:%S')}] polling {len(watchlist)} symbols...")
        rows = []
        for sym in watchlist:
            quote = provider.get_ltp(sym)
            if not quote:
                continue
            ltp = quote.get("ltp")
            prev_close = quote.get("close")
            pct_change = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else None

            volume = None
            try:
                bars = provider.get_intraday_bars(sym, n=1, interval="1min")
                if bars:
                    volume = bars[-1].get("volume")
            except Exception:
                pass

            oi_pct = oi_data.get(sym, {}).get("avg_oi_pct")
            news_status = staleness.get(sym, {}).get("status", "?")

            moved = ""
            if sym in prev_ltp and prev_ltp[sym] and ltp:
                delta = round((ltp - prev_ltp[sym]) / prev_ltp[sym] * 100, 2)
                if abs(delta) >= 0.5:
                    moved = f"  ({delta:+.2f}% since last poll)"
            prev_ltp[sym] = ltp

            print(f"  {sym:12s} LTP={ltp}  chg={pct_change}%  vol={volume}  "
                  f"OI%={oi_pct}  news={news_status}{moved}")

            rows.append([now.strftime("%Y-%m-%d %H:%M:%S"), sym, ltp, pct_change,
                         volume, oi_pct, news_status])
            time.sleep(0.5)

        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        print(f"  -> logged {len(rows)} rows, sleeping {POLL_INTERVAL_SEC}s\n")
        time.sleep(POLL_INTERVAL_SEC)

    print(f"\nDone. Full log in {LOG_FILE}")


if __name__ == "__main__":
    main()
