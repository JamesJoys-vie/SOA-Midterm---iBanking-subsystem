"""Database connection for otp-service's own database."""
import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

log = logging.getLogger(__name__)
engine = create_engine(settings.database_url, pool_pre_ping=True)  # Connection pool to the database. pool_pre_ping drops dead connections before use.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)  # Factory for sessions (one per request). Objects stay readable after commit.

class Base(DeclarativeBase):
    """Parent class of every table model in this service."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: open a session for one request and close it afterwards."""
    with SessionLocal() as db:
        yield db

def db_is_up() -> bool:
    """Return True if a trivial query succeeds. Used by the /ready check."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False

def init_db() -> None:
    """Create this service's tables, waiting for the database to come up first."""
    for attempt in range(1, settings.db_connect_retries + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except OperationalError:
            if attempt == settings.db_connect_retries:
                raise
            log.warning("database not ready (attempt %d/%d), retrying",
                        attempt, settings.db_connect_retries)
            time.sleep(settings.db_connect_retry_seconds)