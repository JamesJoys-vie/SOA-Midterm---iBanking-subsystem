"""Request and response bodies of the HTTP API."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class IssueOtpRequest(BaseModel):
    """Body of POST /otps (first code and every resend).

    payment-service passes the payer and tuition details for the email, so otp-service
    never has to look them up in another service.
    """
    txn_id: str = Field(min_length=1, max_length=64)  # transaction to issue a code for
    email: EmailStr  # payer's email; the code is sent here
    payer_name: str = Field(min_length=1, max_length=120)
    mssv: str = Field(min_length=1, max_length=20)  # what is being paid, shown in the email
    student_name: str = Field(min_length=1, max_length=120)
    amount: int = Field(gt=0)  # VND

class IssueOtpResponse(BaseModel):
    """Result of POST /otps. Never contains the code."""
    txn_id: str
    expires_at: datetime  # UTC moment the code stops working
    otp_expires_in: int  # seconds, used by the UI countdown
    sent_to: str  # masked address for "We sent a code to a****@example.com"
    resend_available_in: int  # seconds until "Resend code" may be pressed
    sends_left: int  # resends still allowed for this transaction

class VerifyOtpRequest(BaseModel):
    """Body of POST /otps/verify."""
    txn_id: str = Field(min_length=1, max_length=64)  # transaction being confirmed
    code: str = Field(pattern=r"^\d+$", max_length=12)  # digits the user typed

class VerifyOtpResponse(BaseModel):
    """Result of a successful POST /otps/verify (failures use the error body instead)."""
    txn_id: str
    verified: bool  # always True here
    used_at: datetime  # UTC moment the code was consumed
