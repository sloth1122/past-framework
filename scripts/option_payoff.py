#!/usr/bin/env python3
"""Option position analytics for the arena (Charlie proposals + Beta's Greeks dashboard).

Black-Scholes (no dividends) repricing + exact piecewise-linear expiry payoff.

  option_payoff.py analyze --pos pos.json [--xlsx out.xlsx]   → text breakdown (+ Excel)

pos.json:
{ "ticker": "AMD", "spot": 509.7, "as_of": "2026-10-23 06:45 MT", "quantity": 1, "rate": 0.04,
  "today": "2026-10-23",
  "legs": [ {"option_type":"call","strike":545,"expiration":"2026-11-20","side":"buy","price":22.1,"iv":0.63,
             "delta":0.41,"gamma":0.0043,"theta":-0.62,"vega":0.55}, ... ] }

Broker greeks (per share) are used when present; otherwise computed from IV.
Position greeks are reported in $ terms: delta/gamma per share x 100 x contracts (shares-equivalent),
theta = $/day, vega = $ per 1 vol point.
"""
import argparse, json, math, sys
from datetime import date
from pathlib import Path

SQ2 = math.sqrt(2.0)


def N(x):
    return 0.5 * (1 + math.erf(x / SQ2))


def n(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs(S, K, T, r, v, typ):
    """price, delta, gamma, theta(/day), vega(/1 vol pt) per share."""
    if T <= 0 or v <= 0:
        intr = max(0.0, S - K) if typ == "call" else max(0.0, K - S)
        d = (1.0 if S > K else 0.0) if typ == "call" else (-1.0 if S < K else 0.0)
        return intr, d, 0.0, 0.0, 0.0
    sT = v * math.sqrt(T)
    d1 = (math.log(S / K) + (r + v * v / 2) * T) / sT
    d2 = d1 - sT
    if typ == "call":
        p = S * N(d1) - K * math.exp(-r * T) * N(d2)
        de = N(d1)
        th = -S * n(d1) * v / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N(d2)
    else:
        p = K * math.exp(-r * T) * N(-d2) - S * N(-d1)
        de = N(d1) - 1
        th = -S * n(d1) * v / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * N(-d2)
    return p, de, n(d1) / (S * sT), th / 365.0, S * n(d1) * math.sqrt(T) / 100.0


def sign(leg):
    return 1 if leg["side"] == "buy" else -1


def years(exp, today):
    return max(0.0, (date.fromisoformat(exp) - today).days / 365.0)


def expiry_pl(pos, S):
    q = pos["quantity"]
    v = 0.0
    for l in pos["legs"]:
        intr = max(0.0, S - l["strike"]) if l["option_type"] == "call" else max(0.0, l["strike"] - S)
        v += sign(l) * intr
    return (v - net_entry(pos)) * 100 * q


def net_entry(pos):
    """per-share net premium paid (+) / received (−)."""
    return sum(sign(l) * l["price"] for l in pos["legs"])


def model_pl(pos, S, today, iv_mult=1.0, days_fwd=0):
    q, r = pos["quantity"], pos.get("rate", 0.04)
    v = 0.0
    for l in pos["legs"]:
        T = max(0.0, years(l["expiration"], today) - days_fwd / 365.0)
        v += sign(l) * bs(S, l["strike"], T, r, l["iv"] * iv_mult, l["option_type"])[0]
    return (v - net_entry(pos)) * 100 * q


def analyze(pos):
    today = date.fromisoformat(pos.get("today", str(date.today())))
    S, q, r = pos["spot"], pos["quantity"], pos.get("rate", 0.04)
    legs = pos["legs"]
    strikes = sorted({l["strike"] for l in legs})
    # exact max/min of a piecewise-linear payoff: kinks + 0 + far tail
    hi = max(strikes) * 3
    pts = [0.0] + strikes + [hi]
    vals = [expiry_pl(pos, x) for x in pts]
    slope_hi = expiry_pl(pos, hi * 2) - vals[-1]
    max_profit = math.inf if slope_hi > 1e-9 else max(vals)
    # a falling far tail (e.g. a naked short call) has no floor: report it as unlimited
    max_loss = -math.inf if slope_hi < -1e-9 else min(vals)
    bes = []
    for (x0, y0), (x1, y1) in zip(zip(pts, vals), zip(pts[1:], vals[1:])):
        if (y0 < 0 <= y1) or (y0 > 0 >= y1):
            if y1 != y0:
                bes.append(round(x0 + (0 - y0) * (x1 - x0) / (y1 - y0), 2))
    # probability of profit at expiry under lognormal with avg IV (risk-neutral drift)
    exp0 = min(l["expiration"] for l in legs)
    T = years(exp0, today)
    iv = sum(l["iv"] for l in legs) / len(legs)
    def p_below(x):
        if x <= 0:
            return 0.0
        if T <= 0 or iv <= 0:
            # expiry day (or zero vol): the price is known, so P(S_T < x) is 1 or 0.
            # The option is NOT worthless — it settles at intrinsic value — only the
            # lognormal formula is undefined (it divides by iv * sqrt(T) = 0).
            return 1.0 if S < x else 0.0
        return N((math.log(x / S) - (r - iv * iv / 2) * T) / (iv * math.sqrt(T)))
    edges = [0.0] + sorted(set(bes)) + [math.inf]
    pop = 0.0
    for a, b in zip(edges, edges[1:]):
        mid = (a + b) / 2 if b != math.inf else a * 1.5 + 1
        if expiry_pl(pos, mid) > 0:
            pop += (1.0 if b == math.inf else p_below(b)) - p_below(a)
    # greeks (broker per-share values if present)
    G = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    src = "broker"
    for l in legs:
        calc = bs(S, l["strike"], years(l["expiration"], today), r, l["iv"], l["option_type"])
        vals_l = {"delta": l.get("delta"), "gamma": l.get("gamma"), "theta": l.get("theta"), "vega": l.get("vega")}
        if any(v is None for v in vals_l.values()):
            src = "model"
            vals_l = dict(zip(("delta", "gamma", "theta", "vega"), calc[1:]))
        for k in G:
            G[k] += sign(l) * float(vals_l[k]) * 100 * q
    scen = [
        ("Stock −5% tomorrow", model_pl(pos, S * 0.95, today, 1.0, 1)),
        ("Stock +5% tomorrow", model_pl(pos, S * 1.05, today, 1.0, 1)),
        ("IV +50% (vol spike)", model_pl(pos, S, today, 1.5, 0)),
        ("IV −30% (post-event crush)", model_pl(pos, S, today, 0.7, 1)),
        ("Flat stock, 1 week passes", model_pl(pos, S, today, 1.0, 7)),
    ]
    grid = sorted(set([round(S * (1 + k / 100), 2) for k in range(-20, 25, 5)] + strikes + bes))
    return {"debit": net_entry(pos) * 100 * q, "max_profit": max_profit, "max_loss": max_loss,
            "breakevens": bes, "pop": pop, "greeks": G, "greeks_src": src, "scenarios": scen,
            "grid": [(x, expiry_pl(pos, x)) for x in grid], "dte": (date.fromisoformat(exp0) - today).days}


def money(x):
    return "unlimited" if math.isinf(x) else f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def legs_text(pos):
    return " / ".join(f"{'Buy' if l['side']=='buy' else 'Sell'} {l['strike']:g}{l['option_type'][0].upper()}"
                      for l in pos["legs"]) + f" · exp {pos['legs'][0]['expiration']}"


def text(pos, a):
    S = pos["spot"]
    out = [f"{pos['ticker']} — {legs_text(pos)} × {pos['quantity']}",
           f"Spot ${S:,.2f} ({pos.get('as_of','')}) · {a['dte']} DTE",
           f"Cost (max loss): {money(-a['debit'])} · Max profit: {money(a['max_profit'])} · "
           f"Breakeven: {', '.join(f'${b:,.2f} ({(b/S-1)*100:+.1f}%)' for b in a['breakevens'])} · POP ≈{a['pop']*100:.0f}%",
           "", "```", f"{'At expiry':<12}{'Move':>7}{'P/L':>10}"]
    for x, pl in a["grid"]:
        out.append(f"${x:<11,.2f}{(x/S-1)*100:>+6.1f}%{money(pl):>10}")
    out += ["```", "Scenarios (model):"] + [f"- {nm}: {money(v)}" for nm, v in a["scenarios"]]
    g = a["greeks"]
    out.append(f"Greeks ({a['greeks_src']}): Δ {g['delta']:+.1f} sh · Γ {g['gamma']:+.3f} · Θ {money2(g['theta'])}/day · "
               f"Vega {money2(g['vega'])}/vol pt")
    return "\n".join(out)


def money2(x):
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def to_xlsx(pos, a, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    hdr = Font(bold=True, color="FFFFFF"); fill = PatternFill("solid", fgColor="0B0F14")
    def head(ws, row):
        ws.append(row)
        for c in ws[ws.max_row]:
            c.font, c.fill = hdr, fill
    ws = wb.active; ws.title = "Summary"
    head(ws, ["Field", "Value"])
    rows = [("Ticker", pos["ticker"]), ("Structure", legs_text(pos)), ("Contracts", pos["quantity"]),
            ("Spot", S := pos["spot"]), ("As of", pos.get("as_of", "")), ("Days to expiry", a["dte"]),
            ("Cost / max loss ($)", round(a["debit"], 2)),
            ("Max profit ($)", "unlimited" if math.isinf(a["max_profit"]) else round(a["max_profit"], 2)),
            ("Max loss ($)", "unlimited" if math.isinf(a["max_loss"]) else round(a["max_loss"], 2)),
            ("Breakeven(s)", ", ".join(f"{b:.2f}" for b in a["breakevens"])),
            ("Probability of profit (model)", round(a["pop"], 4)),
            ("Delta (shares-equiv)", round(a["greeks"]["delta"], 2)), ("Gamma", round(a["greeks"]["gamma"], 3)),
            ("Theta ($/day)", round(a["greeks"]["theta"], 2)), ("Vega ($/vol pt)", round(a["greeks"]["vega"], 2)),
            ("Greeks source", a["greeks_src"])]
    for r in rows:
        ws.append(list(r))
    ws["B12"].number_format = "0.0%"
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 44
    ws2 = wb.create_sheet("Legs")
    head(ws2, ["Side", "Type", "Strike", "Expiration", "Price", "IV", "Delta", "Gamma", "Theta", "Vega"])
    for l in pos["legs"]:
        ws2.append([l["side"], l["option_type"], l["strike"], l["expiration"], l["price"], l["iv"],
                    l.get("delta"), l.get("gamma"), l.get("theta"), l.get("vega")])
    ws3 = wb.create_sheet("Payoff at expiry")
    head(ws3, ["Stock price", "Move vs spot", "P/L ($)"])
    for x, pl in a["grid"]:
        ws3.append([x, x / S - 1, round(pl, 2)])
        ws3.cell(ws3.max_row, 2).number_format = "+0.0%;-0.0%"
        ws3.cell(ws3.max_row, 3).number_format = "+$#,##0;-$#,##0"
    ws4 = wb.create_sheet("Scenarios")
    head(ws4, ["Scenario (Black-Scholes)", "P/L ($)"])
    for nm, v in a["scenarios"]:
        ws4.append([nm, round(v, 2)])
    ws4.column_dimensions["A"].width = 32
    for w in (ws2, ws3):
        for col in "ABCDEFGHIJ":
            w.column_dimensions[col].width = 14
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("analyze"); a.add_argument("--pos", required=True); a.add_argument("--xlsx")
    args = ap.parse_args()
    pos = json.loads(Path(args.pos).read_text())
    res = analyze(pos)
    print(text(pos, res))
    if args.xlsx:
        to_xlsx(pos, res, args.xlsx)
        print(f"\nXLSX: {args.xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
