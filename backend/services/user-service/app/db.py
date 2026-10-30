"""Database engine, session management, and startup initialization for user-service."""
import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

log = logging.getLogger("user-service.db")

# Connection arguments: SQLite requires check_same_thread=False for multi-threaded FastAPI workers
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Database engine with connection pool pre-ping to drop dead connections
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# Request-scoped sessionmaker (expire_on_commit=False keeps models readable after commit)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base declarative class for user-service ORM models."""
    pass


def get_db() -> Iterator[Session]:
    """FastAPI Dependency: Yields a database session per request and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_is_up() -> bool:
    """Return True if a trivial test query succeeds. Used by the /ready healthcheck."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


def init_db() -> None:
    """Create all service tables, with retry logic waiting for database readiness at startup."""
    for attempt in range(1, settings.db_connect_retries + 1):
        try:
            Base.metadata.create_all(engine)
            log.info("Successfully initialized user-service database tables")
            return
        except OperationalError as exc:
            if attempt == settings.db_connect_retries:
                log.error("Failed to connect to database after %d attempts: %s", attempt, exc)
                raise
            log.warning(
                "Database not ready yet (attempt %d/%d), waiting %d seconds...",
                attempt,
                settings.db_connect_retries,
                settings.db_connect_retry_seconds,
            )
            time.sleep(settings.db_connect_retry_seconds)
