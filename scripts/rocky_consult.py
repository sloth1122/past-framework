#!/usr/bin/env python3
"""Rocky pre-trade coach consult (Arena v5.1, Oct 23 2026).

Beta runs this BEFORE submitting any trade sourced from Charlie (or any options trade) to the Judges.
Rocky (skill trading-arena-rocky) reviews the proposal against Beta's scored history
(state/decisions/lessons.md) and returns one line:
    COACH | <TICKER> | GO or ADJUST or PASS | <reason / the adjustment>
The verdict is appended to the proposal file. Rocky is advisory, but Beta must answer any ADJUST/PASS in
writing in the thesis ("Coach said X; I am doing Y because Z") — the Judges see it.

Usage: rocky_consult.py --proposal PATH [--ticker T]
"""
import argparse, re, subprocess, sys
from datetime import datetime

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from broker_read import CLAUDE, BROKER_WRITE_TOOLS  # noqa: E402 — single source of the deny-list
PROMPT = """You are Rocky, the arena coach (load skill trading-arena-rocky). This is a PRE-TRADE COACH CONSULT, not your weekly review.
Read Charlie's options proposal at {p}{t}, Beta's scorecard at /Users/johntytko/trading-arena/state/decisions/lessons.md, and Beta's open positions in /Users/johntytko/trading-arena/state/agent_beta/state.md.
Coach on: (1) does this repeat a pattern the scorecard shows losing (e.g., buying into macro-driven selloffs, chasing a prior stop-out)? (2) is the max loss / position count sane given current equity and the open positions in state.md (read them; do not assume)? (3) is Charlie's enthusiasm backed by the numbers (EV, breakeven vs implied move, liquidity)? (4) one concrete adjustment if any (strike, width, size, expiry, wait for X).
Do NOT place trades and do NOT edit any file. Under 200 words. End with exactly one line:
COACH | <TICKER> | GO or ADJUST or PASS | <one-sentence reason or adjustment>"""
RE = re.compile(r"^COACH\s*\|\s*([A-Z.\-]+)\s*\|\s*(GO|ADJUST|PASS)\s*\|\s*(.*)$", re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--ticker", default="")
    ap.add_argument("--judge-cmd", default="")   # testing hook
    a = ap.parse_args()
    prompt = PROMPT.format(p=a.proposal, t=f" (ticker {a.ticker})" if a.ticker else "")
    cmd = a.judge_cmd.split() + [prompt] if a.judge_cmd else [CLAUDE, "-p", prompt, "--max-turns", "15", "--dangerously-skip-permissions", "--disallowedTools", BROKER_WRITE_TOOLS]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=290, cwd="/Users/johntytko/trading-arena").stdout
    except Exception:  # noqa: BLE001 — timeout, missing binary, any OSError → fail closed below
        out = ""
    m = RE.findall(out or "")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if m:
        t, v, why = m[-1]
        line = f"COACH | {t} | {v} | {why.strip()}"
    else:
        line = f"COACH | {a.ticker or '?'} | PASS | Rocky consult failed/timed out — fail closed: no trade on this proposal today."
    body = out.strip().split("COACH |")[0].strip()
    with open(a.proposal, "a") as f:
        f.write(f"\n\n## Rocky coach consult — {stamp}\n{body[-1500:]}\n\n**{line}**\n")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
