"""
kaal_monitor.py
Intraday monitor: runs 9:15 AM – 3:30 PM, polls every 5 minutes.
Alerts on: new announcements on watchlist stocks, fresh Tier 1 catalysts, new bulk/block deals.
All alerts include WHY (reason chain).
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from kaal_sources import fetch_nse_announcements, fetch_bse_announcements, fetch_bse_bulk_block, fetch_macro, fetch_asm_gsm_ban
from kaal_scorer import score_announcement, score_bulk_deal
from kaal_telegram import send
from kaal_config import VIX_HIGH, TIER1_MIN_SCORE

DATA_DIR       = os.path.join(os.path.dirname(__file__), "data")
SEEN_FILE      = os.path.join(DATA_DIR, "seen_ids.txt")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.txt")


def load_seen():
    if not os.path.exists(SEEN_FILE): return set()
    return set(open(SEEN_FILE).read().splitlines())

def save_seen(ids):
    open(SEEN_FILE, "w").write("\n".join(sorted(ids)))

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE): return set()
    return set(open(WATCHLIST_FILE).read().splitlines())

def get_ann_id(ann):
    return (ann.get("an_dt", "") or ann.get("dt", "")) + "_" + (ann.get("symbol", "") or str(ann.get("SCRIP_CD", "")))

def direction_emoji(direction: str) -> str:
    return {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(direction, "⚪")

def send_alert(signal: dict, trigger_reason: str):
    now  = datetime.now().strftime("%I:%M %p")
    tier = signal.get("tier", 2)
    icon = "🔥" if tier == 1 else "⚡"
    de   = direction_emoji(signal.get("direction", "NEUTRAL"))

    msg = (
        f"{icon} <b>INTRADAY ALERT</b> — <b>{signal['symbol']}</b> {de}\n"
        f"<code>{now}</code>  Score: <code>{signal['score']}/100</code>\n"
        f"📌 <b>Catalyst:</b> {signal.get('catalyst','').replace('_',' ')}\n"
        f"💡 <b>Key:</b> {signal.get('key','')[:110]}\n"
        f"🧠 <b>Why:</b> {signal.get('reason','')[:200]}\n"
        f"🔔 <b>Trigger:</b> {trigger_reason}\n"
        f"🎯 Confirm with price action. Enter after 9:30 only."
    )
    send(msg)
    print(f"ALERT: {signal['symbol']} | {trigger_reason} | Score: {signal['score']}")


def check_once(watchlist: set, skip_set: set, macro: dict):
    seen     = load_seen()
    new_seen = set(seen)

    nse_anns   = fetch_nse_announcements()
    bse_anns   = fetch_bse_announcements()
    bulk_deals = fetch_bse_bulk_block()

    for ann in nse_anns + bse_anns:
        aid = get_ann_id(ann)
        if aid in seen:
            continue
        new_seen.add(aid)

        result = score_announcement(ann, skip_set=skip_set, macro_context=macro, use_pdf=False)
        if result.get("skip"):
            continue

        symbol = result["symbol"]
        score  = result["score"]

        if symbol in watchlist and score >= 50:
            send_alert(result, f"New announcement on your watchlist stock ({symbol})")
        elif score >= TIER1_MIN_SCORE:
            send_alert(result, f"Fresh Tier 1 catalyst detected (not on watchlist — consider adding)")

    for deal in bulk_deals:
        result = score_bulk_deal(deal)
        if result.get("skip"):
            continue
        if result["symbol"] in watchlist:
            send_alert(result, f"Institutional bulk/block deal on watchlist stock")

    save_seen(new_seen)


def run():
    now          = datetime.now()
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if not (market_open <= now <= market_close):
        print("Market closed. Monitor not running.")
        return

    print(f"[{now.strftime('%H:%M:%S')}] KAAL Monitor started")

    # If watchlist is empty, morning scan never ran — run it now
    watchlist_check = load_watchlist()
    if not watchlist_check:
        print("[KAAL] Watchlist empty — running morning scan first...")
        send("⚡ <b>KAAL: Watchlist empty, running morning scan before monitor...</b>")
        try:
            from kaal_morning import run as morning_run
            morning_run()
        except Exception as e:
            print(f"[KAAL] Morning scan failed: {e}")

    send("👁️ <b>KAAL Monitor: Active</b> (polling every 5 min)")

    filters  = fetch_asm_gsm_ban()
    skip_set = filters["asm"] | filters["gsm"] | filters["ban"]
    macro    = fetch_macro()
    print(f"[Monitor] Macro: VIX={macro.get('vix',0):.1f}, Bias={macro.get('gift_nifty_bias')}, GIFT={macro.get('gift_nifty_pct',0):+.2f}%")

    while True:
        now = datetime.now()
        if now >= market_close:
            print("Market closed. Monitor stopping.")
            send("🔒 <b>KAAL Monitor: Market closed. Stopping.</b>")
            break
        watchlist = load_watchlist()
        try:
            check_once(watchlist, skip_set, macro)
        except Exception as e:
            print(f"Monitor error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    run()
