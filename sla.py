"""SLA computation for the Helpdesk Ticket API.

Every ticket stores two deadlines (response_due, resolve_due) computed from
its priority at creation time. This module classifies each deadline, at any
moment, into one of four states:

    met         the action happened on or before its deadline
    within_sla  not done yet, deadline comfortably in the future
    at_risk     not done yet, less than 25% of the SLA window remains
    breached    deadline has passed without the action happening
                (or the action happened after the deadline)
"""

from datetime import timedelta

from config import SLA_TARGETS

AT_RISK_FRACTION = 0.25


def compute_due_times(priority, created_at):
    """Return (response_due, resolve_due) datetimes for a new ticket."""
    targets = SLA_TARGETS[priority]
    response_due = created_at + timedelta(minutes=targets["response"])
    resolve_due = created_at + timedelta(minutes=targets["resolve"])
    return response_due, resolve_due


def _classify(deadline, done_at, window_minutes, now):
    """Classify a single SLA deadline."""
    if done_at is not None:
        return "met" if done_at <= deadline else "breached"
    if now > deadline:
        return "breached"
    remaining_seconds = (deadline - now).total_seconds()
    if remaining_seconds < AT_RISK_FRACTION * window_minutes * 60:
        return "at_risk"
    return "within_sla"


def compute_sla(ticket, now):
    """Return the SLA status object for a ticket dict.

    The ticket dict must carry timezone-aware datetimes (or None) for:
    priority, response_due, resolve_due, responded_at, resolved_at.
    """
    targets = SLA_TARGETS[ticket["priority"]]
    return {
        "response_status": _classify(
            ticket["response_due"], ticket["responded_at"],
            targets["response"], now,
        ),
        "resolve_status": _classify(
            ticket["resolve_due"], ticket["resolved_at"],
            targets["resolve"], now,
        ),
    }
