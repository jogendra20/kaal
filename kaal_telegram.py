import requests
from kaal_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS

def _send_to_one(chat_id: str, msg: str) -> bool:
    import time
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )
            if r.status_code == 200:
                return True
            print(f"[TG] Failed for {chat_id} {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            print(f"[TG] Error for {chat_id}, attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5)
    return False


def send(msg: str) -> bool:
    """
    Sends to every chat_id in TELEGRAM_CHAT_IDS. One recipient failing
    (e.g. they blocked the bot) doesn't stop delivery to the others.
    Returns True only if ALL recipients received it.
    """
    if not TELEGRAM_CHAT_IDS:
        print("[TG] No chat IDs configured - nothing sent")
        return False
    results = [_send_to_one(cid, msg) for cid in TELEGRAM_CHAT_IDS]
    if not all(results):
        failed = [cid for cid, ok in zip(TELEGRAM_CHAT_IDS, results) if not ok]
        print(f"[TG] Delivery failed for: {failed}")
    return all(results)
