import requests
from kaal_config import TELEGRAM_TOKEN, TELEGRAM_CHAT

def send(msg: str):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        if r.status_code == 200:
            return True
        print(f"[TG] Failed {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[TG] Error: {e}")
        return False
