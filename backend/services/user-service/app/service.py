"""Business Service Layer for user-service.

Implements Task 1 and Task 4:
- Task 1:
  * User authentication with bcrypt and JWT token issue.
  * Retrieve user profile with available balance (GET /me).
  * Transaction history retrieval (GET /history).
- Task 4:
  * Conditional atomic balance deduction (balance >= amount).
  * Idempotency guarantee: each transaction_id is debited at most once.
  * Saga compensation: credit/refund endpoint for rollbacks.
"""
import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, LedgerEntry, TransactionHistory, User, utcnow
from app.schemas import (
    CreditResponse,
    DebitResponse,
    TokenResponse,
    TransactionHistoryItem,
    UserProfile,
)
from app.security import _DUMMY_HASH, create_access_token, verify_password

log = logging.getLogger("user-service.service")


def authenticate_user(db: Session, username: str, password: str) -> TokenResponse:
    """Authenticate user with username and password.

    Uses bcrypt password verification and dummy hash to prevent timing attacks.
    On success, issues a signed JWT Bearer Token.
    """
    user = db.scalar(select(User).where(User.username == username.strip()))

    # Check against stored hash if user exists, else compare against _DUMMY_HASH
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    is_valid_password = verify_password(password, hash_to_check)

    if not user or not is_valid_password:
        log.warning("Authentication failed for username='%s'", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Issue JWT token
    token = create_access_token(
        user_id=user.id,
        secret=settings.jwt_secret,
        expire_minutes=settings.jwt_expire_minutes,
    )

    log.info("User '%s' (id=%s) logged in successfully", user.username, user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
    )


def get_user_profile(db: Session, user_id: str) -> UserProfile:
    """Retrieve user profile information along with current available balance (GET /me).

    Automatically initializes an account with 0.00 balance if not already present.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Find associated payment account
    account = db.scalar(select(Account).where(Account.user_id == user.id))
    if not account:
        account = Account(user_id=user.id, balance=Decimal("0.00"), version=0)
        db.add(account)
        db.commit()
        db.refresh(account)

    return UserProfile(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        balance=account.balance,
    )


def get_account_balance(db: Session, user_id: str) -> Decimal:
    """Quick lookup of the user's available balance."""
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment account not found for this user",
        )
    return account.balance


# ==============================================================================
# TASK 4: CONDITIONAL DEBIT & SAGA COMPENSATION (CREDIT)
# ==============================================================================

def debit_user_account(
    db: Session,
    user_id: str,
    amount: Decimal,
    transaction_id: str,
) -> DebitResponse:
    """Deduct money from the payer's account conditionally and atomically.

    Business and safety rules:
    1. Idempotency: Each transaction_id is debited at most once.
       If already debited, return success with the previously recorded balance.
    2. Sufficient Funds Check: Atomic UPDATE with condition 'WHERE balance >= :amount'.
       If balance is insufficient -> rowcount is 0 -> return HTTP 422 Unprocessable Content.
    """
    # 1. Idempotency check via ledger_entries
    existing_ledger = db.scalar(
        select(LedgerEntry).where(
            LedgerEntry.transaction_id == transaction_id,
            LedgerEntry.type == "DEBIT",
        )
    )
    if existing_ledger:
        log.info(
            "Duplicate debit request for txn_id=%s. Returning existing balance without re-charging.",
            transaction_id,
        )
        return DebitResponse(
            success=True,
            transaction_id=transaction_id,
            balance_after=existing_ledger.balance_after,
            message="Transaction was already debited previously",
        )

    # 2. Retrieve payer account
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payer account not found",
        )

    # 3. Execute atomic conditional update (balance >= amount)
    result = db.execute(
        update(Account)
        .where(Account.user_id == user_id, Account.balance >= amount)
        .values(
            balance=Account.balance - amount,
            version=Account.version + 1,
        )
        .execution_options(synchronize_session=False)
    )

    # If rowcount == 0: insufficient balance
    if result.rowcount == 0:
        log.warning(
            "Debit failed for user_id=%s: available balance (%s) is less than amount (%s)",
            user_id,
            account.balance,
            amount,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient balance to complete the tuition payment",
        )

    # Reload new balance
    db.refresh(account)
    new_balance = account.balance

    # 4. Record entry in ledger_entries to guarantee idempotency
    ledger = LedgerEntry(
        transaction_id=transaction_id,
        account_id=account.id,
        type="DEBIT",
        amount=amount,
        balance_after=new_balance,
    )
    db.add(ledger)
    db.commit()

    log.info(
        "Debit successful: user_id=%s, txn_id=%s, amount=%s, remaining balance=%s",
        user_id,
        transaction_id,
        amount,
        new_balance,
    )

    return DebitResponse(
        success=True,
        transaction_id=transaction_id,
        balance_after=new_balance,
        message="Account debited successfully",
    )


def credit_user_account(
    db: Session,
    user_id: str,
    amount: Decimal,
    transaction_id: str,
) -> CreditResponse:
    """Refund money back to payer's account (saga compensation).

    Enforces Idempotency: each transaction_id is refunded at most once.
    """
    # 1. Idempotency check for refund
    existing_ledger = db.scalar(
        select(LedgerEntry).where(
            LedgerEntry.transaction_id == transaction_id,
            LedgerEntry.type == "CREDIT",
        )
    )
    if existing_ledger:
        log.info(
            "Duplicate credit request for txn_id=%s. Returning existing balance without re-refunding.",
            transaction_id,
        )
        return CreditResponse(
            success=True,
            transaction_id=transaction_id,
            balance_after=existing_ledger.balance_after,
            message="Transaction was already refunded previously",
        )

    # 2. Retrieve payer account
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payer account not found",
        )

    # 3. Add money back atomically
    db.execute(
        update(Account)
        .where(Account.user_id == user_id)
        .values(
            balance=Account.balance + amount,
            version=Account.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.refresh(account)
    new_balance = account.balance

    # 4. Record CREDIT entry in ledger
    ledger = LedgerEntry(
        transaction_id=transaction_id,
        account_id=account.id,
        type="CREDIT",
        amount=amount,
        balance_after=new_balance,
    )
    db.add(ledger)
    db.commit()

    log.info(
        "Credit successful: user_id=%s, txn_id=%s, refunded=%s, new balance=%s",
        user_id,
        transaction_id,
        amount,
        new_balance,
    )

    return CreditResponse(
        success=True,
        transaction_id=transaction_id,
        balance_after=new_balance,
        message="Account refunded successfully",
    )


# ==============================================================================
# TRANSACTION HISTORY
# ==============================================================================

def get_transaction_history(
    db: Session,
    user_id: str,
    limit: int = 100,
) -> List[TransactionHistoryItem]:
    """Retrieve transaction history of the authenticated user (newest first)."""
    transactions = db.scalars(
        select(TransactionHistory)
        .where(TransactionHistory.payer_user_id == user_id)
        .order_by(TransactionHistory.created_at.desc())
        .limit(limit)
    ).all()

    return [TransactionHistoryItem.model_validate(t) for t in transactions]


def record_transaction_history(
    db: Session,
    user_id: str,
    student_id: str,
    tuition_id: Optional[str],
    amount: Decimal,
    status: str = "SUCCESS",
    failure_reason: Optional[str] = None,
) -> TransactionHistory:
    """Record payment transaction history entry."""
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    account_id = account.id if account else "unknown-account"

    history_record = TransactionHistory(
        account_id=account_id,
        payer_user_id=user_id,
        student_id=student_id,
        tuition_id=tuition_id,
        amount=amount,
        status=status,
        failure_reason=failure_reason,
        completed_at=utcnow() if status == "SUCCESS" else None,
    )
    db.add(history_record)
    db.commit()
    db.refresh(history_record)
    return history_record
