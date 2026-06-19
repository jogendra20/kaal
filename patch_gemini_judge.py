content = open('kaal_llm.py').read()

start = content.find('\ndef gemini_final_judge')
end = content.find('\ndef search_staleness', start)

new_func = '''
def gemini_final_judge(signals: list, macro: dict) -> list:
    """
    Gemini receives top 15 signals and strictly filters them.
    Returns only high conviction stocks with action verdicts.
    """
    _load_env()
    if not signals:
        return []

    import json

    signals_text = json.dumps([{
        "symbol":   s["symbol"],
        "score":    s["score"],
        "catalyst": s.get("catalyst", ""),
        "key":      s.get("key", ""),
        "reason":   s.get("reason", ""),
    } for s in signals[:15]], indent=2)

    macro_text = (
        f"VIX={macro.get('vix',15):.1f}, "
        f"GIFT={macro.get('gift_nifty_bias','Neutral')}, "
        f"SPX={macro.get('spx_chg',0):+.1f}%"
    )

    # Build example from first signal
    ex = signals[0]
    example = (
        f'[{{"symbol": "{ex["symbol"]}", "final_score": {ex["score"]}, '
        f'"final_reason": "reason here", "action": "WATCH"}}]'
    )

    prompt = (
        "You are a strict NSE intraday risk manager. REDUCE the list ruthlessly."
        f"\\n\\nMARKET: {macro_text}"
        f"\\n\\nSignals:\\n{signals_text}"
        f"\\n\\nReturn ONLY a JSON array in this exact format (no markdown):\\n{example}"
        "\\n\\nSTRICT RULES:"
        "\\n- NEWS_MOMENTUM = SKIP always"
        "\\n- OI_SPURT alone = SKIP"
        "\\n- SCREENER alone = SKIP"
        "\\n- ORDER_WIN without size = SKIP"
        "\\n- Score < 70 = SKIP"
        "\\n- MAXIMUM 2 BUY_PULLBACK"
        "\\n- MAXIMUM 3 WATCH"
        "\\n- Everything else = SKIP"
        "\\n- When in doubt = SKIP"
    )

    result = _call_gemini(prompt)
    if result is None or not result:
        return []

    # Handle list or dict response
    if isinstance(result, list):
        ranked = result
    elif isinstance(result, dict):
        ranked = result.get("signals", result.get("results", result.get("data", [])))
    else:
        return []

    if not ranked:
        return []

    print(f"[LLM] Gemini verdicts: {[(r.get('symbol'), r.get('action')) for r in ranked[:5]]}")

    # Merge verdicts back
    gemini_map = {r["symbol"]: r for r in ranked if isinstance(r, dict) and "symbol" in r}
    updated = []
    for s in signals:
        sym = s["symbol"]
        if sym not in gemini_map:
            print(f"[LLM] Gemini not ranked: {sym} — skipping")
            continue
        g = gemini_map[sym]
        action = g.get("action", "SKIP")
        if action == "SKIP":
            print(f"[LLM] Gemini SKIP: {sym}")
            continue
        s = dict(s)
        s["score"]  = g.get("final_score", s["score"])
        s["reason"] = f"[{action}] {g.get('final_reason', s.get('reason',''))}"
        s["action"] = action
        updated.append(s)

    updated.sort(key=lambda x: -x["score"])
    return updated

'''

content = content[:start] + new_func + content[end:]
open('kaal_llm.py', 'w').write(content)
print('Done')
