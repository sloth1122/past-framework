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


def iv_rank(tk, iv_now):
    if not IVH.exists():
        return None, 0
    obs = [json.loads(l)["iv"] for l in IVH.read_text().splitlines() if l.strip() and json.loads(l)["ticker"] == tk]
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
    try:
        vix = chart("^VIX")[1]; v9 = chart("^VIX9D")[1]; v3 = chart("^VIX3M")[1]
        rg, play = regime(vix, v3)
        shape = "contango" if v3 and vix / v3 < 0.97 else ("flat" if vix / v3 < 1.05 else "BACKWARDATION")
        lines += [f"- **VIX {vix:.2f}** · VIX9D {v9:.2f} · VIX3M {v3:.2f} (ratio {vix/v3:.2f}) → term structure **{shape}**",
                  f"- **Regime: {rg}** — {play}"]
    except Exception as e:
        lines.append(f"- VIX fetch failed ({e}) → treat regime as UNKNOWN; no new single long options today.")
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
