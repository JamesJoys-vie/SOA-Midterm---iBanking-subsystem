"""Các model cơ sở dữ liệu cho user-service.

Tuân thủ phân công công việc:
- Bảng users: lưu thông tin đăng nhập, họ tên, số điện thoại, email.
- Bảng accounts: lưu tài khoản ngân hàng, số dư khả dụng (balance >= 0) gắn với từng người dùng.
- Bảng transactions / ledger_entries: lưu vết giao dịch trừ tiền và lịch sử giao dịch (GET /history).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    """Tạo mã định danh duy nhất UUID dạng chuỗi."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Lấy thời gian hiện tại theo chuẩn UTC (naive datetime)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Bảng lưu trữ thông tin tài khoản người dùng đăng nhập hệ thống iBanking."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Quan hệ 1-1 với tài khoản ngân hàng
    account: Mapped["Account"] = relationship("Account", back_populates="user", uselist=False)


class Account(Base):
    """Bảng lưu trữ tài khoản tiền gửi và số dư của người dùng."""
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_account_balance_nonneg"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship("User", back_populates="account")


class TransactionHistory(Base):
    """Bảng lưu lịch sử giao dịch phục vụ cho endpoint GET /history."""
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


class DebitLedger(Base):
    """Bảng ghi nhận các lần trừ tiền để đảm bảo tính Idempotency: mỗi txn_id chỉ trừ đúng 1 lần."""
    __tablename__ = "debit_ledger"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_debit_ledger_txn"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
