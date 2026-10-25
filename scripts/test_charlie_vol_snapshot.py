#!/usr/bin/env python3
"""Tests for charlie_vol_snapshot.vix_lines (no network: fetcher is injected)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charlie_vol_snapshot as c


def fetcher(vals):
    def f(sym):
        v = vals.get(sym)
        if isinstance(v, Exception):
            raise v
        return [v], v
    return f


def test_all_three_fetched():
    out = "\n".join(c.vix_lines(fetcher({"^VIX": 16.0, "^VIX9D": 15.0, "^VIX3M": 18.0})))
    assert "VIX 16.00" in out and "contango" in out and "R2 Normal" in out, out


def test_vix3m_missing_keeps_vix_and_says_so():
    out = "\n".join(c.vix_lines(fetcher({"^VIX": 16.0, "^VIX9D": 15.0, "^VIX3M": None})))
    assert "fetch failed" not in out, out
    assert "VIX 16.00" in out and "VIX3M n/a" in out and "term structure unknown" in out, out


def test_vix9d_error_is_not_fatal():
    out = "\n".join(c.vix_lines(fetcher({"^VIX": 25.0, "^VIX9D": TimeoutError("t/o"), "^VIX3M": 24.0})))
    assert "VIX9D n/a" in out and "R3" in out, out


def test_vix_itself_missing_is_unknown_regime():
    out = "\n".join(c.vix_lines(fetcher({"^VIX": TimeoutError("yahoo down"), "^VIX9D": 15.0, "^VIX3M": 18.0})))
    assert "VIX (spot) unavailable" in out and "UNKNOWN" in out and "yahoo down" in out, out


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("✓", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("✗", name, "→", type(e).__name__, e)
    sys.exit(1 if fails else 0)
