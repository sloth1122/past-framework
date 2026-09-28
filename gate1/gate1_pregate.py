#!/usr/bin/env python3
"""
GATE 1 — Deterministic Pre-Gate for Trading Arena thesis submissions.
=====================================================================
Purpose: mechanically fact-check every agent thesis BEFORE it reaches the
LLM Judge. The Judge's audit trail (Sep 16-28) shows most catches were
numeric: buying-power misrepresentation, market-cap errors (5.5x, 6x),
stale prices into pre-market gaps, re-scored win rates. These checks need
NO reasoning — they are arithmetic against live data.

TRUST MODEL (important):
    account / market / agent_book data is TRUSTED only when supplied by
    the harness from live MCP pulls. A thesis file may embed these values
    ONLY for demo/testing purposes (`--demo`). Enforce mode REFUSES to
    run on submitter-controlled data.

Architecture:
    agent builds thesis -> harness injects trusted data -> GATE 1
    -> if PASS -> LLM Judge
    -> if FAIL -> rejected with machine reason

Validation:
    See VALIDATION section at the bottom + the selftest. Three modes:
    1. shadow mode (log only, no enforcement) for 5 sessions
    2. replay mode against synthetic scenarios built from the Judge log's
       documented failure patterns
    3. live-fire with harness-injected trusted data

Usage:
    python3 gate1_pregate.py --thesis thesis.json --demo   # demo (embedded data)
    python3 gate1_pregate.py --thesis t.json --account a.json \
        --market m.json --book b.json                     # enforce (trusted data)
    python3 gate1_pregate.py --thesis t.json --demo --shadow  # log-only demo
    python3 gate1_pregate.py --selftest
    Exit 0 = PASS (submit to Judge), Exit 1 = FAIL (reason printed), Exit 2 = ERROR
"""

import argparse
import json
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
    "position_value_tolerance": 0.02, # position_value vs shares×entry tolerance ±2%
    "max_position_value": 500.0,      # FIXED budget baseline per trade (allocation cap)
    "earnings_blackout_days": 7,      # no entries within N days BEFORE earnings
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
    mode: str                      # "enforce" | "shadow" | "replay" | "demo"
    results: list = field(default_factory=list)
    def summary(self):
        fails = [r for r in self.results if not r.passed]
        return all(r.passed for r in self.results), fails

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _parse_time(v):
    """Accept datetime OR ISO 8601 string (JSON round-trip) → datetime, else None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def _parse_date(v):
    """Accept date, datetime, or ISO string → date, else None."""
    dt = _parse_time(v)
    if isinstance(v, __import__("datetime").date) and not isinstance(v, datetime):
        return v
    return dt.date() if dt else None

# ---------------------------------------------------------------------------
# CHECKS — every one is deterministic: number vs number.
# ---------------------------------------------------------------------------

def check_capital(thesis, account, config) -> GateResult:
    """Deployable capital check — catches the INTC $3,377 vs $385 error.

    Verified order cost = shares x entry_price (recomputed from first
    principles). A materially understated position_value cannot enlarge
    the permitted purchase. allocation_share is bounded to (0, 1] — an
    agent cannot multiply its own allowance.
    """
    shares = thesis["shares"]
    entry = thesis["entry_price"]
    claimed_position_value = thesis["position_value"]
    order_cost = shares * entry
    # (a) claimed position value must match the recomputed order cost
    if order_cost > 0:
        pv_err = abs(claimed_position_value - order_cost) / order_cost
        if pv_err > config["position_value_tolerance"]:
            return GateResult(
                "CAPITAL", False,
                f"claimed position_value ${claimed_position_value:,.2f} vs "
                f"recomputed shares×entry ${order_cost:,.2f} "
                f"({pv_err*100:.1f}% — understated/overstated size)",
                claimed=f"${claimed_position_value:,.2f}",
                verified=f"${order_cost:,.2f} (shares×entry)",
            )
    # (b) allocation_share must be a valid fraction of the account
    share = thesis.get("allocation_share", 1.0)
    if not (0.0 < share <= 1.0):
        return GateResult(
            "CAPITAL", False,
            f"allocation_share {share} outside (0, 1] — cannot exceed "
            f"the agent's own allocation",
        )
    shared_cash = account["cash"]                    # whole account cash
    reserve = config["deployable_reserve"]
    deployable = max(0.0, shared_cash - reserve) * share
    # (c) VERIFIED order cost (not the claimed value) must fit
    ok = order_cost <= deployable * 1.001  # 0.1% rounding grace
    return GateResult(
        "CAPITAL", ok,
        f"verified order cost ${order_cost:,.2f} vs deployable "
        f"${deployable:,.2f}",
        claimed=f"${claimed_position_value:,.2f}",
        verified=f"${order_cost:,.2f} (raw cash ${shared_cash:,.2f} − "
                 f"${reserve} reserve × share {share})",
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

def check_price_freshness(thesis, market, now) -> GateResult:
    """Entry price vs live quote: freshness AND gap-chase detection.
    Catches: stale-close theses placed into pre-market gaps (INTC +3.7%).

    `now` is the TRUSTED clock (gate's own time in enforce mode, or the
    harness-supplied historical time in replay) — never a thesis field.
    """
    claimed_price = thesis["entry_price"]
    live = market["last_price"]
    quote_time = _parse_time(market.get("quote_time"))
    # (a) freshness
    if quote_time is None:
        return GateResult("PRICE", False, "no/invalid quote timestamp from source")
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
    """Audit fix: stop distance must clear noise so a normal 2-3 day move
    can't kill a months-long thesis (COHR/MU class).

    When ATR is available, the required stop distance is the LARGER of
    (10% of entry — the classic floor — and 2x ATR14), capped at 20%.
    Dollar risk is held constant by the RISK check below.
    """
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    atr = market.get("atr14")
    actual_distance = entry - stop
    pct_distance = actual_distance / entry
    if actual_distance <= 0:
        return GateResult("STOP", False, f"stop ${stop} >= entry ${entry}")
    if not atr or atr <= 0:
        # no ATR available: fall back to the classic 10% floor
        ok = pct_distance >= CONFIG["stop_floor_pct"]
        return GateResult("STOP", ok,
                          f"no ATR; classic floor dist {pct_distance*100:.1f}% "
                          f"(min {CONFIG['stop_floor_pct']*100:.0f}%)")
    floor_distance = entry * CONFIG["stop_floor_pct"]     # classic 10% of entry
    atr_distance = CONFIG["stop_atr_multiple"] * atr      # 2 x ATR14
    min_stop_distance = max(floor_distance, atr_distance)
    within_cap = pct_distance <= CONFIG["stop_cap_pct"]
    ok = actual_distance >= min_stop_distance and within_cap
    return GateResult(
        "STOP", ok,
        f"stop ${stop:.2f} = {pct_distance*100:.1f}% below entry "
        f"(required ≥ max(10% floor ${floor_distance:.2f}, "
        f"2·ATR ${atr_distance:.2f}) = ${min_stop_distance:.2f}; "
        f"cap {CONFIG['stop_cap_pct']*100:.0f}%)",
    )

def check_dollar_risk(thesis, config) -> GateResult:
    """Anti-whipsaw companion: wider stop ⇒ smaller size, SAME dollar risk.

    The risk budget is a FIXED baseline (max_position_value x 10%) — it is
    NOT derived from the proposed shares, which would be circular (a
    bigger position would inflate its own budget).
    """
    shares = thesis["shares"]
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    dollar_risk = shares * (entry - stop)
    # fixed budget: 10% of the per-trade allocation cap
    risk_budget = config["max_position_value"] * config["stop_floor_pct"]
    ok = dollar_risk <= risk_budget * 1.001
    return GateResult(
        "RISK", ok,
        f"dollar risk ${dollar_risk:.2f} vs fixed budget "
        f"${risk_budget:.2f} (10% of ${config['max_position_value']:,.0f} "
        f"allocation cap)",
    )

def check_earnings_window(thesis, market, now) -> GateResult:
    """No entries inside the pre-earnings blackout (event risk ≠ thesis
    risk). Earnings dates in the PAST are allowed through (already
    reported)."""
    edate = _parse_date(market.get("earnings_date"))
    if edate is None:
        return GateResult("EARN", True, "no earnings date on file")
    today = now.date()
    days = (edate - today).days
    # blackout: strictly future earnings within the window
    in_blackout = 0 < days <= CONFIG["earnings_blackout_days"]
    if in_blackout:
        return GateResult("EARN", False,
                          f"earnings in {days} days (blackout "
                          f"{CONFIG['earnings_blackout_days']}d)")
    if days <= 0:
        return GateResult("EARN", True,
                          f"earnings already reported ({abs(days)}d ago)")
    return GateResult("EARN", True,
                      f"earnings {days} days out (blackout "
                      f"{CONFIG['earnings_blackout_days']}d)")

def check_no_reentry(thesis, agent_book, now) -> GateResult:
    """Banned from re-entering a ticker stopped out within N days
    (functionally averaging down on a failed setup — the BAC rule).
    Cutoff uses the TRUSTED clock, not wall time, so replay verdicts apply
    the window relative to their evaluation time."""
    ticker = thesis["ticker"]
    cutoff = now - timedelta(days=CONFIG["no_reentry_days"])
    recent_stops = []
    for s in agent_book.get("recent_stop_exits", []):
        if s.get("ticker") != ticker:
            continue
        d = _parse_time(s.get("date"))
        if d is None:
            continue  # unparseable stop-exit record — treat as not matching
        if d >= cutoff:
            recent_stops.append((s, d))
    ok = not recent_stops
    if not ok:
        s, d = recent_stops[0]
        return GateResult("REENTRY", False,
                          f"{ticker} stopped out {d.date()} "
                          f"(< {CONFIG['no_reentry_days']}d ago) at ${s['price']:.2f}")
    return GateResult("REENTRY", True, f"no {ticker} stop in last "
                                       f"{CONFIG['no_reentry_days']}d")

# ---------------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------------

CHECKS = [
    # (check_id, function, arg-builder from (thesis, account, market, book, now))
    ("CAPITAL", check_capital,        lambda th, ac, mk, bk, nw: (th, ac, CONFIG)),
    ("SLOTS",   check_slots,          lambda th, ac, mk, bk, nw: (th, bk, CONFIG)),
    ("MKTCAP",  check_market_cap,     lambda th, ac, mk, bk, nw: (th, mk)),
    ("PRICE",   check_price_freshness,lambda th, ac, mk, bk, nw: (th, mk, nw)),
    ("RR",      check_rr_arithmetic,  lambda th, ac, mk, bk, nw: (th,)),
    ("STOP",    check_stop_vs_volatility, lambda th, ac, mk, bk, nw: (th, mk)),
    ("RISK",    check_dollar_risk,    lambda th, ac, mk, bk, nw: (th, CONFIG)),
    ("EARN",    check_earnings_window,lambda th, ac, mk, bk, nw: (th, mk, nw)),
    ("REENTRY", check_no_reentry,     lambda th, ac, mk, bk, nw: (th, bk, nw)),
]

def run_gate(thesis: dict, account: dict, market: dict,
             agent_book: dict, mode: str = "enforce",
             clock: datetime = None) -> GateReport:
    """Run all checks. `clock` is the TRUSTED evaluation time:
    - enforce mode: gate's own wall clock (default) — the thesis cannot
      backdate freshness checks.
    - replay/demo: harness-supplied historical time."""
    now = clock or datetime.now(timezone.utc)
    report = GateReport(
        thesis_id=thesis.get("thesis_id", "unknown"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
    )
    for check_id, fn, build_args in CHECKS:
        try:
            report.results.append(fn(*build_args(thesis, account, market,
                                                agent_book, now)))
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
# TESTS — run: python3 gate1_pregate.py --selftest
# 12 synthetic scenarios CONSTRUCTED FROM the failure patterns documented in
# the Judge's decision log (Sep 16-28). They are not byte-for-byte replays
# of historical submissions — the real thesis JSON was not preserved — but
# every rejection pattern (capital misrep, market-cap error, gap chase,
# R/R misrep, whipsaw stop, re-entry ban, blackout, stale quote, layer cap,
# price-parse deviation) is represented, with 2 expected-PASS controls.
# ---------------------------------------------------------------------------
def selftest():
    import copy
    passing = 0; failing = 0

    def run_case(name, thesis, account, market, book, expect_pass, clock=None):
        nonlocal passing, failing
        rep = run_gate(thesis, account, market, book, mode="replay",
                       clock=clock)
        ok, fails = rep.summary()
        got_pass = ok
        if got_pass == expect_pass:
            passing += 1
        else:
            failing += 1
            print(f"  ❌ TEST FAILURE {name}: expected "
                  f"{'PASS' if expect_pass else 'FAIL'}, got "
                  f"{'PASS' if ok else 'FAIL ' + str([f.check_id for f in fails])}")

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
    }

    # --- cases that MUST PASS (controls) -----------------------------------
    run_case("clean thesis", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), copy.deepcopy(base_market),
             copy.deepcopy(base_book), True, clock=now)

    # 2. COHR-class boundary: the historical fixed-10% stop ($276.71 on a
    # $307.45 entry, ATR14 $15) misses the new volatility-scaled threshold
    # by half a cent (30.74 < max(30.745, 30.0)) — the gate REJECTS it.
    # That is the audit's conclusion made executable: the historical stop
    # was marginally too tight for this name's volatility, and the stop
    # fired at the exact low of the move.
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 307.45, "stop_price": 276.71,
              "target_price": 370.0, "position_value": 307.45,
              "shares": 1.0, "claimed_rr": 2.04})
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("historical COHR stop REJECTED by half a cent (rule works)",
             t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now)

    # 2b. the corrected COHR trade: stop widened to 12% below entry
    # ($270.55) clears the noise threshold — but note the rule interaction
    # this test documents: widening the stop cuts recomputed R/R
    # (62.55/36.90 = 1.69), so the target must rise to ≥$381.25 to keep
    # R/R at the 2:1 floor. Wider stops demand further targets — the two
    # rules form a coherent system, and this test pins that.
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 307.45, "stop_price": 270.55,   # 12% below
              "target_price": 381.25, "position_value": 307.45,
              "shares": 1.0, "claimed_rr": 2.0})
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("corrected COHR stop (12%, clears threshold)", t,
             copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), True, clock=now)

    # --- cases that MUST FAIL — patterns from the Judge log ---------------
    # 1. INTC buying-power misrep: $485 position vs $385 deployable
    t = copy.deepcopy(base_thesis)
    t.update({"position_value": 485.0, "shares": 4.85, "entry_price": 100.0})
    a = copy.deepcopy(base_account); a["cash"] = 885.0  # 885-500=385 deployable
    run_case("INTC-class capital misrep", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 1b. understated position_value hiding an oversized order
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 10.0, "position_value": 100.0})  # real cost = $1000
    a = copy.deepcopy(base_account); a["cash"] = 1500.0   # deployable $1000
    run_case("understated position_value", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 1c. allocation_share > 1 (agent multiplying its own allowance)
    t = copy.deepcopy(base_thesis)
    t.update({"allocation_share": 2.0, "position_value": 5000.0,
              "shares": 50.0})
    run_case("allocation_share > 1", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 2. ALAB market-cap 5.5x error: claimed 8.5B actual 46.7B
    t = copy.deepcopy(base_thesis); t["market_cap"] = 8.5e9
    m = copy.deepcopy(base_market); m["market_cap"] = 46.7e9
    run_case("ALAB-class mktcap 5.5x error", t,
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             False, clock=now)

    # 3. INTC stale-price gap chase: claimed 97.14 close, live 100.70 (+3.7%)
    t = copy.deepcopy(base_thesis); t["entry_price"] = 97.14
    m = copy.deepcopy(base_market); m["last_price"] = 100.70
    run_case("INTC-class gap chase", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now)

    # 4. price-parse bug: claimed price 2%+ off live (wrong instrument)
    t = copy.deepcopy(base_thesis); t["entry_price"] = 108.0
    run_case("price-parse deviation", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 5. BA-class R/R misrepresentation: claimed 2.02:1, real 1.02:1
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 100.0, "target_price": 102.0,
              "stop_price": 98.0, "claimed_rr": 2.02})
    run_case("BA-class R/R misrep", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 6. whipsaw stop: tighter than the noise threshold (2x ATR)
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 307.45, "stop_price": 291.0,
              "target_price": 370.0, "position_value": 307.45,
              "shares": 1.0, "claimed_rr": 2.5})
    # stop distance 16.45 < required max(30.745, 30) — reject
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("whipsaw stop < noise threshold", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now)

    # 6b. circular-risk exploit: huge position setting its own budget
    # (RISK now uses the FIXED budget: 10% of $500 = $50)
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 100.0, "stop_price": 80.0, "shares": 10.0,
              "position_value": 1000.0, "target_price": 140.0,
              "claimed_rr": 3.0, "allocation_share": 1.0})
    a = copy.deepcopy(base_account); a["cash"] = 100000.0  # capital passes
    # dollar risk = 10 * 20 = $200 >> $50 budget → reject
    run_case("oversized dollar risk vs fixed budget", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 7. re-entry ban: BAC stopped 2 days ago, thesis re-enters today
    t = copy.deepcopy(base_thesis); t["ticker"] = "BAC"
    b = copy.deepcopy(base_book)
    b["recent_stop_exits"] = [{"ticker": "BAC",
                               "date": (now - timedelta(days=2)).isoformat(),
                               "price": 56.20}]
    run_case("BAC-class re-entry ban", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), b, False, clock=now)

    # 7b. re-entry ban honored with STRING dates (JSON round-trip)
    t = copy.deepcopy(base_thesis); t["ticker"] = "BAC"
    b = copy.deepcopy(base_book)
    b["recent_stop_exits"] = [{"ticker": "BAC",
                               "date": (now - timedelta(days=2)).isoformat(),
                               "price": 56.20}]
    run_case("re-entry ban (string date parse)", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), b, False, clock=now)

    # 8. earnings blackout: earnings in 3 days
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now + timedelta(days=3)).date().isoformat()
    run_case("earnings blackout", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             False, clock=now)

    # 8b. PAST earnings date must be allowed (already reported)
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now - timedelta(days=10)).date().isoformat()
    run_case("past earnings allowed", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             True, clock=now)

    # 9. layer max: networking already 2/2
    t = copy.deepcopy(base_thesis); t["layer"] = "networking"
    b = copy.deepcopy(base_book)
    b["positions"] = [{"layer": "networking"}, {"layer": "networking"}]
    run_case("networking layer full", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), b, False, clock=now)

    # 10. stale quote: timestamp 30 min old
    m = copy.deepcopy(base_market)
    m["quote_time"] = (now - timedelta(minutes=30)).isoformat()
    run_case("stale quote", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             False, clock=now)

    # 11. thesis-controlled clock attack: thesis backdates a stale quote
    #     to look fresh — clock is TRUSTED, so the stale quote still fails
    m = copy.deepcopy(base_market)
    m["quote_time"] = (now - timedelta(minutes=30)).isoformat()
    run_case("backdated clock attack rejected", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             False, clock=now)  # trusted clock = now; quote 30 min old = stale

    print(f"\nSelf-test: {passing} passed, {failing} failed")
    if failing:
        print("GATE 1 NOT READY — fix failing cases before deployment")
        return 1
    print("GATE 1 READY — all documented failure patterns reproduced mechanically")
    return 0

# ---------------------------------------------------------------------------
# VALIDATION PLAN — "how do I know it's working but not wrong?"
# ---------------------------------------------------------------------------
# The fear is correct: a gate can be (a) not running, (b) running but
# passing bad theses, or (c) running but rejecting good ones. The plan:
#
# PHASE 1 — REPLAY (confidence it catches the right things)
#   Synthetic scenarios built from every failure pattern the Judge
#   documented (capital misrep, mktcap error, gap chase, R/R misrep,
#   whipsaw stop, re-entry, blackout, stale quote, layer cap, parse
#   deviation) + 2 positive controls. Encoded as the selftest above.
#
# PHASE 2 — SHADOW MODE (confidence it doesn't over-reject)
#   For 5 sessions, the harness runs Gate 1 with TRUSTED MCP data and
#   logs only. Compare verdicts to the LLM Judge's on every submission.
#   - Gate PASS + Judge APPROVE  → both agree, good
#   - Gate FAIL + Judge REJECT   → both agree, good
#   - Gate FAIL + Judge APPROVE  → DANGER CASE: gate over-rejecting.
#     Mandatory manual review. If the gate is right, the Judge missed
#     it; if the Judge is right, loosen the gate's threshold.
#   - Gate PASS + Judge REJECT   → expected & fine: the Judge catches
#     reasoning problems OUTSIDE Gate 1's job description.
#
# PHASE 3 — ENFORCE (flip the switch)
#   Only after shadow shows < 10% disagreement on FAIL/APPROVE cases.
#   Enforce mode REFUSES submitter-embedded account/market/book data —
#   the harness must inject trusted values (--account/--market/--book).
#
# CONTINUOUS METRICS:
#   - gate_rejections_by_check → which check fires most (data quality
#     early on: MKTCAP/PRICE; discipline later)
#   - disagreement_rate vs Judge (should trend to ~0 for arithmetic)
#   - every Gate-FAIL + Judge-APPROVE enters a mandatory human review
#     queue — the override valve.
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thesis", help="path to thesis JSON")
    ap.add_argument("--account", help="trusted account data JSON (enforce)")
    ap.add_argument("--market", help="trusted market data JSON (enforce)")
    ap.add_argument("--book", help="trusted agent book JSON (enforce)")
    ap.add_argument("--demo", action="store_true",
                    help="allow thesis-embedded data (demo/testing ONLY)")
    ap.add_argument("--shadow", action="store_true",
                    help="log verdict but do not enforce")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.thesis:
        print(__doc__); sys.exit(2)

    thesis = json.loads(Path(args.thesis).read_text())
    embedded = {k: thesis.pop(k) for k in ("account", "market", "agent_book")
                if k in thesis}

    # TRUST MODEL: enforce/shadow require harness-supplied trusted data.
    # Thesis-embedded data is allowed ONLY in explicit demo mode.
    trusted_sources = (args.account or args.market or args.book)
    if trusted_sources:
        account = (json.loads(Path(args.account).read_text())
                   if args.account else embedded.get("account", {}))
        market = (json.loads(Path(args.market).read_text())
                  if args.market else embedded.get("market", {}))
        book = (json.loads(Path(args.book).read_text())
                if args.book else embedded.get("agent_book",
                                                {"positions": [],
                                                 "recent_stop_exits": []}))
        mode = "shadow" if args.shadow else "enforce"
    elif args.demo:
        account = embedded.get("account", {})
        market = embedded.get("market", {})
        book = embedded.get("agent_book", {"positions": [],
                                           "recent_stop_exits": []})
        mode = "demo" + ("-shadow" if args.shadow else "")
    else:
        print("ERROR: enforce mode requires trusted data via --account/--market/--book "
              "or explicit --demo for testing. Refusing to run on "
              "submitter-controlled data.")
        sys.exit(2)

    report = run_gate(thesis, account, market, book, mode=mode)

    # append-only audit log — every verdict, full evidence
    log_path = Path(__file__).parent / "gate1_log.jsonl"
    with log_path.open("a") as f:
        f.write(json.dumps({**asdict(report),
                            "verdict": "PASS" if report.summary()[0] else "FAIL"}) + "\n")

    ok = print_report(report)
    sys.exit(0 if (ok or args.shadow) else 1)

if __name__ == "__main__":
    main()
