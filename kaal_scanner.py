import os, json, time, requests, yfinance as yf
from bse import BSE
from datetime import date, timedelta

CKPT = "scan_checkpoint.json"

if os.path.exists(".env"):
    for line in open(".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY")

def load_ckpt():
    if os.path.exists(CKPT):
        return json.load(open(CKPT))
    return {"done_batches": [], "results": []}

def save_ckpt(state):
    json.dump(state, open(CKPT, "w"))

def get_nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    })
    s.get("https://www.nseindia.com", timeout=10)
    time.sleep(1)
    return s

def get_nse_list(s):
    r = s.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", timeout=15)
    syms = []
    for line in r.text.splitlines()[1:]:
        parts = line.split(",")
        if parts and parts[0].strip():
            syms.append(parts[0].strip() + ".NS")
    return syms

def get_bse_list_and_client():
    bse = BSE(download_folder="./")
    groups = ["A", "B", "T", "TS", "M", "MT", "Z", "P", "X", "XT", "W"]
    all_secs = {}
    for g in groups:
        for attempt in range(3):
            try:
                secs = bse.listSecurities(segment="Equity", status="Active", group=g)
                for s in secs:
                    code = s.get("SCRIP_CD")
                    if code:
                        all_secs[code] = s
                break
            except Exception:
                time.sleep(3)
    syms = [str(code) + ".BO" for code in all_secs.keys()]
    return syms, bse

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def scan_universe(tickers, state):
    batches = list(chunk(tickers, 150))
    for i, batch in enumerate(batches):
        if i in state["done_batches"]:
            continue
        try:
            data = yf.download(tickers=batch, period="1d", group_by="ticker", threads=True, progress=False)
        except Exception as e:
            print(f"  batch {i+1} failed: {e} -- will retry next run")
            save_ckpt(state)
            continue
        for t in batch:
            try:
                row = data if len(batch) == 1 else data[t]
                low, high, close, vol = row["Low"].iloc[-1], row["High"].iloc[-1], row["Close"].iloc[-1], row["Volume"].iloc[-1]
                if low and 50 <= close <= 3000:
                    chg = ((high - low) / low) * 100
                    state["results"].append({"symbol": t, "low": float(low), "high": float(high),
                                              "close": float(close), "volume": float(vol), "change_pct": chg})
            except Exception:
                continue
        state["done_batches"].append(i)
        save_ckpt(state)
        print(f"  batch {i+1}/{len(batches)} done, {len(state['results'])} matched so far (checkpoint saved)")
        time.sleep(1)
    return state["results"]

def check_nse_announcement(s, base):
    try:
        r = s.get("https://www.nseindia.com/api/corporate-announcements",
                   params={"index": "equities", "symbol": base}, timeout=10)
        return r.json() or []
    except Exception:
        return []

def check_bse_announcement(bse_client, base):
    try:
        today = date.today().strftime("%Y%m%d")
        weekago = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
        return bse_client.announcements(scripcode=base, fromDate=weekago, toDate=today)
    except Exception:
        return []

def check_volume_conviction(symbol, current_vol):
    try:
        info = yf.Ticker(symbol).info
        avg = info.get("averageVolume10days") or info.get("averageVolume")
        return (avg and current_vol > avg * 1.5), avg
    except Exception:
        return False, None

def tavily_news(query):
    try:
        r = requests.post("https://api.tavily.com/search",
                           json={"api_key": TAVILY_KEY, "query": query, "max_results": 5}, timeout=15)
        return r.json().get("results", [])
    except Exception:
        return []

def mistral_summarize(prompt):
    try:
        r = requests.post("https://api.mistral.ai/v1/chat/completions",
                           headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
                           json={"model": "mistral-large-latest",
                                 "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}, timeout=30)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[summary failed: {e}]"

def main():
    state = load_ckpt()
    s = get_nse_session()
    print("Fetching NSE + BSE lists...")
    nse_syms = get_nse_list(s)
    bse_syms, bse_client = get_bse_list_and_client()
    universe = nse_syms + bse_syms
    print(f"Universe: {len(universe)} symbols (NSE: {len(nse_syms)}, BSE: {len(bse_syms)}) | {len(state['done_batches'])} batches already checkpointed")

    print("Scanning...")
    results = scan_universe(universe, state)
    print(f"\nStack (Rs.50-3000): {len(results)} stocks")

    top20 = sorted(results, key=lambda x: x["change_pct"], reverse=True)[:20]
    print("\nTop 20 by change%:")
    for r in top20:
        print(f"  {r['symbol']:15s} close={r['close']:.2f} chg%={r['change_pct']:.2f}")

    print("\n=== SUMMARY ===")
    for r in top20:
        symbol, base = r["symbol"], r["symbol"].replace(".NS", "").replace(".BO", "")
        ann = check_nse_announcement(s, base) if symbol.endswith(".NS") else check_bse_announcement(bse_client, base)
        if ann:
            conv, avg = check_volume_conviction(symbol, r["volume"])
            tag = "CONVICTION (breakout+high vol)" if conv else "weak volume, caution"
            print(f"{symbol:15s} {r['change_pct']:.2f}% -> Announcement-driven | {tag}")
        else:
            news = tavily_news(f"{base} share price today reason NSE BSE")
            ctx = "\n".join(n.get("content", "") for n in news[:3])
            reason = mistral_summarize(f"Stock {base} moved {r['change_pct']:.2f}% today with NO corporate announcement. Based on this news, explain in 2 lines why:\n{ctx}")
            print(f"{symbol:15s} {r['change_pct']:.2f}% -> No announcement | {reason}")
        time.sleep(1)

    os.remove(CKPT)
    print("\nDone. Checkpoint cleared.")

if __name__ == "__main__":
    main()
