# KAAL Devlog

### 2026-06-11
- first commit

### 2026-06-11
- KAAL full codebase - pre upgrade

### 2026-06-11
- KAAL upgrade - 6 LLM pipeline, staleness check, demerger fix, AGM subsidiary rule

### 2026-06-12
- fix: gemini model + pdf warnings + speed 146s

### 2026-06-12
- fix: gemini json parser + pdf warnings + news momentum

### 2026-06-12
- feat: network resilience - auto retry on internet drop

### 2026-06-12
- fix: live VIX from NSE + GIFT Nifty 3-source fallback

### 2026-06-12
- fix: macro data accuracy - correct close comparison + gold bad data filter

### 2026-06-13
- cleanup: remove BSE, deals, PIT, unsized order wins demoted to Tier2

### 2026-06-13
- feat: results-specific LLM prompt with PAT growth, exceptional items, guidance

### 2026-06-13
- feat: NSE pre-open data - gap boost + edge consumed filter

### 2026-06-13
- feat: sector strength detector - hot/cold sector boost/penalty

### 2026-06-15
- fix: news momentum cap 62, order win Tier2 only, Gemini stricter, tighter reasons

### 2026-06-15
- fix: news momentum hard cap after boosts, Gemini stricter max 3+3

### 2026-06-15
- fix: Gemini judge working - 503 retry, merge logic, action field

### 2026-06-15
- fix: Gemini fallback filter + raise Tier1 threshold to 75

### 2026-06-15
- fix: strict fallback filter when Gemini 503, news momentum cap in velocity scorer

### 2026-06-15
- fix: rewrite Gemini judge block cleanly, fallback filter working

### 2026-06-15
- fix: gemini returns None on 503, judge returns empty list on failure

### 2026-06-15
- fix: Gemini 429 quota handled same as 503 - triggers fallback

### 2026-06-16
- fix: RBLBANK stale open offer filter, small acquisition skip rule

### 2026-06-16
- fix: stricter fallback filter, clarification skip, acquisition threshold, Tier2 cap 40

### 2026-06-16
- KAAL v2 production ready - June 16 2026

### 2026-06-17
- feat: Chartink screener integration - gap up + 52W high + screener boost

### 2026-06-18
- feat: Chartink screener live, Telegram retry on network drop

### 2026-06-18
- feat: proxy/indirect beneficiary map - NSE IPO, defence, pharma, EV, PSU bank

### 2026-06-18
- fix: proxy import in morning, NSE IPO proxy working in production

### 2026-06-18
- fix: all 4 Chartink screeners working - gap up, 52w high, volume breakout, momentum

### 2026-06-19
- feat: OI spurt detector - smart money positioning signal

### 2026-06-19
- fix: proxy dedup working, clean rewrite, OI spurt integration

### 2026-06-19
- fix: pre-filter 15 signals to Gemini, stricter judge rules

### 2026-06-19
- fix: gemini judge clean rewrite - verdicts working correctly

### 2026-06-19
- feat: negative proxy, tender buyback, results upgrade, USFDA, budget sector plays

### 2026-06-20
- fix: USFDA false positives, NSE IPO 5-day cooldown, buyback type fix

### 2026-06-20
- fix: APLLTD 180-day exclusivity boost, USFDA false positive fix

### 2026-06-20
- fix: NSE IPO 7-day cooldown, milestone-based triggers

### 2026-06-20
- feat: new brief format - timestamp, score, pct change since trigger, freshness status

### 2026-06-20
- fix: an_dt now passed through to signal dict for timestamp display

### 2026-06-20
- fix: Cerebras as primary final judge (max_tokens 3000), Gemini as fallback

### 2026-06-20
- fix: Cerebras reasoning_effort=none - eliminates token burn, judge now works reliably

### 2026-06-20
- fix: an_dt now wired into USFDA signals for correct timestamp display

### 2026-06-21
- fix: kaal_evening.py - remove dead BSE/PIT/deals code, same cleanup as morning file

### 2026-06-21
- fix: kaal_evening.py now saves brief to file (Telegram blocked till June 22)

### 2026-06-21
- fix: MC RSS feed swapped to latestnews.xml (4→15 articles), removed dead CNBC18

### 2026-06-21
- fix: remove MC RSS feed - both URLs confirmed serving stale Apr 2024 data

### 2026-06-22
- feat: Hindu Business Line RSS added as third source (90 articles total, replaces MC)

### 2026-06-23
- feat: Hindu Business Line RSS added as third source (90 articles total, replaces MC)

### 2026-06-29
- feat: yesterday change, catalyst age, already-moved warning in brief

### 2026-06-29
- feat: EOD price tracking, catalyst-day move, opportunity classification (PRICED_IN/UNDERREACTED/CONSOLIDATING/IGNORED/ACTIVE)

### 2026-06-29
- verified: opportunity classification working in production

### 2026-06-30
- feat: NSE bulk deal accumulation signal - clean net buys, fund-weighted scoring

### 2026-07-02
- fix: RSS freshness filter in proxy scanner (36h max), EV trigger tightened to national policy, postal ballot = stale skip, tender buyback detection improved

### 2026-07-02
- fix: EV proxy tightened to national policy only, tender buyback detection expanded to PUBLIC_ANNOUNCEMENT cat

### 2026-07-02
- fix: buyback type cap re-applied after LLM override, tender entry plan correct

### 2026-07-02
- fix: SALE_OR_DISPOSAL hard skip if no deal value, buyback tender cap after LLM

### 2026-07-03
- fix: migrate Groq models - gpt-oss-20b (fast) + gpt-oss-120b (deep), deprecated llama models removed

### 2026-07-05
- fix: add response_format json_object to Groq calls for gpt-oss model compatibility

### 2026-07-05
- fix: conditional json_object format for gpt-oss models, auto-add json instruction if missing

### 2026-07-05
- feat: Mistral as primary fast LLM (reliable JSON), Groq gpt-oss-120b for deep calls only

### 2026-07-05
- feat: Mistral as primary fast LLM - no more Groq JSON 400 errors, Yahoo timeout fix

### 2026-07-07
- fix: Mistral as primary for both fast and deep calls, Groq gpt-oss as fallback only

### 2026-07-08
- feat: NSE bhavcopy delivery % integration - classify_delivery, evening stores data, morning displays it

### 2026-07-09
- patching all

### 2026-07-15
- For time pass

### 2026-07-17
- New

### 2026-07-20
- Thanks

### 2026-07-20
- chore: remove 40 one-shot patch scripts (already applied, unused at runtime)

### 2026-07-20
- Phase 0: split kaal_sources.py into kaal_http/kaal_sources/kaal_market_data

### 2026-07-20
- remove one-time migration script

### 2026-07-20
- Phase 0b: split kaal_scorer.py into event_classifier/scorer/deterministic_scorers

### 2026-07-20
- remove one-time migration script

### 2026-07-21
- Phase 1: independent Momentum Engine (EOD factors + provider interface)

### 2026-07-21
- fix: case-insensitive index name lookup in NSE index bhavcopy provider

### 2026-07-21
- Phase 1: add sector-diversity cap (max 1/sector) to watchlist, fix TATAMOTORS->TMPV

### 2026-07-21
- stop tracking bhavcopy cache - regenerable data, not source

### 2026-07-21
- stop tracking bhavcopy cache - regenerable data, not source

### 2026-07-21
- Phase 1: raise trend weight 0.15->0.30 after TCS downtrend ranked top-3

### 2026-07-21
- FY27 results: Tier1 reclassification + dedicated Tavily result-season queries

### 2026-07-21
- remove one-time patch script

### 2026-07-22
- Results growth-trend factor: capture+store PAT/revenue YoY the LLM already extracts, add self-relative trend scorer

### 2026-07-22
- remove one-time patch script

### 2026-07-22
- Add as_of_date to provider interface, prerequisite for backtesting

### 2026-07-22
- Backtest script: walk-forward next-day-only evaluation of momentum picks

### 2026-07-22
- Fix FakeProvider test double for as_of_date parameter

### 2026-07-22
- Add per-day progress logging to backtest, trim lookback 120->75

### 2026-07-22
- fix: kaal_deterministic_scorers.py missing os/re/json/datetime imports from Phase 0b split

### 2026-07-23
- Add Nifty benchmark + alpha calculation to backtest

### 2026-07-23
- fix: INDEX_SYMBOL constant was never actually defined

### 2026-07-23
- fix: add missing INDEX_SYMBOL constant

### 2026-07-23
- remove duplicate INDEX_SYMBOL line

### 2026-07-23
- Phase 2: Market Regime classification (VIX, expiry, trend/choppy via efficiency ratio, sector rotation, breadth, liquidity)

### 2026-07-23
- Phase 2: display-only regime lines (VIX, sector breadth, Nifty trend) in morning scan

### 2026-07-23
- Phase 3: Decision Engine (catalyst-led, momentum+regime as conviction filters)

### 2026-07-24
- Add deterministic staleness check for results announcements (STALE/FRESH/UNKNOWN)

### 2026-07-24
- Add standalone FY27 news gatherer/relevance checker/report builder

### 2026-07-24
- Wire FY27 news report into morning scan (display only)

### 2026-07-24
- Add symbol tagging to FY27 news report (reuses today's own announcement data)

### 2026-07-24
- Fix FY27 symbol tagging false positives: title-only matching + BSE exclusion

### 2026-07-25
- dedupe .gitignore entry

### 2026-07-25
- Add safe Angel One connection test (login + profile check only, no order code exists)

### 2026-07-25
- Add Angel One instrument token lookup (scrip master fetch + cache)

### 2026-07-25
- Add Angel One intraday candle provider (unverified against live server yet)

### 2026-07-26
- Fix: skip weekends when resolving candle-data end date - root cause of the corrupted-looking data

### 2026-07-26
- Real RVOL and VWAP position implementations (ORB, gap_quality still pending)

### 2026-07-26
- Real ORB and gap_quality implementations - all four intraday factors now complete

### 2026-07-27
- Add live intraday factor display panel to run_momentum.py (informational only, not scored)

### 2026-07-27
- Fix critical bug: intraday factors silently used stale prior-day data as if it were live (pre-market)

### 2026-07-27
- Fix rate limit: fetch intraday bars once per symbol, reuse across all 4 factors

### 2026-07-28
- Add missing bars parameter to all 4 intraday factor functions (was only in run_momentum.py, not the functions themselves)

### 2026-07-28
- Add retry-with-backoff for Angel One's rate-limit false-positives (known issue per their own forum)

### 2026-07-28
- Broaden retry to cover network timeouts too, not just rate-limit errors (M&M failed with a timeout, not a rate limit, in the same live run)

### 2026-07-29
- All pushed

### 2026-08-05
- All
