# KAAL Devlog

### 2026-06-11
- first commit
- KAAL full codebase - pre upgrade
- KAAL upgrade - 6 LLM pipeline, staleness check, demerger fix, AGM subsidiary rule

### 2026-06-12
- fix: gemini model + pdf warnings + speed 146s
- fix: gemini json parser + pdf warnings + news momentum
- feat: network resilience - auto retry on internet drop
- fix: live VIX from NSE + GIFT Nifty 3-source fallback
- fix: macro data accuracy - correct close comparison + gold bad data filter

### 2026-06-13
- cleanup: remove BSE, deals, PIT, unsized order wins demoted to Tier2
- feat: results-specific LLM prompt with PAT growth, exceptional items, guidance
- feat: NSE pre-open data - gap boost + edge consumed filter
- feat: sector strength detector - hot/cold sector boost/penalty

### 2026-06-15
- fix: news momentum cap 62, order win Tier2 only, Gemini stricter, tighter reasons
- fix: news momentum hard cap after boosts, Gemini stricter max 3+3
- fix: Gemini judge working - 503 retry, merge logic, action field
- fix: Gemini fallback filter + raise Tier1 threshold to 75
- fix: strict fallback filter when Gemini 503, news momentum cap in velocity scorer
- fix: rewrite Gemini judge block cleanly, fallback filter working
- fix: gemini returns None on 503, judge returns empty list on failure
- fix: Gemini 429 quota handled same as 503 - triggers fallback

### 2026-06-16
- fix: RBLBANK stale open offer filter, small acquisition skip rule
- fix: stricter fallback filter, clarification skip, acquisition threshold, Tier2 cap 40
- KAAL v2 production ready - June 16 2026

### 2026-06-17
- feat: Chartink screener integration - gap up + 52W high + screener boost

### 2026-06-18
- feat: Chartink screener live, Telegram retry on network drop
- feat: proxy/indirect beneficiary map - NSE IPO, defence, pharma, EV, PSU bank
- fix: proxy import in morning, NSE IPO proxy working in production
- fix: all 4 Chartink screeners working - gap up, 52w high, volume breakout, momentum

### 2026-06-19
- feat: OI spurt detector - smart money positioning signal
- fix: proxy dedup working, clean rewrite, OI spurt integration
- fix: pre-filter 15 signals to Gemini, stricter judge rules
- fix: gemini judge clean rewrite - verdicts working correctly
- feat: negative proxy, tender buyback, results upgrade, USFDA, budget sector plays

### 2026-06-20
- fix: USFDA false positives, NSE IPO 5-day cooldown, buyback type fix
- fix: APLLTD 180-day exclusivity boost, USFDA false positive fix
- fix: NSE IPO 7-day cooldown, milestone-based triggers
- feat: new brief format - timestamp, score, pct change since trigger, freshness status
- fix: an_dt now passed through to signal dict for timestamp display
- fix: Cerebras as primary final judge (max_tokens 3000), Gemini as fallback
- fix: Cerebras reasoning_effort=none - eliminates token burn, judge now works reliably
- fix: an_dt now wired into USFDA signals for correct timestamp display

### 2026-06-21
- fix: kaal_evening.py - remove dead BSE/PIT/deals code, same cleanup as morning file
- fix: kaal_evening.py now saves brief to file (Telegram blocked till June 22)
- fix: MC RSS feed swapped to latestnews.xml (4→15 articles), removed dead CNBC18
- fix: remove MC RSS feed - both URLs confirmed serving stale Apr 2024 data

### 2026-06-22
- feat: Hindu Business Line RSS added as third source (90 articles total, replaces MC)

### 2026-06-23
- feat: Hindu Business Line RSS added as third source (90 articles total, replaces MC)

### 2026-06-29
- feat: yesterday change, catalyst age, already-moved warning in brief
- feat: EOD price tracking, catalyst-day move, opportunity classification (PRICED_IN/UNDERREACTED/CONSOLIDATING/IGNORED/ACTIVE)
- verified: opportunity classification working in production

### 2026-06-30
- feat: NSE bulk deal accumulation signal - clean net buys, fund-weighted scoring

### 2026-07-02
- fix: RSS freshness filter in proxy scanner (36h max), EV trigger tightened to national policy, postal ballot = stale skip, tender buyback detection improved
- fix: EV proxy tightened to national policy only, tender buyback detection expanded to PUBLIC_ANNOUNCEMENT cat
- fix: buyback type cap re-applied after LLM override, tender entry plan correct
- fix: SALE_OR_DISPOSAL hard skip if no deal value, buyback tender cap after LLM

### 2026-07-03
- fix: migrate Groq models - gpt-oss-20b (fast) + gpt-oss-120b (deep), deprecated llama models removed

### 2026-07-05
- fix: add response_format json_object to Groq calls for gpt-oss model compatibility
- fix: conditional json_object format for gpt-oss models, auto-add json instruction if missing
- feat: Mistral as primary fast LLM (reliable JSON), Groq gpt-oss-120b for deep calls only
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
- chore: remove 40 one-shot patch scripts (already applied, unused at runtime)
- Phase 0: split kaal_sources.py into kaal_http/kaal_sources/kaal_market_data
- remove one-time migration script
- Phase 0b: split kaal_scorer.py into event_classifier/scorer/deterministic_scorers
- remove one-time migration script

### 2026-07-21
- Phase 1: independent Momentum Engine (EOD factors + provider interface)
- fix: case-insensitive index name lookup in NSE index bhavcopy provider
- Phase 1: add sector-diversity cap (max 1/sector) to watchlist, fix TATAMOTORS->TMPV
- stop tracking bhavcopy cache - regenerable data, not source
- stop tracking bhavcopy cache - regenerable data, not source
- Phase 1: raise trend weight 0.15->0.30 after TCS downtrend ranked top-3
- FY27 results: Tier1 reclassification + dedicated Tavily result-season queries
- remove one-time patch script

### 2026-07-22
- Results growth-trend factor: capture+store PAT/revenue YoY the LLM already extracts, add self-relative trend scorer
- remove one-time patch script
- Add as_of_date to provider interface, prerequisite for backtesting
- Backtest script: walk-forward next-day-only evaluation of momentum picks
- Fix FakeProvider test double for as_of_date parameter
- Add per-day progress logging to backtest, trim lookback 120->75
- fix: kaal_deterministic_scorers.py missing os/re/json/datetime imports from Phase 0b split

### 2026-07-23
- Add Nifty benchmark + alpha calculation to backtest
- fix: INDEX_SYMBOL constant was never actually defined
- fix: add missing INDEX_SYMBOL constant
- remove duplicate INDEX_SYMBOL line
- Phase 2: Market Regime classification (VIX, expiry, trend/choppy via efficiency ratio, sector rotation, breadth, liquidity)
- Phase 2: display-only regime lines (VIX, sector breadth, Nifty trend) in morning scan
- Phase 3: Decision Engine (catalyst-led, momentum+regime as conviction filters)

### 2026-07-24
- Add deterministic staleness check for results announcements (STALE/FRESH/UNKNOWN)
- Add standalone FY27 news gatherer/relevance checker/report builder
- Wire FY27 news report into morning scan (display only)
- Add symbol tagging to FY27 news report (reuses today's own announcement data)
- Fix FY27 symbol tagging false positives: title-only matching + BSE exclusion

### 2026-07-25
- dedupe .gitignore entry
- Add safe Angel One connection test (login + profile check only, no order code exists)
- Add Angel One instrument token lookup (scrip master fetch + cache)
- Add Angel One intraday candle provider (unverified against live server yet)

### 2026-07-26
- Fix: skip weekends when resolving candle-data end date - root cause of the corrupted-looking data
- Real RVOL and VWAP position implementations (ORB, gap_quality still pending)
- Real ORB and gap_quality implementations - all four intraday factors now complete

### 2026-07-27
- Add live intraday factor display panel to run_momentum.py (informational only, not scored)
- Fix critical bug: intraday factors silently used stale prior-day data as if it were live (pre-market)
- Fix rate limit: fetch intraday bars once per symbol, reuse across all 4 factors

### 2026-07-28
- Add missing bars parameter to all 4 intraday factor functions (was only in run_momentum.py, not the functions themselves)
- Add retry-with-backoff for Angel One's rate-limit false-positives (known issue per their own forum)
- Broaden retry to cover network timeouts too, not just rate-limit errors (M&M failed with a timeout, not a rate limit, in the same live run)

### 2026-07-29
- All pushed

### 2026-08-05
- All

### 2026-08-08
- chore: ignore run artifacts and debug dumps
- docs: add DEVLOG.md generated from git history + devlog.py for future entries
- chore: untrack debug/stdout dumps, keep them local via .gitignore
- chore: keep fy27_backtest_results json tracked as evidence, not treated as disposable output
- chore: untrack watchlist snapshots - unused, generated locally, not needed in history
- chore: untrack watchlist snapshots - unused, generated locally, not needed in history


### 2026-08-20
- cleanup: removed superseded FY27 backtest drafts (fy27_backtest8q.py, v3/v4/v5) - results preserved in fy27_backtest_results_v*.json
- cleanup: removed raw stdout dumps (fy27_out_v1-v5.txt) - superseded by structured JSON results
- cleanup: removed backtest progress checkpoints + fy27_quarter_history_cache.json - regenerable scratch state
- cleanup: removed nse_cache.db - regenerable cache, same precedent as bhavcopy
- cleanup: removed patch_chartink_sort_fix.py (leftover one-shot patch, missed in Phase 0) + bse_test/nse_test debug probes
- cleanup: removed kpl_* pre-rename announcement fetchers + bse_full_list.py/json - superseded by kaal_sources.py/kaal_market_data.py, zero importers
- cleanup: removed one-off dated research dumps (observation_monday, movers_pattern_scan, analyze_movers, analyze_volume_positioning, delivery_rvol_check, volume_surge, weekend_results_momentum, timestamp_check, enrich_unexplained) - single-session analysis scripts, not reusable pipeline code
