#!/usr/bin/env python3
"""
Backtest v3 — portfolio-level, shared capital, rolling windows, no leakage.

Why v3 exists
-------------
v1 (backtest_sim.py) simulated every ticker as an INDEPENDENT run that each
started with the full $2,500 per agent, then summed the six P&Ls. That is not a
portfolio return. It also used full-dataset 52-week extremes (look-ahead) and a
stub Judge that auto-passed 5/13 checks. v2 fixed leakage and added an LLM
Judge but was still single-ticker.

v3 runs ONE portfolio per agent across all tickers simultaneously:
  * one cash pool of $2,500 per agent, shared across every ticker
  * one day at a time, exits processed before entries, tickers in fixed
    alphabetical order (disclosed; matters only when cash is binding)
  * every indicator at day D uses only data from D-252 .. D
  * Judge is deterministic and scores only the six checklist items that can
    actually fail in a price-only, rule-based harness. Items that are constant or
    tautological here (2, 3, 4, 5) or need external data (6, 9, 10, 11) are NOT
    scored and the pass threshold is scaled accordingly. See judge_evaluate().
  * Rocky is the rule-based coach from v1, unchanged in logic, but its
    adjustments now actually cascade into the entry rules per the paper §3.2
    (Alpha Patience 7 -> RSI<20 + bullish close). Other trait changes are
    recorded but have no defined cascade in the paper and so are inert.
  * no commissions, no slippage, fills at daily close (disclosed)

Usage:
  python3 backtest_v3.py                       # defaults below
  python3 backtest_v3.py --no-ipo-ban          # sensitivity: allow <90-day IPOs
  python3 backtest_v3.py --start 2026-01-01 --end 2026-07-21 --tickers SPCX,OKLO,NVDA,APLD,CCJ,MU
"""
import argparse, datetime, json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import yfinance as yf

from backtest_engine import ALLOC, prepare_data  # noqa: E402

OUT_DIR = os.path.expanduser(os.environ.get("OUT_DIR", "~/trading-arena/state/backtests"))
IPO_DATES = {"SPCX": "2026-06-12"}   # first trading day; Judge item 11c bans < 90 calendar days
IPO_BAN_DAYS = 90
MIN_AVG_VOLUME = 1_000_000           # Judge item 7 liquidity

AGENTS = {
    "alpha": {
        # Production go-live vector (skills/trading-arena-alpha.md, 2026-08-06). "patience" = Entry Patience.
        "label": "Alpha — Renaissance / mean reversion",
        "past": {"risk_tolerance": 3, "conviction": 2, "impulsivity": 2, "patience": 3},
        "stop_pct": 0.03, "size_pct": 0.15, "size_pct_secondary": 0.08,
        "max_positions": 4, "banned": set(),
    },
    "beta_aschenbrenner": {
        "label": "Beta — Aschenbrenner / AI-infra thesis (paper §6.3)",
        "past": {"risk_tolerance": 6, "conviction": 7, "impulsivity": 5, "patience": 7},
        "stop_pct": 0.10, "size_pct": 0.20, "size_pct_secondary": None,
        "max_positions": 6, "banned": {"NVDA"},   # paper: NVDA thesis-banned (short side only)
        "entry": "near_low",
    },
    "beta_baker": {
        "label": "Beta — Baker / Atreides (live profile since 2026-07-30)",
        "past": {"risk_tolerance": 5, "conviction": 6, "impulsivity": 3, "patience": 6},
        "stop_pct": 0.10, "size_pct": 0.25, "size_pct_secondary": None,
        "max_positions": 5, "banned": set(),   # skills/trading-arena-beta.md: "Max 5 positions" at Risk 5/7
        "entry": "near_low_or_pullback",
    },
}


# ────────────────────────────────────────────────────────────── data
def fetch(ticker, start, end, lookback_weeks=52):
    buf = pd.Timestamp(start) - pd.Timedelta(weeks=lookback_weeks + 4)
    df = yf.Ticker(ticker).history(start=buf, end=pd.Timestamp(end) + pd.Timedelta(days=1), auto_adjust=True)
    if df.empty:
        return None
    df.index = df.index.tz_localize(None)
    df = prepare_data(df, ticker)
    df["AvgVol20"] = df["Volume"].rolling(20, min_periods=1).mean()
    df["Open_"] = df["Open"]
    return df


# ────────────────────────────────────────────────────────────── rule cascade (paper §3.2)
def alpha_entry(row, past):
    rsi, ma50, ma50_prev, price = row["RSI"], row["MA50"], row["MA50_prev"], row["Close"]
    rising = ma50 > ma50_prev
    if past["patience"] >= 7:
        # paper: P4=7 -> RSI<20 AND rising 50d MA AND bullish candle confirmation
        if rsi < 20 and rising and row["Close"] > row["Open_"] and price > ma50 * 0.85:
            return "PRIMARY"
        return None
    if rsi < 35 and rising and price > ma50 * 0.85:
        return "PRIMARY"
    if 35 <= rsi <= 45 and rising and price > ma50 * 0.90:
        return "SECONDARY"
    return None


def alpha_exit(row, pos, days_held, stop_pct):
    if row["Close"] <= pos["entry_price"] * (1 - stop_pct):
        return "STOP_LOSS"
    if row["RSI"] > 55:
        return "RSI_EXIT"
    if days_held >= 5:
        return "TIME_EXIT"
    return None


def beta_entry(row, cfg):
    price, low52, high52 = row["Close"], row["Low52"], row["High52"]
    near_low = price <= low52 * 1.25
    if cfg["entry"] == "near_low":
        return "THESIS" if near_low else None
    pulled_back = price <= high52 * 0.85
    return "THESIS" if (near_low or pulled_back) else None


def beta_exit(row, pos, days_held, stop_pct):
    if row["Close"] <= pos["entry_price"] * (1 - stop_pct):
        return "STOP_LOSS"
    return None


# ────────────────────────────────────────────────────────────── Judge (deterministic, no auto-pass)
def judge_evaluate(agent_key, cfg, ticker, date, row, signal, size_pct, n_open, ipo_ban, other_agent_in_ticker):
    """Score only checks that can actually fail in this harness. Returns (approved, score, max_score, notes).

    Six items are scored: 1 thesis/data (re-derived from the row, not the agent's signal),
    7 liquidity, 8 personality fit, 11b restricted list, 11c IPO ban, 13 max positions.
    NOT scored (recorded as notes where useful):
      2  position size  — always equals the configured size by construction (tautology)
      3  stop defined   — per-agent constant in this harness (cannot fail)
      4  PAST bounds    — Rocky clamps to 1-7 before the Judge sees scores (cannot fail)
      5  convergence    — informational in production, never rejects
      6, 9, 10, 11      — need earnings/options/catalyst/state data a price backtest lacks
    Item 8 can fail only if Rocky moves the fit trait past its threshold; in the committed runs
    it never did, and that is disclosed in the paper.
    Threshold keeps production's 10/13 ratio: ceil(6 * 10/13) = 5. Items 11b, 11c, 13 are hard blocks."""
    notes, score, max_score = [], 0, 0

    def check(ok, label):
        nonlocal score, max_score
        max_score += 1
        score += int(bool(ok))
        notes.append(("✓ " if ok else "✗ ") + label)

    # 1 thesis supported by data — the Judge re-derives the entry condition from the row itself
    #   rather than trusting the agent's signal. For Beta the Judge applies the STRICTER of the two
    #   Beta entry definitions (within 25% of the 52-week low), so a Baker pullback-only entry
    #   (>=15% off the high but >25% above the low) fails this item. This is a genuine check.
    if agent_key == "alpha":
        check(row["RSI"] < 45 and row["MA50"] > row["MA50_prev"], f"RSI {row['RSI']:.1f}, 50d MA rising")
    else:
        near_low = row["Close"] <= row["Low52"] * 1.25
        check(near_low, f"price {row['Close']:.2f} within 25% of 52wk low {row['Low52']:.2f}")
    # 3 stop-loss set — NOT scored: stop_pct is a per-agent constant in this harness (cannot fail)
    notes.append(f"· stop {cfg['stop_pct']:.0%} (constant, unscored)")
    # 4/11d PAST drift and 5 convergence are NOT scored: Rocky clamps scores to 1-7 before the Judge
    # ever sees them (item 4 cannot fail), and convergence is informational in production (item 5
    # never rejects). Both are recorded as notes only.
    notes.append(("· convergence: other agent also holds " + ticker) if other_agent_in_ticker else "· no convergence")
    # 7 liquidity
    check(row["AvgVol20"] >= MIN_AVG_VOLUME, f"20d avg vol {row['AvgVol20']/1e6:.1f}M >= 1M")
    # 8 PAST personality fit — production skill files define the fit:
    #   Alpha: Impulsivity 2/7 -> "requires 5 entry criteria, RSI < 35" (low impulsivity fits statistical entry)
    #   Beta:  Conviction 6/7  -> "holds through volatility, exits on thesis break"
    if agent_key == "alpha":
        check(cfg["past"]["impulsivity"] <= 3, "impulsivity <= 3 fits rule-gated statistical entry")
    else:
        check(cfg["past"]["conviction"] >= 6, "conviction >= 6 fits thesis hold")
    # 11b restricted list
    check(ticker not in cfg["banned"], f"{ticker} not on agent's banned list")
    # 11c IPO ban (HARD BLOCK)
    ipo = IPO_DATES.get(ticker)
    days_public = (date - pd.Timestamp(ipo)).days if ipo else 10_000
    ipo_ok = (not ipo_ban) or days_public >= IPO_BAN_DAYS
    check(ipo_ok, f"public {days_public}d >= {IPO_BAN_DAYS}d" if ipo else "not a recent IPO")
    # 13 max positions
    check(n_open < cfg["max_positions"], f"open positions {n_open} < {cfg['max_positions']}")

    # NOT SCORED (need data not in a price backtest): 6 earnings window, 9 options budget,
    # 10 catalyst, 11 state-file honesty. Threshold: production is 10/13 = 77%; same ratio here.
    threshold = math.ceil(max_score * 10 / 13)
    hard_block = not ipo_ok or ticker in cfg["banned"] or n_open >= cfg["max_positions"]
    approved = score >= threshold and not hard_block
    return approved, score, max_score, notes


# ────────────────────────────────────────────────────────────── Rocky (rule-based, v1 logic)
def rocky_tune(agent_key, closed_all, closed_this_cycle, past, cycle):
    """Rule-based coach. Reacts only to trades CLOSED SINCE THE LAST REVIEW (closed_this_cycle);
    cumulative history (closed_all) is used only for the 'has this agent ever traded' test."""
    adj, reasons = {}, []
    period = closed_this_cycle
    wins = [t for t in period if t["pnl"] > 0]
    losses = [t for t in period if t["pnl"] < 0]
    wr = len(wins) / len(period) if period else None
    if agent_key == "alpha":
        if wr is not None and wr < 0.3 and len(losses) > 2 and past["patience"] < 7:
            adj["patience"] = past["patience"] + 1
            reasons.append(f"period win rate {wr:.0%} low on {len(period)} trades — Patience +1 tightens entry")
        if not closed_all and cycle >= 2 and past["patience"] > 4:
            adj["patience"] = past["patience"] - 1
            reasons.append("no trades yet — Patience -1 loosens entry")
    else:
        stops = [t for t in losses if t["pnl_pct"] <= -0.10]
        if stops and past["impulsivity"] < 7:
            adj["impulsivity"] = past["impulsivity"] + 1
            reasons.append(f"{len(stops)} max-stop exit(s) this period ({', '.join(t['ticker'] for t in stops)}) — Impulsivity +1 (recorded; no cascade defined in paper)")
        if wr is not None and wr > 0.5 and len(wins) >= 2 and past["conviction"] < 7:
            adj["conviction"] = past["conviction"] + 1
            reasons.append(f"period win rate {wr:.0%} high — Conviction +1 (recorded; no cascade defined)")
    return adj, reasons


# ────────────────────────────────────────────────────────────── portfolio simulation
def run_agent(agent_key, data, dates, ipo_ban, other_positions_lookup, cooldown=0):
    cfg = json.loads(json.dumps(AGENTS[agent_key], default=list))
    cfg["banned"] = set(cfg["banned"])
    past = dict(cfg["past"])
    cash = ALLOC
    positions = {}            # ticker -> pos
    stopped_until = {}        # ticker -> trading-day index before which re-entry is blocked
    trades, verdicts, past_hist = [], [], [{"cycle": 0, "scores": dict(past), "reasons": ["initial"]}]
    equity_curve = []
    cycle = 0
    trades_at_last_review = 0

    for i, date in enumerate(dates):
        # exits first
        for tk in sorted(positions):
            df = data[tk]
            if date not in df.index:
                continue
            row = df.loc[date]
            pos = positions[tk]
            held = i - pos["entry_idx"]          # trading sessions held, not calendar days
            reason = alpha_exit(row, pos, held, cfg["stop_pct"]) if agent_key == "alpha" \
                else beta_exit(row, pos, held, cfg["stop_pct"])
            if reason:
                px = row["Close"]
                pnl = (px - pos["entry_price"]) * pos["shares"]
                cash += px * pos["shares"]
                trades.append({"ticker": tk, "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
                               "exit_date": date.strftime("%Y-%m-%d"), "entry_price": round(pos["entry_price"], 4),
                               "exit_price": round(px, 4), "shares": pos["shares"], "cost": round(pos["cost"], 2),
                               "pnl": round(pnl, 2), "pnl_pct": round(pnl / pos["cost"], 4),
                               "exit_reason": reason, "status": "CLOSED"})
                del positions[tk]
                if reason == "STOP_LOSS":
                    # cooldown = number of full trading sessions that must pass after a stop before the
                    # same ticker may be re-entered. 0 = eligible again at the very next session (the live
                    # arena runs once per session, so this is the live-matching value). -1 reproduces the
                    # v1 artifact of re-buying on the same bar you were stopped on.
                    stopped_until[tk] = i + 1 + cooldown

        # entries, alphabetical
        for tk in sorted(data):
            if tk in positions or i < stopped_until.get(tk, -1):
                continue
            df = data[tk]
            if date not in df.index:
                continue
            row = df.loc[date]
            cfg["past"] = past
            signal = alpha_entry(row, past) if agent_key == "alpha" else beta_entry(row, cfg)
            if not signal:
                continue
            size_pct = cfg["size_pct_secondary"] if signal == "SECONDARY" else cfg["size_pct"]
            other = other_positions_lookup(date, tk)
            ok, sc, mx, notes = judge_evaluate(agent_key, cfg, tk, date, row, signal, size_pct,
                                               len(positions), ipo_ban, other)
            verdicts.append({"date": date.strftime("%Y-%m-%d"), "ticker": tk, "signal": signal,
                             "approved": ok, "score": f"{sc}/{mx}", "notes": notes})
            if not ok:
                continue
            px = row["Close"]
            budget = min(cash, ALLOC * size_pct)
            shares = round(budget / px, 1)
            if shares <= 0 or shares * px > cash + 1e-6:
                shares = round(cash / px - 0.05, 1)
            if shares <= 0:
                verdicts[-1]["notes"].append("✗ insufficient cash — skipped")
                verdicts[-1]["filled"] = False
                continue
            verdicts[-1]["filled"] = True
            cost = shares * px
            cash -= cost
            positions[tk] = {"entry_price": px, "shares": shares, "entry_date": date, "entry_idx": i, "cost": cost}

        # mark to market
        mtm = cash + sum(data[tk].loc[:date]["Close"].iloc[-1] * p["shares"] for tk, p in positions.items())
        equity_curve.append((date.strftime("%Y-%m-%d"), round(mtm, 2)))

        # Rocky every 10 trading days
        if i > 0 and i % 10 == 0:
            cycle += 1
            adj, reasons = rocky_tune(agent_key, trades, trades[trades_at_last_review:], past, cycle)
            trades_at_last_review = len(trades)
            if adj:
                for k, v in adj.items():
                    past[k] = max(1, min(7, v))
                past_hist.append({"cycle": cycle, "date": date.strftime("%Y-%m-%d"),
                                  "scores": dict(past), "adjustments": adj, "reasons": reasons})

    # end-of-period mark for open positions (reported separately as unrealized)
    open_marks = []
    for tk, pos in positions.items():
        px = data[tk].loc[:dates[-1]]["Close"].iloc[-1]
        open_marks.append({"ticker": tk, "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
                           "entry_price": round(pos["entry_price"], 4), "mark": round(px, 4),
                           "shares": pos["shares"], "cost": round(pos["cost"], 2),
                           "unrealized": round((px - pos["entry_price"]) * pos["shares"], 2)})

    realized = round(sum(t["pnl"] for t in trades), 2)
    unrealized = round(sum(o["unrealized"] for o in open_marks), 2)
    final_equity = round(cash + sum(o["mark"] * o["shares"] for o in open_marks), 2)
    eq = pd.Series([e for _, e in equity_curve])
    peak = eq.cummax()
    max_dd = float(((eq - peak) / peak).min()) if len(eq) else 0.0

    return {
        "agent": agent_key, "label": AGENTS[agent_key]["label"],
        "start_capital": ALLOC, "final_equity": final_equity,
        "total_return_pct": round((final_equity / ALLOC - 1) * 100, 2),
        "realized_pnl": realized, "unrealized_pnl": unrealized,
        "closed_trades": len(trades), "wins": sum(t["pnl"] > 0 for t in trades),
        "losses": sum(t["pnl"] < 0 for t in trades),
        "win_rate": round(sum(t["pnl"] > 0 for t in trades) / len(trades), 3) if trades else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "judge_signals": len(verdicts), "judge_approved": sum(v["approved"] for v in verdicts),
        "judge_rejected": sum(not v["approved"] for v in verdicts),
        "approved_but_no_cash": sum(1 for v in verdicts if v["approved"] and v.get("filled") is False),
        "filled_entries": sum(1 for v in verdicts if v.get("filled")),
        "final_past": past, "past_history": past_hist,
        "trades": trades, "open_at_end": open_marks, "verdicts": verdicts,
        "equity_curve": equity_curve,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-21")
    ap.add_argument("--tickers", default="SPCX,OKLO,NVDA,APLD,CCJ,MU")
    ap.add_argument("--no-ipo-ban", action="store_true")
    ap.add_argument("--agents", default="alpha,beta_aschenbrenner,beta_baker")
    ap.add_argument("--cooldown", type=int, default=0,
                    help="full trading sessions to skip after a stop before the same ticker may be re-entered. "
                         "Default 0 = eligible at the next session, matching the live arena (agents run once daily "
                         "at 7:00 AM; stops fire broker-side intraday). -1 = same-bar re-entry (v1 artifact).")
    a = ap.parse_args()
    tickers = [t.strip().upper() for t in a.tickers.split(",")]
    ipo_ban = not a.no_ipo_ban

    print(f"BACKTEST v3 — portfolio-level, shared ${ALLOC:,.0f}/agent, rolling 52-wk windows")
    print(f"window {a.start} → {a.end} | tickers {tickers} | IPO ban {'ON' if ipo_ban else 'OFF'} | stop cooldown {a.cooldown}")
    data = {}
    for tk in tickers:
        df = fetch(tk, a.start, a.end)
        if df is None:
            print(f"  {tk}: NO DATA"); continue
        df = df.loc[a.start:a.end]
        data[tk] = df
        print(f"  {tk}: {len(df)} trading days ({df.index[0].date()} → {df.index[-1].date()})")
    dates = sorted(set().union(*[set(df.index) for df in data.values()]))

    results = {}
    # Alpha first so Beta's convergence note can see Alpha's book; Alpha sees nothing (order-independent for scoring)
    alpha_book = {}
    def alpha_lookup(date, tk):
        return tk in alpha_book.get(date, set())
    results["alpha"] = run_agent("alpha", data, dates, ipo_ban, lambda d, t: False, cooldown=a.cooldown)
    # reconstruct Alpha's daily book for the convergence note
    for t in results["alpha"]["trades"]:
        for d in pd.date_range(t["entry_date"], t["exit_date"]):
            alpha_book.setdefault(d, set()).add(t["ticker"])
    for key in [k for k in a.agents.split(",") if k != "alpha"]:
        results[key] = run_agent(key, data, dates, ipo_ban, alpha_lookup, cooldown=a.cooldown)

    print()
    print(f"{'agent':<22}{'final $':>10}{'return':>9}{'realized':>10}{'unreal':>9}{'trades':>7}{'win%':>6}{'maxDD':>8}{'judge':>10}")
    for k, r in results.items():
        wr = f"{r['win_rate']:.0%}" if r["win_rate"] is not None else "—"
        print(f"{k:<22}{r['final_equity']:>10,.2f}{r['total_return_pct']:>8.2f}%{r['realized_pnl']:>10,.2f}"
              f"{r['unrealized_pnl']:>9,.2f}{r['closed_trades']:>7}{wr:>6}{r['max_drawdown_pct']:>7.1f}%"
              f"{r['judge_approved']:>4}/{r['judge_signals']:<4} fill {r['filled_entries']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = ("ipoban" if ipo_ban else "noipoban") + f"_cd{a.cooldown}"
    out = os.path.join(OUT_DIR, f"backtest_v3_{tag}_{ts}.json")
    with open(out, "w") as f:
        json.dump({"version": 3, "start": a.start, "end": a.end, "tickers": tickers, "ipo_ban": ipo_ban,
                   "stop_cooldown_days": a.cooldown,
                   "alloc_per_agent": ALLOC, "fills": "daily close, no commission, no slippage",
                   "judge": "deterministic; scored items 1,7,8,11b,11c,13 (threshold 5/6); unscored 2,3,4,5 (cannot fail in harness), 6,9,10,11 (need non-price data)",
                   "results": results}, f, indent=2, default=str)
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
