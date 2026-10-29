"""Table models owned by otp-service."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

class OtpStatus(str, enum.Enum):
    """Life cycle of an OTP. Only ACTIVE can be verified; every other status is final."""

    ACTIVE = "ACTIVE"  # issued, waiting for the user to enter it
    USED = "USED"  # verified successfully, can never be used again
    REVOKED = "REVOKED"  # replaced by a newer OTP for the same transaction
    EXPIRED = "EXPIRED"  # ran past expires_at before being used
    LOCKED = "LOCKED"  # too many wrong attempts

_ACTIVE = text("status = 'ACTIVE'")  # SQL condition for "live" rows, used by the partial unique indexes below.

class Otp(Base):
    """One code issued for one payment transaction."""

    __tablename__ = "otps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # Row id (UUID string).
    txn_id: Mapped[str] = mapped_column(String(64), index=True)  # Transaction this code confirms. Opaque id from payment-service (no foreign key).

    # HMAC of the code: the plain code is never stored, but equal codes give equal hashes, so the unique index below can stop two live OTPs sharing a code.
    code_hash: Mapped[str] = mapped_column(String(64))
    
    status: Mapped[str] = mapped_column(String(16), default=OtpStatus.ACTIVE.value)  # Current OtpStatus value.
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # Wrong codes entered so far.

    # All timestamps are naive UTC.
    created_at: Mapped[datetime] = mapped_column(DateTime)  # when it was issued
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # no longer valid from this moment
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # set once, on success

    __table_args__ = (
        # One live OTP per transaction.
        Index("uq_otps_active_txn", "txn_id", unique=True,
              postgresql_where=_ACTIVE, sqlite_where=_ACTIVE),
        # A live OTP never shares its code with another transaction's live OTP.
        Index("uq_otps_active_code", "code_hash", unique=True,
              postgresql_where=_ACTIVE, sqlite_where=_ACTIVE),
    )