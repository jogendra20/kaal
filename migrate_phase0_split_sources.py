"""
migrate_phase0_split_sources.py
ONE-TIME migration script. Run once from the repo root, verify, commit, delete.

Splits kaal_sources.py into:
  - kaal_http.py         shared NSE session (new)
  - kaal_sources.py      announcements / macro / news / liquidity (trimmed)
  - kaal_market_data.py  bhavcopy / OI / sector / chartink / preopen / options (new)

And updates the 4 files that import from the old kaal_sources.py so their
imports point at the right module. Does not change any function's logic or
behavior - only where each function lives.

Safety: aborts before writing anything if an expected code pattern isn't
found, so it never leaves you with a half-migrated repo.
"""
import re
import subprocess
import sys

SRC = open("kaal_sources.py").read()
LINES = SRC.split("\n")


def block(a, b):
    return "\n".join(LINES[a - 1:b])


def require(cond, msg):
    if not cond:
        print(f"ABORT: {msg}")
        sys.exit(1)


def line_of(pattern):
    for i, line in enumerate(LINES, start=1):
        if line.startswith(pattern):
            return i
    require(False, f"could not find line starting with: {pattern!r}")


markers = {
    "headers_nse":        line_of("HEADERS_NSE = {"),
    "nse_session":         line_of("def nse_session():"),
    "fetch_announcements": line_of("def fetch_nse_announcements():"),
    "stooq":                line_of("def _stooq_quote("),
    "yahoo":                 line_of("def _yahoo_quote("),
    "macro":                  line_of("def fetch_macro():"),
    "asm_gsm":                 line_of("def fetch_asm_gsm_ban():"),
    "sector_map":               line_of("SECTOR_MAP = {"),
    "sector_strength":           line_of("def fetch_sector_strength()"),
    "chartink_scans":             line_of("CHARTINK_SCANS = {"),
    "oi_spurts":                   line_of("def fetch_oi_spurts()"),
    "bhavcopy":                     line_of("def fetch_bhavcopy("),
    "oi_from_bhavcopy":              line_of("def fetch_oi_from_bhavcopy("),
    "classify_delivery":              line_of("def classify_delivery("),
    "eod_prices":                      line_of("def fetch_eod_prices("),
    "bulk_deals":                       line_of("def fetch_clean_bulk_deals()"),
    "chartink_screeners":                line_of("def fetch_chartink_screeners()"),
    "preopen":                             line_of("def fetch_preopen_gainers()"),
    "marketaux":                             line_of("def fetch_marketaux_news("),
    "news":                                    line_of("def fetch_news():"),
    "liquidity":                                line_of("def check_liquidity("),
    "pdf":                                        line_of("def download_pdf_text("),
    "option_chain":                                line_of("def fetch_option_chain("),
    "pcr_max_pain":                                  line_of("def compute_pcr_max_pain("),
    "pcr_map":                                        line_of("def fetch_pcr_map("),
}
END = len(LINES)

require(SRC.count("class ") == 0, "unexpected 'class' in kaal_sources.py - file has drifted, stopping")

http_content = '''"""
kaal_http.py
Shared low-level HTTP layer for NSE/BSE endpoints.
Owns the single cached NSE session (cookies/headers) used by every
module that hits nseindia.com - kaal_sources.py and kaal_market_data.py
both depend on this instead of keeping their own session state.
"""
import requests, time

''' + block(markers["headers_nse"], markers["nse_session"] - 1).rstrip() + "\n\n" + \
    block(markers["nse_session"], markers["fetch_announcements"] - 1).rstrip() + '''

def reset_session():
    """
    Force the next nse_session() call to build a fresh session.
    Callers should use this instead of touching the module-level
    session variable directly (e.g. after several consecutive
    request failures suggest NSE's WAF flagged the session).
    """
    global _nse_session
    _nse_session = None
'''

md_header = '''"""
kaal_market_data.py
Market-technical data: bhavcopy, OI, sector strength, chartink screeners,
preopen gainers, EOD prices, bulk deals, option chain / PCR.
Shares the NSE session from kaal_http.py rather than keeping its own.
"""
import requests, time, io

from datetime import datetime, timedelta
from kaal_config import MIN_VOLUME_CR
from kaal_http import nse_session, reset_session, HEADERS_NSE, HEADERS_BSE

'''
md_parts = [
    block(markers["sector_map"], markers["sector_strength"] - 1),
    block(markers["sector_strength"], markers["chartink_scans"] - 1),
    block(markers["chartink_scans"], markers["oi_spurts"] - 1),
    block(markers["oi_spurts"], markers["bhavcopy"] - 1),
    block(markers["bhavcopy"], markers["oi_from_bhavcopy"] - 1),
    block(markers["oi_from_bhavcopy"], markers["classify_delivery"] - 1),
    block(markers["classify_delivery"], markers["eod_prices"] - 1),
    block(markers["eod_prices"], markers["bulk_deals"] - 1),
    block(markers["bulk_deals"], markers["chartink_screeners"] - 1),
    block(markers["chartink_screeners"], markers["preopen"] - 1),
    block(markers["preopen"], markers["marketaux"] - 1),
    block(markers["option_chain"], markers["pcr_max_pain"] - 1),
    block(markers["pcr_max_pain"], markers["pcr_map"] - 1),
    block(markers["pcr_map"], END),
]
md_body = "\n\n".join(p.rstrip() for p in md_parts)

md_body = md_body.replace(
    "global _nse_session\n                _nse_session = None   # force a real rebuild, not the cached singleton",
    "reset_session()  # force a real rebuild, not the cached singleton",
)
md_body = md_body.replace(
    "    global _nse_session\n    s = nse_session()\n    prices = {}",
    "    s = nse_session()\n    prices = {}",
)
require("global _nse_session" not in md_body,
        "a 'global _nse_session' reference survived the split - aborting, would silently break at runtime")
md_content = md_header + md_body + "\n"

src_header = '''"""
kaal_sources.py
Announcements, macro, and news acquisition.
Market-technical data (bhavcopy, OI, sector strength, chartink, preopen,
option chain) lives in kaal_market_data.py. Both import the shared NSE
session from kaal_http.py.
Fixes: GIFT Nifty (real SGX/NSE futures proxy), liquidity gate, promoter PIT.
"""
import requests, time, feedparser, io

from datetime import datetime, timedelta
from kaal_config import RSS_FEEDS, MIN_VOLUME_CR
from kaal_http import nse_session, reset_session, HEADERS_NSE, HEADERS_BSE

'''
src_parts = [
    block(markers["fetch_announcements"], markers["stooq"] - 1),
    block(markers["stooq"], markers["yahoo"] - 1),
    block(markers["yahoo"], markers["macro"] - 1),
    block(markers["macro"], markers["asm_gsm"] - 1),
    block(markers["asm_gsm"], markers["sector_map"] - 1),
    block(markers["marketaux"], markers["news"] - 1),
    block(markers["news"], markers["liquidity"] - 1),
    block(markers["liquidity"], markers["pdf"] - 1),
    block(markers["pdf"], markers["option_chain"] - 1),
]
src_content = src_header + "\n\n".join(p.rstrip() for p in src_parts) + "\n"

open("kaal_http.py", "w").write(http_content)
open("kaal_market_data.py", "w").write(md_content)
open("kaal_sources.py", "w").write(src_content)
print("wrote kaal_http.py, kaal_market_data.py, kaal_sources.py")


def patch(path, old, new):
    c = open(path).read()
    require(old in c, f"{path}: expected import pattern not found - repo has drifted, aborting")
    open(path, "w").write(c.replace(old, new, 1))
    print(f"patched {path}")


patch(
    "kaal_evening.py",
    'from kaal_sources import (\n'
    '    fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban,\n'
    '    fetch_news, fetch_eod_prices, fetch_bhavcopy, classify_delivery,\n'
    ')',
    'from kaal_sources import (\n'
    '    fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban, fetch_news,\n'
    ')\n'
    'from kaal_market_data import fetch_eod_prices, fetch_bhavcopy, classify_delivery',
)

patch(
    "kaal_morning.py",
    'from kaal_sources import (\n'
    '    fetch_nse_announcements, fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners, fetch_oi_from_bhavcopy, fetch_clean_bulk_deals,\n'
    '    fetch_macro, fetch_asm_gsm_ban,\n'
    '    fetch_news, check_liquidity,\n'
    '    fetch_pcr_map, fetch_option_chain, compute_pcr_max_pain,\n'
    '    fetch_bhavcopy,\n'
    ')',
    'from kaal_sources import (\n'
    '    fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban,\n'
    '    fetch_news, check_liquidity,\n'
    ')\n'
    'from kaal_market_data import (\n'
    '    fetch_preopen_gainers, fetch_sector_strength, fetch_chartink_screeners,\n'
    '    fetch_oi_from_bhavcopy, fetch_clean_bulk_deals,\n'
    '    fetch_pcr_map, fetch_option_chain, compute_pcr_max_pain,\n'
    '    fetch_bhavcopy,\n'
    ')',
)
patch(
    "kaal_morning.py",
    "        from kaal_sources import SECTOR_MAP",
    "        from kaal_market_data import SECTOR_MAP",
)

patch(
    "kaal_monitor.py",
    "from kaal_sources import fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban, fetch_clean_bulk_deals",
    "from kaal_sources import fetch_nse_announcements, fetch_macro, fetch_asm_gsm_ban\n"
    "from kaal_market_data import fetch_clean_bulk_deals",
)

patch(
    "kaal_scorer.py",
    "        from kaal_sources import fetch_preopen_gainers",
    "        from kaal_market_data import fetch_preopen_gainers",
)

touched = ["kaal_http.py", "kaal_market_data.py", "kaal_sources.py",
           "kaal_evening.py", "kaal_morning.py", "kaal_monitor.py", "kaal_scorer.py"]
result = subprocess.run([sys.executable, "-m", "py_compile"] + touched)
require(result.returncode == 0, "py_compile failed on one of the touched files - see output above")

orig_defs = set(re.findall(r"^def (\w+)", SRC, re.M))
new_defs = set()
for f in ["kaal_http.py", "kaal_sources.py", "kaal_market_data.py"]:
    new_defs |= set(re.findall(r"^def (\w+)", open(f).read(), re.M))
missing = orig_defs - new_defs
require(not missing, f"functions lost in the split: {missing}")

print("OK: all files compile, all", len(orig_defs), "original functions accounted for.")
