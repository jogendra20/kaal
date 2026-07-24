"""
kaal_fy27_symbol_tagging.py
Symbol tagging for news articles, built from today's own NSE
announcement data (ann['sm_name'], ann['symbol']) rather than a new
static company database.

Known limitation: only tags a news article if that company ALSO has an
NSE announcement the same day. Most FY27 results/guidance news comes
with a same-day filing, so this covers the common case, not every case.
"""
import re


def build_symbol_lookup(announcements: list) -> dict:
    """Returns {company_name_lower: symbol} from today's announcements."""
    lookup = {}
    for ann in announcements or []:
        if not isinstance(ann, dict):
            continue
        symbol = ann.get("symbol", "")
        company_name = ann.get("sm_name", "")
        if symbol and company_name:
            lookup[company_name.lower().strip()] = symbol
    return lookup


_SUFFIX_PATTERN = re.compile(
    r'\s+(limited|ltd\.?|industries|inc\.?|corporation|corp\.?)\s*$', re.IGNORECASE
)


def _strip_suffix(name: str) -> str:
    return _SUFFIX_PATTERN.sub('', name).strip()


def _name_candidates(root: str) -> list:
    """
    Headlines commonly abbreviate a multi-word company name down to its
    first word or two. Try progressively shorter word-prefixes, longest
    first, down to a 2-word minimum (a single generic word alone would
    match far too many unrelated companies).
    """
    words = root.split()
    if len(words) < 2:
        return [root] if root else []
    return [' '.join(words[:i]) for i in range(len(words), 1, -1)]


def extract_symbol_from_text(text: str, symbol_lookup: dict) -> str:
    """
    Tries: 1) exact symbol as a standalone word in the text, then
    2) company name or a shortened word-prefix of it. Returns None if
    nothing matches - never guesses.
    """
    if not text:
        return None
    text_upper = text.upper()

    for company_name, symbol in symbol_lookup.items():
        if re.search(r'\b' + re.escape(symbol) + r'\b', text_upper):
            return symbol

    text_lower = text.lower()
    best_match = None
    best_len = 0
    for company_name, symbol in symbol_lookup.items():
        root = _strip_suffix(company_name)
        for candidate in _name_candidates(root):
            if candidate and len(candidate) >= 3 and candidate in text_lower:
                if len(candidate) > best_len:
                    best_match = symbol
                    best_len = len(candidate)
                break
    return best_match
