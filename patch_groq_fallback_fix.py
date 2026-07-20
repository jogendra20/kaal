content = open('kaal_llm.py').read()

old = '''    model = GROQ_FAST_MODEL if fast else GROQ_MODEL
    result, rl1 = _call_groq_key(key1, prompt, "Groq1", model)
    if result:
        print("→ Groq1 OK")
        return result

    if rl1 and key2:
        result, rl2 = _call_groq_key(key2, prompt, "Groq2", model)
        if result:
            print("→ Groq2 OK")
            return result
        if rl2:
            # Both rate limited — set cooldown, only retry for Tier 1
            _rate_limited_until = time.time() + 30
            if not fast:
                print("→ both limited, wait 30s for Tier1")
                time.sleep(30)
                result, _ = _call_groq_key(key1, prompt, "Groq1-retry")
                if result:
                    print("→ Groq1 retry OK")
                    return result
            else:
                print("→ skipped (Tier2, rate limited)")
                return {}'''

new = '''    model = GROQ_FAST_MODEL if fast else GROQ_MODEL
    result, rl1 = _call_groq_key(key1, prompt, "Groq1", model)
    if result:
        print("→ Groq1 OK")
        return result

    # Try Groq2 on ANY Groq1 miss (missing key, timeout, 500, exception —
    # not just a 429). Previously this was gated behind `if rl1`, so a
    # non-rate-limit Groq1 failure skipped Groq2 (and Cerebras/Gemini for
    # fast calls) entirely and went straight to FAILED.
    rl2 = False
    if key2:
        result, rl2 = _call_groq_key(key2, prompt, "Groq2", model)
        if result:
            print("→ Groq2 OK")
            return result

    if rl1 and rl2:
        # Both rate limited — set cooldown, only retry for Tier 1
        _rate_limited_until = time.time() + 30
        if not fast:
            print("→ both limited, wait 30s for Tier1")
            time.sleep(30)
            result, _ = _call_groq_key(key1, prompt, "Groq1-retry")
            if result:
                print("→ Groq1 retry OK")
                return result
        else:
            print("→ skipped (Tier2, rate limited)")
            return {}'''

assert old in content, "call_llm Groq fallback block not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_llm.py', 'w').write(content)
print('Done: Groq2 is now tried on any Groq1 failure, not only a 429.')
