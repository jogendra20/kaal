content = open('kaal_scorer.py').read()

old = '''  "offer_price": <for open offers: the offer price per share as number, else 0>,
  "buyback_type": "<TENDER|OPEN_MARKET|NA> — TENDER=fixed price fixed date, OPEN_MARKET=company buys daily from market",
  "macro_impact": "<one line: how current market context affects this stock's setup>"
}}

Scoring reference (adjust for macro context):'''

new = '''  "offer_price": <for open offers: the offer price per share as number, else 0>,
  "buyback_type": "<TENDER|OPEN_MARKET|NA> — TENDER=fixed price fixed date, OPEN_MARKET=company buys daily from market",
  "macro_impact": "<one line: how current market context affects this stock's setup>"
}}

CRITICAL: Only state a specific number (price, %, ₹ crore amount, share count) in "key_detail", "reason", "offer_price", or "macro_impact" if that exact figure literally appears in the Subject/Details/PDF Excerpt above. Never invent or estimate a plausible-sounding number for a detail that wasn't actually given. If a figure isn't present in the source text, describe it qualitatively instead (e.g. "at a premium to CMP", "value not disclosed") and leave the numeric field at 0.

Scoring reference (adjust for macro context):'''

assert old in content, "prompt schema block not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_scorer.py', 'w').write(content)
print("Done: general LLM prompt now has the same 'do not invent numbers' guardrail the results prompt already had.")
