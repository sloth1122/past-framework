#!/usr/bin/env python3
"""Unit regression tests for the refactored backtest_v2 helpers.

Stubs LLM calls AND entry-signal functions so every refactored path
executes deterministically: entry, floor sizing, stop exit, same-bar
re-entry block, final close, Rocky clamp.
"""
import sys, os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm_judge
import backtest_v2
import backtest_engine

# ── Stubs ──────────────────────────────────────────────────────
def fake_judge(**kwargs):
    return True, 12, ["synthetic approve"], {}

def fake_rocky(**kwargs):
    past = kwargs["past_scores"]
    return ({"patience": min(7, past["patience"] + 1)},
            {"note": "synthetic",
             "adjustments": {"patience": {"old": past["patience"],
                                          "new": min(7, past["patience"] + 1)}}},
            {})

llm_judge.judge_evaluate_llm = fake_judge
llm_judge.rocky_tune_llm = fake_rocky
backtest_v2.judge_evaluate_llm = fake_judge
backtest_v2.rocky_tune_llm = fake_rocky

# Force Alpha's entry signal to fire — isolates the refactor from
# indicator construction
backtest_v2.alpha_should_enter = lambda row, position: "PRIMARY"
backtest_engine.alpha_should_enter = lambda row, position: "PRIMARY"

failures = []

def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(name)

# ── Test 1: _process_entry sizing floors, never exceeds cash ────
row = pd.Series({"Close": 9.95}, name=pd.Timestamp("2026-06-15"))
pos, cash_delta, verdict, cnt = backtest_v2._process_entry(
    None, False, 0, "alpha", row, "TEST", "2026-06-15",
    {"patience": 3}, 15, 3, "3-5 days", "test", [], 100.0, 2500.0, True)
# cash=100, price=9.95 -> 10.05 shares -> floor to 10.0 -> cost 99.50
check("entry floor sizing", pos is not None and abs(pos["shares"] - 10.0) < 1e-9,
      f"shares={pos['shares'] if pos else None}")
check("entry cash delta <= 0", cash_delta <= 0 and cash_delta >= -100.0,
      f"delta={cash_delta}")
check("entry verdict recorded", verdict is not None and verdict["approved"] is True)
check("entry trade count delta", cnt == 1)

# ── Test 2: same-bar re-entry blocked after exit ───────────────
pos2, cd2, v2_, cnt2 = backtest_v2._process_entry(
    None, True, 0, "alpha", row, "TEST", "2026-06-15",
    {"patience": 3}, 15, 3, "3-5 days", "test", [], 100.0, 2500.0, True)
check("same-bar re-entry blocked", pos2 is None and cnt2 == 0)

# ── Test 3: daily trade cap respected ──────────────────────────
pos3, cd3, v3_, cnt3 = backtest_v2._process_entry(
    None, False, 2, "alpha", row, "TEST", "2026-06-15",
    {"patience": 3}, 15, 3, "3-5 days", "test", [], 100.0, 2500.0, True)
check("daily trade cap enforced", pos3 is None and cnt3 == 0)

# ── Test 4: _process_exit triggers STOP_LOSS and computes P&L ──
position = {"entry_price": 100.0, "shares": 5.0,
            "entry_date": pd.Timestamp("2026-06-10"), "entry_row": None}
row_down = pd.Series({"Close": 89.0}, name=pd.Timestamp("2026-06-15"))
trade, new_pos, cash_out = backtest_v2._process_exit(
    position, "alpha", row_down, "TEST", "2026-06-15", 5, True)
check("stop-loss exit fires", trade is not None and trade["exit_reason"] == "STOP_LOSS")
check("exit clears position", new_pos is None)
check("exit cash credit", abs(cash_out - 89.0 * 5.0) < 1e-9, f"cash_out={cash_out}")
if trade:
    check("exit pnl computed", abs(trade["pnl"] - (89.0 - 100.0) * 5.0) < 1e-9,
          f"pnl={trade['pnl']}")

# ── Test 5: _process_exit no-op when no signal ─────────────────
row_up = pd.Series({"Close": 105.0}, name=pd.Timestamp("2026-06-15"))
t5, p5, c5 = backtest_v2._process_exit(
    position, "alpha", row_up, "TEST", "2026-06-15", 2, True)
check("exit no-op when no signal", t5 is None and p5 is position and c5 == 0)

# ── Test 6: _close_final_position ──────────────────────────────
dates = pd.bdate_range("2026-06-01", periods=5)
df = pd.DataFrame({"Close": [100, 101, 102, 103, 104]}, index=dates)
final_cash, final_trade = backtest_v2._close_final_position(
    position, "TEST", "alpha", df, 2500.0, [])
check("final close fires", final_trade is not None
      and final_trade["exit_reason"] == "END_OF_PERIOD")
check("final close cash", abs(final_cash - 104.0 * 5.0) < 1e-9)

# ── Test 7: full loop integration — trades, cash floor, clamp ──
calls = {"judge": 0, "rocky": 0}
def counting_judge(**kw):
    calls["judge"] += 1
    return fake_judge(**kw)
def counting_rocky(**kw):
    calls["rocky"] += 1
    return fake_rocky(**kw)
backtest_v2.judge_evaluate_llm = counting_judge
backtest_v2.rocky_tune_llm = counting_rocky

df_int = pd.DataFrame({"Close": [100.0 + i for i in range(42)]},
                      index=pd.bdate_range("2026-01-01", periods=42))

strategy_meta = {
    "name": "test_alpha", "stop_pct": 3, "holding": "3-5 days",
    "max_position_pct": 15,
    "past_init": {"patience": 3, "conviction": 3, "risk_tolerance": 3, "impulsivity": 3},
}
result = backtest_v2.run_simulation_llm(df_int, "SYNTH", "alpha", strategy_meta, [], True)
trades = result["trades"]
check("integration: trades produced", len(trades) > 0, f"{len(trades)} trades")
check("integration: judge invoked", calls["judge"] > 0, f"{calls['judge']} calls")
check("integration: rocky invoked", calls["rocky"] > 0, f"{calls['rocky']} cycles")

# cash replay
cash = 2500.0
min_cash = cash
for t in trades:
    cash -= t["entry_price"] * t["shares"]
    min_cash = min(min_cash, cash)
    cash += t["exit_price"] * t["shares"]
check("integration: cash never negative", min_cash >= -0.005, f"min=${min_cash:.2f}")

# same-bar re-entry: no entry on a day that had an exit
exit_days = {t["exit_date"] for t in trades}
entry_days = [t["entry_date"] for t in trades]
check("integration: no same-bar re-entry",
      not (exit_days & set(entry_days)),
      f"exits={sorted(exit_days)}, entries={sorted(entry_days)}")

# clamp
ok = all(1 <= s <= 7 for h in result["past_history"] for s in h["scores"].values())
check("integration: PAST scores in 1-7", ok)

# ── Summary ────────────────────────────────────────────────────
print("=" * 60)
if failures:
    print(f"{len(failures)} FAILURES:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL REFACTOR REGRESSION CHECKS PASSED ✅")
sys.exit(0)
