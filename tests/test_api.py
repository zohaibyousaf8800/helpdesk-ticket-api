"""End-to-end tests for the Helpdesk Ticket API (Flask test client)."""

from datetime import datetime, timedelta, timezone

import pytest

from config import AGENTS
from tests.conftest import HEADERS, make_ticket


def hours_ago(hours):
    return (datetime.now(timezone.utc)
            - timedelta(hours=hours)).isoformat()


# --------------------------------------------------------------- auth
def test_api_routes_require_key(client):
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/stats").status_code == 401
    bad = client.get("/api/tickets", headers={"X-API-Key": "wrong"})
    assert bad.status_code == 401
    assert bad.get_json()["error"] == "unauthorized"


def test_root_route_is_public(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Helpdesk Ticket API" in response.data


# ----------------------------------------------------------- creation
def test_create_ticket_computes_sla_deadlines(client):
    ticket = make_ticket(client, priority="P1")
    created = datetime.fromisoformat(ticket["created_at"])
    response_due = datetime.fromisoformat(ticket["response_due"])
    resolve_due = datetime.fromisoformat(ticket["resolve_due"])
    # P1: respond within 15 minutes, resolve within 4 hours.
    assert (response_due - created) == timedelta(minutes=15)
    assert (resolve_due - created) == timedelta(hours=4)
    assert ticket["status"] == "Open"
    assert ticket["sla"] == {"response_status": "within_sla",
                             "resolve_status": "within_sla"}


def test_create_ticket_validation(client):
    missing = client.post("/api/tickets", json={"title": "x"},
                          headers=HEADERS)
    assert missing.status_code == 400
    bad_priority = client.post(
        "/api/tickets",
        json={"title": "x", "requester": "a@b.c", "priority": "P9"},
        headers=HEADERS)
    assert bad_priority.status_code == 400


def test_get_and_delete_ticket(client):
    ticket = make_ticket(client)
    fetched = client.get(f"/api/tickets/{ticket['id']}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.get_json()["title"] == ticket["title"]

    deleted = client.delete(f"/api/tickets/{ticket['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    assert client.get(f"/api/tickets/{ticket['id']}",
                      headers=HEADERS).status_code == 404


# ---------------------------------------------------------- filtering
def test_list_filters(client):
    make_ticket(client, priority="P1", category="network",
                assignee="Sara Malik")
    make_ticket(client, priority="P4", category="hardware")
    third = make_ticket(client, priority="P4", category="hardware")
    client.patch(f"/api/tickets/{third['id']}", json={"status": "Resolved"},
                 headers=HEADERS)

    by_priority = client.get("/api/tickets?priority=P4",
                             headers=HEADERS).get_json()
    assert by_priority["count"] == 2
    by_status = client.get("/api/tickets?status=Resolved",
                           headers=HEADERS).get_json()
    assert by_status["count"] == 1
    by_assignee = client.get("/api/tickets?assignee=Sara Malik",
                             headers=HEADERS).get_json()
    assert by_assignee["count"] == 1
    by_category = client.get("/api/tickets?category=network",
                             headers=HEADERS).get_json()
    assert by_category["count"] == 1
    assert client.get("/api/tickets",
                      headers=HEADERS).get_json()["count"] == 3


# ------------------------------------------------------ status changes
def test_status_transitions_set_response_and_resolve_times(client):
    ticket = make_ticket(client)
    assert ticket["responded_at"] is None
    assert ticket["resolved_at"] is None

    moved = client.patch(f"/api/tickets/{ticket['id']}",
                         json={"status": "In Progress"},
                         headers=HEADERS).get_json()
    assert moved["responded_at"] is not None
    assert moved["resolved_at"] is None

    resolved = client.patch(f"/api/tickets/{ticket['id']}",
                            json={"status": "Resolved"},
                            headers=HEADERS).get_json()
    assert resolved["resolved_at"] is not None
    assert resolved["sla"]["response_status"] == "met"
    assert resolved["sla"]["resolve_status"] == "met"


# ------------------------------------------------------------ SLA math
def test_sla_breached_when_created_long_ago(client):
    # P1 created 6 hours ago: response (15m) and resolve (4h) both passed.
    ticket = make_ticket(client, priority="P1", created_at=hours_ago(6))
    assert ticket["sla"]["response_status"] == "breached"
    assert ticket["sla"]["resolve_status"] == "breached"


def test_sla_at_risk_when_window_almost_gone(client):
    # P2 created 7 hours ago: resolve window is 8h, 1h left = 12.5% < 25%.
    ticket = make_ticket(client, priority="P2", created_at=hours_ago(7))
    assert ticket["sla"]["resolve_status"] == "at_risk"
    # Response window (1h) has fully passed, so response is breached.
    assert ticket["sla"]["response_status"] == "breached"


# ------------------------------------------------------- auto-assign
def test_auto_assignment_round_robin(client):
    names = [agent["name"] for agent in AGENTS]
    assigned = []
    for _ in range(len(names) + 1):
        ticket = make_ticket(client, assignee=None)
        assigned.append(ticket["assignee"])
    assert assigned[:len(names)] == names       # full rotation, in order
    assert assigned[len(names)] == names[0]     # wraps around


def test_agents_endpoint_counts_open_tickets(client):
    make_ticket(client, assignee="Ahmed Raza")
    done = make_ticket(client, assignee="Ahmed Raza")
    client.patch(f"/api/tickets/{done['id']}", json={"status": "Closed"},
                 headers=HEADERS)
    agents = client.get("/api/agents", headers=HEADERS).get_json()["agents"]
    by_name = {agent["name"]: agent for agent in agents}
    assert by_name["Ahmed Raza"]["open_tickets"] == 1
    assert by_name["Sara Malik"]["open_tickets"] == 0
    assert by_name["Ahmed Raza"]["skills"]


# ------------------------------------------------------------ comments
def test_comments_create_and_list(client):
    ticket = make_ticket(client)
    created = client.post(f"/api/tickets/{ticket['id']}/comments",
                          json={"author": "Sara Malik",
                                "body": "Looking into this now."},
                          headers=HEADERS)
    assert created.status_code == 201
    listed = client.get(f"/api/tickets/{ticket['id']}/comments",
                        headers=HEADERS).get_json()
    assert listed["count"] == 1
    assert listed["comments"][0]["body"] == "Looking into this now."
    missing = client.post("/api/tickets/9999/comments",
                          json={"author": "x", "body": "y"}, headers=HEADERS)
    assert missing.status_code == 404


# --------------------------------------------------------------- stats
def test_stats_math(client):
    # Resolved in 2h against a 4h P1 target: compliant.
    fast = make_ticket(client, priority="P1", created_at=hours_ago(2))
    client.patch(f"/api/tickets/{fast['id']}", json={"status": "Resolved"},
                 headers=HEADERS)
    # Resolved after 100h against a 48h P4 target: not compliant.
    slow = make_ticket(client, priority="P4", created_at=hours_ago(100))
    client.patch(f"/api/tickets/{slow['id']}", json={"status": "Resolved"},
                 headers=HEADERS)
    # Still open and fully breached.
    make_ticket(client, priority="P1", created_at=hours_ago(6))

    stats = client.get("/api/stats", headers=HEADERS).get_json()
    assert stats["total_tickets"] == 3
    assert stats["by_status"]["Resolved"] == 2
    assert stats["by_status"]["Open"] == 1
    assert stats["by_priority"]["P1"] == 2
    assert stats["sla_resolve_compliance_pct"] == 50.0
    assert stats["avg_resolution_hours"] == pytest.approx(51.0, abs=0.1)
    # All three tickets were responded to after their response deadlines
    # (the two resolved ones only got their first response at resolve
    # time), so response breaches = 3. Resolve breaches = 2: the slow P4
    # plus the still-open P1.
    assert stats["breached"]["response"] == 3
    assert stats["breached"]["resolve"] == 2
