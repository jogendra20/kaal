content = open('kaal_sources.py').read()

old = '''        print(f"[SRC] Bhavcopy {date_str}: {len(result)} EQ stocks loaded")
        return result

    except Exception as e:
        print(f"[SRC] Bhavcopy error: {e}")
        return {}


def classify_delivery(deliv_per: float, chg_pct: float) -> dict:'''

new = '''        print(f"[SRC] Bhavcopy {date_str}: {len(result)} EQ stocks loaded")
        return result

    except Exception as e:
        print(f"[SRC] Bhavcopy error: {e}")
        return {}


def fetch_oi_from_bhavcopy(date_str: str = None) -> dict:
    """
    Replaces fetch_oi_spurts() for the PRE-MARKET morning run.
    fetch_oi_spurts() hits NSE's "live-analysis-oi-spurts-underlyings"
    endpoint, which only has data once today's derivatives session is
    live (from market open) - called at ~8:58 AM (before 9:15 open) it
    has nothing to serve and 404s every time, making the OI signal
    silently dead weight in the morning brief.

    This pulls yesterday's F&O bhavcopy instead (published ~7PM, so it's
    always ready well before the next morning's run) and computes the
    same {symbol: {oi_change, avg_oi_pct, volume}} shape from the
    CHG_IN_OI / OPEN_INT columns NSE already provides per-contract, summed
    across expiries for FUTSTK contracts only (stock futures - excludes
    index futures/options noise).
    """
    import csv
    from datetime import datetime, timedelta
    import requests as req

    if not date_str:
        # Same last-trading-day walk-back as fetch_bhavcopy(), so this is
        # always looking at the most recent published session.
        d = datetime.now() - timedelta(days=1)
        while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            d -= timedelta(days=1)
        date_str = d.strftime("%d%m%Y")

    url = f"https://nsearchives.nseindia.com/products/content/fo_bhavdata_full_{date_str}.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        r = req.get(url, headers=headers, timeout=(5, 15))
        if r.status_code != 200:
            print(f"[SRC] FO Bhavcopy {date_str}: HTTP {r.status_code}")
            return {}

        reader = csv.DictReader(r.text.splitlines())
        agg = {}  # symbol -> {open_int_total, chg_oi_total, volume_total}
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("INSTRUMENT") != "FUTSTK":
                continue  # stock futures only - skip index futs and all options
            symbol = row.get("SYMBOL", "")
            if not symbol:
                continue
            try:
                open_int = float(row.get("OPEN_INT", 0) or 0)
                chg_oi   = float(row.get("CHG_IN_OI", 0) or 0)
                contracts = int(float(row.get("CONTRACTS", 0) or 0))
            except Exception:
                continue
            a = agg.setdefault(symbol, {"open_int": 0.0, "chg_oi": 0.0, "contracts": 0})
            a["open_int"]  += open_int
            a["chg_oi"]    += chg_oi
            a["contracts"] += contracts

        oi_map = {}
        for symbol, a in agg.items():
            prev_oi = a["open_int"] - a["chg_oi"]  # OPEN_INT is post-change; back out prior day's OI
            avg_oi_pct = round((a["chg_oi"] / prev_oi) * 100, 2) if prev_oi else 0
            oi_map[symbol] = {
                "oi_change":  int(a["chg_oi"]),
                "avg_oi_pct": avg_oi_pct,
                "volume":     a["contracts"],
            }

        high_oi = {s: v for s, v in oi_map.items() if v["avg_oi_pct"] > 10}
        print(f"[SRC] FO Bhavcopy OI: {len(oi_map)} FUTSTK symbols | {len(high_oi)} high conviction (>10%)")
        if high_oi:
            top = sorted(high_oi.items(), key=lambda x: -x[1]["avg_oi_pct"])[:5]
            print(f"[SRC] Top OI: {[(s, round(v['avg_oi_pct'],1)) for s,v in top]}")
        return oi_map

    except Exception as e:
        print(f"[SRC] FO Bhavcopy OI error: {e}")
        return {}


def classify_delivery(deliv_per: float, chg_pct: float) -> dict:'''

assert old in content, "Bhavcopy tail / classify_delivery anchor not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_sources.py', 'w').write(content)
print('Done: fetch_oi_from_bhavcopy added to kaal_sources.py')
