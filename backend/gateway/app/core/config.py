from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    jwt_secret: str = "change_me_to_a_long_random_string"  # same secret as user-service (it signs, we verify)
    redis_url: str = "redis://localhost:6379/0"  # rate-limit counters
    user_service_url: str = "http://user-service:8000"
    tuition_service_url: str = "http://tuition-service:8000"
    payment_service_url: str = "http://payment-service:8000"
    upstream_timeout_seconds: float = 20.0
    rate_limit_multiplier: int = 1  # raise only for load tests
