"""Pytest fixtures cho tuition-service."""
import os
import sys
from decimal import Decimal
from pathlib import Path

# Thêm thư mục tuition-service vào sys.path
service_dir = Path(__file__).resolve().parent.parent
if str(service_dir) not in sys.path:
    sys.path.insert(0, str(service_dir))

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

# Engine dùng chung (StaticPool) để tất cả connections trong test
# cùng nhìn vào một vùng bộ nhớ duy nhất
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Mọi kết nối đều dùng CÙNG một connection -> nhìn thấy nhau
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database():
    """Khởi tạo cấu trúc bảng trước mỗi test và dọn dẹp sau khi xong."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


@pytest.fixture
def db_session():
    """Cung cấp database session cho test."""
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def client(db_session: Session):
    """Cung cấp FastAPI TestClient sử dụng db_session của test.

    Override get_db để inject đúng session có kết nối vào test_engine (StaticPool).
    Vì StaticPool, mọi request trong TestClient đều "thấy" dữ liệu đã commit từ db_session.
    """
    def override_get_db():
        """Tạo session mới từ cùng engine -> cùng vùng nhớ SQLite."""
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_data(db_session: Session):
    """Tạo dữ liệu sinh viên và học phí mẫu để test các trường hợp."""
    # Sinh viên 1: Có 1 khoản học phí chưa đóng
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

    # Sinh viên 2: Có 2 khoản học phí (2024-HK2 và 2025-HK1), cả 2 đều chưa đóng
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

    # Sinh viên 3: Đã nộp toàn bộ học phí (PAID)
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
