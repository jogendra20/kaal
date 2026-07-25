"""
angel_session.py
Shared Angel One login - factored out so the connection test and the
intraday provider use the same, already-verified login path.
"""
import os

from load_env import load_env
from totp import totp_from_base32_secret

REQUIRED_VARS = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]


def get_authenticated_client(env_path: str = ".env"):
    load_env(env_path)
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing environment variable(s): {', '.join(missing)}")

    from SmartApi import SmartConnect

    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    pin = os.environ["ANGEL_PIN"]
    totp_secret = os.environ["ANGEL_TOTP_SECRET"]

    totp_code = totp_from_base32_secret(totp_secret)
    obj = SmartConnect(api_key=api_key)
    session = obj.generateSession(client_code, pin, totp_code)

    if not session or not session.get("status"):
        raise RuntimeError(f"Angel One login failed: {session}")

    return obj
