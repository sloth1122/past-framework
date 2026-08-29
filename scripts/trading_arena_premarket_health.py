#!/usr/bin/env python3
"""
Trading Arena — Pre-Market Health Check (Watchdog)
Runs at 5 AM MST / 7 AM EST Mon-Fri, 2 hours before agents trade.

Verifies ALL dependencies the agents need to execute trades:
  1. Claude Code + OAuth token (Judge gate + Robinhood MCP)
  2. Z.AI API (GLM-5.2 for agent reasoning)
  3. Ollama (Deepseek R1 fallback for Judge/Beta)
  4. Robinhood MCP (end-to-end trade path via claude -p)
  5. State files exist and are fresh

Output: stdout. Non-empty = ALERT (delivered to Telegram by cron).
        Empty stdout = SILENT (all checks passed).
        Non-zero exit = ERROR (cron delivers error alert).
"""
import subprocess
import os
import sys
import json
import re
import datetime
import glob

# ── Paths ──
CLAUDE_BIN = "/Users/johntytko/.local/bin/claude"
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
STATE_DIR = "/Users/johntytko/trading-arena/state"
AGENT_ALPHA_STATE = f"{STATE_DIR}/agent_alpha/state.md"
AGENT_BETA_STATE = f"{STATE_DIR}/agent_beta/state.md"
THESIS_QUEUE = f"{STATE_DIR}/thesis_queue.md"
JUDGE_LOG = f"{STATE_DIR}/judge_decision_log.md"
MODEL_STATUS = f"{STATE_DIR}/model_status.md"

# ── Thresholds ──
TOKEN_WARN_HOURS = 4       # alert if <4h left on Claude OAuth
STATE_STALE_HOURS = 48     # alert if state files older than 2 days
CLAUDE_TIMEOUT = 90
ZAI_TIMEOUT = 15
OLLAMA_TIMEOUT = 10

alerts = []

def alert(msg):
    """Add to alert list."""
    alerts.append(msg)

def check_claude_oauth_and_connectivity():
    """Check Claude OAuth token AND connectivity together.

    Mirrors the token monitor logic:
    - If token has >4h remaining → healthy, skip connectivity test (fast)
    - If token is near/expired → test connectivity (triggers auto-refresh)
    - If connectivity passes → healthy (auto-refresh worked)
    - If connectivity fails → CRITICAL (trading is down)
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
        access_token = oauth.get("accessToken", "")

        if not access_token:
            alert("CRITICAL: Claude OAuth accessToken is EMPTY. "
                  "Robinhood MCP cannot connect. Run `claude auth login`.")
            return

        hours_left = None
        if expires_ms:
            expires_dt = datetime.datetime.fromtimestamp(expires_ms / 1000)
            hours_left = (expires_dt - datetime.datetime.now()).total_seconds() / 3600

        # Token healthy (>4h) → no need to test connectivity
        if hours_left is not None and hours_left > TOKEN_WARN_HOURS:
            return  # Token is fresh, Claude should work

        # Token near/expired → test connectivity (triggers auto-refresh)
        claude_ok = test_claude_connectivity()

        if claude_ok:
            # Auto-refresh worked — token is fine despite stale timestamp
            return

        # Connectivity failed
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
    """Run minimal claude -p call. Verifies OAuth auto-refresh + MCP available.
    Returns True if Claude works, False otherwise."""
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

def test_zai_api():
    """Check Z.AI API (GLM-5.2 for agent reasoning). Returns True if healthy."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "-m", str(ZAI_TIMEOUT), "https://api.z.ai/api/payload/v1/models"],
            capture_output=True, text=True, timeout=ZAI_TIMEOUT + 5
        )
        code = result.stdout.strip()
        if code != "200":
            alert(f"WARNING: Z.AI API returned HTTP {code} (expected 200). "
                  f"GLM-5.2 (agent reasoning) may be down. "
                  f"Check .env for ZAI_API_KEY or plan credits.")
            return False
        return True
    except Exception as e:
        alert(f"WARNING: Z.AI API check failed: {e}. "
              f"GLM-5.2 (agent reasoning) may be down.")
        return False

def test_ollama():
    """Check Ollama (Deepseek R1 fallback for Judge/Beta). Returns True if healthy."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=OLLAMA_TIMEOUT
        )
        if result.returncode != 0:
            alert(f"WARNING: Ollama not responding (exit {result.returncode}). "
                  f"Deepseek R1 fallback is DOWN. Start with `ollama serve`.")
            return False
        if "deepseek-r1:70b" not in result.stdout:
            alert("WARNING: Ollama running but deepseek-r1:70b not found. "
                  "Judge/Beta fallback is unavailable. Run `ollama pull deepseek-r1:70b`.")
            return False
        return True
    except FileNotFoundError:
        alert("WARNING: Ollama not installed. Judge/Beta fallback is unavailable.")
        return False
    except subprocess.TimeoutExpired:
        alert(f"WARNING: Ollama timed out after {OLLAMA_TIMEOUT}s. "
              f"Fallback model may be hung. Try `ollama serve`.")
        return False
    except Exception as e:
        alert(f"WARNING: Ollama check error: {e}")
        return False

def test_robinhood_mcp():
    """Quick Robinhood MCP test via claude -p (read-only account check).
    Returns True if healthy."""
    try:
        cmd = ("Use the robinhood-trading MCP to get_account overview for the account "
               "with nickname 'Agentic' ending in 8877. Report just the buying power "
               "preceded by the exact marker MCP_OK: (e.g. 'MCP_OK:5000.00'). "
               "If MCP is not available, reply: MCP_UNAVAILABLE")
        result = subprocess.run(
            [CLAUDE_BIN, "-p", cmd,
             "--max-turns", "10", "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            alert(f"CRITICAL: Robinhood MCP test FAILED (exit {result.returncode}). "
                  f"Trades cannot execute. Check MCP server config. "
                  f"Stderr: {result.stderr[:200] if result.stderr else 'none'}")
            return False
        if "MCP_UNAVAILABLE" in result.stdout:
            alert("CRITICAL: Robinhood MCP server is NOT connected to Claude Code. "
                  "Trades cannot execute. Check `claude mcp list` or restart Claude.")
            return False
        # Require exact MCP_OK:<buying_power> numeric response to prove get_account completed
        mcp_match = re.fullmatch(
            r"MCP_OK:\d+(?:\.\d{2})?",
            result.stdout.strip(),
        )
        if mcp_match:
            return True  # MCP is working — got explicit numeric buying-power response
        # No explicit marker — treat as failure
        alert("CRITICAL: Robinhood MCP test returned no MCP_OK marker. "
              "get_account did not complete or MCP is partially down. "
              "Verify manually: `claude -p 'get account 8877'`")
        return False
    except subprocess.TimeoutExpired:
        alert("CRITICAL: Robinhood MCP test timed out (180s). "
              "MCP server may be hung. Trades cannot execute.")
        return False
    except Exception as e:
        alert(f"CRITICAL: Robinhood MCP test error: {e}")
        return False

def check_state_files():
    """Check that state files exist and are recent."""
    now = datetime.datetime.now()
    required = {
        "Agent Alpha state": AGENT_ALPHA_STATE,
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

def update_model_status(zai_ok=False, ollama_ok=False, mcp_ok=False):
    """Auto-update model_status.md with current timestamp and actual probe results.
    Only writes ALL OPERATIONAL when all probes succeeded."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M MT")
        all_ok = zai_ok and ollama_ok and mcp_ok
        if all_ok:
            status_line = "## Current Status: ALL OPERATIONAL\n\n"
            header_note = "> All models operational (verified by health check).\n\n"
        else:
            failed = []
            if not zai_ok:
                failed.append("Z.AI/GLM-5.2")
            if not ollama_ok:
                failed.append("Ollama/Deepseek R1")
            if not mcp_ok:
                failed.append("Robinhood MCP/Claude")
            status_line = f"## Current Status: DEGRADED ({', '.join(failed)} failed)\n\n"
            header_note = "> One or more probes failed — see alerts above.\n\n"
        with open(MODEL_STATUS, 'w') as f:
            f.write("# Model Status — Trading Arena\n\n")
            f.write(f"> Auto-updated by pre-market health check: {now}\n")
            f.write(header_note)
            f.write(status_line)
            f.write("| Model | Provider | Status |\n")
            f.write("|---|---|---|\n")
            f.write(f"| GLM-5.2 | Z.AI (cloud) | {'✅ Active' if zai_ok else '❌ Down'} |\n")
            f.write(f"| Deepseek R1 70B | Ollama (local) | {'✅ Fallback' if ollama_ok else '❌ Down'} |\n")
            f.write(f"| Claude Fable 5 | Claude Code | {'✅ Judge gate' if mcp_ok else '❌ Down'} |\n")
    except Exception as e:
        alert(f"WARNING: Failed to update model_status.md: {e}")

def main():
    # Clean up zombie cron executions first (prevents 7 AM agent crons from being blocked)
    try:
        import subprocess
        subprocess.run(['python3', os.path.expanduser('~/.hermes/scripts/cron_zombie_cleanup.py')],
                      capture_output=True, text=True, timeout=30)
    except Exception:
        pass  # Non-critical — don't fail the health check if cleanup has an issue

    # Run all checks
    check_claude_oauth_and_connectivity()  # 1+2. OAuth token + Claude connectivity
    zai_ok = test_zai_api()             # 3. Z.AI API (GLM-5.2)
    ollama_ok = test_ollama()           # 4. Ollama fallback
    mcp_ok = test_robinhood_mcp()       # 5. Robinhood MCP end-to-end

    # Auto-update model_status.md BEFORE checking state files (so it's always fresh)
    update_model_status(zai_ok=zai_ok, ollama_ok=ollama_ok, mcp_ok=mcp_ok)

    check_state_files()         # 6. State files exist & fresh (now sees fresh model_status)

    # Output: non-empty stdout = ALERT (cron delivers to Telegram)
    # Empty stdout = SILENT (all checks passed)
    if alerts:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z")
        print(f"🔴 TRADING ARENA PRE-MARKET HEALTH CHECK — {timestamp}")
        print(f"   {len(alerts)} issue(s) detected. Agents run in ~2h.")
        print()
        for i, a in enumerate(alerts, 1):
            print(f"   {i}. {a}")
        print()
        print("   Agents scheduled: 7:00 AM MST (Alpha + Beta)")
        print("   If CRITICAL issues remain, agents may fail to trade.")
        print("   Fix before market open or pause cron jobs.")
        sys.exit(0)  # exit 0 so cron delivers the alert message
    else:
        # Silent — all checks passed
        sys.exit(0)

if __name__ == "__main__":
    main()
