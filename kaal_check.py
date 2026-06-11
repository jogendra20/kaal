import sys, os, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kaal_config import load_env
load_env()

results = {}

def check(name, fn):
    try:
        ok, msg = fn()
        status = "OK  " if ok else "FAIL"
        print(status + " " + name + ": " + msg)
        results[name] = ok
    except Exception as e:
        print("FAIL " + name + ": " + str(e))
        results[name] = False

def check_groq():
    key = os.environ.get("GROQ_API_KEY", "")
    if not key: return False, "Not set in env"
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "say hi"}], "max_tokens": 5},
        timeout=15
    )
    if r.status_code == 200:
        return True, "Working | model=llama-3.3-70b-versatile"
    return False, "HTTP " + str(r.status_code) + " " + r.json().get("error",{}).get("message","")

def check_gemini():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key: return False, "Not set in env"
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + key,
        json={"contents": [{"parts": [{"text": "say hi"}]}], "generationConfig": {"maxOutputTokens": 5}},
        timeout=15
    )
    if r.status_code == 200:
        return True, "Working | model=gemini-2.0-flash"
    if r.status_code == 429:
        return True, "Quota exhausted (resets midnight PST) — fallback only"
    return False, "HTTP " + str(r.status_code) + " " + str(r.json().get("error",{}).get("message",""))

def check_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token: return False, "TELEGRAM_BOT_TOKEN not set"
    if not chat:  return False, "TELEGRAM_CHAT_ID not set"
    r = requests.get("https://api.telegram.org/bot" + token + "/getMe", timeout=10)
    if r.status_code == 200:
        name = r.json().get("result",{}).get("username","?")
        return True, "Bot=@" + name + " | Chat=" + chat
    return False, "HTTP " + str(r.status_code)

def check_groq_key_env():
    key = os.environ.get("GROQ_API_KEY", "")
    if key: return True, "Present (" + key[:12] + "...)"
    return False, "Missing — run: export GROQ_API_KEY=your_key or add to ~/.bashrc"

def check_gemini_key_env():
    key = os.environ.get("GEMINI_API_KEY", "")
    if key: return True, "Present (" + key[:12] + "...)"
    return False, "Missing — run: export GEMINI_API_KEY=your_key or add to ~/.bashrc"

print()
print("=" * 50)
print("KAAL KEY CHECKER")
print("=" * 50)
print()
print("--- ENV ---")
check("GROQ_API_KEY",    check_groq_key_env)
check("GEMINI_API_KEY",  check_gemini_key_env)
print()
print("--- ENV ---")
check("GROQ_API_KEY_2",   lambda: (True, "Present (" + os.environ.get("GROQ_API_KEY_2","")[:12] + "...)") if os.environ.get("GROQ_API_KEY_2") else (False, "Missing"))
check("CEREBRAS_API_KEY", lambda: (True, "Present (" + os.environ.get("CEREBRAS_API_KEY","")[:12] + "...)") if os.environ.get("CEREBRAS_API_KEY") else (False, "Missing"))
print()
print("--- API CALLS ---")
check("Groq API",     check_groq)
check("Gemini API",   check_gemini)
def check_cerebras():
    key = os.environ.get("CEREBRAS_API_KEY", "")
    if not key: return False, "Not set in env"
    r = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "say hi"}], "max_tokens": 5},
        timeout=15
    )
    if r.status_code == 200: return True, "Working | model=llama-3.3-70b"
    return False, "HTTP " + str(r.status_code) + " " + str(r.json().get("error",{}).get("message",""))

check("Cerebras API",  check_cerebras)
check("Telegram Bot", check_telegram)
print()
print("=" * 50)
ok   = sum(1 for v in results.values() if v)
fail = sum(1 for v in results.values() if not v)
print("Passed: " + str(ok) + " | Failed: " + str(fail))
if fail == 0:
    print("All keys working. KAAL ready.")
else:
    print("Fix failing keys before running KAAL.")
print("=" * 50)
print()
