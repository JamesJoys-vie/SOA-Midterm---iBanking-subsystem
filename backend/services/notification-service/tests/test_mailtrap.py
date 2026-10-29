"""End-to-end test against your Mailtrap Email Testing inbox. Skipped unless configured.

Needs these environment variables:
- SMTP_USER, SMTP_PASSWORD: the inbox's SMTP credentials (same as in .env)
- MAILTRAP_API_TOKEN: Mailtrap → Settings → API Tokens (read access to the inbox is enough)
- MAILTRAP_ACCOUNT_ID, MAILTRAP_INBOX_ID: the two numbers in the inbox URL,
  https://mailtrap.io/inboxes/<INBOX_ID>/... and the account id under Settings → Account
"""
import os
import time
import uuid

import httpx
import pytest

from app.config import settings
from app.mailer import Mailer

_API_TOKEN = os.getenv("MAILTRAP_API_TOKEN", "")
_ACCOUNT_ID = os.getenv("MAILTRAP_ACCOUNT_ID", "")
_INBOX_ID = os.getenv("MAILTRAP_INBOX_ID", "")
# Messages in the inbox, newest first.
_MESSAGES_URL = f"https://mailtrap.io/api/accounts/{_ACCOUNT_ID}/inboxes/{_INBOX_ID}/messages"

@pytest.mark.skipif(not (_API_TOKEN and _ACCOUNT_ID and _INBOX_ID and settings.smtp_user),
                    reason="Mailtrap credentials not set")
def test_email_arrives_in_mailtrap():
    """A sent email shows up in the Mailtrap inbox, found by its unique subject."""
    subject = f"iBanking test {uuid.uuid4()}"

    Mailer(settings).send("alice@example.com", subject, "plain body", "<p>html body</p>")

    found = None
    for _ in range(10):  # Mailtrap can take a moment to list a new email
        messages = httpx.get(_MESSAGES_URL, headers={"Api-Token": _API_TOKEN}, timeout=10).json()
        found = next((m for m in messages if m.get("subject") == subject), None)
        if found:
            break
        time.sleep(1)
    assert found is not None, "email not found in the Mailtrap inbox"
    assert found["to_email"] == "alice@example.com"
