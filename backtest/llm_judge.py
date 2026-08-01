#!/usr/bin/env python3
"""
LLM-in-the-loop Judge — calls local Ollama (deepseek-r1:70b) for real reasoning.
Replaces the hardcoded stub judge_evaluate from backtest_sim.py.

Brian's fix #2: "Build the LLM call into the test to simulate how the LLM
would have reacted (accepted/rejected the trade)."
"""
import json, subprocess, sys, os, time
from pathlib import Path

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-r1:32b")
ROCKY_MODEL = os.getenv("ROCKY_MODEL", "deepseek-r1:32b")

# Track token usage for cost reporting
_token_log = []

def _call_ollama(model: str, prompt: str, timeout: int = 120) -> dict:
    """Call local Ollama, return {response, tokens, elapsed}."""
    t0 = time.time()
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.3, "num_ctx": 8192}})
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{OLLAMA_URL}/api/generate",
             "-d", payload],
            capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            return {"response": "", "error": f"curl failed: {result.stderr}", "elapsed": elapsed}
        data = json.loads(result.stdout)
        resp = data.get("response", "").strip()
        # Deepseek R1 wraps reasoning in <think>...</think> — strip it
        if "</think>" in resp:
            resp = resp.split("</think>")[-1].strip()
        usage = {
            "prompt_eval_count": data.get("prompt_eval_count", 0),
            "eval_count": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        }
        _token_log.append({"model": model, "role": "judge_or_rocky", **usage, "elapsed": elapsed})
        return {"response": resp, "usage": usage, "elapsed": elapsed}
    except subprocess.TimeoutExpired:
        return {"response": "", "error": "timeout", "elapsed": timeout}
    except Exception as e:
        return {"response": "", "error": str(e), "elapsed": time.time() - t0}


# ════════════════════════════════════════════════════════════
# JUDGE — 13-point checklist via LLM
# ════════════════════════════════════════════════════════════
JUDGE_SYSTEM = """You are the Independent Judge of a multi-agent trading arena.
You are a different model family from the agents (you are {model}).
You MUST verify every trade using a 13-point checklist. You pull your own data
from the context provided — never trust the agent's claims.

Respond ONLY with valid JSON. No markdown, no explanation outside JSON.
Schema:
{{
  "score": <int 0-13>,
  "approved": <true|false>,
  "checks_passed": [<int>],
  "checks_failed": [<int>],
  "reasoning": "<one sentence summary>",
  "integrity_flag": <true|false>
}}
Require score >= 10 to approve.
"""

JUDGE_PROMPT_TEMPLATE = """AGENT: {agent_name}
TICKER: {ticker}
ENTRY PRICE: ${entry_price:.2f}
DATE: {date}

CURRENT MARKET CONTEXT (rolling window — 52 weeks prior to today):
- RSI(14): {rsi:.1f}
- 50-day MA: ${ma50:.2f} (5-day slope: {ma50_slope:+.2f})
- 52-week high: ${high52:.2f}  |  52-week low: ${low52:.2f}
- Distance from 52wk low: {pct_from_low:+.1f}%
- Volume today: {volume:,.0f}

TRADE THESIS:
- Agent strategy: {strategy}
- Position size: {size_pct:.0f}% of allocation
- Stop-loss: {stop_pct:.0f}%
- Target holding period: {holding}
- PAST personality scores: {past_scores}

THE 13-POINT CHECKLIST:
1. Position size within allocation limit
2. Stop-loss defined and reasonable
3. No earnings within 10 trading days
4. Risk/reward ratio >= 2:1
5. Sufficient liquidity (avg volume > 1M)
6. Not in banned sectors (SPCX off-limits for all agents)
7. PAST score alignment (personality fits the trade type)
8. Thesis supported by current data (verify the numbers above)
9. Entry criteria met (Alpha: RSI<35 + rising MA | Beta: near 52wk low + thesis intact)
10. Catalyst identified (Beta requires this; Alpha statistical only)
11. Convergence check (note if other agent would also enter — not disqualifying)
12. State file honesty (no phantom positions)
13. Daily trade limit not exceeded

Evaluate each of the 13 points. Respond with JSON only."""

def judge_evaluate_llm(agent_name, ticker, entry_price, row, past_scores,
                       position_size_pct, stop_pct, holding, strategy, call_log):
    """Run real LLM Judge. Returns (approved, score, notes, usage)."""
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        agent_name=agent_name, ticker=ticker, entry_price=entry_price,
        date=str(row.name.date()) if hasattr(row.name, 'date') else str(row.name),
        rsi=row.get('RSI', 50), ma50=row.get('MA50', entry_price),
        ma50_slope=row.get('MA50', 0) - row.get('MA50_prev', 0),
        high52=row.get('High52', entry_price), low52=row.get('Low52', entry_price),
        pct_from_low=(entry_price - row.get('Low52', entry_price)) / max(row.get('Low52', 1), 1) * 100,
        volume=row.get('Volume', 0),
        strategy=strategy, size_pct=position_size_pct, stop_pct=stop_pct,
        holding=holding, past_scores=past_scores
    )
    sys_prompt = JUDGE_SYSTEM.format(model=JUDGE_MODEL)
    result = _call_ollama(JUDGE_MODEL, sys_prompt + "\n\n" + prompt)

    call_log.append({
        "role": "judge", "agent": agent_name, "ticker": ticker,
        "date": str(row.name.date()) if hasattr(row.name, 'date') else str(row.name),
        "elapsed_s": round(result.get("elapsed", 0), 1),
        "tokens": result.get("usage", {}).get("total_tokens", 0),
        "error": result.get("error")
    })

    if result.get("error"):
        # On LLM failure, REJECT (fail safe — never auto-approve)
        return False, 0, [f"LLM error: {result['error']}"], result.get("usage", {})

    # Parse JSON response
    resp = result["response"]
    # Strip any markdown fences
    resp = resp.strip().strip("`")
    if resp.startswith("json"):
        resp = resp[4:]
    try:
        verdict = json.loads(resp)
        approved = verdict.get("approved", False)
        score = verdict.get("score", 0)
        passed = verdict.get("checks_passed", [])
        failed = verdict.get("checks_failed", [])
        notes = []
        for c in passed:
            notes.append(f"✓ Check {c}")
        for c in failed:
            notes.append(f"✗ Check {c}")
        notes.append(f"Judge: {verdict.get('reasoning', '')}")
        if verdict.get("integrity_flag"):
            notes.append("⚠ INTEGRITY FLAG")
        return approved, score, notes, result.get("usage", {})
    except json.JSONDecodeError:
        # If JSON parse fails, fail safe
        return False, 0, [f"Judge parse error: {resp[:200]}"], result.get("usage", {})


# ════════════════════════════════════════════════════════════
# ROCKY — PAST tuning via LLM
# ════════════════════════════════════════════════════════════
ROCKY_PROMPT_TEMPLATE = """You are Rocky, the Coach of a trading arena with two competing AI agents.
You observe their trades bi-weekly and tune their PAST (Personality-Adaptive Score Tuning) scores.
You may adjust at most 2 traits by ±1 each (trust region). Changing a score cascades into trading rules.

AGENT: {agent_name} ({strategy})
WEEK NUMBER: {week_num}
CURRENT PAST SCORES: {past_scores}

TRADES THIS PERIOD:
{trade_summaries}

PERFORMANCE THIS PERIOD:
- Trades completed: {num_trades}
- Win rate: {win_rate:.0%}
- Total P&L: ${pnl:+.2f}

ROCKY'S COACHING NOTES (your observations):
Write 2-3 sentences of coaching. Then decide on adjustments.

Respond ONLY with JSON:
{{
  "rocky_note": "<2-3 sentence coaching observation>",
  "adjustments": {{"trait_name": <new_score>}},
  "cascade_after": "<how the new scores change trading rules>"
}}

Traits: risk_tolerance, impulsivity, conviction, patience, adaptability,
technical_focus, sector_specialization, position_concentration
All on Likert 1-7 scale. Max ±1 change per trait per cycle."""

def rocky_tune_llm(agent_name, trades, past_scores, week_num, strategy, call_log):
    """Run real LLM Rocky. Returns (new_past, adjustment_info, usage)."""
    # Build trade summaries
    summaries = []
    for t in trades[-5:]:  # last 5 trades
        summaries.append(
            f"  {t.get('ticker','?')} entry ${t.get('entry_price',0):.2f} → "
            f"exit ${t.get('exit_price',0):.2f} ({t.get('pnl_pct',0)*100:+.1f}%) "
            f"[{t.get('exit_reason','?')}]"
        )
    trade_str = "\n".join(summaries) if summaries else "  No trades this period."

    completed = [t for t in trades if t.get('status') == 'CLOSED']
    wins = [t for t in completed if t.get('pnl', 0) > 0]
    win_rate = len(wins) / len(completed) if completed else 0
    pnl = sum(t.get('pnl', 0) for t in completed)

    prompt = ROCKY_PROMPT_TEMPLATE.format(
        agent_name=agent_name, strategy=strategy, week_num=week_num,
        past_scores=past_scores, trade_summaries=trade_str,
        num_trades=len(completed), win_rate=win_rate, pnl=pnl
    )

    result = _call_ollama(ROCKY_MODEL, prompt, timeout=120)

    call_log.append({
        "role": "rocky", "agent": agent_name, "week": week_num,
        "elapsed_s": round(result.get("elapsed", 0), 1),
        "tokens": result.get("usage", {}).get("total_tokens", 0),
        "error": result.get("error")
    })

    if result.get("error"):
        return past_scores, {"note": f"Rocky LLM error: {result['error']}", "adjustments": {}}, result.get("usage", {})

    resp = result["response"].strip().strip("`")
    if resp.startswith("json"):
        resp = resp[4:]
    try:
        out = json.loads(resp)
        adjustments = out.get("adjustments", {})
        # Enforce trust region: max ±1 per trait
        new_past = past_scores.copy()
        actual_adj = {}
        for trait, new_val in adjustments.items():
            if trait in past_scores:
                old_val = past_scores[trait]
                clamped = max(old_val - 1, min(old_val + 1, int(new_val)))
                if clamped != old_val:
                    new_past[trait] = clamped
                    actual_adj[trait] = {"old": old_val, "new": clamped}
        info = {
            "note": out.get("rocky_note", ""),
            "adjustments": actual_adj,
            "cascade": out.get("cascade_after", "")
        }
        return new_past, info, result.get("usage", {})
    except json.JSONDecodeError:
        return past_scores, {"note": f"Rocky parse error", "adjustments": {}}, result.get("usage", {})


def get_token_log():
    return _token_log

def reset_token_log():
    global _token_log
    _token_log = []
