from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str  # event bus (Redis Streams)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ibanking@example.com"


settings = Settings()
