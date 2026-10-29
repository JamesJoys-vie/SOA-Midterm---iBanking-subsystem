"""otp-service: internal API called by payment-service (not exposed through the gateway).

Owns the `otps` table in its own database.
Knows nothing about payments, users or tuition: `txn_id` is an opaque id that belongs to payment-service.
Emails codes through notification-service; it never talks to a mail server itself.
"""
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_is_up, get_db, init_db
from app.notifier import Notifier, OtpEmail, get_notifier
from app.schemas import IssueOtpRequest, IssueOtpResponse, VerifyOtpRequest, VerifyOtpResponse
from app.service import OtpError, send_otp, verify_otp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("otp-service")

# HTTP status per OtpError code; every other OtpError is a 400.
_STATUS = {
    "OTP_NOT_FOUND": 404,
    "OTP_RESEND_TOO_SOON": 429,
    "OTP_RESEND_LIMIT": 429,
    "EMAIL_UNAVAILABLE": 503,
}

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup: wait for the database and create tables before serving requests."""
    init_db()
    yield

app = FastAPI(title="otp-service", lifespan=lifespan)  # The ASGI app uvicorn runs (`uvicorn app.main:app`).

def require_internal_token(x_internal_token: str = Header(default="")) -> None:
    """Reject the request with 401 unless X-Internal-Token matches INTERNAL_API_TOKEN.

    compare_digest takes the same time for any input, so the token can't be guessed
    by timing.
    """
    if not hmac.compare_digest(x_internal_token, settings.internal_api_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")

@app.exception_handler(OtpError)
async def otp_error_handler(_: Request, exc: OtpError) -> JSONResponse:
    """Turn an OtpError into the JSON error body {error, message, attempts_left?, retry_after?}."""
    body = {"error": exc.code, "message": exc.message}
    headers = {}
    if exc.attempts_left is not None:
        body["attempts_left"] = exc.attempts_left
    if exc.retry_after is not None:
        body["retry_after"] = exc.retry_after
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(status_code=_STATUS.get(exc.code, 400), content=body, headers=headers)

@app.get("/health")
def health() -> dict:
    """Liveness: the process is up."""
    return {"status": "ok"}

@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: the process can reach its database."""
    if db_is_up():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "database unavailable"}, status_code=503)

@app.post("/otps", response_model=IssueOtpResponse, status_code=201,
          dependencies=[Depends(require_internal_token)])
def create_otp(body: IssueOtpRequest, db: Session = Depends(get_db),
               notifier: Notifier = Depends(get_notifier)) -> IssueOtpResponse:
    """Issue a new OTP for a transaction (replaces any earlier one) and email it.

    Used for the first code and for "Resend code"; the cooldown and send limit apply to both.
    """
    email = OtpEmail(to=body.email, payer_name=body.payer_name, mssv=body.mssv,
                     student_name=body.student_name, amount=body.amount)
    try:
        sent = send_otp(db, body.txn_id, email, settings, notifier)
    except OtpError as exc:
        log.info("otp not issued txn_id=%s reason=%s", body.txn_id, exc.code)
        raise
    log.info("otp issued txn_id=%s expires_at=%s", body.txn_id, sent.otp.expires_at)
    return IssueOtpResponse(
        txn_id=sent.otp.txn_id,
        expires_at=sent.otp.expires_at.replace(tzinfo=UTC),
        otp_expires_in=settings.otp_ttl_seconds,
        sent_to=sent.sent_to,
        resend_available_in=settings.otp_resend_cooldown_seconds,
        sends_left=sent.sends_left,
    )

@app.post("/otps/verify", response_model=VerifyOtpResponse,
          dependencies=[Depends(require_internal_token)])
def verify(body: VerifyOtpRequest, db: Session = Depends(get_db)) -> VerifyOtpResponse:
    """Check the code for a transaction; 200 if accepted, error body if not."""
    try:
        otp = verify_otp(db, body.txn_id, body.code, settings)
    except OtpError as exc:
        log.info("otp rejected txn_id=%s reason=%s", body.txn_id, exc.code)
        raise
    log.info("otp verified txn_id=%s", body.txn_id)
    return VerifyOtpResponse(txn_id=otp.txn_id, verified=True, used_at=otp.used_at.replace(tzinfo=UTC))