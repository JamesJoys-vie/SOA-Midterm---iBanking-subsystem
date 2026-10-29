"""Các Pydantic schema (Data Transfer Objects) cho user-service."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ==============================================================================
# 1. SCHEMAS CHO ĐĂNG NHẬP VÀ XÁC THỰC
# ==============================================================================

class LoginRequest(BaseModel):
    """Dữ liệu client gửi lên để đăng nhập."""
    username: str = Field(..., min_length=3, max_length=50, description="Tên đăng nhập")
    password: str = Field(..., min_length=6, description="Mật khẩu tài khoản")


class TokenResponse(BaseModel):
    """Kết quả trả về sau khi đăng nhập thành công."""
    access_token: str = Field(..., description="Mã JWT Bearer Token")
    token_type: str = Field("bearer", description="Loại token")
    expires_in: int = Field(..., description="Thời gian token còn hiệu lực (tính theo giây)")


# ==============================================================================
# 2. SCHEMAS CHO THÔNG TIN NGƯỜI DÙNG & TÀI KHOẢN (GET /me)
# ==============================================================================

class UserProfile(BaseModel):
    """Thông tin chi tiết người dùng và số dư tài khoản khả dụng."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID của người dùng")
    username: str = Field(..., description="Tên đăng nhập")
    full_name: str = Field(..., description="Họ và tên người dùng")
    phone: str = Field(..., description="Số điện thoại")
    email: EmailStr = Field(..., description="Địa chỉ email nhận thông báo và OTP")
    balance: Decimal = Field(default=Decimal("0.00"), description="Số dư khả dụng trong tài khoản (VND)")


class AccountBalanceResponse(BaseModel):
    """Số dư tài khoản (GET /accounts/me)."""
    balance: Decimal = Field(..., description="Số dư hiện tại")


# ==============================================================================
# 3. SCHEMAS CHO TRỪ TIỀN (DEBIT) VÀ LỊCH SỬ GIAO DỊCH
# ==============================================================================

class DebitRequest(BaseModel):
    """Yêu cầu trừ tiền tài khoản từ hệ thống thanh toán."""
    user_id: str = Field(..., description="UUID của người dùng cần trừ tiền")
    amount: Decimal = Field(..., gt=0, description="Số tiền cần trừ (phải > 0)")
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Mã giao dịch duy nhất")


class DebitResponse(BaseModel):
    """Kết quả thực hiện trừ tiền."""
    success: bool
    transaction_id: str
    balance_after: Decimal
    message: str = "Trừ tiền thành công"


class TransactionHistoryItem(BaseModel):
    """Thông tin một dòng giao dịch trong lịch sử."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    amount: Decimal
    status: str
    failure_reason: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class RecordHistoryRequest(BaseModel):
    """Request ghi nhận lịch sử giao dịch từ payment-service."""
    user_id: str
    student_id: str
    tuition_id: Optional[str] = None
    amount: Decimal
    status: str = "SUCCESS"
    failure_reason: Optional[str] = None
