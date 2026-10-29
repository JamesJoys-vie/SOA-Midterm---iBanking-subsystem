import secrets
from functools import lru_cache
from fastapi import APIRouter, HTTPException
from shared import events
from shared.redis_client import get_redis
from app.core.config import settings
from app.repositories.otp_store import OtpStore, VerifyResult
from app.schemas.otp import IssueOtpRequest, IssueOtpResponse, VerifyOtpRequest, VerifyOtpResponse

router = APIRouter()
test_router = APIRouter()  # mounted only when OTP_TEST_ECHO=true (see app/main.py)
MAX_GENERATION_TRIES = 20
TEST_ECHO_PREFIX = "otp:test:"


@lru_cache
def store() -> OtpStore:
    return OtpStore(get_redis(settings.redis_url), settings.otp_ttl_seconds, settings.otp_max_attempts)


@router.post("/internal/otp", response_model=IssueOtpResponse, status_code=201,
             responses={429: {"description": "Resend too soon / too many OTPs for this transaction"}})
def issue(body: IssueOtpRequest):
    """New 6-digit OTP for the transaction (replaces any previous one), then `otp.requested` is published on
    Redis Streams and notification-service emails it. The code is unique among ACTIVE OTPs (regenerated on collision)."""
    s = store()
    wait = s.acquire_issue_slot(body.transaction_id, settings.otp_max_issues, settings.otp_resend_cooldown_seconds,
                                window_s=settings.otp_ttl_seconds * settings.otp_max_issues)
    if wait:
        raise HTTPException(429, "Please wait before requesting another OTP", headers={"Retry-After": str(wait)})
    for _ in range(MAX_GENERATION_TRIES):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if s.save(body.transaction_id, code):
            break
    else:  # practically unreachable unless ~10^6 OTPs are active at once
        raise HTTPException(503, "Could not allocate a unique OTP, try again")
    if settings.otp_test_echo:
        s.r.set(f"{TEST_ECHO_PREFIX}{body.transaction_id}", code, ex=settings.otp_ttl_seconds)
    events.publish(s.r, events.OTP_REQUESTED, {"email": body.email, "full_name": body.full_name, "otp": code,
                                               "transaction_id": body.transaction_id,
                                               "expires_in": settings.otp_ttl_seconds})
    return IssueOtpResponse(expires_in=settings.otp_ttl_seconds)


@router.post("/internal/otp/verify", response_model=VerifyOtpResponse)
def verify(body: VerifyOtpRequest):
    """Atomic compare-and-delete: a correct code works exactly once; wrong codes burn the OTP after N attempts."""
    s = store()
    result = s.verify_and_consume(body.transaction_id, body.otp)
    if result is VerifyResult.OK:
        return VerifyOtpResponse(valid=True)
    left = s.attempts_left(body.transaction_id) if result is VerifyResult.INVALID else 0
    return VerifyOtpResponse(valid=False, reason=result.value, attempts_left=left)


@test_router.get("/internal/test/otp/{transaction_id}", include_in_schema=False)
def latest_code(transaction_id: str):
    """LOAD TESTS ONLY: the latest plain code issued for the transaction (what the email would contain)."""
    code = store().r.get(f"{TEST_ECHO_PREFIX}{transaction_id}")
    if code is None:
        raise HTTPException(404, "No OTP issued for this transaction")
    return {"otp": code}
