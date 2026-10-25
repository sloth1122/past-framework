#!/usr/bin/env python3
"""Risk-tiered pre-trade Judge runner (Arena v5.2, Oct 24 2026 — John's decision).

There is ONE Judge (skill `trade-judge`, one rulebook). The trade's risk tier decides
how many independent runs of that Judge are required and which model runs them:

  HIGH-RISK  every option trade (single calls/puts, spreads, any legs, long or short);
             crypto or leveraged trades; a stock trade whose notional exceeds John's
             threshold (state/judge_config.json "high_risk_notional_usd"; null = none).
             → 3 parallel runs on Fable 5.1 (claude-fable-5-1, effort high); ALL must approve.
             Fable unavailable → 3 runs on Opus 5.5 (effort high), logged "failover".
             Shadow test: on `shadow_rate` (10%) of high-risk trades, one extra NON-VOTING
             Opus 5.5 run; both verdicts are logged for the Fable-vs-Opus agreement rate.
  ROUTINE    every other stock trade → 1 run on Opus 5.5 (claude-opus-5-5, effort high).

Vote protocol (all tiers): each run must end with exactly one JSON vote
    {"run_id": "<id>", "vote": "approve|reject", "reason": "..."}
Votes are tallied by unique run_id — identical duplicate lines from one run are ignored,
raw lines are never counted. A missing, malformed, wrong-run_id or conflicting vote, or a
timeout, makes that run invalid: it is re-run once; still invalid → the trade is REJECTED.
APPROVED only if valid_votes == runs_required AND every valid vote is approve.
The Judge is never bypassed: any failure path ends in REJECTED.

Logs (state/judge_votes/): votes.jsonl (every attempt), trades.jsonl (every verdict,
incl. splits on 3-run trades), shadow.jsonl, and raw run output <run_id>_a<attempt>.md.

Usage:
  judge_vote.py --ticker AMD  --instrument option
  judge_vote.py --ticker MSFT --instrument stock --notional 2400
  judge_vote.py --report        # split rate + Fable/Opus agreement (milestones at 50)
Exit 0 = APPROVED, 2 = REJECTED. A JUDGE VERDICT block is printed and appended to the queue.
"""
import argparse, concurrent.futures as cf, json, random, re, subprocess, sys
from datetime import datetime
from pathlib import Path

CLAUDE = "/Users/johntytko/.local/bin/claude"
FABLE = "claude-fable-5-1"
OPUS = "claude-opus-5-5"
ROUTINE_MODEL = OPUS          # John, Oct 24: routine tier = Opus 5.5 high, 1 run
HIGH_RUNS, ROUTINE_RUNS = 3, 1
MILESTONE = 50
# The Judge is read-only: remove every broker tool that can change the account under
# both Robinhood MCP registrations (claude.ai connector + local "robinhood-trading"
# server scoped to ~). Harness-enforced; holds even with --dangerously-skip-permissions.
BROKER_WRITE_TOOLS = ",".join(f"{srv}{t}" for srv in (
    "mcp__claude_ai_Robinhood_trading__", "mcp__robinhood-trading__") for t in (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "exercise_option", "cancel_option_exercise"))
QUEUE = "/Users/johntytko/trading-arena/state/thesis_queue.md"
VOTES_DIR = Path("/Users/johntytko/trading-arena/state/judge_votes")
CONFIG = Path("/Users/johntytko/trading-arena/state/judge_config.json")

PROMPT = """You are the Trade Judge (load skill trade-judge, including its ARENA v5 block). Evaluate ONLY the PENDING thesis for {ticker} in the queue at {queue}; ignore other tickers. This is an independent run ({label}); do not look for or read any other run's vote.
Run the full checklist with your OWN data pulls (Robinhood connector, read-only): sizing (≤30% equity, dollar risk ≤3% equity, gap risk if earnings inside the hold), 2×ATR(14) stop recomputed, dated catalyst ≤30 trading days, the REQUIRED bear case (real news only — lawsuits, CEO exits, lost customers, guidance cuts, financing stress; reject theses whose bear case is generic "AI bubble" talk or missing), R/R ≥ 2.0, IPO ban, limited-margin limits (no borrowing/shorting/naked options). For OPTION theses also run the trade-judge options checklist (buy-only single leg or 2-leg debit vertical with ratio 1, direction vs thesis, max loss ≤ 3% equity, ≤ $1,500/month premium, expiry 7–60 days after the catalyst or the capitol_cluster exception, limit ≤ mid from your own chain pull, exit plan).
Do NOT edit the queue file and do NOT place, cancel or modify any order.
End your reply with EXACTLY ONE line of JSON and nothing after it:
{{"run_id": "{run_id}", "vote": "approve or reject", "reason": "<one sentence, no braces>"}}"""
PREFLIGHT = "Preflight availability check. Reply with exactly: OK"

JSON_RE = re.compile(r"\{[^{}]*\}")
OPTION_TERMS = re.compile(r"\b(calls?|puts?)\b[\s\S]*\b(strike|expir\w*|spread|debit|contracts?)\b", re.I)


def load_jsonl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def append_jsonl(p, rec):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def pending_block(queue_text, ticker):
    """Newest '## ' section of the queue whose header says PENDING and that names the ticker."""
    blocks = re.split(r"(?m)^## ", queue_text)
    hits = [b for b in blocks if b and "PENDING" in b.splitlines()[0].upper()
            and re.search(rf"\b{re.escape(ticker)}\b", b)]
    return hits[-1] if hits else ""


def classify(instrument, ticker, notional, leverage, cfg, queue_text):
    """Return (tier, reasons). Option terms in the PENDING thesis force HIGH even if the
    caller said 'stock' (defense in depth: the caller cannot under-tier an option trade)."""
    why = []
    if instrument in ("option", "crypto"):
        why.append(instrument)
    if leverage:
        why.append("leverage")
    thr = cfg.get("high_risk_notional_usd")
    if thr is not None and notional is not None and notional > float(thr):
        why.append(f"notional ${notional:,.0f} > threshold ${float(thr):,.0f}")
    if instrument == "stock" and OPTION_TERMS.search(pending_block(queue_text, ticker)):
        why.append("option terms found in the PENDING thesis")
    return ("high", why) if why else ("routine", ["stock trade below the size threshold"])


def build_cmd(model, prompt, judge_cmd, max_turns=25):
    if judge_cmd:                                   # testing hook
        return judge_cmd.split() + ["--model", model, prompt]
    return [CLAUDE, "-p", prompt, "--model", model, "--effort", "high", "--max-turns", str(max_turns),
            "--dangerously-skip-permissions", "--disallowedTools", BROKER_WRITE_TOOLS]


def call(model, prompt, judge_cmd, cwd, timeout, max_turns=25):
    try:
        r = subprocess.run(build_cmd(model, prompt, judge_cmd, max_turns), capture_output=True,
                           text=True, timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def model_available(model, judge_cmd, cwd):
    rc, out = call(model, PREFLIGHT, judge_cmd, cwd, timeout=90, max_turns=1)
    return rc == 0 and "OK" in out


def parse_vote(out, run_id):
    """(vote, reason, None) for a valid vote, else (None, None, why_invalid)."""
    if out == "TIMEOUT":
        return None, None, "timeout"
    objs = []
    for m in JSON_RE.finditer(out or ""):
        try:
            o = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(o, dict) and "run_id" in o and "vote" in o:
            objs.append(o)
    if not objs:
        return None, None, "missing or malformed JSON vote"
    if any(str(o["run_id"]) != run_id for o in objs):
        return None, None, "wrong run_id"
    votes = {str(o["vote"]).strip().lower() for o in objs}
    if not votes <= {"approve", "reject"}:
        return None, None, "vote must be approve or reject"
    if len(votes) > 1:
        return None, None, "conflicting votes from one run"
    return votes.pop(), str(objs[-1].get("reason", "")).strip(), None


def judge_run(run_id, label, model, a, stamp):
    """One run of the Judge with one re-run on an invalid vote."""
    prompt = PROMPT.format(ticker=a.ticker, queue=a.queue, label=label, run_id=run_id)
    vote = reason = why = None
    for attempt in (1, 2):
        _, out = call(model, prompt, a.judge_cmd, a.cwd, a.run_timeout)
        (a.votes_dir / f"{run_id}_a{attempt}.md").write_text(out or "")
        vote, reason, why = parse_vote(out, run_id)
        append_jsonl(a.votes_dir / "votes.jsonl", {"ts": stamp, "ticker": a.ticker, "run_id": run_id, "model": model,
                                                    "attempt": attempt, "vote": vote, "reason": reason, "invalid": why})
        if why is None:
            break
    return {"run_id": run_id, "vote": vote, "reason": reason, "invalid": why}


def stats(votes_dir):
    trades = [t for t in load_jsonl(votes_dir / "trades.jsonl") if t["tier"] == "high"]
    splits = sum(1 for t in trades if t.get("split"))
    shadow = [s for s in load_jsonl(votes_dir / "shadow.jsonl") if s.get("agree") is not None]
    agree = sum(1 for s in shadow if s["agree"])
    lines = [f"- High-risk trades judged: {len(trades)} · splits {splits}"
             + (f" ({splits / len(trades):.0%})" if trades else ""),
             f"- Fable-vs-Opus shadow comparisons: {len(shadow)} · agreement "
             + (f"{agree / len(shadow):.0%}" if shadow else "n/a")]
    if len(trades) >= MILESTONE:
        lines.append(f"- MILESTONE: {len(trades)} high-risk trades → report the split rate to John.")
    if len(shadow) >= MILESTONE:
        lines.append(f"- MILESTONE: {len(shadow)} shadow comparisons → report the agreement rate to John.")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--instrument", choices=["stock", "option", "crypto"])
    ap.add_argument("--notional", type=float, default=None, help="order size in USD (stocks)")
    ap.add_argument("--leverage", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--queue", default=QUEUE)
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--votes-dir", default=str(VOTES_DIR))
    ap.add_argument("--cwd", default="/Users/johntytko/trading-arena")
    ap.add_argument("--judge-cmd", default="", help="testing hook")
    ap.add_argument("--run-timeout", type=int, default=540)
    ap.add_argument("--shadow-rate", type=float, default=None)
    a = ap.parse_args()
    a.votes_dir = Path(a.votes_dir)
    a.votes_dir.mkdir(parents=True, exist_ok=True)
    if a.report:
        print("\n".join(stats(a.votes_dir)))
        return 0
    if not a.ticker or not a.instrument:
        ap.error("--ticker and --instrument are required")
    a.ticker = a.ticker.upper()
    cfg = json.loads(Path(a.config).read_text()) if Path(a.config).exists() else {}
    queue_text = Path(a.queue).read_text() if Path(a.queue).exists() else ""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    tier, why_tier = classify(a.instrument, a.ticker, a.notional, a.leverage, cfg, queue_text)
    failover = False
    if tier == "high":
        runs, model = HIGH_RUNS, FABLE
        if not model_available(FABLE, a.judge_cmd, a.cwd):
            model, failover = OPUS, True
    else:
        runs, model = ROUTINE_RUNS, ROUTINE_MODEL

    ids = [f"{stamp}-{a.ticker}-r{n}" for n in range(1, runs + 1)]
    with cf.ThreadPoolExecutor(max_workers=runs) as ex:
        results = list(ex.map(lambda i: judge_run(i[1], f"run {i[0]} of {runs}", model, a, stamp), enumerate(ids, 1)))
    valid = [r for r in results if r["invalid"] is None]
    approvals = sum(1 for r in valid if r["vote"] == "approve")
    final = "APPROVED" if len(valid) == runs and approvals == runs else "REJECTED"
    split = runs > 1 and len({r["vote"] for r in valid}) > 1
    append_jsonl(a.votes_dir / "trades.jsonl", {"ts": stamp, "ticker": a.ticker, "tier": tier, "tier_reasons": why_tier,
                                                "model": model, "failover": failover, "runs_required": runs,
                                                "valid_votes": len(valid), "approvals": approvals,
                                                "final": final, "split": split})

    shadow_line = None
    rate = a.shadow_rate if a.shadow_rate is not None else float(cfg.get("shadow_rate", 0.10))
    if tier == "high" and not failover and random.random() < rate:  # noqa: S311 — sampling, not crypto
        s = judge_run(f"{stamp}-{a.ticker}-shadow", "non-voting shadow run", OPUS, a, stamp)
        agree = None if s["invalid"] else (s["vote"] == "approve") == (final == "APPROVED")
        append_jsonl(a.votes_dir / "shadow.jsonl", {"ts": stamp, "ticker": a.ticker, "fable_final": final,
                                                    "opus_vote": s["vote"], "invalid": s["invalid"], "agree": agree})
        shadow_line = (f"- Shadow (non-voting) Opus 5.5: {s['vote'] or 'invalid (' + s['invalid'] + ')'}"
                       + ("" if agree is None else f" → {'agrees' if agree else 'DISAGREES'} with the verdict"))

    label = "HIGH-RISK" if tier == "high" else "ROUTINE"
    lines = [f"\n## JUDGE VERDICT — {stamp} — {a.ticker}: {final}",
             f"- Tier: {label} ({'; '.join(why_tier)}) · model {model} (effort high)"
             + (" · FAILOVER: Fable 5.1 unavailable" if failover else "")
             + f" · {runs} run(s), {'unanimous' if runs > 1 else 'single'} approval required",
             f"- Valid votes {len(valid)}/{runs} · approvals {approvals}" + (" · SPLIT" if split else "")]
    for r in results:
        lines.append(f"  - {r['run_id'].rsplit('-', 1)[-1]}: " + (f"{r['vote']} — {(r['reason'] or '')[:220]}"
                     if r["invalid"] is None else f"INVALID after re-run ({r['invalid']}) → counts as reject"))
    if shadow_line:
        lines.append(shadow_line)
    lines += stats(a.votes_dir)
    block = "\n".join(lines) + "\n"
    with open(a.queue, "a") as f:
        f.write(block)
    print(block)
    return 0 if final == "APPROVED" else 2


if __name__ == "__main__":
    sys.exit(main())
