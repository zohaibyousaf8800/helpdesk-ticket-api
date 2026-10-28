import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import create_app

API_KEY = "demo-key-123"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def make_ticket(client, **overrides):
    """Create one ticket through the API and return its JSON body."""
    payload = {
        "title": "Printer not working",
        "description": "The floor 2 printer shows a paper jam error.",
        "requester": "user@example.com",
        "category": "hardware",
        "priority": "P3",
        "assignee": "Ahmed Raza",
    }
    payload.update(overrides)
    response = client.post("/api/tickets", json=payload, headers=HEADERS)
    assert response.status_code == 201, response.get_json()
    return response.get_json()
