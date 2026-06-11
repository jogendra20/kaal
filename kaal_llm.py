"""
kaal_llm.py
LLM engine: Groq1 -> Groq2 -> Gemini (last resort)
"""
import json, re, os, time
import requests

GROQ_MODEL   = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"

_call_count = 0
MAX_LLM_CALLS_PER_RUN = 50


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
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(clean)


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
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
    }
    try:
        r = requests.post(url, json=body, timeout=25)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_json(text)
        print(f"[LLM] Gemini {r.status_code}: {r.text[:80]}")
    except Exception as e:
        print(f"[LLM] Gemini exception: {e}")
    return {}


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
    time.sleep(2.5)

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
        result = _call_gemini(prompt)
        if result:
            print("→ Gemini OK")
            return result

    print("→ FAILED")
    return {}


def reset_call_count():
    global _call_count
    _call_count = 0
