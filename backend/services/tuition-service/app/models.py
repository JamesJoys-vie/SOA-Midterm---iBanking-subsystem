"""SQLAlchemy ORM models for tuition-service.

Implements Task 2 and Task 4 responsibilities:
- students table: MSSV (student_id) and student full_name
- tuitions table: tuition liability per term, amount, status (UNPAID -> RESERVED -> PAID)
- Concurrency controls:
  * Atomic conditional transitions (reserve, commit, release)
  * Unique constraint on (student_id, term) ensuring exactly one liability per term
  * Unique constraint on paid_by_txn ensuring a transaction pays only one tuition
  * Optimistic locking version field
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

# Tuition lifecycle status constants
UNPAID = "UNPAID"        # Available to be paid
RESERVED = "RESERVED"    # Locked by an active payment transaction
PAID = "PAID"            # Successfully paid


def new_id() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return naive current UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Student(Base):
    """Students table: maps student ID (MSSV) to student full name."""
    __tablename__ = "students"

    student_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # MSSV (e.g., 52100001, 521H0081)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    tuitions: Mapped[list["Tuition"]] = relationship("Tuition", back_populates="student")


class Tuition(Base):
    """Tuitions table: one liability per (student_id, term).

    Status moves:
      UNPAID --reserve--> RESERVED --commit (mark-paid)--> PAID
                               |
                               +--release / timeout--> UNPAID
    """
    __tablename__ = "tuitions"
    __table_args__ = (
        UniqueConstraint("student_id", "term", name="uq_tuition_student_term"),
        CheckConstraint("amount > 0", name="ck_tuition_amount_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False, index=True)
    term: Mapped[str] = mapped_column(String(20), nullable=False)  # Academic term (e.g., 2024-HK2, 2025-HK1)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)  # Full tuition amount (no partial payment)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default=UNPAID)  # UNPAID / RESERVED / PAID

    # Reservation hold fields (Task 2)
    reserved_by_txn: Mapped[str | None] = mapped_column(String(36), nullable=True)  # transaction_id holding the lock
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Lock expiration timestamp

    # Completed payment fields (Task 4)
    # unique=True ensures a transaction pays at most one tuition
    paid_by_txn: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)

    # Optimistic locking version
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    student: Mapped["Student"] = relationship("Student", back_populates="tuitions")
