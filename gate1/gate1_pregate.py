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
import math
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIG — tuned to the arena's rulebook (Arena v5.1, Oct 24 2026)
# ---------------------------------------------------------------------------
CONFIG = {
    "max_positions": 4,               # v5 (Oct 22 2026): 3 event bets + 1 QQQ core
    "per_layer_max": 2,               # max positions per architecture layer
    "deployable_reserve": 50.0,       # v5: no strategic reserve (10% core / 90% bets); $50 fee buffer
    "min_rr": 2.0,                    # risk/reward floor (Judge's standard)
    "price_freshness_seconds": 300,   # quote older than 5 min = stale
    "premarket_gap_pct": 1.5,         # live price > entry price by this = gap chase
    "stop_atr_multiple": 2.0,         # v5: stop distance = 2x ATR14 (anti-whipsaw) ...
    "stop_floor_pct": 0.05,           # ... FLOOR 5% below entry (v5; was 10% pre-v5)
    "stop_cap_pct": 0.20,             # ... CAP 20% below entry
    "entry_price_sanity_pct": 0.02,   # thesis price vs live quote tolerance ±2%
    "position_value_tolerance": 0.02, # position_value vs shares×entry tolerance ±2%
    "max_position_value": 2900.0,     # v5.1 (Oct 23 2026): 30% of ~$9.7K equity (was $1,500 v5; $750 since 2026-09-28)
    "risk_budget": 290.0,             # v5.1: max dollar risk per trade = 3% of equity (~$9,676 → $290).
                                      # RECOMPUTE as 3% of CURRENT equity; decoupled from stop_floor_pct.
    "earnings_hold_window_days": 45,  # v5: earnings within this many CALENDAR days (~30 trading days =
                                      # the max catalyst hold) are "inside the hold" → gap-sized, not blacked out
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
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    # naive timestamps are treated as UTC (same rule as REENTRY records), so
    # aware-vs-naive subtraction can never crash a check
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _parse_date(v):
    """Accept date, datetime, or ISO string → date, else None."""
    dt = _parse_time(v)
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    return dt.astimezone(timezone.utc).date() if dt else None

# ---------------------------------------------------------------------------
# CHECKS — every one is deterministic: number vs number.
# ---------------------------------------------------------------------------

POSITIVE_FIELDS = ("shares", "entry_price", "target_price", "stop_price",
                   "position_value")

def check_inputs(thesis) -> GateResult:
    """Fail closed on malformed numbers: zero/negative/NaN/inf share counts or
    prices would otherwise make CAPITAL/RISK/EARN compare a non-positive
    number against a positive budget and pass."""
    bad = []
    for k in POSITIVE_FIELDS:
        v = thesis.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(v) or v <= 0:
            bad.append(f"{k}={v!r}")
    if bad:
        return GateResult("INPUT", False,
                          "non-positive or non-numeric field(s): " + ", ".join(bad))
    return GateResult("INPUT", True, "all sizing/price fields finite and > 0")

def check_capital(thesis, account, config) -> GateResult:
    """Deployable capital check — catches the INTC $3,377 vs $385 error.

    Verified order cost = shares x entry_price (recomputed from first
    principles). A materially understated position_value cannot enlarge
    the permitted purchase. allocation_share comes from the TRUSTED account
    payload (never the thesis) and is bounded to (0, 1] — an
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
    # Trusted source only: a thesis cannot set its own share of shared cash.
    # Default 1.0 = the whole account belongs to one agent (Arena v5: Beta is
    # the sole agent since Oct 22 2026); a multi-agent harness must supply it.
    share = account.get("allocation_share", 1.0)
    if not (0.0 < share <= 1.0):
        return GateResult(
            "CAPITAL", False,
            f"allocation_share {share} outside (0, 1] — cannot exceed "
            f"the agent's own allocation",
        )
    shared_cash = account["cash"]                    # whole account cash
    reserve = config["deployable_reserve"]
    deployable = max(0.0, shared_cash - reserve) * share
    # (c) per-trade position cap (v5.1: 30% of equity)
    cap = config["max_position_value"]
    if order_cost > cap * 1.001:
        return GateResult(
            "CAPITAL", False,
            f"verified order cost ${order_cost:,.2f} exceeds per-trade cap "
            f"${cap:,.2f}",
            claimed=f"${claimed_position_value:,.2f}",
            verified=f"${order_cost:,.2f} (shares×entry)",
        )
    # (d) VERIFIED order cost (not the claimed value) must fit
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
    known = [k.lower() for k in config["known_layers"]]
    if layer not in known:
        return GateResult("SLOTS", False,
                          f"layer '{layer}' not one of {', '.join(known)}")
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
    if age < -60:
        return GateResult("PRICE", False,
                          f"quote timestamp {-age:.0f}s in the future — bad source clock")
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
    claimed_rr = thesis.get("claimed_rr")
    if claimed_rr is None:          # absent or JSON null = no claim to verify
        claimed_rr = rr
    elif isinstance(claimed_rr, bool) or not isinstance(claimed_rr, (int, float)):
        return GateResult("RR", False, f"claimed_rr {claimed_rr!r} is not a number")
    ok = rr >= CONFIG["min_rr"]
    # one-sided: only OVERstating the edge is misrepresentation (BA claimed
    # 2.02, real 1.02); a conservative claim below the real R/R is honest
    honest = claimed_rr <= rr * 1.05  # 5% tolerance
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

    v5 rule: stop distance = 2 x ATR14, FLOOR 5% and CAP 20% below entry.
    Required minimum distance = clamp(2·ATR, 5% of entry, 20% of entry);
    the stop may sit wider than that minimum but never beyond the 20% cap.
    Dollar risk is held constant by the RISK check below.
    """
    eps = 1e-9  # float grace so an exact 2·ATR stop (e.g. 14.22) isn't lost to rounding
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    atr = market.get("atr14")
    actual_distance = entry - stop
    pct_distance = actual_distance / entry
    if actual_distance <= 0:
        return GateResult("STOP", False, f"stop ${stop} >= entry ${entry}")
    floor_distance = entry * CONFIG["stop_floor_pct"]     # 5% of entry
    cap_distance = entry * CONFIG["stop_cap_pct"]         # 20% of entry
    cent = 0.01  # prices are quoted in cents: a stop AT the cap must be placeable
    within_cap = actual_distance <= cap_distance + cent
    if not atr or atr <= 0:
        # fail closed (like MKTCAP / EARN): the 2·ATR rule is this check's
        # whole purpose, so missing trusted ATR is a data failure, not a pass
        return GateResult("STOP", False,
                          f"no ATR14 from data source — cannot verify the 2·ATR "
                          f"stop (dist {pct_distance*100:.2f}%)")
    atr_distance = CONFIG["stop_atr_multiple"] * atr      # 2 x ATR14
    min_stop_distance = min(max(floor_distance, atr_distance), cap_distance)
    tol = cent if min_stop_distance == cap_distance else eps
    ok = actual_distance >= min_stop_distance - tol and within_cap
    reason = ""
    if actual_distance < min_stop_distance - tol:
        if min_stop_distance == floor_distance:
            reason = " — below 5% floor"
        elif min_stop_distance == cap_distance:
            reason = " — 2·ATR exceeds 20% cap; stop must sit at the cap"
        else:
            reason = " — inside 2·ATR noise"
    elif not within_cap:
        reason = " — beyond 20% cap"
    return GateResult(
        "STOP", ok,
        f"stop ${stop:.2f} = {pct_distance*100:.2f}% below entry "
        f"(required ≥ clamp(2·ATR ${atr_distance:.2f}, 5% floor "
        f"${floor_distance:.2f}, 20% cap ${cap_distance:.2f}) = "
        f"${min_stop_distance:.2f}, ≤ cap){reason}",
    )

def check_dollar_risk(thesis, config) -> GateResult:
    """Anti-whipsaw companion: wider stop ⇒ smaller size, SAME dollar risk.

    The risk budget is a FIXED, explicit CONFIG value (v5.1: 3% of equity,
    `risk_budget`) — it is NOT derived from the proposed shares (circular:
    a bigger position would inflate its own budget) and NOT coupled to the
    stop floor (a 5% floor must not halve the budget).
    """
    shares = thesis["shares"]
    entry = thesis["entry_price"]
    stop = thesis["stop_price"]
    dollar_risk = shares * (entry - stop)
    risk_budget = config["risk_budget"]
    ok = dollar_risk <= risk_budget * 1.001
    return GateResult(
        "RISK", ok,
        f"dollar risk ${dollar_risk:.2f} vs budget "
        f"${risk_budget:.2f} (3% of equity)",
    )

def check_earnings_window(thesis, market, now, config=None) -> GateResult:
    """v5: NO pre-earnings blackout (earnings are valid event bets), but
    when earnings fall inside the hold window the position must be sized
    for the gap:
        shares x max(stop distance/share, entry x implied_move_pct/100)
            <= risk_budget (3% of equity)
    `implied_move_pct` (options-implied earnings move, %) must come from
    the trusted market data; if earnings are inside the hold and it is
    missing, FAIL — the gap cannot be sized. Earnings dates in the PAST
    are allowed through (already reported). Earnings TODAY count as inside
    the hold unless trusted market data sets `earnings_reported: true`
    (e.g. a BMO print) — an after-close report is the highest gap risk."""
    edate = _parse_date(market.get("earnings_date"))
    if edate is None:
        return GateResult("EARN", True, "no earnings date on file")
    today = now.date()
    days = (edate - today).days
    window = CONFIG["earnings_hold_window_days"]
    if days < 0 or (days == 0 and market.get("earnings_reported") is True):
        return GateResult("EARN", True,
                          f"earnings already reported ({abs(days)}d ago)")
    if days > window:
        return GateResult("EARN", True,
                          f"earnings {days} days out (beyond {window}d hold window)")
    # earnings today (not yet reported) or ahead, inside the hold → gap sizing
    implied = market.get("implied_move_pct")
    if implied is None or implied <= 0:
        return GateResult("EARN", False,
                          f"earnings inside hold: implied move required for "
                          f"gap sizing (earnings in {days}d)")
    shares = thesis["shares"]
    entry = thesis["entry_price"]
    stop_dist = entry - thesis["stop_price"]
    implied_dist = entry * implied / 100.0
    per_share = max(stop_dist, implied_dist)
    gap_risk = shares * per_share
    budget = (config or CONFIG)["risk_budget"]
    ok = gap_risk <= budget * 1.001
    return GateResult(
        "EARN", ok,
        f"earnings in {days}d inside hold; gap risk {shares:g} sh × "
        f"max(stop ${stop_dist:.2f}, implied {implied:g}% ${implied_dist:.2f}) "
        f"= ${gap_risk:.2f} vs budget ${budget:.2f}"
        + ("" if ok else " — oversized for earnings gap"),
    )

def check_no_reentry(thesis, agent_book, now) -> GateResult:
    """Banned from re-entering a ticker stopped out within N days
    (functionally averaging down on a failed setup — the BAC rule).
    Cutoff uses the TRUSTED clock, not wall time, so replay verdicts apply
    the window relative to their evaluation time."""
    ticker = str(thesis["ticker"]).strip().upper()
    cutoff = now - timedelta(days=CONFIG["no_reentry_days"])
    recent_stops = []
    for s in agent_book.get("recent_stop_exits", []):
        if str(s.get("ticker", "")).strip().upper() != ticker:
            continue
        d = _parse_time(s.get("date"))
        if d is None:
            continue  # unparseable stop-exit record — treat as not matching
        if d.tzinfo is None:  # date-only / naive record → treat as UTC (Rocky fix Oct 24 2026)
            d = d.replace(tzinfo=timezone.utc)
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
    ("INPUT",   check_inputs,         lambda th, ac, mk, bk, nw, cf: (th,)),
    ("CAPITAL", check_capital,        lambda th, ac, mk, bk, nw, cf: (th, ac, cf)),
    ("SLOTS",   check_slots,          lambda th, ac, mk, bk, nw, cf: (th, bk, cf)),
    ("MKTCAP",  check_market_cap,     lambda th, ac, mk, bk, nw, cf: (th, mk)),
    ("PRICE",   check_price_freshness,lambda th, ac, mk, bk, nw, cf: (th, mk, nw)),
    ("RR",      check_rr_arithmetic,  lambda th, ac, mk, bk, nw, cf: (th,)),
    ("STOP",    check_stop_vs_volatility, lambda th, ac, mk, bk, nw, cf: (th, mk)),
    ("RISK",    check_dollar_risk,    lambda th, ac, mk, bk, nw, cf: (th, cf)),
    ("EARN",    check_earnings_window,lambda th, ac, mk, bk, nw, cf: (th, mk, nw, cf)),
    ("REENTRY", check_no_reentry,     lambda th, ac, mk, bk, nw, cf: (th, bk, nw)),
]

def effective_config(account) -> dict:
    """Equity-relative limits (v5.1): position cap = 30% and risk budget = 3%
    of CURRENT equity when the trusted account payload carries `equity`;
    otherwise the CONFIG constants (set at ~$9.7K equity) apply."""
    cfg = dict(CONFIG)
    acct = account or {}
    eq = acct.get("equity")
    if isinstance(eq, (int, float)) and not isinstance(eq, bool) \
            and math.isfinite(eq) and eq > 0:
        share = acct.get("allocation_share", 1.0)
        if isinstance(share, (int, float)) and 0.0 < share <= 1.0:
            eq = eq * share  # limits apply to THIS agent's slice of the account
        cfg["max_position_value"] = round(0.30 * eq, 2)
        cfg["risk_budget"] = round(0.03 * eq, 2)
    return cfg

def run_gate(thesis: dict, account: dict, market: dict,
             agent_book: dict, mode: str = "enforce",
             clock: datetime = None) -> GateReport:
    """Run all checks. `clock` is the TRUSTED evaluation time:
    - enforce mode: gate's own wall clock (default) — the thesis cannot
      backdate freshness checks.
    - replay/demo: harness-supplied historical time."""
    now = clock or datetime.now(timezone.utc)
    cfg = effective_config(account)
    report = GateReport(
        thesis_id=thesis.get("thesis_id", "unknown"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode=mode,
    )
    for check_id, fn, build_args in CHECKS:
        try:
            report.results.append(fn(*build_args(thesis, account, market,
                                                agent_book, now, cfg)))
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
# Synthetic scenarios CONSTRUCTED FROM the failure patterns documented in
# the Judge's decision log (Sep 16-28), plus v5.1 rule cases (Oct 24 2026).
# They are not byte-for-byte replays of historical submissions — the real
# thesis JSON was not preserved (except the AMZN Oct 23 replay) — but
# every rejection pattern (capital misrep, market-cap error, gap chase,
# R/R misrep, whipsaw stop, 5% stop floor / 20% cap, re-entry ban,
# earnings gap sizing, stale quote, layer cap, price-parse deviation) is
# represented, with expected-PASS controls.
# ---------------------------------------------------------------------------
def selftest():
    import copy
    passing = 0; failing = 0

    def run_case(name, thesis, account, market, book, expect_pass, clock=None,
                 expect_fail_ids=None):
        """expect_fail_ids (optional): exact set of check_ids that must FAIL
        (pins WHICH rule fired, not just the overall verdict)."""
        nonlocal passing, failing
        rep = run_gate(thesis, account, market, book, mode="replay",
                       clock=clock)
        ok, fails = rep.summary()
        got_pass = ok
        fail_ids = {f.check_id for f in fails}
        ids_ok = (expect_fail_ids is None or fail_ids == set(expect_fail_ids))
        if got_pass == expect_pass and ids_ok:
            passing += 1
        else:
            failing += 1
            print(f"  ❌ TEST FAILURE {name}: expected "
                  f"{'PASS' if expect_pass else 'FAIL'}"
                  + (f" {sorted(expect_fail_ids)}" if expect_fail_ids else "")
                  + f", got "
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

    # 2. COHR-class stop under v5: the historical fixed-10% stop ($276.71 on
    # a $307.45 entry, ATR14 $15). Pre-v5 this was REJECTED by half a cent
    # (30.74 < max(10% floor 30.745, 2·ATR 30.0)). Under v5 the binding
    # requirement is 2·ATR = $30.00 (5% floor $15.37 is looser), so the
    # $30.74 stop now CLEARS the noise threshold — the gate PASSES it.
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 307.45, "stop_price": 276.71,
              "target_price": 370.0, "position_value": 307.45,
              "shares": 1.0, "claimed_rr": 2.04})
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("historical COHR stop clears v5 2·ATR (30.74 ≥ 30.00)",
             t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), True, clock=now)

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
    a = copy.deepcopy(base_account); a["cash"] = 435.0  # v5: 435-50=385 deployable (was 885-500)
    run_case("INTC-class capital misrep", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 1b. understated position_value hiding an oversized order
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 10.0, "position_value": 100.0})  # real cost = $1000
    a = copy.deepcopy(base_account); a["cash"] = 1500.0   # deployable $1000
    run_case("understated position_value", t, a,
             copy.deepcopy(base_market), copy.deepcopy(base_book), False, clock=now)

    # 1c. allocation_share > 1 in the trusted account payload is invalid
    t = copy.deepcopy(base_thesis)
    t.update({"position_value": 2800.0, "shares": 28.0})
    run_case("allocation_share > 1", t, {"cash": 9000.0, "allocation_share": 2.0},
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"CAPITAL"})

    # 1d. shared-cash misrep: the THESIS claims the whole account (share 1.0)
    # but the trusted account says this agent owns 30% → deployable $2,685 <
    # $2,800 order. The thesis value must be ignored.
    t = copy.deepcopy(base_thesis)
    t.update({"position_value": 2800.0, "shares": 28.0, "allocation_share": 1.0})
    run_case("thesis cannot claim shared cash (trusted share 0.3)", t,
             {"cash": 9000.0, "allocation_share": 0.3},
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"CAPITAL"})

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
    # stop distance 16.45 < required 2·ATR $30.00 (5% floor $15.37 looser) — reject
    m = copy.deepcopy(base_market); m.update({"last_price": 307.45, "atr14": 15.0})
    run_case("whipsaw stop < noise threshold", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now)

    # 6b. circular-risk exploit: huge position setting its own budget
    # (RISK uses the FIXED CONFIG risk_budget: 3% of equity = $290 in v5.1)
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 100.0, "stop_price": 80.0, "shares": 20.0,
              "position_value": 2000.0, "target_price": 140.0,
              "claimed_rr": 3.0, "allocation_share": 1.0})
    a = copy.deepcopy(base_account); a["cash"] = 100000.0  # capital passes
    # dollar risk = 20 * 20 = $400 > $290 budget → reject (v5.1 fixture)
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

    # 8. earnings inside the hold (3 days out): v5 lifted the blackout, so
    # this tests GAP SIZING instead. 25 sh, $10 stop → stop risk $250 passes
    # RISK, but implied move 15% → 25 × max($10, $15) = $375 > $290 → EARN fail.
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 25.0, "position_value": 2500.0})
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now + timedelta(days=3)).date().isoformat()
    m["implied_move_pct"] = 15.0
    run_case("earnings gap oversized vs risk budget", t,
             copy.deepcopy(base_account), m, copy.deepcopy(base_book),
             False, clock=now, expect_fail_ids={"EARN"})

    # 8a. earnings inside the hold with NO implied move → cannot size gap
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now + timedelta(days=3)).date().isoformat()
    run_case("earnings inside hold, implied move missing",
             copy.deepcopy(base_thesis), copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now,
             expect_fail_ids={"EARN"})

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

    # --- v5.1 rule cases (Oct 24 2026) ------------------------------------
    # (a) AMZN Oct 23 replay — v5-legal, Judge 3/3 approved: 11 sh @ $248.64,
    # stop $234.42 = exactly 2·ATR14 ($7.11) = 5.72%, earnings 6d out (Oct 29
    # AMC), options-implied move 7.7%. Gap risk 11 × max($14.22, $19.15) =
    # $210.59 ≤ $290. Must PASS (pre-v5 gate wrongly failed STOP + EARN).
    amzn_thesis = {
        "thesis_id": "AMZN-2026-10-23", "ticker": "AMZN", "shares": 11,
        "entry_price": 248.64, "position_value": 2735.04,
        "target_price": 280.0, "stop_price": 234.42, "layer": "compute",
        "market_cap": 2.66e12, "claimed_rr": 2.2,
    }
    amzn_market = {"last_price": 248.64, "quote_time": fresh,
                   "market_cap": 2.66e12, "atr14": 7.11,
                   "earnings_date": (now + timedelta(days=6)).date().isoformat(),
                   "implied_move_pct": 7.7}
    amzn_account = {"cash": 8931.58}
    amzn_book = {"positions": [{"ticker": "CIEN", "layer": "networking"},
                               {"ticker": "VST", "layer": "power"}],
                 "recent_stop_exits": []}
    run_case("v5 AMZN Oct 23 replay (2·ATR stop, gap-sized earnings)",
             copy.deepcopy(amzn_thesis), copy.deepcopy(amzn_account),
             copy.deepcopy(amzn_market), copy.deepcopy(amzn_book), True,
             clock=now)

    # (b) same trade at 30 sh: $7,459 > $2,900 cap (CAPITAL), stop risk
    # 30 × $14.22 = $426.60 > $290 (RISK) and gap risk 30 × $19.15 =
    # $574.38 > $290 (EARN) — all three fire.
    t = copy.deepcopy(amzn_thesis)
    t.update({"shares": 30, "position_value": 30 * 248.64})
    run_case("v5 AMZN 30 sh oversized for earnings gap", t,
             copy.deepcopy(amzn_account), copy.deepcopy(amzn_market),
             copy.deepcopy(amzn_book), False, clock=now,
             expect_fail_ids={"CAPITAL", "RISK", "EARN"})

    # (b2) isolates the GAP rule inside the $2,900 cap: the replay's 11 sh
    # with a 12% implied move — stop risk $156.42 passes RISK, but gap risk
    # 11 × $29.84 = $328.20 > $290 → EARN only.
    m = copy.deepcopy(amzn_market); m["implied_move_pct"] = 12.0
    run_case("v5 AMZN 11 sh, 12% implied move: gap sizing binds", 
             copy.deepcopy(amzn_thesis), copy.deepcopy(amzn_account), m,
             copy.deepcopy(amzn_book), False, clock=now,
             expect_fail_ids={"EARN"})

    # (c) stop 4% below entry with low ATR (2·ATR = 3%) → below 5% floor
    t = copy.deepcopy(base_thesis)
    t.update({"stop_price": 96.0, "target_price": 108.0, "claimed_rr": 2.0})
    m = copy.deepcopy(base_market); m["atr14"] = 1.5
    run_case("v5 stop 4% < 5% floor", t, copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now,
             expect_fail_ids={"STOP"})

    # (c2) control: same low-ATR name, stop exactly at the 5% floor → PASS
    t = copy.deepcopy(base_thesis)
    t.update({"stop_price": 95.0, "target_price": 110.0, "claimed_rr": 2.0})
    m = copy.deepcopy(base_market); m["atr14"] = 1.5
    run_case("v5 stop exactly at 5% floor passes", t,
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), True,
             clock=now)

    # (d) stop 21% below entry → beyond the 20% cap
    t = copy.deepcopy(base_thesis)
    t.update({"stop_price": 79.0, "target_price": 142.0, "claimed_rr": 2.0})
    run_case("v5 stop 21% > 20% cap", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"STOP"})

    # --- review fixes (Oct 26 2026) ----------------------------------------
    # INPUT: negative / zero shares used to pass CAPITAL, RISK and EARN
    for label, sh in (("negative", -50.0), ("zero", 0.0)):
        t = copy.deepcopy(base_thesis)
        t.update({"shares": sh, "position_value": sh * 100.0})
        run_case(f"{label} shares rejected (INPUT)", t,
                 copy.deepcopy(base_account), copy.deepcopy(base_market),
                 copy.deepcopy(base_book), False, clock=now,
                 expect_fail_ids={"INPUT"})
    # CAPITAL: $3,600 position (36 sh, 8% stop, $288 risk) with $9K cash —
    # inside the risk budget but over the $2,900 per-trade cap
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 36.0, "position_value": 3600.0, "stop_price": 92.0,
              "target_price": 116.0, "claimed_rr": 2.0})
    run_case("position over $2,900 cap (CAPITAL)", t, {"cash": 9000.0},
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"CAPITAL"})
    # SLOTS: layer must be a known architecture layer
    t = copy.deepcopy(base_thesis); t["layer"] = "crypto-lol"
    run_case("unknown layer rejected (SLOTS)", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"SLOTS"})
    # EARN: earnings TODAY (after-close) with no implied move → cannot size gap
    m = copy.deepcopy(base_market); m["earnings_date"] = now.date().isoformat()
    run_case("earnings today, no implied move (EARN)", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"EARN"})
    # control: same, but trusted data says the report already printed (BMO)
    m["earnings_reported"] = True
    run_case("earnings today, already reported → PASS", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), True,
             clock=now)
    # STOP: 2·ATR beyond the 20% cap — a cent-rounded stop AT the cap passes
    t = copy.deepcopy(base_thesis)
    t.update({"entry_price": 248.64, "position_value": 248.64,
              "stop_price": 198.91, "target_price": 348.20, "claimed_rr": 2.0})
    m = copy.deepcopy(base_market); m.update({"last_price": 248.64, "atr14": 30.0})
    run_case("stop at 20% cap, cent-rounded (STOP) → PASS", t,
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), True,
             clock=now)
    # PRICE: quote timestamped 10 min in the future = bad source clock
    m = copy.deepcopy(base_market); m["quote_time"] = now + timedelta(minutes=10)
    run_case("future quote timestamp (PRICE)", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"PRICE"})

    # PRICE: a timezone-naive quote timestamp (UTC) must not crash the check
    m = copy.deepcopy(base_market)
    m["quote_time"] = fresh.replace(tzinfo=None).isoformat()
    run_case("naive UTC quote timestamp → PASS (no crash)", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), True, clock=now)

    # REENTRY: ticker casing/whitespace cannot evade the ban
    t = copy.deepcopy(base_thesis); t["ticker"] = " bac "
    b = copy.deepcopy(base_book)
    b["recent_stop_exits"] = [{"ticker": "BAC",
                               "date": (now - timedelta(days=2)).isoformat(),
                               "price": 56.20}]
    run_case("re-entry ban not evaded by ' bac ' casing", t,
             copy.deepcopy(base_account), copy.deepcopy(base_market), b, False,
             clock=now, expect_fail_ids={"REENTRY"})
    # STOP: no ATR from the source fails closed
    m = copy.deepcopy(base_market); m["atr14"] = None
    run_case("no ATR14 → STOP fails closed", copy.deepcopy(base_thesis),
             copy.deepcopy(base_account), m, copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"STOP"})
    # equity-relative limits: $5,000 position, $400 risk
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 50.0, "position_value": 5000.0, "stop_price": 92.0,
              "target_price": 116.0, "claimed_rr": 2.0})
    run_case("equity $20K → cap $6,000 / risk $600 → PASS", t,
             {"cash": 9000.0, "equity": 20000.0}, copy.deepcopy(base_market),
             copy.deepcopy(base_book), True, clock=now)
    run_case("no equity → $2,900 / $290 constants → FAIL", copy.deepcopy(t),
             {"cash": 9000.0}, copy.deepcopy(base_market),
             copy.deepcopy(base_book), False, clock=now,
             expect_fail_ids={"CAPITAL", "RISK"})
    # EARN: offset-aware earnings datetime normalised to UTC (inside hold)
    m = copy.deepcopy(base_market)
    m["earnings_date"] = (now + timedelta(days=3)).astimezone(
        timezone(timedelta(hours=-4))).isoformat()
    run_case("tz-aware earnings in 3d, no implied move (EARN)",
             copy.deepcopy(base_thesis), copy.deepcopy(base_account), m,
             copy.deepcopy(base_book), False, clock=now, expect_fail_ids={"EARN"})

    # RR: a conservative claim (2.0 vs real 2.5) is honest, not misrepresentation
    t = copy.deepcopy(base_thesis); t.update({"target_price": 125.0, "claimed_rr": 2.0})
    run_case("understated R/R (2.0 claimed, 2.5 real) → PASS", t,
             copy.deepcopy(base_account), copy.deepcopy(base_market),
             copy.deepcopy(base_book), True, clock=now)
    # equity limits scale by allocation_share: agent slice $6K → cap $1,800,
    # risk budget $180. $1,500 position inside the cap; risk 15 × $13 = $195.
    t = copy.deepcopy(base_thesis)
    t.update({"shares": 15.0, "position_value": 1500.0, "stop_price": 87.0,
              "target_price": 126.0, "claimed_rr": 2.0})
    run_case("equity × allocation_share: $195 risk > $180 budget (RISK)", t,
             {"cash": 9000.0, "equity": 20000.0, "allocation_share": 0.3},
             copy.deepcopy(base_market), copy.deepcopy(base_book), False,
             clock=now, expect_fail_ids={"RISK"})

    # RR: claimed_rr null = no claim (recomputed ratio still enforced)
    t = copy.deepcopy(base_thesis); t["claimed_rr"] = None
    run_case("claimed_rr null → PASS (no crash)", t, copy.deepcopy(base_account),
             copy.deepcopy(base_market), copy.deepcopy(base_book), True, clock=now)

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
#   whipsaw stop, re-entry, earnings gap sizing, stale quote, layer cap, parse
#   deviation) + positive controls + v5.1 rule cases. Encoded as the selftest above.
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
    supplied = [f for f in ("account", "market", "book") if getattr(args, f)]
    if supplied and len(supplied) < 3:
        missing = sorted({"account", "market", "book"} - set(supplied))
        print("ERROR: enforce/shadow mode needs ALL trusted sources; missing "
              + ", ".join("--" + m for m in missing)
              + ". Refusing to fall back to submitter-embedded data.")
        sys.exit(2)
    if supplied:
        account = json.loads(Path(args.account).read_text())
        market = json.loads(Path(args.market).read_text())
        book = json.loads(Path(args.book).read_text())
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
