"""OTP rules: issue and verify.

Concurrency is handled by the database, not by Python locks:
- partial unique indexes keep one live OTP per transaction and no shared live codes;
- verify consumes the OTP with one conditional UPDATE, so only one caller can win.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Otp, OtpStatus

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

class OtpError(Exception):
    """Verification failed. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str, attempts_left: int | None = None):
        super().__init__(message)
        self.code = code  # e.g. OTP_INVALID, OTP_EXPIRED; callers branch on this
        self.message = message  # human-readable text the UI can show
        self.attempts_left = attempts_left  # only set for wrong-code / locked errors

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

def issue_otp(db: Session, txn_id: str, settings: Settings, now: datetime | None = None) -> IssuedOtp:
    """Create a new OTP for `txn_id`, revoking any earlier live one for it.

    Steps: expire stale OTPs, revoke this transaction's live OTP, insert the new
    one. If the database rejects it (code clash), retry with a fresh code.
    `now` can be passed in by tests to control the clock.
    """
    now = now or utcnow()
    for _ in range(_ISSUE_RETRIES):
        code = generate_code(settings.otp_length)
        try:
            _expire_stale(db, now)
            db.execute(
                update(Otp)
                .where(Otp.txn_id == txn_id, Otp.status == ACTIVE)
                .values(status=OtpStatus.REVOKED.value)
            )
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
    raise RuntimeError("could not issue a unique OTP")

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