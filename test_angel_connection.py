"""
test_angel_connection.py
Safe connection check ONLY. This file does not import, define, or call
ANY order-placement, order-modification, or order-cancellation
functionality. The only SmartConnect methods used below are
generateSession() (login) and getProfile() (read-only account info).
"""
import os
import sys

from load_env import load_env
from totp import totp_from_base32_secret

load_env(".env")

REQUIRED_VARS = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(empty)"
    return value[:keep] + "*" * max(0, len(value) - keep)


def main():
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"ABORT: missing required environment variable(s): {', '.join(missing)}")
        print("Check your .env file has all of: " + ", ".join(REQUIRED_VARS))
        sys.exit(1)

    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    pin = os.environ["ANGEL_PIN"]
    totp_secret = os.environ["ANGEL_TOTP_SECRET"]

    print(f"API key:     {_mask(api_key)}")
    print(f"Client code: {_mask(client_code)}")
    print(f"TOTP secret: {_mask(totp_secret)} (not the code itself, the secret used to generate it)")

    try:
        totp_code = totp_from_base32_secret(totp_secret)
    except Exception as e:
        print(f"ABORT: could not generate TOTP code from ANGEL_TOTP_SECRET: {e}")
        sys.exit(1)
    print(f"Generated TOTP code: {totp_code} (valid for ~30 seconds)")

    try:
        from SmartApi import SmartConnect
    except ImportError:
        print("ABORT: smartapi-python is not installed.")
        print("Run: pip install smartapi-python --break-system-packages")
        sys.exit(1)

    print("\nAttempting login...")
    obj = SmartConnect(api_key=api_key)
    try:
        session = obj.generateSession(client_code, pin, totp_code)
    except Exception as e:
        print(f"LOGIN FAILED (exception): {e}")
        sys.exit(1)

    if not session or not session.get("status"):
        print(f"LOGIN FAILED: {session}")
        sys.exit(1)

    print("LOGIN SUCCEEDED")
    print(f"  jwtToken:   {_mask(session['data'].get('jwtToken', ''), keep=8)}")
    print(f"  feedToken:  {_mask(session['data'].get('feedToken', ''), keep=8)}")

    try:
        profile = obj.getProfile(session["data"]["refreshToken"])
        if profile and profile.get("status"):
            pdata = profile.get("data", {})
            print(f"\nProfile check succeeded:")
            print(f"  Name:   {pdata.get('name', '(not returned)')}")
            print(f"  Email:  {_mask(pdata.get('email', ''))}")
            print(f"  Exchanges enabled: {pdata.get('exchanges', '(not returned)')}")
        else:
            print(f"\nProfile check returned unexpected response: {profile}")
    except Exception as e:
        print(f"\nProfile check failed (non-fatal, login itself already succeeded): {e}")

    print("\nDone. No orders were placed - this script cannot place orders.")


if __name__ == "__main__":
    main()
