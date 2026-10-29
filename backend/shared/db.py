"""Shared SQLAlchemy helpers (sync engine + PyMySQL; FastAPI runs `def` endpoints in a threadpool)."""
import os
import uuid
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import sessionmaker

# Wait at most this long for a pooled connection, then answer 503. It must stay well below the gateway timeout
# (20 s): otherwise requests nobody waits for any more pile up in the service (seen in the Phase 5 load test).
POOL_TIMEOUT_S = 5


def new_id() -> str:
    return str(uuid.uuid4())


def make_engine(url: str):
    # per process: with UVICORN_WORKERS=n a service opens up to n * (size + overflow) MySQL connections
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_timeout=POOL_TIMEOUT_S,
                         pool_size=int(os.environ.get("DB_POOL_SIZE", 10)),
                         max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", 20)))


def add_busy_handler(app) -> None:
    """Pool exhausted -> 503 + Retry-After instead of a 500; clients retry (same Idempotency-Key)."""
    from fastapi.responses import JSONResponse

    @app.exception_handler(PoolTimeout)
    async def _busy(request, exc):
        return JSONResponse({"detail": "Service busy, try again"}, status_code=503, headers={"Retry-After": "1"})


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
