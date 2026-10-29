from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str
    otp_ttl_seconds: int = 300  # max 5 minutes per requirements
    otp_max_attempts: int = 5  # wrong codes before the OTP is burned
    otp_max_issues: int = 4  # per transaction: initial OTP + 3 resends
    otp_resend_cooldown_seconds: int = 30
    # LOAD TESTS ONLY: also keep the plain code in Redis and expose GET /internal/test/otp/{id} so a test client
    # can confirm payments without reading emails. Never enable it on a real deployment.
    otp_test_echo: bool = False


settings = Settings()
