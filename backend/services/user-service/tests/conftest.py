"""Pytest fixtures and configuration for user-service test suite."""
import os
import sys
from decimal import Decimal
from pathlib import Path

# Add user-service directory to sys.path
service_dir = Path(__file__).resolve().parent.parent
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

# Configure test environment variables before importing the app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-unit-tests-12345"
os.environ["JWT_EXPIRE_MINUTES"] = "30"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Account, User
from app.security import hash_password

# Use StaticPool with SQLite in-memory so all connections share the same memory database
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database():
    """Create all tables before each test and drop them after test completion."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


@pytest.fixture
def db_session():
    """Provide an isolated database session for each test case."""
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def client(db_session: Session):
    """Provide a FastAPI TestClient configured with test database session."""
    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session: Session) -> User:
    """Seed a sample payer with a known password and balance (30,000,000 VND)."""
    user = User(
        id="user-test-uuid-1",
        username="alice",
        password_hash=hash_password("Password123!"),
        full_name="Nguyen Van A",
        phone="0900000001",
        email="alice@example.com",
    )
    db_session.add(user)
    db_session.flush()

    account = Account(
        id="acc-test-uuid-1",
        user_id=user.id,
        balance=Decimal("30000000.00"),
        version=0,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(user)
    return user
