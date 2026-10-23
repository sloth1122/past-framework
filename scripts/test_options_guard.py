#!/usr/bin/env python3
"""Self-test for options_guard.check (no network, no ledger writes)."""
import sys
from datetime import date
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import options_guard as g

g.month_used = lambda today=None: 0.0          # isolate from the real ledger
T = date(2026, 10, 23)
base = {"account": "XXXX", "ticker": "AMD", "quantity": 1, "type": "limit", "price": 2.40,
        "equity": 9692.16, "open_bets": 2, "catalyst_date": "2026-11-03"}
call = lambda k, s, e="2026-11-20": {"option_type": "call", "strike": k, "expiration": e, "side": s, "position_effect": "open"}
put = lambda k, s, e="2026-11-20": {"option_type": "put", "strike": k, "expiration": e, "side": s, "position_effect": "open"}

cases = [
    ("long call ok", {**base, "legs": [call(250, "buy")]}, True),
    ("call debit spread ok", {**base, "direction": "debit", "legs": [call(250, "buy"), call(270, "sell")]}, True),
    ("put debit spread ok", {**base, "direction": "debit", "legs": [put(220, "buy"), put(200, "sell")]}, True),
    ("naked short call", {**base, "legs": [call(250, "sell")]}, False),
    ("naked short put", {**base, "legs": [put(220, "sell")]}, False),
    ("credit call spread (strikes inverted)", {**base, "direction": "debit", "legs": [call(270, "buy"), call(250, "sell")]}, False),
    ("credit direction", {**base, "direction": "credit", "legs": [call(250, "buy"), call(270, "sell")]}, False),
    ("calendar (diff expiry)", {**base, "direction": "debit", "legs": [call(250, "buy", "2026-12-18"), call(250, "sell")]}, False),
    ("over 3% risk", {**base, "price": 3.00, "legs": [call(250, "buy")]}, False),
    ("6 contracts", {**base, "quantity": 6, "price": 0.40, "legs": [call(250, "buy")]}, False),
    ("4th bet", {**base, "open_bets": 3, "legs": [call(250, "buy")]}, False),
    ("expiry before catalyst+7", {**base, "legs": [call(250, "buy", "2026-11-06")]}, False),
    ("market order", {**base, "type": "market", "legs": [call(250, "buy")]}, False),
    ("wrong account", {**base, "account": "0000", "legs": [call(250, "buy")]}, False),
    ("SPCX", {**base, "ticker": "SPCX", "legs": [call(250, "buy")]}, False),
    ("exit always allowed", {**base, "open_bets": 9, "price": 9.0, "direction": "credit",
                             "legs": [{**call(250, "sell"), "position_effect": "close"}, {**call(270, "buy"), "position_effect": "close"}]}, True),
    ("capitol spread 120d ok", {**base, "setup": "capitol_cluster", "filing_date": "2026-10-15", "direction": "debit",
                                "legs": [call(250, "buy", "2027-02-19"), call(270, "sell", "2027-02-19")]}, True),
    ("capitol single leg", {**base, "setup": "capitol_cluster", "filing_date": "2026-10-15",
                            "legs": [call(250, "buy", "2027-02-19")]}, False),
    ("capitol 60d too short", {**base, "setup": "capitol_cluster", "filing_date": "2026-10-15", "direction": "debit",
                               "legs": [call(250, "buy", "2026-12-18"), call(270, "sell", "2026-12-18")]}, False),
    ("capitol stale filing", {**base, "setup": "capitol_cluster", "filing_date": "2026-08-01", "direction": "debit",
                              "legs": [call(250, "buy", "2027-02-19"), call(270, "sell", "2027-02-19")]}, False),
]
fails = 0
for name, o, want in cases:
    errs = g.check(o, today=T)
    ok = (not errs) == want
    fails += not ok
    print(("✓" if ok else "✗"), name, "" if ok else f"→ {errs}")
# monthly cap
g.month_used = lambda today=None: 1300.0
errs = g.check({**base, "legs": [call(250, "buy")]}, today=T)
ok = any("monthly" in e for e in errs); fails += not ok
print(("✓" if ok else "✗"), "monthly $1,500 cap")
print(f"\n{len(cases)+1-fails}/{len(cases)+1} passed")
sys.exit(1 if fails else 0)
