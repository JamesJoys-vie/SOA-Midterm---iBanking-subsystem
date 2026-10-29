"""Request and response bodies of the HTTP API."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

class OtpEmailRequest(BaseModel):
    """Body of POST /emails/otp (sent by otp-service)."""
    to: EmailStr  # payer's email
    payer_name: str = Field(min_length=1, max_length=120)
    code: str = Field(pattern=r"^\d{4,12}$")  # plain code; used for this email only, never stored
    expires_in: int = Field(gt=0)  # seconds the code stays valid
    mssv: str = Field(min_length=1, max_length=20)  # what is being paid, so the payer can check it
    student_name: str = Field(min_length=1, max_length=120)
    amount: int = Field(gt=0)  # VND

class ReceiptEmailRequest(BaseModel):
    """Body of POST /emails/receipt (sent by payment-service after a successful payment)."""
    txn_id: str = Field(min_length=1, max_length=64)  # one receipt per transaction
    to: EmailStr
    payer_name: str = Field(min_length=1, max_length=120)
    mssv: str = Field(min_length=1, max_length=20)
    student_name: str = Field(min_length=1, max_length=120)
    term: str = Field(min_length=1, max_length=20)
    amount: int = Field(gt=0)  # VND
    balance_after: int = Field(ge=0)  # VND, payer's balance after the payment
    completed_at: datetime  # when the payment finished; without a timezone it is taken as UTC

class EmailSentResponse(BaseModel):
    """Result of both email endpoints."""
    status: Literal["sent", "already_sent"]  # already_sent = a retry of a receipt that went out before
