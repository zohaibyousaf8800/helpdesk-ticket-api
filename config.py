"""Configuration for the Helpdesk Ticket API.

SLA targets and the agent roster live here so they are easy to review and
change without touching application logic.
"""

# SLA targets per priority, in minutes.
# "response" = time to first response (ticket leaves the Open state),
# "resolve"  = time to resolution.
SLA_TARGETS = {
    "P1": {"response": 15, "resolve": 4 * 60},        # 15 min / 4 h
    "P2": {"response": 60, "resolve": 8 * 60},        # 1 h / 8 h
    "P3": {"response": 4 * 60, "resolve": 24 * 60},   # 4 h / 24 h
    "P4": {"response": 8 * 60, "resolve": 48 * 60},   # 8 h / 48 h
}

PRIORITIES = tuple(SLA_TARGETS.keys())

STATUSES = ("Open", "In Progress", "Resolved", "Closed")
OPEN_STATUSES = ("Open", "In Progress")
DONE_STATUSES = ("Resolved", "Closed")

# Sample support agents used for round-robin auto-assignment.
# These are sample data for the demo, not real staff records.
AGENTS = [
    {"name": "Ahmed Raza", "skills": ["network", "vpn", "hardware"]},
    {"name": "Sara Malik", "skills": ["microsoft-365", "accounts", "email"]},
    {"name": "Bilal Hussain", "skills": ["hardware", "printers", "windows"]},
    {"name": "Fatima Noor", "skills": ["software", "security", "azure"]},
]

DEFAULT_CATEGORY = "General"
