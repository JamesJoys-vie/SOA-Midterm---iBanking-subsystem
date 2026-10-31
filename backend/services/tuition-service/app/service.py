"""Business Service Layer for tuition-service.

Implements Task 2 and Task 4 responsibilities:
- Task 2:
  * Tuition lookup by MSSV: student name and full tuition amount (no partial payment).
  * Oldest unpaid term offered first (FIFO).
  * Atomic conditional reservation hold (reserve) to prevent race conditions.
- Task 4:
  * Mark-paid commit: only the transaction holding the active hold can transition to PAID.
  * Hold release: releases hold back to UNPAID if payment fails or is cancelled.
"""
import logging
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PAID, RESERVED, UNPAID, Student, Tuition, utcnow
from app.schemas import CommitResponse, ReleaseResponse, TuitionInfo

log = logging.getLogger("tuition-service.service")


# ==============================================================================
# TASK 2: TUITION LOOKUP
# ==============================================================================

def lookup_tuition(db: Session, mssv: str) -> TuitionInfo:
    """Look up tuition liability for a student by MSSV.

    Business rules:
    1. Case-insensitive lookup on student_id (e.g. '521h0081' matches '521H0081').
    2. Offers the oldest unpaid term first (FIFO).
    3. If a tuition hold is past reserved_until, it is displayed as UNPAID so the user can pay.
    4. If every term is paid, returns the most recent PAID term so the UI can notify the user.
    5. Always returns the full tuition amount; partial payments are strictly disallowed.
    """
    clean_mssv = mssv.strip().upper()
    if not clean_mssv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student ID (MSSV) must not be empty",
        )

    # 1. Query student record
    student = db.scalar(
        select(Student).where(func.upper(Student.student_id) == clean_mssv)
    )
    if not student:
        log.warning("Student not found for MSSV='%s'", clean_mssv)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with MSSV '{clean_mssv}' not found",
        )

    # 2. Query tuition liabilities: UNPAID/RESERVED prioritized over PAID, ascending by term
    now = utcnow()
    paid_priority = case((Tuition.status == PAID, 1), else_=0)
    tuition = db.scalars(
        select(Tuition)
        .where(Tuition.student_id == student.student_id)
        .order_by(paid_priority, Tuition.term.asc())
    ).first()

    if not tuition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tuition liabilities found for student '{student.full_name}' ({student.student_id})",
        )

    # If all terms are paid, pick the newest term to show completion
    if tuition.status == PAID:
        tuition = db.scalars(
            select(Tuition)
            .where(Tuition.student_id == student.student_id)
            .order_by(Tuition.term.desc())
        ).first()

    # 3. Determine display status (handle stale hold past reserved_until)
    display_status = tuition.status
    if display_status == RESERVED and tuition.reserved_until and tuition.reserved_until < now:
        display_status = UNPAID

    return TuitionInfo(
        tuition_id=tuition.id,
        student_id=tuition.student_id,
        student_name=student.full_name,
        term=tuition.term,
        amount=tuition.amount,
        status=display_status,
    )


# ==============================================================================
# TASK 2: CONDITIONAL RESERVATION HOLD
# ==============================================================================

def reserve_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> TuitionInfo:
    """Hold a tuition liability for a specific transaction (UNPAID -> RESERVED).

    Uses an atomic conditional UPDATE at the database engine level.
    When two concurrent payments race for the same student tuition:
    - Exactly one UPDATE succeeds (rowcount == 1).
    - The losing transaction gets rowcount == 0 and is rejected with 409 Conflict.

    Idempotent: Re-calling with the same transaction_id extends the hold.
    """
    now = utcnow()
    expiry = now + timedelta(seconds=settings.reservation_ttl_seconds)

    # Atomic conditional update
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            or_(
                Tuition.status == UNPAID,
                and_(
                    Tuition.status == RESERVED,
                    or_(
                        Tuition.reserved_until < now,                   # Stale hold from another transaction
                        Tuition.reserved_by_txn == transaction_id,      # Same transaction extending hold
                    ),
                ),
            ),
        )
        .values(
            status=RESERVED,
            reserved_by_txn=transaction_id,
            reserved_until=expiry,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    tuition = db.get(Tuition, tuition_id)
    if not tuition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tuition liability not found",
        )

    # If rowcount == 0: Lost the race or already locked/paid
    if res.rowcount != 1:
        if tuition.status == PAID:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tuition for this student is already paid",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tuition is being paid by another transaction",
            )

    student = db.get(Student, tuition.student_id)
    student_name = student.full_name if student else "N/A"

    log.info(
        "Tuition reserved successfully: tuition_id=%s, txn_id=%s, expires_at=%s",
        tuition_id,
        transaction_id,
        expiry,
    )

    return TuitionInfo(
        tuition_id=tuition.id,
        student_id=tuition.student_id,
        student_name=student_name,
        term=tuition.term,
        amount=tuition.amount,
        status=RESERVED,
    )


# ==============================================================================
# TASK 4: MARK-PAID (COMMIT) & SAGA COMPENSATION (RELEASE)
# ==============================================================================

def commit_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> CommitResponse:
    """Mark tuition as paid (mark-paid): RESERVED -> PAID.

    Safety & consistency rules (Task 4):
    - ONLY the transaction currently holding the reservation
      (status == 'RESERVED' AND reserved_by_txn == transaction_id)
      is authorized to commit the status to PAID.
    - Clears reserved_until and records paid_by_txn.
    - Idempotent: If already PAID by this exact transaction_id, return success.
    """
    # 1. Pre-check idempotency: already paid by this transaction?
    tuition = db.get(Tuition, tuition_id, populate_existing=True)
    if not tuition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tuition liability not found")

    if tuition.status == PAID and tuition.paid_by_txn == transaction_id:
        log.info(
            "Idempotent commit: tuition_id=%s was already PAID by txn_id=%s", tuition_id, transaction_id
        )
        return CommitResponse(status=PAID, message="Tuition was already paid by this transaction")

    # 2. Atomic conditional transition: RESERVED (by this txn) -> PAID
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            Tuition.status == RESERVED,
            Tuition.reserved_by_txn == transaction_id,
        )
        .values(
            status=PAID,
            paid_by_txn=transaction_id,
            reserved_until=None,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if res.rowcount == 1:
        log.info("Mark-paid commit successful: tuition_id=%s by txn_id=%s", tuition_id, transaction_id)
        return CommitResponse(status=PAID, message="Tuition marked as paid successfully")

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Tuition is not reserved by this transaction or already paid by another transaction",
    )


def release_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> ReleaseResponse:
    """Release hold on tuition liability (RESERVED -> UNPAID).

    Called on transaction cancellation or saga compensation failure.
    Idempotent: No-op (released=False) if hold is already gone or belongs to another transaction.
    """
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            Tuition.status == RESERVED,
            Tuition.reserved_by_txn == transaction_id,
        )
        .values(
            status=UNPAID,
            reserved_by_txn=None,
            reserved_until=None,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if res.rowcount == 1:
        log.info("Tuition hold released: tuition_id=%s for txn_id=%s", tuition_id, transaction_id)
        return ReleaseResponse(released=True, message="Tuition hold released successfully")

    return ReleaseResponse(
        released=False,
        message="Tuition hold not found or not owned by this transaction",
    )
