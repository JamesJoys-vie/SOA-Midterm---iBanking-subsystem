"""Request / response models of the public API (same fields as docs/api/openapi/payment-service.json)."""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from app.domain.models import Transaction, TxnStatus, utcnow


class InitiateTransactionRequest(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=20, description="MSSV to pay for")
    term: str | None = None  # accepted but ignored: the oldest unpaid term is paid
    # No payer / amount fields on purpose: payer comes from the JWT, amount from tuition-service.


class VerifyOtpRequest(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6)


class TransactionOut(BaseModel):
    id: str
    student_id: str
    amount: Decimal
    status: str
    failure_reason: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    otp_expires_in: int | None = None  # seconds left, only while PENDING_OTP

    @classmethod
    def from_model(cls, txn: Transaction) -> "TransactionOut":
        left = None
        if txn.status == TxnStatus.PENDING_OTP.value and txn.expires_at:
            left = max(int((txn.expires_at - utcnow()).total_seconds()), 0)
        return cls(id=txn.id, student_id=txn.student_id, amount=txn.amount, status=txn.status,
                   failure_reason=txn.failure_reason, created_at=txn.created_at, completed_at=txn.completed_at,
                   otp_expires_in=left)


class TransactionResult(BaseModel):
    transaction: TransactionOut
    balance_after: Decimal | None = None


class ResendOtpResult(BaseModel):
    otp_expires_in: int
