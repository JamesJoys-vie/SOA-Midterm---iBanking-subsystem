"""Unit and API integration tests for tuition-service (Tasks 2 & 4 - Nguyen Duc Hieu).

Test coverage:
  - Task 2: Tuition lookup by MSSV (GET /tuitions/{student_id} and GET /tuitions?mssv=)
  - Task 2: Conditional reservation hold (POST /internal/tuitions/{id}/reserve)
  - Task 4: Mark-paid commit (POST /internal/tuitions/{id}/commit)
  - Task 4: Hold release (POST /internal/tuitions/{id}/release)
  - Health & readiness probes
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


# ==============================================================================
# 1. HEALTH AND READINESS PROBES
# ==============================================================================

def test_health(client: TestClient):
    """Liveness probe returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "tuition-service"


def test_ready(client: TestClient):
    """Readiness probe verifies database connectivity."""
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


# ==============================================================================
# 2. TASK 2: TUITION LOOKUP
# ==============================================================================

def test_lookup_tuition_by_path(client: TestClient, sample_data):
    """GET /tuitions/{student_id}: Path parameter lookup returns correct student and tuition data."""
    res = client.get("/tuitions/52100001")
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == "52100001"
    assert data["student_name"] == "Pham Minh D"
    assert data["term"] == "2025-HK1"
    assert Decimal(str(data["amount"])) == Decimal("15000000.00")
    assert data["status"] == "UNPAID"


def test_lookup_tuition_by_query(client: TestClient, sample_data):
    """GET /tuitions?mssv=: Query parameter lookup returns tuition data."""
    res = client.get("/tuitions?mssv=52100001")
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == "52100001"
    assert data["status"] == "UNPAID"


def test_lookup_tuition_case_insensitive(client: TestClient, sample_data):
    """Student ID lookup is case-insensitive."""
    res = client.get("/tuitions/52100001")
    assert res.status_code == 200


def test_lookup_tuition_student_not_found(client: TestClient, sample_data):
    """Lookup for an unknown student ID must return 404 Not Found."""
    res = client.get("/tuitions/INVALID_MSSV_999")
    assert res.status_code == 404
    assert "Student with MSSV" in res.json()["detail"]


def test_lookup_tuition_oldest_unpaid_first(client: TestClient, sample_data):
    """Student with multiple unpaid terms: must return the oldest unpaid term (FIFO)."""
    # Student 522H0099 has 2024-HK2 and 2025-HK1 (both UNPAID)
    # -> must return 2024-HK2 first
    res = client.get("/tuitions/522H0099")
    assert res.status_code == 200
    data = res.json()
    assert data["term"] == "2024-HK2"
    assert Decimal(str(data["amount"])) == Decimal("9500000.00")


def test_lookup_tuition_all_paid_shows_latest(client: TestClient, sample_data):
    """If all tuition terms are paid, return the latest term with status PAID."""
    res = client.get("/tuitions/52100003")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PAID"
    assert data["student_name"] == "Vo Quoc F"


def test_lookup_tuition_no_query_param(client: TestClient, sample_data):
    """GET /tuitions without query parameter must return 400 Bad Request."""
    res = client.get("/tuitions")
    assert res.status_code in (400, 422)


# ==============================================================================
# 3. TASK 2: CONDITIONAL RESERVATION HOLD
# ==============================================================================

def test_reserve_tuition_success(client: TestClient, sample_data):
    """Holding an UNPAID tuition succeeds and returns status RESERVED."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESERVED"
    assert data["tuition_id"] == "tuition-uuid-1"


def test_reserve_tuition_idempotent(client: TestClient, sample_data):
    """Calling reserve again with the same transaction_id extends hold without error."""
    # First call
    res1 = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-idempotent"},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "RESERVED"

    # Second call (same txn_id)
    res2 = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-idempotent"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "RESERVED"


def test_reserve_tuition_conflict_already_reserved_by_other(client: TestClient, sample_data):
    """Tuition held by ANOTHER transaction must return 409 Conflict."""
    # Txn A reserves first
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-owner-A"},
    )
    # Txn B attempts to reserve same tuition -> 409
    res_b = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-other-B"},
    )
    assert res_b.status_code == 409


def test_reserve_tuition_conflict_already_paid(client: TestClient, sample_data):
    """Attempting to reserve already PAID tuition must return 409 Conflict."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-3/reserve",
        json={"transaction_id": "txn-pay-again"},
    )
    assert res.status_code == 409
    assert "already paid" in res.json()["detail"]


def test_reserve_tuition_not_found(client: TestClient, sample_data):
    """Attempting to reserve non-existent tuition ID returns 404."""
    res = client.post(
        "/internal/tuitions/non-existent-id/reserve",
        json={"transaction_id": "txn-xyz"},
    )
    assert res.status_code == 404


# ==============================================================================
# 4. TASK 4: MARK-PAID (COMMIT)
# ==============================================================================

def test_commit_tuition_success(client: TestClient, sample_data):
    """Commit transitions status from RESERVED to PAID."""
    # 1. Reserve first
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-commit-001"},
    )

    # 2. Commit
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PAID"


def test_commit_tuition_idempotent(client: TestClient, sample_data):
    """Committing multiple times with same txn_id succeeds idempotently."""
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-commit-idem"},
    )
    res1 = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-idem"},
    )
    assert res1.status_code == 200

    # Repeat commit with same txn_id
    res2 = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-idem"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "PAID"


def test_commit_tuition_without_reserve(client: TestClient, sample_data):
    """Committing an unreserved tuition returns 409 Conflict."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-no-reserve"},
    )
    assert res.status_code == 409


def test_commit_tuition_wrong_owner(client: TestClient, sample_data):
    """Committing by a transaction other than the hold owner returns 409 Conflict."""
    # Reserved by txn-A
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-real-owner"},
    )
    # Txn-B tries to commit
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-intruder"},
    )
    assert res.status_code == 409


# ==============================================================================
# 5. TASK 4: RELEASE HOLD (COMPENSATION)
# ==============================================================================

def test_release_tuition_success(client: TestClient, sample_data):
    """Releasing a hold owned by caller succeeds with released=True."""
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-release-001"},
    )
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-release-001"},
    )
    assert res.status_code == 200
    assert res.json()["released"] is True


def test_release_tuition_not_reserved_by_caller(client: TestClient, sample_data):
    """Releasing a hold owned by another transaction returns released=False (no error)."""
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-holder"},
    )
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-not-holder"},
    )
    assert res.status_code == 200
    assert res.json()["released"] is False


def test_release_tuition_unpaid_no_op(client: TestClient, sample_data):
    """Releasing an unheld tuition is a no-op (released=False)."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-release-noop"},
    )
    assert res.status_code == 200
    assert res.json()["released"] is False


def test_full_payment_flow(client: TestClient, sample_data):
    """End-to-end payment happy path: Lookup -> Reserve -> Commit."""
    # 1. Lookup
    lookup_res = client.get("/tuitions/52100001")
    assert lookup_res.status_code == 200
    tuition = lookup_res.json()
    assert tuition["status"] == "UNPAID"
    tuition_id = tuition["tuition_id"]

    # 2. Reserve
    reserve_res = client.post(
        f"/internal/tuitions/{tuition_id}/reserve",
        json={"transaction_id": "txn-full-flow"},
    )
    assert reserve_res.status_code == 200
    assert reserve_res.json()["status"] == "RESERVED"

    # 3. Lookup again -> RESERVED
    lookup_res2 = client.get("/tuitions/52100001")
    assert lookup_res2.json()["status"] == "RESERVED"

    # 4. Commit -> PAID
    commit_res = client.post(
        f"/internal/tuitions/{tuition_id}/commit",
        json={"transaction_id": "txn-full-flow"},
    )
    assert commit_res.status_code == 200
    assert commit_res.json()["status"] == "PAID"

    # 5. Lookup again -> PAID
    lookup_res3 = client.get("/tuitions/52100001")
    assert lookup_res3.json()["status"] == "PAID"


def test_cancel_payment_flow(client: TestClient, sample_data):
    """End-to-end cancellation flow: Reserve -> Release -> returns to UNPAID."""
    # 1. Reserve
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-cancel-flow"},
    )

    # 2. Release
    release_res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-cancel-flow"},
    )
    assert release_res.status_code == 200
    assert release_res.json()["released"] is True

    # 3. Lookup again -> UNPAID
    lookup_res = client.get("/tuitions/52100001")
    assert lookup_res.json()["status"] == "UNPAID"
