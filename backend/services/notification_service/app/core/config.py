from pydantic import field_validator
from pydantic_settings import BaseSettings
from shared.otp_crypto import validate_key


class Settings(BaseSettings):
    redis_url: str  # event bus (Redis Streams)
    otp_event_key: str  # Fernet key shared with otp-service only: decrypts the code in `otp.requested`
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ibanking@example.com"

    @field_validator("otp_event_key")
    @classmethod
    def _valid_key(cls, v: str) -> str:  # a missing / malformed key stops the service at startup
        return validate_key(v)


settings = Settings()
