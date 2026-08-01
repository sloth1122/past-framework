# Changelog

All notable changes to the PAST Framework are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [v0.2.0] — 2026-08-01 — Backtest Integrity Update

### Reviewer
**Brian** — code review of initial backtest harness, 2026-08-01.

### Summary
Two critical backtest integrity fixes to eliminate target leakage and
replace the stub Judge with real LLM-based verification. These changes
ensure the backtest faithfully simulates how the live Trading Arena
agents (Alpha, Beta, Judge, Rocky) actually behave.

---

### Fixed — Target Leakage (Brian's Recommendation #1)

**Problem:** `run_backtest.py` `fetch_data()` computed 52-week high/low
from the **entire dataset**, including prices *after* the trade date.
This leaked future information into Beta's entry decisions — the agent
"knew" the eventual range before the backtest window ended.

```python
# BEFORE (leaky — uses future data):
low52 = df['Close'].min()    # min across the FULL backtest window
high52 = df['Close'].max()   # max across the FULL backtest window
```

**Fix:** All indicators at trade day D now use **only** data from the
52 weeks *prior to* D. The engine fetches a lookback buffer before the
backtest window and computes rolling indicators by construction:

```python
# AFTER (no leakage — rolling window only):
df['Low52'] = df['Close'].rolling(252).min()    # backward-looking
df['High52'] = df['Close'].rolling(252).max()   # backward-looking
```

Entry decisions in `backtest_v2.py` read per-row rolling values
(`row['Low52']`, `row['High52']`) instead of dataset-wide statistics.
No trade at day D can see any price after day D.

**Files changed:** `backtest_v2.py` (new), replaces `run_backtest.py` runner

---

### Added — LLM-in-the-Loop Judge (Brian's Recommendation #2)

**Problem:** The original `judge_evaluate()` in `backtest_sim.py` was a
hardcoded Python function — not an LLM call. It auto-passed 5 of 13
checklist points and used simple thresholds. This did not simulate the
real Judge (Claude Fable 5) which reasons about catalysts, thesis
integrity, and PAST alignment.

```python
# BEFORE (stub — not real verification):
# 9-13: Simplified - pass on options, catalyst, state file honesty, etc.
score += 5; notes.append('Remaining checks pass ✓')
```

**Fix:** Judge and Rocky are now **real LLM calls** to a local model
(deepseek-r1:32b via Ollama — free, no API costs). The Judge receives
the full trade context (rolling indicators, PAST scores, thesis) and
returns a scored JSON verdict with per-check reasoning. Fail-safe: if
the LLM errors, the trade is **rejected** (never auto-approved).

```python
# AFTER (real LLM reasoning via Ollama):
result = _call_ollama(JUDGE_MODEL, prompt)
# Returns: {"score": 11, "approved": true, "checks_failed": [3, 10],
#           "reasoning": "Lacks earnings confirmation and catalyst"}
```

**New files:**
- `backtest/llm_judge.py` — LLM Judge (13-point checklist) + LLM Rocky (PAST tuning)
- `backtest/backtest_v2.py` — Rolling-window runner with LLM-in-the-loop

**Model:** deepseek-r1:32b (local via Ollama). Cost: $0.00.

---

### Verified
- 2-week test on OKLO (2026-07-01 → 2026-07-14) ran end-to-end
- Judge returned valid scored JSON verdicts (score 11/13, 2 checks failed)
- Judge caught different issues on different trades based on actual data
- No target leakage — rolling window confirmed
- Cost: $0.00 (local model)

---

## [v0.1.0] — 2026-07-31 — Initial Release

- PAST research paper v2
- Backtest harness (yfinance + Python): +11.7% over 6.5 months
- Agent skills: Alpha (Renaissance), Beta (Atreides/Baker), Judge (13-point)
- SpaceX IPO simulation case study
- MIT License
