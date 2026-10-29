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
    """All configuration of notification-service. Frozen so nothing changes it at runtime."""

    # Connection string of this service's own PostgreSQL database.
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://ibanking:ibanking@localhost:5432/notification"
    )
    internal_api_token: str = os.getenv("INTERNAL_API_TOKEN", "change-me")  # Token callers (otp-service, payment-service) send as X-Internal-Token.

    # Outgoing mail server: the Mailtrap Email Testing inbox (catches every email, delivers none).
    # Port 2525 or 587 with STARTTLS; port 465 (TLS from the first byte) is not supported.
    smtp_host: str = os.getenv("SMTP_HOST", "sandbox.smtp.mailtrap.io")
    smtp_port: int = _int("SMTP_PORT", 2525)
    smtp_user: str = os.getenv("SMTP_USER", "")  # from the Mailtrap inbox's SMTP settings; empty = no login
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_starttls: bool = _bool("SMTP_STARTTLS", True)
    smtp_timeout_seconds: int = _int("SMTP_TIMEOUT_SECONDS", 10)
    mail_from: str = os.getenv("MAIL_FROM", "iBanking <no-reply@ibanking.local>")  # Sender shown in every email.

    # The database may start after this service (e.g. in Docker Compose):
    # how many times to try connecting at startup, and the wait between tries.
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

settings = Settings()  # The single settings object the rest of the service imports.
