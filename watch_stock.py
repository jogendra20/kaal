"""
watch_stock.py

Manual single-stock live observer. You give a symbol, it polls Angel One
for price/volume at a fixed interval and sends a Telegram alert when
either condition fires:
  1. Price has moved beyond +/- PRICE_ALERT_PCT since the watch started
  2. Current 5-min volume exceeds VOLUME_MULTIPLIER x the recent average

This does NOT decide buy/sell/hold - it only observes and alerts. No
position sizing, no entry/exit logic. Standalone, not wired into any
other KAAL module.

Usage:
    python watch_stock.py RELIANCE
    python watch_stock.py RELIANCE --interval 300 --price-alert 2.0 --vol-mult 3.0
"""

import argparse
import sys
import time
from datetime import datetime

import load_env
load_env.load_env()

from angel_provider import AngelOneProvider
import kaal_telegram

POLL_INTERVAL_DEFAULT = 300  # 5 minutes
PRICE_ALERT_PCT_DEFAULT = 2.0
VOLUME_MULTIPLIER_DEFAULT = 3.0
VOLUME_LOOKBACK_CANDLES = 20


def fmt_pct(x):
    return f"{x:+.2f}%"


def check_price_alert(symbol, baseline_price, current_price, threshold_pct, already_fired):
    if baseline_price is None or current_price is None or baseline_price == 0:
        return None
    move_pct = (current_price - baseline_price) / baseline_price * 100
    if abs(move_pct) >= threshold_pct and threshold_pct not in already_fired:
        return move_pct
    return None


def check_volume_alert(symbol, bars, multiplier, already_fired_this_candle):
    """bars: list of recent 5-min candles, most recent last. Compares the
    latest candle's volume against the average of the prior N candles."""
    if not bars or len(bars) < VOLUME_LOOKBACK_CANDLES + 1:
        return None, None
    latest = bars[-1]
    history = bars[-(VOLUME_LOOKBACK_CANDLES + 1):-1]
    avg_vol = sum(b["volume"] for b in history) / len(history)
    if avg_vol == 0:
        return None, None
    ratio = latest["volume"] / avg_vol
    candle_ts = latest.get("timestamp") or latest.get("date")
    if ratio >= multiplier and candle_ts not in already_fired_this_candle:
        return ratio, candle_ts
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="NSE symbol, e.g. RELIANCE")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL_DEFAULT,
                         help=f"seconds between polls (default {POLL_INTERVAL_DEFAULT})")
    parser.add_argument("--price-alert", type=float, default=PRICE_ALERT_PCT_DEFAULT,
                         help=f"%% move to trigger a price alert (default {PRICE_ALERT_PCT_DEFAULT})")
    parser.add_argument("--vol-mult", type=float, default=VOLUME_MULTIPLIER_DEFAULT,
                         help=f"volume multiple vs recent avg to trigger an alert (default {VOLUME_MULTIPLIER_DEFAULT})")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    provider = AngelOneProvider()

    print(f"Watching {symbol} - poll every {args.interval}s, "
          f"price alert at +/-{args.price_alert}%, volume alert at {args.vol_mult}x avg")

    start_data = provider.get_ltp(symbol)
    if not start_data or start_data.get("ltp") is None:
        print(f"Could not fetch starting price for {symbol} - check symbol name and Angel One session.")
        sys.exit(1)
    baseline_price = start_data["ltp"]
    print(f"Baseline price: {baseline_price}")

    kaal_telegram.send(
        f"\U0001F441 Watching <b>{symbol}</b>\n"
        f"Baseline: {baseline_price}\n"
        f"Price alert: +/-{args.price_alert}% | Volume alert: {args.vol_mult}x avg\n"
        f"(observation only - not a trade signal)"
    )

    price_alerts_fired = set()
    volume_alerts_fired = set()

    try:
        while True:
            time.sleep(args.interval)
            now = datetime.now().strftime("%H:%M:%S")

            ltp_data = provider.get_ltp(symbol)
            current_price = ltp_data.get("ltp") if ltp_data else None

            if current_price is not None:
                move_pct = check_price_alert(symbol, baseline_price, current_price,
                                              args.price_alert, price_alerts_fired)
                if move_pct is not None:
                    price_alerts_fired.add(args.price_alert)
                    msg = (
                        f"\U0001F4C8 <b>{symbol}</b> price alert\n"
                        f"Moved {fmt_pct(move_pct)} from baseline {baseline_price}\n"
                        f"Current: {current_price}  ({now})\n"
                        f"(observation only - not a trade signal)"
                    )
                    print(msg.replace("<b>", "").replace("</b>", ""))
                    kaal_telegram.send(msg)

            bars = provider.get_intraday_bars(symbol, interval="5min", n=VOLUME_LOOKBACK_CANDLES + 5)
            if bars:
                ratio, candle_ts = check_volume_alert(symbol, bars, args.vol_mult, volume_alerts_fired)
                if ratio is not None:
                    volume_alerts_fired.add(candle_ts)
                    msg = (
                        f"\U0001F4CA <b>{symbol}</b> volume alert\n"
                        f"Latest 5-min volume is {ratio:.1f}x the {VOLUME_LOOKBACK_CANDLES}-candle average\n"
                        f"Candle: {candle_ts}  ({now})\n"
                        f"(observation only - not a trade signal)"
                    )
                    print(msg.replace("<b>", "").replace("</b>", ""))
                    kaal_telegram.send(msg)

            print(f"[{now}] {symbol} LTP={current_price} (no new alert)" if current_price else f"[{now}] fetch failed")

    except KeyboardInterrupt:
        print("\nStopped watching.")
        kaal_telegram.send(f"Stopped watching <b>{symbol}</b>.")


if __name__ == "__main__":
    main()
