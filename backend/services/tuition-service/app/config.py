"""Cấu hình cho tuition-service."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    """Đọc biến môi trường kiểu số nguyên, trả về giá trị mặc định nếu không có."""
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Tập hợp tất cả cấu hình của tuition-service."""

    # Chuỗi kết nối cơ sở dữ liệu riêng của tuition-service
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./tuition.db")

    # Thời hạn giữ khóa học phí cho một giao dịch (giây) - mặc định 600s = 10 phút
    reservation_ttl_seconds: int = _int("RESERVATION_TTL_SECONDS", 600)

    # Cấu hình thử kết nối lại database khi khởi động trong Docker Compose
    db_connect_retries: int = _int("DB_CONNECT_RETRIES", 10)
    db_connect_retry_seconds: int = _int("DB_CONNECT_RETRY_SECONDS", 2)

    # Cổng chạy ứng dụng
    port: int = _int("PORT", 8000)


settings = Settings()
