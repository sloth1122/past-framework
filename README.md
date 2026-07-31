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
| **Alpha** 🤵 | Trader | GLM-5.2 | Renaissance / mean reversion (RSI < 35, 3% stop) |
| **Beta** 🧥 | Trader | Deepseek R1 70B | Atreides / architecture-first AI (10% stop, diversified) |
| **Judge** 🔨 | Verifier | Claude Fable 5 | 13-point checklist, independent verification |
| **Rocky** 🦊 | Coach | Claude Fable 5 | Bi-weekly PAST tuning, ±1 trust region |

## Backtest Results

Jan 1 — Jul 21, 2026 | 6 tickers | $5,000 proforma

| Agent | P&L | Trades | Win Rate |
|-------|-----|-------|----------|
| Alpha | +$8.86 | 17 | 35% |
| Beta | +$573.93 | 16 | 19% |
| **Combined** | **+$582.79** | **28** | **32%** |
| **Return** | **+11.7%** | | |

## Case Study: Aschenbrenner → Baker (July 30, 2026)

The PAST framework identified the risk of Aschenbrenner's leveraged, concentrated profile in the research paper (Section 7.2, written July 29) — **one day before** his $45B fund was liquidated by margin call on July 30. That same day, Agent Beta's personality was swapped from Aschenbrenner to Gavin Baker (Atreides Management, Sharpe 2.46), who survived the same crash with a -3.5% drawdown.

The next day (July 31), the Financial Times reported that Aschenbrenner himself vowed to "fight another day" and committed to **no longer using leverage** — exactly what PAST had already done programmatically by changing 6 Likert scores.

**6 integers changed. No weights updated. No models retrained. The agent's behavior changed.**

📖 **Full case study:** [docs/CASE_STUDY_Aschenbrenner_to_Baker.md](docs/CASE_STUDY_Aschenbrenner_to_Baker.md)

## Quick Start

```bash
# Clone
git clone https://github.com/sloth1122/past-framework.git
cd past-framework

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r backtest/requirements.txt

# Run the backtest
python backtest/run_backtest.py

# Generate HTML report
python backtest/generate_backtest_report.py
```

## Repository Structure

```
past-framework/
├── docs/
│   ├── PAST_Research_Paper_v2.md   ← Full research paper
│   └── PAST_Research_Paper_v2.pdf  ← PDF version
├── backtest/
│   ├── backtest_engine.py          ← Agent rules, indicators (RSI, MA)
│   ├── backtest_sim.py             ← Simulation, Judge, Rocky PAST tuning
│   ├── run_backtest.py             ← Runner + go/no-go recommendation
│   ├── generate_backtest_report.py ← HTML report generator
│   └── requirements.txt
├── examples/
│   ├── spacex_simulation.html      ← SpaceX IPO case study
│   └── backtest_report.html        ← Backtest results dashboard
└── skills/
    ├── trading-arena-alpha.md      ← Alpha skill (Renaissance/Jim Simons)
    ├── trading-arena-beta.md       ← Beta skill (Gavin Baker/Atreides)
    └── trade-judge.md              ← Judge skill (13-point checklist)
```

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
