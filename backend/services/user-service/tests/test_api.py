"""Unit tests và API integration tests cho user-service."""
from decimal import Decimal
from fastapi.testclient import TestClient

from app.models import User


def test_health_and_ready(client: TestClient):
    """Kiểm tra liveness và readiness endpoints."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"


def test_login_success(client: TestClient, sample_user: User):
    """Đăng nhập thành công trả về JWT access token."""
    res = client.post("/auth/login", json={"username": "alice", "password": "Password123!"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 1800  # 30 phút


def test_login_wrong_password(client: TestClient, sample_user: User):
    """Đăng nhập sai mật khẩu trả về 401 Unauthorized."""
    res = client.post("/auth/login", json={"username": "alice", "password": "WrongPassword!"})
    assert res.status_code == 401
    assert "Tên đăng nhập hoặc mật khẩu" in res.json()["detail"]


def test_login_nonexistent_user(client: TestClient):
    """Đăng nhập với username không tồn tại trả về 401 Unauthorized."""
    res = client.post("/auth/login", json={"username": "not_found_user", "password": "Password123!"})
    assert res.status_code == 401
    assert "Tên đăng nhập hoặc mật khẩu" in res.json()["detail"]


def test_get_me_unauthenticated(client: TestClient):
    """Truy cập GET /me mà không có token hoặc header X-User-Id phải bị 401."""
    res = client.get("/me")
    assert res.status_code == 401


def test_get_me_with_bearer_token(client: TestClient, sample_user: User):
    """Truy cập GET /me với Authorization Bearer token."""
    # 1. Đăng nhập lấy token
    login_res = client.post("/auth/login", json={"username": "alice", "password": "Password123!"})
    token = login_res.json()["access_token"]

    # 2. Gọi GET /me
    res = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    profile = res.json()
    assert profile["username"] == "alice"
    assert profile["full_name"] == "Nguyen Van A"
    assert profile["phone"] == "0900000001"
    assert profile["email"] == "alice@example.com"
    assert Decimal(str(profile["balance"])) == Decimal("30000000.00")


def test_get_me_with_gateway_header(client: TestClient, sample_user: User):
    """Truy cập GET /users/me qua header X-User-Id do API Gateway truyền tiếp."""
    res = client.get("/users/me", headers={"X-User-Id": sample_user.id})
    assert res.status_code == 200
    profile = res.json()
    assert profile["id"] == sample_user.id
    assert profile["full_name"] == sample_user.full_name


def test_get_account_balance(client: TestClient, sample_user: User):
    """Kiểm tra endpoint lấy số dư GET /accounts/me."""
    res = client.get("/accounts/me", headers={"X-User-Id": sample_user.id})
    assert res.status_code == 200
    assert Decimal(str(res.json()["balance"])) == Decimal("30000000.00")


def test_debit_account_success_and_idempotency(client: TestClient, sample_user: User):
    """Kiểm tra trừ tiền có điều kiện và tính Idempotency:

    1. Trừ lần 1: thành công, số dư giảm từ 30M còn 20M.
    2. Trừ lần 2 cùng txn_id: trả về thành công với số dư 20M (không trừ lần 2).
    """
    txn_id = "txn-unique-test-1"

    # Lần 1: Trừ 10,000,000 VND
    res1 = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res1.status_code == 200
    assert res1.json()["success"] is True
    assert Decimal(str(res1.json()["balance_after"])) == Decimal("20000000.00")

    # Lần 2: Thử gửi lại đúng txn_id đó
    res2 = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res2.status_code == 200
    assert res2.json()["success"] is True
    # Số dư vẫn là 20,000,000 VND, không bị trừ thêm lần nữa!
    assert Decimal(str(res2.json()["balance_after"])) == Decimal("20000000.00")


def test_debit_account_insufficient_balance(client: TestClient, sample_user: User):
    """Trừ số tiền lớn hơn số dư khả dụng phải trả về 422 Unprocessable Entity."""
    res = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 50000000.00, "transaction_id": "txn-overdraft"},
    )
    assert res.status_code == 422
    assert "không đủ" in res.json()["detail"]


def test_transaction_history_record_and_list(client: TestClient, sample_user: User):
    """Kiểm tra ghi lịch sử và đọc danh sách lịch sử giao dịch (GET /history)."""
    # 1. Ghi lịch sử giao dịch
    rec_res = client.post(
        "/internal/history",
        json={
            "user_id": sample_user.id,
            "student_id": "52100001",
            "tuition_id": "tuition-001",
            "amount": 15000000.00,
            "status": "SUCCESS",
        },
    )
    assert rec_res.status_code == 200

    # 2. Đọc lại lịch sử bằng GET /history
    hist_res = client.get("/history", headers={"X-User-Id": sample_user.id})
    assert hist_res.status_code == 200
    items = hist_res.json()
    assert len(items) >= 1
    assert items[0]["student_id"] == "52100001"
    assert items[0]["status"] == "SUCCESS"
    assert Decimal(str(items[0]["amount"])) == Decimal("15000000.00")
