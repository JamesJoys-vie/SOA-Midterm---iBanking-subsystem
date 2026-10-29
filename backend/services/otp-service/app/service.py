"""OTP rules: issue, send and verify.

Concurrency is handled by the database, not by Python locks:
- partial unique indexes keep one live OTP per transaction and no shared live codes;
- issuing revokes the previous OTP with a conditional UPDATE, so two parallel resends
  can't both pass the cooldown;
- verify consumes the OTP with one conditional UPDATE, so only one caller can win.
"""
import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Otp, OtpStatus
from app.notifier import Notifier, NotifierError, OtpEmail

# Shorthand for the status string used in most queries.
ACTIVE = OtpStatus.ACTIVE.value
# How many fresh codes to try when a new code clashes with a live one.
_ISSUE_RETRIES = 5

def utcnow() -> datetime:
    """Current time as naive UTC, the format every timestamp column uses."""
    return datetime.now(UTC).replace(tzinfo=None)

def hash_code(code: str, secret: str) -> str:
    """HMAC-SHA256 of a code. Same code + same secret always give the same hash."""
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()

def generate_code(length: int) -> str:
    """Random numeric code from a cryptographically secure source."""
    return "".join(secrets.choice("0123456789") for _ in range(length))

def mask_email(email: str) -> str:
    """Hide most of an address for display, e.g. alice@example.com -> a****@example.com."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}****@{domain}"

class OtpError(Exception):
    """Issuing or verifying failed. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str, attempts_left: int | None = None,
                 retry_after: int | None = None):
        super().__init__(message)
        self.code = code  # e.g. OTP_INVALID, OTP_EXPIRED; callers branch on this
        self.message = message  # human-readable text the UI can show
        self.attempts_left = attempts_left  # only set for wrong-code / locked errors
        self.retry_after = retry_after  # only set when resending too soon: seconds to wait

@dataclass
class IssuedOtp:
    """Result of issue_otp: the stored row plus the plain code to deliver."""

    otp: Otp
    code: str  # plain code, only kept in memory for delivery

def _expire_stale(db: Session, now: datetime) -> None:
    """Mark every ACTIVE OTP past its expiry as EXPIRED.

    Frees their codes so they don't block the unique index for new OTPs.
    """
    db.execute(
        update(Otp)
        .where(Otp.status == ACTIVE, Otp.expires_at <= now)
        .values(status=OtpStatus.EXPIRED.value)
    )

def _too_soon(retry_after: float) -> OtpError:
    """Error for a resend inside the cooldown."""
    wait = max(math.ceil(retry_after), 1)
    return OtpError("OTP_RESEND_TOO_SOON", f"Please wait {wait} seconds before requesting a new code.",
                    retry_after=wait)

def issue_otp(db: Session, txn_id: str, settings: Settings, now: datetime | None = None) -> IssuedOtp:
    """Create a new OTP for `txn_id`, revoking any earlier live one for it.

    Steps: expire stale OTPs, check the resend cooldown and send limit, revoke this
    transaction's live OTP, insert the new one. If the database rejects the insert
    (code clash, or a parallel request won), start over with a fresh code.
    `now` can be passed in by tests to control the clock.
    """
    now = now or utcnow()
    cooldown = timedelta(seconds=settings.otp_resend_cooldown_seconds)
    for _ in range(_ISSUE_RETRIES):
        code = generate_code(settings.otp_length)
        try:
            _expire_stale(db, now)
            latest = db.scalars(
                select(Otp).where(Otp.txn_id == txn_id).order_by(Otp.created_at.desc())
            ).first()
            if latest is not None and now - latest.created_at < cooldown:
                raise _too_soon((latest.created_at + cooldown - now).total_seconds())
            sends = db.scalar(select(func.count()).select_from(Otp).where(Otp.txn_id == txn_id))
            if sends >= settings.otp_max_sends:
                raise OtpError("OTP_RESEND_LIMIT",
                               "Too many codes requested for this payment. Start a new payment.")
            if latest is not None and latest.status == ACTIVE:
                revoked = db.execute(
                    update(Otp)
                    .where(Otp.id == latest.id, Otp.status == ACTIVE)
                    .values(status=OtpStatus.REVOKED.value)
                )
                if revoked.rowcount == 0:
                    # A parallel request changed it first (e.g. a second resend click).
                    raise _too_soon(settings.otp_resend_cooldown_seconds)
            otp = Otp(
                txn_id=txn_id,
                code_hash=hash_code(code, settings.otp_secret),
                status=ACTIVE,
                attempts=0,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            )
            db.add(otp)
            db.commit()
            return IssuedOtp(otp=otp, code=code)
        except IntegrityError:
            # Code collided with another live OTP, or a concurrent issue for the same transaction won. Start over with a fresh code.
            db.rollback()
        except OtpError:
            db.rollback()
            raise
    raise RuntimeError("could not issue a unique OTP")

@dataclass
class SentOtp:
    """Result of send_otp: what the caller can show the user."""
    otp: Otp
    sent_to: str  # masked address, e.g. a****@example.com
    sends_left: int  # resends still allowed for this transaction

def send_otp(db: Session, txn_id: str, email: OtpEmail, settings: Settings,
             notifier: Notifier, now: datetime | None = None) -> SentOtp:
    """Issue an OTP and email it through notification-service.

    `email` carries everything except the code, which is filled in here. If the email
    can't be sent the new OTP is deleted, so no code exists that nobody received, and
    the failed try doesn't count towards the cooldown or the send limit.
    """
    issued = issue_otp(db, txn_id, settings, now)
    email.code = issued.code
    email.expires_in = settings.otp_ttl_seconds
    try:
        notifier.send_otp_email(email)
    except NotifierError:
        db.execute(delete(Otp).where(Otp.id == issued.otp.id))
        db.commit()
        raise OtpError("EMAIL_UNAVAILABLE", "The verification code could not be emailed. Try again later.")
    sends = db.scalar(select(func.count()).select_from(Otp).where(Otp.txn_id == txn_id))
    return SentOtp(otp=issued.otp, sent_to=mask_email(email.to),
                   sends_left=max(settings.otp_max_sends - sends, 0))

def verify_otp(db: Session, txn_id: str, code: str, settings: Settings,
               now: datetime | None = None) -> Otp:
    """Consume the live OTP of `txn_id` if `code` matches. Raises OtpError otherwise.

    Success is one conditional UPDATE (right code, still ACTIVE, not expired, under
    the attempt limit), so two parallel requests can't both succeed. On failure it
    looks at the latest OTP to report why, and counts a wrong attempt if needed.
    `now` can be passed in by tests to control the clock.
    """
    now = now or utcnow()
    max_attempts = settings.otp_max_attempts

    consumed = db.execute(
        update(Otp)
        .where(
            Otp.txn_id == txn_id,
            Otp.status == ACTIVE,
            Otp.code_hash == hash_code(code, settings.otp_secret),
            Otp.expires_at > now,
            Otp.attempts < max_attempts,
        )
        .values(status=OtpStatus.USED.value, used_at=now)
    )
    if consumed.rowcount == 1:
        db.commit()
        return db.scalars(
            select(Otp).where(Otp.txn_id == txn_id, Otp.status == OtpStatus.USED.value)
            .order_by(Otp.used_at.desc())
        ).first()

    # Not consumed: work out why, so the UI can say something useful.
    otp = db.scalars(
        select(Otp).where(Otp.txn_id == txn_id).order_by(Otp.created_at.desc())
    ).first()
    if otp is None:
        db.rollback()
        raise OtpError("OTP_NOT_FOUND", "No verification code was issued for this transaction.")

    if otp.status == OtpStatus.USED.value:
        db.rollback()
        raise OtpError("OTP_ALREADY_USED", "This verification code has already been used.")
    if otp.status == OtpStatus.LOCKED.value:
        db.rollback()
        raise OtpError("OTP_LOCKED", "Too many incorrect attempts. Request a new code.", 0)
    if otp.status in (OtpStatus.EXPIRED.value, OtpStatus.REVOKED.value) or otp.expires_at <= now:
        if otp.status == ACTIVE:
            otp.status = OtpStatus.EXPIRED.value
        db.commit()
        raise OtpError("OTP_EXPIRED", "The verification code has expired. Request a new code.")

    # Wrong code on a live OTP: count the attempt atomically and lock at the limit.
    db.execute(
        update(Otp)
        .where(Otp.id == otp.id, Otp.status == ACTIVE)
        .values(attempts=Otp.attempts + 1)
    )
    db.execute(
        update(Otp)
        .where(Otp.id == otp.id, Otp.status == ACTIVE, Otp.attempts >= max_attempts)
        .values(status=OtpStatus.LOCKED.value)
    )
    db.commit()
    db.refresh(otp)
    attempts_left = max(max_attempts - otp.attempts, 0)
    if otp.status == OtpStatus.LOCKED.value:
        raise OtpError("OTP_LOCKED", "Too many incorrect attempts. Request a new code.", 0)
    raise OtpError("OTP_INVALID", f"Incorrect code. {attempts_left} attempts left.", attempts_left)