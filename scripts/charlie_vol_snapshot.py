#!/usr/bin/env python3
"""Charlie's volatility snapshot (no LLM, no key): VIX term structure → regime, HV30 per ticker,
and a self-built IV history (for IV Rank once ≥ 60 observations exist).

  charlie_vol_snapshot.py [--tickers AMD,MSFT,...]            → markdown to stdout + state file
  charlie_vol_snapshot.py --log-iv AMD 0.632                   → append today's ATM IV observation

Regime (ARENA adaptation of the ApexVol blueprint, long-premium/debit-only account):
  R1 Complacent  VIX < 14 and contango          → cheap convexity: single long calls/puts or wide debit spreads
  R2 Normal      14 ≤ VIX < 20, VIX/VIX3M < 0.97 → directional debit spreads around dated catalysts
  R3 Elevated    20 ≤ VIX < 30 or flat curve (0.97–1.05) → NARROW debit spreads only (short leg sells the rich IV)
  R4 Crisis      VIX ≥ 30 or VIX/VIX3M ≥ 1.05 (backwardation) → stand down on new premium
"""
import argparse, json, math, sys, time, urllib.request
from datetime import date, datetime
from pathlib import Path

ST = Path("/Users/johntytko/trading-arena/state/agent_charlie")
IVH = ST / "iv_history.jsonl"
OUT = ST / "vol_snapshot.md"


def chart(sym, rng="3mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 — fixed https:// host
                res = json.load(r)["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c]
            return closes, res["meta"].get("regularMarketPrice")
        except Exception:
            if i == 2:
                raise
            time.sleep(2)


def hv(closes, n=30):
    r = [math.log(b / a) for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252)


def regime(vix, vix3m):
    ratio = vix / vix3m if vix3m else 1.0
    if vix >= 30 or ratio >= 1.05:
        return "R4 Crisis/backwardation", "Stand down on new premium until VIX/VIX3M < 1.0; stock entries only via Beta."
    if vix >= 20 or ratio >= 0.97:
        return "R3 Elevated/flat curve", "Narrow debit spreads only (sold leg harvests rich IV); avoid single long options."
    if vix >= 14:
        return "R2 Normal", "Directional debit spreads around dated catalysts."
    return "R1 Complacent", "Convexity is cheap: single long calls/puts or wide debit spreads."


def vix_lines(fetch=None):
    """VIX / VIX9D / VIX3M lines. Each index is fetched on its own so one missing series
    (Yahoo often returns no VIX3M/VIX9D quote) never discards the others. Only a missing
    spot VIX makes the regime UNKNOWN; a missing VIX3M means the curve shape is unknown and
    the regime is read from the VIX level with the curve assumed flat (conservative)."""
    fetch = fetch or chart
    got, errs = {}, {}
    for sym in ("^VIX", "^VIX9D", "^VIX3M"):
        try:
            got[sym] = fetch(sym)[1]
        except Exception as e:  # noqa: BLE001 — reported in the snapshot
            got[sym], errs[sym] = None, e
    vix, v9, v3 = got["^VIX"], got["^VIX9D"], got["^VIX3M"]
    fmt = lambda x: "n/a" if x is None else f"{x:.2f}"
    if vix is None:
        why = errs.get("^VIX", "no quote returned")
        return [f"- VIX (spot) unavailable from Yahoo ({why}) → regime UNKNOWN; no new single long options today."]
    if v3:
        ratio = vix / v3
        shape = "contango" if ratio < 0.97 else ("flat" if ratio < 1.05 else "BACKWARDATION")
        curve = f"VIX3M {v3:.2f} (ratio {ratio:.2f}) → term structure **{shape}**"
    else:
        curve = "VIX3M n/a → term structure unknown (curve assumed flat, conservative)"
    rg, play = regime(vix, v3)
    return [f"- **VIX {vix:.2f}** · VIX9D {fmt(v9)} · {curve}", f"- **Regime: {rg}** — {play}"]


def iv_rank(tk, iv_now):
    if not IVH.exists():
        return None, 0
    rows = [json.loads(l) for l in IVH.read_text().splitlines() if l.strip()]
    obs = [r["iv"] for r in rows if r["ticker"] == tk]
    if len(obs) < 60:
        return None, len(obs)
    lo, hi = min(obs), max(obs)
    return (iv_now - lo) / (hi - lo) if hi > lo else None, len(obs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="QQQ,AMD,MSFT,GOOGL,AMZN,META,NVDA,AVGO,CIEN,VST")
    ap.add_argument("--log-iv", nargs=2, metavar=("TICKER", "IV"))
    a = ap.parse_args()
    ST.mkdir(parents=True, exist_ok=True)
    if a.log_iv:
        tk, iv = a.log_iv[0].upper(), float(a.log_iv[1])
        with IVH.open("a") as f:
            f.write(json.dumps({"date": str(date.today()), "ticker": tk, "iv": iv}) + "\n")
        rk, n = iv_rank(tk, iv)
        print(f"logged {tk} IV {iv:.3f} ({n} obs; IV rank {'n/a — building history' if rk is None else f'{rk*100:.0f}%'})")
        return 0
    lines = [f"# Charlie vol snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M')} MT (Yahoo daily closes; options IV comes from Robinhood)"]
    lines += vix_lines()
    lines += ["", "| Ticker | Last | HV30 | HV10 |", "|---|---|---|---|"]
    for tk in [t.strip().upper() for t in a.tickers.split(",") if t.strip()]:
        try:
            c, last = chart(tk)
            lines.append(f"| {tk} | {last:,.2f} | {hv(c,30)*100:.0f}% | {hv(c,10)*100:.0f}% |")
        except Exception as e:
            lines.append(f"| {tk} | err | {e} | |")
    lines += ["", "Compare each ticker's ATM IV (Robinhood) with HV30: IV ≫ HV30 → premium is rich → prefer a narrower debit spread; "
              "IV ≈/≤ HV30 → long premium is fairly priced. IV Rank: n/a until 60 daily IV observations are logged (`--log-iv`)."]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
