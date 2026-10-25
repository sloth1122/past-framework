#!/usr/bin/env python3
"""Tests for the pre-market health check's model-pin audit and model_status.md (no network)."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trading_arena_premarket_health as h

GOOD = {"model": "claude-opus-5-5", "provider": "anthropic", "reasoning_effort": "high"}
CFG = "model:\n  default: claude-opus-5-5\n  provider: anthropic\nagent:\n  reasoning_effort: high\ndelegation:\n  reasoning_effort: high\n"


def audit(jobs, cfg=CFG):
    d = Path(tempfile.mkdtemp())
    (d / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    (d / "config.yaml").write_text(cfg)
    h.alerts.clear()
    return h.check_model_pins(str(d / "jobs.json"), str(d / "config.yaml"))


def test_all_on_policy_is_silent():
    r = audit([{"id": "a", "name": "Beta", **GOOD}, {"id": "b", "name": "Charlie", **GOOD}])
    assert r["crons_ok"] == 2 and r["crons_total"] == 2 and not r["mismatches"] and not h.alerts, r


def test_glm_cron_is_flagged():
    r = audit([{"id": "a", "name": "Beta", **GOOD},
               {"id": "b", "name": "Old GLM job", "model": "glm-5.2", "provider": "zai", "reasoning_effort": "high"}])
    assert r["crons_ok"] == 1 and any("Old GLM job" in m for m in r["mismatches"]) and h.alerts, r


def test_low_effort_is_flagged():
    r = audit([{"id": "a", "name": "Beta", **{**GOOD, "reasoning_effort": "medium"}}])
    assert r["mismatches"], r


def test_paused_and_script_only_jobs_are_out_of_scope():
    r = audit([{"id": "a", "name": "Alpha", "state": "paused", "model": "glm-5.2"},
               {"id": "b", "name": "price watch", "no_agent": True, "model": None}])
    assert r["crons_total"] == 0 and not r["mismatches"], r


def test_chat_default_must_be_opus():
    r = audit([{"id": "a", "name": "Beta", **GOOD}], cfg=CFG.replace("claude-opus-5-5", "glm-5.3"))
    assert any(m.startswith("chat =") for m in r["mismatches"]), r


def test_missing_pyyaml_is_a_tooling_warning_not_a_policy_breach():
    saved = sys.modules.get("yaml")
    sys.modules["yaml"] = None          # makes `import yaml` raise ImportError
    try:
        r = audit([{"id": "a", "name": "Beta", **GOOD}])
    finally:
        if saved is not None:
            sys.modules["yaml"] = saved
        else:
            sys.modules.pop("yaml", None)
    assert not r["mismatches"], r                       # the fallback reader still verifies the pins
    assert r["chat"] == ("claude-opus-5-5", "anthropic", "high"), r
    assert not any("not on Claude Opus" in a for a in h.alerts), h.alerts


def test_unreadable_config_is_reported_as_unverified():
    r = audit([{"id": "a", "name": "Beta", **GOOD}], cfg="::: not yaml :::\n\t- [")
    assert not r["mismatches"] and r["errors"], r
    assert any("could not verify" in a for a in h.alerts) and not any("not on Claude Opus" in a for a in h.alerts), h.alerts


def test_model_status_never_lists_retired_models_as_operational():
    r = audit([{"id": "a", "name": "Beta", **GOOD}])
    md = h.render_model_status(r, "now")
    assert "claude-fable-5-1" in md and "3 independent runs" in md and "ALL ON POLICY" in md
    for line in md.splitlines():
        if "GLM" in line or "Deepseek" in line:
            assert "retired" in line and "✅" not in line, line


def test_zero_active_crons_is_unverified_not_on_policy():
    r = audit([])
    assert r["errors"] and "ALL ON POLICY" not in h.render_model_status(r, "now"), r


def test_judge_models_come_from_judge_vote():
    import judge_vote
    assert h.JUDGE_HIGH == judge_vote.FABLE and h.JUDGE_ROUTINE == judge_vote.ROUTINE_MODEL
    assert h.SHARED_IMPORT_ERROR is None and "place_option_order" in h.BROKER_WRITE_TOOLS


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("✓", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("✗", name, "→", type(e).__name__, e)
    sys.exit(1 if fails else 0)
