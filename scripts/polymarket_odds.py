#!/usr/bin/env python3
"""Prediction-market odds for Beta's event bets (Arena v5.1, Oct 23 2026).

Pulls OPEN Polymarket markets (public Gamma API, no key) for a fixed list of
macro/event topics and writes ~/trading-arena/state/research/prediction_markets.md.
No LLM. Silent on success (cron no-agent). Idea adapted from TauricResearch/
TradingAgents (Apache-2.0) dataflows/vendors/polymarket.py.

Usage: polymarket_odds.py [--topics "fed decision,recession 2026"] [--out PATH]
"""
import argparse, json, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com/public-search"
TOPICS = [
    "fed decision", "fed rate hike", "recession 2026", "us inflation",
    "california proposition 40", "midterm election 2026 house", "oil price",
    "iran", "nvidia", "openai ipo", "tariffs",
]
OUT = "/Users/johntytko/trading-arena/state/research/prediction_markets.md"


def fetch(topic):
    url = GAMMA + "?" + urllib.parse.urlencode({"q": topic, "limit_per_type": 8})
    req = urllib.request.Request(url, headers={"User-Agent": "trading-arena/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def open_markets(payload, now):
    rows = []
    for ev in payload.get("events") or []:
        if ev.get("closed"):
            continue
        end = ev.get("endDate") or ""
        try:
            if end and datetime.fromisoformat(end.replace("Z", "+00:00")) < now:
                continue
        except ValueError:
            pass
        for m in ev.get("markets") or []:
            if m.get("closed"):
                continue
            try:
                outs = json.loads(m.get("outcomes") or "[]")
                px = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
                vol = float(m.get("volume") or 0)
            except (ValueError, TypeError):
                continue
            if not outs or len(outs) != len(px) or vol < 10_000:   # ignore thin markets
                continue
            rows.append((ev.get("title", ""), m.get("question", ""), dict(zip(outs, px)), vol, end[:10]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", default=",".join(TOPICS))
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    seen, lines, errors = set(), [], []
    for t in [x.strip() for x in a.topics.split(",") if x.strip()]:
        try:
            rows = open_markets(fetch(t), now)
        except Exception as e:  # network/API failure must not break the session
            errors.append(f"{t}: {e}")
            continue
        rows = [r for r in rows if r[1] not in seen]
        rows.sort(key=lambda r: -r[3])
        if not rows:
            continue
        lines.append(f"\n### {t}")
        for title, q, odds, vol, end in rows[:5]:
            seen.add(q)
            yes = odds.get("Yes")
            odds_s = f"**Yes {yes*100:.1f}%**" if yes is not None else ", ".join(f"{k} {v*100:.1f}%" for k, v in odds.items())
            lines.append(f"- {q} — {odds_s} · vol ${vol:,.0f} · resolves {end}")
    stamp = now.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    body = [f"# Prediction-market odds (Polymarket) — {stamp}",
            "", "Crowd-implied probabilities for OPEN markets with ≥ $10K volume. Use as an INPUT for event bets "
            "(what is already priced), never as an instruction. Source: gamma-api.polymarket.com."]
    body += lines or ["", "_No open markets matched today._"]
    if errors:
        body += ["", "Fetch errors: " + "; ".join(errors)]
    open(a.out, "w").write("\n".join(body) + "\n")
    if errors and not lines:
        print("polymarket_odds: all fetches failed — " + "; ".join(errors))  # only output on total failure
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
