"""Email rules: what each email says and when it may be sent."""
import math
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.mailer import Mailer
from app.models import SentEmail
from app.rendering import render
from app.schemas import OtpEmailRequest, ReceiptEmailRequest

RECEIPT = "receipt"  # SentEmail.kind for receipts
VN_TZ = timezone(timedelta(hours=7), "UTC+7")  # Times in emails are shown in Vietnam time.

def utcnow() -> datetime:
    """Current time as naive UTC, the format every timestamp column uses."""
    return datetime.now(UTC).replace(tzinfo=None)

def to_vn_time(moment: datetime) -> str:
    """Format a moment as Vietnam time, e.g. "09/10/2026 14:32 (UTC+7)". Naive = UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M (UTC+7)")

def send_otp_email(req: OtpEmailRequest, mailer: Mailer) -> None:
    """Email the verification code. Not recorded anywhere, so resends just send again."""
    text, html = render(
        "otp",
        payer_name=req.payer_name,
        code=req.code,
        expires_in_minutes=math.ceil(req.expires_in / 60),
        mssv=req.mssv,
        student_name=req.student_name,
        amount=req.amount,
    )
    # Code stays out of the subject so it doesn't show in lock-screen notifications.
    mailer.send(req.to, "iBanking: your verification code", text, html)

def send_receipt_email(db: Session, req: ReceiptEmailRequest, mailer: Mailer) -> bool:
    """Email the payment receipt once per transaction. Returns False if it was already sent.

    Claims the (receipt, txn_id) row first; the unique constraint makes a retry or a
    parallel call lose that claim instead of sending a second email. If sending fails
    the claim is removed, so the caller can retry.
    """
    claim = SentEmail(kind=RECEIPT, ref_id=req.txn_id, recipient=req.to, sent_at=utcnow())
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False

    text, html = render(
        "receipt",
        payer_name=req.payer_name,
        txn_id=req.txn_id,
        mssv=req.mssv,
        student_name=req.student_name,
        term=req.term,
        amount=req.amount,
        balance_after=req.balance_after,
        completed_at=to_vn_time(req.completed_at),
    )
    try:
        mailer.send(req.to, "iBanking: tuition payment successful", text, html)
    except Exception:
        db.execute(delete(SentEmail).where(SentEmail.id == claim.id))
        db.commit()
        raise
    return True
