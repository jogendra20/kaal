# --- kaal_config.py: reclassify results keywords to Tier 1 ---
f = "kaal_config.py"
c = open(f).read()
old = '''    "qualified institutional placement", "qip",
    "rights issue",                # dilution signal — LLM scores direction
]

TIER2_DETAIL_KEYWORDS = [
    "financial results for the period", "quarterly results", "half yearly results",
    "resignation of", "cessation of", "appointment of", "appoints",'''
new = '''    "qualified institutional placement", "qip",
    "rights issue",                # dilution signal — LLM scores direction
    "financial results for the period", "quarterly results", "half yearly results",
    # moved from Tier2 (2026-07-21): results are the primary FY27 earnings-
    # season catalyst, want them scored with Tier1 urgency, not Tier2
]

TIER2_DETAIL_KEYWORDS = [
    "resignation of", "cessation of", "appointment of", "appoints",'''
assert old in c, "kaal_config.py TIER1/TIER2 block doesn't match - paste me the actual block"
open(f, "w").write(c.replace(old, new))
print("patched kaal_config.py")

# --- kaal_sources.py: add FY27 results-season news queries ---
f = "kaal_sources.py"
c = open(f).read()
old = '''        queries = [
            "NSE BSE stocks to buy today intraday",
            "NSE stocks breakout news today",
            "India stock market movers today",'''
new = '''        queries = [
            "NSE BSE stocks to buy today intraday",
            "NSE stocks breakout news today",
            "India stock market movers today",
            "FY27 Q1 results India stocks beat estimates",
            "India companies quarterly results today NSE",
            "Q1 FY27 earnings India stock market",'''
assert old in c, "kaal_sources.py tavily queries block doesn't match - paste me the actual block"
open(f, "w").write(c.replace(old, new))
print("patched kaal_sources.py")
