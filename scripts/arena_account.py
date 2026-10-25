"""Arena account identifier (last 4 digits), kept OUT of this public repo.

Resolution order:
  1. env ARENA_ACCOUNT_LAST4
  2. <scripts>/../state/arena_account_last4  (untracked; one line, e.g. "1234")
  3. ~/trading-arena/state/arena_account_last4 (for copies deployed elsewhere,
     e.g. the health check in ~/.hermes/scripts)

Returns "" when unset — callers must fail closed (options_guard BLOCKs every
opening order; the health check reports the probe as unconfigured).
"""
import os
import re
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "arena_account_last4"
FALLBACK_FILE = Path.home() / "trading-arena" / "state" / "arena_account_last4"


def arena_account_last4():
    val = os.environ.get("ARENA_ACCOUNT_LAST4", "").strip()
    for f in (STATE_FILE, FALLBACK_FILE):
        if val:
            break
        if f.exists():
            val = f.read_text().strip()
    return val if re.fullmatch(r"\d{4}", val) else ""
