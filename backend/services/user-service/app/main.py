"""Main entry point for user-service (FastAPI).

Implements Hieu's responsibilities:
- Task 1:
  * POST /login & POST /auth/login: User login (bcrypt check, JWT issue).
  * GET /me & GET /users/me: Payer profile (name, phone, email) & available balance.
  * GET /accounts/me: Available balance inquiry.
  * GET /history & GET /transactions: User transaction history.
- Task 2:
  * GET /internal/users/{user_id}: Internal API for payer contact details (OTP/receipt emails).
- Task 4:
  * POST /internal/accounts/debit: Atomic conditional balance deduction (balance >= amount, idempotent per txn_id).
  * POST /internal/accounts/credit: Account refund (compensation in payment saga).
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
    CreditRequest,
    CreditResponse,
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
    credit_user_account,
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
    """Application startup: Wait for database connection and initialize tables."""
    log.info("user-service is starting up...")
    init_db()
    yield
    log.info("user-service is shutting down...")


app = FastAPI(
    title="User Service - iBanking Subsystem",
    description="Manages users, login (bcrypt + JWT), account balances, debit/credit and history",
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# HEALTHCHECK & READINESS ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["System"])
def health() -> dict:
    """Liveness check: Indicates the service process is up."""
    return {"status": "ok", "service": "user-service"}


@app.get("/ready", tags=["System"])
def ready() -> JSONResponse:
    """Readiness check: Indicates the database connection is healthy."""
    if db_is_up():
        return JSONResponse({"status": "ready", "service": "user-service"})
    return JSONResponse(
        {"status": "database unavailable", "service": "user-service"},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ==============================================================================
# TASK 1: AUTHENTICATION & LOGIN (POST /login, POST /auth/login)
# ==============================================================================

@app.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="User login (Gateway standard path)",
)
@app.post(
    "/login",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="User login (Direct path)",
)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Log in with username and password.

    Verifies password using bcrypt and returns a signed JWT access token (HS256).
    """
    return authenticate_user(db, body.username, body.password)


# ==============================================================================
# TASK 1 & 2: USER PROFILE & BALANCE (GET /me, GET /users/me)
# ==============================================================================

def resolve_user_id(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    """Helper dependency to resolve user_id from either JWT token or X-User-Id header."""
    return get_current_user_id(auth, x_user_id)


@app.get(
    "/me",
    response_model=UserProfile,
    tags=["User Profile"],
    summary="Get authenticated user profile and available balance",
)
@app.get(
    "/users/me",
    response_model=UserProfile,
    tags=["User Profile"],
    summary="Get authenticated user profile and available balance (Gateway standard)",
)
def get_my_profile(
    user_id: str = Depends(resolve_user_id),
    db: Session = Depends(get_db),
) -> UserProfile:
    """Get full name, phone number, email, and available balance for the logged-in user.

    Used by the frontend to auto-populate readonly Payer details on the payment page.
    """
    return get_user_profile(db, user_id)


@app.get(
    "/accounts/me",
    response_model=AccountBalanceResponse,
    tags=["Account"],
    summary="Get current account balance",
)
def get_my_balance(
    user_id: str = Depends(resolve_user_id),
    db: Session = Depends(get_db),
) -> AccountBalanceResponse:
    """Inquire the available balance for the authenticated user."""
    balance = get_account_balance(db, user_id)
    return AccountBalanceResponse(balance=balance)


# ==============================================================================
# TASK 1: TRANSACTION HISTORY (GET /history, GET /transactions)
# ==============================================================================

@app.get(
    "/history",
    response_model=List[TransactionHistoryItem],
    tags=["Transaction History"],
    summary="View payment transaction history",
)
@app.get(
    "/transactions",
    response_model=List[TransactionHistoryItem],
    tags=["Transaction History"],
    summary="View payment transaction history (Gateway standard)",
)
def list_history(
    user_id: str = Depends(resolve_user_id),
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[TransactionHistoryItem]:
    """Retrieve transaction history of the authenticated user, sorted newest first."""
    return get_transaction_history(db, user_id, limit=limit)


# ==============================================================================
# INTERNAL ENDPOINTS (CALLED BY OTHER MICROSERVICES)
# ==============================================================================

@app.get(
    "/internal/users/{user_id}",
    response_model=UserProfile,
    tags=["Internal"],
    summary="Retrieve payer contact info for payment and notification services",
)
def get_user_internal(user_id: str, db: Session = Depends(get_db)) -> UserProfile:
    """Internal API for payment-service and otp-service to fetch payer details for OTP/receipt."""
    return get_user_profile(db, user_id)


# ==============================================================================
# TASK 4: DEBIT AND REFUND (ATOMIC, CONDITIONAL & IDEMPOTENT)
# ==============================================================================

@app.post(
    "/internal/accounts/debit",
    response_model=DebitResponse,
    tags=["Internal"],
    summary="Conditional debit (balance >= amount), idempotent per txn_id",
)
@app.post(
    "/accounts/debit",
    response_model=DebitResponse,
    tags=["Internal"],
    summary="Conditional debit (alias)",
)
def debit_account_endpoint(body: DebitRequest, db: Session = Depends(get_db)) -> DebitResponse:
    """Task 4: Deduct money from payer account conditionally and atomically.

    - Condition: Only deducts if balance >= amount.
    - Idempotency: Each transaction_id is debited at most once.
    """
    return debit_user_account(db, body.user_id, body.amount, body.transaction_id)


@app.post(
    "/internal/accounts/credit",
    response_model=CreditResponse,
    tags=["Internal"],
    summary="Refund account balance (saga compensation), idempotent per txn_id",
)
@app.post(
    "/accounts/credit",
    response_model=CreditResponse,
    tags=["Internal"],
    summary="Refund account balance (alias)",
)
def credit_account_endpoint(body: CreditRequest, db: Session = Depends(get_db)) -> CreditResponse:
    """Task 4 Compensation: Refund money if a downstream step (like tuition commit) fails."""
    return credit_user_account(db, body.user_id, body.amount, body.transaction_id)


@app.post(
    "/internal/history",
    response_model=TransactionHistoryItem,
    tags=["Internal"],
    summary="Record completed transaction into user history",
)
def record_history_endpoint(
    body: RecordHistoryRequest,
    db: Session = Depends(get_db),
) -> TransactionHistoryItem:
    """Internal API for payment-service to record transaction outcomes in user history."""
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
