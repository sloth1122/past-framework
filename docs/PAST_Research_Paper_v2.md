# Tuning the Persona, Not the Weights: The PAST Framework for Personality-Adaptive Multi-Agent Trading Systems

**Author:** John Tytko — Creator and Author
**Date:** September 2026
**Version:** 2.4
**License:** MIT

## Abstract

Traditional alignment methodologies for Large Language Models (LLMs) rely heavily on parameter fine-tuning (e.g., LoRA, RLHF), which introduces prohibitive computational overhead and compromises the foundational generalization capabilities of the base model. To address this, we introduce the **Personality-Adaptive Score Tuning (PAST)** framework, a novel, weight-free orchestration layer for Multi-Agent Systems. Instead of altering neural network weights, PAST quantifies desired behavioral personas using a multi-dimensional Likert scale (1–7). These numerical personality profiles directly cascade into dynamic, prompt-level execution rules and scoring functions. A supervisory "Coach" agent evaluates operational KPIs on a bi-weekly cycle, iteratively tuning the Likert scores within a trust region to alleviate system bottlenecks and optimize performance. Operational agents autonomously exploit historical runtime logs to refine their behaviors *in-context* without backpropagation. We implement PAST in a four-agent trading system (two competing traders, an independent judge, and a coach) and evaluate it in a portfolio-level backtest across 6 tickers over 6.5 months (January–July 2026) with strictly rolling indicators and a shared $2,500 capital pool per agent. The combined book returned +8.6% (Alpha +2.6%, Beta +14.7% using Beta's live profile), but we do not present this as evidence of outperformance: Beta's entire gain is one unrealized position (MU, re-entered one session after a stop-loss), Beta's maximum drawdown was −30.7%, and delaying re-entry by a single additional session turns the combined result to −3.0%. What the backtest does show, robustly across every variant we ran, is the framework's central mechanism working as specified — the two personality vectors produced sharply different behavior on identical instruments (Alpha: 22 long trades held three to five sessions, 41% win rate, 2.9% max drawdown; Beta: 10 stop-outs and 5 held positions, −30.7% max drawdown), and the coach loop adjusted scores within its trust region in response to observed losses. An earlier draft of this paper reported +15.3%; that figure came from summing six independent single-ticker simulations, each funded with the full allocation, and is retracted (Section 6.5). Live trading began August 6, 2026 with $5,000 real capital on Robinhood. The first three weeks of production operation (through August 24) stress-tested the framework through a sector-wide AI infrastructure drawdown, three broker-side stop-loss executions, and two infrastructure failure modes — with zero PAST drift, a 100% Judge gate approval rate, and full risk-control enforcement. Our framework decouples agent behavioral alignment from model training, offering a highly resource-efficient, explainable, and fully reversible architecture for steerable AI systems.

---

## 1. Introduction

The deployment of Multi-Agent Systems (MAS) powered by Large Language Models (LLMs) has emerged as a dominant paradigm for solving complex, distributed tasks. By coordinating specialized agents to collaborate or compete, these systems simulate human workflows to execute multi-step objectives. However, controlling and aligning behavioral dynamics within a multi-agent collective remains a significant open challenge.

Current methods for altering or aligning agent behavior heavily rely on parameter-level adjustments. Techniques such as Full Fine-Tuning, Low-Rank Adaptation (LoRA), and Reinforcement Learning from Human Feedback (RLHF) modify the underlying neural network weights to achieve stylistic or behavioral shifts. While effective for single-model alignment, parameter fine-tuning is fundamentally ill-suited for the dynamic, iterative requirements of multi-agent orchestration due to three primary limitations:

- **Prohibitive Compute Costs**: Retraining or updating weights across an entire collective of heterogeneous agents demands massive hardware and time commitments.
- **Loss of Model Generalization**: Fine-tuning a model to exhibit a narrow behavioral trait frequently causes catastrophic forgetting, degrading its baseline reasoning capabilities.
- **Irreversibility**: Once neural network weights are updated, reversing a behavioral shift requires reverting to past checkpoints or initiating a fresh training cycle, eliminating real-time agility.

To bypass these limitations, practitioners frequently turn to prompt engineering and hardcoded system prompts to establish agent personas. While compute-efficient, this approach is fundamentally static. It lacks an evolutionary mechanism to self-correct when behavioral conflicts, communication bottlenecks, or operational inefficiencies arise during runtime.

To bridge the gap between expensive weight modification and rigid prompt engineering, we introduce the **Personality-Adaptive Score Tuning (PAST)** framework. PAST is a novel, weight-free alignment layer that formalizes agent behaviors into quantified human personality dimensions via a standard 1–7 Likert scale. Instead of modifying network parameters, these quantified personality vectors cascade directly into runtime constraints, prompt modifications, and evaluation metrics at the model's inference boundary.

The core contribution of this work is the decoupling of behavioral adaptation from neural network optimization. Under the PAST architecture, an autonomous, supervisory "Coach" agent audits system-wide Key Performance Indicators (KPIs) and operational logs on a bi-weekly cadence. Identifying systemic bottlenecks, the Coach shifts the agent's numerical Likert vector within a trust region (±1 per cycle). This adjustment immediately alters downstream behavior without backpropagation. Concurrently, operational units utilize historical runtime logs to guide their in-context adaptation, effectively learning from their own execution "PAST."

This paper makes the following contributions:

1. **The PAST framework** — a formal, mathematical definition of personality scores as Likert vectors, their mapping to operational constraints via a rule cascade, and the coach-mediated tuning loop with trust region. Conceptualized by the author as a weight-free alternative to RLHF/DPO for multi-agent behavioral alignment.
2. **In-Context Log Exploitation (ICLE)** — a micro-level feedback mechanism where agents learn from their own execution history at the inference boundary
3. **A four-agent competitive trading architecture** — two traders with opposite strategies, an independent judge, and a coach — implemented on heterogeneous models (GLM-5.2, Deepseek R1, Claude Fable 5), deployed live with real capital since August 6, 2026
4. **Empirical evaluation** — a portfolio-level backtest across 6 tickers and 6.5 months (combined +8.6%, entirely from one unrealized position and not robust to a one-session change in re-entry timing; no outperformance claimed) demonstrating that PAST scores produce predictable, differentiated agent behavior on identical instruments, followed by live production deployment with 6 real positions in the first three weeks, three broker-side stop executions, and zero PAST drift. The backtest harness, raw JSON outputs, and every table in Section 7 are reproducible from the public repository.

While this paper validates PAST in the financial trading domain, the framework is domain-agnostic. The same personality tuning mechanism — quantified Likert scores, coach-mediated bi-weekly adjustment, in-context log exploitation — can be applied to any multi-agent system requiring behavioral adaptation, from AI tutors (where teaching style is tuned to student learning outcomes) to software engineering agents (where code review strictness is tuned to project KPIs).

---

## 2. Related Work

### 2.1 Multi-Agent Orchestration Frameworks

Modern multi-agent architectures rely on frameworks like Microsoft's AutoGen, CrewAI, and LangGraph to coordinate autonomous collectives. AutoGen focuses on conversation-driven workflows via customizable agents. CrewAI structures agents into production-oriented "crews" with defined roles, tasks, and tool access. LangGraph introduces cyclic graph topologies for complex state machines.

While these frameworks excel at infrastructure, they lack native mechanisms for dynamic, self-correcting behavioral alignment. Agent personas are rigidly codified at initialization via static system prompts. If a persona creates an operational bottleneck, resolving the issue requires manual prompt rewriting and system restart. PAST supplements these frameworks by introducing an algorithmic layer that translates quantified metrics into fluid prompt adjustments, allowing agent behaviors to evolve programmatically.

### 2.2 Multi-Agent LLM Trading Frameworks

**TradingAgents** (Tauric Research, 80k+ GitHub stars) simulates a trading firm with 7 specialized LLM agents (fundamental, sentiment, news, technical analysts + bull/bear researchers + trader + risk manager). Agents debate before reaching consensus. Published results show 24.9% annualized returns with Sharpe ratios of 1.69-2.11. The framework uses static agent roles — no personality tuning.

**AI Hedge Fund** (virattt, 51.7k stars) deploys 18 agents embodying legendary investor personas (Buffett, Munger, Burry, Wood). Each agent has a fixed investment philosophy encoded in its prompt. Explicitly a simulation — no real trades execute. No personality adaptation.

**AI-Trader** (HKUDS, 21k stars) provides agent-native trading with a "team challenge mode" for competitive agents. Closest to our competitive architecture but lacks a coaching/tuning layer.

### 2.3 Psychometric Profiling and LLM Personas

A growing body of literature explores the capacity of LLMs to simulate human personality structures using frameworks like the Big Five (OCEAN) or Myers-Briggs Type Indicator (MBTI). Researchers have demonstrated that prompting LLMs with specific trait descriptions alters their decision-making risk profiles, linguistic styles, and negotiation behaviors.

However, existing research predominantly treats LLM psychometrics as an evaluative curiosity rather than an operational tuning knob. Current implementations rely on long, descriptive prompt paragraphs to induce a persona, consuming significant context windows and suffering from high prompt sensitivity. PAST formalizes persona engineering by converting raw qualitative text into structured 1–7 Likert vectors, mapping numeric scores directly to inference-boundary constraints.

### 2.4 Parameter-Efficient vs. Weight-Free Alignment

Traditional alignment modifies model weights to enforce preferences. Direct Preference Optimization (DPO) and RLHF adjust token probabilities at the parameter level. While effective, parameter tuning is computationally prohibitive for runtime multi-agent optimization, lacks real-time reversibility, and triggers catastrophic forgetting.

Parameter-Efficient Fine-Tuning (PEFT) techniques like LoRA isolate weight updates to compact adapter modules. Even with LoRA, switching an agent's persona mid-task requires hot-swapping weight matrices, incurring latency penalties and requiring GPU orchestration. PAST introduces a completely **weight-free alignment** paradigm — the tuning target shifts entirely from neural network parameters ($W$) to structured prompting scores ($P$), achieving real-time behavioral plasticity through API boundaries while maintaining a frozen, highly generalized base model.

---

## 3. The PAST Framework

### 3.1 The Likert Personality Vector
Let $P$ represent the personality profile of an agent, defined as a multi-dimensional vector in a discrete parameter space:

$$P = [P_1, P_2, \dots, P_n]^T, \quad \text{where } P_i \in \{1, 2, \dots, 7\}$$

Each dimension $i$ corresponds to an explicit behavioral attribute. The framework supports domain-specific trait definitions. For the Trading Arena, the traits are:

| Trait | Agent Alpha | Agent Beta | What It Controls |
|---|---|---|---|
| Risk Tolerance | 3/7 | 5/7 | Max position size, stop-loss width, leverage |
| Conviction | 2/7 | 6/7 | Whether to hold through drawdowns |
| Impulsivity | 2/7 | 3/7 | How quickly to act on a signal |
| Entry Patience | 3/7 | 6/7 | How long to wait for the right entry price |
| Hold Duration | 3/7 | 7/7 | How long to hold once entered — thesis vs price-based exits |
| Adaptability | 4/7 | 6/7 | How quickly to shift strategy when conditions change |
| Technical Focus | 7/7 | 3/7 | Weight on statistical signals vs fundamental thesis |
| Sector Specialization | 1/7 | 7/7 | Domain focus (Alpha = agnostic, Beta = AI architecture only) |
| Position Concentration | 4/7 | 4/7 | Diversification vs concentration |

These are the production vectors as deployed on August 6, 2026 (`skills/trading-arena-alpha.md`, `skills/trading-arena-beta.md`). Rocky has since adjusted two scores in live operation — Alpha Entry Patience 3→4 and Beta Technical Focus 3→2, both on August 29 — which are reported in §8.3. The backtest uses the go-live vectors.

**Key design decision: splitting Patience into two traits.** An early version of the framework used a single "Patience" score, but this conflated two distinct behaviors: patience to *enter* (sitting in cash waiting for the right price) and patience to *hold* (keeping a position through short-term volatility because the thesis is intact). Agent Beta (Baker) has Entry Patience=6 (waits for pullbacks) but Hold Duration=7 (holds architecture positions for months). Agent Alpha has Entry Patience=3 (trades whenever its statistical criteria are met, without waiting for a better price) and Hold Duration=3 (exits in 3–5 days). The split captures the distinction that a single score could not.

| Dimension ($i$) | Attribute | Trading Rule Impact |
|-----------------|----------|---------------------|
| $P_1$ | Risk Tolerance | Stop loss percentage ($P_1=3 \to 3\%$ stop, $P_1=6 \to 10\%$ stop) |
| $P_2$ | Conviction | Position sizing and hold duration |
| $P_3$ | Impulsivity | Entry speed (act immediately vs. wait for confirmation) |
| $P_4$ | Patience | Entry threshold strictness (stricter filter = fewer trades) |

Additional dimensions can be defined (Adaptability, Technical Focus, Sector Specialization, Position Concentration) but the four core scores are sufficient to produce differentiated behavior.

### 3.2 The Rule Cascade and Mapping Functions

The core of the weight-free alignment layer is the mapping function $f(P_i)$, which translates a single scalar Likert score into an operational, text-based system constraint ($C_i$). This mapping uses a linear scaling operation to determine a constraint severity multiplier, $\alpha_i$:

$$\alpha_i = \frac{P_i - 1}{6}, \quad \text{where } \alpha_i \in [0, 1]$$

This coefficient scales both the quantitative execution parameters and the dynamic prompt templates injected into the context window. The global system prompt ($S$) presented to the agent at runtime is constructed via a concatenation of the base task role ($R$) and the active personality constraints:

$$S = R \ \cup \ \bigcup_{i=1}^{n} \Phi\left(\alpha_i, T_i\right)$$

Where $T_i$ represents a structured prompt matrix mapping extreme traits ($P_i=1$ vs. $P_i=7$) to clear behavioral rules, and $\Phi$ is the dynamic text compiler.

**Example cascade (Trading Arena, Alpha Entry Patience):**
- $P_4 \leq 6 \implies$ standard entry filter: RSI $< 35$ AND rising 50-day MA (secondary entry at RSI 35–45, reduced size)
- $P_4 = 7 \implies \alpha_4 = 1.0 \implies$ stricter filter: RSI $< 20$ AND rising 50-day MA AND bullish candle confirmation; secondary entry disabled

A single integer change ($6 \to 7$) cascades through the rule engine to tighten the entry threshold and reduce trade frequency. This is the only trait with a fully specified cascade in the current implementation (see §7.4).

### 3.3 Mathematical Formulation of the Coach Review Loop

Let $\mathbf{P}_t = [P_1, P_2, \dots, P_n]^T$ be the personality vector at bi-weekly interval $t$. The optimization objective of the supervisory Coach agent is to minimize the variance between target system KPIs ($K_{\text{target}}$) and observed runtime metrics ($K_{\text{observed}, t}$). At the end of each two-week window, the Coach updates each personality trait score using the following clipped transition function:

$$P_{i, t+1} = \max\left(1, \min\left(7, \left\lfloor P_{i, t} + \Delta P_{i, t} \right\rceil\right)\right)$$

Where $\lfloor \cdot \rceil$ denotes rounding to the nearest integer to maintain strict Likert boundaries. The delta adjustment is:

$$\Delta P_{i, t} = \gamma \cdot \sigma_i \cdot \Phi\left( K_{\text{target}} - K_{\text{observed}, t} \right)$$

Where:
- $\gamma \in (0, 1]$ is the Coach's *adaptation velocity* (learning rate).
- $\sigma_i \in \{-1, 1\}$ is a directional sign vector derived by the Coach's semantic reasoning layer, dictating whether increasing or decreasing trait $i$ mitigates the observed bottleneck.
- $\Phi(\cdot)$ is a normalized scaling function mapping the performance deficit to a scalar shift.

The trust region constraint ($|\Delta P_{i,t}| \leq 1$) is inspired by Proximal Policy Optimization's clipped objective (Schulman et al., 2017). It ensures that personality evolves gradually rather than swinging wildly based on short-term results — a critical stability property for systems handling real capital.

### 3.4 PAST vs DPO vs RLHF

| Dimension | DPO / RLHF | LoRA / PEFT | PAST |
|-----------|------------|------------|------|
| What is tuned | Model weights | Adapter weights | Likert scores → prompts |
| Requires | GPU training, preference data | GPU training, adapter modules | CPU-only, observation of outcomes |
| Granularity | Model-level | Model-level | Agent-level (per-agent) |
| Reversibility | Difficult (retrain) | Moderate (swap adapter) | Trivial (adjust score) |
| Compute | Hours to days | Minutes to hours | Instant |
| Auditability | Opaque (weights) | Opaque (adapters) | Full audit trail (logged score changes) |
| Catastrophic forgetting | Yes (risk) | Reduced | None (base model frozen) |

PAST does not replace RLHF/DPO/LoRA — it operates at a different abstraction level. These methods tune the model; PAST tunes the instructions given to the model. They are complementary.

---

## 4. In-Context Log Exploitation (ICLE)

While the supervisory Coach agent establishes macro-level behavior via bi-weekly Likert vector shifts, operational units execute micro-level self-correction via **In-Context Log Exploitation (ICLE)**.

### 4.1 The ICLE Feedback Loop

Under traditional architectures, an agent approaches each execution task as an isolated, stateless event. Under PAST, agents are explicitly bound to their execution history. The ICLE mechanism functions as a localized, non-gradient optimization loop:

1. **Chronological Log Compaction:** The agent's runtime wrapper maintains an append-only transaction log containing requests, reasoning paths, tool calls, outputs, and execution scores. When an agent initiates a task, a retrieval mechanism extracts the $K$ most relevant log traces. These are passed through a summarization layer to strip token noise while preserving explicit fault lines (exceptions, rejections, timeouts).

2. **Self-Contrastive Inference:** The agent ingests the compacted history alongside its freshly tuned Likert rules. It evaluates its historical trajectory via an internal meta-prompt: *"Identify where past behaviors violate the boundary limits of the newly assigned personality metrics."*

3. **Behavioral Shifting:** The agent modifies its immediate execution strategy based on this self-contrastive analysis. For instance, if Alpha reads that its Patience score was increased from 6 to 7 by the Coach, and its execution log reveals that previous trades at RSI 35-40 resulted in losses, it explicitly suppresses entries in the 35-40 range in the current context window.

### 4.2 Mathematical Formalization of ICLE Context

Let $H_t$ be the historical log trace up to task $t$, where each entry $h \in H_t$ contains the tuple of prompt, response, and performance feedback: $h = (x, y, r)$. The operational context window $C_t$ passed to the underlying frozen LLM is:

$$C_t = S(\mathbf{P}_t) \ \cup \ \Psi(H_t, K) \ \cup \ x_t$$

Where $S(\mathbf{P}_t)$ is the system prompt generated by the Likert vector cascade, $x_t$ is the current task input, and $\Psi(H_t, K)$ is a filtering operator that compresses the historical log down to the $K$ most critical behavioral failure vectors. By injecting $\Psi(H_t, K)$, the agent performs in-context learning over its own operational timeline — learning from its PAST at the inference boundary.

### 4.3 Trading Arena Implementation

In the Trading Arena, ICLE is implemented via file-based memory:

| File | ICLE Role | Updated By |
|------|-----------|------------|
| `state/agent_alpha/state.md` | Alpha's trade history, P&L, strategy learnings | Alpha (after each trade) |
| `state/agent_beta/state.md` | Beta's trade history, P&L, strategy learnings | Beta (after each trade) |
| `state/judge_decision_log.md` | Judge verdicts (append-only audit trail) | Judge |
| `state/rocky/week_N_notes.md` | Coach's bi-weekly tuning notes | Rocky |

At the start of each trading session, agents read their state file (containing the $K$ most recent trades and learnings) via `read_file()`. This is the $\Psi(H_t, K)$ operator — compressed history injected into the context window. The agent then self-evaluates: "My last 3 trades at RSI 35-40 all lost. My Patience is now 7. I will require RSI < 20 before entering." This is ICLE in action.

---

## 5. System Architecture

### 5.1 Four-Agent Design

The Trading Arena deploys four agents with distinct roles, using a two-layer model architecture (execution layer + reasoning layer):

| Agent | Role | Execution Layer | Reasoning Layer | Provider | Location |
|-------|------|----------------|-----------------|----------|----------|
| **Alpha** | Trader (Renaissance) | GLM-5.2 | GLM-5.2 | Z.AI API | Cloud |
| **Beta** | Trader (Baker/Atreides) | GLM-5.2 | Deepseek R1 70B | Z.AI + Ollama | Cloud + Local |
| **Judge** | Independent verifier | Claude Fable 5 | — | Claude Code | Cloud |
| **Rocky** | Coach (PAST tuning) | GLM-5.2 | — | Z.AI API | Cloud |

**Design principle: cognitive diversity.** Alpha and Beta run on different reasoning models from different providers. Alpha uses a 744B MoE model (GLM-5.2) optimized for long-context reasoning. Beta's reasoning layer uses a 70B dense model (Deepseek R1) optimized for local inference. The Judge uses Anthropic's Claude (Fable 5) for independent verification. This three-model diversity prevents single-model bias — no two agents share the same "brain."

**Two-layer architecture note:** GLM-5.2 (via Z.AI cloud API) is the execution layer for ALL agents — it runs the Hermes Agent cron sessions, handles all tooling (`web_search`, `terminal`, file I/O), invokes the Judge gate via `claude -p`, and places orders. Deepseek R1 70B (local via Ollama) is Beta's reasoning brain — it analyzes the AI compute stack and formulates trade theses. GLM-5.2 executes; Deepseek reasons. This two-layer design demonstrates that PAST's persona-driven approach works across heterogeneous model configurations.

### 5.2 Agent Personalities

**Agent Alpha — Renaissance (Jim Simons style):**
$$\mathbf{P}_{\text{Alpha}} = [3, 2, 2, 3]^T \quad \text{(Risk, Conviction, Impulsivity, Entry Patience)}$$

Strategy: Statistical mean reversion. Buys oversold stocks with rising 50-day MAs. Holds 3-5 days. 3% stop loss. Sector-agnostic.

**Agent Beta — Baker / Atreides style (live since July 30, 2026; Appendix A):**
$$\mathbf{P}_{\text{Beta}} = [5, 6, 3, 6]^T \quad \text{(Risk, Conviction, Impulsivity, Patience)}$$

Strategy: AI infrastructure thesis, architecture-first. Buys pullbacks in second-order beneficiaries (power, nuclear, neocloud, optical). 10% stop loss. Weeks-months holds. The original Aschenbrenner profile, $[6,7,5,7]$, is also reported in the backtest (§6.3) for comparison.

### 5.3 The Judge (13-Point Checklist)

The Judge is a separate LLM that evaluates every trade proposal before execution. Key checklist items include:

1. Thesis supported by data
2. Position size appropriate
3. Stop loss set
4. PAST drift check (within trust region)
5. Convergence check (both agents in same ticker?)
6. Earnings within 5 days
7. Liquidity check
8. PAST personality fit
9. Options budget check (for Beta)
10. Catalyst present
11. State file honesty
11b. Restricted stock check
11c. **IPO ban** (HARD BLOCK — no stocks public < 90 days)
11d. PAST drift detection

**Separation of powers:** The Judge runs on a different model (Claude Fable 5) from both traders. It cannot be influenced by either agent's reasoning — it pulls its own data and applies the checklist independently. This is analogous to the separation between prosecution and judiciary in legal systems.

### 5.3.1 Pre-Trade Gate vs Post-Trade Audit

A critical design decision: the Judge serves as a **pre-trade gate**, not a post-trade auditor. The execution flow is:

1. Agent builds a trade thesis and writes it to a shared queue
2. Agent invokes the Judge (via Claude Code subprocess) BEFORE placing any order
3. Judge independently evaluates the thesis using the 13-point checklist
4. Judge writes APPROVED or REJECTED to the queue
5. **Only APPROVED theses are executed** — no trade is placed without Judge approval

A separate Judge audit runs at 2:10 PM MST (market close + 10 minutes) as a **post-trade verification** — confirming the agents followed the pre-trade decisions, respected stop-losses, and stayed within their PAST profiles.

This two-phase design prevents a significant practical problem: if the Judge rejected trades *after* execution (as in a post-trade-only design), agents would be forced to exit positions same-day, creating unnecessary trading costs, tax noise (short-term gains/losses, wash sale risk), and day-trading patterns. By gating trades *before* execution, the system ensures only validated trades reach the real account.

---

## 6. Experimental Setup

### 6.1 Backtest Configuration

The results in Section 7 come from the v3 harness (`backtest/backtest_v3.py`), which simulates one portfolio per agent across all tickers simultaneously.

| Parameter | Value |
|-----------|-------|
| Date range | January 1, 2026 — July 21, 2026 (137 trading days; SPCX listed June 12) |
| Tickers | SPCX, OKLO, NVDA, APLD, CCJ, MU |
| Capital | $2,500 per agent, one shared cash pool across all six tickers |
| Data source | Yahoo Finance (via yfinance), adjusted daily closes |
| Indicators | RSI(14), 50-day MA, 50-day MA slope (5-day lag), rolling 252-day high/low. Every value at day $D$ uses only data from $D-252$ to $D$. |
| Fills | Daily close; no commission; no slippage |
| Order of operations | Each day: exits first, then entries, tickers in alphabetical order (matters only when cash is binding) |
| Stop re-entry | A ticker stopped out at session $D$ is eligible for re-entry at session $D+1$ (the live arena runs once per session; broker-side stops fire intraday). Sensitivity to this rule is reported in §7.6. |
| Judge | Deterministic 6-item subset of the 13-point checklist; see §6.4 |
| Rocky tuning cycle | Every 10 trading days (~2 weeks), $\lvert \Delta P_{i,t} \rvert \leq 1$ |

### 6.2 Ticker Selection

Tickers were selected to span different market regimes and thesis categories:

| Ticker | Category | Why Selected |
|--------|----------|-------------|
| SPCX | IPO (June 2026) | Tests IPO behavior — agents should avoid or lose |
| OKLO | AI infra (nuclear/SMR) | Core power-bottleneck thesis |
| NVDA | AI infra (chips) | Thesis-banned for the Aschenbrenner Beta profile; permitted for Baker |
| APLD | AI infra (data centers) | Second-order beneficiary |
| CCJ | AI infra (uranium) | Adjacent to nuclear thesis |
| MU | Semiconductors (memory) | AI training demand — high volatility |

### 6.3 Agent Rules

**Alpha (Mean Reversion), $\mathbf{P} = [3,2,2,3]$:**
- **Primary entry:** RSI < 35 AND 50-day MA rising AND price > 85% of 50-day MA; 15% of allocation
- **Secondary entry:** RSI 35–45 AND 50-day MA rising AND price > 90% of 50-day MA; 8% of allocation
- **Patience = 7 cascade:** primary entry tightens to RSI < 20 AND rising MA AND bullish close; secondary entry disabled
- **Exit:** 3% stop loss OR RSI > 55 OR 5-day time limit
- **Max concurrent positions:** 4

**Beta — two profiles are reported.** The Aschenbrenner profile is the configuration the original draft of this paper described; the Baker profile is the one that has been live since July 30, 2026 (Appendix A). Both are run so the reader can see the effect of the personality swap on identical data.

| | Beta (Aschenbrenner) | Beta (Baker) |
|---|---|---|
| $\mathbf{P}$ (Risk, Conviction, Impulsivity, Patience) | $[6,7,5,7]$ | $[5,6,3,6]$ |
| Entry | Price within 25% of rolling 52-week low | Within 25% of 52-week low OR ≥15% below 52-week high |
| Position size | 20% of allocation | 25% of allocation |
| Banned | NVDA | none |
| Exit | 10% stop loss only; no time limit | 10% stop loss only; no time limit |
| Max concurrent positions | 6 | 5 |

### 6.4 What the Backtest Judge Can and Cannot Check

The production Judge applies 13 checks. Four require data a price-only backtest does not have: earnings calendar (item 6), options budget (9), catalyst (10), and state-file honesty (11). Four more cannot fail in a rule-based harness: position size (2) always equals the configured percentage; the stop (3) is a per-agent constant; PAST bounds (4) are clamped to 1–7 by Rocky before the Judge sees them; and convergence (5) is informational in production and never rejects. Rather than auto-pass any of these — which the v1 harness did — the v3 Judge scores only the six items that can genuinely fail (1 thesis supported by data, 7 liquidity, 8 personality fit, 11b restricted list, 11c IPO ban, 13 position cap) and scales the approval threshold by the same ratio as production (10/13 → 5/6). For item 1 the Judge re-derives the entry condition from the price row rather than trusting the agent's signal. For Beta it applies the stricter of the two Beta entry definitions (within 25% of the 52-week low), so a pullback-only Baker entry can fail it; for Alpha the Judge's re-derivation uses the same RSI and moving-average conditions as the entry rule, so item 1 is an independent check for Beta only. Item 8 can fail only if Rocky moves the fit trait past its threshold, which did not happen in the committed runs. Three items are hard blocks regardless of score: the IPO ban (no entries within 90 calendar days of listing), the agent's restricted list, and the position cap. A Judge approval does not guarantee a fill: if the agent's cash pool is exhausted the entry is skipped and recorded as "approved, no cash".

### 6.5 Retracted v1 Results

The first public draft of this paper (v2.3, August 2026) reported +15.3% combined return (+$763.27 on $5,000). That figure is withdrawn. The v1 harness had three defects: (i) it ran each ticker as an independent simulation, each starting with the full $2,500 per agent, then summed the six results — so the "return" was measured against $5,000 while up to $15,000 per agent was deployed; (ii) the 52-week high/low used by Beta's entry rule was computed over the full dataset, including future prices; (iii) the Judge auto-passed 5 of 13 checks. The single largest contributor to the retracted figure — a +$880 MU trade reported as +35.2% — was a $2,500 position, not the 20% position the rules specify, and depended on defect (i). Defects (ii) and (iii) were disclosed in the repository CHANGELOG on August 1, 2026; defect (i) was found while preparing this revision.

---

## 7. Results

All figures are from `backtest_v3_ipoban_cd0_*.json` (repository `examples/backtest_v3/`) via `backtest/report_v3.py`. The full trade-by-trade tables are in `docs/BACKTEST_V3_RESULTS.md`.

### 7.1 Overall Performance

| Metric | Alpha $[3,2,2,3]$ | Beta — Baker $[5,6,3,6]$ | Beta — Aschenbrenner $[6,7,5,7]$ |
|--------|------|------|------|
| Final equity (from $2,500) | $2,563.84 | $2,867.64 | $2,358.18 |
| **Return** | **+2.55%** | **+14.71%** | **−5.67%** |
| Realized P&L | +$39.46 | −$547.97 | −$186.19 |
| Unrealized P&L (open at end) | +$24.37 | +$915.60 | +$44.36 |
| Closed trades | 22 | 10 | 3 |
| Open at end | 1 | 5 | 2 |
| Win rate (closed) | 41% | 0% | 0% |
| Max drawdown | −2.9% | −30.7% | −9.4% |
| Judge approvals / signals | 23 / 23 | 80 / 105 | 5 / 37 |
| Approved but no free cash | 0 | 65 | 0 |
| Entries actually filled | 23 | 15 | 5 |

| Combined book ($5,000) | Final equity | Return |
|---|---|---|
| Alpha + Beta (Baker, live profile) | $5,431.48 | **+8.63%** |
| Alpha + Beta (Aschenbrenner) | $4,922.02 | −1.56% |

Beta's only exit rule is a stop-loss, so every *closed* Beta trade is a loss by construction; Beta's gains exist only as open positions marked at the last close. Win rate is therefore not a meaningful statistic for Beta and is shown only for completeness. Baker Beta's +$915.60 unrealized is dominated by a single position: MU, entered March 31 at $337.79 — one session after being stopped out at $321.75 — and marked at $970.82 on July 21 (+$506.43). Without that one position Baker Beta's return is −5.6%.

### 7.2 Per-Ticker Results

| Ticker | Alpha realized | Beta (Baker) realized | Beta (Baker) unrealized | Observation |
|--------|-----------|-----------|-----------|-----------------|
| SPCX | $0.00 (0 trades) | $0.00 | — | Beta blocked by the Judge IPO ban on all 25 signals; Alpha never signalled (RSI 89 at listing) |
| OKLO | −$11.37 (3) | −$278.55 (5) | +$0.30 | Beta stopped out five times in a downtrend; Alpha's tight stops limited damage |
| NVDA | −$8.85 (6) | — | +$119.92 | Beta held from Feb 4; Alpha scalped six short trades |
| APLD | +$81.11 (5) | −$66.58 (2) | +$288.95 | Alpha's best ticker (RSI exits); Beta stopped twice before its third entry ran |
| CCJ | −$36.44 (4) | −$130.33 (2) | $0.00 | Both lost; Beta held one position four months before the stop |
| MU | +$15.01 (4) | −$72.51 (1) | +$506.43 | Beta stopped out Mar 30 at $321.75, re-entered Mar 31 at $337.79, marked $970.82 |

### 7.3 Behavioral Diversity — The Core PAST Claim

The PAST framework's central claim is that different personality vectors produce different behavior on the same instrument. The data confirms this, independent of whether the behavior was profitable:

**Trade cadence.** Alpha ($P_3=2$ Impulsivity, $P_4=3$ Entry Patience, 5-session time exit) closed 22 trades with a median hold of 5 calendar days. Beta ($P_2=6$ Conviction, no time exit) closed 10 trades and was still holding 5 positions at the end of the window, one of them (NVDA) for 5.5 months.

**Risk exposure.** Alpha's 3% stop and 15% sizing produced a maximum drawdown of 2.9%. Beta's 10% stop and 25% sizing produced a maximum drawdown of 30.7% — the book fell from $3,794.32 on June 2 to $2,628.06 on July 17 as the MU mark retreated and OKLO and CCJ were stopped out. Beta's equity path is more than ten times as volatile as Alpha's on the same six instruments.

**Same ticker, opposite behavior.** On APLD, Alpha entered on February 5 at $27.84 and exited four days later on an RSI signal for +$74.99. Beta had entered the same name on January 2 at $28.11, held through Alpha's round-trip, and was stopped out March 6 at $25.14 for −$65.93. Identical price series; the personality vector, not the prompt wording, determined the outcome.

**The personality swap is visible in the data.** Aschenbrenner Beta (NVDA-banned, near-low entry only) generated 37 signals and had 32 rejected — 25 by the IPO ban on SPCX and 7 by the NVDA ban — leaving it largely in cash and producing a shallower drawdown (−9.4%) than Baker Beta (−30.7%), whose pullback entry rule and unrestricted universe kept it fully deployed through the Q1 correction. Baker Beta was so fully deployed that 65 of its 80 Judge approvals could not be filled for lack of cash — it was at or near its five-position cap of 25% each for most of the window.

### 7.4 PAST Score Evolution

| Agent | Trait | Cycle | $P_{i,t} \to P_{i,t+1}$ | Trigger | Cascade |
|-------|-------|-------|-----------|---------|---------|
| Alpha | Entry Patience | 6 (Mar 31) | 3 → 4 | Three closed trades in the period, all losses (CCJ stop Mar 20, MU stop Mar 26, CCJ time-exit Mar 30) | Recorded; §3.2 defines a cascade only at $P_4 = 7$, so the entry filter did not change |
| Beta (Baker) | Impulsivity | 3 (Feb 17) | 3 → 4 | One stop exit in period (OKLO) | Recorded; no cascade defined for Impulsivity |
| Beta (Baker) | Impulsivity | 5 (Mar 17) | 4 → 5 | One stop exit in period (APLD) | Recorded |
| Beta (Baker) | Impulsivity | 6 (Mar 31) | 5 → 6 | Four stop exits in period (OKLO, APLD, MU, OKLO) | Recorded |
| Beta (Baker) | Impulsivity | 11 (Jun 11) | 6 → 7 | One stop exit in period (CCJ) | Recorded |
| Beta (Aschenbrenner) | Impulsivity | 12, 13 | 5 → 6 → 7 | One OKLO stop in each period | Recorded |

Each adjustment responds only to trades closed since the previous review — Rocky sees a two-week window, not cumulative history — and every move is inside the ±1 trust region. Cycle 4 (Mar 3) produced no Beta adjustment because no position closed in that fortnight, and the four stops of late March produced exactly one +1 step at cycle 6, which is the behavior the trust-region design intends.

This also exposes an honest limitation of the current implementation: the coach loop operates as designed — it observes losses and moves scores — but only one trait (Alpha Entry Patience at 7) has a rule cascade specified in §3.2. Alpha's 3→4 and all of Beta's Impulsivity increments were logged and would be visible to the agent through ICLE (§4), but changed no mechanical rule during the backtest. Until every trait has a defined cascade, the coach's effect on performance cannot be measured; specifying cascades for every trait is the first item of future work (§9.4).

### 7.5 Judge Performance

The Judge rejected 25 of 105 Baker-Beta signals and 32 of 37 Aschenbrenner-Beta signals. Every rejection was a hard block — the IPO ban on SPCX (25 signals per Beta profile across SPCX's 26 trading days), the NVDA restricted list (Aschenbrenner, 7), or the five-position cap (Baker, 8). No entry that passed the hard blocks was rejected on score. Alpha's 23 signals were all approved and filled. The IPO ban was decisive for SPCX: with the ban disabled, Aschenbrenner Beta buys SPCX on its listing day, is stopped out twice (−$67.61, −$60.05), and finishes the window at −10.8% instead of −5.7%; Baker Beta gains marginally (+15.2% vs +14.7%) because it had free cash on only a few of SPCX's signal days.

### 7.6 Sensitivity

| Variant | Alpha | Beta (Baker) | Beta (Aschenbrenner) | Alpha + Baker |
|---|---|---|---|---|
| **Base** (re-entry eligible next session, IPO ban on) | +2.55% | +14.71% | −5.67% | **+8.63%** |
| Re-entry blocked for one further session | +2.47% | −8.46% | −6.51% | −2.99% |
| Re-entry blocked for five further sessions | +0.56% | −7.16% | −4.59% | −3.30% |
| IPO ban off | +2.55% | +15.22% | −10.78% | +8.89% |
| Same-bar re-entry (v1 artifact) | +3.70% | +19.15% | −4.16% | +11.42% |

The re-entry rows are the finding of this section. Baker Beta was stopped out of MU at the March 30 close ($321.75). Under the base rule it re-entered at the March 31 close ($337.79) and that position was marked at $970.82 on July 21 — +$506 unrealized, more than half of Beta's total gain. If re-entry is deferred by one more session, the next qualifying MU entry is June 10 at $891.74 and Beta's return goes from +14.7% to −8.5%. The v1 same-bar artifact — re-buying at the identical $321.75 close, which the live system cannot execute — is the mechanism behind the retracted +15.3% headline. **Beta's reported return is therefore not a property of the personality vector; it is a property of a single ticker's timing within a one-session window.** The behavioral findings in §7.3 — cadence, drawdown, differentiation — are the same in every row.

---

## 8. Live Deployment (August 2026)

### 8.1 Production Go-Live

Following backtest validation, the Trading Arena went live with **$5,000 real capital** on Robinhood on August 6, 2026. All four agents (Alpha, Beta, Judge, Rocky) operate autonomously via scheduled cron jobs — no human intervention except emergency circuit breakers.

| Component | Schedule | Purpose |
|-----------|----------|---------|
| Agent Alpha | Daily 7:00 AM MST | Scan market, build thesis, invoke Judge, execute if approved |
| Agent Beta | Daily 7:05 AM MST | Scan market, build thesis, invoke Judge, execute if approved |
| Judge Audit | Daily 2:10 PM MST | Post-trade verification (stop adherence, PAST drift) |
| Rocky Review | Bi-weekly Friday 5:00 PM MST | Performance analysis, PAST score tuning (±1 trust region) |

**Key architecture decision: Pre-trade Judge gate.** The Judge evaluates every trade thesis **before** execution via a subprocess call (`claude -p`). Only APPROVED theses reach the real account. This eliminates the original design flaw where post-trade-only rejection forced same-day exits, creating unnecessary costs and tax noise.

### 8.2 Live Trading Record (Aug 6 - Aug 24, 2026)

The system opened **6 real positions** (1 Alpha, 5 Beta) and closed 4 of them in the first 13 trading days of operation:

| Date | Agent | Ticker | Entry | Stop | Size | Status | Thesis |
|------|-------|--------|-------|------|------|--------|--------|
| Aug 6 | Beta | ALAB | $313.09 | -10% ($281.78) | 1 sh | **STOPPED Aug 19 @ $281.72 (-10.0%)** | Connectivity bottleneck (PCIe Gen 6, Scorpio-X) |
| Aug 7 | Beta | CIEN | $413.96 | -10% ($372.56) | 1 sh | **STOPPED Aug 24 @ $372.89 (-9.9%)** | Optical networking (AI data bottleneck) |
| Aug 10 | Alpha | CVS | $95.70 | -3% ($92.83) | 3 sh | SOLD (Aug 14 time-exit, -$3.15) | Mean reversion (RSI 33, rising 50d MA) |
| Aug 10 | Beta | VST | $142.50 | -10% ($128.25) | 3 sh | HOLDING (-4.2%) | Energy infrastructure (Helix JV, Meta nuclear PPAs) |
| Aug 14 | Beta | CRWV | $105.48 | -10% ($94.93) | 5 sh | **STOPPED Aug 19 @ $94.16 (-10.7%)** | Neocloud / Data Center (Q2 rev +112%, $104B backlog) |
| Aug 17 | Beta | CCJ | $99.00 | -10% ($89.10) | 3 sh | HOLDING (+3.4%) | Uranium fuel for AI nuclear power |

**Account P&L (as of Aug 24 close):** -$140.17 (-2.80%). Cash: $4,143.31. Two positions held (VST, CCJ).

**Realized P&L (closed trades):**
- CVS (Alpha): -$3.15 (time exit, day 5)
- ALAB (Beta): -$31.37 (-10.02%, broker-side stop)
- CRWV (Beta): -$56.60 (-10.73%, broker-side stop)
- CIEN (Beta): -$41.07 (-9.93%, broker-side stop)
- **Total realized: -$132.19**

**Unrealized P&L (open positions):**
- VST: -$18.09 (-4.2%)
- CCJ: +$10.11 (+3.4%)
- **Total unrealized: -$7.98**

**Behavioral observations:**

1. **Agent separation working.** Alpha (Renaissance, mean reversion, RSI-driven) executed 1 trade in 3 weeks — correctly patient, waiting for qualifying setups. Beta (Baker, architecture-first AI) executed 5 trades, all thesis-driven AI infrastructure names. Zero convergence (both agents in same ticker).

2. **Judge gate effectiveness.** 100% pre-trade approval rate. All 6 entries met the 13-point checklist before execution. No post-trade rejections requiring forced exits.

3. **PAST drift check.** Alpha's CVS trade (Entry Patience 3/7, Hold Duration 3/7) matched profile: took the first setup that met all entry criteria after 15 sessions without one, exited after 4 days on the mechanical time exit. Beta's 5 trades (Entry Patience 6/7, Hold Duration 7/7) all entered on thesis, none exited voluntarily — stops only. Drift = 0.

4. **Stop discipline under stress.** The Aug 18-24 week stress-tested the stop system: CRWV and ALAB stops triggered Aug 19 (broker-side, automatic), CIEN's stop triggered Aug 24 at the open. Three stops, zero violations, zero manual intervention. Critically, on Aug 18 the CRWV stop was violated by 2.4% because no agent session ran (Z.AI API timeout) — the stop existed only in the agent's state file. This exposed the structural weakness of agent-side stops and motivated the move to broker-side GTC orders (see 8.3).

5. **Market regime stress test.** Aug 5-14 saw a 35-47% AI infrastructure selloff, followed by a relief bounce (Aug 11-17, SMH +14%) that itself reversed Aug 18-24. Beta's entries came during the drawdown per Baker's "buy architecture bottlenecks when oversold" thesis (Entry Patience 6/7); the subsequent reversal stopped out 3 of 5 positions at the mechanical 10% line. Alpha stayed out entirely (RSI > 35 on most names during the bounce phase). Both behaviors match their profiles.

### 8.3 Operational Learnings

**PAST persistence compliance gap (fixed v0.3.0).** Agent Alpha failed to persist its full PAST index in state files for 3 consecutive Rocky reviews (Jul 25, Aug 1, Aug 8), preventing drift detection. Rocky flagged this as a compliance escalation with a hard Aug 15 deadline. The root cause: Alpha's cron prompt lacked an execution step for writing the PAST index — the coach's directive had no path to enforcement. **Fix:** Added `STEP 9 — PAST INDEX PERSISTENCE` to Alpha's cron prompt and updated the skill documentation. Lesson: A coaching framework that depends on persisted data is only as good as the persistence step in the execution loop.

**Patience trait split (v0.3.0).** The single "Patience" score conflated two independent behaviors: patience to *enter* (waiting for qualifying setups) and patience to *hold* (resisting mechanical exits when thesis intact). Split into **Entry Patience** (confluence requirements before entry) and **Hold Duration** (time-based vs thesis-based exits). This enabled Rocky to detect drift on each dimension independently — e.g., if Alpha starts entering on weaker setups (Entry Patience drift) without changing hold behavior, the split catches it where a single score would have masked it.

**Model architecture clarification (v0.3.1-v0.3.3).** Documentation updates established the two-layer architecture: GLM-5.2 (Z.AI cloud) is the **execution layer** for all agents (cron sessions, tooling, MCP, order placement), while Deepseek R1 70B (local Ollama) is Beta's **reasoning brain** (architecture-first thesis analysis). Alpha uses GLM-5.2 for both execution and reasoning (statistical only, no deep model needed). This architecture demonstrates that PAST works across heterogeneous model configurations (cloud + local, statistical + deliberative).

**Broker-side stop-loss requirement (v0.4.0).** The original design placed stop-losses in agent state files — an agent session had to run, read prices, and manually place the sell order. On Aug 18, no agent session ran (Z.AI API timeout) and CRWV bled 2.4% past its $94.93 hard stop with no execution. The fix: GTC stop-market orders placed directly on Robinhood, executing at the broker level with zero dependency on agent availability. Verified Aug 19: ALAB sold at $281.72 (-10.0%) and CRWV at $94.16 (-10.7%) — both automatically, no agent present. CRWV subsequently fell to $88.92 (-15.6%), confirming the stop saved ~$26 of additional downside. **Lesson: risk controls for unattended autonomous systems must live at the broker, not the agent.** The 10% rule is correct; its execution mechanism was wrong.

**API stale-call detector misconfiguration (v0.4.0).** GLM-5.2 cron sessions failed 4 of 5 trading days (Aug 12, 13, 17, 18) with a 90-second stale-call timeout. Root cause: GLM-5.2 cold-start latency on first API call of a fresh session is 90-120 seconds — exactly at the detector's default threshold. The detector killed sessions before Z.AI ever responded. Fix: raised stale timeout to 300s and added a 6:45 AM pre-warm call. After the fix: zero timeouts across 3 consecutive trading days. **Lesson: multi-agent systems using cloud LLM APIs must account for cold-start latency in timeout configuration.** Defaults tuned for interactive sessions are too aggressive for batch/cron workloads.

**Regime detection gap (v0.4.0).** Beta entered 5 positions during the Aug 6-17 window that included a relief bounce; the AI infrastructure sector then rolled over Aug 18-24 and stopped out 3 positions. The agents had technical signals (RSI, 13F filings, pullback depth) but no sector momentum or sentiment layer to detect that the entire sector was in a downtrend. Fix: a 6:30 AM pre-trade signal scan (sector momentum, market breadth, sentiment) outputs a GO/NO-GO signal before agents decide to trade. **Lesson: personality-driven agents generate theses but do not inherently detect market regime.** A regime layer — separate from agent personalities — is needed to prevent counter-trend entries during sector-wide drawdowns.

**First live PAST adjustments (Rocky review, August 29).** After the paper's August 24 cutoff, Rocky's bi-weekly review made the first two score changes of the live deployment, both within the ±1 trust region. **Alpha Entry Patience 3→4:** twelve consecutive no-trade sessions, each backed by a progressively wider scan (39→42 tickers, options-viability analysis, macro impact review), were judged to be disciplined waiting rather than paralysis, and the trait was raised to reflect it. **Beta Technical Focus 3→2:** after a second 13F misstatement in one cycle (AVGO cited as a core Atreides holding; the filing showed the position had been reduced), Rocky lowered Beta's Technical Focus, reasoning that unreliable 13F verification was "a Technical focus deficiency." We report this adjustment as made, but we do not endorse its direction. In Beta's skill file, Technical Focus governs the weight placed on RSI confirmation relative to the fundamental thesis (3/7: "RSI as secondary confirmation"; the +1 cascade: "may use RSI as primary entry signal"). A failure of *fundamental* research therefore argues for raising the trait — leaning more on the statistical check that did not fail — not lowering it, which shifts weight toward the process that just failed twice. The LLM coach conflated "technical" in the sense of research diligence with the trait's defined sense of technical-analysis weighting. This is the first observed instance of a coach adjustment whose direction contradicts the trait's own cascade definition, and it is a finding rather than an embarrassment: the framework's trust region limited the damage to one Likert step, the adjustment is fully logged and reversible, and the episode shows that trait names must be defined tightly enough that the coach cannot mis-map a failure mode onto them. Both August 29 changes are recorded in Rocky's review notes with their triggers, and the Judge audits subsequent trades against the updated vectors. The live `state/` directory — agent state files, Rocky notes, Judge decision log — contains real brokerage account data and is not part of the public repository; the live-deployment figures in this section are therefore self-reported by the author and, unlike the backtest in §7, cannot be independently regenerated from the repository.

---

## 9. Discussion

### 9.1 Strengths

**Behavioral diversity is emergent and measurable.** The same stock produces different behavior from different agents — not because the prompts differ, but because the personality vectors cascade into different trading rules. This is the core contribution: personality as a tunable parameter.

**The coaching loop operates without retraining.** In the backtest, Rocky raised Beta's Impulsivity one notch in each of the four review periods that contained a stop-loss exit ($P_3: 3 \to 7$ over four months) and raised Alpha's Entry Patience after a fortnight of three straight losses ($P_4: 3 \to 4$), each move inside the ±1 trust region and each logged with its trigger. In production the same loop split the Patience trait (§8.3) and, on August 29, raised Alpha's Entry Patience 3→4 after twelve consecutive well-documented no-trade sessions. (The same review also lowered Beta's Technical Focus 3→2 in response to a research-quality failure — an adjustment we report but argue in §8.3 pointed the wrong way, and which the ±1 trust region contained.) The adjustments are integers in a file, not weights in a model. No GPU. No backpropagation. No checkpoint rollback. Whether a given adjustment *helps* is a separate question the backtest cannot yet answer — see §7.4 and §9.2.

**File-based memory provides full auditability.** Every trade, every Judge verdict, every PAST adjustment is logged in markdown. The trust region ($|\Delta P| \leq 1$) ensures changes are gradual and reviewable. This is critical for a system handling real capital.

**ICLE produces self-correction.** Alpha's state file documents 18 strategy learnings accumulated over 6.5 months, including the observation that "the RSI<35 threshold may be too conservative for names with strong intact uptrends." This is the agent learning from its own execution history — $\Psi(H_t, K)$ in action.

### 9.2 Limitations

**No evidence of outperformance.** The portfolio-level backtest returned +8.6% combined over 6.5 months, but §7.6 shows the sign of that result depends on whether one ticker is re-entered one session earlier or later. 32 closed trades across 6 tickers is far too few for statistical significance in either direction, and Beta's gain is a single unrealized position. The paper's empirical claim is therefore limited to *behavioral differentiation and coach-loop mechanics*, not returns.

**Incomplete rule cascades.** Only Alpha's Patience trait has a fully specified mapping from score to rule (§3.2). Rocky's other adjustments during the backtest were recorded but mechanically inert. Until every trait has a defined cascade, the coach loop's effect on performance cannot be measured.

**Backtest simplifications.** Fills at daily close with no commission or slippage; stops are evaluated against the daily close only, so a stop can fill well past its nominal level (Baker Beta's first OKLO exit was −12.3% against a 10% stop) — the live system's broker-side stop orders would typically fill closer to the level; holding periods counted in trading sessions; a deterministic Judge that scores 6 of 13 checklist items; rule-based Rocky rather than the LLM coach used in production. Results are highly sensitive to the stop re-entry rule (§7.6).

**Live drawdown regime.** The live account was down −2.8% at the August 24 cutoff, with 3 of 5 Beta positions stopped out. This is consistent with the backtest, where Beta's thesis-driven entries produced a −30.7% drawdown: the Baker profile buys pullbacks, and in a sustained downtrend that means buying repeatedly into stops. The regime detection layer (added v0.4.0) addresses the entry-timing side; the jury remains out on whether the underlying theses recover before the remaining stops trigger.

**Self-evaluation in simulation mode.** Without Claude Code OAuth, the Judge ran as self-evaluation (same LLM evaluating its own theses). Production uses a separate model (Fable 5).

**Regime dependence.** Beta's strategy has no time exit and no profit-taking rule; its only exit is a 10% stop. Every closed Beta trade in the backtest was therefore a loss, and all of Beta's gains were open positions at the cutoff. The strategy's return is entirely a function of whether the thesis names trend upward for long enough after entry — a regime bet, not a personality effect.

### 9.3 Comparison with Existing Frameworks

| Dimension | PAST (Ours) | TradingAgents | AI Hedge Fund | AI-Trader |
|-----------|-------------|---------------|----------------|-----------|
| **Agents** | 4 (competitive) | 7 (collaborative) | 18 (collaborative) | Configurable |
| **Key innovation** | Weight-free personality tuning | Structured debate | Investor personas | Agent-native exec |
| **Adaptation** | Bi-weekly PAST tuning ($\Delta P$) | None | None | Unknown |
| **ICLE** | Yes (file-based log exploitation) | No | No | Unknown |
| **Model diversity** | 3 models (GLM, Deepseek, Claude) | 1 model | 13 providers | Any |
| **Independent Judge** | Yes (separate LLM) | Risk Manager (same LLM) | Portfolio Manager | Unknown |
| **Local fallback** | Deepseek R1 70B (Ollama) | None | None | None |
| **Real trading** | Yes (Robinhood, $5K) | Backtest only | Simulation only | Yes (Robinhood) |
| **Backtest return** | +8.6% (6.5 months, portfolio-level; not robust — see §7.6) | +24.9% annualized | Not published | Not published |

**PAST's unique contribution:** No other framework tunes agent personality based on observed performance. TradingAgents and AI Hedge Fund use static roles/personas. PAST makes personality a dynamic, coach-tuned parameter with a trust region for stability, supplemented by ICLE for micro-level self-correction.

### 9.4 Future Work

1. **Extended backtesting** — 12+ months across 50+ tickers and multiple market regimes
2. **Live deployment results** — compare simulated vs. live P&L after August 2026 go-live
3. **Additional personalities** — test Druckenmiller (macro-adaptive), Tepper (distressed contrarian), Tudor Jones (trend-following) as alternative personality vectors
4. **PAST drift analysis** — measure how personality vectors evolve over 6+ months and correlate with performance
5. **Regime detection** — add a regime classifier that Rocky uses to adjust $P$ proactively
6. **Generalization** — Apply PAST to non-trading domains. The PAST framework is domain-agnostic: any multi-agent system where behavioral diversity and adaptation are valuable can benefit. Potential applications include:
   - **AI tutors for children** — personality tuning for teaching style adaptation (visual vs. reading, patient vs. direct, structured vs. exploratory). A coach agent observes learning outcomes and adjusts the tutor's Likert scores (Patience, Assertiveness, Empathy) bi-weekly, exactly as Rocky adjusts trading agent scores.
   - **Software engineering agents** — tuning code review strictness, refactoring aggressiveness, or documentation thoroughness based on project KPIs (bug rate, deployment speed, code quality).
   - **Customer support** — adjusting agent empathy, technical depth, and escalation thresholds based on satisfaction scores and resolution rates.
   - **Content moderation** — tuning strictness, context sensitivity, and appeal handling based on false positive/negative rates.

---

## 10. Conclusion

We presented **Personality-Adaptive Score Tuning (PAST)**, a novel, weight-free alignment framework for multi-agent LLM systems. By quantifying agent personas into discrete 1–7 Likert vectors, PAST cleanly decouples runtime behavioral steerability from parameter-level model training. The combination of a macro-level, bi-weekly **Coach review loop** (with trust region) and a micro-level **In-Context Log Exploitation (ICLE)** pipeline yields system performance that rivals parameter-tuned frameworks while introducing zero compute overhead at the training layer.

In a portfolio-level backtest across 6 tickers and 6.5 months, the combined book returned +8.6%, but we make no performance claim from it: the result rests on one unrealized position and reverses sign if that position is entered one session later. What the backtest establishes is measurable behavioral diversity: agents with different PAST vectors made different decisions on the same instrument, exactly as their profiles predicted, with a 10× difference in maximum drawdown between the two personalities that holds in every variant we ran. The coaching loop adjusted personality scores bi-weekly within its trust region in response to observed results. Whether those adjustments improve returns is not yet established, because only one trait currently has a fully specified rule cascade.

Live deployment with $5,000 real capital (August 2026) moved the framework beyond simulation and into its first genuine stress test. In the first three weeks, the system opened 6 positions across 2 agents, weathered a sector-wide AI infrastructure drawdown, and enforced its risk controls without human intervention: three positions stopped out at the mechanical 10% line (broker-side, automatic), one exited on a time rule, and zero PAST drift was detected across all agents. The period also surfaced three production lessons now folded back into the framework — broker-side risk enforcement, API cold-start-aware timeout configuration, and a regime detection layer — each discovered by live operation, not simulation. The account's negative P&L over the window (-2.8%) is itself informative: the personality-consistent behavior (buying thesis names during drawdown, holding to stops) is precisely what the PAST vectors specified, and the drawdown regime — not personality drift — explains the losses.

The key insight: **agents learn from their PAST.** Not by updating weights, but by adjusting the quantified personality that drives their rules, and by exploiting their own execution history at the inference boundary. This is contextual reinforcement learning at the instruction level — lightweight, interpretable, auditable, and achievable on consumer hardware without GPU training.

PAST offers engineers total system explainability, immediate behavioral reversibility, and absolute immunity against catastrophic forgetting. This work confirms that structuring and tuning personality metrics at the inference boundary is a highly viable, energy-efficient alternative to gradient-descent alignment strategies for agentic AI.

---

## References

1. Xiao, Y., Sun, E., Luo, D., Wang, W. (2024). "TradingAgents: Multi-Agents LLM Financial Trading Framework." arXiv:2412.20138.
2. Singh, V. (2025). "AI Hedge Fund." GitHub: virattt/ai-hedge-fund.
3. Fan, T. et al. (2026). "AI-Trader: 100% Fully-Automated Agent-Native Trading." GitHub: HKUDS/AI-Trader.
4. Schulman, J. et al. (2017). "Proximal Policy Optimization Algorithms." arXiv:1707.06347. (Trust region inspiration)
5. Rafailov, R. et al. (2023). "Direct Preference Optimization." arXiv:2305.18290.
6. Hartley, J., Hamill, C., Batra, D., Seddon, D., Okhrati, R., Khraishi, R. (2025). "How Personality Traits Shape LLM Risk-Taking Behavior." *Findings of ACL 2025*, pp. 21068–21092.
7. Wang, Y., Li, X., Chen, G. (2025). "Risk Profiling and Modulation for LLMs." arXiv:2509.23058.
8. GLM-5 Team, Zeng, A. et al. (2026). "GLM-5: from Vibe Coding to Agentic Engineering." arXiv:2602.15763.
9. Torres-Leguet, J. (2025). "The Little Book of Reinforcement Learning."
10. Grable, J. & Lytton, R. (2003). "Financial Risk Tolerance Revisited." (Likert scale inspiration)
11. Microsoft (2024). "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation."
12. CrewAI (2024). "CrewAI: Framework for Orchestrating Role-Playing Autonomous AI Agents."
13. LangGraph (2024). "LangGraph: Building Stateful Multi-Actor Applications with LLMs."

---

*This research is for educational purposes. Past performance does not indicate future results. The Trading Arena uses real capital and accepts the risks of AI-driven trading.*

*Code and backtest harness available at [GitHub repository](https://github.com/sloth1122/past-framework).*

---

## Appendix A: Real-Time Personality Swap — Aschenbrenner → Baker

On July 30, 2026 — one day after this paper was written — Leopold Aschenbrenner's hedge fund (Situational Awareness LP, $45B at peak) was liquidated by margin call. His 4x-leveraged, 76%-concentrated portfolio of AI infrastructure stocks (BE, SNDK, CRWV, IREN, CORZ) declined 35-55% in July, triggering forced liquidation by Goldman Sachs, JPMorgan, and Bank of America. The entire public book was sold to Citadel in a single block trade.

The July 29 draft of this paper had flagged the concentration risk in its limitations section: "Beta's return was dominated by a single MU trade. In a different market regime, Beta's low win rate with 10% stops could produce consecutive losses without a compensating win." (The return figures that sentence referred to have since been retracted — §6.5 — but the qualitative warning stands, and the v3 backtest bears it out: every closed Beta trade was a stop-loss.)

On the same day as the liquidation, Agent Beta's personality vector was swapped from Aschenbrenner to Gavin Baker (Atreides Management, $8.9B AUM, Sharpe 2.46):

| Trait | Aschenbrenner | Baker | $\Delta P$ |
|---|---|---|---|
| Risk Tolerance | 6/7 | 5/7 | -1 |
| Conviction | 7/7 | 6/7 | -1 |
| Impulsivity | 5/7 | 3/7 | -2 |
| Patience | 7/7 | 6/7 | -1 |
| Concentration | 6/7 | 4/7 | -2 |
| Adaptability | 5/7 | 6/7 | +1 |

The swap was motivated by Baker's survival of the same July 2026 crash that destroyed Aschenbrenner: Baker's diversified, no-leverage, architecture-first approach produced a -3.5% drawdown vs Aschenbrenner's total wipeout.

**This is the PAST framework operating in real time.** The risk was identified, alternative personalities were researched, and the personality vector was updated — all without touching model weights. The agent's behavior changed because 6 integers changed.

**What the backtest says about the swap.** Run on identical data (§7.1), the Baker profile finished the January–July window at +14.7% versus Aschenbrenner's −5.7% — but §7.6 shows Baker's figure depends on a single MU re-entry and becomes −8.5% if that entry is one session later, while its drawdown (−30.7%) was far deeper than Aschenbrenner's (−9.4%), which sat mostly in cash because the Judge blocked its SPCX and NVDA signals. The swap was not made for backtest return; it was made because Aschenbrenner's leverage and concentration profile had just been demonstrated to be ruinous in live markets, and the Likert vector that encodes those traits (Risk 6, Conviction 7, Concentration 6) was the closest analogue in the arena. This is exactly the kind of judgment the coach layer is meant to exercise and exactly the kind that a return-only metric would have gotten wrong.

A detailed case study is available in `docs/CASE_STUDY_Aschenbrenner_to_Baker.md`.
