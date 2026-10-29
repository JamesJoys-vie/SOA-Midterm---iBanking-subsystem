"""Cấu hình pytest fixtures cho user-service."""
import os
import sys
from decimal import Decimal
from pathlib import Path

# Thêm thư mục user-service vào sys.path để import app chuẩn xác
service_dir = Path(__file__).resolve().parent.parent
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

# Đặt biến môi trường trước khi import app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-unit-tests-12345"
os.environ["JWT_EXPIRE_MINUTES"] = "30"

from app.db import Base, get_db
from app.main import app
from app.models import Account, User
from app.security import hash_password

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Tạo engine in-memory cho test
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database():
    """Khởi tạo schema database trước mỗi test case và dọn dẹp sau khi xong."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


@pytest.fixture
def db_session():
    """Tạo một database session riêng biệt cho mỗi test case."""
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def client(db_session: Session):
    """Cung cấp FastAPI TestClient sử dụng db_session của test."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session: Session) -> User:
    """Tạo một người dùng mẫu có tài khoản và số dư để test."""
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
