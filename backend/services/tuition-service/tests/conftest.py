"""Pytest fixtures and configuration for tuition-service test suite."""
import os
import sys
from decimal import Decimal
from pathlib import Path

# Add tuition-service directory to sys.path
service_dir = Path(__file__).resolve().parent.parent
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

# Configure test environment variables
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["RESERVATION_TTL_SECONDS"] = "600"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import PAID, UNPAID, Student, Tuition

# StaticPool ensures all connections within tests access the exact same in-memory SQLite database
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
    """Provide a FastAPI TestClient configured to use the test engine session."""
    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_data(db_session: Session):
    """Seed sample students and tuition liabilities for test scenarios."""
    # Student 1: Has 1 unpaid tuition liability
    s1 = Student(student_id="52100001", full_name="Pham Minh D")
    db_session.add(s1)
    t1 = Tuition(
        id="tuition-uuid-1",
        student_id="52100001",
        term="2025-HK1",
        amount=Decimal("15000000.00"),
        status=UNPAID,
        version=0,
    )
    db_session.add(t1)

    # Student 2: Has 2 unpaid tuition liabilities (2024-HK2 and 2025-HK1)
    s2 = Student(student_id="522H0099", full_name="Kieu Anh Thu")
    db_session.add(s2)
    t2_old = Tuition(
        id="tuition-uuid-2-old",
        student_id="522H0099",
        term="2024-HK2",
        amount=Decimal("9500000.00"),
        status=UNPAID,
        version=0,
    )
    t2_new = Tuition(
        id="tuition-uuid-2-new",
        student_id="522H0099",
        term="2025-HK1",
        amount=Decimal("18000000.00"),
        status=UNPAID,
        version=0,
    )
    db_session.add(t2_old)
    db_session.add(t2_new)

    # Student 3: Has already paid all tuition
    s3 = Student(student_id="52100003", full_name="Vo Quoc F")
    db_session.add(s3)
    t3 = Tuition(
        id="tuition-uuid-3",
        student_id="52100003",
        term="2025-HK1",
        amount=Decimal("12000000.00"),
        status=PAID,
        paid_by_txn="txn-completed-before",
        version=1,
    )
    db_session.add(t3)

    db_session.commit()
    return {"s1": s1, "t1": t1, "s2": s2, "s3": s3}
