#!/usr/bin/env python3
"""
Helper script: print how long until the next "new year" announcement is posted.

Uses config.json (staff-years hours_per_year) and history.jsonl (last printed timestamp).
Run from project root: python next_year.py  or  uv run python next_year.py
"""

import json
import os
import sys
from datetime import datetime, timedelta

def main():
    if not os.path.exists("config.json"):
        print("config.json not found (run from project root)", file=sys.stderr)
        sys.exit(1)

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    calendars = config.get("calendars", [])
    staff = next((c for c in calendars if c.get("is_staff_years") is True), None)
    if not staff:
        print("No staff-years calendar in config", file=sys.stderr)
        sys.exit(1)

    hours_per_year = float(staff.get("hours_per_year", 0))
    if hours_per_year <= 0:
        print("Staff-years calendar has no hours_per_year", file=sys.stderr)
        sys.exit(1)

    last_printed_ts_ms = None
    if os.path.exists("history.jsonl"):
        with open("history.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                printed = row.get("printed")
                if printed is not None and printed != "":
                    ts = row.get("timestamp")
                    if ts is not None:
                        if last_printed_ts_ms is None or ts > last_printed_ts_ms:
                            last_printed_ts_ms = ts
                # keep scanning to get the latest printed row
                continue

    now = datetime.now()
    if last_printed_ts_ms is None:
        print("No previous 'new year' print found in history.jsonl.")
        print("The next announcement will happen once the bot has run and printed once.")
        return

    # timestamps in history are in milliseconds (same as bot uses)
    last_printed = datetime.fromtimestamp(last_printed_ts_ms / 1000.0)
    next_print = last_printed + timedelta(hours=hours_per_year)
    delta = next_print - now

    if delta.total_seconds() <= 0:
        print("The next year announcement is due now.")
        print("The bot checks every 30 minutes, so it may post within the next 30 minutes.")
        print(f"(Last printed: {last_printed.isoformat()})")
        return

    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder %= 3600
    minutes = remainder // 60
    seconds = remainder % 60

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours or parts:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts or seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

    print("Time until next year announcement:", " ".join(parts))
    print(f"Next print at: {next_print.isoformat()}")
    print(f"Last printed at: {last_printed.isoformat()}")
    print(f"(Staff year length: {hours_per_year:.0f} real hours)")

if __name__ == "__main__":
    main()
