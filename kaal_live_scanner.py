"""
kaal_live_scanner.py
Combines global cues (VIX via fetch_macro_context), NSE announcements/
results, Chartink screeners, OI spurts, and news into one weighted score.
Prints CANDIDATE (not "Entry" -- see reasoning below) when a stock crosses
threshold, and sends a Telegram alert.

IMPORTANT, read before trusting any output this produces:
This composite score has NOT been backtested as a combined signal. Each
individual ingredient (OI spurt, screen membership, heavy news, delivery %)
has, at most, 1-2 days of informal overnight comparison behind it from this
week -- not a validated edge. This script is a LIVE OBSERVATION TOOL, not a
trading signal. The word "CANDIDATE" is used deliberately instead of "Entry"
-- an "Entry" label implies a decision has been validated, which it hasn't.
Change the label if you disagree, but do so knowingly.
"""
import os, csv, json, time
from datetime import datetime, timedelta
import requests

from kaal_market_data import fetch_chartink_screeners, fetch_oi_spurts
from kaal_sources import fetch_macro
from angel_provider import AngelOneProvider
import kaal_telegram
import yfinance as yf

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

RESULTS_KEYWORDS = ("financial result", "quarterly result", "outcome of board meeting")
KMP_KEYWORDS = ("resignation", "appointment of", "change in key managerial",
                "cfo", "chief financial officer", "managing director",
                "cessation of", "kmp")
LOOKBACK_HOURS = 24
POLL_INTERVAL_SEC = 900  # 15 min -- wider than the 5-min version that hit rate limits
MARKET_CLOSE_STOP = "15:25"

# Weighted scoring -- these weights are a starting guess, NOT calibrated
# against any backtest. Adjust freely; nothing here is sacred.
WEIGHTS = {
    "BIG_MOVE": 2, "SCREEN_CONFIRMED": 2, "OI_SPURT": 3,
    "WATCH_HEAVY_NEWS": 1, "HIGH_DELIVERY": 1, "KMP_CHANGE": 1,
}
SMALL_CAP_CEILING_CR = 20000  # your stated sweet-spot ceiling for 3x-move potential
_mcap_cache = {}  # market cap doesn't move intraday -- fetch once per session, not per poll
CANDIDATE_THRESHOLD = 4  # sum of weights needed to trigger a CANDIDATE alert
BIG_MOVE_PCT = 5.0
HIGH_VIX = 20.0   # above this, VIX regime note added to alert (not a hard block)

GREEN = "\033[92m"
RESET = "\033[0m"

ALREADY_ALERTED = set()  # avoid re-sending Telegram for the same symbol every poll cycle


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


def fetch_recent_results(session, universe):
    """FIXED: now actually checks an_dt, not just the (day-granularity)
    URL date params, which were never enough on their own to enforce a
    24h window -- this was silently letting week-old+ results through."""
    now = datetime.now()
    from_date = now - timedelta(hours=LOOKBACK_HOURS)
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
        an_dt_str = a.get("an_dt", "")
        try:
            an_dt = datetime.strptime(an_dt_str, "%d-%b-%Y %H:%M:%S")
        except Exception:
            continue
        if an_dt < from_date:
            continue  # the actual freshness check that was missing entirely
        symbol = a.get("symbol", "")
        if symbol not in universe or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def get_market_cap_cr(symbol):
    """Market cap in Rs crore, via yfinance (.NS suffix). Cached per run --
    doesn't change intraday. Returns None on failure rather than guessing."""
    if symbol in _mcap_cache:
        return _mcap_cache[symbol]
    try:
        t = yf.Ticker(f"{symbol}.NS")
        mcap = t.info.get("marketCap")
        mcap_cr = round(mcap / 1e7, 0) if mcap else None
        _mcap_cache[symbol] = mcap_cr
        return mcap_cr
    except Exception as e:
        print(f"  [WARN] market cap fetch failed for {symbol}: {e}")
        _mcap_cache[symbol] = None
        return None


def fetch_recent_kmp_changes(session, universe):
    """Same announcement pull as results, filtered to KMP/management-change
    keywords instead -- a distinct catalyst type your own manual research
    flagged (Krystal's 'stacked KMP+results') that RESULTS_KEYWORDS alone
    never would have caught."""
    now = datetime.now()
    from_date = now - timedelta(hours=LOOKBACK_HOURS)
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={now.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=20)
        anns = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[WARN] KMP announcement fetch failed: {e}")
        return set()
    out = set()
    for a in anns:
        if not isinstance(a, dict):
            continue
        subject = (a.get("desc") or a.get("subject") or "").lower()
        if not any(k in subject for k in KMP_KEYWORDS):
            continue
        an_dt_str = a.get("an_dt", "")
        try:
            an_dt = datetime.strptime(an_dt_str, "%d-%b-%Y %H:%M:%S")
        except Exception:
            continue
        if an_dt < from_date:
            continue
        symbol = a.get("symbol", "")
        if symbol in universe:
            out.add(symbol)
    return out


def check_news(symbol):
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
                articles = r.json().get("results", [])
        except Exception:
            pass
    return len(articles)


def build_watchlist(session, universe):
    print(f"Midcap universe: {len(universe)} symbols")

    screeners = fetch_chartink_screeners()
    screeners.pop("gap_up", None)
    high_volume = set()
    for name, symbols in screeners.items():
        high_volume.update(symbols)
    print(f"Screener symbols: {len(high_volume)}")

    oi_data = fetch_oi_spurts()

    results = fetch_recent_results(session, universe)
    print(f"Recent results (fresh, within {LOOKBACK_HOURS}h): {len(results)} -- {results}")

    kmp_changes = fetch_recent_kmp_changes(session, universe)
    print(f"Recent KMP/management changes (fresh): {len(kmp_changes)} -- {sorted(kmp_changes)}")

    # Watchlist for OBSERVATION stays broad (screener + results union).
    # But CANDIDATE eligibility -- and Telegram alerts -- now require the
    # symbol to be in `results` specifically. A stock with no fresh catalyst
    # can still be printed and watched, but can never fire a CANDIDATE alert
    # purely off stale technical/OI activity -- this is the direct fix for
    # GODFRYPHLP/NAM-INDIA/KEI firing on results that were 8-13 days old.
    watchlist = sorted(set(results) | (high_volume & universe))
    print(f"Combined watchlist (observation only): {len(watchlist)} symbols\n")

    news_counts = {}
    for sym in results:
        news_counts[sym] = check_news(sym)
        time.sleep(0.3)

    return watchlist, high_volume, oi_data, news_counts, set(results), kmp_changes


def score_symbol(sym, quote, high_volume, oi_data, news_counts, kmp_changes, deliv_pct=None):
    tags = []
    ltp_pct_change = None
    if quote and quote.get("close"):
        ltp_pct_change = round((quote["ltp"] - quote["close"]) / quote["close"] * 100, 2)
        if abs(ltp_pct_change) >= BIG_MOVE_PCT:
            tags.append("BIG_MOVE")
    if sym in high_volume:
        tags.append("SCREEN_CONFIRMED")
    oi = oi_data.get(sym)
    if oi and oi.get("avg_oi_pct", 0) > 10:
        tags.append("OI_SPURT")
    if news_counts.get(sym, 0) >= 3:
        tags.append("WATCH_HEAVY_NEWS")
    if deliv_pct and deliv_pct > 60:
        tags.append("HIGH_DELIVERY")
    if sym in kmp_changes:
        tags.append("KMP_CHANGE")

    mcap_cr = get_market_cap_cr(sym)
    size_tag = None
    if mcap_cr is not None:
        size_tag = "SMALL_CAP" if mcap_cr < SMALL_CAP_CEILING_CR else "LARGE_CAP"

    score = sum(WEIGHTS.get(t, 0) for t in tags)
    return score, tags, ltp_pct_change, mcap_cr, size_tag


def send_alert(sym, score, tags, ltp, pct_change, vix, mcap_cr, size_tag):
    vix_note = f"\n⚠️ VIX elevated ({vix:.1f}) -- higher regime risk" if vix and vix > HIGH_VIX else ""
    size_note = f" ({size_tag}, {mcap_cr} Cr)" if size_tag else " (mcap unavailable)"
    msg = (
        f"🟢 <b>CANDIDATE: {sym}</b>{size_note}\n"
        f"Score: {score} | LTP: {ltp} ({pct_change:+.2f}%)\n"
        f"Tags: {', '.join(tags)}\n"
        f"India VIX: {vix}{vix_note}\n\n"
        f"<i>Unvalidated composite signal -- observation only, not a trade call.</i>"
    )
    ok = kaal_telegram.send(msg)
    print(f"  [TG] {'sent' if ok else 'FAILED to send'} for {sym}")


def main():
    print(f"Live scanner starting -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Polling every {POLL_INTERVAL_SEC}s until {MARKET_CLOSE_STOP}\n")

    session = nse_session()
    provider = AngelOneProvider()

    universe = fetch_midcap_universe()
    watchlist, high_volume, oi_data, news_counts, fresh_results, kmp_changes = build_watchlist(session, universe)
    if not watchlist:
        print("Empty watchlist -- nothing to scan.")
        return

    stop_hour, stop_min = map(int, MARKET_CLOSE_STOP.split(":"))

    while True:
        now = datetime.now()
        if (now.hour, now.minute) >= (stop_hour, stop_min):
            print(f"\nReached stop time {MARKET_CLOSE_STOP}, ending scan.")
            break

        macro = fetch_macro()
        vix = macro.get("vix")
        print(f"[{now.strftime('%H:%M:%S')}] VIX={vix} | scanning {len(watchlist)} symbols...")

        for sym in watchlist:
            quote = provider.get_ltp(sym)
            if not quote:
                continue
            score, tags, pct_change, mcap_cr, size_tag = score_symbol(sym, quote, high_volume, oi_data, news_counts, kmp_changes)
            has_fresh_catalyst = sym in fresh_results

            if score >= CANDIDATE_THRESHOLD and has_fresh_catalyst:
                print(f"  {GREEN}{sym:12s} CANDIDATE  score={score}  "
                      f"LTP={quote['ltp']} ({pct_change:+.2f}%)  tags={tags}  "
                      f"mcap={mcap_cr}Cr [{size_tag}]{RESET}")
                if sym not in ALREADY_ALERTED:
                    send_alert(sym, score, tags, quote["ltp"], pct_change, vix, mcap_cr, size_tag)
                    ALREADY_ALERTED.add(sym)
            elif score >= CANDIDATE_THRESHOLD and not has_fresh_catalyst:
                print(f"  {sym:12s} score={score}  LTP={quote['ltp']} ({pct_change:+.2f}%)  "
                      f"tags={tags}  mcap={mcap_cr}Cr [{size_tag}]  [no fresh catalyst -- suppressed]")
            else:
                print(f"  {sym:12s} score={score}  LTP={quote['ltp']} ({pct_change:+.2f}%)  "
                      f"tags={tags}  mcap={mcap_cr}Cr [{size_tag}]")

            time.sleep(0.5)

        print(f"  -> sleeping {POLL_INTERVAL_SEC}s\n")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
