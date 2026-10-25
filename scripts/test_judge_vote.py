#!/usr/bin/env python3
"""Tests for the risk-tiered Judge runner (no network, no Claude calls).

A fake Judge script stands in for `claude -p`; per-run behaviour is scripted with
FAKE_PLAN = {"r1": ["garbage", "approve"], ...} (one action per attempt).
"""
import json, os, random, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "judge_vote.py"
sys.path.insert(0, str(HERE))
import judge_vote as jv  # noqa: E402

FAKE = r'''
import json, os, re, sys, time
from pathlib import Path
args = sys.argv[1:]; model = args[args.index("--model") + 1]; prompt = args[-1]
st = Path(os.environ["FAKE_DIR"])
if prompt.startswith("Preflight"):
    pc = st / "preflight.n"; n = int(pc.read_text()) if pc.exists() else 0; pc.write_text(str(n + 1))
    after = os.environ.get("FAKE_FABLE_DOWN_AFTER")
    down = os.environ.get("FAKE_FABLE_DOWN") or (after is not None and n >= int(after))
    print("model unavailable" if down and "fable" in model else "OK"); sys.exit(0)
rid = re.search(r'"run_id": "([^"]+)"', prompt).group(1)
key = rid.rsplit("-", 1)[-1]
cnt = st / (rid + ".n"); n = int(cnt.read_text()) if cnt.exists() else 0; cnt.write_text(str(n + 1))
with (st / "calls.log").open("a") as f: f.write(f"{model} {key}\n")
plan = json.loads(os.environ.get("FAKE_PLAN", "{}")).get(key, ["approve"])
act = plan[min(n, len(plan) - 1)]
v = lambda x: json.dumps({"run_id": rid, "vote": x, "reason": "fake " + x})
if act in ("approve", "reject"): print("analysis ...\n" + v(act))
elif act == "dup": print(v("approve") + "\n" + v("approve"))
elif act == "conflict": print(v("approve") + "\n" + v("reject"))
elif act == "garbage": print("VOTE | AMD | APPROVED | old format")
elif act == "wrongid": print(json.dumps({"run_id": "someone-else", "vote": "approve", "reason": "r"}))
elif act == "sleep": time.sleep(3)
elif act == "rcfail": print(v("approve")); sys.exit(1)
'''
STOCK = ["--ticker", "MSFT", "--instrument", "stock", "--notional", "900"]
OPTION = ["--ticker", "AMD", "--instrument", "option"]


def run(args, plan=None, fable_down=False, fable_down_after=None,
        queue="## THESIS SUBMISSION — Beta — AMD (PENDING)\nbuy shares\n",
        config=None, raw_config=None, shadow="0", seed_trades=0):
    d = Path(tempfile.mkdtemp())
    (d / "fake.py").write_text(FAKE)
    (d / "queue.md").write_text(queue)
    (d / "cfg.json").write_text(raw_config if raw_config is not None else json.dumps(config or {}))
    if seed_trades:
        (d / "votes").mkdir()
        (d / "votes" / "trades.jsonl").write_text("".join(
            json.dumps({"tier": "high", "split": False, "failover": False}) + "\n" for _ in range(seed_trades)))
    env = {**os.environ, "FAKE_DIR": str(d), "FAKE_PLAN": json.dumps(plan or {})}
    if fable_down:
        env["FAKE_FABLE_DOWN"] = "1"
    if fable_down_after is not None:
        env["FAKE_FABLE_DOWN_AFTER"] = str(fable_down_after)
    cmd = [sys.executable, str(RUNNER), *args, "--queue", str(d / "queue.md"), "--votes-dir", str(d / "votes"),
           "--config", str(d / "cfg.json"), "--judge-cmd", f"{sys.executable} {d / 'fake.py'}",
           "--run-timeout", "2", "--shadow-rate", shadow]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    calls = (d / "calls.log").read_text().split("\n") if (d / "calls.log").exists() else []
    trades = [json.loads(l) for l in (d / "votes" / "trades.jsonl").read_text().splitlines()] \
        if (d / "votes" / "trades.jsonl").exists() else []
    return p, [c for c in calls if c], trades, d


def test_routine_stock_one_opus_run():
    p, calls, t, _ = run(STOCK)
    assert p.returncode == 0 and "MSFT: APPROVED" in p.stdout, p.stdout + p.stderr
    assert calls == ["claude-opus-5-5 r1"], calls
    assert t[-1]["tier"] == "routine" and t[-1]["runs_required"] == 1


def test_option_three_fable_runs_unanimous():
    p, calls, t, _ = run(OPTION)
    assert p.returncode == 0 and "AMD: APPROVED" in p.stdout, p.stdout
    assert sorted(calls) == ["claude-fable-5-1 r1", "claude-fable-5-1 r2", "claude-fable-5-1 r3"], calls
    assert t[-1]["tier"] == "high" and t[-1]["valid_votes"] == 3


def test_duplicate_vote_line_is_not_a_rejection():
    """The Oct 24 bug: a repeated vote line turned 3/3 approvals into REJECTED (4/3)."""
    p, _, t, _ = run(OPTION, plan={"r2": ["dup"]})
    assert p.returncode == 0 and "AMD: APPROVED" in p.stdout, p.stdout
    assert t[-1]["approvals"] == 3


def test_conflicting_vote_rerun_once_then_reject():
    p, calls, _, _ = run(OPTION, plan={"r2": ["conflict", "conflict"]})
    assert p.returncode == 2 and "AMD: REJECTED" in p.stdout and "conflicting" in p.stdout, p.stdout
    assert calls.count("claude-fable-5-1 r2") == 2, calls


def test_malformed_then_valid_on_rerun_counts():
    p, calls, _, _ = run(OPTION, plan={"r1": ["garbage", "approve"]})
    assert p.returncode == 0 and "AMD: APPROVED" in p.stdout, p.stdout
    assert calls.count("claude-fable-5-1 r1") == 2


def test_wrong_run_id_is_invalid():
    p, _, _, _ = run(STOCK, plan={"r1": ["wrongid", "wrongid"]})
    assert p.returncode == 2 and "wrong run_id" in p.stdout, p.stdout


def test_one_reject_is_logged_as_split():
    p, _, t, _ = run(OPTION, plan={"r3": ["reject"]})
    assert p.returncode == 2 and "SPLIT" in p.stdout, p.stdout
    assert t[-1]["split"] is True and t[-1]["approvals"] == 2


def test_two_approve_one_invalid_counts_as_split():
    p, _, t, _ = run(OPTION, plan={"r3": ["garbage", "garbage"]})
    assert p.returncode == 2 and t[-1]["split"] is True and t[-1]["invalid_runs"] == 1, t


def test_fable_unavailable_fails_over_to_opus_three_runs():
    p, calls, t, _ = run(OPTION, fable_down=True)
    assert p.returncode == 0 and "FAILOVER" in p.stdout, p.stdout
    assert sorted(calls) == ["claude-opus-5-5 r1", "claude-opus-5-5 r2", "claude-opus-5-5 r3"], calls
    assert t[-1]["failover"] is True and t[-1]["runs_required"] == 3


def test_fable_dying_mid_run_reruns_on_opus():
    """Preflight passes, then Fable stops answering: the failed run's re-run uses Opus."""
    p, calls, t, _ = run(OPTION, plan={"r2": ["sleep", "approve"]}, fable_down_after=1)
    assert p.returncode == 0 and "Opus failover" in p.stdout and "FAILOVER" in p.stdout, p.stdout
    assert "claude-fable-5-1 r2" in calls and "claude-opus-5-5 r2" in calls, calls
    assert t[-1]["failover"] is True


def test_failover_skips_shadow_and_logs_why():
    _, calls, t, _ = run(OPTION, fable_down=True, shadow="1")
    assert not any("shadow" in c for c in calls) and t[-1]["shadow"] == "skipped (failover)", (calls, t)


def test_option_terms_in_thesis_force_high_tier():
    q = "## THESIS SUBMISSION — Beta — AMD (PENDING)\nBuy the AMD 250/260 call debit spread, expiration Nov 20\n"
    _, calls, t, _ = run(["--ticker", "AMD", "--instrument", "stock", "--notional", "500"], queue=q)
    assert t[-1]["tier"] == "high" and len(calls) == 3, (t, calls)


def test_option_terms_without_pending_tag_still_escalate():
    q = "## THESIS SUBMISSION — Beta — AMD\nBuy the AMD 250/260 call debit spread, expiration Nov 20\n"
    _, calls, t, _ = run(["--ticker", "AMD", "--instrument", "stock", "--notional", "500"], queue=q)
    assert t[-1]["tier"] == "high" and len(calls) == 3, (t, calls)


def test_compact_option_notation_forces_high_tier():
    q = "## THESIS SUBMISSION — Beta — AMD (PENDING)\nBuy 1 AMD 250C 11/20\n"
    _, calls, t, _ = run(["--ticker", "AMD", "--instrument", "stock", "--notional", "500"], queue=q)
    assert t[-1]["tier"] == "high" and len(calls) == 3, (t, calls)


def test_timeout_rejects_after_one_rerun():
    p, calls, _, _ = run(STOCK, plan={"r1": ["sleep", "sleep"]})
    assert p.returncode == 2 and "timeout" in p.stdout, p.stdout
    assert calls.count("claude-opus-5-5 r1") == 2


def test_time_sensitive_timeout_rejects_without_rerun():
    p, calls, _, _ = run(STOCK + ["--time-sensitive"], plan={"r1": ["sleep", "approve"]})
    assert p.returncode == 2 and "time-sensitive" in p.stdout, p.stdout
    assert calls.count("claude-opus-5-5 r1") == 1, calls


def test_nonzero_exit_vote_is_invalid():
    """A claude process that crashes after printing a valid-looking vote must not count."""
    p, calls, _, _ = run(STOCK, plan={"r1": ["rcfail", "rcfail"]})
    assert p.returncode == 2 and "exited 1" in p.stdout, p.stdout
    assert calls.count("claude-opus-5-5 r1") == 2


def test_stock_without_notional_is_logged_reject():
    p, calls, t, _ = run(["--ticker", "MSFT", "--instrument", "stock"])
    assert p.returncode == 2 and "MSFT: REJECTED" in p.stdout and "--notional" in p.stdout, p.stdout
    assert calls == [] and t[-1]["tier"] == "error"


def test_malformed_config_is_logged_reject():
    p, calls, t, _ = run(OPTION, raw_config="{not json")
    assert p.returncode == 2 and "AMD: REJECTED" in p.stdout and "config" in p.stdout, p.stdout
    assert calls == [] and t[-1]["final"] == "REJECTED"


def test_shadow_is_logged_and_non_voting():
    p, calls, _, d = run(OPTION, plan={"shadow": ["reject"]}, shadow="1")
    assert p.returncode == 0 and "AMD: APPROVED" in p.stdout and "DISAGREES" in p.stdout, p.stdout
    assert "claude-opus-5-5 shadow" in calls
    s = [json.loads(l) for l in (d / "votes" / "shadow.jsonl").read_text().splitlines()]
    assert s[-1]["agree"] is False and s[-1]["fable_final"] == "APPROVED"


def test_shadow_sampling_is_about_ten_percent():
    rnd = random.Random(7)  # noqa: S311 — deterministic test sampling
    hits = sum(jv.shadow_sampled(0.10, rnd.random) for _ in range(20000))
    assert 0.09 < hits / 20000 < 0.11, hits


def test_size_threshold_escalates_stock():
    p, calls, t, _ = run(["--ticker", "MSFT", "--instrument", "stock", "--notional", "3000"],
                         config={"high_risk_notional_usd": 2500})
    assert t[-1]["tier"] == "high" and len(calls) == 3 and "threshold" in p.stdout, (t, p.stdout)


def test_report_counts_splits():
    _, _, _, d = run(OPTION, plan={"r3": ["reject"]})
    r = subprocess.run([sys.executable, str(RUNNER), "--report", "--votes-dir", str(d / "votes")],
                       capture_output=True, text=True)
    assert "High-risk trades judged: 1 · splits 1 (100%)" in r.stdout, r.stdout


def test_milestone_announced_once():
    p, _, _, d = run(OPTION, seed_trades=49)
    assert "MILESTONE — REPORT TO JOHN: 50 high-risk trades" in p.stdout, p.stdout
    assert (d / "votes" / "milestones.json").exists()
    env = {**os.environ, "FAKE_DIR": str(d), "FAKE_PLAN": "{}"}
    p2 = subprocess.run([sys.executable, str(RUNNER), *OPTION, "--queue", str(d / "queue.md"),
                         "--votes-dir", str(d / "votes"), "--config", str(d / "cfg.json"),
                         "--judge-cmd", f"{sys.executable} {d / 'fake.py'}", "--run-timeout", "2",
                         "--shadow-rate", "0"], capture_output=True, text=True, env=env)
    assert "MILESTONE" not in p2.stdout and "High-risk trades judged: 51" in p2.stdout, p2.stdout


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("✓", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("✗", name, "→", type(e).__name__, str(e)[:300])
    sys.exit(1 if fails else 0)
