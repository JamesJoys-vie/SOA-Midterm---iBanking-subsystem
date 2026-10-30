"""Service settings for user-service, loaded from environment variables or .env."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    """Read an environment variable as an integer, or return the default value."""
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Configuration settings for user-service (immutable dataclass)."""

    # Database connection URL for user-service's own database
    # Local dev/testing default: sqlite:///./users.db
    # Production / Docker Compose default: mysql+pymysql://user_svc:user_pass@mysql:3306/users_db
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./users.db")

    # Secret key used for signing and verifying JWT tokens (HS256)
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-super-secret-jwt-key-for-ibanking")

    # Access token expiration time in minutes (default 30 minutes as required)
    jwt_expire_minutes: int = _int("JWT_EXPIRE_MINUTES", 30)

    # Database startup retry settings (useful for Docker Compose startup)
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

    # Server port
    port: int = _int("PORT", 8000)


# Global settings singleton used throughout the service
settings = Settings()
