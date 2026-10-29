"""Main entry point của user-service (FastAPI).

Thực hiện các nhiệm vụ của Hiệu trong Task 1 và Task 2:
- POST /login & POST /auth/login: Đăng nhập username/password, kiểm tra bcrypt, cấp JWT.
- GET /me & GET /users/me: Thông tin người nộp tiền (họ tên, SĐT, email) và số dư tài khoản.
- GET /accounts/me: Lấy riêng số dư khả dụng.
- GET /history & GET /transactions: Lấy lịch sử giao dịch của người dùng.
- GET /internal/users/{user_id}: API nội bộ cung cấp thông tin người dùng cho otp-service và payment-service.
- POST /internal/accounts/debit: Endpoint trừ tiền có điều kiện nguyên tử, đảm bảo mỗi txn_id chỉ trừ 1 lần.
"""
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_is_up, get_db, init_db
from app.schemas import (
    AccountBalanceResponse,
    DebitRequest,
    DebitResponse,
    LoginRequest,
    RecordHistoryRequest,
    TokenResponse,
    TransactionHistoryItem,
    UserProfile,
)
from app.security import get_current_user_id, security_bearer
from app.service import (
    authenticate_user,
    debit_user_account,
    get_account_balance,
    get_transaction_history,
    get_user_profile,
    record_transaction_history,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("user-service")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Khởi động ứng dụng: Chờ kết nối và tự động khởi tạo bảng dữ liệu nếu chưa có."""
    log.info("user-service đang khởi động...")
    init_db()
    yield
    log.info("user-service đang tắt...")


app = FastAPI(
    title="User Service - iBanking Subsystem",
    description="Dịch vụ quản lý người dùng, đăng nhập (bcrypt + JWT), tài khoản số dư và lịch sử giao dịch",
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# HEALTHCHECK & READINESS ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["Hệ thống"])
def health() -> dict:
    """Liveness check: Xác nhận tiến trình service đang chạy."""
    return {"status": "ok", "service": "user-service"}


@app.get("/ready", tags=["Hệ thống"])
def ready() -> JSONResponse:
    """Readiness check: Xác nhận service đã kết nối thành công tới database."""
    if db_is_up():
        return JSONResponse({"status": "ready", "service": "user-service"})
    return JSONResponse(
        {"status": "database unavailable", "service": "user-service"},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ==============================================================================
# TASK 1: ĐĂNG NHẬP VÀ XÁC THỰC (POST /login, POST /auth/login)
# ==============================================================================

@app.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["Xác thực"],
    summary="Đăng nhập tài khoản iBanking (chuẩn gateway)",
)
@app.post(
    "/login",
    response_model=TokenResponse,
    tags=["Xác thực"],
    summary="Đăng nhập tài khoản iBanking (chuẩn trực tiếp)",
)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Đăng nhập bằng username và password (không có chức năng đăng ký theo đề tài).

    Sử dụng bcrypt kiểm tra mật khẩu và trả về JWT Access Token (HS256) có hạn dùng 30 phút.
    """
    return authenticate_user(db, body.username, body.password)


# ==============================================================================
# TASK 1 & 2: THÔNG TIN NGƯỜI DÙNG & SỐ DƯ (GET /me, GET /users/me)
# ==============================================================================

def resolve_user_id(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    """Hàm phụ trợ lấy user_id từ JWT token hoặc header X-User-Id."""
    return get_current_user_id(auth, x_user_id)


@app.get(
    "/me",
    response_model=UserProfile,
    tags=["Người dùng"],
    summary="Lấy thông tin cá nhân và số dư khả dụng",
)
@app.get(
    "/users/me",
    response_model=UserProfile,
    tags=["Người dùng"],
    summary="Lấy thông tin cá nhân và số dư khả dụng (chuẩn gateway)",
)
def get_my_profile(
    user_id: str = Depends(resolve_user_id),
    db: Session = Depends(get_db),
) -> UserProfile:
    """Lấy họ tên, số điện thoại, email và số dư khả dụng của người đăng nhập.

    Thông tin này được giao diện nạp tự động vào mục 'Người nộp tiền' và 'Thông tin thanh toán' (chỉ đọc).
    """
    return get_user_profile(db, user_id)


@app.get(
    "/accounts/me",
    response_model=AccountBalanceResponse,
    tags=["Tài khoản"],
    summary="Lấy số dư khả dụng của người dùng",
)
def get_my_balance(
    user_id: str = Depends(resolve_user_id),
    db: Session = Depends(get_db),
) -> AccountBalanceResponse:
    """Lấy số dư khả dụng của tài khoản đăng nhập hiện tại."""
    balance = get_account_balance(db, user_id)
    return AccountBalanceResponse(balance=balance)


# ==============================================================================
# TASK 1: LỊCH SỬ GIAO DỊCH (GET /history, GET /transactions)
# ==============================================================================

@app.get(
    "/history",
    response_model=List[TransactionHistoryItem],
    tags=["Lịch sử giao dịch"],
    summary="Xem lịch sử các giao dịch thanh toán",
)
@app.get(
    "/transactions",
    response_model=List[TransactionHistoryItem],
    tags=["Lịch sử giao dịch"],
    summary="Xem danh sách giao dịch thanh toán (chuẩn gateway)",
)
def list_history(
    user_id: str = Depends(resolve_user_id),
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[TransactionHistoryItem]:
    """Lấy danh sách các giao dịch thanh toán học phí của người dùng, sắp xếp mới nhất lên đầu."""
    return get_transaction_history(db, user_id, limit=limit)


# ==============================================================================
# CÁC ENDPOINT NỘI BỘ (INTERNAL API - GIAO TIẾP GIỮA CÁC MICROSERVICES)
# ==============================================================================

@app.get(
    "/internal/users/{user_id}",
    response_model=UserProfile,
    tags=["Nội bộ"],
    summary="Lấy thông tin liên hệ của người nộp cho payment / notification service",
)
def get_user_internal(user_id: str, db: Session = Depends(get_db)) -> UserProfile:
    """API nội bộ cho phép payment-service và otp-service lấy email và họ tên người dùng để gửi mã OTP."""
    return get_user_profile(db, user_id)


@app.post(
    "/internal/accounts/debit",
    response_model=DebitResponse,
    tags=["Nội bộ"],
    summary="Trừ tiền có điều kiện (balance >= amount) và chống trùng lặp theo txn_id",
)
@app.post(
    "/accounts/debit",
    response_model=DebitResponse,
    tags=["Nội bộ"],
    summary="Trừ tiền tài khoản (alias)",
)
def debit_account_endpoint(body: DebitRequest, db: Session = Depends(get_db)) -> DebitResponse:
    """Endpoint trừ tiền khỏi tài khoản người nộp.

    - Cập nhật có điều kiện: chỉ trừ khi balance >= amount.
    - Đảm bảo Idempotency: mỗi txn_id chỉ trừ đúng 1 lần duy nhất.
    """
    return debit_user_account(db, body.user_id, body.amount, body.transaction_id)


@app.post(
    "/internal/history",
    response_model=TransactionHistoryItem,
    tags=["Nội bộ"],
    summary="Ghi nhận giao dịch hoàn tất vào lịch sử người dùng",
)
def record_history_endpoint(
    body: RecordHistoryRequest,
    db: Session = Depends(get_db),
) -> TransactionHistoryItem:
    """API nội bộ cho phép payment-service ghi lại kết quả giao dịch vào lịch sử của người nộp."""
    record = record_transaction_history(
        db,
        user_id=body.user_id,
        student_id=body.student_id,
        tuition_id=body.tuition_id,
        amount=body.amount,
        status=body.status,
        failure_reason=body.failure_reason,
    )
    return TransactionHistoryItem.model_validate(record)
