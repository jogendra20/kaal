"""
kaal_event_classifier.py
Deterministic keyword-based classification of NSE/BSE announcements.
No LLM calls - this runs first and cheaply, before score_announcement()
spends an LLM call on anything.
"""
from kaal_config import (
    NSE_SKIP_EXACT, NSE_SKIP_EXTRA, NSE_TIER1_EXACT, NSE_TIER2_EXACT,
    SKIP_SUBJECTS, SKIP_DETAILS,
    TIER1_DETAIL_KEYWORDS, TIER2_DETAIL_KEYWORDS,
    TIER1_SUBJECTS, TIER2_SUBJECTS,
)

REGULATORY_SCRUTINY_KEYWORDS = [
    "reply to clarification", "clarification sought", "rumour verification",
    "news verification", "exchange has sought", "seeking clarification",
    "sought clarification",
]

CORPORATE_ACTION_SUSPENSION_KEYWORDS = [
    "trading suspension", "suspension of trading", "shall be suspended",
    "trading in the shares of the company",
]

CORPORATE_ACTION_STRUCTURAL_KEYWORDS = [
    "scheme of amalgamation", "scheme of arrangement", "amalgamated with",
    "merged with and into", "ceases to exist", "dissolved without winding up",
]


def classify_event_type(subject: str, details: str) -> str:
    """
    Returns 'REGULATORY_SCRUTINY', 'CORPORATE_ACTION', or 'MOMENTUM_CATALYST'.
    Only MOMENTUM_CATALYST is a normal tradeable setup - the other two get
    special handling in score_announcement() and _entry_plan().
    """
    full = (subject + " " + details).lower()

    if any(kw in full for kw in REGULATORY_SCRUTINY_KEYWORDS):
        return "REGULATORY_SCRUTINY"

    has_suspension = any(kw in full for kw in CORPORATE_ACTION_SUSPENSION_KEYWORDS)
    has_structural = any(kw in full for kw in CORPORATE_ACTION_STRUCTURAL_KEYWORDS)
    if has_suspension and has_structural:
        return "CORPORATE_ACTION"

    return "MOMENTUM_CATALYST"


def classify_announcement(subject: str, details: str) -> tuple:
    """Returns (category, base_score, tier)"""
    subj = subject.strip()
    subj_lower = subj.lower()
    det  = details.lower().strip()

    # Step 1: exact NSE desc match (highest precision)
    # AGM special case: if company is a subsidiary, don't skip — send to LLM
    if subj == "Shareholders meeting":
        return "AGM_POSSIBLE", 45, 2

    if subj in NSE_SKIP_EXACT:
        return "SKIP", 0, 3
    if subj in NSE_SKIP_EXTRA:
        return "SKIP", 0, 3

    # Disclosure under Takeover: skip all except genuine open offers
    if subj == "Disclosure under SEBI Takeover Regulations":
        det_low = det.lower()
        if any(kw in det_low for kw in ["open offer", "change of control"]):
            return "TAKEOVER_OPEN_OFFER", 70, 1
        return "SKIP", 0, 3

    if subj in NSE_TIER1_EXACT:
        cat = subj.upper().replace(" ", "_").replace("/","_")[:25]
        return cat, 72, 1
    if subj in NSE_TIER2_EXACT:
        cat = subj.upper().replace(" ", "_").replace("/","_")[:25]
        return cat, 50, 2

    # Step 2: keyword fallback for unknown desc values
    full = subj_lower + " " + det
    for kw in SKIP_SUBJECTS:
        if kw in subj_lower:
            return "SKIP", 0, 3
    for kw in SKIP_DETAILS:
        if kw in det:
            return "SKIP", 0, 3
    for kw in TIER1_DETAIL_KEYWORDS:
        if kw in full:
            cat = kw.upper().replace(" ", "_").replace("/", "_")[:20]
            return cat, 70, 1
    for kw in TIER2_DETAIL_KEYWORDS:
        if kw in full:
            cat = kw.upper().replace(" ", "_")[:20]
            return cat, 50, 2
    for kw in TIER1_SUBJECTS:
        if kw in subj_lower:
            return kw.upper().replace(" ", "_"), 68, 1
    for kw in TIER2_SUBJECTS:
        if kw in subj_lower:
            return kw.upper().replace(" ", "_"), 48, 2

    if len(subj.split()) <= 3:
        return "VAGUE", 40, 2
    return "GENERAL", 12, 3


# ── LLM SCORING PROMPT ───────────────────────────────────────────────────────
