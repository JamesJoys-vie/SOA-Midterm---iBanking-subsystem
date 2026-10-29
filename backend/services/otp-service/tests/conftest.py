"""Shared pytest fixtures: a throwaway database, a fake notifier and HTTP test clients."""
import os
import tempfile
from dataclasses import replace

# Point the app at a throwaway database before anything imports app.db.
# SQLite by default; set TEST_DATABASE_URL to run the same tests on PostgreSQL.
_db_file = os.path.join(tempfile.mkdtemp(), "otp_test.db")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_db_file}")
# Token the `client` fixture sends, standing in for payment-service.
os.environ["INTERNAL_API_TOKEN"] = "test-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings as app_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.notifier import NotifierError, get_notifier  # noqa: E402

# Request body payment-service would send to POST /otps.
OTP_REQUEST = {"txn_id": "txn-1", "email": "alice@example.com", "payer_name": "Nguyen Van A",
               "mssv": "52100001", "student_name": "Pham Minh D", "amount": 15_000_000}

class FakeNotifier:
    """Stands in for notification-service: records emails, or fails when told to."""

    def __init__(self):
        self.sent = []  # every OtpEmail "sent", in order
        self.fail = False  # True = behave as if notification-service is down

    def send_otp_email(self, email):
        """Record the email, or raise NotifierError when `fail` is set."""
        if self.fail:
            raise NotifierError("notification-service down")
        self.sent.append(email)

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
def settings():
    """App settings with a fixed test secret."""
    return replace(app_settings, otp_secret="test-secret")

@pytest.fixture
def notifier():
    """Fake notifier, also used by the HTTP app for the duration of the test."""
    fake = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_notifier, None)

@pytest.fixture
def client(notifier):
    """Client calling as payment-service would, with the internal token."""
    with TestClient(app, headers={"X-Internal-Token": "test-token"}) as c:
        yield c

@pytest.fixture
def anon_client():
    """Client with no token, to check that internal endpoints refuse it."""
    with TestClient(app) as c:
        yield c
