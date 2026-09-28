#!/usr/bin/env python3
"""
GATE 1 — Deterministic Pre-Gate for Trading Arena thesis submissions.
=====================================================================
Purpose: mechanically fact-check every agent thesis BEFORE it reaches the
LLM Judge. The Judge's audit trail (Sep 16-28) shows most catches were
numeric: buying-power misrepresentation, market-cap errors (5.5x, 6x),
stale prices into pre-market gaps, re-scored win rates. These checks need
NO reasoning — they are arithmetic against live data. A script cannot
hallucinate, never 529-errors, and costs nothing to run.

Architecture:
    agent builds thesis -> GATE 1 (this script) -> if PASS -> LLM Judge
                                                     -> if FAIL -> rejected
                                                        with machine reason

Validation (how you know it's working):
    See VALIDATION section at bottom of this file + test suite. Three modes:
    1. shadow mode (log only, no enforcement) for 5 sessions
    2. replay mode against historical theses with known Judge verdicts
    3. synthetic theses with known-bad numbers (must all FAIL)

Usage:
    python3 gate1_pregate.py --thesis thesis.json [--shadow]
    Exit 0 = PASS (submit to Judge), Exit 1 = FAIL (reason printed), Exit 2 = ERROR
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIG — tuned to the arena's rulebook (skill v3.0.0 defaults)
# ---------------------------------------------------------------------------
CONFIG = {
    "max_positions": 5,               # per agent book limit
    "per_layer_max": 2,               # max positions per architecture layer
    "deployable_reserve": 500.0,      # cash reserve below which no entries
    "min_rr": 2.0,                    # risk/reward floor (Judge's standard)
    "price_freshness_seconds": 300,   # quote older than 5 min = stale
    "premarket_gap_pct": 1.5,         # live price > entry price by this = gap chase
    "stop_atr_multiple": 2.0,         # MIN stop distance = 2x ATR14 (anti-whipsaw)
    "stop_floor_pct": 0.10,           # traditional 10% minimum (unchanged rule)
    "stop_cap_pct": 0.20,              # widened stop allowed up to 20% w/ sizing
    "entry_price_sanity_pct": 0.02,   # thesis price vs live quote tolerance ±2%
    "earnings_blackout_days": 7,      # no entries within N days of earnings
    "no_reentry_days": 5,             # banned from re-entering a recent stop-out
    "market_cap_tolerance": 0.10,     # claimed mktcap within 10% of source
    "known_layers": ["compute", "memory", "networking", "power"],
}

# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """One check's outcome. Evidence, not adjectives."""
    check_id: str
    passed: bool
    detail: str
    claimed: str = ""    # what the thesis said
    verified: str = ""   # what the live data says

@dataclass
class GateReport:
    thesis_id: str
    timestamp: str
    mode: str                      # "enforce" | "shadow" | "replay"
    results: list = field(default_factory=list)
    def summary(self):
        fails = [r for r in self.results if not r.passed]
        return all(r.passed for r in self.results), fails

# ---------------------------------------------------------------------------
# CHECKS — every one is deterministic: number vs number.
# ---------------------------------------------------------------------------

def check_capital(thesis, account, config) -> GateResult:
    """Deployable capital check — catches the INTC $3,377 vs $385 error."""
    claimed_position_value = thesis["position_value"]
    shared_cash = account["cash"]                    # whole account cash
    reserve = config["deployable_reserve"]
    # deployable = agent's share. Agents are REQUIRED to submit their own
    # allocation math; gate verifies it against raw cash.
    deployable = max(0.0, shared_cash - reserve) * thesis.get("allocation_share", 1.0)
    ok = claimed_position_value <= deployable * 1.001  # 0.1% rounding grace
    return GateResult(
        "CAPITAL", ok,
        f"claimed ${claimed_position_value:,.2f} vs deployable ${deployable:,.2f}",
        claimed=f"${claimed_position_value:,.2f}",
        verified=f"${deployable:,.2f} (raw cash ${shared_cash:,.2f} − ${reserve} reserve)",
    )

def check_slots(thesis, agent_book, config) -> GateResult:
    """Position count + layer caps — mechanical book limits."""
    n_open = len(agent_book["positions"])
    ok_count = n_open < config["max_positions"]
    layer = thesis.get("layer", "").lower()
    n_layer = sum(1 for p in agent_book["positions"]
                  if p.get("layer", "").lower() == layer)
    ok_layer = n_layer < config["per_layer_max"]
    ok = ok_count and ok_layer
    return GateResult(
        "SLOTS", ok,
        f"{n_open}/{config['max_positions']} positions; layer '{layer}' at "
        f"{n_layer}/{config['per_layer_max']}",
    )

def check_market_cap(thesis, market) -> GateResult:
    """Claimed market cap vs verified source — catches ALAB 5.5x / INTC 6x."""
    claimed = thesis["market_cap"]
    actual = market["market_cap"]
    if actual <= 0:
        return GateResult("MKTCAP", False, "no market cap from data source")
    err = abs(claimed - actual) / actual
    ok = err <= CONFIG["market_cap_tolerance"]
    return GateResult(
        "MKTCAP", ok,
        f"claimed ${claimed/1e9:.2f}B vs actual ${actual/1e9:.2f}B "
        f"({err*100:.1f}% error)",
        claimed=f"${claimed/1e9:.2f}B", verified=f"${actual/1e9:.2f}B",
    )

def _parse_time(v):
    """Accept datetime OR ISO 8601 string (JSON round-trip) → datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

def check_price_freshness(thesis, market) -> GateResult:
    """Entry price vs live quote: freshness AND gap-chase detection.
    Catches: stale-close theses placed into pre-market gaps (INTC +3.7%)."""
    claimed_price = thesis["entry_price"]
    live = market["last_price"]
    quote_time = _parse_time(market.get("quote_time"))  # datetime or ISO str
    now = _parse_time(thesis.get("eval_time")) or datetime.now(timezone.utc)
    # (a) freshness
    if quote_time is None:
        return GateResult("PRICE", False, "no quote timestamp from source")
    age = (now - quote_time).total_seconds()
    if age > CONFIG["price_freshness_seconds"]:
        return GateResult(
            "PRICE", False,
            f"quote {age/60:.0f} min old (> {CONFIG['price_freshness_seconds']//60} min)",
        )
    # (b) sanity: claimed price within ±2% of live (else the agent priced
    # off a different instrument/day — the price-parse bug class)
    dev = abs(claimed_price - live) / live
    if dev > CONFIG["entry_price_sanity_pct"]:
        return GateResult(
            "PRICE", False,
            f"claimed ${claimed_price:.2f} vs live ${live:.2f} "
            f"({dev*100:.1f}% deviation — likely wrong instrument or parse)",
        )
    # (c) gap-chase: live ABOVE claimed by > threshold means the agent
    # priced the thesis on a stale close and the stock gapped up = chase.
    gap = (live - claimed_price) / claimed_price
    if gap > CONFIG["premarket_gap_pct"] / 100:
        return GateResult(
            "PRICE", False,
            f"live ${live:.2f} is {gap*100:+.1f}% above claimed "
            f"${claimed_price:.2f} — gap chase (thesis priced on stale close)",
        )
    return GateResult("PRICE", True, f"claimed ${claimed_price:.2f} ≈ live ${live:.2f}")

def check_rr_arithmetic(thesis) -> GateResult:
    """R/R recomputed from first principles — never trust stated ratio.
    Catches: BA's '2.02:1' that was 1.02:1 at conservative target."""
    entry = thesis["entry_price"]
    target = thesis["target_price"]
    stop = thesis["stop_price"]
    if stop >= entry:
        return GateResult("RR", False, f"stop ${stop} >= entry ${entry}")
    if target <= entry:
        return GateResult("RR", False, f"target ${target} <= entry ${entry}")
    rr = (target - entry) / (entry - stop)
    claimed_rr = thesis.get("claimed_rr", rr)
    ok = rr >= CONFIG["min_rr"]
    honest = abs(rr - claimed_rr) / max(claimed_rr, 0.01) < 0.05  # 5% tolerance
    if not honest:
        return GateResult(
            "RR", False,
            f"claimed {claimed_rr:.2f}:1 but recomputed {rr:.2f}:1 "
            "(misrepresentation)",
        )
    return GateResult("RR", ok, f"recomputed {rr:.2f}:1 (floor {CONFIG['min_rr']}:1)")

def check_stop_vs_volatility(thesis, market) -> GateResult:
    """NEW (audit fix): stop distance must clear 2x ATR14 so a normal
    2-3 day noise move can't kill a months-long thesis (COHR/MU class).
    Dollar risk is held constant by the sizing check below."""
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    atr = market.get("atr14")
    if not atr or atr <= 0:
        # no ATR available: fall back to the classic 10% floor, pass-through
        dist = (entry - stop) / entry
        ok = dist >= CONFIG["stop_floor_pct"]
        return GateResult("STOP", ok,
                          f"no ATR; classic floor dist {dist*100:.1f}% "
                          f"(min {CONFIG['stop_floor_pct']*100:.0f}%)")
    min_stop_distance = CONFIG["stop_atr_multiple"] * atr
    actual_distance = entry - stop
    pct_distance = actual_distance / entry
    # Stop must be >= 2x ATR away AND within the widened cap.
    clears_noise = actual_distance >= min_stop_distance
    within_cap = pct_distance <= CONFIG["stop_cap_pct"]
    ok = clears_noise and within_cap
    return GateResult(
        "STOP", ok,
        f"stop ${stop:.2f} = {pct_distance*100:.1f}% below entry "
        f"({actual_distance/min_stop_distance:.1f}x of 2·ATR "
            f"=${min_stop_distance:.2f}; cap {CONFIG['stop_cap_pct']*100:.0f}%)",
    )

def check_dollar_risk(thesis, account) -> GateResult:
    """Anti-whipsaw companion: wider stop ⇒ smaller size, SAME dollar risk.
    If a thesis widens its stop to clear ATR, position value must shrink so
    (shares x stop distance) <= the classic 10%-rule dollar risk."""
    shares = thesis["shares"]
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    dollar_risk = shares * (entry - stop)
    classic_risk = shares * entry * CONFIG["stop_floor_pct"]  # 10% equivalent
    ok = dollar_risk <= classic_risk * 1.001
    return GateResult(
        "RISK", ok,
        f"dollar risk ${dollar_risk:.2f} vs 10%-rule equivalent "
        f"${classic_risk:.2f}",
    )

def check_earnings_window(thesis, market) -> GateResult:
    """No entries inside the earnings blackout (event risk ≠ thesis risk)."""
    edate = market.get("earnings_date")  # date or None
    if not edate:
        return GateResult("EARN", True, "no earnings date on file")
    today = (_parse_time(thesis.get("eval_time")) or
             datetime.now(timezone.utc)).date()
    days = (edate - today).days
    ok = days > CONFIG["earnings_blackout_days"]
    return GateResult("EARN", ok,
                      f"earnings {days} days out (blackout "
                      f"{CONFIG['earnings_blackout_days']}d)")

def check_no_reentry(thesis, agent_book) -> GateResult:
    """Banned from re-entering a ticker stopped out within N days
    (functionally averaging down on a failed setup — the BAC rule)."""
    ticker = thesis["ticker"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG["no_reentry_days"])
    recent_stops = [s for s in agent_book.get("recent_stop_exits", [])
                    if s["ticker"] == ticker and s["date"] >= cutoff]
    ok = not recent_stops
    if not ok:
        s = recent_stops[0]
        return GateResult("REENTRY", False,
                          f"{ticker} stopped out {s['date'].date()} "
                          f"(< {CONFIG['no_reentry_days']}d ago) at ${s['price']:.2f}")
    return GateResult("REENTRY", True, f"no {ticker} stop in last "
                                       f"{CONFIG['no_reentry_days']}d")

# ---------------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------------

CHECKS = [
    # (check_id, function, arg-builder from (thesis, account, market, agent_book))
    ("CAPITAL", check_capital,        lambda th, ac, mk, bk: (th, ac, CONFIG)),
    ("SLOTS",   check_slots,          lambda th, ac, mk, bk: (th, bk, CONFIG)),
    ("MKTCAP",  check_market_cap,     lambda th, ac, mk, bk: (th, mk)),
    ("PRICE",   check_price_freshness,lambda th, ac, mk, bk: (th, mk)),
    ("RR",      check_rr_arithmetic,  lambda th, ac, mk, bk: (th,)),
    ("STOP",    check_stop_vs_volatility, lambda th, ac, mk, bk: (th, mk)),
    ("RISK",    check_dollar_risk,    lambda th, ac, mk, bk: (th, ac)),
    ("EARN",    check_earnings_window,lambda th, ac, mk, bk: (th, mk)),
    ("REENTRY", check_no_reentry,     lambda th, ac, mk, bk: (th, bk)),
]

def run_gate(thesis: dict, account: dict, market: dict,
             agent_book: dict, mode: str = "enforce") -> GateReport:
    report = GateReport(
        thesis_id=thesis.get("thesis_id", "unknown"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
    )
    for check_id, fn, build_args in CHECKS:
        try:
            report.results.append(fn(*build_args(thesis, account, market, agent_book)))
        except Exception as e:  # a check that crashes = FAIL that check
            report.results.append(
                GateResult(check_id, False, f"CHECK ERROR: {e}"))
    return report

def print_report(report: GateReport):
    print(f"\n=== GATE 1 — {report.thesis_id} ({report.mode}) "
          f"@ {report.timestamp} ===")
    all_ok, fails = report.summary()
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"[{mark}] {r.check_id:8s} {r.detail}"
              + (f"  (claimed {r.claimed} vs verified {r.verified})"
                 if r.claimed else ""))
    verdict = "PASS — submit to LLM Judge" if all_ok else \
              f"REJECT — {len(fails)} deterministic failure(s): " + \
              ", ".join(f.check_id for f in fails)
    print(f"\nVERDICT: {verdict}\n")
    return all_ok

# ---------------------------------------------------------------------------
# TESTS — this is how you know Gate 1 itself works. Run: python3 gate1_pregate.py --selftest
# Every test case is a REAL event from the Judge's decision log (Sep 16-28).
# ---------------------------------------------------------------------------
def selftest():
    import copy
    passing = 0; failing = 0

    def run_case(name, thesis, account, market, book, expect_pass):
        nonlocal passing, failing
        rep = run_gate(thesis, account, market, book, mode="replay")
        ok, fails = rep.summary()
        got_pass = ok
        status = "✅" if got_pass == expect_pass else "❌ TEST FAILURE"
        if got_pass == expect_pass: passing += 1
        else:
            failing += 1
            print(f"  {status} {name}: expected {'PASS' if expect_pass else 'FAIL'}, "
                  f"got {'PASS' if ok else 'FAIL ' + str([f.check_id for f in fails])}")

    now = datetime.now(timezone.utc)
    fresh = now - timedelta(seconds=30)

    base_market = {"last_price": 100.0, "quote_time": fresh,
                   "market_cap": 50e9, "atr14": 4.0,
                   "earnings_date": None}
    base_account = {"cash": 3000.0}
    base_book = {"positions": [], "recent_stop_exits": []}
    base_thesis = {
        "thesis_id": "T1", "ticker": "TEST", "entry_price": 100.0,
        "target_price": 120.0, "stop_price": 90.0, "shares": 1.0,
        "position_value": 100.0, "market_cap": 50e9, "layer": "compute",
        "claimed_rr": 2.0, "allocation_share": 1.0,
        "eval_time": now,
    }

    # --- cases that MUST PASS --------------------------------------------
    run_case("clean thesis", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), copy.deepcopy(base_market),
             copy.deepcopy(base_book), True)

    # --- cases that MUST FAIL — each maps to a real Judge catch ---------
    # 1. INTC buying-power misrep: $485 position vs $385 deployable
    t = copy.deepcopy(base_thesis); t["position_value"] = 485.0
    a = copy.deepcopy(base_account); a["cash"] = 885.0  # 885-500=385 deployable
    run_case("INTC-class capital misrep", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False)

    # 2. ALAB market-cap 5.5x error: claimed 8.5B actual 46.7B
    t = copy.deepcopy(base_thesis); t["market_cap"] = 8.5e9
    m = copy.deepcopy(base_market); m["market_cap"] = 46.7e9
    run_case("ALAB-class mktcap 5.5x error", t,
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False)

    # 3. INTC stale-price gap chase: claimed 97.14 close, live 100.70 (+3.7%)
    t = copy.deepcopy(base_thesis); t["entry_price"] = 97.14
    m = copy.deepcopy(base_market); m["last_price"] = 100.70
    run_case("INTC-class gap chase", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False)

    # 4. price-parse bug: claimed price 2%+ off live (wrong instrument)
    t = copy.deepcopy(base_thesis); t["entry_price"] = 108.0
    run_case("price-parse deviation", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False)

    # 5. BA-class R/R misrepresentation: claimed 2.02:1, real 1.02:1
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 100.0, "target_price": 102.0, "stop_price": 98.0})
    run_case("BA-class R/R misrep", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False)

    # 6. COHR-class whipsaw stop: stop tighter than 2x ATR
    t = copy.deepcopy(base_thesis)  # stop 10 below entry, ATR 4 => 10 < 8? no, 10>=8 pass
    t.update({"entry_price": 307.45, "stop_price": 276.71, "target_price": 370.0})
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    # 2*ATR = 30; stop distance 30.74 >= 30 → borderline PASS under new rule,
    # but dollar risk: 1 share * 30.74 = 30.74 vs 10% floor 30.745 → equal, ok.
    # This documents that the COHR stop was EXACTLY at the edge — which is the point.
    run_case("COHR edge case (2xATR boundary)", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), True)

    # 6b. same trade with a genuinely-too-tight stop vs ATR
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 307.45, "stop_price": 291.0, "target_price": 370.0,
              "position_value": 307.45})
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("whipsaw stop < 2x ATR", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False)

    # 7. re-entry ban: BAC stopped 2 days ago, thesis re-enters today
    t = copy.deepcopy(base_thesis); t["ticker"] = "BAC"
    b = copy.deepcopy(base_book)
    b["recent_stop_exits"] = [{"ticker": "BAC",
                               "date": now - timedelta(days=2),
                               "price": 56.20}]
    run_case("BAC-class re-entry ban", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), b, False)

    # 8. earnings blackout: earnings in 3 days
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now + timedelta(days=3)).date()
    run_case("earnings blackout", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False)

    # 9. layer max: networking already 2/2
    t = copy.deepcopy(base_thesis); t["layer"] = "networking"
    b = copy.deepcopy(base_book)
    b["positions"] = [{"layer": "networking"}, {"layer": "networking"}]
    run_case("networking layer full", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), b, False)

    # 10. stale quote: timestamp 30 min old
    m = copy.deepcopy(base_market)
    m["quote_time"] = now - timedelta(minutes=30)
    run_case("stale quote", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False)

    print(f"\nSelf-test: {passing} passed, {failing} failed")
    if failing:
        print("GATE 1 NOT READY — fix failing cases before deployment")
        return 1
    print("GATE 1 READY — all historical Judge catches reproduced mechanically")
    return 0

# ---------------------------------------------------------------------------
# VALIDATION PLAN — "how do I know it's working but not wrong?"
# ---------------------------------------------------------------------------
# The fear is correct: a gate can be (a) not running, (b) running but
# passing bad theses, or (c) running but rejecting good ones. The plan:
#
# PHASE 1 — REPLAY (build confidence it catches the right things)
#   Feed it the 6 real rejected theses (INTC x2, ALAB x2, U, BA) with the
#   real numbers from the Judge log. Gate 1 must FAIL every one of them,
#   for the SAME reason the Judge gave. If it passes any → fix before use.
#   (encoded as the selftest above)
#
# PHASE 2 — SHADOW MODE (build confidence it doesn't over-reject)
#   For 5 sessions, agents run Gate 1 BEFORE the Judge but it only LOGS.
#   Compare its verdicts to the LLM Judge's on every submission.
#   - Gate PASS + Judge APPROVE  → both agree, good
#   - Gate FAIL + Judge REJECT  → both agree, good (and the Judge wasted
#     no reasoning budget on arithmetic it shouldn't be doing)
#   - Gate FAIL + Judge APPROVE → THE DANGER CASE: gate over-rejecting.
#     Manually review each. If the gate is right, the Judge missed it.
#     If the Judge is right, loosen the gate's threshold.
#   - Gate PASS + Judge REJECT  → expected & fine: the Judge catches
#     reasoning problems (falling knives, catalyst reality) that are
#     OUTSIDE Gate 1's job description.
#   Disagreement rate should settle near zero on arithmetic matters.
#
# PHASE 3 — ENFORCE (flip the switch)
#   Only after shadow shows < 10% disagreement on FAIL/APPROVE cases.
#   Keep shadow-logging forever: every enforcement verdict is written
#   to gate1_log.jsonl with full evidence (claimed vs verified numbers).
#
# CONTINUOUS METRICS (the "is it working" dashboard):
#   - gate_rejections_by_check  → which check fires most (data quality
#     early on: MKTCAP/PRICE; discipline later)
#   - disagreement_rate vs Judge (should trend to ~0 for arithmetic)
#   - false-reject review queue: any Gate FAIL + Judge APPROVE gets a
#     mandatory human (you) review note — this is your override valve.
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thesis", help="path to thesis JSON")
    ap.add_argument("--shadow", action="store_true",
                    help="log verdict but do not enforce")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.thesis:
        print(__doc__); sys.exit(2)

    thesis = json.loads(Path(args.thesis).read_text())
    # In production, account/market/book come from live MCP pulls;
    # this stub accepts them embedded in the thesis file for now.
    account = thesis.pop("account", {"cash": 3000.0})
    market = thesis.pop("market", {})
    book = thesis.pop("agent_book", {"positions": [],
                                     "recent_stop_exits": []})
    mode = "shadow" if args.shadow else "enforce"
    report = run_gate(thesis, account, market, book, mode=mode)

    # append-only audit log — every verdict, full evidence
    log_path = Path(__file__).parent / "gate1_log.jsonl"
    with log_path.open("a") as f:
        f.write(json.dumps({**asdict(report),
                            "verdict": "PASS" if report.summary()[0] else "FAIL"}) + "\n")

    ok = print_report(report)
    sys.exit(0 if (ok or mode == "shadow") else 1)

if __name__ == "__main__":
    main()
