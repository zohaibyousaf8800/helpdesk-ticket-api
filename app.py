"""Helpdesk Ticket API — an SLA-aware IT helpdesk ticketing REST API.

Flask + SQLite (stdlib). Run locally with:

    python seed.py      # optional: load sample data
    python app.py       # serves on http://127.0.0.1:5000

All /api routes require the X-API-Key header. The key comes from the
HELPDESK_API_KEY environment variable and defaults to "demo-key-123"
for local demo use.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request

from config import (AGENTS, DEFAULT_CATEGORY, DONE_STATUSES, PRIORITIES,
                    STATUSES)
from sla import compute_due_times, compute_sla

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = str(BASE_DIR / "helpdesk.db")
DEFAULT_API_KEY = "demo-key-123"

DATETIME_FIELDS = ("created_at", "updated_at", "responded_at", "resolved_at",
                   "response_due", "resolve_due")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    requester    TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'General',
    priority     TEXT NOT NULL DEFAULT 'P3',
    status       TEXT NOT NULL DEFAULT 'Open',
    assignee     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    responded_at TEXT,
    resolved_at  TEXT,
    response_due TEXT NOT NULL,
    resolve_due  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow():
    return datetime.now(timezone.utc)


def _parse_dt(value):
    """Parse an ISO-8601 string into an aware datetime (UTC assumed)."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_dt(dt):
    return dt.isoformat() if dt is not None else None


def init_db(db_path):
    """Create the database schema if it does not exist yet."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get(
        "HELPDESK_DB", DEFAULT_DB_PATH)
    app.config["API_KEY"] = os.environ.get(
        "HELPDESK_API_KEY", DEFAULT_API_KEY)
    init_db(app.config["DB_PATH"])

    # ------------------------------------------------------------------ db
    def get_db():
        if "db" not in g:
            conn = sqlite3.connect(app.config["DB_PATH"])
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            g.db = conn
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # ---------------------------------------------------------------- auth
    @app.before_request
    def require_api_key():
        if request.path.startswith("/api"):
            if request.headers.get("X-API-Key") != app.config["API_KEY"]:
                return jsonify({"error": "unauthorized",
                                "detail": "missing or invalid X-API-Key"}), 401
        return None

    # ------------------------------------------------------- serialisation
    def ticket_to_json(row, now=None):
        ticket = dict(row)
        parsed = dict(ticket)
        for field in DATETIME_FIELDS:
            parsed[field] = _parse_dt(ticket[field])
        ticket["sla"] = compute_sla(parsed, now or utcnow())
        return ticket

    def fetch_ticket(ticket_id):
        return get_db().execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()

    def next_assignee():
        """Round-robin over the agent roster, persisted in the meta table."""
        db = get_db()
        row = db.execute(
            "SELECT value FROM meta WHERE key = 'rr_index'").fetchone()
        index = int(row["value"]) if row else 0
        agent = AGENTS[index % len(AGENTS)]["name"]
        db.execute(
            "INSERT INTO meta (key, value) VALUES ('rr_index', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(index + 1),))
        db.commit()
        return agent

    def error(message, status=400):
        return jsonify({"error": message}), status

    # -------------------------------------------------------------- routes
    @app.get("/")
    def index():
        return (
            "Helpdesk Ticket API\n"
            "-------------------\n"
            "SLA-aware IT helpdesk ticketing service.\n\n"
            "Endpoints (all require the X-API-Key header):\n"
            "  POST   /api/tickets\n"
            "  GET    /api/tickets?status=&priority=&assignee=&category=\n"
            "  GET    /api/tickets/<id>\n"
            "  PATCH  /api/tickets/<id>\n"
            "  DELETE /api/tickets/<id>\n"
            "  POST   /api/tickets/<id>/comments\n"
            "  GET    /api/tickets/<id>/comments\n"
            "  GET    /api/agents\n"
            "  GET    /api/stats\n"
        ), 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.post("/api/tickets")
    def create_ticket():
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        requester = (data.get("requester") or "").strip()
        if not title or not requester:
            return error("title and requester are required")
        priority = data.get("priority", "P3")
        if priority not in PRIORITIES:
            return error(f"priority must be one of {list(PRIORITIES)}")

        created_at = utcnow()
        if data.get("created_at"):  # optional, for imports/tests
            try:
                created_at = _parse_dt(str(data["created_at"]))
            except ValueError:
                return error("created_at must be an ISO-8601 datetime")

        assignee = (data.get("assignee") or "").strip() or next_assignee()
        response_due, resolve_due = compute_due_times(priority, created_at)
        now_iso = _fmt_dt(created_at)
        db = get_db()
        cur = db.execute(
            "INSERT INTO tickets (title, description, requester, category,"
            " priority, status, assignee, created_at, updated_at,"
            " response_due, resolve_due)"
            " VALUES (?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?, ?)",
            (title, data.get("description", ""), requester,
             data.get("category", DEFAULT_CATEGORY), priority, assignee,
             now_iso, now_iso, _fmt_dt(response_due), _fmt_dt(resolve_due)))
        db.commit()
        return jsonify(ticket_to_json(fetch_ticket(cur.lastrowid))), 201

    @app.get("/api/tickets")
    def list_tickets():
        clauses, params = [], []
        for field in ("status", "priority", "assignee", "category"):
            value = request.args.get(field)
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        sql = "SELECT * FROM tickets"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        now = utcnow()
        rows = get_db().execute(sql, params).fetchall()
        tickets = [ticket_to_json(row, now) for row in rows]
        return jsonify({"tickets": tickets, "count": len(tickets)})

    @app.get("/api/tickets/<int:ticket_id>")
    def get_ticket(ticket_id):
        row = fetch_ticket(ticket_id)
        if row is None:
            return error("ticket not found", 404)
        return jsonify(ticket_to_json(row))

    @app.patch("/api/tickets/<int:ticket_id>")
    def update_ticket(ticket_id):
        row = fetch_ticket(ticket_id)
        if row is None:
            return error("ticket not found", 404)
        data = request.get_json(silent=True) or {}
        current = dict(row)
        updates = {}

        if "priority" in data:
            if data["priority"] not in PRIORITIES:
                return error(f"priority must be one of {list(PRIORITIES)}")
            updates["priority"] = data["priority"]
            # Deadlines follow the new priority, anchored at creation time.
            created_at = _parse_dt(current["created_at"])
            response_due, resolve_due = compute_due_times(
                data["priority"], created_at)
            updates["response_due"] = _fmt_dt(response_due)
            updates["resolve_due"] = _fmt_dt(resolve_due)

        if "assignee" in data:
            updates["assignee"] = data["assignee"]

        now = utcnow()
        if "status" in data:
            new_status = data["status"]
            if new_status not in STATUSES:
                return error(f"status must be one of {list(STATUSES)}")
            updates["status"] = new_status
            # First move out of Open counts as the first response.
            if current["status"] == "Open" and new_status != "Open" \
                    and current["responded_at"] is None:
                updates["responded_at"] = _fmt_dt(now)
            if new_status in DONE_STATUSES and current["resolved_at"] is None:
                updates["resolved_at"] = _fmt_dt(now)

        if not updates:
            return error("nothing to update: send status, assignee or priority")

        updates["updated_at"] = _fmt_dt(now)
        set_sql = ", ".join(f"{key} = ?" for key in updates)
        db = get_db()
        db.execute(f"UPDATE tickets SET {set_sql} WHERE id = ?",
                   (*updates.values(), ticket_id))
        db.commit()
        return jsonify(ticket_to_json(fetch_ticket(ticket_id)))

    @app.delete("/api/tickets/<int:ticket_id>")
    def delete_ticket(ticket_id):
        if fetch_ticket(ticket_id) is None:
            return error("ticket not found", 404)
        db = get_db()
        db.execute("DELETE FROM comments WHERE ticket_id = ?", (ticket_id,))
        db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        db.commit()
        return jsonify({"deleted": True, "id": ticket_id})

    @app.post("/api/tickets/<int:ticket_id>/comments")
    def add_comment(ticket_id):
        if fetch_ticket(ticket_id) is None:
            return error("ticket not found", 404)
        data = request.get_json(silent=True) or {}
        author = (data.get("author") or "").strip()
        body = (data.get("body") or "").strip()
        if not author or not body:
            return error("author and body are required")
        db = get_db()
        cur = db.execute(
            "INSERT INTO comments (ticket_id, author, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (ticket_id, author, body, _fmt_dt(utcnow())))
        db.commit()
        row = db.execute("SELECT * FROM comments WHERE id = ?",
                         (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201

    @app.get("/api/tickets/<int:ticket_id>/comments")
    def list_comments(ticket_id):
        if fetch_ticket(ticket_id) is None:
            return error("ticket not found", 404)
        rows = get_db().execute(
            "SELECT * FROM comments WHERE ticket_id = ? ORDER BY id",
            (ticket_id,)).fetchall()
        comments = [dict(row) for row in rows]
        return jsonify({"comments": comments, "count": len(comments)})

    @app.get("/api/agents")
    def list_agents():
        placeholders = ", ".join("?" for _ in DONE_STATUSES)
        rows = get_db().execute(
            f"SELECT assignee, COUNT(*) AS n FROM tickets"
            f" WHERE status NOT IN ({placeholders}) GROUP BY assignee",
            DONE_STATUSES).fetchall()
        open_counts = {row["assignee"]: row["n"] for row in rows}
        agents = [{"name": agent["name"], "skills": agent["skills"],
                   "open_tickets": open_counts.get(agent["name"], 0)}
                  for agent in AGENTS]
        return jsonify({"agents": agents, "count": len(agents)})

    @app.get("/api/stats")
    def stats():
        db = get_db()
        now = utcnow()
        rows = db.execute("SELECT * FROM tickets").fetchall()
        tickets = [dict(row) for row in rows]

        by_status = {status: 0 for status in STATUSES}
        by_priority = {priority: 0 for priority in PRIORITIES}
        breached = {"response": 0, "resolve": 0}
        at_risk = 0
        resolved_hours = []
        compliant = 0

        for ticket in tickets:
            by_status[ticket["status"]] += 1
            by_priority[ticket["priority"]] += 1
            parsed = {field: _parse_dt(ticket[field])
                      for field in DATETIME_FIELDS}
            parsed["priority"] = ticket["priority"]
            sla = compute_sla(parsed, now)
            if sla["response_status"] == "breached":
                breached["response"] += 1
            if sla["resolve_status"] == "breached":
                breached["resolve"] += 1
            if "at_risk" in (sla["response_status"], sla["resolve_status"]):
                at_risk += 1
            if parsed["resolved_at"] is not None:
                hours = (parsed["resolved_at"]
                         - parsed["created_at"]).total_seconds() / 3600
                resolved_hours.append(hours)
                if parsed["resolved_at"] <= parsed["resolve_due"]:
                    compliant += 1

        resolved_count = len(resolved_hours)
        return jsonify({
            "total_tickets": len(tickets),
            "by_status": by_status,
            "by_priority": by_priority,
            "breached": breached,
            "at_risk": at_risk,
            "sla_resolve_compliance_pct": (
                round(100.0 * compliant / resolved_count, 2)
                if resolved_count else None),
            "avg_resolution_hours": (
                round(sum(resolved_hours) / resolved_count, 2)
                if resolved_count else None),
        })

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port)
