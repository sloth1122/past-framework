#!/usr/bin/env python3
"""
Trading Arena — Pre-Market Health Check (Watchdog)
Runs before the agents trade (Beta 7:05 AM MT; Alpha retired Oct 22 2026).

Verifies everything the arena needs to trade:
  1. Claude Code + OAuth token (Judge gate + Robinhood MCP)
  2. Model pins: every Hermes chat, subagent and agent cron runs Claude Opus 5.5
     (claude-opus-5-5, anthropic, effort high). The Judge routes by risk tier
     (scripts/judge_vote.py): high-risk → Fable 5.1 high ×3, routine → Opus 5.5 high ×1.
  3. Robinhood MCP (end-to-end, read-only; broker write tools denied)
  4. Gate 1 pre-gate self-test
  5. State files exist and are fresh; model_status.md rewritten from the live check
GLM/Z.AI (retired Oct 19 2026) and local Ollama models (retired Oct 11 2026) are no
longer checked or listed as operational.

Output: stdout. Non-empty = ALERT (delivered to Telegram by cron).
        Empty stdout = SILENT (all checks passed).
        Non-zero exit = ERROR (cron delivers error alert).
"""
import subprocess
import os
import sys
import json
import datetime

# Shared arena modules (account last-4, broker deny-list, Judge model routing) live next to
# this script in the repo and in ~/trading-arena/scripts in the live deployment. Importing
# them keeps ONE source of truth; if they are missing the check alerts instead of guessing.
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), "/Users/johntytko/trading-arena/scripts"]
try:
    from arena_account import arena_account_last4
    from broker_read import BROKER_WRITE_TOOLS
    import judge_vote as _jv
    JUDGE_HIGH, JUDGE_ROUTINE, JUDGE_SHADOW_DEFAULT = _jv.FABLE, _jv.ROUTINE_MODEL, _jv.DEFAULT_SHADOW_RATE
    JUDGE_CONFIG = str(_jv.CONFIG)
    SHARED_IMPORT_ERROR = None
except Exception as _e:  # noqa: BLE001 — reported as an alert in main()
    SHARED_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"
    arena_account_last4 = lambda: ""  # noqa: E731 — probe then reports "not configured"
    BROKER_WRITE_TOOLS = None
    JUDGE_HIGH = JUDGE_ROUTINE = "unknown (judge_vote.py not importable)"
    JUDGE_SHADOW_DEFAULT, JUDGE_CONFIG = 0.10, ""

# ── Paths ──
CLAUDE_BIN = "/Users/johntytko/.local/bin/claude"
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
HERMES_JOBS = os.path.expanduser("~/.hermes/cron/jobs.json")
HERMES_CONFIG = os.path.expanduser("~/.hermes/config.yaml")
STATE_DIR = "/Users/johntytko/trading-arena/state"
AGENT_BETA_STATE = f"{STATE_DIR}/agent_beta/state.md"
THESIS_QUEUE = f"{STATE_DIR}/thesis_queue.md"
JUDGE_LOG = f"{STATE_DIR}/judge_decision_log.md"
MODEL_STATUS = f"{STATE_DIR}/model_status.md"

# ── Model policy (John, Oct 19 + Oct 24 2026) ──
REQUIRED = ("claude-opus-5-5", "anthropic", "high")   # every chat, subagent and agent cron
# Judge models come from judge_vote.py (imported above) — not restated here.

# ── Thresholds ──
TOKEN_WARN_HOURS = 4       # alert if <4h left on Claude OAuth
STATE_STALE_HOURS = 48     # alert if state files older than 2 days
CLAUDE_TIMEOUT = 90

alerts = []


def alert(msg):
    """Add to alert list."""
    alerts.append(msg)


def check_claude_oauth_and_connectivity():
    """Check Claude OAuth token AND connectivity together.

    - Token has >4h remaining → healthy, skip connectivity test (fast)
    - Token near/expired → test connectivity (triggers auto-refresh)
    - Connectivity passes → healthy; fails → CRITICAL (trading is down)
    """
    if not os.path.exists(CREDENTIALS_PATH):
        alert("CRITICAL: Claude credentials file missing (~/.claude/.credentials.json). "
              "Robinhood MCP is DOWN. Run `claude auth login`.")
        return
    try:
        with open(CREDENTIALS_PATH) as f:
            d = json.load(f)
        oauth = d.get("claudeAiOauth", {})
        expires_ms = oauth.get("expiresAt", 0)
        if not oauth.get("accessToken", ""):
            alert("CRITICAL: Claude OAuth accessToken is EMPTY. "
                  "Robinhood MCP cannot connect. Run `claude auth login`.")
            return
        hours_left = None
        if expires_ms:
            expires_dt = datetime.datetime.fromtimestamp(expires_ms / 1000)
            hours_left = (expires_dt - datetime.datetime.now()).total_seconds() / 3600
        if hours_left is not None and hours_left > TOKEN_WARN_HOURS:
            return
        if test_claude_connectivity():
            return
        if hours_left is not None and hours_left < 0:
            alert(f"CRITICAL: Claude OAuth token expired {abs(hours_left):.1f}h ago "
                  f"and auto-refresh FAILED. Judge gate + Robinhood MCP are DOWN. "
                  f"Run `claude auth login` NOW.")
        else:
            alert("CRITICAL: Claude Code connectivity test FAILED. "
                  "Judge gate + Robinhood MCP are DOWN. "
                  "Run `claude auth login` or check Claude installation.")
    except Exception as e:
        alert(f"ERROR reading Claude credentials: {e}")


def test_claude_connectivity():
    """Minimal claude -p call. Verifies OAuth auto-refresh. True if Claude works."""
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "Reply with exactly: OK",
             "--max-turns", "1", "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
        )
        return result.returncode == 0 and "OK" in result.stdout.upper()
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        alert(f"CRITICAL: Claude Code binary not found at {CLAUDE_BIN}.")
        return False
    except Exception:
        return False


def read_hermes_config(path):
    """Top-level sections of ~/.hermes/config.yaml. PyYAML when available; otherwise a
    minimal reader for `section:` / `  key: value` lines — enough for model/agent/delegation."""
    with open(path) as f:
        text = f.read()
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        c = yaml.safe_load(text)
        if not isinstance(c, dict) or not isinstance(c.get("model"), dict):
            raise ValueError("no 'model:' section")
        return c
    out, sec = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and line.rstrip().endswith(":"):
            sec = line.strip()[:-1]
            out[sec] = {}
        elif sec and line.startswith("  ") and not line.startswith("   ") and ":" in line:
            k, _, v = line.strip().partition(":")
            out[sec][k.strip()] = v.strip().strip("'\"") or None
    if not isinstance(out.get("model"), dict) or not out["model"]:
        raise ValueError("no 'model:' section")
    return out


def check_model_pins(jobs_path=HERMES_JOBS, config_path=HERMES_CONFIG):
    """Every Hermes chat, subagent and agent cron must run Claude Opus 5.5, high effort.
    Policy breaches ("mismatches") and tooling failures ("errors") are reported separately,
    so an unreadable file is never presented as a model-policy violation.
    Returns {"crons_ok", "crons_total", "chat", "subagents", "mismatches", "errors"}."""
    res = {"crons_ok": 0, "crons_total": 0, "chat": None, "subagents": None, "mismatches": [], "errors": []}
    try:
        with open(jobs_path) as f:
            d = json.load(f)
        jobs = d.get("jobs", d) if isinstance(d, dict) else d
        for j in jobs:
            if not j.get("enabled", True) or j.get("state") == "paused" or j.get("no_agent"):
                continue          # paused jobs and plain scripts (no LLM) are out of scope
            res["crons_total"] += 1
            got = (j.get("model"), j.get("provider"), j.get("reasoning_effort"))
            if got == REQUIRED:
                res["crons_ok"] += 1
            else:
                res["mismatches"].append(f"cron '{j.get('name', j.get('id'))}' = {'/'.join(map(str, got))}")
        if res["crons_total"] == 0:
            res["errors"].append("no active agent crons found (is Beta's cron paused?)")
    except Exception as e:
        res["errors"].append(f"could not read {jobs_path}: {e}")
    try:
        c = read_hermes_config(config_path)
        m, agent, dele = c.get("model") or {}, c.get("agent") or {}, c.get("delegation") or {}
        res["chat"] = (m.get("default"), m.get("provider"), agent.get("reasoning_effort"))
        # subagents inherit the chat model unless delegation pins its own
        res["subagents"] = (dele.get("model") or m.get("default"), dele.get("provider") or m.get("provider"),
                            dele.get("reasoning_effort") or agent.get("reasoning_effort"))
        for name in ("chat", "subagents"):
            if res[name] != REQUIRED:
                res["mismatches"].append(f"{name} = {'/'.join(map(str, res[name]))}")
    except Exception as e:
        res["errors"].append(f"could not read {config_path}: {e} (python {sys.executable})")
    if res["errors"]:
        alert("WARNING: could not verify model pins — " + "; ".join(res["errors"]))
    if res["mismatches"]:
        alert("WARNING: not on Claude Opus 5.5 high (claude-opus-5-5/anthropic/high): "
              + "; ".join(res["mismatches"]) + ". Fix: `hermes cron edit <id> --model claude-opus-5-5 "
              "--provider anthropic --reasoning-effort high`.")
    return res


def test_robinhood_mcp():
    """Quick Robinhood MCP test via claude -p (read-only account check)."""
    last4 = arena_account_last4()
    if not last4 or BROKER_WRITE_TOOLS is None:
        alert("WARNING: arena account not configured (set ARENA_ACCOUNT_LAST4 or "
              "state/arena_account_last4) — Robinhood MCP probe skipped.")
        return
    try:
        cmd = ("Use the robinhood-trading MCP to get_account overview for the account "
               f"ending in {last4} (nickname 'MCP'). Report just the buying power. "
               "Do NOT place, cancel, or modify any order. "
               "If MCP is not available, reply: MCP_UNAVAILABLE")
        result = subprocess.run(
            [CLAUDE_BIN, "-p", cmd,
             "--max-turns", "10", "--dangerously-skip-permissions",
             "--disallowedTools", BROKER_WRITE_TOOLS],
            capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            alert(f"CRITICAL: Robinhood MCP test FAILED (exit {result.returncode}). "
                  f"Trades cannot execute. Check MCP server config. "
                  f"Stderr: {result.stderr[:200] if result.stderr else 'none'}")
            return
        if "MCP_UNAVAILABLE" in result.stdout:
            alert("CRITICAL: Robinhood MCP server is NOT connected to Claude Code. "
                  "Trades cannot execute. Check `claude mcp list` or restart Claude.")
            return
        if "buying power" in result.stdout.lower() or "$" in result.stdout:
            return  # MCP is working
        alert("WARNING: Robinhood MCP test returned unclear response. "
              "MCP may be partially down. Verify manually with a read-only `claude -p` account check.")
    except subprocess.TimeoutExpired:
        alert("CRITICAL: Robinhood MCP test timed out (180s). "
              "MCP server may be hung. Trades cannot execute.")
    except Exception as e:
        alert(f"CRITICAL: Robinhood MCP test error: {e}")


def check_gate1_selftest():
    """Gate 1 (trading-arena/gate1_pregate.py) is the deterministic thesis fact-check
    layer before the LLM Judge; its selftest encodes every historical Judge catch."""
    gate1_path = "/Users/johntytko/trading-arena/gate1_pregate.py"
    if not os.path.exists(gate1_path):
        alert("WARNING: Gate 1 pre-gate script missing: " + gate1_path +
              ". Thesis submissions will skip deterministic fact-checks.")
        return
    try:
        result = subprocess.run(
            [sys.executable, gate1_path, "--selftest"],
            capture_output=True, text=True, timeout=60)
        out = result.stdout.strip()
        if result.returncode == 0:
            return
        fail_lines = [l for l in out.splitlines() if "TEST FAILURE" in l or "NOT READY" in l]
        summary = "; ".join(fail_lines[:3]) if fail_lines else out[-200:]
        alert("CRITICAL: Gate 1 selftest FAILED — deterministic pre-gate may "
              "reject good theses or pass bad ones. " + summary)
    except subprocess.TimeoutExpired:
        alert("WARNING: Gate 1 selftest timed out (60s). Pre-gate integrity "
              "unverified this morning.")
    except Exception as e:
        alert(f"WARNING: Gate 1 selftest error: {e}")


def check_state_files():
    """Check that state files exist and are recent. (Alpha retired Oct 22 2026 — its
    state file is frozen by design and no longer checked.)"""
    now = datetime.datetime.now()
    required = {
        "Agent Beta state": AGENT_BETA_STATE,
        "Thesis queue": THESIS_QUEUE,
        "Judge log": JUDGE_LOG,
        "Model status": MODEL_STATUS,
    }
    for name, path in required.items():
        if not os.path.exists(path):
            alert(f"WARNING: {name} file missing: {path}. "
                  f"Agent may fail to read its state.")
            continue
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        age_hours = (now - mtime).total_seconds() / 3600
        if age_hours > STATE_STALE_HOURS:
            alert(f"WARNING: {name} is stale ({age_hours:.0f}h old, last modified "
                  f"{mtime.strftime('%b %d %H:%M')}). May cause agents to trade on "
                  f"outdated data.")


def shadow_rate():
    try:
        with open(JUDGE_CONFIG) as f:
            return float(json.load(f).get("shadow_rate", JUDGE_SHADOW_DEFAULT))
    except Exception:
        return JUDGE_SHADOW_DEFAULT


def render_model_status(pins, now):
    ok = not pins["mismatches"] and not pins.get("errors")
    fmt = lambda t: "/".join(map(str, t)) if t else "unknown"
    return "\n".join([
        "# Model Status — Trading Arena",
        "",
        f"> Auto-updated by the pre-market health check: {now}",
        f"> Model pins {'verified' if ok else 'NOT all verified — see alerts'}: "
        f"{pins['crons_ok']}/{pins['crons_total']} agent crons on Claude Opus 5.5 high; "
        f"chat {fmt(pins['chat'])}; subagents {fmt(pins['subagents'])}.",
        "",
        f"## Current status: {'ALL ON POLICY' if ok else ('MISMATCH' if pins['mismatches'] else 'UNVERIFIED')}",
        "",
        "| Role | Model | Effort | Status |",
        "|---|---|---|---|",
        "| Every Hermes chat, subagent and agent cron (Beta, Charlie, Rocky, research, reviews) "
        f"| Claude Opus 5.5 (`claude-opus-5-5`, Anthropic) | high | {'✅' if ok else '⚠️'} policy since Oct 19 2026 |",
        f"| Judge — HIGH-RISK tier (every option trade; crypto/leverage; stock above size threshold) "
        f"| Claude Fable 5.1 (`{JUDGE_HIGH}`) — 3 independent runs, unanimous | high | configured Oct 24 2026; availability is checked by judge_vote.py before every high-risk trade (failover below) |",
        f"| Judge — ROUTINE tier (all other stock trades) | Claude Opus 5.5 (`{JUDGE_ROUTINE}`) — 1 run | high | configured |",
        "| Judge failover (Fable 5.1 unavailable) | Claude Opus 5.5 — 3 runs, unanimous, logged \"failover\" | high | standby |",
        f"| Judge shadow test ({shadow_rate():.0%} of high-risk trades, non-voting) | Claude Opus 5.5 | high | configured (logs to state/judge_votes/shadow.jsonl) |",
        "| GLM-5.2 / 5.3 (Z.AI) | — | — | ⛔ retired Oct 19 2026 (subscription cancelled) |",
        "| Deepseek R1 / local Ollama models | — | — | ⛔ retired Oct 11 2026 |",
        "",
        "Agent Alpha: retired Oct 22 2026 (cron paused). Agent Beta: sole trading agent.",
        "",
    ])


def update_model_status(pins):
    """Rewrite model_status.md from the live pin check (so it can never claim stale models)."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M MT")
        with open(MODEL_STATUS, "w") as f:
            f.write(render_model_status(pins, now))
    except Exception:
        pass  # Non-critical — don't fail the health check


def main():
    # Clean up zombie cron executions first (prevents 7 AM agent crons from being blocked)
    try:
        subprocess.run(['python3', os.path.expanduser('~/.hermes/scripts/cron_zombie_cleanup.py')],
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass

    if SHARED_IMPORT_ERROR:
        alert("CRITICAL: shared arena modules not importable (" + SHARED_IMPORT_ERROR + "). "
              "Deploy arena_account.py, broker_read.py and judge_vote.py to ~/trading-arena/scripts.")
    check_claude_oauth_and_connectivity()   # 1. OAuth token + Claude connectivity
    pins = check_model_pins()               # 2. every chat/subagent/agent cron on Opus 5.5 high
    test_robinhood_mcp()                    # 3. Robinhood MCP end-to-end (read-only)
    check_gate1_selftest()                  # 4. Gate 1 pre-gate regression test
    update_model_status(pins)               # 5a. rewrite model_status.md BEFORE the freshness check
    check_state_files()                     # 5b. state files exist & fresh

    if alerts:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z")
        print(f"🔴 TRADING ARENA PRE-MARKET HEALTH CHECK — {timestamp}")
        print(f"   {len(alerts)} issue(s) detected. Agents run in ~2h.")
        print()
        for i, a in enumerate(alerts, 1):
            print(f"   {i}. {a}")
        print()
        print("   Agent scheduled: 7:05 AM MT (Beta — sole trading agent; Alpha retired Oct 22 2026)")
        print("   If CRITICAL issues remain, Beta may fail to trade.")
        print("   Fix before market open or pause the cron job.")
    sys.exit(0)  # exit 0 either way: stdout decides alert vs silent


if __name__ == "__main__":
    main()
