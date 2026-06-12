"""
kaal_network.py
Network resilience for KAAL.
If internet drops mid-run, waits and retries automatically.
"""
import time
import requests
from kaal_log import log

def wait_for_internet(max_wait_seconds: int = 300) -> bool:
    """
    Waits until internet is available.
    Checks every 10 seconds up to max_wait_seconds.
    Returns True if connected, False if timed out.
    """
    start = time.time()
    attempt = 0
    while time.time() - start < max_wait_seconds:
        try:
            requests.get("https://www.google.com", timeout=5)
            if attempt > 0:
                log(f"Internet restored after {int(time.time()-start)}s")
            return True
        except Exception:
            attempt += 1
            log(f"No internet — waiting 10s (attempt {attempt})...")
            time.sleep(10)
    log("Internet wait timed out after 5 minutes — aborting")
    return False


def safe_request(func, *args, retries: int = 3, wait: int = 10, **kwargs):
    """
    Wraps any requests call with retry + internet wait logic.
    Usage: safe_request(requests.get, url, timeout=10)
    """
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            log(f"Network error (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                if not wait_for_internet():
                    return None
            else:
                log(f"All {retries} attempts failed — skipping this call")
                return None
    return None
