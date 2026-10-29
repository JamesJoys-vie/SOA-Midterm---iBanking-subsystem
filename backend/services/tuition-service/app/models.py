"""Các model cơ sở dữ liệu cho tuition-service.

Tuân thủ phân công công việc của Task 2:
- Bảng students: lưu MSSV (student_id) và họ tên sinh viên.
- Bảng tuitions: lưu khoản phải nộp theo từng kỳ học, số tiền, và trạng thái giao dịch
  (UNPAID -> RESERVED -> PAID).
- Hỗ trợ khóa học phí nguyên tử và kiểm soát tranh chấp đồng thời (Optimistic Lock).
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

# Các hằng số trạng thái học phí
UNPAID = "UNPAID"        # Chưa thanh toán
RESERVED = "RESERVED"    # Đang được giữ khóa cho một giao dịch đang thanh toán
PAID = "PAID"            # Đã thanh toán thành công


def new_id() -> str:
    """Tạo mã UUID ngẫu nhiên."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Thời gian UTC hiện tại không kèm múi giờ (naive datetime)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Student(Base):
    """Bảng sinh viên: Lưu mã số sinh viên (MSSV) và họ tên."""
    __tablename__ = "students"

    student_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # MSSV (ví dụ: 52100001, 521H0081)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    tuitions: Mapped[list["Tuition"]] = relationship("Tuition", back_populates="student")


class Tuition(Base):
    """Bảng học phí: Mỗi dòng là một khoản công nợ của sinh viên theo kỳ học."""
    __tablename__ = "tuitions"
    __table_args__ = (
        UniqueConstraint("student_id", "term", name="uq_tuition_student_term"),
        CheckConstraint("amount > 0", name="ck_tuition_amount_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.student_id"), nullable=False, index=True)
    term: Mapped[str] = mapped_column(String(20), nullable=False)  # Kỳ học (ví dụ: 2024-HK2, 2025-HK1)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)  # Toàn bộ số tiền học phí
    status: Mapped[str] = mapped_column(String(15), nullable=False, default=UNPAID)  # UNPAID / RESERVED / PAID

    # Thông tin khóa giữ chỗ (Hold/Reserve)
    reserved_by_txn: Mapped[str | None] = mapped_column(String(36), nullable=True)  # Mã transaction_id đang giữ khóa
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Thời điểm hết hạn khóa

    # Thông tin khi đã thanh toán thành công
    # unique=True bảo đảm một giao dịch chỉ được liên kết thanh toán cho đúng một khoản học phí
    paid_by_txn: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)

    # Phiên bản dữ liệu phục vụ Optimistic Locking
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    student: Mapped["Student"] = relationship("Student", back_populates="tuitions")
