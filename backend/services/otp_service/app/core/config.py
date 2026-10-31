from pydantic import field_validator
from pydantic_settings import BaseSettings
from shared.otp_crypto import validate_key


class Settings(BaseSettings):
    redis_url: str
    otp_event_key: str  # Fernet key shared with notification-service only: encrypts the code in `otp.requested`
    otp_ttl_seconds: int = 300  # max 5 minutes per requirements
    otp_max_attempts: int = 5  # wrong codes before the OTP is burned
    otp_max_issues: int = 4  # per transaction: initial OTP + 3 resends
    otp_resend_cooldown_seconds: int = 30
    # LOAD TESTS ONLY: also keep the plain code in Redis and expose GET /internal/test/otp/{id} so a test client
    # can confirm payments without reading emails. Never enable it on a real deployment.
    otp_test_echo: bool = False

    @field_validator("otp_event_key")
    @classmethod
    def _valid_key(cls, v: str) -> str:  # a missing / malformed key stops the service at startup
        return validate_key(v)


settings = Settings()
