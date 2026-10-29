"""Cấu hình cho user-service, đọc các biến môi trường từ hệ thống hoặc file .env."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    """Đọc biến môi trường kiểu số nguyên, trả về giá trị mặc định nếu không có."""
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Tập hợp tất cả cấu hình của user-service."""

    # Chuỗi kết nối cơ sở dữ liệu riêng của user-service
    # Mặc định sử dụng SQLite cho môi trường phát triển cục bộ và kiểm thử
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./users.db")

    # Khóa bí mật dùng để ký và giải mã JWT token (HS256)
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-super-secret-jwt-key-for-ibanking")

    # Thời hạn hiệu lực của access token (mặc định 30 phút theo yêu cầu đề tài)
    jwt_expire_minutes: int = _int("JWT_EXPIRE_MINUTES", 30)

    # Cấu hình thử kết nối lại database khi khởi động trong Docker Compose
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

    # Cổng chạy ứng dụng
    port: int = _int("PORT", 8000)


# Đối tượng cài đặt duy nhất được sử dụng xuyên suốt service
settings = Settings()
