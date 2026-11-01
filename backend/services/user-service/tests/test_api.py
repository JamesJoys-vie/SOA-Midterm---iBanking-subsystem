"""Unit and integration tests for user-service (Tasks 1 & 4 - Nguyen Duc Hieu)."""
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, User


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


# ==============================================================================
# 6. ISSUE #21 BUG FIXES: HANDLING USER WITHOUT ACCOUNT
# ==============================================================================

def test_user_without_account_profile_returns_404(
    client: TestClient,
    user_without_account: User,
    db_session: Session,
):
    """Bug 2 & 3: GET /me and GET /users/me must return 404 and NOT create an account."""
    # 1. GET /me via Bearer token
    login_res = client.post(
        "/auth/login",
        json={"username": "noacc_user", "password": "Password123!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    res_me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 404
    assert res_me.json()["detail"] == "Payment account not found for this user"

    # 2. GET /users/me via Gateway header
    res_users_me = client.get("/users/me", headers={"X-User-Id": user_without_account.id})
    assert res_users_me.status_code == 404
    assert res_users_me.json()["detail"] == "Payment account not found for this user"

    # Verify no account was automatically created in the database
    account_count = db_session.scalar(
        select(func.count(Account.id)).where(Account.user_id == user_without_account.id)
    )
    assert account_count == 0


def test_user_without_account_internal_get_returns_404(
    client: TestClient,
    user_without_account: User,
    db_session: Session,
):
    """Bug 2 & 3: GET /internal/users/{user_id} must return 404 and NOT create an account."""
    res = client.get(f"/internal/users/{user_without_account.id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "Payment account not found for this user"

    # Verify database was not modified
    account_count = db_session.scalar(
        select(func.count(Account.id)).where(Account.user_id == user_without_account.id)
    )
    assert account_count == 0


def test_user_without_account_balance_returns_404(
    client: TestClient,
    user_without_account: User,
):
    """Consistency check: GET /accounts/me must return 404 when user has no account."""
    res = client.get("/accounts/me", headers={"X-User-Id": user_without_account.id})
    assert res.status_code == 404
    assert res.json()["detail"] == "Payment account not found for this user"


def test_user_without_account_record_history_returns_404(
    client: TestClient,
    user_without_account: User,
):
    """Bug 1: POST /internal/history must return 404 when user has no account (avoiding foreign key failure)."""
    res = client.post(
        "/internal/history",
        json={
            "user_id": user_without_account.id,
            "student_id": "52100001",
            "tuition_id": "tuition-001",
            "amount": 15000000.00,
            "status": "SUCCESS",
        },
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Payment account not found for this user"


def test_profile_idempotent_read_consistency(
    client: TestClient,
    user_without_account: User,
    db_session: Session,
):
    """Verify Bug 2 reproduction flow does not mutate state or cause race conditions:
    1. GET /accounts/me -> 404
    2. GET /internal/users/{id} -> 404 (does NOT create an account)
    3. GET /accounts/me -> still 404
    """
    res1 = client.get("/accounts/me", headers={"X-User-Id": user_without_account.id})
    assert res1.status_code == 404

    res2 = client.get(f"/internal/users/{user_without_account.id}")
    assert res2.status_code == 404

    res3 = client.get("/accounts/me", headers={"X-User-Id": user_without_account.id})
    assert res3.status_code == 404

    account_count = db_session.scalar(
        select(func.count(Account.id)).where(Account.user_id == user_without_account.id)
    )
    assert account_count == 0


def test_sqlite_foreign_key_constraint_enforced(db_session: Session):
    """Verify that PRAGMA foreign_keys=ON is active in SQLite tests.

    Attempting to directly persist a TransactionHistory with an invalid account_id
    must trigger an IntegrityError, ensuring test fidelity with MySQL production.
    """
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.models import TransactionHistory

    invalid_txn = TransactionHistory(
        account_id="unknown-account",
        payer_user_id="user-test-uuid-1",
        student_id="52100001",
        tuition_id="tuition-001",
        amount=Decimal("10000.00"),
        status="SUCCESS",
    )
    db_session.add(invalid_txn)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


