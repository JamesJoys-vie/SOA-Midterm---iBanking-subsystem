"""Table models owned by notification-service."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

class SentEmail(Base):
    """One email that must go out at most once (e.g. the receipt of a transaction).

    OTP emails are not recorded here: they can be resent, and the code must not be stored.
    """

    __tablename__ = "sent_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # Row id (UUID string).
    kind: Mapped[str] = mapped_column(String(32))  # Email type, e.g. "receipt".
    ref_id: Mapped[str] = mapped_column(String(64))  # What it is about, e.g. the txn_id from payment-service (no foreign key).
    recipient: Mapped[str] = mapped_column(String(320))  # Address it was sent to.
    sent_at: Mapped[datetime] = mapped_column(DateTime)  # Naive UTC.

    __table_args__ = (
        # The same email is never sent twice for the same thing, even on retries.
        UniqueConstraint("kind", "ref_id", name="uq_sent_emails_kind_ref"),
    )
