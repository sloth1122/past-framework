#!/usr/bin/env python3
"""Consistency vote for the pre-trade Judge (Arena v5.1, Oct 23 2026).

Runs the Trade Judge 3 times INDEPENDENTLY (in parallel, fresh contexts) on the
PENDING theses in the queue. A thesis is APPROVED only if all 3 votes approve
(unanimous). Each vote writes to its own file; this script appends one
CONSENSUS block to the queue. Evidence: same LLM + same inputs gives different
buy/hold/sell answers run to run (Koviazin et al., "Reproducibility in the
TradingAgents Framework", IC-AIF 2026).

Usage: judge_vote.py [--queue PATH] [--votes 3] [--judge-cmd CMD (testing)]
Exit 0 always; prints the consensus block (Beta reads it).
"""
import argparse, concurrent.futures as cf, re, subprocess, sys
from datetime import datetime
from pathlib import Path

CLAUDE = "/Users/johntytko/.local/bin/claude"
# Judges are read-only: remove every broker tool that can change the account
# (harness-enforced; verified Oct 24 2026 that --disallowedTools holds even with
# --dangerously-skip-permissions).
# both Robinhood MCP registrations: the claude.ai connector AND the local
# "robinhood-trading" server scoped to /Users/johntytko (loaded when cwd = ~).
BROKER_WRITE_TOOLS = ",".join(f"{srv}{t}" for srv in (
    "mcp__claude_ai_Robinhood_trading__", "mcp__robinhood-trading__") for t in (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "exercise_option", "cancel_option_exercise"))
QUEUE = "/Users/johntytko/trading-arena/state/thesis_queue.md"
VOTES_DIR = Path("/Users/johntytko/trading-arena/state/judge_votes")

PROMPT = """You are the Trade Judge (load skill trade-judge, including its ARENA v5 block). This is INDEPENDENT VOTE {n} of {total}: other judges are evaluating the same theses separately — do not look for or read their votes.
Read the thesis queue at {queue} and evaluate every PENDING thesis from Beta. Run the full checklist with your OWN data pulls (Robinhood connector, read-only): sizing (≤30% equity, dollar risk ≤3% equity, gap risk if earnings inside the hold), 2×ATR(14) stop recomputed, dated catalyst ≤30 trading days, the REQUIRED bear case (real news only — lawsuits, CEO exits, lost customers, guidance cuts, financing stress; reject theses whose bear case is generic "AI bubble" talk or missing), R/R ≥ 2.0, IPO ban, limited-margin limits (no borrowing/shorting/naked options). For OPTION theses also run the trade-judge options checklist (buy-only single leg or debit vertical, direction vs thesis, max loss ≤ 3% equity, ≤ $1,500/month premium, expiry 7–60 days after the catalyst, limit ≤ mid from your own chain pull, exit plan).
Do NOT edit the queue file and do NOT place trades. End your reply with exactly one line per thesis in this format:
VOTE | <TICKER> | APPROVED or REJECTED | <one-sentence reason>"""

VOTE_RE = re.compile(r"^VOTE\s*\|\s*([A-Z.\-]+)\s*\|\s*(APPROVED|REJECTED)\s*\|\s*(.*)$", re.M)


def run_vote(n, total, queue, judge_cmd, cwd):
    prompt = PROMPT.format(n=n, total=total, queue=queue)
    cmd = judge_cmd.split() + [prompt] if judge_cmd else \
        [CLAUDE, "-p", prompt, "--max-turns", "25", "--dangerously-skip-permissions",
         "--disallowedTools", BROKER_WRITE_TOOLS]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=540, cwd=cwd)
        out = r.stdout
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    return n, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=QUEUE)
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--judge-cmd", default="")
    ap.add_argument("--cwd", default="/Users/johntytko/trading-arena")
    ap.add_argument("--votes-dir", default=str(VOTES_DIR))
    a = ap.parse_args()
    votes_dir = Path(a.votes_dir)
    votes_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    with cf.ThreadPoolExecutor(max_workers=a.votes) as ex:
        results = list(ex.map(lambda n: run_vote(n, a.votes, a.queue, a.judge_cmd, a.cwd), range(1, a.votes + 1)))
    tally = {}   # ticker -> list of (vote_no, verdict, reason)
    for n, out in results:
        (votes_dir / f"{stamp}_vote{n}.md").write_text(out)
        found = VOTE_RE.findall(out)
        for t, v, why in found:
            tally.setdefault(t.upper(), []).append((n, v, why.strip()))
    lines = [f"\n## CONSENSUS VERDICT — {stamp} ({a.votes} independent Judge votes; unanimous required)"]
    if not tally:
        lines.append("- NO PARSEABLE VOTES → treat every PENDING thesis as **REJECTED** (fail closed). Raw votes: "
                     f"state/judge_votes/{stamp}_vote*.md")
    for t, vs in sorted(tally.items()):
        approvals = sum(1 for _, v, _ in vs if v == "APPROVED")
        final = "APPROVED" if approvals == a.votes and len(vs) == a.votes else "REJECTED"
        lines.append(f"- **{t}: {final}** ({approvals}/{a.votes} approve)")
        for n, v, why in sorted(vs):
            lines.append(f"  - vote {n}: {v} — {why[:220]}")
        missing = a.votes - len(vs)
        if missing:
            lines.append(f"  - {missing} vote(s) missing/unparseable → counted as REJECTED")
    block = "\n".join(lines) + "\n"
    with open(a.queue, "a") as f:
        f.write(block)
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
