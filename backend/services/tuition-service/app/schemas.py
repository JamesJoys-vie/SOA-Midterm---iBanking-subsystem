"""Các Pydantic schemas (Data Transfer Objects) cho tuition-service."""
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class TuitionInfo(BaseModel):
    """Thông tin tra cứu học phí của sinh viên."""
    model_config = ConfigDict(from_attributes=True)

    tuition_id: str = Field(..., description="Mã định danh khoản học phí")
    student_id: str = Field(..., description="Mã số sinh viên (MSSV)")
    student_name: str = Field(..., description="Họ và tên sinh viên")
    term: str = Field(..., description="Học kỳ cần nộp học phí")
    amount: Decimal = Field(..., description="Toàn bộ số tiền học phí (không thanh toán một phần)")
    status: str = Field(..., description="Trạng thái: UNPAID (chưa nộp), RESERVED (đang giữ khóa), PAID (đã nộp)")


class ReserveRequest(BaseModel):
    """Yêu cầu khóa giữ chỗ học phí khi bắt đầu giao dịch thanh toán."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Mã giao dịch khởi tạo")


class CommitRequest(BaseModel):
    """Yêu cầu xác nhận hoàn tất thanh toán học phí (Mark-paid)."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Mã giao dịch đã thanh toán thành công")


class ReleaseRequest(BaseModel):
    """Yêu cầu giải phóng khóa học phí khi giao dịch bị hủy hoặc thất bại."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Mã giao dịch cần nhả khóa")


class CommitResponse(BaseModel):
    """Kết quả xác nhận mark-paid."""
    status: str = "PAID"
    message: str = "Học phí đã được đánh dấu thanh toán thành công"


class ReleaseResponse(BaseModel):
    """Kết quả giải phóng khóa học phí."""
    released: bool
    message: str
