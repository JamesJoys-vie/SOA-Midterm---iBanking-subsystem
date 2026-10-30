"""Engine + session factory of payments_db (reuses the shared helpers in shared/db.py)."""
from collections.abc import Iterator
from sqlalchemy.orm import Session
from shared.db import make_engine, make_session_factory
from app.core.config import settings

engine = make_engine(settings.database_url)
SessionLocal = make_session_factory(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
