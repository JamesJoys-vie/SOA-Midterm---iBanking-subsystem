"""Service configuration for tuition-service loaded from environment variables or .env."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    """Read an environment variable as an integer, or return the default value."""
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Configuration settings for tuition-service (immutable dataclass)."""

    # Database connection URL for tuition-service's isolated database
    # Local dev/testing default: sqlite:///./tuition.db
    # Production / Docker Compose default: mysql+pymysql://tuition_svc:tuition_pass@mysql:3306/tuition_db
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./tuition.db")

    # Tuition reservation hold duration in seconds (default: 600s = 10 minutes)
    # Keeps tuition locked while the payer receives and verifies OTP
    reservation_ttl_seconds: int = _int("RESERVATION_TTL_SECONDS", 600)

    # Database startup retry settings for container environments
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

    # Service listening port
    port: int = _int("PORT", 8000)


settings = Settings()
