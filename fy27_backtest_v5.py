import io, csv, json, time, os, re, requests
from datetime import datetime, timedelta
from getpass import getpass

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or getpass("Groq API key: ")

LOOKBACK_DAYS = 200
HISTORY_DAYS = 900
MIN_HISTORY_QUARTERS = 6
PRICED_IN_THRESHOLD = 8.0
GROQ_MODEL = "qwen/qwen3.6-27b"
CHECKPOINT_FILE = "fy27_backtest_results_v5_minq6.json"
HISTORY_CACHE_FILE = "fy27_quarter_history_cache.json"

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
        pnl_keywords = ["Total Income", "Revenue from Operations", "Profit Before Tax",
                        "Profit/(Loss) for the period", "Profit for the period",
                        "Net Profit", "Total Expenses", "Earnings Per Share"]
        scored = []
        for i, page in enumerate(reader.pages):
            t = page.extract_text() or ""
            digit_count = sum(c.isdigit() for c in t)
            kw_hits = sum(1 for kw in pnl_keywords if kw in t)
            score = digit_count + (kw_hits * 800)
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


def forward_returns(symbol, result_date):
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


def fetch_index_constituents(list_url):
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
    index_urls = {
        "NIFTY MIDCAP 150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        "NIFTY SMALLCAP 250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    }
    probe_date = datetime.now() - timedelta(days=3)
    day_data = {}
    for _ in range(7):
        day_data = get_bhavcopy_day(probe_date)
        if day_data:
            break
        probe_date -= timedelta(days=1)
    if not day_data:
        print("  [WARN] could not find a recent bhavcopy day with data")
        return []
    print(f"  using turnover data from {probe_date.strftime('%Y-%m-%d')}")

    universe = []
    for idx_name, url in index_urls.items():
        syms = fetch_index_constituents(url)
        if not syms:
            print(f"  {idx_name}: constituent list fetch failed, skipping")
            continue
        ranked = []
        for sym in syms:
            bar = day_data.get(sym)
            if not bar:
                continue
            turnover_cr = bar["turnover_lacs"] / 100.0
            if turnover_cr >= min_turnover_cr:
                ranked.append((sym, turnover_cr))
        ranked.sort(key=lambda x: -x[1])
        top = ranked[:per_index_top_n]
        if top:
            print(f"  {idx_name}: {len(top)} liquid names, turnover range "
                  f"{top[-1][1]:.0f}-{top[0][1]:.0f} Cr")
        universe.extend(s for s, _ in top)
    return sorted(set(universe))


def _parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _call_mistral(prompt, max_tokens=800):
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
                "max_tokens": max_tokens,
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


def _call_groq_key(key, prompt, label, max_tokens=3000):
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
                "max_tokens": max_tokens,
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
            print(f"  [WARN] {label} hit max_tokens with zero output")
            return None, False
        verdict = _parse_json(content)
        if verdict is None:
            print(f"  [WARN] {label} no JSON in response: {content[:150]!r}")
        return verdict, False
    except Exception as e:
        print(f"  [WARN] {label} exception: {e}")
        return None, False


def call_llm_with_retry(prompt, max_attempts=4, max_tokens=3000):
    result = _call_mistral(prompt, max_tokens=min(max_tokens, 1200))
    if result:
        return result

    key2 = os.environ.get("GROQ_API_KEY_2", "")
    key1 = os.environ.get("GROQ_API_KEY", "") or GROQ_API_KEY

    for attempt in range(1, max_attempts + 1):
        rl2 = False
        if key2:
            verdict, rl2 = _call_groq_key(key2, prompt, "Groq2", max_tokens)
            if verdict:
                return verdict
        verdict, rl1 = _call_groq_key(key1, prompt, "Groq1", max_tokens)
        if verdict:
            return verdict
        if rl1 or rl2:
            wait = min(20.0, 5.0 * attempt)
            print(f"  [WAIT] rate limited, sleeping {wait}s (attempt {attempt}/{max_attempts})")
            time.sleep(wait)
        else:
            break
    return None


EXTRACT_PROMPT = """Extract ONLY figures actually present in this filing excerpt.
Do not invent numbers. If a figure isn't stated, use null.

FILING TEXT:
---
{pdf_text}
---

Find the CURRENT quarter's figures and the SAME QUARTER LAST YEAR figures
(year-ago comparison), if both are present in a comparison table.

Respond with ONLY this JSON:
{{"revenue_current": <number or null>, "revenue_year_ago": <number or null>,
  "profit_current": <number or null>, "profit_year_ago": <number or null>}}
"""


def extract_financials(pdf_text):
    prompt = EXTRACT_PROMPT.format(pdf_text=pdf_text[:4000])
    result = call_llm_with_retry(prompt, max_tokens=600)
    if not result:
        return None
    try:
        rc, ry = result.get("revenue_current"), result.get("revenue_year_ago")
        pc, py = result.get("profit_current"), result.get("profit_year_ago")
        rev_yoy = ((rc - ry) / abs(ry) * 100) if (rc is not None and ry) else None
        prof_yoy = ((pc - py) / abs(py) * 100) if (pc is not None and py) else None
        return {"revenue_yoy_pct": rev_yoy, "profit_yoy_pct": prof_yoy}
    except (TypeError, ZeroDivisionError):
        return None


def load_history_cache():
    if os.path.exists(HISTORY_CACHE_FILE):
        try:
            with open(HISTORY_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history_cache(cache):
    with open(HISTORY_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def build_company_history(session, symbol, history_cache):
    if symbol in history_cache:
        return history_cache[symbol]

    to_date = datetime.now() - timedelta(days=3)
    from_date = to_date - timedelta(days=HISTORY_DAYS)
    anns = fetch_results_announcements(session, symbol, from_date, to_date)
    time.sleep(0.5)

    seen_dates = set()
    quarters = []
    for a in anns:
        an_dt_str = a.get("an_dt", "")
        try:
            result_date = datetime.strptime(an_dt_str.split()[0], "%d-%b-%Y")
        except Exception:
            continue
        date_key = result_date.strftime("%Y-%m-%d")
        if date_key in seen_dates:
            continue
        seen_dates.add(date_key)

        pdf_url = a.get("attchmntFile") or a.get("pdfLink") or ""
        pdf_text = download_pdf_text(pdf_url)
        if len(pdf_text) < 200:
            continue
        fin = extract_financials(pdf_text)
        if fin and fin["profit_yoy_pct"] is not None:
            quarters.append({"date": date_key, **fin})

    quarters.sort(key=lambda q: q["date"])
    history_cache[symbol] = quarters
    save_history_cache(history_cache)
    return quarters


def _theil_sen_trend(vals):
    """Median of all pairwise slopes — resistant to a single outlier quarter
    distorting the trend, unlike a simple mean/std over raw values (which is
    what produced the z=-15.33 / z=+22.81 statistical artifacts in the
    previous version, from tiny-sample std-dev instability)."""
    n = len(vals)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = j - i
            slopes.append((vals[j] - vals[i]) / dx)
    slopes.sort()
    m = len(slopes)
    slope = slopes[m // 2] if m % 2 else (slopes[m // 2 - 1] + slopes[m // 2]) / 2

    intercepts = sorted(vals[i] - slope * i for i in range(n))
    mi = len(intercepts)
    intercept = intercepts[mi // 2] if mi % 2 else (intercepts[mi // 2 - 1] + intercepts[mi // 2]) / 2

    return slope, intercept


def compute_sue_zscore(target_date_str, quarters):
    prior = [q for q in quarters if q["date"] < target_date_str and q["profit_yoy_pct"] is not None]
    current = next((q for q in quarters if q["date"] == target_date_str), None)
    if not current or current["profit_yoy_pct"] is None or len(prior) < MIN_HISTORY_QUARTERS:
        return None

    vals = [q["profit_yoy_pct"] for q in prior]
    slope, intercept = _theil_sen_trend(vals)
    expected = slope * len(vals) + intercept  # trend extrapolated to the current quarter's position

    residuals = [vals[i] - (slope * i + intercept) for i in range(len(vals))]
    variance = sum(r ** 2 for r in residuals) / len(residuals)
    std = variance ** 0.5
    if std < 1e-6:
        return None

    z = (current["profit_yoy_pct"] - expected) / std
    return {"z_score": round(z, 2), "trailing_mean": round(expected, 1),
             "trailing_std": round(std, 1), "n_prior_quarters": len(prior)}


def build_checklist_prompt(symbol, pdf_text, pre_move_pct, sue):
    priced_in_note = (
        f"Stock moved {pre_move_pct:+.1f}% in the 5 trading days before this result "
        f"({'ALREADY TRIGGERS Priced-In skip, >|8%|' if pre_move_pct is not None and abs(pre_move_pct) > PRICED_IN_THRESHOLD else 'within normal range'})."
        if pre_move_pct is not None else "Pre-result price move unavailable."
    )
    if sue:
        sue_note = (
            f"STATISTICAL BASELINE (computed, not your judgment call): over the company's "
            f"prior {sue['n_prior_quarters']} quarters, profit YoY growth averaged "
            f"{sue['trailing_mean']:+.1f}% (std dev {sue['trailing_std']:.1f}). This quarter's "
            f"result is {sue['z_score']:+.2f} standard deviations from that company-specific "
            f"normal (z-score). Treat |z| >= 1.0 as a genuine positive/negative surprise for "
            f"THIS company; |z| < 1.0 means growth is in line with this company's own normal "
            f"pace, even if the absolute number looks large — do NOT treat routine high growth "
            f"as a beat just because the percentage is big."
        )
    else:
        sue_note = ("STATISTICAL BASELINE: not enough prior-quarter history available for this "
                     "company to compute a z-score. Fall back to treating profit growth "
                     ">=15% YoY as the beat threshold, and say so explicitly in your reasoning.")

    return f"""You are a disciplined intraday analyst applying a strict results checklist.
Extract ONLY numbers actually present in the filing text below — never invent figures.

SYMBOL: {symbol}
{priced_in_note}
{sue_note}

FILING TEXT (raw extract, may be messy):
---
{pdf_text[:4000]}
---

PHASE 1 — SKIP if ANY true:
1. Priced-In: stock already moved >{PRICED_IN_THRESHOLD}% in the 5 days before this result (see note above).
2. Mixed Bag: revenue grew but profit fell, or vice versa.
3. Red Flag: profit driven by exceptional/one-time items, auditor qualification, or promoter pledging increase mentioned.
4. Poor Guidance: management commentary is flat, cautious, or negative despite decent numbers.
5. Not-a-real-surprise: z-score (if available) is between -1.0 and +1.0 — this is normal growth for this company, not a beat or a miss.

PHASE 2 — ENTER LONG only if ALL true (and Phase 1 didn't trigger SKIP):
6. Revenue and profit both grew YoY, margin stable/expanding.
7. z-score >= +1.0 (a genuine positive surprise vs this company's own history), OR if no z-score available, profit growth >=15% YoY as fallback.
8. Guidance is positive, or new order wins / capacity expansion mentioned.

PHASE 3 — ENTER SHORT only if Phase 1 has no red-flag/mixed-bag trigger but:
9. z-score <= -1.0 (a genuine negative surprise vs this company's own history), OR if no z-score available, revenue AND profit both missed prior year significantly (>10% decline).
10. Guidance is explicitly negative.

Respond with ONLY this JSON, no other text:
{{"decision": "ENTER_LONG" | "ENTER_SHORT" | "SKIP",
  "revenue_yoy_pct": <number or null>,
  "profit_yoy_pct": <number or null>,
  "z_score_used": <number or null>,
  "reasoning": "<1-2 sentences citing the specific numbers/z-score that drove this>"}}
"""


def save_checkpoint(results):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(results, f, indent=2)


def main():
    universe = fetch_liquid_universe()
    print(f"Screened universe ({len(universe)} liquid mid/small-caps): {universe}\n")

    session = nse_session()
    to_date = datetime.now() - timedelta(days=3)
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)

    history_cache = load_history_cache()
    results = []
    seen = set()

    for i, symbol in enumerate(universe, 1):
        print(f"[{i}/{len(universe)}] {symbol}...")

        print(f"  building quarterly history...")
        quarters = build_company_history(session, symbol, history_cache)
        print(f"  -> {len(quarters)} prior quarters with usable financials")

        anns = fetch_results_announcements(session, symbol, from_date, to_date)
        time.sleep(0.5)
        if not anns:
            print("  -> no results filings found in test window")
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

            sue = compute_sue_zscore(result_date.strftime("%Y-%m-%d"), quarters)
            pre_move = pre_result_move_pct(symbol, result_date)
            prompt = build_checklist_prompt(symbol, pdf_text, pre_move, sue)
            verdict = call_llm_with_retry(prompt, max_tokens=3000)
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
                "z_score": sue["z_score"] if sue else None,
                "revenue_yoy": verdict.get("revenue_yoy_pct"),
                "profit_yoy": verdict.get("profit_yoy_pct"),
                "next_day_oc": fwd["next_day_oc"], "three_day_cc": fwd["three_day_cc"],
                "reasoning": verdict.get("reasoning", ""),
            })
            save_checkpoint(results)
            z_str = f"z={sue['z_score']:+.2f}" if sue else "z=N/A"
            print(f"  -> {result_date.date()} {verdict['decision']} ({z_str})  "
                  f"next_day {fwd['next_day_oc']:+.2f}%")

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
        z_str = f"z={r['z_score']:+.2f}" if r['z_score'] is not None else "z=N/A"
        print(f"{r['date']} {r['symbol']:12s} {r['decision']:11s} {z_str:8s} "
              f"pre_move={r['pre_move_pct']}%  next_day={r['next_day_oc']:+.2f}%  "
              f"3day={r['three_day_cc']}  | {r['reasoning'][:70]}")


if __name__ == "__main__":
    main()
