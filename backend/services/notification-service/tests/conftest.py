"""Shared pytest fixtures: a throwaway database, a fake mailer and HTTP test clients."""
import os
import tempfile

# Point the app at a throwaway database before anything imports app.db.
# SQLite by default; set TEST_DATABASE_URL to run the same tests on PostgreSQL.
_db_file = os.path.join(tempfile.mkdtemp(), "notification_test.db")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_db_file}")
# Token the `client` fixture sends, standing in for otp-service / payment-service.
os.environ["INTERNAL_API_TOKEN"] = "test-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.mailer import MailerError, get_mailer  # noqa: E402
from app.main import app  # noqa: E402

# Request bodies the callers would send.
OTP_EMAIL = {"to": "alice@example.com", "payer_name": "Nguyen Van A", "code": "482913",
             "expires_in": 300, "mssv": "52100001", "student_name": "Pham Minh D",
             "amount": 15_000_000}
RECEIPT_EMAIL = {"txn_id": "7f3a-c21e", "to": "alice@example.com", "payer_name": "Nguyen Van A",
                 "mssv": "52100001", "student_name": "Pham Minh D", "term": "2025-HK1",
                 "amount": 15_000_000, "balance_after": 15_000_000,
                 "completed_at": "2026-10-09T07:32:00Z"}

class FakeMailer:
    """Stands in for the SMTP server: records emails, or fails when told to."""

    def __init__(self):
        self.sent = []  # (to, subject, text, html) of every email "sent"
        self.fail = False  # True = behave as if the mail server is down

    def send(self, to, subject, text, html):
        """Record the email, or raise MailerError when `fail` is set."""
        if self.fail:
            raise MailerError("smtp down")
        self.sent.append((to, subject, text, html))

@pytest.fixture(autouse=True)
def _fresh_db():
    """Give every test empty tables."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield

@pytest.fixture
def db():
    """Database session for calling the service functions directly."""
    with SessionLocal() as session:
        yield session

@pytest.fixture
def mailer():
    """Fake mailer, also used by the HTTP app for the duration of the test."""
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_mailer, None)

@pytest.fixture
def client(mailer):
    """Client calling as an internal service would, with the internal token."""
    with TestClient(app, headers={"X-Internal-Token": "test-token"}) as c:
        yield c

@pytest.fixture
def anon_client():
    """Client with no token, to check that the email endpoints refuse it."""
    with TestClient(app) as c:
        yield c
