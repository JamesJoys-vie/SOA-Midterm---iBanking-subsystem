"""Request and response bodies of the HTTP API."""
from datetime import datetime
from pydantic import BaseModel, Field

class IssueOtpRequest(BaseModel):
    """Body of POST /otps."""
    txn_id: str = Field(min_length=1, max_length=64)  # transaction to issue a code for

class IssueOtpResponse(BaseModel):
    """Result of POST /otps. Never contains the code in production."""
    txn_id: str
    expires_at: datetime  # UTC moment the code stops working
    otp_expires_in: int  # seconds, used by the UI countdown
    code: str | None = None  # only when OTP_DEBUG_RETURN_CODE is on

class VerifyOtpRequest(BaseModel):
    """Body of POST /otps/verify."""
    txn_id: str = Field(min_length=1, max_length=64)  # transaction being confirmed
    code: str = Field(pattern=r"^\d+$", max_length=12)  # digits the user typed

class VerifyOtpResponse(BaseModel):
    """Result of a successful POST /otps/verify (failures use the error body instead)."""
    txn_id: str
    verified: bool  # always True here
    used_at: datetime  # UTC moment the code was consumed