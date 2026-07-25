"""
angel_scrip_master.py
Angel One requires a numeric instrument token for candle-data requests,
not a plain symbol string - this file fetches their official
symbol<->token mapping and caches it locally (large file, updated
periodically, not re-fetched every run).
"""
import json
import os
import time
import requests

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "angel_scrip_master.json")
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60


def _fetch_and_cache() -> list:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    r = requests.get(SCRIP_MASTER_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    json.dump(data, open(CACHE_PATH, "w"))
    return data


def load_scrip_master(force_refresh: bool = False) -> list:
    if not force_refresh and os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_MAX_AGE_SECONDS:
            return json.load(open(CACHE_PATH))
    return _fetch_and_cache()


def build_token_lookup(scrip_master: list, exchange: str = "NSE") -> dict:
    """{bare_symbol: token} for equity instruments - matches the "name"
    field with instrumenttype empty (equity, not futures/options)."""
    lookup = {}
    for entry in scrip_master:
        if entry.get("exch_seg") != exchange:
            continue
        if entry.get("instrumenttype", "") != "":
            continue
        symbol = entry.get("symbol", "")
        name = entry.get("name", "")
        if symbol.endswith("-EQ") and name:
            lookup[name] = entry.get("token", "")
    return lookup


def get_token(symbol: str, exchange: str = "NSE", scrip_master: list = None) -> str:
    scrip_master = scrip_master if scrip_master is not None else load_scrip_master()
    lookup = build_token_lookup(scrip_master, exchange)
    return lookup.get(symbol)
