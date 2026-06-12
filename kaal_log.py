"""
kaal_log.py
Centralized logging for KAAL.
"""
import os
from datetime import datetime

LOG_DIR  = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "kaal.log")

def log(msg: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def log_section(title: str):
    log(f"{'='*10} {title} {'='*10}")

def get_today_log() -> str:
    if not os.path.exists(LOG_FILE):
        return "No logs yet."
    lines = open(LOG_FILE).readlines()
    today = datetime.now().strftime("%Y-%m-%d")
    return "".join(l for l in lines if l.startswith(f"[{today}"))
