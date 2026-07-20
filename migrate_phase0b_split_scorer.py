"""
migrate_phase0b_split_scorer.py
ONE-TIME migration script. Run once, verify, commit, delete.

Splits kaal_scorer.py into:
  - kaal_event_classifier.py   deterministic keyword classification (new)
  - kaal_scorer.py              LLM-based announcement scorer (trimmed)
  - kaal_deterministic_scorers.py  the 9 non-LLM scoring strategies (new)
"""
import re
import subprocess
import sys

SRC = open("kaal_scorer.py").read()
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
    "reg_scrutiny":    line_of("REGULATORY_SCRUTINY_KEYWORDS = ["),
    "classify_event":   line_of("def classify_event_type("),
    "classify_ann":      line_of("def classify_announcement("),
    "build_results":      line_of("def _build_results_prompt("),
    "build_prompt":        line_of("def _build_prompt("),
    "score_announcement":   line_of("def score_announcement("),
    "score_bulk_deal":       line_of("def score_bulk_deal("),
    "score_promoter_pit":     line_of("def score_promoter_pit("),
    "noise_words":             line_of("_NOISE_WORDS = {"),
    "score_budget":             line_of("def score_budget_signals("),
    "score_usfda":               line_of("def score_usfda_signals("),
    "score_bulk_buying":           line_of("def score_bulk_buying("),
    "score_neg_proxy":              line_of("def score_negative_proxy("),
    "score_proxy":                   line_of("def score_proxy_signals("),
    "score_policy":                   line_of("def score_policy_signals("),
    "score_velocity":                  line_of("def score_news_velocity("),
}
END = len(LINES)

require(SRC.count("class ") == 0, "unexpected 'class' in kaal_scorer.py - file has drifted, stopping")

clf_header = '''"""
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

'''
clf_body = block(markers["reg_scrutiny"], markers["build_results"] - 1).rstrip()
clf_content = clf_header + clf_body + "\n"

scorer_header = '''"""
kaal_scorer.py
LLM-based announcement scorer. Builds a REASON CHAIN so you know WHY a
stock is bullish/bearish.
Deterministic keyword classification lives in kaal_event_classifier.py -
this file only holds the part that actually calls the LLM.
Every scored dict has:
  - score      : 0-100
  - tier       : 1 / 2 / 3
  - direction  : BULLISH / BEARISH / NEUTRAL
  - catalyst   : type of event
  - reason     : human-readable explanation (the "why")
  - signal_sources: list of what triggered it (announcement / bulk_deal / promoter / news)
"""
import re
from kaal_config import (
    TIER1_MIN_SCORE, TIER2_MIN_SCORE, SKIP_BELOW,
    FNO_UNIVERSE_HINT,
    PCR_BULLISH_THRESHOLD, PCR_BEARISH_THRESHOLD, MAX_PAIN_EXPIRY_WINDOW_DAYS,
    VWAP_EXTENDED_THRESHOLD_PCT, VWAP_DISCOUNT_THRESHOLD_PCT,
    MIN_VOLUME_CR,
)
from kaal_llm import call_llm
from kaal_sources import download_pdf_text
from kaal_event_classifier import classify_event_type, classify_announcement

'''
scorer_body = block(markers["build_results"], markers["score_bulk_deal"] - 1).rstrip()
scorer_content = scorer_header + scorer_body + "\n"

det_header = '''"""
kaal_deterministic_scorers.py
Every scoring strategy that does NOT call the LLM: bulk deals, promoter
pit, budget/policy/USFDA signal keyword scoring, negative proxy, proxy
signals, news velocity. Pure rule-based math on structured input -
matches the project rule that LLM is for classification only, never
for scoring.
"""
from kaal_config import TIER1_MIN_SCORE, SKIP_BELOW, FNO_UNIVERSE_HINT

'''
det_parts = [
    block(markers["score_bulk_deal"], markers["score_promoter_pit"] - 1),
    block(markers["score_promoter_pit"], markers["noise_words"] - 1),
    block(markers["noise_words"], markers["score_budget"] - 1),
    block(markers["score_budget"], markers["score_usfda"] - 1),
    block(markers["score_usfda"], markers["score_bulk_buying"] - 1),
    block(markers["score_bulk_buying"], markers["score_neg_proxy"] - 1),
    block(markers["score_neg_proxy"], markers["score_proxy"] - 1),
    block(markers["score_proxy"], markers["score_policy"] - 1),
    block(markers["score_policy"], markers["score_velocity"] - 1),
    block(markers["score_velocity"], END),
]
det_content = det_header + "\n\n".join(p.rstrip() for p in det_parts) + "\n"

open("kaal_event_classifier.py", "w").write(clf_content)
open("kaal_scorer.py", "w").write(scorer_content)
open("kaal_deterministic_scorers.py", "w").write(det_content)
print("wrote kaal_event_classifier.py, kaal_scorer.py, kaal_deterministic_scorers.py")


def patch(path, old, new):
    c = open(path).read()
    require(old in c, f"{path}: expected import pattern not found - repo has drifted, aborting")
    open(path, "w").write(c.replace(old, new, 1))
    print(f"patched {path}")


patch(
    "kaal_evening.py",
    "from kaal_scorer import (\n"
    "    score_announcement, score_bulk_deal,\n"
    "    score_promoter_pit, score_news_velocity,\n"
    ")",
    "from kaal_scorer import score_announcement\n"
    "from kaal_deterministic_scorers import (\n"
    "    score_bulk_deal, score_promoter_pit, score_news_velocity,\n"
    ")",
)

patch(
    "kaal_monitor.py",
    "from kaal_scorer import score_announcement, score_bulk_buying",
    "from kaal_scorer import score_announcement\n"
    "from kaal_deterministic_scorers import score_bulk_buying",
)

patch(
    "kaal_morning.py",
    "from kaal_scorer import (\n"
    "    classify_announcement, score_announcement,\n"
    "    score_bulk_deal, score_promoter_pit, score_news_velocity,\n"
    "    score_proxy_signals, score_negative_proxy, score_usfda_signals, score_budget_signals, score_policy_signals,\n"
    "    score_bulk_buying,\n"
    ")",
    "from kaal_event_classifier import classify_announcement\n"
    "from kaal_scorer import score_announcement\n"
    "from kaal_deterministic_scorers import (\n"
    "    score_bulk_deal, score_promoter_pit, score_news_velocity,\n"
    "    score_proxy_signals, score_negative_proxy, score_usfda_signals, score_budget_signals, score_policy_signals,\n"
    "    score_bulk_buying,\n"
    ")",
)
patch(
    "kaal_morning.py",
    "    from kaal_scorer import classify_announcement as _classify",
    "    from kaal_event_classifier import classify_announcement as _classify",
)

touched = ["kaal_event_classifier.py", "kaal_scorer.py", "kaal_deterministic_scorers.py",
           "kaal_evening.py", "kaal_morning.py", "kaal_monitor.py"]
result = subprocess.run([sys.executable, "-m", "py_compile"] + touched)
require(result.returncode == 0, "py_compile failed on one of the touched files - see output above")

orig_defs = set(re.findall(r"^def (\w+)", SRC, re.M))
new_defs = set()
for f in ["kaal_event_classifier.py", "kaal_scorer.py", "kaal_deterministic_scorers.py"]:
    new_defs |= set(re.findall(r"^def (\w+)", open(f).read(), re.M))
missing = orig_defs - new_defs
require(not missing, f"functions lost in the split: {missing}")

print("OK: all files compile, all", len(orig_defs), "original functions accounted for.")
