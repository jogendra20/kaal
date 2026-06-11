"""
kaal.py  —  Single entry point. Run this anytime.

KAAL figures out what to do based on current time:

  Before 8:30 AM          → Too early. Shows next scheduled action.
  8:30 AM – 9:14 AM       → Morning scan (today's watchlist + Telegram brief)
  9:15 AM – 3:30 PM       → Intraday monitor (live alerts loop until market close)
  3:31 PM – 8:59 PM       → Market closed. Shows what evening scan will do.
  9:00 PM – 11:59 PM      → Evening scan (tomorrow's pre-watchlist + Telegram brief)
  After midnight – 3 AM   → Too late / too early. Reminds you.

Usage:
    python3 kaal/kaal.py

Force a specific mode (for testing):
    python3 kaal/kaal.py --morning
    python3 kaal/kaal.py --evening
    python3 kaal/kaal.py --monitor
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, time as dtime

def now_time() -> dtime:
    return datetime.now().time()

def time_str(t: dtime) -> str:
    return datetime.now().replace(
        hour=t.hour, minute=t.minute
    ).strftime("%I:%M %p")

def detect_mode() -> str:
    t = now_time()

    # Force flags
    if "--morning" in sys.argv: return "morning"
    if "--evening" in sys.argv: return "evening"
    if "--monitor" in sys.argv: return "monitor"

    # Time windows
    if dtime(8, 30) <= t < dtime(9, 15):
        return "morning"
    elif dtime(9, 15) <= t <= dtime(15, 30):
        return "monitor"
    elif dtime(21, 0) <= t <= dtime(23, 59):
        return "evening"
    else:
        return "idle"

def print_idle_message(t: dtime):
    print("\n╔══════════════════════════════════╗")
    print("║         KAAL — IDLE              ║")
    print("╚══════════════════════════════════╝")

    if t < dtime(8, 30):
        mins = (dtime(8, 30).hour * 60 + dtime(8, 30).minute) - (t.hour * 60 + t.minute)
        print(f"\n  Current time : {datetime.now().strftime('%I:%M %p')}")
        print(f"  Morning scan : starts at 8:30 AM  ({mins} min away)")
        print(f"\n  Run again at 8:30 AM or use:")
        print(f"  python3 kaal/kaal.py --morning   (force morning scan now)")

    elif dtime(15, 31) <= t < dtime(21, 0):
        mins = (21 * 60) - (t.hour * 60 + t.minute)
        print(f"\n  Current time  : {datetime.now().strftime('%I:%M %p')}")
        print(f"  Market closed : 3:30 PM")
        print(f"  Evening scan  : starts at 9:00 PM  ({mins} min away)")
        print(f"\n  Run again at 9 PM or use:")
        print(f"  python3 kaal/kaal.py --evening   (force evening scan now)")

    else:
        print(f"\n  Current time  : {datetime.now().strftime('%I:%M %p')}")
        print(f"  Nothing to do at this hour.")
        print(f"  Next morning scan: 8:30 AM")

    print()

def main():
    mode = detect_mode()
    now  = datetime.now().strftime("%I:%M %p")

    print(f"\n{'='*40}")
    print(f"  KAAL v2 — {datetime.now().strftime('%d %b %Y %I:%M:%S %p')}")
    print(f"  Mode detected: {mode.upper()}")
    print(f"{'='*40}\n")

    # Key check
    try:
        from kaal_config import check_keys, GROQ_API_KEY, GEMINI_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT
        warns = check_keys()
        if not warns:
            print("[✓] All API keys loaded")
        print(f"[✓] Groq: {'SET' if GROQ_API_KEY else 'MISSING'} | Gemini: {'SET' if GEMINI_API_KEY else 'MISSING'} | Telegram: {'SET' if TELEGRAM_TOKEN and TELEGRAM_CHAT else 'MISSING'}")
    except Exception as e:
        print(f"[✗] Config load error: {e}")
        return

    # Import check
    print("\n[→] Checking module imports...")
    for mod in ["kaal_sources", "kaal_scorer", "kaal_llm", "kaal_telegram"]:
        try:
            __import__(mod)
            print(f"    [✓] {mod}")
        except Exception as e:
            print(f"    [✗] {mod} — ERROR: {e}")
            return

    print()

    if mode == "morning":
        print(f"[KAAL] {now} → Running MORNING SCAN")
        try:
            from kaal_morning import run
            run()
        except Exception as e:
            import traceback
            print(f"\n[✗] MORNING SCAN CRASHED:")
            traceback.print_exc()

    elif mode == "monitor":
        print(f"[KAAL] {now} → Market hours. Starting INTRADAY MONITOR")
        try:
            from kaal_monitor import run
            run()
        except Exception as e:
            import traceback
            print(f"\n[✗] MONITOR CRASHED:")
            traceback.print_exc()

    elif mode == "evening":
        print(f"[KAAL] {now} → Running EVENING SCAN")
        try:
            from kaal_evening import run
            run()
        except Exception as e:
            import traceback
            print(f"\n[✗] EVENING SCAN CRASHED:")
            traceback.print_exc()

    else:
        print_idle_message(now_time())

if __name__ == "__main__":
    main()
