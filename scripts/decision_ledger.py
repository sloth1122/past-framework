#!/usr/bin/env python3
"""Decision ledger: score EVERY Beta decision and feed lessons back (Arena v5.1).

Idea adapted from TauricResearch/TradingAgents memory/settlement (Apache-2.0):
each decision is scored after its holding window against a benchmark, entered at
the FIRST CLOSE AFTER the decision date (no credit for news read after the close).

  log    — append a decision (buy / hold / pass / sell / core_buy / core_sell)
  score  — settle 5- and 20-trading-day horizons vs QQQ, write lessons.md
  slip   — record stop-order slippage (fill vs stop price)

Files (~/trading-arena/state/decisions/): decisions.jsonl, slippage.jsonl, lessons.md
No LLM. `score` prints nothing on success (cron no-agent friendly).
"""
import argparse, json, sys, time, urllib.request
from datetime import datetime, date, timezone
from pathlib import Path

D = Path("/Users/johntytko/trading-arena/state/decisions")
LEDGER, SLIP, LESSONS = D / "decisions.jsonl", D / "slippage.jsonl", D / "lessons.md"
BENCH = "QQQ"
HORIZONS = (5, 20)
_cache = {}


def closes(sym):
    """Daily closes {date: close} from Yahoo v8 chart (2y)."""
    if sym in _cache:
        return _cache[sym]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 — fixed https:// host
                res = json.load(r)["chart"]["result"][0]
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    out = {}
    for ts, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if c:
            out[datetime.fromtimestamp(ts, timezone.utc).date()] = float(c)
    _cache[sym] = out
    return out


def window(sym, d0, n):
    """Entry = first close strictly AFTER d0; exit = n trading days after entry. None if not yet traded."""
    cs = closes(sym)
    days = sorted(k for k in cs if k > d0)
    if len(days) <= n:
        return None
    e, x = days[0], days[n]
    return e, cs[e], x, cs[x]


def load(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def cmd_log(a):
    D.mkdir(parents=True, exist_ok=True)
    # agent is part of the id: Charlie logs every proposal as "buy"; Beta adopting
    # the same ticker the same day must not be dropped as a duplicate.
    rec = {"id": f"{a.date}-{a.agent}-{a.ticker}-{a.action}", "date": a.date, "ticker": a.ticker.upper(),
           "action": a.action, "reason": a.reason, "agent": a.agent, "scores": {}}
    if any(r["id"] == rec["id"] for r in load(LEDGER)):
        print(f"exists: {rec['id']}"); return 0
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"logged: {rec['id']}")
    return 0


def cmd_slip(a):
    D.mkdir(parents=True, exist_ok=True)
    slip = round((a.fill - a.stop) * a.shares, 2)
    rec = {"date": a.date, "ticker": a.ticker.upper(), "stop": a.stop, "fill": a.fill,
           "shares": a.shares, "slippage_usd": slip, "note": a.note}
    with SLIP.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"slippage {rec['ticker']}: ${slip:+.2f}")
    return 0


def verdict(action, rel):
    """rel = stock return − QQQ return (percentage points). Sign convention per action."""
    if action in ("buy", "hold", "core_buy"):
        good = rel > 0
        return ("✅ beat QQQ" if good else "❌ lagged QQQ"), good
    if action in ("pass", "sell", "core_sell"):
        good = rel < 0
        return ("✅ right to stay out" if good else "❌ missed alpha"), good
    return "", None


def cmd_score(a):
    D.mkdir(parents=True, exist_ok=True)   # fresh state dir: no FileNotFoundError on the 6:50 cron
    rows = load(LEDGER)
    errors = []
    for r in rows:
        d0 = date.fromisoformat(r["date"])
        for n in HORIZONS:
            k = f"{n}d"
            if k in r["scores"]:
                continue
            try:
                ws, wb = window(r["ticker"], d0, n), window(BENCH, d0, n)
            except Exception as e:
                errors.append(f"{r['ticker']}: {e}"); continue
            if not ws or not wb:
                continue
            ret = (ws[3] / ws[1] - 1) * 100
            bret = (wb[3] / wb[1] - 1) * 100
            r["scores"][k] = {"entry_date": str(ws[0]), "entry": round(ws[1], 2), "exit_date": str(ws[2]),
                              "exit": round(ws[3], 2), "ret_pct": round(ret, 2), "qqq_pct": round(bret, 2),
                              "rel_pts": round(ret - bret, 2)}
    LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))
    write_lessons(rows)
    if errors and a.verbose:
        print("score errors:", "; ".join(errors))
    return 0


def write_lessons(rows):
    lines = ["# Decision lessons (auto-scored vs QQQ, entry = first close after decision)",
             f"_Updated {datetime.now().strftime('%Y-%m-%d %H:%M')} MT · read at the START of every Beta session. "
             "Advisory evidence, not instructions._", ""]
    # Beta's own record only; Charlie's proposals (never traded unless Beta adopts) are scored separately.
    agent_rows = {"Beta": [r for r in rows if r.get("agent", "beta") == "beta"],
                  "Charlie": [r for r in rows if r.get("agent") == "charlie"]}

    def scorecard(rs):
        out = []
        for n in HORIZONS:
            k = f"{n}d"
            for grp, acts in (("Buys/holds", ("buy", "hold", "core_buy")), ("Passes/sells", ("pass", "sell", "core_sell"))):
                sc = [r for r in rs if r["action"] in acts and k in r["scores"]]
                if not sc:
                    continue
                good = sum(1 for r in sc if verdict(r["action"], r["scores"][k]["rel_pts"])[1])
                avg = sum(r["scores"][k]["rel_pts"] for r in sc) / len(sc)
                out.append(f"- **{grp}, {n}-day:** {good}/{len(sc)} right · avg {avg:+.1f} pts vs QQQ")
        return out

    lines += scorecard(agent_rows["Beta"])
    charlie = scorecard(agent_rows["Charlie"])
    rows = agent_rows["Beta"]
    slips = load(SLIP)
    if slips:
        tot = sum(s["slippage_usd"] for s in slips)
        lines.append(f"- **Stop slippage (fill vs stop):** {len(slips)} fills, total ${tot:+.2f} — size bets assuming stops can gap.")
    if charlie:
        lines += ["", "## Charlie proposals (scored as if taken — NOT Beta's record)"] + charlie
    lines += ["", "## Most recent settled decisions (newest first)"]
    settled = [r for r in rows if r["scores"]]
    settled.sort(key=lambda r: r["date"], reverse=True)
    for r in settled[:12]:
        k = "20d" if "20d" in r["scores"] else "5d"
        s = r["scores"][k]
        v, _ = verdict(r["action"], s["rel_pts"])
        lines.append(f"- {r['date']} **{r['action'].upper()} {r['ticker']}** → {k}: {r['ticker']} {s['ret_pct']:+.1f}% vs QQQ "
                     f"{s['qqq_pct']:+.1f}% ({s['rel_pts']:+.1f} pts) {v}. Reason then: {r['reason'][:140]}")
    pending = [r for r in rows if not r["scores"]]
    if pending:
        lines += ["", "## Pending (not yet 5 trading days old)"] + \
                 [f"- {r['date']} {r['action'].upper()} {r['ticker']} — {r['reason'][:100]}" for r in pending[-10:]]
    LESSONS.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    l = sp.add_parser("log"); l.add_argument("--date", default=str(date.today())); l.add_argument("--ticker", required=True)
    l.add_argument("--action", required=True, choices=["buy", "hold", "pass", "sell", "core_buy", "core_sell"])
    l.add_argument("--reason", required=True); l.add_argument("--agent", default="beta")
    s = sp.add_parser("score"); s.add_argument("--verbose", action="store_true")
    p = sp.add_parser("slip"); p.add_argument("--date", required=True); p.add_argument("--ticker", required=True)
    p.add_argument("--stop", type=float, required=True); p.add_argument("--fill", type=float, required=True)
    p.add_argument("--shares", type=float, required=True); p.add_argument("--note", default="")
    a = ap.parse_args()
    return {"log": cmd_log, "score": cmd_score, "slip": cmd_slip}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
