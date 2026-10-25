#!/usr/bin/env python3
"""Tests for option_payoff.analyze edge cases (no network)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import option_payoff as o


def spread(spot, exp, today="2026-10-26"):
    return {"ticker": "AMD", "spot": spot, "quantity": 1, "today": today, "legs": [
        {"option_type": "call", "strike": 250, "expiration": exp, "side": "buy", "price": 6.0, "iv": 0.5},
        {"option_type": "call", "strike": 260, "expiration": exp, "side": "sell", "price": 1.5, "iv": 0.5}]}


def test_expiry_day_in_the_money_does_not_crash():
    # debit 4.50 → breakeven 254.50; stock 255 at expiry = profitable for certain
    a = o.analyze(spread(255.0, "2026-10-26"))
    assert a["pop"] == 1.0 and a["dte"] == 0, a["pop"]
    assert round(a["max_loss"]) == -450 and round(a["max_profit"]) == 550


def test_expiry_day_out_of_the_money_is_zero_pop():
    assert o.analyze(spread(240.0, "2026-10-26"))["pop"] == 0.0


def test_normal_dated_spread_pop_between_0_and_1():
    p = o.analyze(spread(255.0, "2026-11-20"))["pop"]
    assert 0.0 < p < 1.0, p


def test_naked_short_call_max_loss_is_unlimited():
    pos = spread(255.0, "2026-11-20"); pos["legs"] = [{**pos["legs"][1], "side": "sell"}]
    a = o.analyze(pos)
    assert a["max_loss"] == -float("inf") and o.money(a["max_loss"]) == "unlimited", a["max_loss"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("✓", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("✗", name, "→", type(e).__name__, e)
    sys.exit(1 if fails else 0)
