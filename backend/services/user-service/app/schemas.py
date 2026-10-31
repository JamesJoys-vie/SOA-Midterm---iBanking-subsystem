"""Pydantic schemas (Data Transfer Objects) for user-service."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ==============================================================================
# 1. AUTHENTICATION & LOGIN SCHEMAS (Task 1)
# ==============================================================================

class LoginRequest(BaseModel):
    """Payload for user login."""
    username: str = Field(..., min_length=3, max_length=50, description="Login username")
    password: str = Field(..., min_length=6, description="Account password")


class TokenResponse(BaseModel):
    """Response returned upon successful authentication."""
    access_token: str = Field(..., description="JWT Bearer token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(..., description="Token TTL in seconds")


# ==============================================================================
# 2. USER PROFILE & BALANCE SCHEMAS (Task 1 & Task 2)
# ==============================================================================

class UserProfile(BaseModel):
    """User profile information with available balance (GET /me)."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="User unique identifier (UUID)")
    username: str = Field(..., description="Username")
    full_name: str = Field(..., description="Full name of the payer")
    phone: str = Field(..., description="Phone number")
    email: EmailStr = Field(..., description="Email address for notifications and OTP")
    balance: Decimal = Field(default=Decimal("0.00"), description="Available account balance in VND")


class AccountBalanceResponse(BaseModel):
    """Account balance response (GET /accounts/me)."""
    balance: Decimal = Field(..., description="Current available balance in VND")


# ==============================================================================
# 3. TASK 4: DEBIT, CREDIT (REFUND) & TRANSACTION HISTORY SCHEMAS
# ==============================================================================

class DebitRequest(BaseModel):
    """Internal debit request from payment-service."""
    user_id: str = Field(..., description="Payer UUID")
    amount: Decimal = Field(..., gt=0, description="Amount to deduct (must be > 0)")
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Unique transaction ID")


class DebitResponse(BaseModel):
    """Response returned after account debit."""
    success: bool
    transaction_id: str
    balance_after: Decimal
    message: str = "Account debited successfully"


class CreditRequest(BaseModel):
    """Internal refund/credit request (compensation in saga)."""
    user_id: str = Field(..., description="Payer UUID")
    amount: Decimal = Field(..., gt=0, description="Amount to refund (must be > 0)")
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Unique transaction ID")


class CreditResponse(BaseModel):
    """Response returned after account refund/credit."""
    success: bool
    transaction_id: str
    balance_after: Decimal
    message: str = "Account refunded successfully"


class TransactionHistoryItem(BaseModel):
    """Transaction item displayed in transaction history."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    amount: Decimal
    status: str
    failure_reason: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class RecordHistoryRequest(BaseModel):
    """Internal request to record transaction outcome in history."""
    user_id: str
    student_id: str
    tuition_id: Optional[str] = None
    amount: Decimal
    status: str = "SUCCESS"
    failure_reason: Optional[str] = None
