# Changelog

All notable changes to the PAST Framework are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [v0.3.1] — 2026-08-14 — Model Documentation Fix (Two-Layer Architecture)

### Summary

Corrected a documentation discrepancy where Beta's model was listed as
"Deepseek R1 70B" without mentioning GLM-5.2 as the execution layer. The
Trading Arena uses a **two-layer model architecture** — GLM-5.2 (via Z.AI
cloud API) is the execution/orchestration layer for ALL agents, and
Deepseek R1 70B (local via Ollama) is Beta's reasoning brain. The docs
incorrectly implied Beta runs entirely on a local model.

---

### Fixed — Model Identity Documentation (Beta + Alpha)

**Problem:** The skills and README listed Beta's model as "Deepseek R1
70B (local via Ollama)" with no mention of GLM-5.2. This was inaccurate
because GLM-5.2 (cloud, via Z.AI) is the model that actually runs the
cron sessions, handles all tooling (web_search, terminal, file I/O,
Robinhood MCP via `claude -p`), invokes the Judge, and places orders.
Deepseek R1 70B is Beta's *reasoning* layer — it analyzes the AI compute
stack, identifies bottlenecks, and formulates trade theses. The docs made
it look like Beta was a fully local model when in reality GLM-5.2 (cloud)
does most of the work.

**The correct architecture:**

| Agent | Execution Layer | Reasoning Layer | Notes |
|-------|----------------|-----------------|-------|
| Alpha | GLM-5.2 (Z.AI) | GLM-5.2 (Z.AI) | Single model — Alpha is purely statistical, no deep reasoning needed |
| Beta | GLM-5.2 (Z.AI) | Deepseek R1 70B (Ollama) | Two-layer — GLM-5.2 executes, Deepseek reasons (Baker architecture-first thesis) |
| Judge | Claude Fable 5 (Claude Code) | — | Independent trade verification via `claude -p` subprocess |
| Rocky | GLM-5.2 (Z.AI) | — | Coaching sessions, PAST tuning |

**Files changed:**
- `skills/trading-arena-beta.md` — Replaced single "Model Identity" line
  with a full "Model Architecture — Two-Layer" section documenting both
  GLM-5.2 (execution) and Deepseek R1 70B (reasoning), how they interact,
  and what each layer is responsible for. Updated frontmatter description.
- `skills/trading-arena-alpha.md` — Added "Model Architecture —
  Single-Layer" section documenting that GLM-5.2 handles both execution
  and reasoning, with explanation of why Alpha doesn't need a separate
  reasoning model (purely statistical approach).
- `README.md` — Updated architecture table: Alpha now shows "GLM-5.2
  (exec + reasoning)", Beta now shows "GLM-5.2 (exec) / Deepseek R1 70B
  (reasoning)".
- `CHANGELOG.md` — This entry.

**Why this matters:** Accurate model documentation is essential for
reproducibility. A reader following the old docs would believe they need
only a local Ollama instance to run Beta, when in reality the cron
sessions, tooling, MCP calls, and order execution all go through GLM-5.2
via Hermes Agent's Z.AI integration. The two-layer architecture is also
architecturally significant — it demonstrates that PAST's persona-driven
approach works across heterogeneous model configurations (cloud + local,
statistical + deliberative).

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

### Fixed — Claude OAuth Token Reliability (Recurring Auth Failures)

**Problem:** Claude Code's OAuth token expired every 24-48 hours, causing
"OAuth session expired and could not be refreshed" errors that took down
the Robinhood MCP, Judge gate, and all trading operations. This required
manual `claude auth login` intervention 3+ times in the first week of
live trading (Aug 10, Aug 12, Aug 13).

**Root cause (3 interacting bugs):**

1. **`claude -p` does not persist refreshed tokens** (GitHub #37402).
   Claude Code refreshes the OAuth access token in-memory during active
   sessions, but `--print` (headless) mode does not write the refreshed
   token back to `~/.claude/.credentials.json`. New subprocesses read the
   stale file and may fail.

2. **Credentials file vs Keychain confusion.** Claude Code on macOS stores
   credentials in the **Keychain** (service: `Claude Code-credentials`),
   not the legacy `.credentials.json` file. The file may show an expired
   token while the Keychain has a fresh one. The token monitor script was
   reading the stale file, generating false alerts even when Claude was
   working fine.

3. **Refresh token aging** (GitHub #65761). After weeks of refresh-only
   usage (no interactive login), the underlying `refresh_token` expires
   or is rotated server-side. When this happens, neither in-memory refresh
   nor file-based refresh works — only a full `claude auth login` (browser
   OAuth flow) fixes it.

**Fix (3 layers):**

1. **Token monitor now reads Keychain (not file).** The `claude_token_monitor.py`
   script (runs every 30 min) now reads from the macOS Keychain as primary
   source, falling back to the file only if Keychain is unavailable. This
   eliminates false alerts when the file is stale but the Keychain token is
   fresh.

2. **Token keepalive cron (every 2h).** New `claude_token_keepalive.py`
   script runs every 2 hours and tests actual `claude -p` connectivity
   (ground truth — not the file). If connectivity works, it stays silent.
   If connectivity fails, it alerts to Telegram. Running `claude -p`
   periodically also keeps the in-memory session active and the refresh
   token from going stale prematurely.

3. **Connectivity-based alerting (not file-based).** Both the monitor and
   keepalive scripts now alert based on actual `claude -p` connectivity
   test results, not the credentials file timestamp. The file is a cache;
   connectivity is ground truth. This eliminates false positives from the
   stale file.

**Files changed:**
- `~/.hermes/scripts/claude_token_monitor.py` — reads Keychain (primary),
  file (fallback); clearer comments about the stale-file bug
- `~/.hermes/scripts/claude_token_keepalive.py` — new script, tests
  connectivity every 2h, silent on pass, alerts on fail

**Cron jobs:**
- `Claude OAuth Token Monitor` (every 30 min) — fixed, reads Keychain
- `Claude OAuth Token Keepalive` (every 2h) — new, connectivity test

**References:**
- GitHub #37402: OAuth token not persisted for --print mode
- GitHub #65761: Stale refresh token causes persistent 401
- GitHub #44945: OAuth auto-refresh broken in long-running sessions
- GitHub #37512: CLAUDE_CODE_OAUTH_TOKEN silently deletes Keychain credentials
- macOS Keychain service: `Claude Code-credentials`

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
