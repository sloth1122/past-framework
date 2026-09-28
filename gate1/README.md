# Gate 1 — Deterministic Pre-Gate for LLM Trading Agents

Mechanical fact-check layer that runs **before** the LLM Judge in a
multi-agent trading arena. Born from an audit of the Judge's own decision
log: nearly every catch was arithmetic, not reasoning — misstated market
caps (5.5x, 6x errors), buying-power misrepresentation, stale prices
placed into pre-market gaps, risk/reward ratios that don't recompute.
No LLM should ever spend reasoning budget on arithmetic a script can't
get wrong.

## The 9 checks (number vs number, zero LLM)

| Check | What it rejects |
|---|---|
| `CAPITAL` | position value > actual deployable (shared-cash misreps) |
| `SLOTS` | book/layer position caps |
| `MKTCAP` | claimed market cap vs verified source (±10%) |
| `PRICE` | stale quote (>5 min), wrong-instrument parse (>±2%), gap-chase (>1.5% above claimed) |
| `RR` | R/R recomputed from entry/target/stop — floor 2:1, >5% misrep rejected |
| `STOP` | **stop must clear 2×ATR14** — normal noise can't kill a months-long thesis (anti-whipsaw) |
| `RISK` | wider stop ⇒ smaller size, dollar risk held constant |
| `EARN` | earnings blackout window (7d) |
| `REENTRY` | re-entry ban after recent stop-out in same ticker (5d) |

## Usage

```
python3 gate1_pregate.py --selftest       # regression suite — run after ANY edit
python3 gate1_pregate.py --thesis t.json # enforce mode: exit 0 = PASS, 1 = REJECT
python3 gate1_pregate.py --thesis t.json --shadow  # log-only (no enforcement)
```

Every verdict is appended to `gate1_log.jsonl` with claimed-vs-verified
evidence. A check that *crashes* is treated as a FAIL, never a silent
pass — the gate cannot fail quietly by construction.

## Validation methodology (how you know the gate works but isn't wrong)

1. **Selftest = replay of real catches.** Each test case is a real
   historical failure the LLM Judge caught. The gate must reproduce
   every one mechanically. 12 cases: 12 pass.
2. **Shadow mode.** Run before the LLM Judge for N sessions, logging only.
   Compare verdicts. The danger case is Gate-FAIL + Judge-APPROVE
   (over-rejection) — those get mandatory human review. Gate-PASS +
   Judge-REJECT is expected: the Judge catches reasoning problems
   (falling knives, catalyst reality) outside Gate 1's job.
3. **Enforce** only when shadow disagreement < 10%.

## Provenance

Extracted from a live 2-agent trading arena (Alpha: statistical mean
reversion; Beta: AI-infrastructure architecture). The stop-out audit
that motivated the `STOP` check: 3 of 7 stopped-out names recovered
above their stop price within days — the theses were right, but fixed
10% stops were ~2 days of normal volatility on high-ATR names, so
thesis-correct trades were converted into losses by the risk rule
itself.

MIT License. Educational — not investment advice.
