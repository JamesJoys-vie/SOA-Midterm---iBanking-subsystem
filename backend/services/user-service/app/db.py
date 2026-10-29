"""Quản lý kết nối cơ sở dữ liệu và phiên làm việc (Session) của user-service."""
import logging
import time
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

log = logging.getLogger("user-service.db")

# Xử lý tham số kết nối: nếu dùng SQLite thì cần check_same_thread=False
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Khởi tạo engine với pool_pre_ping để tự loại bỏ các kết nối hỏng
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

# Factory tạo session cho từng request (expire_on_commit=False giúp giữ dữ liệu object sau commit)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Lớp cơ sở cho toàn bộ các model bảng dữ liệu của user-service."""
    pass


def get_db() -> Iterator[Session]:
    """FastAPI Dependency: Cung cấp session database cho mỗi request và tự đóng sau khi kết thúc."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_is_up() -> bool:
    """Kiểm tra kết nối cơ sở dữ liệu có đang hoạt động tốt hay không (dùng cho /ready endpoint)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


def init_db() -> None:
    """Tạo bảng dữ liệu nếu chưa tồn tại, có cơ chế retry chờ database sẵn sàng lúc khởi động."""
    for attempt in range(1, settings.db_connect_retries + 1):
        try:
            Base.metadata.create_all(engine)
            log.info("Khởi tạo bảng cơ sở dữ liệu user-service thành công")
            return
        except OperationalError as exc:
            if attempt == settings.db_connect_retries:
                log.error("Không thể kết nối đến cơ sở dữ liệu sau %d lần thử: %s", attempt, exc)
                raise
            log.warning(
                "Cơ sở dữ liệu chưa sẵn sàng (lần thử %d/%d), đang đợi %d giây...",
                attempt,
                settings.db_connect_retries,
                settings.db_connect_retry_seconds,
            )
            time.sleep(settings.db_connect_retry_seconds)
