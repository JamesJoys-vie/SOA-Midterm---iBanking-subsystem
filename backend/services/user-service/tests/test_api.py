"""Unit and integration tests for user-service (Tasks 1 & 4 - Nguyen Duc Hieu)."""
from decimal import Decimal
from fastapi.testclient import TestClient

from app.models import User


# ==============================================================================
# 1. HEALTH AND READINESS CHECKS
# ==============================================================================

def test_health_and_ready(client: TestClient):
    """Test liveness and readiness probe endpoints."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "user-service"

    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"


# ==============================================================================
# 2. TASK 1: AUTHENTICATION AND LOGIN
# ==============================================================================

def test_login_success(client: TestClient, sample_user: User):
    """Successful login returns a signed JWT Bearer access token."""
    res = client.post("/auth/login", json={"username": "alice", "password": "Password123!"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 1800  # 30 minutes


def test_login_wrong_password(client: TestClient, sample_user: User):
    """Login with wrong password must return 401 Unauthorized."""
    res = client.post("/auth/login", json={"username": "alice", "password": "WrongPassword!"})
    assert res.status_code == 401
    assert "Invalid username or password" in res.json()["detail"]


def test_login_nonexistent_user(client: TestClient):
    """Login with unknown username must return 401 Unauthorized."""
    res = client.post("/auth/login", json={"username": "not_found_user", "password": "Password123!"})
    assert res.status_code == 401
    assert "Invalid username or password" in res.json()["detail"]


# ==============================================================================
# 3. TASK 1: USER PROFILE & AVAILABLE BALANCE (GET /me)
# ==============================================================================

def test_get_me_unauthenticated(client: TestClient):
    """Accessing GET /me without token or Gateway header must return 401 Unauthorized."""
    res = client.get("/me")
    assert res.status_code == 401


def test_get_me_with_bearer_token(client: TestClient, sample_user: User):
    """Accessing GET /me with Bearer token returns full user profile and balance."""
    # 1. Login to get token
    login_res = client.post("/auth/login", json={"username": "alice", "password": "Password123!"})
    token = login_res.json()["access_token"]

    # 2. Call GET /me
    res = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    profile = res.json()
    assert profile["username"] == "alice"
    assert profile["full_name"] == "Nguyen Van A"
    assert profile["phone"] == "0900000001"
    assert profile["email"] == "alice@example.com"
    assert Decimal(str(profile["balance"])) == Decimal("30000000.00")


def test_get_me_with_gateway_header(client: TestClient, sample_user: User):
    """Accessing GET /users/me with X-User-Id injected by API Gateway."""
    res = client.get("/users/me", headers={"X-User-Id": sample_user.id})
    assert res.status_code == 200
    profile = res.json()
    assert profile["id"] == sample_user.id
    assert profile["full_name"] == sample_user.full_name


def test_get_account_balance(client: TestClient, sample_user: User):
    """Inquire account balance via GET /accounts/me."""
    res = client.get("/accounts/me", headers={"X-User-Id": sample_user.id})
    assert res.status_code == 200
    assert Decimal(str(res.json()["balance"])) == Decimal("30000000.00")


# ==============================================================================
# 4. TASK 4: CONDITIONAL DEBIT, IDEMPOTENCY & REFUND
# ==============================================================================

def test_debit_account_success_and_idempotency(client: TestClient, sample_user: User):
    """Test Task 4 conditional debit and idempotency:

    1. First debit: succeeds, balance decreases from 30M to 20M.
    2. Second debit with same txn_id: returns previous balance (20M) without deducting again.
    """
    txn_id = "txn-unique-test-1"

    # 1. First debit of 10,000,000 VND
    res1 = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res1.status_code == 200
    assert res1.json()["success"] is True
    assert Decimal(str(res1.json()["balance_after"])) == Decimal("20000000.00")

    # 2. Second debit with same txn_id (idempotency check)
    res2 = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res2.status_code == 200
    assert res2.json()["success"] is True
    assert Decimal(str(res2.json()["balance_after"])) == Decimal("20000000.00")


def test_debit_account_insufficient_balance(client: TestClient, sample_user: User):
    """Task 4: Attempting to debit more than available balance must return 422."""
    res = client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 50000000.00, "transaction_id": "txn-overdraft"},
    )
    assert res.status_code == 422
    assert "Insufficient balance" in res.json()["detail"]


def test_credit_account_refund_and_idempotency(client: TestClient, sample_user: User):
    """Task 4: Saga refund compensation test.

    1. Debit 10M -> balance 20M.
    2. Credit 10M (refund) -> balance restored to 30M.
    3. Duplicate credit with same txn_id -> returns 30M without adding again.
    """
    txn_id = "txn-refund-test-1"

    # Step 1: Debit 10,000,000 VND
    client.post(
        "/internal/accounts/debit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )

    # Step 2: Refund 10,000,000 VND
    res_credit = client.post(
        "/internal/accounts/credit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res_credit.status_code == 200
    assert res_credit.json()["success"] is True
    assert Decimal(str(res_credit.json()["balance_after"])) == Decimal("30000000.00")

    # Step 3: Duplicate refund with same txn_id
    res_credit2 = client.post(
        "/internal/accounts/credit",
        json={"user_id": sample_user.id, "amount": 10000000.00, "transaction_id": txn_id},
    )
    assert res_credit2.status_code == 200
    assert Decimal(str(res_credit2.json()["balance_after"])) == Decimal("30000000.00")


# ==============================================================================
# 5. TRANSACTION HISTORY RECORD AND INQUIRY
# ==============================================================================

def test_transaction_history_record_and_list(client: TestClient, sample_user: User):
    """Test recording a transaction and querying it through GET /history."""
    # 1. Record history entry
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

    # 2. Read history via GET /history
    hist_res = client.get("/history", headers={"X-User-Id": sample_user.id})
    assert hist_res.status_code == 200
    items = hist_res.json()
    assert len(items) >= 1
    assert items[0]["student_id"] == "52100001"
    assert items[0]["status"] == "SUCCESS"
    assert Decimal(str(items[0]["amount"])) == Decimal("15000000.00")
