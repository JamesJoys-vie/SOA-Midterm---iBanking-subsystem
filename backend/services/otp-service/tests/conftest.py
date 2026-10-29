"""Shared pytest fixtures: a throwaway SQLite database and HTTP test clients."""
import os
import tempfile
from dataclasses import replace

# Point the app at a throwaway SQLite file before anything imports app.db.
_db_file = os.path.join(tempfile.mkdtemp(), "otp_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"
# Token the `client` fixture sends, standing in for payment-service.
os.environ["INTERNAL_API_TOKEN"] = "test-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings as app_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

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
def client():
    """Client calling as payment-service would, with the internal token."""
    with TestClient(app, headers={"X-Internal-Token": "test-token"}) as c:
        yield c

@pytest.fixture
def anon_client():
    """Client with no token, to check that internal endpoints refuse it."""
    with TestClient(app) as c:
        yield c