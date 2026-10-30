"""Main entry point for tuition-service (FastAPI).

Implements Hieu's responsibilities:
- Task 2:
  * Tuition lookup: GET /tuitions?mssv= and GET /tuitions/{student_id}.
    Returns student name and full tuition amount (partial payment disallowed).
  * Conditional reservation hold: POST /internal/tuitions/{id}/reserve.
- Task 4:
  * Mark-paid commit: POST /internal/tuitions/{id}/commit (only current hold owner).
  * Release hold: POST /internal/tuitions/{id}/release (saga compensation or cancel).
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import db_is_up, get_db, init_db
from app.schemas import (
    CommitRequest,
    CommitResponse,
    ReleaseRequest,
    ReleaseResponse,
    ReserveRequest,
    TuitionInfo,
)
from app.service import (
    commit_tuition,
    lookup_tuition,
    release_tuition,
    reserve_tuition,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("tuition-service")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application startup: Initialize database tables."""
    log.info("tuition-service is starting up...")
    init_db()
    yield
    log.info("tuition-service is shutting down...")


app = FastAPI(
    title="Tuition Service - iBanking Subsystem",
    description="Tuition lookup by MSSV, conditional reservation hold, and mark-paid status management",
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# HEALTHCHECK & READINESS ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["System"])
def health() -> dict:
    """Liveness check: Indicates the process is up."""
    return {"status": "ok", "service": "tuition-service"}


@app.get("/ready", tags=["System"])
def ready() -> JSONResponse:
    """Readiness check: Indicates the database connection is healthy."""
    if db_is_up():
        return JSONResponse({"status": "ready", "service": "tuition-service"})
    return JSONResponse(
        {"status": "database unavailable", "service": "tuition-service"},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ==============================================================================
# TASK 2: TUITION LOOKUP (GET /tuitions?mssv= AND GET /tuitions/{student_id})
# ==============================================================================

@app.get(
    "/tuitions",
    response_model=TuitionInfo,
    tags=["Tuition Lookup"],
    summary="Tuition lookup by MSSV via query parameter (?mssv=)",
)
def get_tuition_by_query(
    mssv: Optional[str] = Query(None, description="Student ID (e.g. 52100001, 521H0081)"),
    student_id: Optional[str] = Query(None, description="Alias for mssv"),
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Task 2b: Enter MSSV -> auto-lookup student name and full tuition amount.

    Only full tuition payment is allowed (no partial payment).
    """
    code = mssv or student_id
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide the 'mssv' query parameter for tuition lookup",
        )
    return lookup_tuition(db, code)


@app.get(
    "/tuitions/{student_id}",
    response_model=TuitionInfo,
    tags=["Tuition Lookup"],
    summary="Tuition lookup by MSSV via path parameter (OpenAPI standard)",
)
def get_tuition_by_path(
    student_id: str,
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Look up student tuition liability via path parameter /tuitions/{student_id}."""
    return lookup_tuition(db, student_id)


# ==============================================================================
# TASK 2: CONDITIONAL RESERVATION HOLD
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/reserve",
    response_model=TuitionInfo,
    tags=["Tuition Hold"],
    summary="Hold tuition conditionally for a transaction (internal)",
)
@app.post(
    "/tuitions/{tuition_id}/reserve",
    response_model=TuitionInfo,
    tags=["Tuition Hold"],
    summary="Hold tuition conditionally for a transaction (alias)",
)
def reserve_tuition_endpoint(
    tuition_id: str,
    body: ReserveRequest,
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Task 2: Conditional reservation hold.

    Executes an atomic conditional UPDATE to lock tuition for 10 minutes,
    preventing race conditions when multiple payers attempt to pay for the same student.
    """
    return reserve_tuition(db, tuition_id, body.transaction_id)


# ==============================================================================
# TASK 4: MARK-PAID (COMMIT)
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/commit",
    response_model=CommitResponse,
    tags=["Tuition Status"],
    summary="Update tuition to PAID (only transaction holding the lock)",
)
@app.post(
    "/tuitions/{tuition_id}/commit",
    response_model=CommitResponse,
    tags=["Tuition Status"],
    summary="Update tuition to PAID (alias)",
)
def commit_tuition_endpoint(
    tuition_id: str,
    body: CommitRequest,
    db: Session = Depends(get_db),
) -> CommitResponse:
    """Task 4: Mark-paid (only transaction holding the lock).

    Transitions status from RESERVED to PAID.
    Rejects with 409 Conflict if not currently locked by this transaction.
    """
    return commit_tuition(db, tuition_id, body.transaction_id)


# ==============================================================================
# TASK 4: RELEASE HOLD (COMPENSATION OR CANCELLATION)
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/release",
    response_model=ReleaseResponse,
    tags=["Tuition Hold"],
    summary="Release tuition hold back to UNPAID status",
)
@app.post(
    "/tuitions/{tuition_id}/release",
    response_model=ReleaseResponse,
    tags=["Tuition Hold"],
    summary="Release tuition hold back to UNPAID status (alias)",
)
def release_tuition_endpoint(
    tuition_id: str,
    body: ReleaseRequest,
    db: Session = Depends(get_db),
) -> ReleaseResponse:
    """Release tuition hold when transaction is cancelled or saga step fails."""
    return release_tuition(db, tuition_id, body.transaction_id)
