from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./payments.db"  # payments_db (MySQL in compose)
    redis_url: str = "redis://localhost:6379/0"  # event bus for payment.completed
    user_service_url: str = "http://user-service:8000"
    tuition_service_url: str = "http://tuition-service:8000"
    otp_service_url: str = "http://otp-service:8000"
    http_timeout_seconds: float = 5.0
    http_retries: int = 2  # only for idempotent calls (debit/reserve/commit/release)
    otp_ttl_seconds: int = 300  # OTP window = PENDING_OTP window (max 5 minutes)
    # Background jobs (app/workers). Off in unit tests.
    run_workers: bool = True
    expiry_job_interval_seconds: float = 5.0
    outbox_interval_seconds: float = 1.0
    stuck_processing_seconds: int = 30  # PROCESSING longer than this -> the job finishes it


settings = Settings()
