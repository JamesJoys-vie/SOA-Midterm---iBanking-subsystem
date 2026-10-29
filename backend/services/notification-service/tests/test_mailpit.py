"""End-to-end test against a real Mailpit. Skipped when Mailpit isn't running.

Start one with:  docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
"""
import uuid

import httpx
import pytest

from app.config import settings
from app.mailer import Mailer

MAILPIT_API = "http://localhost:8025/api/v1"  # Mailpit's web UI / REST API

def _mailpit_up() -> bool:
    """True if Mailpit's API answers."""
    try:
        return httpx.get(f"{MAILPIT_API}/info", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False

@pytest.mark.skipif(not _mailpit_up(), reason="Mailpit not running on localhost:1025/8025")
def test_email_arrives_in_mailpit():
    """A sent email can be found in Mailpit's inbox by its unique subject."""
    subject = f"iBanking test {uuid.uuid4()}"

    Mailer(settings).send("alice@example.com", subject, "plain body", "<p>html body</p>")

    found = httpx.get(f"{MAILPIT_API}/search", params={"query": f'subject:"{subject}"'}).json()
    assert found["messages_count"] == 1
    assert found["messages"][0]["To"][0]["Address"] == "alice@example.com"
