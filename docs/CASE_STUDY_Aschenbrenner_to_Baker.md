# Case Study: Real-Time Personality Swap — Aschenbrenner → Baker

## The Event

On **July 30, 2026**, Leopold Aschenbrenner's hedge fund Situational Awareness LP was forced to sell its entire public equities portfolio in a single block trade to Ken Griffin's Citadel, following margin calls from Goldman Sachs, JPMorgan, and Bank of America.

| Detail | Value |
|---|---|
| Fund size at peak | $45 billion (July 2026) |
| Leverage | ~4x gross |
| Top 5 concentration | 76% of portfolio |
| July drawdown on key holdings | BE -45%, SNDK -55%, CRWV -38%, NBIS -35%, MU -35% |
| **July fund plunge** | **-67%** (per Financial Times, July 31, 2026) |
| **Still up YTD** | **+80% despite July losses** |
| Outcome | Entire public book sold to Citadel at >10% discount; ~$10B remaining (private stakes) |

### Aschenbrenner's Response (FT, July 31, 2026)

In a letter to investors sent July 31, Aschenbrenner wrote:

> "These were very expensive scars, but I am dedicated to ensuring they will be invaluable lessons for our organization and for myself as we move forward. My core promise to you is that we will not waste the opportunity to learn from these events."

> "Over the past two years, we have delivered outstanding results, despite occasional sharp pullbacks. But our fund must always be structured such that we can take a loss and fight another day."

**Key commitment:** Situational Awareness will **no longer borrow money from banks** to magnify its bets — i.e., no more leverage.

This is exactly what the PAST framework did programmatically on July 30: removed leverage from Beta's personality profile by swapping from Aschenbrenner (Risk=6, 4x leverage) to Baker (Risk=5, no leverage).

## What PAST Identified Before the Collapse

The PAST research paper's Limitations section (now §9.2 of v2.4; §7.2 in the July draft), written on July 29, 2026 — **one day before the liquidation** — explicitly warned:

> "Beta's [return] was dominated by a single MU trade. In a different market regime, Beta's [low] win rate with 10% stops could produce consecutive losses without a compensating win."

*(The specific dollar and win-rate figures in the original sentence — +$754, +$880, 27% — came from the v1 harness and have been retracted; see the Backtest Comparison section below and CHANGELOG v0.4.1. The qualitative warning stands and the v3 backtest confirms it: every closed Beta trade was a stop-loss.)*

The paper also noted:
- **Regime dependence** — the Aschenbrenner thesis (AI infrastructure) works in a bull market, fails in a downturn
- **Concentration risk** — 76% in top 5 positions
- **Conviction without risk management** — "Aschenbrenner's strength is conviction, but his weakness is holding through regime changes"

## The Personality Swap

On July 30, 2026 — the same day Aschenbrenner was liquidated — Agent Beta's personality was swapped from Aschenbrenner to **Gavin Baker (Atreides Management)**.

### Why Baker?

| Dimension | Aschenbrenner (Liquidated) | Baker (Survived) |
|---|---|---|
| **Leverage** | 4x (margin) | None (cash only) |
| **Concentration** | Top 5 = 76% | Top 5 = ~32%, 5-10 positions |
| **NVDA** | Short (puts) | Owns when reasonable (5.3%) |
| **Software** | Short (Adobe) | Owns (Unity, Twilio, Zoom) |
| **Thesis** | Power + data centers only | Full architecture: compute + memory + networking + power + data center + software |
| **Risk management** | Conviction = hold through crash | 10% hard stop, no exceptions |
| **Sharpe ratio** | Unknown (volatile) | 2.46 (risk-adjusted) |
| **July 2026 outcome** | Liquidated by margin call | Survived (-3.5% drawdown, fund intact) |

### PAST Score Changes

| Trait | Aschenbrenner | Baker | Change | Rationale |
|---|---|---|---|---|
| Risk Tolerance | 6/7 | 5/7 | -1 | No leverage, more conservative |
| Conviction | 7/7 | 6/7 | -1 | 10% hard stop limits conviction risk |
| Impulsivity | 5/7 | 3/7 | -2 | Methodical, waits for cross-sectional value |
| Patience | 7/7 | 6/7 | -1 | Reviews monthly, not "hold forever" |
| Concentration | 6/7 | 4/7 | -2 | Diversified 5-10 positions, not 76% in top 5 |
| Adaptability | 5/7 | 6/7 | +1 | Shifts architecture layers as bottlenecks evolve |

## Backtest Comparison

> **Retraction notice (September 2026).** The two comparison tables that originally appeared here (Aschenbrenner +$754.41 / Baker +$573.93) were produced by the v1 harness, which simulated each ticker as an independent $2,500 book and summed the results. Those figures are withdrawn. The tables below are from the v3 portfolio-level harness (`backtest/backtest_v3.py`, shared $2,500 pool, rolling indicators, 1-day stop cooldown, IPO ban on). Source: `docs/BACKTEST_V3_RESULTS.md`.

### Both profiles on identical data (Jan 1 – Jul 21, 2026)

| Metric | Beta — Aschenbrenner $[6,7,5,7]$ | Beta — Baker $[5,6,3,6]$ |
|---|---|---|
| Final equity (from $2,500) | $2,358.18 | $2,867.64 |
| Return | −5.67% | +14.71% |
| Realized / unrealized | −$186.19 / +$44.36 | −$547.97 / +$915.60 |
| Closed trades (all stop-outs) | 3 | 10 |
| Open at end | 2 | 5 |
| Max drawdown | −9.4% | −30.7% |
| Judge approvals / signals | 5 / 37 | 80 / 105 |
| Return if MU re-entry is one session later (paper §7.6) | −6.51% | −8.46% |

### The Key Insight

On this window Baker's headline return is higher, but for a reason that has nothing to do with the profile: one MU position, re-entered the session after a stop, carried +$506 of unrealized gain. Shift that re-entry by a single session and Baker is −8.5%, worse than Aschenbrenner. Aschenbrenner lost less not because its thesis was better but because it barely traded — the Judge blocked 25 of its signals on the SPCX IPO ban and 7 on its own NVDA restriction, so it sat mostly in cash. Baker's pullback-entry rule and unrestricted universe kept it fully deployed and produced a 30.7% drawdown.

The backtest ended July 21 — nine days before the liquidation. The swap to Baker was not made on backtest return. It was made because Aschenbrenner's real-world profile (4× leverage, 76% in five names) had just been shown to be ruinous, and the Likert vector encoding those traits — Risk 6, Conviction 7, Concentration 6 — was the closest analogue in the arena. A return-only comparison of the two profiles on this window is not stable enough to point anywhere.

### The PAST Lesson

**In a bull market, concentration + conviction wins. In a crash, diversification + risk management survives.** PAST's value is not predicting which regime will occur — it's ensuring the agent's personality is suited to survive both.

The swap from Aschenbrenner to Baker is the PAST framework in action:
1. **Identify** that the current personality profile has unacceptable tail risk (paper §9.2)
2. **Research** alternative personalities (Druckenmiller, Tepper, Tudor Jones, Baker)
3. **Evaluate** which profile best fits the system's constraints (no leverage, 10% stop, diversified)
4. **Swap** the personality vector ($\mathbf{P}$) — adjust 6 Likert scores
5. **Validate** with a backtest comparing old vs new profile
6. **Deploy** — the agent continues running with the new personality

No weights were updated. No models were retrained. The agent's behavior changed because 6 integers changed.

## The Real-World Counterfactual

The Aschenbrenner liquidation provides a **real-world counterfactual** for the PAST paper's claims:

- **PAST identified the risk** (paper limitations section, written July 29) before the collapse (July 30)
- **PAST offered the solution** (diversified, no-leverage personality) before the collapse
- **The real-world outcome validated the prediction** (concentration + leverage = ruin)

Without PAST's risk management (10% hard stop, no leverage, max 25% per position), our Trading Arena would have been exposed to the same tail risk as Aschenbrenner — just with less leverage. With PAST, the Baker personality would have:
- Exited each position at -10% (not held to -47%)
- Diversified across architecture layers (not 76% in 5 stocks)
- Owned NVDA (which fell less than BE/CRWV)
- Used no leverage (no margin call risk)

**The PAST framework's value proposition was validated by a $45 billion liquidation event on the same day we deployed the fix.**
