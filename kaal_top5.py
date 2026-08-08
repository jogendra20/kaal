"""
kaal_top5.py
Adds a Top 5 section to the morning brief without modifying kaal_morning.py.
Imports the real pipeline functions from kaal_morning and monkeypatches
build_morning_brief so Tier1/Tier2 scoring logic stays untouched -
this file only changes what gets printed at the top of the brief.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import kaal_morning
from kaal_morning import _format_signal_block


def build_top5_section(final: list) -> list:
    """
    Top 5 across the whole scored universe (tier1 + tier2 combined),
    ranked purely by score. Reuses kaal_morning._format_signal_block
    so conviction, delivery data, opportunity label and entry plan
    match exactly what's already in the Tier sections.
    """
    top5 = final[:5]
    if not top5:
        return []
    lines = ["\n🏆 <b>TOP 5 — HIGHEST CONVICTION</b>"]
    for i, s in enumerate(top5, 1):
        block = _format_signal_block(s)
        block[1] = block[1].replace(f"<b>{s['symbol']}</b>", f"<b>{i}. {s['symbol']}</b>")
        lines += block
    lines.append("─" * 34)
    return lines


# Keep a reference to the original so we can still call it
_original_build_morning_brief = kaal_morning.build_morning_brief


def build_morning_brief_with_top5(tier1, tier2, macro, top5_source=None):
    """
    Wraps the original build_morning_brief: renders the normal brief,
    then splices the Top 5 section in right after the macro block
    (right before the "TIER 1" header) if top5_source was passed.
    """
    msg = _original_build_morning_brief(tier1, tier2, macro)
    if not top5_source:
        return msg

    top5_lines = build_top5_section(top5_source)
    if not top5_lines:
        return msg

    top5_block = "\n".join(top5_lines)
    marker = "\n🔥 <b>TIER 1"
    if marker in msg:
        msg = msg.replace(marker, f"\n{top5_block}{marker}", 1)
    else:
        # No Tier 1 stocks today - just prepend Top 5 after macro section
        msg = msg + "\n" + top5_block
    return msg


def run_with_top5():
    """
    Runs kaal_morning's full pipeline, but patches build_morning_brief
    for the duration of this run so the Top 5 section gets included.
    Everything else -- scoring, classification, Telegram send, file
    saves -- is exactly kaal_morning.run(), untouched.
    """
    kaal_morning.build_morning_brief = build_morning_brief_with_top5
    try:
        kaal_morning.run()
    finally:
        kaal_morning.build_morning_brief = _original_build_morning_brief


if __name__ == "__main__":
    run_with_top5()
