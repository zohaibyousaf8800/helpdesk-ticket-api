"""Seed the Helpdesk Ticket API database with SAMPLE data.

Creates a fresh SQLite database containing 12 sample tickets in varied
priorities and statuses: some resolved within SLA, at least one breached
and at least one at risk. All timestamps are offsets from the moment the
seed runs, so the SLA states are real when you start the app.

The agents themselves live in config.py (AGENTS); the sample tickets are
assigned to them. This script RESETS the database file.

Usage:  python seed.py
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import DEFAULT_DB_PATH, init_db
from sla import compute_due_times

# (title, requester, category, priority, status, assignee,
#  created_hours_ago, responded_after_min, resolved_after_min)
SAMPLE_TICKETS = [
    ("Core network switch down in main office", "ops.manager@example.com",
     "network", "P1", "Resolved", "Ahmed Raza", 3, 10, 120),
    ("Email server outage - nobody can send mail", "reception@example.com",
     "email", "P1", "Open", "Sara Malik", 6, None, None),
    ("VPN tunnel drops for remote staff", "sales.lead@example.com",
     "network", "P2", "In Progress", "Ahmed Raza", 7, 30, None),
    ("Shared drive permissions for finance folder", "accounts@example.com",
     "accounts", "P3", "Resolved", "Bilal Hussain", 30, 60, 1200),
    ("New starter laptop request", "hr@example.com",
     "hardware", "P3", "Open", "Fatima Noor", 1, None, None),
    ("Printer replacement on floor 2", "office.admin@example.com",
     "hardware", "P4", "Closed", "Bilal Hussain", 100, 120, 2400),
    ("CRM sync failures between offices", "sales.ops@example.com",
     "software", "P2", "Resolved", "Sara Malik", 30, 45, 720),
    ("Monitor flickering at desk 14", "designer@example.com",
     "hardware", "P4", "Open", "Ahmed Raza", 2, None, None),
    ("ERP login failures for finance team", "finance@example.com",
     "software", "P1", "In Progress", "Fatima Noor", 1, 5, None),
    ("Antivirus alerts on reception PC", "reception@example.com",
     "security", "P3", "Open", "Sara Malik", 10, None, None),
    ("Teams call quality issues in meeting room", "pm@example.com",
     "software", "P2", "Closed", "Bilal Hussain", 50, 20, 300),
    ("Design software install request", "designer@example.com",
     "software", "P4", "Open", "Fatima Noor", 7, None, None),
]

SAMPLE_COMMENTS = [
    (1, "Ahmed Raza", "Replacement switch installed, monitoring the link."),
    (3, "Ahmed Raza", "Tunnel re-keyed; watching for further drops."),
]


def main():
    db_path = os.environ.get("HELPDESK_DB", DEFAULT_DB_PATH)
    path = Path(db_path)
    if path.exists():
        path.unlink()
    init_db(db_path)

    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    for (title, requester, category, priority, status, assignee,
         hours_ago, responded_min, resolved_min) in SAMPLE_TICKETS:
        created_at = now - timedelta(hours=hours_ago)
        response_due, resolve_due = compute_due_times(priority, created_at)
        responded_at = (created_at + timedelta(minutes=responded_min)
                        if responded_min is not None else None)
        resolved_at = (created_at + timedelta(minutes=resolved_min)
                       if resolved_min is not None else None)
        updated_at = resolved_at or responded_at or created_at
        conn.execute(
            "INSERT INTO tickets (title, description, requester, category,"
            " priority, status, assignee, created_at, updated_at,"
            " responded_at, resolved_at, response_due, resolve_due)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, "Sample ticket created by seed.py.", requester, category,
             priority, status, assignee, created_at.isoformat(),
             updated_at.isoformat(),
             responded_at.isoformat() if responded_at else None,
             resolved_at.isoformat() if resolved_at else None,
             response_due.isoformat(), resolve_due.isoformat()))
    for ticket_id, author, body in SAMPLE_COMMENTS:
        conn.execute(
            "INSERT INTO comments (ticket_id, author, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (ticket_id, author, body, now.isoformat()))
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('rr_index', ?)",
        (str(len(SAMPLE_TICKETS)),))
    conn.commit()
    conn.close()
    print(f"Seeded {len(SAMPLE_TICKETS)} sample tickets into {db_path}")


if __name__ == "__main__":
    main()
