#!/usr/bin/env python3
"""
Trading Arena — Structured Execution Logger

Logs all script/cron/agent executions to a searchable SQLite database.
Enables post-hoc debugging, error pattern detection, and automated analysis.

Schema:
  events(
    id, timestamp, source, job_id, event_type, severity,
    message, data_json, session_id
  )

Usage:
  from arena_logger import log_event
  log_event("alpha", "trade_executed", "info", "BUY 3 CVS @ $95.70", {"order_id": "..."})

  # Query:
  from arena_logger import query_events
  errors = query_events(severity="error", source="beta", limit=20)
"""
import sqlite3
import json
import os
import datetime
import uuid

DB_PATH = os.path.expanduser("~/trading-arena/state/arena_logs.db")

def init_db():
    """Create the events table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            job_id TEXT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('debug','info','warning','error','critical')),
            message TEXT NOT NULL,
            data_json TEXT,
            session_id TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)
    """)
    conn.commit()
    conn.close()

def log_event(source, event_type, severity="info", message="", data=None, job_id=None, session_id=None):
    """Log a structured event to the database.

    Args:
        source: Who logged this (alpha, beta, judge, rocky, health_check, retry_check, keepalive, etc.)
        event_type: What happened (session_start, trade_executed, judge_verdict, error, cron_fired, etc.)
        severity: debug, info, warning, error, critical
        message: Human-readable message
        data: Dict of structured data (stored as JSON)
        job_id: Hermes cron job ID (if applicable)
        session_id: Session/correlation ID (auto-generated if None)
    """
    if session_id is None:
        session_id = str(uuid.uuid4())[:8]

    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO events (timestamp, source, job_id, event_type, severity, message, data_json, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.datetime.now().isoformat(),
        source,
        job_id,
        event_type,
        severity,
        message,
        json.dumps(data) if data else None,
        session_id,
    ))
    conn.commit()
    conn.close()
    return session_id

def query_events(source=None, severity=None, event_type=None, job_id=None,
                 since=None, limit=50, offset=0):
    """Query events from the database with optional filters.

    Args:
        source: Filter by source (alpha, beta, judge, etc.)
        severity: Filter by severity (error, critical, etc.)
        event_type: Filter by event type
        job_id: Filter by Hermes job ID
        since: ISO timestamp (only events after this)
        limit: Max results
        offset: Pagination offset

    Returns: List of dicts
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM events WHERE 1=1"
    params = []

    if source:
        query += " AND source = ?"
        params.append(source)
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if job_id:
        query += " AND job_id = ?"
        params.append(job_id)
    if since:
        query += " AND timestamp >= ?"
        params.append(since)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    columns = [desc[0] for desc in conn.execute("SELECT * FROM events LIMIT 0").description]

    conn.close()
    return [dict(zip(columns, row)) for row in rows]

def get_error_summary(hours=24):
    """Get a summary of errors in the last N hours, grouped by source."""
    init_db()
    since = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT source, severity, event_type, COUNT(*) as count,
               MAX(timestamp) as last_occurrence, MIN(message) as sample_message
        FROM events
        WHERE timestamp >= ? AND severity IN ('error', 'critical')
        GROUP BY source, severity, event_type
        ORDER BY count DESC
    """, (since,)).fetchall()

    conn.close()
    return [
        {
            "source": r[0], "severity": r[1], "event_type": r[2],
            "count": r[3], "last_occurrence": r[4], "sample_message": r[5][:200]
        }
        for r in rows
    ]

if __name__ == "__main__":
    # CLI: query the log database
    import argparse
    parser = argparse.ArgumentParser(description="Query Trading Arena execution logs")
    parser.add_argument("--source", help="Filter by source (alpha, beta, judge, etc.)")
    parser.add_argument("--severity", help="Filter by severity (error, critical, etc.)")
    parser.add_argument("--type", help="Filter by event type")
    parser.add_argument("--hours", type=int, default=24, help="Last N hours")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    parser.add_argument("--errors-only", action="store_true", help="Only errors and criticals")
    parser.add_argument("--summary", action="store_true", help="Error summary by source")
    args = parser.parse_args()

    if args.summary:
        summary = get_error_summary(args.hours)
        if not summary:
            print(f"No errors in the last {args.hours}h. All clean.")
        else:
            print(f"=== ERROR SUMMARY (last {args.hours}h) ===")
            for s in summary:
                print(f"  {s['source']:15s} {s['severity']:8s} {s['event_type']:25s} "
                      f"x{s['count']}  last: {s['last_occurrence'][:16]}")
                print(f"    sample: {s['sample_message']}")
    else:
        since = (datetime.datetime.now() - datetime.timedelta(hours=args.hours)).isoformat()
        events = query_events(
            source=args.source,
            severity="error" if args.errors_only else args.severity,
            event_type=args.type,
            since=since,
            limit=args.limit
        )
        if not events:
            print(f"No events found matching filters.")
        else:
            for e in events:
                print(f"[{e['timestamp'][:19]}] {e['source']:15s} {e['severity']:8s} {e['event_type']:25s} {e['message'][:100]}")
