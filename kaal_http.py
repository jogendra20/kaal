"""
kaal_http.py
Shared low-level HTTP layer for NSE/BSE endpoints.
Owns the single cached NSE session (cookies/headers) used by every
module that hits nseindia.com - kaal_sources.py and kaal_market_data.py
both depend on this instead of keeping their own session state.
"""
import requests, time

HEADERS_NSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
    "Referer":    "https://www.nseindia.com",
}
HEADERS_BSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
    "Origin":     "https://www.bseindia.com",
    "Referer":    "https://www.bseindia.com/",
}

_nse_session = None

def nse_session():
    global _nse_session
    if _nse_session is None:
        s = requests.Session()
        s.headers.update(HEADERS_NSE)
        try:
            s.get("https://www.nseindia.com", timeout=15)
            time.sleep(1)
        except Exception:
            pass
        _nse_session = s
    return _nse_session


# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────

def reset_session():
    """
    Force the next nse_session() call to build a fresh session.
    Callers should use this instead of touching the module-level
    session variable directly (e.g. after several consecutive
    request failures suggest NSE's WAF flagged the session).
    """
    global _nse_session
    _nse_session = None
