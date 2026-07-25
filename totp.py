"""
totp.py
Minimal RFC 6238 TOTP implementation - stdlib only, no pyotp dependency.
Verified against the RFC's own published test vectors.
"""
import base64
import hmac
import struct
import time


def _hotp(key_bytes: bytes, counter: int, digits: int = 6, digestmod='sha1') -> str:
    counter_bytes = struct.pack('>Q', counter)
    h = hmac.new(key_bytes, counter_bytes, digestmod).digest()
    offset = h[-1] & 0x0F
    truncated = struct.unpack('>I', h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def totp_from_raw_key(key_bytes: bytes, for_time: int = None, digits: int = 6,
                       step: int = 30, digestmod='sha1') -> str:
    t = for_time if for_time is not None else int(time.time())
    counter = t // step
    return _hotp(key_bytes, counter, digits, digestmod)


def totp_from_base32_secret(secret_b32: str, for_time: int = None,
                             digits: int = 6, step: int = 30) -> str:
    secret_b32 = secret_b32.strip().upper()
    secret_b32 += '=' * (-len(secret_b32) % 8)
    key_bytes = base64.b32decode(secret_b32)
    return totp_from_raw_key(key_bytes, for_time, digits, step, 'sha1')
