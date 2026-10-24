#!/usr/bin/env python3
"""Options guard for Agent Beta (Arena v5.1, enabled by John Oct 23 2026).

Code-level gate that EVERY option order must pass before review_option_order /
place_option_order. Pure Python, no network. Beta writes the proposed order as
JSON and runs:

  options_guard.py check  --order order.json      → PASS (exit 0) / BLOCK (exit 2)
  options_guard.py record --order order.json --fill-price 2.35   (after an OPENING fill)
  options_guard.py month                           → premium used this month

order.json:
{
  "account": "XXXX", "ticker": "AMD", "quantity": 1, "type": "limit",
  "price": 2.40,                      # per-share net debit (limit); x100 per contract
  "direction": "debit",               # required for 2 legs; omit/"debit" for 1 leg
  "equity": 9692.16,                  # current account equity (from broker, this session)
  "open_bets": 2,                     # event bets already open (stock + options)
  "catalyst_date": "2026-11-03",      # dated catalyst (opening orders)
  "legs": [ {"option_type": "call", "strike": 250, "expiration": "2026-11-21",
             "side": "buy", "position_effect": "open"}, ... ]
}

Rules (opening orders): buy-only single leg OR a 2-leg DEBIT vertical (same type,
same expiry; call: long strike < short strike; put: long strike > short strike);
ratio_quantity 1 on every leg (no ratio spreads/backspreads);
limit orders only; max loss (= debit x 100 x qty) <= 3% of equity; monthly new
premium <= $1,500; <= 5 contracts; expiry 7..60 calendar days after the catalyst
and <= 90 days out; <= 3 open event bets incl. this one; no SPCX; arena account
only (last 4 from env ARENA_ACCOUNT_LAST4 or untracked state/arena_account_last4 —
unset = every order BLOCKs).
Closing orders (position_effect "close" on every leg) always pass the structure
check — exiting risk is never blocked.
"""
import argparse, json, sys
from datetime import date
from pathlib import Path

from arena_account import arena_account_last4

LEDGER = Path("/Users/johntytko/trading-arena/state/options_premium.jsonl")
MONTHLY_CAP = 1500.0
RISK_PCT = 0.03
MAX_CONTRACTS = 5
MAX_BETS = 3
BLOCKLIST = {"SPCX"}


def month_used(today=None):
    today = today or date.today()
    if not LEDGER.exists():
        return 0.0
    tot = 0.0
    for l in LEDGER.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["date"][:7] == today.isoformat()[:7]:
            tot += float(r["premium_usd"])
    return tot


def check(o, today=None):
    today = today or date.today()
    errs = []
    legs = o.get("legs") or []
    account = arena_account_last4()
    if not account:   # fail closed: an unverifiable account never passes
        errs.append("arena account not configured (set ARENA_ACCOUNT_LAST4 or state/arena_account_last4)")
    elif str(o.get("account")) != account:
        errs.append("account must be the arena account")
    if str(o.get("ticker", "")).upper() in BLOCKLIST:
        errs.append("ticker is blocklisted")
    if o.get("type", "limit") != "limit":
        errs.append("limit orders only")
    if not 1 <= len(legs) <= 2:
        errs.append("1 or 2 legs only")
        return errs
    qty = int(o.get("quantity", 0))
    if qty < 1:
        errs.append("quantity must be ≥ 1")
    effects = {l.get("position_effect") for l in legs}
    if effects == {"close"}:
        return errs                       # exits are always allowed
    if effects != {"open"}:
        errs.append("cannot mix open and close legs")
        return errs
    if qty > MAX_CONTRACTS:
        errs.append(f"max {MAX_CONTRACTS} contracts")
    for l in legs:
        if l.get("option_type") not in ("call", "put"):
            errs.append("option_type must be call/put")
        if l.get("side") not in ("buy", "sell"):
            errs.append("side must be buy/sell")
        # Robinhood legs accept ratio_quantity; anything but 1 is a ratio/backspread
        # (a 1x2 leaves a naked short leg and breaks the debit = max-loss math).
        try:
            if float(l.get("ratio_quantity", 1)) != 1:
                errs.append("ratio_quantity must be 1 on every leg (no ratio spreads/backspreads)")
        except (TypeError, ValueError):
            errs.append("ratio_quantity must be 1 on every leg (no ratio spreads/backspreads)")
    if errs:
        return errs
    if len(legs) == 1:
        if legs[0]["side"] != "buy":
            errs.append("single-leg opening orders must be BUY (no naked/short options)")
    else:
        a, b = legs
        if a["option_type"] != b["option_type"] or a["expiration"] != b["expiration"]:
            errs.append("spread legs must share type and expiration (vertical only)")
        sides = sorted([a["side"], b["side"]])
        if sides != ["buy", "sell"]:
            errs.append("spread needs exactly one buy leg and one sell leg")
        else:
            long = a if a["side"] == "buy" else b
            short = b if long is a else a
            if long["option_type"] == "call" and not float(long["strike"]) < float(short["strike"]):
                errs.append("call debit spread: long strike must be BELOW short strike")
            if long["option_type"] == "put" and not float(long["strike"]) > float(short["strike"]):
                errs.append("put debit spread: long strike must be ABOVE short strike")
        if o.get("direction") != "debit":
            errs.append("2-leg orders must be direction 'debit' (no credit spreads)")
    price = float(o.get("price", 0))
    if price <= 0:
        errs.append("limit price (net debit) must be > 0")
    debit = price * 100 * qty
    equity = float(o.get("equity", 0))
    if equity <= 0:
        errs.append("equity (from broker, this session) is required")
    elif debit > RISK_PCT * equity:
        errs.append(f"max loss ${debit:,.2f} > 3% of equity (${RISK_PCT*equity:,.2f})")
    used = month_used(today)
    if used + debit > MONTHLY_CAP:
        errs.append(f"monthly premium cap: ${used:,.2f} used + ${debit:,.2f} > ${MONTHLY_CAP:,.0f}")
    if int(o.get("open_bets", 99)) + 1 > MAX_BETS:
        errs.append(f"would exceed {MAX_BETS} open event bets")
    try:
        exp = date.fromisoformat(legs[0]["expiration"])
        if o.get("setup") == "capitol_cluster":
            # Charlie playbook B: congressional PTR cluster — debit SPREAD only, 90–150 days out
            dte = (exp - today).days
            if len(legs) != 2:
                errs.append("capitol_cluster setups must be debit spreads (2 legs)")
            if dte < 90 or dte > 150:
                errs.append(f"capitol_cluster expiry must be 90–150 days out (is {dte})")
            filed = date.fromisoformat(o["filing_date"])
            if (today - filed).days > 30:
                errs.append("capitol_cluster: newest PTR filing older than 30 days")
            return errs
        cat = date.fromisoformat(o["catalyst_date"])
        gap = (exp - cat).days
        if gap < 7 or gap > 60:
            errs.append(f"expiry must be 7–60 days after the catalyst (is {gap})")
        if (exp - today).days > 90:
            errs.append("expiry more than 90 days out")
        if cat < today:
            errs.append("catalyst date is in the past")
    except (KeyError, ValueError):
        errs.append("catalyst_date (or setup=capitol_cluster + filing_date) and leg expiration (YYYY-MM-DD) are required")
    return errs


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("check"); c.add_argument("--order", required=True)
    r = sp.add_parser("record"); r.add_argument("--order", required=True); r.add_argument("--fill-price", type=float, required=True)
    sp.add_parser("month")
    a = ap.parse_args()
    if a.cmd == "month":
        print(f"options premium used {date.today():%Y-%m}: ${month_used():,.2f} of ${MONTHLY_CAP:,.0f}")
        return 0
    o = json.loads(Path(a.order).read_text())
    if a.cmd == "check":
        errs = check(o)
        if errs:
            print("BLOCK — " + "; ".join(errs)); return 2
        kind = "EXIT" if {l["position_effect"] for l in o["legs"]} == {"close"} else "OPEN"
        print(f"PASS ({kind}) — {o['ticker']} {len(o['legs'])}-leg, qty {o['quantity']}, limit {o.get('price')}"
              + (f", max loss ${float(o['price'])*100*int(o['quantity']):,.2f}" if kind == "OPEN" else ""))
        return 0
    if a.cmd == "record":
        prem = round(a.fill_price * 100 * int(o["quantity"]), 2)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as f:
            f.write(json.dumps({"date": str(date.today()), "ticker": o["ticker"], "legs": o["legs"],
                                "quantity": o["quantity"], "fill_price": a.fill_price, "premium_usd": prem}) + "\n")
        print(f"recorded ${prem:,.2f}; month total ${month_used():,.2f}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
