#!/usr/bin/env python3
"""Read-only Robinhood access for every caller that must never trade.

One place for the broker deny-list. Callers: Beta's position pull, Charlie's
quotes/chains, the Daily Judge Audit, the Judge (judge_vote.py), Rocky
(rocky_consult.py) and the pre-market health probe. Only Beta's ORDER step
(after a Judge APPROVED verdict) runs Claude with the write tools available.

The deny-list removes every tool that can change the account under BOTH
Robinhood MCP registrations (claude.ai connector + local "robinhood-trading"
server scoped to ~). Verified Oct 24 2026 that --disallowedTools holds even
with --dangerously-skip-permissions (the tool disappears from the session).

CLI:
  broker_read.py [--max-turns 14] [--timeout 280] "<request>"
    → prints Claude's answer; exit code = Claude's exit code (124 on timeout).
"""
import argparse
import subprocess
import sys

CLAUDE = "/Users/johntytko/.local/bin/claude"
WRITE_TOOL_NAMES = (
    "place_equity_order", "place_option_order", "place_crypto_order",
    "cancel_equity_order", "cancel_option_order", "cancel_crypto_order",
    "exercise_option", "cancel_option_exercise",
)
SERVER_PREFIXES = ("mcp__claude_ai_Robinhood_trading__", "mcp__robinhood-trading__")
BROKER_WRITE_TOOLS = ",".join(f"{srv}{t}" for srv in SERVER_PREFIXES for t in WRITE_TOOL_NAMES)
PREFIX = ("READ-ONLY broker request: never place, cancel, modify or exercise any order "
          "(those tools are disabled in this session). ")


def read_only_cmd(prompt, max_turns=14, model=None, effort=None):
    """argv for a claude -p call with every broker write tool removed."""
    cmd = [CLAUDE, "-p", prompt]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    return cmd + ["--max-turns", str(max_turns), "--dangerously-skip-permissions",
                  "--disallowedTools", BROKER_WRITE_TOOLS]


def main():
    ap = argparse.ArgumentParser(description="Read-only Robinhood request via Claude")
    ap.add_argument("request")
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--timeout", type=int, default=280)
    ap.add_argument("--cwd", default="/Users/johntytko/trading-arena")
    a = ap.parse_args()
    try:
        r = subprocess.run(read_only_cmd(PREFIX + a.request, a.max_turns), capture_output=True,
                           text=True, timeout=a.timeout, cwd=a.cwd)
    except subprocess.TimeoutExpired:
        print(f"BROKER_READ_TIMEOUT after {a.timeout}s")
        return 124
    print(r.stdout)
    if r.returncode != 0 and r.stderr:
        print(r.stderr[-500:], file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
