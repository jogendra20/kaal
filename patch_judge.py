content = open('kaal_morning.py').read()

# Find and replace entire Gemini judge block
old_start = content.find('    # ── Gemini Final Judge')
old_end = content.find('    # ── Sort and tier', old_start)

new_block = '''    # ── Gemini Final Judge ──────────────────────────────────
    log("Running Gemini final judge...")
    try:
        from kaal_llm import gemini_final_judge
        judged = gemini_final_judge(final, macro)
        if judged and isinstance(judged, list) and len(judged) > 0:
            final = judged
            log(f"Gemini judge done: {len(final)} signals remain")
        else:
            raise Exception("Gemini returned empty")
    except Exception as e:
        log(f"Gemini unavailable: {e} — rule-based fallback")
        SKIP_CATS = {"NEWS_MOMENTUM", "OTHER", "PARTNERSHIP"}
        ORDER_CATS = {"ORDER_WIN", "BAGGING_RECEIVING_OF_ORDE", "AWARDING_OF_ORDER(S)_CONT"}
        filtered = []
        for s in final:
            cat = s.get("catalyst", "").upper()
            score = s.get("score", 0)
            if cat in SKIP_CATS:
                continue
            if cat in ORDER_CATS and score < 80:
                continue
            if score < 65:
                continue
            filtered.append(s)
        final = filtered
        log(f"Fallback done: {len(final)} signals remain")

'''

content = content[:old_start] + new_block + content[old_end:]
open('kaal_morning.py', 'w').write(content)
print('Done')
