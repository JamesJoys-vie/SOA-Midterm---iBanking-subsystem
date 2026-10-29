"""Module bảo mật: Xử lý mã hóa mật khẩu với bcrypt và xác thực JWT.

Đáp ứng yêu cầu của Task 1:
- Đăng nhập bằng bcrypt và sinh mã JWT token
- Cung cấp cơ chế 'Kiểm tra JWT (dùng chung)' bảo vệ các endpoint yêu cầu xác thực.
"""
import time
from typing import Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# Chuẩn bị HTTPBearer dependency để FastAPI tự parse header 'Authorization: Bearer <token>'
security_bearer = HTTPBearer(auto_error=False)

# Dummy hash để chạy kiểm tra giả định khi username không tồn tại trong hệ thống.
# Kỹ thuật này giúp loại bỏ nguy cơ Timing Attack (kẻ tấn công đo thời gian phản hồi để đoán xem username có tồn tại hay không).
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing-defense", bcrypt.gensalt()).decode()


def hash_password(plain_password: str) -> str:
    """Mã hóa mật khẩu văn bản thô bằng thuật toán bcrypt với salt ngẫu nhiên."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Xác thực mật khẩu người dùng nhập vào với chuỗi hash đã lưu trong database."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, secret: str, expire_minutes: int = 30) -> str:
    """Tạo mã JWT Access Token (HS256) chứa user_id (subject), thời điểm tạo và hết hạn."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + (expire_minutes * 60),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """Giải mã và xác thực chữ ký JWT.

    Ném ra HTTPException(401) nếu token không hợp lệ hoặc đã hết hạn.
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token đã hết hạn, vui lòng đăng nhập lại",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_id(
    auth: Optional[HTTPAuthorizationCredentials] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    """FastAPI Dependency dùng chung để xác thực và lấy user_id của người dùng đang đăng nhập.

    Hỗ trợ 2 trường hợp:
    1. Khi gọi trực tiếp qua user-service: xác thực Authorization Bearer token.
    2. Khi đi qua API Gateway: Gateway đã xác thực JWT và chuyển user_id qua header 'X-User-Id'.
    """
    # Trường hợp 1: Có header X-User-Id từ API Gateway
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()

    # Trường hợp 2: Có Bearer Token
    if auth and auth.credentials:
        payload = decode_token(auth.credentials, settings.jwt_secret)
        user_id = payload.get("sub")
        if user_id:
            return str(user_id)

    # Nếu không có cả hai -> Từ chối truy cập
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Yêu cầu đăng nhập để truy cập tài nguyên này",
        headers={"WWW-Authenticate": "Bearer"},
    )
