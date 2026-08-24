# Changelog

All notable changes to the PAST Framework are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [v0.4.0] — 2026-08-24 — Live Trading Lessons (Aug 18-24): Risk, Reliability, Regime

### Summary

One week of live trading (Aug 18-24) exposed three structural weaknesses
in the PAST Trading Arena: (1) stop-loss execution depended on agent
presence (not broker-side), (2) the Hermes API stale-call detector was
misconfigured (90s default killed GLM-5.2 cold-start), and (3) the
pre-trade signal layer lacked sector momentum and sentiment checks.
All three are now fixed. The arena survived its first broad AI
infrastructure selloff with stops functioning correctly — but entered
positions during a relief bounce that reversed, highlighting the need
for regime detection before entry.

**Live P&L as of Aug 24:** -$140.74 (-2.81%). 6 trades placed, 3 sold
(2 stops triggered, 1 time-exit), 3 held. Stop-loss system worked —
CRWV sold at -10.8%, stock subsequently fell to -15.6%.

---

### Fixed — Stop-Loss Execution Moved to Broker-Side

**Problem:** Stop-loss was "manual" — an agent session had to run, read
prices, and manually place a sell order. On Aug 18, no agent session ran
(Z.AI timeout), and CRWV bled from $94.93 (stop) to $92.51 (actual) with
no sell executed. The position was held 2.4% past its hard stop.

**Root cause:** Robinhood cash accounts do not support automated stop
orders via the API — but they DO support `stop_market` GTC (good-till-
cancelled) orders. The agents were placing stops in state files, not on
the broker.

**Fix:** All positions now have GTC stop-market sell orders placed
directly on Robinhood. These execute automatically when the price hits
the trigger — no agent session needed, even if Z.AI is down or the Mac
is asleep. The 10% hard stop is enforced by the broker, not by the agent.

**Evidence:** On Aug 19, ALAB stop triggered at $281.72 (10.0% loss) and
CRWV stop triggered at $94.16 (10.8% loss, $0.77 slippage) — both
automatically, no agent present. CRWV subsequently fell to $88.92
(-15.6%), confirming the stop saved ~$26 of additional downside.

---

### Fixed — Z.AI GLM-5.2 API Timeout (Recurring 90s Stale Detector)

**Problem:** GLM-5.2 cron sessions failed 4 out of 5 trading days (Aug
12, 13, 17, 18) with `RuntimeError: Non-streaming API call timed out
after 90s with no response (threshold: 90s)`.

**Root cause:** Hermes Agent has a non-streaming stale-call detector
(`HERMES_API_CALL_STALE_TIMEOUT`) defaulting to 90 seconds. GLM-5.2
cold-start latency on first API call of a new session is 90-120s —
exactly at the threshold. The detector killed the session before Z.AI
responded.

**Fix:** Set `providers.nous.stale_timeout_seconds = 300` and
`providers.nous.request_timeout_seconds = 600` in Hermes config.
This gives GLM-5.2 5 minutes for cold-start (vs 90 seconds). Verified
Aug 21: both agents fired at 7:00/7:05 AM, zero timeouts, first clean
5-day streak.

**Pre-warm cron added:** A Z.AI pre-warm script runs at 6:45 AM MST
(15 min before agents) to establish the API connection. Silent on
success, alerts on failure.

---

### Fixed — Health Check MCP Test (5 → 10 Turns)

**Problem:** Pre-market health check reported CRITICAL: Robinhood MCP
FAILED on Aug 24. Root cause: `test_robinhood_mcp()` used
`--max-turns 5`, insufficient for Claude Code to establish the
claude.ai MCP connector session. Claude ran out of turns before
connecting.

**Fix:** Increased to `--max-turns 10` and timeout 120s → 180s.
Verified: MCP returns account value successfully with 10 turns.

---

### Added — Pre-Trade Signal Scan (Sector Momentum + Sentiment)

**Problem:** Beta entered 5 positions during a relief bounce (Aug 6-14)
that immediately reversed in the AI infrastructure selloff. All 5
positions went red simultaneously. The agents lacked a regime
detection layer — they saw technical setups (RSI oversold) but didn't
check whether the AI infrastructure sector was in an uptrend or
downtrend before entering.

**Fix:** New `pretrade_signal_scan.py` runs at 6:30 AM MST (30 min
before agents). It checks:
1. Sector momentum: are AI infra stocks above/below 50-day MA?
2. Market breadth: are SPY/QQQ/SMH above 20-day MA?
3. X/Twitter sentiment: bullish vs bearish posts for candidate tickers

Output: GO or NO-GO signal. If NO-GO (sector in downtrend), agents stay
defensive — no new entries, manage existing positions only.

**Reference:** TradingAgents framework (TauricResearch, 80K+ GitHub
stars, UCLA/MIT) uses a similar bull/bear debate structure with
sentiment analysts. Our PAST framework's pre-trade scan adds the
sentiment/flow layer that was missing from the original design.

---

### Fixed — model_status.md Auto-Update Ordering

**Problem:** model_status.md was flagged as stale (167h+) every Monday
because no process updated it. The auto-update function was added but
ran AFTER the stale check, so the alert fired before the update.

**Fix:** Moved `update_model_status()` to run BEFORE `check_state_files()`
in the health check. The file is now refreshed every morning at 5 AM
before the stale check runs.

---

### Fixed — Retry Script Could Not Trigger Retries

**Problem:** The mid-morning (10 AM) and afternoon (12 PM) retry checks
detected agent failures (state file not updated today) but could not
actually trigger retries. The script called `claude -p "test"` instead
of `hermes cron run <job_id>`.

**Fix:** Updated retry script to use `hermes cron run` for both Alpha
and Beta job IDs. Also added Z.AI connectivity test before retry — if
Z.AI is down, automatically switches to Ollama fallback model before
retrying, then switches back to Z.AI for the next day.

---

### Added — GTC Stop-Market Orders (Broker-Side Risk Management)

**All remaining positions have GTC stop-market sell orders on Robinhood:**

| Position | Shares | Stop Price | Stop % Below Fill | Status |
|----------|--------|------------|-------------------|--------|
| CIEN | 1 | $372.56 | 10% below $413.96 | Active |
| VST | 3 | $128.25 | 10% below $142.50 | Active |
| CCJ | 3 | $89.10 | 10% below $99.00 | Active |

Previous positions (ALAB, CRWV) had their stops triggered and sold
automatically on Aug 19.

**Agent skill updated:** All future trades MUST place a GTC stop-market
order on Robinhood immediately after fill. This is non-negotiable and
removes the dependency on agent presence for stop execution.

---

### Infrastructure Changes (Aug 18-24)

| Change | What | Impact |
|--------|------|--------|
| Z.AI stale timeout | 90s → 300s | No more cold-start timeouts |
| Pre-warm cron | 6:45 AM daily | Warms Z.AI before agents fire |
| Retry script | Uses `hermes cron run` | Retries actually work now |
| Ollama fallback | Auto-switch if Z.AI down | Agents always run |
| GTC stop-market | Broker-side stops | Stops fire without agent |
| model_status auto-update | 5 AM daily | No more stale alerts |
| MCP health check | 5 → 10 turns | No more false MCP failures |
| Pre-trade signal scan | 6:30 AM daily | Regime detection before entry |
| Cron schedule | 7 days/week | No weekend gaps |
| Mac sleep settings | 45 min idle | Monitors off when idle |

---

## [v0.3.3] — 2026-08-14 — Engineering Infrastructure (CodeRabbit, Branch Protection, Model Split)

### Summary

Three infrastructure improvements to enforce code quality and operational
reliability: (1) CodeRabbit AI installed for automated PR review, (2) `main`
branch protected with required review + force-push/deletion blocks, (3)
session model switched to Claude Sonnet 4.5 for engineering work while
trading cron jobs remain on GLM-5.2 for cost control.

---

### Added — CodeRabbit AI Code Review

**What:** CodeRabbit AI bot installed on the `sloth1122/past-framework`
GitHub repository. Automatically reviews every PR with actionable
comments, walkthrough summaries, and pre-merge checks.

**First review:** PR #1 (v0.3.1 model docs fix). CodeRabbit flagged 2
actionable issues (model identity inconsistency, stale documentation in
research paper and SpaceX simulation). Both fixed in v0.3.2.

**Workflow enforced:** All changes to `main` now go through branch →
PR → CodeRabbit review → approval → merge.

---

### Added — Branch Protection (`main`)

**What:** `main` branch protected via GitHub API with the following rules:

| Rule | Setting |
|------|---------|
| Required pull request reviews | 1 approving review required |
| Dismiss stale reviews | Yes (new commits clear old approvals) |
| Allow force pushes | No (blocked) |
| Allow deletions | No (blocked) |
| Enforce for administrators | Yes (applies to repo owner too) |

**Why:** Prevents accidental history rewrites, direct commits to `main`,
and merging without review. The repo is public — protection ensures
every change is traceable and reviewed.

---

### Changed — Session Model Split (Engineering vs Trading)

**What:** Hermes Agent session model switched from GLM-5.2 (Z.AI) to
Claude Sonnet 4.5 (Anthropic) for engineering, code review, and repo
management work. Trading cron jobs (Alpha, Beta, Rocky, Judge Audit,
Token Monitor, Weekly Review) pinned to GLM-5.2 via Z.AI for cost
control ($384/qtr plan).

**Why:** GLM-5.2 is capable for constrained trading tasks but lacks the
proactive initiative and cross-document consistency checking needed for
engineering work. Claude Sonnet 4.5 provides senior-engineer-level code
review, architecture reasoning, and repo hygiene.

**Architecture update:**

| Layer | Model | Provider | Use Case |
|-------|-------|----------|----------|
| Engineering session | Claude Sonnet 4.5 | Anthropic | Code review, repo management, architecture |
| Trading execution (all agents) | GLM-5.2 | Z.AI ($384/qtr) | Cron sessions, tooling, MCP, order placement |
| Beta reasoning | Deepseek R1 70B | Ollama (local) | Baker architecture-first thesis analysis |
| Judge | Claude Fable 5 | Claude Code (`claude -p`) | 13-point trade verification |

**Cron jobs pinned (6):** Alpha, Beta, Rocky, Judge Audit, Token Monitor,
Weekly Review — all pinned to `z-ai/glm-5.2` via `nous` provider to
prevent fail-closed on global model drift.

---

### Fixed — Mac Sleep (Root Cause of Cron Failures)

**Problem:** Mac Studio `pmset` had `sleep=1` (sleep after 1 min idle)
and `disksleep=10`. While Hermes, Claude, and Perplexity held
`NoIdleSleepAssertion`, if any of those apps crashed, the Mac would
sleep within 1 minute — causing cron jobs to miss their schedules
(Aug 12-13 Alpha/Beta failures).

**Fix:** `sudo pmset -a sleep 0 disksleep 0` — system sleep and disk
sleep permanently disabled. Display sleep remains at 10 min (cron jobs
don't need the screen). `tcpkeepalive=1` and `powernap=1` retained.

---

## [v0.3.2] — 2026-08-14 — CodeRabbit Review Fixes (Documentation Consistency)

### Summary

CodeRabbit AI reviewed PR #1 and flagged 2 actionable issues: (1) model
identity inconsistency for Judge/Rocky between README and CHANGELOG, and
(2) stale model documentation in the research paper and SpaceX simulation
that didn't reflect the two-layer architecture. Both were documentation
consistency issues — no code bugs.

---

### Fixed — Model Identity Consistency (README vs CHANGELOG)

**Problem:** The README listed Rocky as "Claude Fable 5" while the
CHANGELOG v0.3.1 table listed Rocky as "GLM-5.2 (Z.AI)". The Judge was
listed as just "Claude Fable 5" in the README without noting it runs
via `claude -p` subprocess.

**Fix:**
- `README.md` — Rocky now shows "GLM-5.2 (exec)" (consistent with
  CHANGELOG). Judge now shows "Claude Fable 5 (Claude Code)" with
  `claude -p` subprocess note.

---

### Fixed — Stale Documentation (Research Paper + SpaceX Simulation)

**Problem:** Two files still had the old single-model architecture:
- `docs/PAST_Research_Paper_v2.md` Section 5.1: Listed Beta as
  "Aschenbrenner" (personality was swapped to Baker on Jul 30), used
  a single "Model" column instead of execution/reasoning layers, and
  listed Rocky as "Claude Fable 5" instead of GLM-5.2.
- `examples/spacex_simulation.html`: Alpha's role said "GLM-5.2
  (Cloud)" and Beta's said "Deepseek R1 70B (Local)" — neither
  reflected the two-layer architecture.

**Fix:**
- `docs/PAST_Research_Paper_v2.md` — Updated Section 5.1 table to
  two-layer format (Execution Layer + Reasoning Layer columns), changed
  Beta role from "Aschenbrenner" to "Baker/Atreides", updated Rocky to
  GLM-5.2, added two-layer architecture explanatory paragraph.
- `examples/spacex_simulation.html` — Alpha role updated to "GLM-5.2
  (exec + reasoning)", Beta role updated to "GLM-5.2 (exec) / Deepseek
  R1 70B (reasoning)".

---

### Process Improvement — Daily Code Audit

Added a daily evening cron job to audit the repository for documentation
inconsistencies, stale references, and organizational issues. This ensures
issues are caught within 24 hours instead of accumulating over weeks.

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
