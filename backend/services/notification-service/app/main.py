"""notification-service: internal API that sends iBanking emails (OTP codes, receipts).

Called by otp-service and payment-service, not exposed through the gateway.
Owns the `sent_emails` table in its own database and the only SMTP connection.
"""
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import db_is_up, get_db, init_db
from app.mailer import Mailer, MailerError, get_mailer
from app.schemas import EmailSentResponse, OtpEmailRequest, ReceiptEmailRequest
from app.service import send_otp_email, send_receipt_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("notification-service")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup: wait for the database and create tables before serving requests."""
    init_db()
    yield

app = FastAPI(title="notification-service", lifespan=lifespan)  # The ASGI app uvicorn runs (`uvicorn app.main:app`).

def require_internal_token(x_internal_token: str = Header(default="")) -> None:
    """Reject the request with 401 unless X-Internal-Token matches INTERNAL_API_TOKEN.

    compare_digest takes the same time for any input, so the token can't be guessed
    by timing.
    """
    if not hmac.compare_digest(x_internal_token, settings.internal_api_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")

@app.exception_handler(MailerError)
async def mailer_error_handler(_: Request, exc: MailerError) -> JSONResponse:
    """Mail server down or refusing: 503 so the caller knows it can retry later."""
    log.error("email not sent: %s", exc)
    return JSONResponse(status_code=503, content={
        "error": "EMAIL_UNAVAILABLE", "message": "The email could not be sent. Try again later."})

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

@app.post("/emails/otp", response_model=EmailSentResponse,
          dependencies=[Depends(require_internal_token)])
def otp_email(body: OtpEmailRequest, mailer: Mailer = Depends(get_mailer)) -> EmailSentResponse:
    """Send a verification code email."""
    send_otp_email(body, mailer)
    log.info("otp email sent mssv=%s", body.mssv)
    return EmailSentResponse(status="sent")

@app.post("/emails/receipt", response_model=EmailSentResponse,
          dependencies=[Depends(require_internal_token)])
def receipt_email(body: ReceiptEmailRequest, db: Session = Depends(get_db),
                  mailer: Mailer = Depends(get_mailer)) -> EmailSentResponse:
    """Send the success receipt of a transaction; a repeat call for the same txn_id sends nothing."""
    if send_receipt_email(db, body, mailer):
        log.info("receipt email sent txn_id=%s", body.txn_id)
        return EmailSentResponse(status="sent")
    log.info("receipt email already sent txn_id=%s", body.txn_id)
    return EmailSentResponse(status="already_sent")
