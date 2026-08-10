# Changelog

All notable changes to the PAST Framework are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [v0.3.0] — 2026-08-10 — PAST Persistence Fix + Trait Split

### Summary

Two changes driven by live Trading Arena operations (Week 3–4, production
mode): (1) a compliance gap where Agent Alpha failed to persist its PAST
index in state files for 3 consecutive Rocky review cycles, and (2) the
split of the single "Patience" trait into two independent dimensions
(Entry Patience + Hold Duration) for finer-grained drift detection.

---

### Fixed — PAST Index Persistence Compliance Gap

**Problem:** Rocky's coaching framework depends on reading each agent's
full PAST index (all 8 traits) from the state file every session to audit
personality drift. Agent Beta correctly persisted its PAST index with a
per-session drift check. **Agent Alpha did not** — its state file contained
no PAST index section at all. Only Risk (3/7) and Conviction (2/7) were
discoverable, and only by digging through historical dashboard data.

Rocky flagged this as a compliance gap in **3 consecutive weekly reviews**
(7/25, 8/1, 8/8), each time directing Alpha to persist the full index.
Alpha's cron prompt lacked a step for writing the PAST index, so the
directive was never executed. Rocky set a hard deadline of 8/15 — if still
unresolved, it would escalate to a formal process violation.

**Impact:** Without the persisted index, Rocky could not audit whether
Alpha's personality was drifting from its assigned profile. This became
critical when Alpha executed its first real trade (CVS, 8/10) — the exact
moment when drift detection matters most.

**Fix (3 layers):**

1. **Immediate:** Added full PAST index with drift check to Alpha's state
   file (`state/agent_alpha/state.md`), matching Beta's format.

2. **Permanent (cron prompt):** Added `STEP 9 — PAST INDEX PERSISTENCE`
   to Alpha's cron prompt in `update_cron_pretrade_judge.py`. Alpha must
   now write all 8 traits + a drift check every session. Missing index =
   compliance escalation.

3. **Skill documentation:** Added persistence requirement callout to the
   Alpha skill's PAST section: "The full PAST index MUST be written to
   the agent's state file every session, with a drift check. Missing PAST
   index = compliance escalation."

**Lessons learned:**
- A coaching framework that depends on persisted data is only as good as
  the persistence step in the agent's execution loop. Rocky can direct
  corrections, but if the cron prompt doesn't include the step, the
  directive is inert.
- Asymmetric compliance (Beta persisted, Alpha didn't) went undetected
  for 3 cycles because Rocky's review focused on trading behavior, not
  state-file completeness. State-file schema compliance should be a
  checklist item in Rocky's review, not just trading behavior.

---

### Changed — Patience Trait Split (Entry Patience + Hold Duration)

**Problem:** The single "Patience" trait conflated two independent
dimensions of trading behavior:
- **Entry Patience** — willingness to wait for qualifying setups before
  entering a trade (resists forcing trades when nothing qualifies)
- **Hold Duration** — how long to hold a position before mechanically
  exiting (resists holding past the thesis invalidation)

An agent can be patient about entries but quick to exit (Alpha's profile:
waits 15 sessions for CVS, then holds 3-5 days), or impatient about entries
but patient about holds (Beta's profile: trades more readily, holds for
weeks). The single trait couldn't distinguish these patterns.

**Fix:** Split `Patience` into:
- `Entry Patience` — measures entry-side discipline (confluence
  requirements, minimum setup quality, willingness to no-trade)
- `Hold Duration` — measures exit-side discipline (mechanical time exits,
  stop adherence, thesis-based holds vs. time-based exits)

This enables Rocky to detect drift on each dimension independently. For
example, if Alpha starts entering trades on weaker setups (Entry Patience
drift) without changing hold behavior, the split catches it where the
single trait would have masked it.

**Affected files:**
- `skills/trading-arena-alpha.md` — PAST table updated, trait split
  documented
- `skills/trading-arena-beta.md` — already uses split format (Beta's
  state file persisted `Patience 6/7` which maps to Entry Patience)
- `CHANGELOG.md` — this entry
- Alpha state file — PAST index now uses split format
- Beta state file — already uses split format (no change needed)

**Migration:** Existing `Patience` scores map to `Entry Patience` (the
closer behavioral analog). `Hold Duration` is assigned from the agent's
existing hold-period rules (Alpha 3/7 = 3-5 days, Beta 7/7 = weeks).

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
