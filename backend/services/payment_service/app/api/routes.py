"""Public endpoints of payment-service (reached through the gateway as /api/transactions/...).

Routes stay thin: read the request, call PaymentSaga, shape the response. Errors -> app/core/errors.py.
"""
from fastapi import APIRouter, Depends, Header
from app.api.deps import current_user_id, get_saga
from app.domain.models import TxnStatus
from app.domain.payment_saga import PaymentSaga
from app.schemas.transaction import (InitiateTransactionRequest, ResendOtpResult, TransactionOut, TransactionResult,
                                     VerifyOtpRequest)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("", response_model=TransactionOut, status_code=201,
             responses={400: {}, 404: {}, 409: {}, 422: {"description": "Insufficient balance"}, 502: {}})
def initiate(body: InitiateTransactionRequest, idempotency_key: str = Header(..., alias="Idempotency-Key"),
             user_id: str = Depends(current_user_id), saga: PaymentSaga = Depends(get_saga)):
    """Start paying a student's tuition: checks, tuition hold, OTP email. Status PENDING_OTP.
    """
    return TransactionOut.from_model(saga.initiate(user_id, body.student_id, idempotency_key))


@router.get("", response_model=list[TransactionOut])
def history(user_id: str = Depends(current_user_id), saga: PaymentSaga = Depends(get_saga)):
    """The caller's transactions, newest first (max 100)."""
    return [TransactionOut.from_model(t) for t in saga.history(user_id)]


@router.get("/{transaction_id}", response_model=TransactionOut, responses={404: {}})
def get_transaction(transaction_id: str, user_id: str = Depends(current_user_id),
                    saga: PaymentSaga = Depends(get_saga)):
    return TransactionOut.from_model(saga.get(user_id, transaction_id))


@router.post("/{transaction_id}/verify-otp", response_model=TransactionResult,
             responses={400: {"description": "Wrong / expired / locked OTP"}, 404: {}, 409: {}, 410: {}, 502: {}})
def verify_otp(transaction_id: str, body: VerifyOtpRequest, user_id: str = Depends(current_user_id),
               saga: PaymentSaga = Depends(get_saga)):
    """Confirm with the OTP; returns SUCCESS, FAILED (see failure_reason) or PROCESSING (poll GET).
    """
    txn = saga.confirm(user_id, transaction_id, body.otp)
    debited = txn.status in (TxnStatus.SUCCESS.value, TxnStatus.PROCESSING.value) and txn.balance_after is not None
    balance = txn.balance_after if debited else saga.current_balance(user_id)
    return TransactionResult(transaction=TransactionOut.from_model(txn), balance_after=balance)


@router.post("/{transaction_id}/resend-otp", response_model=ResendOtpResult,
             responses={404: {}, 409: {}, 410: {}, 429: {}, 502: {}})
def resend_otp(transaction_id: str, user_id: str = Depends(current_user_id), saga: PaymentSaga = Depends(get_saga)):
    return ResendOtpResult(otp_expires_in=saga.resend_otp(user_id, transaction_id))


@router.post("/{transaction_id}/cancel", response_model=TransactionOut, responses={404: {}, 409: {}})
def cancel(transaction_id: str, user_id: str = Depends(current_user_id), saga: PaymentSaga = Depends(get_saga)):
    return TransactionOut.from_model(saga.cancel(user_id, transaction_id))
