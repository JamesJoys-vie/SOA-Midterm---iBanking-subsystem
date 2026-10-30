"""Tables of payments_db: one row per payment attempt + the outbox of events still to publish.

Accounts / balances live in user-service and tuitions in tuition-service (database per service), so
payer_user_id and tuition_id are logical references (no FOREIGN KEY across databases).
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from shared.db import new_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TxnStatus(str, Enum):
    """PENDING_OTP -> PROCESSING -> SUCCESS, or FAILED / CANCELLED / EXPIRED (all four are final).
    """
    PENDING_OTP = "PENDING_OTP"  # created, tuition held, OTP emailed, waiting for the code
    PROCESSING = "PROCESSING"  # OTP accepted, money / tuition being updated
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


FINAL_STATUSES = (TxnStatus.SUCCESS, TxnStatus.FAILED, TxnStatus.CANCELLED, TxnStatus.EXPIRED)


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payer_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)  # from the JWT, never from the body
    student_id: Mapped[str] = mapped_column(String(20), nullable=False)  # MSSV, copied from tuition-service
    tuition_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)  # always the full tuition amount
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default=TxnStatus.PENDING_OTP.value)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # same key -> same transaction
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    debited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # money taken (needs a refund if we fail later)
    needs_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # refund failed, the job retries it
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # end of the OTP window
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutboxEvent(Base):
    """Transactional outbox: written in the same DB commit as SUCCESS, published to Redis Streams later.
    So the confirmation email is never lost even if Redis is down at that moment.
    """
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
