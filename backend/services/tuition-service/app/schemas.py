"""Pydantic schemas (Data Transfer Objects) for tuition-service."""
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class TuitionInfo(BaseModel):
    """Tuition lookup response for students."""
    model_config = ConfigDict(from_attributes=True)

    tuition_id: str = Field(..., description="Unique tuition liability ID (UUID)")
    student_id: str = Field(..., description="Student ID (MSSV)")
    student_name: str = Field(..., description="Full name of the student")
    term: str = Field(..., description="Academic term (e.g. 2025-HK1)")
    amount: Decimal = Field(..., description="Total tuition amount (partial payment is not allowed)")
    status: str = Field(..., description="Current status: UNPAID, RESERVED, or PAID")


class ReserveRequest(BaseModel):
    """Request payload to reserve hold a tuition liability."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Transaction ID requesting hold")


class CommitRequest(BaseModel):
    """Request payload to mark-paid a reserved tuition liability."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Transaction ID that completed payment")


class ReleaseRequest(BaseModel):
    """Request payload to release hold on a tuition liability."""
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Transaction ID releasing the hold")


class CommitResponse(BaseModel):
    """Response returned upon successful mark-paid commit."""
    status: str = "PAID"
    message: str = "Tuition marked as paid successfully"


class ReleaseResponse(BaseModel):
    """Response returned upon hold release."""
    released: bool
    message: str
