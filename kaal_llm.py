"""
kaal_llm.py
LLM engine: Groq1 -> Groq2 -> Gemini (last resort)
"""
import json, re, os, time
import requests

GROQ_MODEL   = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"

_call_count = 0
MAX_LLM_CALLS_PER_RUN = 30


def _load_env():
    if os.environ.get("GROQ_API_KEY"):
        return
    for path in [
        os.path.expanduser("~/kaal/kaal_v2/kaal/.env"),
        os.path.expanduser("~/kaal_project/.env"),
        os.path.join(os.path.dirname(__file__), ".env"),
    ]:
        if os.path.exists(path):
            for line in open(path):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break


def _parse_json(text: str) -> dict:
    clean = re.sub(r"```json|```", "", text).strip()
    # Try full parse first
    try:
        return json.loads(clean)
    except Exception:
        pass
    # Try extracting first JSON object
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    # Try extracting JSON array
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    # Last resort: fix common issues
    try:
        fixed = re.sub(r",\s*([}\]])", r"", clean)  # trailing commas
        fixed = re.sub(r"'([^']*)':", r'"":', fixed)  # single quotes
        return json.loads(fixed)
    except Exception:
        pass
    return {}


def _call_groq_key(key: str, prompt: str, label: str) -> tuple:
    """Returns (result_dict, rate_limited_bool)"""
    if not key:
        return {}, False
    safe_prompt = prompt if "json" in prompt.lower() else prompt + "\n\nRespond in json format."
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": safe_prompt}],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=body, timeout=20
        )
        if r.status_code == 200:
            return _parse_json(r.json()["choices"][0]["message"]["content"]), False
        if r.status_code == 429:
            return {}, True  # signal rate limited
        print(f"[LLM] {label} {r.status_code}: {r.text[:80]}")
    except Exception as e:
        print(f"[LLM] {label} exception: {e}")
    return {}, False


def _call_cerebras(prompt: str) -> dict:
    _load_env()
    key = os.environ.get("CEREBRAS_API_KEY", "")
    if not key:
        return {}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": "zai-glm-4.7",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 3000,
    }
    try:
        r = requests.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers=headers, json=body, timeout=25
        )
        if r.status_code == 200:
            choice = r.json()["choices"][0]
            msg = choice["message"]
            text = msg.get("content", "") or ""
            if not text.strip():
                # Truncated before content — try reasoning as last resort
                text = msg.get("reasoning", "") or ""
            if not text.strip():
                fr = choice.get("finish_reason")
                print(f"[LLM] Cerebras empty content (finish_reason={fr})")
                return {}
            return _parse_json(text)
        print(f"[LLM] Cerebras {r.status_code}: {r.text[:80]}")
    except Exception as e:
        print(f"[LLM] Cerebras exception: {e}")
    return {}


def _call_gemini(prompt: str) -> dict:
    _load_env()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return {}
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000},
    }
    try:
        r = requests.post(url, json=body, timeout=25)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_json(text)
        elif r.status_code in (503, 429):
            print(f"[LLM] Gemini {r.status_code} — retrying in 5s...")
            time.sleep(5)
            r2 = requests.post(url, json=body, timeout=25)
            if r2.status_code == 200:
                text = r2.json()["candidates"][0]["content"]["parts"][0]["text"]
                return _parse_json(text)
            print(f"[LLM] Gemini 503 retry failed")
            return None
        print(f"[LLM] Gemini {r.status_code}: {r.text[:80]}")
        return None
    except Exception as e:
        print(f"[LLM] Gemini exception: {e}")
    return None


# Track if we're in rate-limit cooldown
_rate_limited_until = 0

def call_llm(prompt: str, fast: bool = False) -> dict:
    global _call_count, _rate_limited_until
    if _call_count >= MAX_LLM_CALLS_PER_RUN:
        return {}
    _call_count += 1
    _load_env()

    key1 = os.environ.get("GROQ_API_KEY_2", "")
    key2 = os.environ.get("GROQ_API_KEY", "")

    print(f"[LLM] #{_call_count}{' fast' if fast else ''}", end=" ")

    # If we know we're rate limited and it's a fast (Tier2) call, skip immediately
    if fast and time.time() < _rate_limited_until:
        remaining = int(_rate_limited_until - time.time())
        print(f"→ skipped (rate limit cooldown {remaining}s)")
        return {}

    # Pace calls: 2.5s between calls to stay under 30 RPM
    time.sleep(1.5)

    result, rl1 = _call_groq_key(key1, prompt, "Groq1")
    if result:
        print("→ Groq1 OK")
        return result

    if rl1 and key2:
        result, rl2 = _call_groq_key(key2, prompt, "Groq2")
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
                return {}

    if not fast:
        result = _call_cerebras(prompt)
        if result:
            print("→ Cerebras OK")
            return result
        result = _call_gemini(prompt)
        if result:
            print("→ Gemini OK")
            return result

    print("→ FAILED")
    return {}


def _build_judge_prompt(signals: list, macro: dict) -> str:
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
        f"\n\nMARKET: {macro_text}"
        f"\n\nSignals:\n{signals_text}"
        f"\n\nReturn ONLY a JSON array in this exact format (no markdown):\n{example}"
        "\n\nSTRICT RULES:"
        "\n- NEWS_MOMENTUM = SKIP always"
        "\n- OI_SPURT alone = SKIP"
        "\n- SCREENER alone = SKIP"
        "\n- ORDER_WIN without size = SKIP"
        "\n- Score < 70 = SKIP"
        "\n- MAXIMUM 2 BUY_PULLBACK"
        "\n- MAXIMUM 3 WATCH"
        "\n- Everything else = SKIP"
        "\n- When in doubt = SKIP"
    )


def _merge_judge_verdicts(signals: list, ranked: list, source_name: str) -> list:
    if not ranked:
        return []
    sample = [(r.get("symbol"), r.get("action")) for r in ranked[:5]]
    print(f"[LLM] {source_name} verdicts: {sample}")
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
        s["reason"] = f"[{action}] {g.get("final_reason", s.get("reason",""))}"
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


def search_staleness(symbol: str, catalyst: str) -> dict:
    """
    Use Tavily or Serper to check if catalyst is stale.
    Returns {"is_fresh": bool, "note": str}
    """
    _load_env()
    query = f"{symbol} {catalyst.replace('_',' ')} NSE announcement latest"

    # Try Tavily first
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query, "max_results": 3},
                timeout=10
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                snippets = " ".join(r.get("content", "") for r in results[:3])[:500]
                # Simple heuristic: if old dates found, likely stale
                stale_signals = ["weeks ago", "last month", "announced in", "previously"]
                is_stale = any(s in snippets.lower() for s in stale_signals)
                return {"is_fresh": not is_stale, "note": snippets[:200]}
        except Exception as e:
            print(f"[SEARCH] Tavily error: {e}")

    # Fallback to Serper
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": 3},
                timeout=10
            )
            if r.status_code == 200:
                items = r.json().get("organic", [])
                snippets = " ".join(i.get("snippet", "") for i in items[:3])[:500]
                stale_signals = ["weeks ago", "last month", "announced in", "previously"]
                is_stale = any(s in snippets.lower() for s in stale_signals)
                return {"is_fresh": not is_stale, "note": snippets[:200]}
        except Exception as e:
            print(f"[SEARCH] Serper error: {e}")

    return {"is_fresh": True, "note": "search unavailable"}


def reset_call_count():
    global _call_count
    _call_count = 0
