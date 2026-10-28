# Gate 1 — Deterministic Pre-Gate for LLM Trading Agents

Mechanical fact-check layer that runs **before** the LLM Judge in a
multi-agent trading arena. Born from an audit of the Judge's own decision
log: nearly every catch was arithmetic, not reasoning — misstated market
caps (5.5x, 6x errors), buying-power misrepresentation, stale prices
placed into pre-market gaps, risk/reward ratios that don't recompute.
No LLM should ever spend reasoning budget on arithmetic a script can't
get wrong.

## The 10 checks (number vs number, zero LLM)

| Check | What it rejects |
|---|---|
| `INPUT` | zero, negative, NaN or non-numeric shares/prices/position value (fails closed) |
| `CAPITAL` | position value > actual deployable (shared-cash misreps), or > the per-trade cap ($2,900) |
| `SLOTS` | book/layer position caps; layer must be compute, memory, networking or power. Adding to a ticker already held is **not** checked — CAPITAL/RISK size each order on its own |
| `MKTCAP` | claimed market cap vs verified source (±10%) |
| `PRICE` | stale quote (>5 min), wrong-instrument parse (>±2%), gap-chase (>1.5% above claimed) |
| `RR` | R/R recomputed from entry/target/stop — floor 2:1; a claim >5% above the real ratio is rejected |
| `STOP` | **stop distance = 2×ATR14, floor 5%, cap 20% below entry** — normal noise can't kill a months-long thesis (anti-whipsaw); fails closed without ATR14 |
| `RISK` | wider stop ⇒ smaller size; dollar risk ≤ fixed budget (3% of equity) |
| `EARN` | earnings inside the hold are allowed but must be gap-sized: shares × max(stop distance, implied move) ≤ risk budget |
| `REENTRY` | re-entry ban after recent stop-out in same ticker (5d) |

## Current rules (Arena v5.1, Oct 24 2026)

Constants live in `CONFIG` at the top of `gate1_pregate.py`: max 4 positions
(3 event bets + 1 QQQ core), max position value $2,900 (30% of ~$9.7K equity),
risk budget $290 (3% of equity). When the trusted account payload
includes `equity`, both limits are recomputed from it (30% / 3%). $50 fee
buffer instead of a cash reserve, R/R floor 2:1, re-entry ban 5 days.
Earlier versions used a 10% stop floor, $750 cap, 5 positions and a 7-day
pre-earnings blackout (see CHANGELOG).

## Usage

```
python3 gate1_pregate.py --selftest       # regression suite — run after ANY edit

# enforce: ALL three trusted sources required (exit 0 = PASS, 1 = REJECT,
# 2 = refused because a trusted source is missing)
python3 gate1_pregate.py --thesis t.json --account a.json --market m.json --book b.json
python3 gate1_pregate.py --thesis t.json --account a.json --market m.json --book b.json --shadow  # log-only

# demo/testing: account/market/agent_book embedded in the thesis file
python3 gate1_pregate.py --thesis t.json --demo --shadow
```

Input files must be `.json` files inside the script's folder or
`~/trading-arena/state` (add one more folder with `GATE1_INPUT_ROOT`);
anything else is refused with exit 2.

Every verdict is appended to `gate1_log.jsonl` with claimed-vs-verified
evidence. A check that *crashes* is treated as a FAIL, never a silent
pass — the gate cannot fail quietly by construction.

## Trust model

Account, market, and agent-book data is trusted ONLY when injected by
the harness from live MCP pulls — all three of `--account/--market/--book`;
supplying only some is refused rather than filled from the thesis. A thesis
file may embed these values ONLY in explicit `--demo` mode — enforce
mode refuses to run on submitter-controlled data, and the evaluation
clock is always the gate's own (a thesis cannot backdate freshness
checks).

## Validation methodology (how you know the gate works but isn't wrong)

1. **Selftest = synthetic scenarios built from real failure patterns.**
   Each test case reconstructs a failure pattern documented in the
   Judge's decision log (capital misrep, market-cap error, gap chase,
   R/R misrep, whipsaw stop, re-entry ban, earnings gap sizing, stale quote,
   layer cap, price-parse deviation) — not byte-for-byte replays of
   historical submissions. Includes positive controls and adversarial
   cases (backdated-clock attack, understated position value,
   allocation_share inflation, circular risk budget, negative shares,
   partial-trust fallback, thesis-claimed shared cash, ticker-casing evasion). 44 cases: 44 pass.
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
