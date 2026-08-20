"""
monitor_shortlist.py

Runs from now until a fixed stop time (default 10:30 IST), polling up
to 5 symbols on a live interval via Angel One, using the same
gap/RVOL/VWAP checks as check_confirmations.py.

Removal condition (stock drops out of active tracking, one-time
Telegram notice sent):
  - |gap_pct| >= --gap-remove-threshold (default 5.0%) - already moved
    too far, chasing it now is a different/riskier trade than catching
    the initial move.

Alert condition (Telegram, sent ONCE per stock per notable state - not
every poll, to avoid spamming a 90-minute window):
  - gap aligned with volume aligned with VWAP position - i.e. gap up +
    RVOL >= --rvol-alert (default 2.0) + price above VWAP (or the
    mirrored bearish version) - reported as a "confirmation", not a
    trade signal.

Observation only. Does not decide buy/sell/hold, no position sizing.

Usage:
    python monitor_shortlist.py RELIANCE TCS INFY HDFCBANK TITAN
    python monitor_shortlist.py RELIANCE TCS --stop-time 10:30 --interval 300
"""

import argparse
import time
from datetime import datetime, timedelta

import load_env
load_env.load_env()

from angel_provider import AngelOneProvider
import kaal_telegram
from check_confirmations import check_symbol

INTERVAL_DEFAULT = 300  # 5 minutes
GAP_REMOVE_THRESHOLD_DEFAULT = 5.0
RVOL_ALERT_DEFAULT = 2.0
VOL_LOOKBACK_DEFAULT = 20


def parse_stop_time(hhmm_str):
    now = datetime.now()
    h, m = map(int, hhmm_str.split(":"))
    stop = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if stop <= now:
        stop += timedelta(days=1)  # only relevant if you start after your own stop time
    return stop


def is_confirmed(r, rvol_alert):
    """Bullish: gap up + high RVOL + above VWAP. Bearish: mirrored. Any
    other combination is not treated as a clean confirmation."""
    if r.get("error") or r.get("gap_pct") is None or r.get("rvol") is None:
        return None
    gap = r["gap_pct"]
    rvol = r["rvol"]
    vwap_pos = r.get("vwap_position")

    if gap > 0 and rvol >= rvol_alert and vwap_pos == "above":
        return "bullish"
    if gap < 0 and rvol >= rvol_alert and vwap_pos == "below":
        return "bearish"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+", help="up to 5 NSE symbols")
    parser.add_argument("--interval", type=int, default=INTERVAL_DEFAULT)
    parser.add_argument("--stop-time", default="10:30", help="HH:MM 24hr IST, default 10:30")
    parser.add_argument("--gap-remove-threshold", type=float, default=GAP_REMOVE_THRESHOLD_DEFAULT)
    parser.add_argument("--rvol-alert", type=float, default=RVOL_ALERT_DEFAULT)
    parser.add_argument("--vol-lookback", type=int, default=VOL_LOOKBACK_DEFAULT)
    args = parser.parse_args()

    active = [s.upper() for s in args.symbols][:5]
    if len(args.symbols) > 5:
        print(f"Note: only tracking the first 5 ({active})")

    stop_time = parse_stop_time(args.stop_time)
    provider = AngelOneProvider()

    print(f"Monitoring {active} until {stop_time.strftime('%H:%M')}, "
          f"polling every {args.interval}s")
    print(f"Remove if |gap| >= {args.gap_remove_threshold}%  |  "
          f"Alert if gap+RVOL>={args.rvol_alert}x+VWAP align\n")

    kaal_telegram.send(
        f"\U0001F50D Monitoring shortlist: {', '.join(active)}\n"
        f"Until {stop_time.strftime('%H:%M')} | "
        f"remove if gap>={args.gap_remove_threshold}% | "
        f"alert if gap+volume+VWAP align\n"
        f"(observation only - not a trade signal)"
    )

    already_alerted = set()  # (symbol, direction) pairs, alert once each
    removed = set()

    while datetime.now() < stop_time and len(active) > len(removed):
        now_str = datetime.now().strftime("%H:%M:%S")
        for symbol in list(active):
            if symbol in removed:
                continue

            r = check_symbol(provider, symbol, args.vol_lookback)

            if r.get("error"):
                print(f"[{now_str}] {symbol}: {r['error']}")
                continue

            gap = r.get("gap_pct")
            rvol = r.get("rvol")
            vwap_pos = r.get("vwap_position")
            print(f"[{now_str}] {symbol}: price={r['current_price']} "
                  f"gap={gap} rvol={rvol} vwap={vwap_pos}")

            # Removal check
            if gap is not None and abs(gap) >= args.gap_remove_threshold:
                removed.add(symbol)
                msg = (
                    f"\u274C <b>{symbol}</b> removed from watchlist\n"
                    f"Gap {gap:+.2f}% exceeds {args.gap_remove_threshold}% threshold "
                    f"(already moved too far)\n({now_str})"
                )
                print(f"  -> REMOVED: {msg}".replace('<b>', '').replace('</b>', ''))
                kaal_telegram.send(msg)
                continue

            # Confirmation check
            direction = is_confirmed(r, args.rvol_alert)
            if direction and (symbol, direction) not in already_alerted:
                already_alerted.add((symbol, direction))
                emoji = "\U0001F7E2" if direction == "bullish" else "\U0001F534"
                msg = (
                    f"{emoji} <b>{symbol}</b> {direction} confirmation\n"
                    f"gap={gap:+.2f}%  rvol={rvol:.2f}x  vwap={vwap_pos}\n"
                    f"({now_str})\n"
                    f"(observation only - not a trade signal, not backtested)"
                )
                print(f"  -> ALERT: {msg}".replace('<b>', '').replace('</b>', ''))
                kaal_telegram.send(msg)

        remaining = [s for s in active if s not in removed]
        if not remaining:
            print("All symbols removed - stopping early.")
            break

        if datetime.now() >= stop_time:
            break
        time.sleep(args.interval)

    remaining = [s for s in active if s not in removed]
    summary = (
        f"\u23F9 Monitoring window ended ({datetime.now().strftime('%H:%M')})\n"
        f"Still active: {', '.join(remaining) if remaining else 'none'}\n"
        f"Removed (gapped too far): {', '.join(removed) if removed else 'none'}\n"
        f"Confirmed at some point: "
        f"{', '.join(f'{s}({d})' for s, d in already_alerted) if already_alerted else 'none'}"
    )
    print(f"\n{summary}")
    kaal_telegram.send(summary)


if __name__ == "__main__":
    main()
