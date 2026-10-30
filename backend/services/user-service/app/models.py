"""SQLAlchemy ORM models for user-service.

Responsibilities assigned to Hieu:
- Task 1:
  * users table: username, bcrypt password_hash, full_name, phone, email
  * accounts table: balance (CHECK balance >= 0), version (optimistic locking)
  * GET /me: profile and available balance
  * transactions table: transaction history (GET /history)
- Task 4:
  * Conditional debit (balance >= amount)
  * Idempotent debit and credit (refund): ledger_entries ensures each txn_id is debited/credited at most once
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return naive current UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Users table: stores login credentials and profile details."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # 1-to-1 relationship with Account
    account: Mapped["Account"] = relationship("Account", back_populates="user", uselist=False)


class Account(Base):
    """Accounts table: stores bank account balance for each payer.

    The check constraint (balance >= 0) is the last line of defense against overdraft.
    """
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_account_balance_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship("User", back_populates="account")


class LedgerEntry(Base):
    """Ledger table: tracks all balance debit and credit (refund) movements.

    Enforces Idempotency:
    - At most ONE DEBIT and ONE CREDIT per transaction_id.
    - Prevents double charging or duplicate refunds.
    """
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("transaction_id", "type", name="uq_ledger_txn_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'DEBIT' or 'CREDIT'
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# Backward-compatible alias for existing tests
DebitLedger = LedgerEntry


class TransactionHistory(Base):
    """Transactions history table: stores payment transaction records for GET /history."""
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    payer_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(20), nullable=False)
    tuition_id: Mapped[str] = mapped_column(String(36), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
