import io, csv, json, time, os, re, requests
from datetime import datetime, timedelta
from getpass import getpass

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or getpass("Groq API key: ")

def fetch_index_constituents(list_url):
    """NSE publishes static constituent-list CSVs on the archives domain —
    same domain already proven reliable for bhavcopy, no session/cookie
    handshake needed, unlike the live index-quote API that 404'd."""
    try:
        r = requests.get(list_url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  [WARN] constituent list fetch failed: {r.status_code} for {list_url}")
            return []
        reader = csv.DictReader(r.text.splitlines())
        syms = []
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            sym = row.get("Symbol") or row.get("SYMBOL")
            if sym:
                syms.append(sym)
        return syms
    except Exception as e:
        print(f"  [WARN] constituent list exception: {e}")
        return []


def fetch_liquid_universe(min_turnover_cr=50, per_index_top_n=15):
    """Pulls Nifty Midcap 150 + Smallcap 250 constituent lists (static CSVs),
    checks each one's turnover from a recent bhavcopy day, and keeps the top
    N most liquid names per index that clear min_turnover_cr. Two-step
    (constituent list, then turnover lookup) instead of one live API call,
    since the combined live-quote endpoint returned 404 for every index
    tried, including NIFTY 50 itself."""
    index_urls = {
        "NIFTY MIDCAP 150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        "NIFTY SMALLCAP 250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    }

    # find a recent trading day with real bhavcopy data
    probe_date = datetime.now() - timedelta(days=3)
    day_data = {}
    for _ in range(7):
        day_data = get_bhavcopy_day(probe_date)
        if day_data:
            break
        probe_date -= timedelta(days=1)
    if not day_data:
        print("  [WARN] could not find a recent bhavcopy day with data — universe will be empty")
        return []
    print(f"  using turnover data from {probe_date.strftime('%Y-%m-%d')}")

    universe = []
    for idx_name, url in index_urls.items():
        syms = fetch_index_constituents(url)
        if not syms:
            print(f"  {idx_name}: constituent list fetch failed, skipping this index")
            continue
        ranked = []
        for sym in syms:
            bar = day_data.get(sym)
            if not bar:
                continue
            turnover_cr = bar["turnover_lacs"] / 100.0  # lacs -> crores
            if turnover_cr >= min_turnover_cr:
                ranked.append((sym, turnover_cr))
        ranked.sort(key=lambda x: -x[1])
        top = ranked[:per_index_top_n]
        if top:
            print(f"  {idx_name}: {len(top)} liquid names (of {len(syms)} constituents), "
                  f"turnover range {top[-1][1]:.0f}-{top[0][1]:.0f} Cr")
        else:
            print(f"  {idx_name}: 0 names cleared the {min_turnover_cr} Cr bar")
        universe.extend(s for s, _ in top)
    return sorted(set(universe))


UNIVERSE = None  # built lazily in main() — needs nse_session(), defined later in this file

LOOKBACK_DAYS = 200
PRICED_IN_THRESHOLD = 8.0
YOY_PROFIT_BEAT_PCT = 15.0
GROQ_MODEL = "qwen/qwen3.6-27b"
CHECKPOINT_FILE = "fy27_backtest_results_v2_trendbeat.json"

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}


def nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=15)
    return s


def fetch_results_announcements(session, symbol, from_date, to_date):
    url = (f"https://www.nseindia.com/api/corporate-announcements"
           f"?index=equities&symbol={symbol}"
           f"&from_date={from_date.strftime('%d-%m-%Y')}"
           f"&to_date={to_date.strftime('%d-%m-%Y')}")
    try:
        r = session.get(url, timeout=15)
        anns = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [WARN] announcement fetch failed for {symbol}: {e}")
        return []
    keywords = ("financial result", "quarterly result", "outcome of board meeting")
    out = []
    for a in anns:
        if not isinstance(a, dict):
            continue
        subject = (a.get("desc") or a.get("subject") or "").lower()
        if any(k in subject for k in keywords):
            out.append(a)
    return out


def download_pdf_text(url, max_chars=4000, top_pages=3):
    if not url or url == "-":
        return ""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=NSE_HEADERS, timeout=40)
            break
        except requests.exceptions.Timeout:
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"  [WARN] PDF fetch timed out twice, skipping")
            return ""
        except Exception as e:
            print(f"  [WARN] PDF fetch failed: {e}")
            return ""
    try:
        if r.status_code != 200:
            return ""
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(r.content))
        scored = []
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            digit_count = sum(c.isdigit() for c in t)
            score = digit_count + (500 if "Particulars" in t else 0)
            scored.append((i, score, t))
        top = sorted(scored, key=lambda x: -x[1])[:top_pages]
        top_in_order = sorted(top, key=lambda x: x[0])
        combined = "\n\n---PAGE BREAK---\n\n".join(t for _, _, t in top_in_order)
        return combined[:max_chars]
    except Exception as e:
        print(f"  [WARN] PDF extract failed: {e}")
        return ""


_bhav_cache = {}

def get_bhavcopy_day(d):
    key = d.strftime("%Y-%m-%d")
    if key in _bhav_cache:
        return _bhav_cache[key]
    date_str = d.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        if r.status_code != 200:
            _bhav_cache[key] = {}
            return {}
        reader = csv.DictReader(r.text.splitlines())
        result = {}
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("SERIES") != "EQ":
                continue
            sym = row.get("SYMBOL", "")
            if not sym:
                continue
            result[sym] = {
                "open": float(row.get("OPEN_PRICE", 0) or 0),
                "close": float(row.get("CLOSE_PRICE", 0) or 0),
                "turnover_lacs": float(row.get("TURNOVER_LACS", 0) or 0),
            }
        _bhav_cache[key] = result
        return result
    except Exception:
        _bhav_cache[key] = {}
        return {}


def nearby_trading_days(center, back=0, fwd=0):
    days = []
    d = center - timedelta(days=back * 2 + 5)
    while d <= center + timedelta(days=fwd * 2 + 5):
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def pre_result_move_pct(symbol, result_date, n=5):
    days = [d for d in nearby_trading_days(result_date, back=n) if d < result_date]
    closes = []
    for d in days[-(n + 2):]:
        bar = get_bhavcopy_day(d).get(symbol)
        if bar and bar["close"]:
            closes.append(bar["close"])
    if len(closes) < 2:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100


def forward_returns(symbol, result_date, index_symbol="NIFTY 50"):
    days = [d for d in nearby_trading_days(result_date, fwd=6) if d > result_date]
    stock_bars = []
    for d in days[:6]:
        sb = get_bhavcopy_day(d).get(symbol)
        if sb and sb["open"]:
            stock_bars.append(sb)
        if len(stock_bars) >= 3:
            break
    if not stock_bars:
        return None
    next_oc = (stock_bars[0]["close"] - stock_bars[0]["open"]) / stock_bars[0]["open"] * 100
    three_day = None
    if len(stock_bars) >= 3:
        three_day = (stock_bars[2]["close"] - stock_bars[0]["open"]) / stock_bars[0]["open"] * 100
    return {"next_day_oc": round(next_oc, 2),
            "three_day_cc": round(three_day, 2) if three_day is not None else None}


def build_checklist_prompt(symbol, pdf_text, pre_move_pct):
    priced_in_note = (
        f"Stock moved {pre_move_pct:+.1f}% in the 5 trading days before this result "
        f"({'ALREADY TRIGGERS Priced-In skip, >|8%|' if pre_move_pct is not None and abs(pre_move_pct) > PRICED_IN_THRESHOLD else 'within normal range'})."
        if pre_move_pct is not None else "Pre-result price move unavailable."
    )
    return f"""You are a disciplined intraday analyst applying a strict results checklist.
Extract ONLY numbers actually present in the filing text below — never invent figures.

SYMBOL: {symbol}
{priced_in_note}

FILING TEXT (raw extract, may be messy):
---
{pdf_text[:4000]}
---

No analyst consensus data exists here, so wherever the checklist would normally
compare to analyst estimates, use this instead: "BEAT" = revenue grew YoY, net
profit grew YoY, operating margin is stable or expanding, AND the growth looks
like a genuine acceleration for THIS company rather than its normal run-rate.
To judge that: if the filing shows the immediately preceding quarter's
revenue/profit (most NSE results tables do, as a third column alongside
current-quarter and year-ago figures), compare current YoY growth against what
the sequential (quarter-on-quarter) trend implies. Fast-growing companies often
post large YoY numbers every quarter as their normal cadence — that is NOT a
beat, it is business as usual, and should not trigger ENTER_LONG on its own.
A genuine beat looks like growth that is unusually strong even against this
company's own recent trajectory, or explicit acceleration language in
management commentary. If no preceding-quarter figure is available to compare
against, fall back to requiring net profit growth >={YOY_PROFIT_BEAT_PCT}% YoY,
but note in your reasoning that this is the weaker fallback test, not the
trend-based one.
Base all comparisons only on figures actually stated in the text.

PHASE 1 — SKIP if ANY true:
1. Priced-In: stock already moved >{PRICED_IN_THRESHOLD}% in the 5 days before this result (see note above).
2. Mixed Bag: revenue grew but profit fell, or vice versa.
3. Red Flag: profit driven by exceptional/one-time items, auditor qualification, or promoter pledging increase mentioned.
4. Poor Guidance: management commentary is flat, cautious, or negative despite decent numbers.

PHASE 2 — ENTER LONG only if ALL true (and Phase 1 didn't trigger SKIP):
5. Revenue and profit both grew YoY, margin stable/expanding (the "BEAT" definition above).
6. Profit growth is a significant beat (>={YOY_PROFIT_BEAT_PCT}%).
7. Guidance is positive, or new order wins / capacity expansion mentioned.

PHASE 3 — ENTER SHORT only if Phase 1 has no red-flag/mixed-bag trigger but:
8. Revenue AND profit both missed prior year significantly (>10% decline), AND guidance is explicitly negative.

Respond with ONLY this JSON, no other text:
{{"decision": "ENTER_LONG" | "ENTER_SHORT" | "SKIP",
  "revenue_yoy_pct": <number or null>,
  "profit_yoy_pct": <number or null>,
  "beat_basis": "trend" | "fallback_threshold" | "not_applicable",
  "reasoning": "<1-2 sentences citing the specific numbers/phrases that drove this>"}}
"""


def _parse_reset(s):
    m = re.match(r"(?:(\d+)m)?([\d.]+)s", s or "")
    if not m:
        return 20.0
    mins = float(m.group(1) or 0)
    secs = float(m.group(2) or 0)
    return mins * 60 + secs


def _parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _call_mistral(prompt):
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1200,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"]["content"]
            return _parse_json(text)
        print(f"  [WARN] Mistral {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"  [WARN] Mistral exception: {e}")
    return None


def _call_groq_key(key, prompt, label):
    if not key:
        return None, False
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 3000,
                "reasoning_format": "hidden",
            },
            timeout=30,
        )
        remaining = r.headers.get("x-ratelimit-remaining-tokens")
        if remaining is not None and int(remaining) < 1000:
            print(f"  [PACE] {label} low on budget ({remaining} tokens left)")
        if r.status_code == 429:
            return None, True
        if r.status_code != 200:
            print(f"  [WARN] {label} error {r.status_code}: {r.text[:150]}")
            return None, False
        choice = r.json()["choices"][0]
        content = choice["message"]["content"]
        if choice.get("finish_reason") == "length" and not content.strip():
            print(f"  [WARN] {label} hit max_tokens with zero output — reasoning ate the budget")
            return None, False
        verdict = _parse_json(content)
        if verdict is None:
            print(f"  [WARN] {label} no JSON in response: {content[:150]!r}")
        return verdict, False
    except Exception as e:
        print(f"  [WARN] {label} exception: {e}")
        return None, False


def call_groq_with_retry(prompt, max_attempts=4):
    """Mistral first, then GROQ_API_KEY_2, then GROQ_API_KEY — spreads load
    across two Groq keys plus a separate provider instead of hammering one
    key's per-minute token budget."""
    result = _call_mistral(prompt)
    if result:
        return result

    key2 = os.environ.get("GROQ_API_KEY_2", "")
    key1 = os.environ.get("GROQ_API_KEY", "") or GROQ_API_KEY

    for attempt in range(1, max_attempts + 1):
        rl2 = False
        if key2:
            verdict, rl2 = _call_groq_key(key2, prompt, "Groq2")
            if verdict:
                return verdict

        verdict, rl1 = _call_groq_key(key1, prompt, "Groq1")
        if verdict:
            return verdict

        if rl1 or rl2:
            wait = min(20.0, 5.0 * attempt)
            print(f"  [WAIT] rate limited, sleeping {wait}s (attempt {attempt}/{max_attempts})")
            time.sleep(wait)
        else:
            break

    print("  [WARN] gave up after retries, treating as no verdict")
    return None


def save_checkpoint(results):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(results, f, indent=2)


def main():
    global UNIVERSE
    UNIVERSE = fetch_liquid_universe()
    print(f"Screened universe ({len(UNIVERSE)} liquid mid/small-caps): {UNIVERSE}")

    session = nse_session()
    to_date = datetime.now() - timedelta(days=3)
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)

    results = []
    seen = set()

    for i, symbol in enumerate(UNIVERSE, 1):
        print(f"[{i}/{len(UNIVERSE)}] {symbol}...")
        anns = fetch_results_announcements(session, symbol, from_date, to_date)
        time.sleep(0.5)
        if not anns:
            print("  -> no results filings found in window")
            continue

        for a in anns:
            an_dt_str = a.get("an_dt", "")
            try:
                result_date = datetime.strptime(an_dt_str.split()[0], "%d-%b-%Y")
            except Exception:
                continue

            key = (symbol, result_date.strftime("%Y-%m-%d"))
            if key in seen:
                continue
            seen.add(key)

            pdf_url = a.get("attchmntFile") or a.get("pdfLink") or ""
            if not pdf_url:
                continue
            pdf_text = download_pdf_text(pdf_url)
            if len(pdf_text) < 200:
                print(f"  -> {result_date.date()} PDF text too short, skipping")
                continue

            pre_move = pre_result_move_pct(symbol, result_date)
            prompt = build_checklist_prompt(symbol, pdf_text, pre_move)
            verdict = call_groq_with_retry(prompt)
            if not verdict or verdict.get("decision") not in ("ENTER_LONG", "ENTER_SHORT", "SKIP"):
                print(f"  -> {result_date.date()} no usable verdict")
                continue

            fwd = forward_returns(symbol, result_date)
            if not fwd:
                print(f"  -> {result_date.date()} no forward price data")
                continue

            results.append({
                "symbol": symbol, "date": result_date.strftime("%Y-%m-%d"),
                "decision": verdict["decision"], "pre_move_pct": pre_move,
                "revenue_yoy": verdict.get("revenue_yoy_pct"),
                "profit_yoy": verdict.get("profit_yoy_pct"),
                "next_day_oc": fwd["next_day_oc"], "three_day_cc": fwd["three_day_cc"],
                "reasoning": verdict.get("reasoning", ""),
            })
            save_checkpoint(results)
            print(f"  -> {result_date.date()} {verdict['decision']}  next_day {fwd['next_day_oc']:+.2f}%")

    print(f"\nDone. {len(results)} results evaluated. Saved to {CHECKPOINT_FILE}")

    def report(label, subset, field):
        vals = [r[field] for r in subset if r[field] is not None]
        if not vals:
            print(f"  {label}: no data")
            return
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        avg = sum(vals) / n
        print(f"  {label}: n={n}  win_rate={wins}/{n} ({wins/n*100:.1f}%)  avg={avg:+.2f}%")

    for decision in ("ENTER_LONG", "ENTER_SHORT", "SKIP"):
        subset = [r for r in results if r["decision"] == decision]
        print(f"\n{decision} (n={len(subset)})")
        report("  next-day O->C", subset, "next_day_oc")
        report("  3-day C->C   ", subset, "three_day_cc")

    print(f"\n{'-'*70}")
    for r in results:
        print(f"{r['date']} {r['symbol']:12s} {r['decision']:11s} "
              f"pre_move={r['pre_move_pct']}%  next_day={r['next_day_oc']:+.2f}%  "
              f"3day={r['three_day_cc']}  | {r['reasoning'][:80]}")


if __name__ == "__main__":
    main()
