# Trading Arena v5 — Single Agent (Beta), Core + Event Bets

**Date:** 2026-10-22 · **Decision owner:** John Tytko · **Status:** LIVE from the next Beta session (Fri Oct 23, 07:05 MT)

## 1. Decision

1. **Agent Alpha is retired.** Its cron is paused (not deleted), its skill is marked deprecated, and the retry check no longer re-runs it.
2. **Agent Beta is the only trading agent** and manages the whole arena account (Alpha's cash is merged into Beta).
3. **New mandate: 10% CORE + 90% EVENT BETS**, with the Judge kept as the risk gate.
4. **Scoreboard changes from "Alpha vs Beta" to "Beta vs QQQ"** since the v5 start.
5. **Options are not enabled yet.** Since Oct 23 the account is limited margin, so Level 3 spreads are possible after approval (see `OPTIONS_MARGIN_GUIDE.md`).

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

**Judge** enforces all of the above, recomputes ATR/filters independently, and rejects options until enabled.

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
| `skills/trade-judge/SKILL.md` | v5 block: Beta-only audit, new sizing, options rejected |
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
| 3-vote unanimous Judge | `scripts/judge_vote.py` — 3 parallel independent Judges, fail-closed | `state/judge_votes/` |
| Required real-news bear case | Beta template field; Judge rejects generic "AI bubble" | Beta + Judge SKILL |
| Slippage + honest backtests | `decision_ledger.py slip`; backtests = next-open fills, costs, bootstrap range | `state/decisions/slippage.jsonl` |
| Options enabled (buy calls/puts, debit verticals) | `scripts/options_guard.py` (17/17 tests), 3/3 Judge, review shows debit | `state/options_premium.jsonl` |

First scorecard (backfilled Aug 6–Oct 16): buys beat QQQ at 20 days 4 of 12, avg −5.8 pts. Tests: judge_vote mixed vote (2/3 → REJECTED), fail-closed, live 3-Judge run (3/3, 94 s). Bet size confirmed by John: ≤ 30% of equity (~$2,900), risk ≤ 3% (~$290).
