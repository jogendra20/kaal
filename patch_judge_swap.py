content = open('kaal_llm.py').read()

start = content.find('def gemini_final_judge')
end = content.find('\ndef search_staleness', start)

new_func = '''def _build_judge_prompt(signals: list, macro: dict) -> str:
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

    ex = signals[0]
    example = (
        f'[{{"symbol": "{ex["symbol"]}", "final_score": {ex["score"]}, '
        f'"final_reason": "reason here", "action": "WATCH"}}]'
    )

    return (
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


def _merge_judge_verdicts(signals: list, ranked: list, source_name: str) -> list:
    if not ranked:
        return []
    print(f"[LLM] {source_name} verdicts: {[(r.get(\\'symbol\\'), r.get(\\'action\\')) for r in ranked[:5]]}")
    verdict_map = {r["symbol"]: r for r in ranked if isinstance(r, dict) and "symbol" in r}
    updated = []
    for s in signals:
        sym = s["symbol"]
        if sym not in verdict_map:
            continue
        g = verdict_map[sym]
        action = g.get("action", "SKIP")
        if action == "SKIP":
            print(f"[LLM] {source_name} SKIP: {sym}")
            continue
        s = dict(s)
        s["score"]  = g.get("final_score", s["score"])
        s["reason"] = f"[{action}] {g.get(\\'final_reason\\', s.get(\\'reason\\',\\'\\'))}"
        s["action"] = action
        updated.append(s)
    updated.sort(key=lambda x: -x["score"])
    return updated


def gemini_final_judge(signals: list, macro: dict) -> list:
    """
    Final judge: tries Cerebras first (more reliable, no quota issues seen),
    falls back to Gemini if Cerebras fails. Returns [] if both fail —
    caller (kaal_morning.py) applies rule-based fallback in that case.
    """
    if not signals:
        return []

    prompt = _build_judge_prompt(signals, macro)

    # Try Cerebras first
    result = _call_cerebras(prompt)
    if result:
        ranked = result if isinstance(result, list) else result.get("signals", result.get("results", result.get("data", [])))
        if ranked:
            return _merge_judge_verdicts(signals, ranked, "Cerebras")

    print("[LLM] Cerebras judge unavailable — trying Gemini")

    # Fallback to Gemini
    result = _call_gemini(prompt)
    if result:
        ranked = result if isinstance(result, list) else result.get("signals", result.get("results", result.get("data", [])))
        if ranked:
            return _merge_judge_verdicts(signals, ranked, "Gemini")

    print("[LLM] Both Cerebras and Gemini unavailable for judge")
    return []

'''

content = content[:start] + new_func + content[end:]
open('kaal_llm.py', 'w').write(content)
print('Done')
