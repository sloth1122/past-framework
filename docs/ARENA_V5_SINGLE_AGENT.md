# Trading Arena v5 — Single Agent (Beta), Core + Event Bets

**Date:** 2026-10-22 · **Decision owner:** John Tytko · **Status:** LIVE from the next Beta session (Fri Oct 23, 07:05 MT)

## 1. Decision

1. **Agent Alpha is retired.** Its cron is paused (not deleted), its skill is marked deprecated, and the retry check no longer re-runs it.
2. **Agent Beta is the only trading agent** and manages the whole arena account (Alpha's cash is merged into Beta).
3. **New mandate: 10% CORE + 90% EVENT BETS**, with the Judge kept as the risk gate.
4. **Scoreboard changes from "Alpha vs Beta" to "Beta vs QQQ"** since the v5 start.
5. **Options are ON for Agent Beta (since Oct 23 2026).** The account is limited margin with options Level 3, verified at the broker. Beta may buy single calls/puts and 2-leg debit verticals, enforced in code by `scripts/options_guard.py`. Every option trade is a high-risk Judge trade (3 Fable 5.1 runs, all must approve). See v5.2 below.

**v5.1 update (Oct 23 2026):** John added **$5,000** → **$9,692.16** total, cash $8,931.58; account converted to **limited margin** (no borrowing). Scoreboard baseline **$9,676.71 / QQQ $704.59** (Oct 22 close + deposit). Sizing re-expressed as % of equity: bet ≤ 30%, risk ≤ 3%, core ≈10%. Gate-1 max_position_value $2,900 (risk $290), self-test 19/19.

**Original v5 baseline (Robinhood, 2026-10-22 1:35 PM ET):** equity **$4,678.46**, cash $3,931.58, CIEN 1 @ $328.50 (stop $319.50), VST 3 @ $139.46 (stop $128.25). Benchmark **QQQ $706.68** (200-day SMA $676.49).

## 2. Why — the arena's own record (Aug 3 → Oct 21, 2026)

| | Result |
|---|---|
| Arena account | **−5.4%** (≈ −$270 on $5,000) |
| SPY, same window | **+2.0%** |
| Closed trades | 11 — **1 winner** (CRDO +$26.42), realized −$287.46 |
| Exits by stop-loss | **7 of 11** |
| Alpha | 3 trades (CVS, BKNG, BAC), 0 winners, −$19.35; **29+ consecutive sessions with zero submissions** (its oversold-AND-rising-20d gate never fired) |
| Beta | 8 closed trades, 1 winner, realized −$268.11 |

Two failure modes:
- **Missed market beta.** Alpha sat in cash through a rising market; Beta was usually < 30% invested.
- **Stops inside the noise.** Beta bought AI-hardware names that move 7–8% in a day with flat 10% stops, so ordinary volatility stopped it out before theses could play out.

## 3. Why — the published evidence

| Source | Finding | Implication for us |
|---|---|---|
| FINSABER — *Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?* (arXiv 2505.07078, KDD 2026) | 20 years, 100+ symbols: LLM strategies show **no statistically significant alpha** (p > 0.34); **too conservative in bull markets, too aggressive in bear markets**. Authors recommend trend detection + regime-aware risk controls. | Add a mechanical trend-following core so the agent can't miss an uptrend; regime filter = QQQ vs its 200-day SMA. |
| StockBench (arXiv 2510.02209) | "Most models struggle to outperform the simple buy-and-hold baseline"; every agent underperformed during the downturn. | Benchmark against buy-and-hold (QQQ), not against another agent. |
| Agent Market Arena (arXiv 2510.11695) | **Agent architecture matters more than the LLM backbone.** | Fix the rules/structure, not the model. |
| Alpha Arena (nof1, real money, 2025) | Season 1: 4 of 6 frontier models lost 42–59%. Season 1.5 (US stocks): one model positive. Risk-constrained "Monk Mode" did best; max-leverage blew up. An independent analysis found results consistent with random trading. | Keep hard dollar-risk limits; don't set a "double the money" target that pushes toward leverage. |

## 4. The v5 rules (source of truth: `trading-arena-beta/SKILL.md` Section 0)

**CORE — 10% of equity, mechanical**
- Hold QQQ (fractional OK) ≈10% of equity only while QQQ's prior close > 200-day SMA; sell the core on the first close below; re-enter on the first close back above.
- No stop on the core (the trend filter is the exit). Rebalance Mondays if drift > ±3 pts.

**EVENT BETS — 90% of equity, Beta's judgment**
- Max **3** concurrent bets (CIEN + VST count as 2); ≤ 2 per architecture layer.
- Each bet needs a **dated catalyst within 30 trading days** (earnings, guidance, product, contract, index, regulatory).
- **≤ 30% of equity per position; ≤ 3% of equity dollar risk per bet** (v5: $1,500 / $150 at $4.7K; v5.1: ≈ $2,900 / $290 at $9.7K).
- **Stop = entry − 2×ATR(14)**, floor 5%, cap 20%; shares = floor(3%-of-equity ÷ stop distance), capped at 30% of equity; whole shares.
- Earnings inside the hold are allowed only if shares × max(stop distance, options-implied move) ≤ 3% of equity (stop-market orders don't protect against gaps).
- Morning after the catalyst: HOLD (confirmed) or EXIT; 5-trading-day time stop if unconfirmed. Daily +20% profit ratchet unchanged.

**Judge** enforces all of the above, recomputes ATR/filters independently, and runs the options checklist on every option trade (options are ON for Beta since Oct 23).

**Changed constants (Gate-1, `gate1_pregate.py`):** max_position_value $750 → **$1,500** (risk budget $75 → **$150**), deployable_reserve $500 → **$50**, max_positions 5 → **4** (3 bets + core). Self-test: **19/19 pass**.

**PAST vector (user directive):** Position concentration 4→6, Hold Duration 7→5, Entry Patience 6→5.

## 5. Success test and exit

- **90-day review ≈ 2027-01-20.** Beta beats QQQ (after costs) from the v5.1 baseline with max drawdown ≤ 15% → continue. Otherwise → arena shut down, cash to VOO. (John added the planned $5,000 up front on Oct 23.)
- **Cost context:** Nous ($100/mo) and Z.AI are cancelled; everything runs on Claude Opus 5.5 under Claude Max ($200/mo), which John keeps regardless. At $5K–$10K the arena cannot pay for Claude Max from returns (it would need +48%/+24% a year); its value is as a live research lab for PAST.

## 6. What changed where (with backups `*.bak-v5-202610221134`)

| File / job | Change |
|---|---|
| cron `bdfac2a2e8e5` (Alpha) | **Paused** |
| `~/.hermes/scripts/trading_arena_retry_check.sh` | Alpha retired → never retried |
| `skills/trading-arena-alpha/SKILL.md` | DEPRECATED banner |
| `skills/trading-arena-beta/SKILL.md` | v5.0.0 — Section 0 mandate; model = Opus 5.5; sizing/stop/template fields updated |
| `skills/trade-judge/SKILL.md` | v5 block: Beta-only audit, new sizing; options checklist (options ON since Oct 23); risk-tiered runs (v5.2) |
| `skills/trading-arena-rocky/SKILL.md` | v5 note: coach Beta only; scoreboard vs QQQ |
| `state/agent_beta/{state,next_prompt}.md` | v5 header + first-session task list |
| `state/agent_alpha/state.md` | RETIRED header |
| `state/judge_decision_log.md` | USER RULING — Arena v5 |
| `gate1_pregate.py` | v5 constants; INTC test fixture re-based to the $50 reserve |

## 7. Rollback

`hermes cron resume bdfac2a2e8e5`, restore the `*.bak-v5-202610221134` files, and revert the Gate-1 constants.

## v5.1 decision discipline (Oct 23 2026) — adopted from the TradingAgents review

Source: TauricResearch/TradingAgents v0.7.0 (Apache-2.0) and replications (Koviazin et al., IC-AIF 2026; "The Alpha Illusion", arXiv 2605.16895). Taken: scoring/lesson loop, prediction-market inputs. Skipped: multi-analyst debate, 5-tier ratings, quick/deep model split.

| Rule | Mechanism | File |
|---|---|---|
| Score every decision (buy/hold/pass/sell/core) vs QQQ at 5 and 20 trading days; entry = first close after the decision | `scripts/decision_ledger.py score`, 6:50 MT no-LLM cron | `state/decisions/decisions.jsonl`, `lessons.md` |
| Lessons fed into the next session | Beta cron Step 1 reads `lessons.md` | — |
| Prediction-market odds as event-bet input | `scripts/polymarket_odds.py` (public Gamma API, open markets, ≥$10K volume) | `state/research/prediction_markets.md` |
| Risk-tiered Judge (v5.2 replaces the 3-vote-for-everything design) | `scripts/judge_vote.py` — ONE Judge: high-risk = 3 Fable 5.1 runs, unanimous; routine = 1 Opus 5.5 run; JSON vote per run_id; fail-closed | `state/judge_votes/` |
| Required real-news bear case | Beta template field; Judge rejects generic "AI bubble" | Beta + Judge SKILL |
| Slippage + honest backtests | `decision_ledger.py slip`; backtests = next-open fills, costs, bootstrap range | `state/decisions/slippage.jsonl` |
| Options ON for Beta (buy calls/puts, debit verticals) | `scripts/options_guard.py` (26/26 tests), high-risk Judge (3 Fable 5.1 runs), review shows debit | `state/options_premium.jsonl` |

First scorecard (backfilled Aug 6–Oct 16): buys beat QQQ at 20 days 4 of 12, avg −5.8 pts. Tests: judge_vote mixed vote (2/3 → REJECTED), fail-closed, live 3-Judge run (3/3, 94 s). Bet size confirmed by John: ≤ 30% of equity (~$2,900), risk ≤ 3% (~$290).

## v5.2 (Oct 24 2026) — risk-tiered Judge, model policy, review fixes

**Status check (Oct 24):** Agent Beta is live: its 07:05 MT cron ran today, checked the account read-only, logged holds on AMZN/VST and the QQQ core, and is ready for Monday's open. Agent Alpha is terminated: its cron has been paused since Oct 22 after 77 sessions with 3 trades, 0 winners, and 29+ consecutive sessions with no submission. It sat in cash through a rising market, which is both a performance failure and a mismatch with the goal of beating QQQ.

**One Judge, risk-tiered (John's decision).** There is exactly one Judge (one skill, one rulebook). `scripts/judge_vote.py --ticker T --instrument stock|option [--notional USD]` runs it once per thesis:

| Tier | Which trades | Runs | Model | Approval |
|---|---|---|---|---|
| HIGH-RISK | every option trade (any legs, long or short); crypto or leverage if ever enabled; a stock trade above John's size threshold (`state/judge_config.json` → `high_risk_notional_usd`, currently unset) | 3 in parallel | Claude Fable 5.1 (`claude-fable-5-1`), effort high | all 3 approve |
| ROUTINE | every other stock trade | 1 | Claude Opus 5.5 (`claude-opus-5-5`), effort high | the one run approves |

- **Vote protocol:** each run ends with one JSON line `{"run_id", "vote": "approve|reject", "reason"}`. Votes are tallied by unique `run_id`, so duplicate lines from one run are ignored and raw lines are never counted. A missing, malformed, wrong-id or conflicting vote, or a timeout, gets one re-run; if it's still invalid, the trade is rejected. APPROVED only if valid votes = runs required and all approve.
- **Why the old design rejected good trades:** the v5.1 runner counted raw `VOTE |` lines. A run that repeated its final line produced 4 lines for 3 runs, and `len(votes) == 3` failed → REJECTED "4/3", even with three approvals. Reproduced, then fixed and tested (`test_judge_vote.py`, 13 cases).
- **Failover:** Fable 5.1 unavailable (preflight) → 3 runs on Opus 5.5 high, unanimous, logged `failover`. A timeout on a time-sensitive order = reject. The Judge is never bypassed.
- **Shadow test:** 10% of high-risk trades also get one non-voting Opus 5.5 run, and both verdicts are logged (`shadow.jsonl`).
- **Logging and reports:** `votes.jsonl` (every attempt), `trades.jsonl` (every verdict, `split` flag on 3-run trades). `judge_vote.py --report` prints the split rate and the Fable-vs-Opus agreement rate. Each verdict block flags a MILESTONE to report to John at 50 high-risk trades and at 50 shadow comparisons.
- **Defense in depth:** if the PENDING thesis text contains option terms, the trade is treated as high-risk even if the caller passed `--instrument stock`.

**Model policy:** every Hermes chat, subagent and agent cron runs Claude Opus 5.5 at high effort, and the pre-market health check now verifies it from the live config every morning. On Oct 24 it reported 12/12 agent crons, chat and subagents all on policy. The Judge routes by tier as above. GLM/Z.AI (retired Oct 19) and local Ollama/Deepseek models (retired Oct 11) are listed only as retired; the dead checks for them were removed.

**Other fixes in this release:**
- `option_payoff.py`: an option on its expiry day crashed the probability-of-profit step (division by `iv × √T` with T = 0). On expiry day the price is known, so the probability is now exactly 1 or 0. The option is not worthless at expiry: it settles at intrinsic value. A naked short call now reports max loss as unlimited instead of a finite number.
- `charlie_vol_snapshot.py`: VIX, VIX9D and VIX3M are fetched separately. A missing VIX3M or VIX9D quote no longer discards the VIX level as "VIX fetch failed". Only a missing spot VIX makes the regime UNKNOWN.
- Health check: no longer requires Alpha's frozen state file to be fresh (that would have raised a false alarm every morning from Oct 24).
- Repo and live (`~/trading-arena/scripts`) copies of the arena scripts are now identical files. The account last-4 comes from `ARENA_ACCOUNT_LAST4` or the untracked `state/arena_account_last4`.

### v5.2 review round (Oct 24 2026) — standards, spec and architecture reviews

- **One read-only broker path:** new `scripts/broker_read.py` holds the only copy of the broker deny-list. Charlie's quote pulls, the Daily Judge Audit's position check and Beta's own position pull used to run Claude with order-placing tools available, enforced only by the words "read-only". They now go through `broker_read.py`, and so do the Judge, Rocky and the health probe. A live test confirmed that `place_equity_order` does not exist in that session. Only Beta's order step, after a Judge APPROVED verdict, keeps write access.
- **Judge (spec gaps closed):**
  - `--time-sensitive`: a timeout rejects at once, with no re-run.
  - If Fable stops responding mid-run, the failed run's re-run uses Opus and is logged `failover`.
  - The shadow run starts in parallel, so it never delays an order.
  - A shadow skipped during failover is recorded as skipped.
  - `split` now counts "2 approve + 1 invalid".
  - The split rate is also shown for Fable-only trades.
  - Milestones are announced once ("MILESTONE — REPORT TO JOHN"), and Beta copies them into its Telegram report.
  - A stock order without `--notional`, a malformed config, or any internal error produces a logged REJECTED verdict.
  - Option terms in the thesis escalate the tier even without a PENDING tag.
  - 24 tests.
- **Health check:**
  - Judge model names come from `judge_vote.py` (no second copy), and the shadow rate from the Judge config.
  - 0 active agent crons is UNVERIFIED, not "on policy".
  - Missing shared modules raise a CRITICAL alert instead of a silent fallback.
  - 10 tests, which pass with and without PyYAML.
- **Rocky:** any error, not only a timeout, fails closed to PASS.
- **`robinhood_trade.py`:** stopped calling the arena account a "CASH account". It is limited margin and never borrows.
- **Open decisions:**
  - stock size threshold (issue #8);
  - research-paper PDF redaction (issue #7);
  - the architecture candidates in the Oct 24 review (one order object shared by the options guard and the broker; one deploy path; one arena settings file).
