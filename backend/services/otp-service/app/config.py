"""Service settings, read once from environment variables (see .env.example)."""
import os
from dataclasses import dataclass

def _int(name: str, default: int) -> int:
    """Read env var `name` as an int, or `default` when it isn't set."""
    return int(os.getenv(name, default))

def _bool(name: str, default: bool) -> bool:
    """Read env var `name` as a bool ("1", "true", "yes" mean True)."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}

@dataclass(frozen=True)
class Settings:
    """All configuration of otp-service. Frozen so nothing changes it at runtime."""

    # Connection string of this service's own PostgreSQL database.
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://ibanking:ibanking@localhost:5432/otp"
    )
    
    internal_api_token: str = os.getenv("INTERNAL_API_TOKEN", "change-me")  # Shared token callers must send as X-Internal-Token. Only payment-service has it.
    otp_secret: str = os.getenv("OTP_SECRET", "change-me")  # Secret for hashing OTP codes. Must be the same on every otp-service replica.
    otp_ttl_seconds: int = _int("OTP_TTL_SECONDS", 300)  # How long a code stays valid, in seconds. Requirement: at most 5 minutes.
    
    otp_length: int = _int("OTP_LENGTH", 6)  # Number of digits in a code.
    otp_max_attempts: int = _int("OTP_MAX_ATTEMPTS", 3)  # Wrong codes allowed before the OTP is locked.
    
    otp_debug_return_code: bool = _bool("OTP_DEBUG_RETURN_CODE", False)  # Dev only: return the plain code from POST /otps until email delivery exists.

    # The database may start after this service (e.g. in Docker Compose):
    # how many times to try connecting at startup, and the wait between tries.
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

settings = Settings()  # The single settings object the rest of the service imports.