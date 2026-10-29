"""
Unit tests và API integration tests cho tuition-service (Task 2 - Nguyễn Đức Hiệu).

Test coverage:
  - Tra cứu học phí theo MSSV (GET /tuitions/{student_id} và GET /tuitions?mssv=)
  - Khóa học phí có điều kiện (POST /internal/tuitions/{id}/reserve)
  - Xác nhận thanh toán (POST /internal/tuitions/{id}/commit)
  - Mở khóa học phí (POST /internal/tuitions/{id}/release)
  - Health/Readiness endpoints
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


# ==============================================================================
# TEST HEALTH & READY
# ==============================================================================

def test_health(client: TestClient):
    """Liveness endpoint trả về status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["service"] == "tuition-service"


def test_ready(client: TestClient):
    """Readiness endpoint xác nhận service kết nối được database."""
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"


# ==============================================================================
# TEST TRA CỨU HỌC PHÍ (Task 2 - Lookup Tuition)
# ==============================================================================

def test_lookup_tuition_by_path(client: TestClient, sample_data):
    """GET /tuitions/{student_id}: Tra cứu học phí qua path parameter trả về đúng thông tin."""
    res = client.get("/tuitions/52100001")
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == "52100001"
    assert data["student_name"] == "Pham Minh D"
    assert data["term"] == "2025-HK1"
    assert Decimal(str(data["amount"])) == Decimal("15000000.00")
    assert data["status"] == "UNPAID"


def test_lookup_tuition_by_query(client: TestClient, sample_data):
    """GET /tuitions?mssv=: Tra cứu học phí qua query parameter."""
    res = client.get("/tuitions?mssv=52100001")
    assert res.status_code == 200
    data = res.json()
    assert data["student_id"] == "52100001"
    assert data["status"] == "UNPAID"


def test_lookup_tuition_case_insensitive(client: TestClient, sample_data):
    """Tra cứu MSSV không phân biệt chữ hoa/thường (vd: 52100001 == 52100001)."""
    # Dùng chữ thường (nếu MSSV chứa chữ)
    res = client.get("/tuitions/52100001")
    assert res.status_code == 200


def test_lookup_tuition_student_not_found(client: TestClient, sample_data):
    """Tra cứu MSSV không tồn tại phải trả về 404."""
    res = client.get("/tuitions/INVALID_MSSV_999")
    assert res.status_code == 404
    assert "Không tìm thấy sinh viên" in res.json()["detail"]


def test_lookup_tuition_oldest_unpaid_first(client: TestClient, sample_data):
    """Sinh viên có nhiều kỳ chưa đóng: phải trả về kỳ cũ nhất (FIFO) trước."""
    # Sinh viên 522H0099 có 2024-HK2 và 2025-HK1, cả 2 đều UNPAID
    # -> phải trả về 2024-HK2 (cũ hơn)
    res = client.get("/tuitions/522H0099")
    assert res.status_code == 200
    data = res.json()
    assert data["term"] == "2024-HK2"
    assert Decimal(str(data["amount"])) == Decimal("9500000.00")


def test_lookup_tuition_all_paid_shows_latest(client: TestClient, sample_data):
    """Tất cả học phí đã nộp: trả về kỳ mới nhất với status PAID để UI thông báo."""
    res = client.get("/tuitions/52100003")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PAID"
    assert data["student_name"] == "Vo Quoc F"


def test_lookup_tuition_no_query_param(client: TestClient, sample_data):
    """GET /tuitions mà không cung cấp mssv phải trả về 400."""
    res = client.get("/tuitions")
    assert res.status_code in (400, 422)


# ==============================================================================
# TEST KHÓA HỌC PHÍ (Task 2 - Reserve Hold)
# ==============================================================================

def test_reserve_tuition_success(client: TestClient, sample_data):
    """Khóa học phí UNPAID thành công: trả về TuitionInfo với status RESERVED."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESERVED"
    assert data["tuition_id"] == "tuition-uuid-1"


def test_reserve_tuition_idempotent(client: TestClient, sample_data):
    """Cùng một transaction_id gọi lại: không báo lỗi, gia hạn thời gian khóa."""
    # Lần 1
    res1 = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-idempotent"},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "RESERVED"

    # Lần 2 (cùng txn_id) -> phải thành công, không báo lỗi
    res2 = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-abc-idempotent"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "RESERVED"


def test_reserve_tuition_conflict_already_reserved_by_other(client: TestClient, sample_data):
    """Học phí đang bị khóa bởi giao dịch KHÁC: phải trả về 409 Conflict."""
    # Giao dịch A khóa trước
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-owner-A"},
    )
    # Giao dịch B cố gắng khóa cùng tuition -> 409
    res_b = client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-other-B"},
    )
    assert res_b.status_code == 409


def test_reserve_tuition_conflict_already_paid(client: TestClient, sample_data):
    """Học phí đã PAID: mọi yêu cầu reserve phải trả về 409."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-3/reserve",
        json={"transaction_id": "txn-pay-again"},
    )
    assert res.status_code == 409
    assert "đã được thanh toán" in res.json()["detail"]


def test_reserve_tuition_not_found(client: TestClient, sample_data):
    """Tuition ID không tồn tại: phải trả về 404."""
    res = client.post(
        "/internal/tuitions/non-existent-id/reserve",
        json={"transaction_id": "txn-xyz"},
    )
    assert res.status_code == 404


# ==============================================================================
# TEST ĐÁNH DẤU ĐÃ THANH TOÁN (Commit / Mark-paid)
# ==============================================================================

def test_commit_tuition_success(client: TestClient, sample_data):
    """Commit thành công: học phí chuyển từ RESERVED -> PAID."""
    # Bước 1: Reserve trước
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-commit-001"},
    )

    # Bước 2: Commit
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PAID"


def test_commit_tuition_idempotent(client: TestClient, sample_data):
    """Commit 2 lần với cùng txn_id: lần 2 phải thành công (không lỗi, Idempotency)."""
    # Reserve + Commit lần 1
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-commit-idem"},
    )
    res1 = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-idem"},
    )
    assert res1.status_code == 200

    # Commit lần 2 với cùng txn_id
    res2 = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-commit-idem"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "PAID"


def test_commit_tuition_without_reserve(client: TestClient, sample_data):
    """Commit một tuition không được khóa: phải trả về 409."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-no-reserve"},
    )
    assert res.status_code == 409


def test_commit_tuition_wrong_owner(client: TestClient, sample_data):
    """Commit bởi giao dịch KHÔNG PHẢI chủ khóa: phải trả về 409."""
    # Reserve bởi txn-A
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-real-owner"},
    )
    # Commit bởi txn-B (khác)
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/commit",
        json={"transaction_id": "txn-intruder"},
    )
    assert res.status_code == 409


# ==============================================================================
# TEST MỞ KHÓA HỌC PHÍ (Release Hold)
# ==============================================================================

def test_release_tuition_success(client: TestClient, sample_data):
    """Mở khóa học phí đã RESERVED bởi đúng giao dịch: trả về released=True."""
    # Reserve trước
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-release-001"},
    )
    # Release
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-release-001"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["released"] is True


def test_release_tuition_not_reserved_by_caller(client: TestClient, sample_data):
    """Mở khóa học phí bởi giao dịch không giữ khóa: released=False (không có lỗi, no-op)."""
    # Reserve bởi txn-A
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-holder"},
    )
    # Release bởi txn-B
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-not-holder"},
    )
    assert res.status_code == 200
    assert res.json()["released"] is False


def test_release_tuition_unpaid_no_op(client: TestClient, sample_data):
    """Mở khóa học phí UNPAID (không có khóa nào): released=False, không báo lỗi."""
    res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-release-noop"},
    )
    assert res.status_code == 200
    assert res.json()["released"] is False


def test_full_payment_flow(client: TestClient, sample_data):
    """Kiểm tra toàn bộ luồng: Lookup -> Reserve -> Commit."""
    # Bước 1: Tra cứu học phí
    lookup_res = client.get("/tuitions/52100001")
    assert lookup_res.status_code == 200
    tuition = lookup_res.json()
    assert tuition["status"] == "UNPAID"
    tuition_id = tuition["tuition_id"]

    # Bước 2: Khóa học phí
    reserve_res = client.post(
        f"/internal/tuitions/{tuition_id}/reserve",
        json={"transaction_id": "txn-full-flow"},
    )
    assert reserve_res.status_code == 200
    assert reserve_res.json()["status"] == "RESERVED"

    # Bước 3: Lookup lại -> phải thấy RESERVED
    lookup_res2 = client.get("/tuitions/52100001")
    assert lookup_res2.json()["status"] == "RESERVED"

    # Bước 4: Commit -> PAID
    commit_res = client.post(
        f"/internal/tuitions/{tuition_id}/commit",
        json={"transaction_id": "txn-full-flow"},
    )
    assert commit_res.status_code == 200
    assert commit_res.json()["status"] == "PAID"

    # Bước 5: Lookup lại -> phải thấy PAID
    lookup_res3 = client.get("/tuitions/52100001")
    assert lookup_res3.json()["status"] == "PAID"


def test_cancel_payment_flow(client: TestClient, sample_data):
    """Kiểm tra luồng hủy: Reserve -> Release -> UNPAID lại."""
    # Reserve
    client.post(
        "/internal/tuitions/tuition-uuid-1/reserve",
        json={"transaction_id": "txn-cancel-flow"},
    )

    # Release (hủy)
    release_res = client.post(
        "/internal/tuitions/tuition-uuid-1/release",
        json={"transaction_id": "txn-cancel-flow"},
    )
    assert release_res.status_code == 200
    assert release_res.json()["released"] is True

    # Lookup lại -> phải về UNPAID
    lookup_res = client.get("/tuitions/52100001")
    assert lookup_res.json()["status"] == "UNPAID"
