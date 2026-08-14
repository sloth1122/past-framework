#!/usr/bin/env python3
"""
Trading Arena — Error Analysis & Auto-Patch Layer

Runs as a script-only cron job. Queries the execution log database for
recent errors, analyzes patterns, and if a recurring error is detected,
triggers an LLM analysis that proposes a patch.

The analysis output is delivered to Telegram (via cron delivery) so the
user sees the diagnosis + proposed fix without having to dig through logs.

Pattern detection:
  - If the same error_type from the same source occurs 3+ times in 24h,
    it's a recurring pattern → trigger deep analysis
  - If a critical error occurs → immediate analysis (even single occurrence)
  - If no errors → silent (watchdog pattern)

Usage (CLI):
  python3 error_analyzer.py              # Check last 24h, alert if recurring
  python3 error_analyzer.py --hours 48   # Check last 48h
  python3 error_analyzer.py --dry-run    # Show what would be analyzed, don't call LLM
"""
import sys
import os
import json
import datetime

# Add the scripts directory to path for arena_logger
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arena_logger import get_error_summary, query_events, init_db

def analyze_errors(hours=24, dry_run=False):
    """Analyze recent errors and produce a diagnostic report.

    Returns: (should_alert: bool, report: str)
    """
    summary = get_error_summary(hours)

    if not summary:
        return False, ""  # No errors — silent

    # Check for recurring patterns (3+ occurrences of same error)
    recurring = [s for s in summary if s["count"] >= 3]
    criticals = [s for s in summary if s["severity"] == "critical"]

    # Only alert if there are recurring errors OR critical errors
    if not recurring and not criticals:
        return False, ""  # Isolated errors — not worth alerting

    # Build the diagnostic report
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z")
    report_lines = [
        f"TRADING ARENA — ERROR ANALYSIS — {now}",
        f"Reviewing last {hours}h of execution logs.",
        f"",
        f"=== RECURRING ERRORS (3+ occurrences) ===",
    ]

    for s in recurring:
        report_lines.append(
            f"  {s['source']:15s} | {s['severity']:8s} | {s['event_type']:25s} | "
            f"x{s['count']} | last: {s['last_occurrence'][:16]}"
        )
        report_lines.append(f"    sample: {s['sample_message']}")

    if criticals and not recurring:
        report_lines.append(f"")
        report_lines.append(f"=== CRITICAL ERRORS (immediate attention) ===")
        for s in criticals:
            report_lines.append(
                f"  {s['source']:15s} | {s['severity']:8s} | {s['event_type']:25s} | "
                f"x{s['count']} | last: {s['last_occurrence'][:16]}"
            )
            report_lines.append(f"    sample: {s['sample_message']}")

    # Fetch detailed error events for the top recurring pattern
    if recurring:
        top = recurring[0]
        details = query_events(
            source=top["source"],
            severity=top["severity"],
            event_type=top["event_type"],
            since=(datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat(),
            limit=5
        )
        report_lines.append(f"")
        report_lines.append(f"=== DETAILED LOGS (top pattern, last 5) ===")
        for d in details:
            report_lines.append(f"  [{d['timestamp'][:19]}] {d['message'][:150]}")
            if d.get("data_json"):
                try:
                    data = json.loads(d["data_json"])
                    if data:
                        report_lines.append(f"    data: {json.dumps(data)[:200]}")
                except json.JSONDecodeError:
                    pass

    # Pattern diagnosis (rule-based, no LLM needed for common patterns)
    report_lines.append(f"")
    report_lines.append(f"=== DIAGNOSIS ===")

    for s in summary:
        msg = s["sample_message"].lower()
        source = s["source"]
        etype = s["event_type"]

        if "timeout" in msg or "timed out" in msg:
            if "terminal_cwd" in msg or "write lock" in msg or "read lock" in msg:
                report_lines.append(
                    f"  {source}: Terminal lock contention (Hermes #79768). "
                    f"FIX: Stagger cron schedules so jobs don't run simultaneously. "
                    f"Alpha=7:00, Beta=7:05."
                )
            elif "api" in msg or "z.ai" in msg or "90s" in msg:
                report_lines.append(
                    f"  {source}: Z.AI API timeout (90s non-streaming). "
                    f"FIX: Enable streaming=true in config. Stagger agent start times. "
                    f"Increase API timeout if possible."
                )
            elif "claude" in msg or "oauth" in msg or "auth" in msg:
                report_lines.append(
                    f"  {source}: Claude OAuth/auth timeout. "
                    f"FIX: Check claude auth status. May need manual 'claude auth login'. "
                    f"Keychain token may be expired."
                )

        elif "zombie" in msg or "stale execution" in msg:
            report_lines.append(
                f"  {source}: Zombie execution blocking schedule. "
                f"FIX: cron_zombie_cleanup.py should handle this. "
                f"If recurring, increase cleanup frequency."
            )

        elif "oauth" in msg and ("expired" in msg or "failed" in msg):
            report_lines.append(
                f"  {source}: Claude OAuth token expired/refresh failed. "
                f"FIX: Run 'claude auth login' in a separate terminal. "
                f"Check keepalive cron is running every 2h."
            )

        elif "mcp" in msg and ("unavailable" in msg or "queued" in msg or "not filled" in msg):
            report_lines.append(
                f"  {source}: Robinhood MCP order execution issue. "
                f"Known: claude.ai MCP connectors unreliable in -p headless mode (#26364). "
                f"FIX: Let agents place orders through their own cron sessions. "
                f"Avoid manual order placement via claude -p from chat."
            )

        elif "invalid_grant" in msg or "401" in msg:
            report_lines.append(
                f"  {source}: Auth credential rejection (401/invalid_grant). "
                f"FIX: Delete ~/.claude/.credentials.json and run 'claude auth login' fresh. "
                f"Refresh token may have aged out (GitHub #65761)."
            )

    report_lines.append(f"")
    report_lines.append(f"=== RECOMMENDED ACTIONS ===")
    actions = set()
    for s in summary:
        msg = s["sample_message"].lower()
        if "terminal_cwd" in msg or "write lock" in msg:
            actions.add("Stagger agent cron schedules (already done: Alpha 7:00, Beta 7:05)")
        if "zombie" in msg:
            actions.add("Verify zombie cleanup cron is running every 2h")
        if "oauth" in msg and ("expired" in msg or "failed" in msg or "401" in msg):
            actions.add("Run 'claude auth login' in a separate terminal")
        if "90s" in msg or "non-streaming" in msg:
            actions.add("Verify streaming=true in Z.AI config")
        if "mcp" in msg and ("queued" in msg or "not filled" in msg):
            actions.add("Stop manual order placement via claude -p — use agent cron sessions only")

    if actions:
        for a in sorted(actions):
            report_lines.append(f"  → {a}")
    else:
        report_lines.append(f"  → No automated fixes identified. Manual investigation needed.")

    report = "\n".join(report_lines)
    return True, report

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Trading Arena Error Analyzer")
    parser.add_argument("--hours", type=int, default=24, help="Hours to analyze")
    parser.add_argument("--dry-run", action="store_true", help="Don't alert, just print")
    args = parser.parse_args()

    should_alert, report = analyze_errors(hours=args.hours, dry_run=args.dry_run)

    if should_alert:
        print(report)
        # Exit 0 so cron delivers the report to Telegram
        sys.exit(0)
    else:
        # Silent — no errors or only isolated ones
        sys.exit(0)

if __name__ == "__main__":
    main()
