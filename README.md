# PAST Framework

**PAST (Personality-Adaptive Score Tuning) — weight-free behavioral alignment for multi-agent LLM systems. Tune the persona, not the weights.**

## What is PAST?

PAST is a novel framework for controlling and aligning the behavior of multi-agent LLM systems **without fine-tuning model weights**. Instead of modifying neural network parameters (RLHF, DPO, LoRA), PAST quantifies agent personality as a vector of Likert-scale scores (1–7) that cascade into specific trading rules and prompt-level constraints. A supervisory "Coach" agent evaluates performance bi-weekly and adjusts these scores within a trust region (±1 per cycle), creating a closed-loop learning system where **agents learn from their PAST**.

## Key Properties

- **Weight-free alignment** — no GPU training, no backpropagation, no checkpoint rollback
- **Real-time reversible** — adjust a single integer to change behavior
- **Full auditability** — every score change is logged with justification
- **Trust region stability** — ±1 per cycle prevents wild oscillation (inspired by PPO)
- **In-Context Log Exploitation (ICLE)** — agents learn from their own execution history at the inference boundary

## The PAST Formula

$$P_{i,t+1} = \max\left(1, \min\left(7, \left\lfloor P_{i,t} + \Delta P_{i,t} \rceil\right)\right)\right)$$

Where:
- $P_{i,t}$ is the Likert score for trait $i$ at bi-weekly interval $t$
- $\Delta P_{i,t}$ is the coach adjustment (clipped to ±1)
- The trust region constraint: $|\Delta P_{i,t}| \leq 1$

## Architecture

The Trading Arena implements PAST with four agents:

| Agent | Role | Model | Strategy |
|-------|------|-------|----------|
| **Alpha** 🤵 | Trader | GLM-5.2 (exec + reasoning) | Renaissance / mean reversion (RSI < 35, 3% stop) |
| **Beta** 🧥 | Trader | GLM-5.2 (exec) / Deepseek R1 70B (reasoning) | Atreides / architecture-first AI (10% stop, diversified) |
| **Judge** 🔨 | Verifier | Claude Fable 5 (Claude Code) | 13-point checklist, independent verification via `claude -p` |
| **Rocky** 🦊 | Coach | GLM-5.2 (exec) | Bi-weekly PAST tuning, ±1 trust region |

## Backtest Results

Jan 1 — Jul 21, 2026 | 6 tickers | portfolio-level, shared $2,500 per agent

> **v0.4.1 integrity update:** earlier READMEs and paper drafts reported +11.7% / +15.3%. Those numbers came from the v1 harness, which simulated each ticker as an independent $2,500 book and summed the results (plus look-ahead 52-week extremes and a stub Judge). They are retracted. The figures below are from `backtest/backtest_v3.py` — one shared cash pool per agent, strictly rolling indicators, a deterministic Judge that scores only checks that can actually fail, re-entry eligible the session after a stop. Raw JSON in `examples/backtest_v3/`; full tables in [docs/BACKTEST_V3_RESULTS.md](docs/BACKTEST_V3_RESULTS.md); defect history in [CHANGELOG v0.4.1](CHANGELOG.md).

| Agent | Final equity | Return | Closed trades | Max drawdown |
|-------|-----|-------|-------|-------|
| Alpha $[3,2,2,3]$ | $2,563.84 | +2.55% | 22 long, 3–5 session holds (41% win) | −2.9% |
| Beta — Baker $[5,6,3,6]$ (live profile) | $2,867.64 | +14.71% | 10 (all stops) | −30.7% |
| Beta — Aschenbrenner $[6,7,5,7]$ | $2,358.18 | −5.67% | 3 (all stops) | −9.4% |
| **Alpha + Beta (Baker)** | **$5,431.48** | **+8.63%** | | |

**Do not read the +8.6% as outperformance.** Beta's gain is one unrealized MU position entered the session after a stop-loss; if that re-entry is one session later the combined book is −3.0% (paper §7.6). What the backtest shows robustly is the PAST mechanism working: two personality vectors produced a 10× difference in drawdown and completely different trade cadence on identical price data, and the coach loop moved scores within its ±1 trust region in response to observed losses.

## Case Study: Aschenbrenner → Baker (July 30, 2026)

The PAST framework identified the risk of Aschenbrenner's leveraged, concentrated profile in the research paper (limitations section, written July 29) — **one day before** his $45B fund was liquidated by margin call on July 30. That same day, Agent Beta's personality was swapped from Aschenbrenner to Gavin Baker (Atreides Management, Sharpe 2.46), who survived the same crash with a -3.5% drawdown.

The next day (July 31), the Financial Times reported that Aschenbrenner himself vowed to "fight another day" and committed to **no longer using leverage** — exactly what PAST had already done programmatically by changing 6 Likert scores.

**6 integers changed. No weights updated. No models retrained. The agent's behavior changed.**

📖 **Full case study:** [docs/CASE_STUDY_Aschenbrenner_to_Baker.md](docs/CASE_STUDY_Aschenbrenner_to_Baker.md)

## Quick Start

### Option A — Reproduce the paper's results (v3, recommended)

Portfolio-level, shared capital, rolling indicators, deterministic Judge. No
API keys or LLM required — runs in about a minute.

```bash
# Clone
git clone https://github.com/sloth1122/past-framework.git
cd past-framework

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r backtest/requirements.txt

# Base case (every number in the paper's §7 and this README)
python backtest/backtest_v3.py

# Sensitivities reported in paper §7.6
python backtest/backtest_v3.py --cooldown 1
python backtest/backtest_v3.py --cooldown 5
python backtest/backtest_v3.py --cooldown -1      # v1 same-bar artifact
python backtest/backtest_v3.py --no-ipo-ban

# Regenerate docs/BACKTEST_V3_RESULTS.md (incl. the §7.6 sensitivity table)
B=examples/backtest_v3   # committed paper runs; or ~/trading-arena/state/backtests
python backtest/report_v3.py "$B/backtest_v3_ipoban_cd0_*.json" --sens \
  "Same-bar re-entry (v1 artifact, cooldown −1)=$B/backtest_v3_ipoban_cd-1_*.json" \
  "1 further session (cooldown 1)=$B/backtest_v3_ipoban_cd1_*.json" \
  "5 further sessions (cooldown 5)=$B/backtest_v3_ipoban_cd5_*.json" \
  "IPO ban off=$B/backtest_v3_noipoban_cd0_*.json"
```

Output JSON is written to `~/trading-arena/state/backtests/` (override with
the `OUT_DIR` environment variable); the runs used for the paper are committed under
`examples/backtest_v3/`.

### Option A′ — LLM-in-the-loop single-ticker run (v0.2.0)

Uses a real LLM Judge via local Ollama; single ticker only, not used for the
published results.

```bash
ollama pull deepseek-r1:32b
python backtest/backtest_v2.py OKLO 2025-08-01 2026-07-21
```

### Option B — Original backtest (v0.1.0, reference only)

The original harness is retained for reproducibility. See
[CHANGELOG](CHANGELOG.md) for known issues.

```bash
# Run the original backtest
python backtest/run_backtest.py

# Generate HTML report
python backtest/generate_backtest_report.py
```

## Repository Structure

```
past-framework/
├── docs/
│   ├── PAST_Research_Paper_v2.md   ← Full research paper
│   ├── PAST_Research_Paper_v2.4.pdf ← PDF version (v2.4, September 2026)
│   ├── PAST_Research_Paper_v2.3_RETRACTED.pdf ← superseded; return figures withdrawn
│   └── BACKTEST_V3_RESULTS.md      ← generated backtest tables
├── backtest/
│   ├── backtest_engine.py          ← Agent rules, indicators (RSI, MA)
│   ├── backtest_sim.py             ← [v0.1.0] Simulation, stub Judge, Rocky tuning
│   ├── backtest_v3.py              ← [v0.4.1] Portfolio-level harness — source of all published figures
│   ├── report_v3.py                ← [v0.4.1] JSON → docs/BACKTEST_V3_RESULTS.md
│   ├── backtest_v2.py              ← [v0.2.0] Single-ticker runner (rolling window, LLM Judge)
│   ├── llm_judge.py                ← [v0.2.0] LLM Judge + Rocky via local Ollama
│   ├── run_backtest.py             ← [v0.1.0] Original runner + go/no-go
│   ├── generate_backtest_report.py ← HTML report generator
│   └── requirements.txt
├── examples/
│   ├── backtest_v3/                ← Raw JSON for every run cited in the paper
│   ├── spacex_simulation.html      ← SpaceX IPO case study
│   └── backtest_report.html        ← Backtest results dashboard
├── CHANGELOG.md                    ← Version history + reviewer notes
└── skills/
    ├── trading-arena-alpha.md      ← Alpha skill (Renaissance/Jim Simons)
    ├── trading-arena-beta.md       ← Beta skill (Gavin Baker/Atreides)
    └── trade-judge.md              ← Judge skill (13-point checklist)
```

## Development Workflow

### Branch Protection

The `main` branch is protected:
- **PR required** — no direct commits to `main`
- **1 review required** — CodeRabbit AI or human approval before merge
- **Force-push blocked** — history cannot be rewritten
- **Deletion blocked** — branch cannot be deleted
- **Admins enforced** — rules apply to repo owner

### Code Review

[CodeRabbit AI](https://coderabbit.ai) reviews every pull request automatically. Each PR receives:
- Actionable comments with specific file/line references
- Walkthrough summary of changes
- Pre-merge checks (5+ automated validations)

### Model Architecture

The PAST Framework uses a split model strategy:

| Layer | Model | Provider | Use Case |
|-------|-------|----------|----------|
| Engineering session | Claude Sonnet 4.5 | Anthropic | Code review, repo management, architecture |
| Trading execution (all agents) | GLM-5.2 | Z.AI ($384/qtr) | Cron sessions, tooling, MCP, order placement |
| Beta reasoning | Deepseek R1 70B | Ollama (local) | Baker architecture-first thesis analysis |
| Judge | Claude Fable 5 | Claude Code (`claude -p`) | 13-point trade verification |

### Contributing

1. Create a feature branch from `main` (`git checkout -b feat/your-feature`)
2. Make changes and commit with conventional format (`feat:`, `fix:`, `docs:`)
3. Push and open a PR against `main`
4. CodeRabbit will review automatically — address any actionable comments
5. Merge after approval

## PAST vs Other Alignment Methods

| Dimension | DPO / RLHF | LoRA / PEFT | PAST |
|-----------|------------|------------|------|
| What is tuned | Model weights | Adapter weights | Likert scores → prompts |
| Requires | GPU training | GPU training | CPU-only, observation |
| Reversibility | Difficult (retrain) | Moderate (swap adapter) | Trivial (adjust score) |
| Compute | Hours to days | Minutes to hours | Instant |
| Auditability | Opaque (weights) | Opaque (adapters) | Full audit trail |
| Catastrophic forgetting | Yes (risk) | Reduced | None (model frozen) |

## Citation

```bibtex
@article{tytko2026past,
  title={Tuning the Persona, Not the Weights: The PAST Framework for Personality-Adaptive Multi-Agent Trading Systems},
  author={Tytko, John},
  year={2026},
  url={https://github.com/sloth1122/past-framework}
}
```

## License

MIT — see [LICENSE](LICENSE)

## Disclaimer

This research is for educational purposes. Past performance does not indicate future results. The Trading Arena uses real capital and accepts the risks of AI-driven trading.
