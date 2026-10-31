"""Security module: Password hashing with bcrypt and JWT authentication.

Implements Task 1 requirements:
- Login with bcrypt password verification and JWT token generation.
- Common JWT validation dependency to protect routes requiring authentication.
"""
import time
from typing import Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# HTTPBearer dependency for parsing 'Authorization: Bearer <token>'
security_bearer = HTTPBearer(auto_error=False)

# Dummy bcrypt hash evaluated when username is not found.
# Prevents Timing Attacks where response time could reveal whether a username exists.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing-defense", bcrypt.gensalt()).decode()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt with a random salt."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, secret: str, expire_minutes: int = 30) -> str:
    """Create a signed JWT access token (HS256) containing user_id (sub), iat, and exp."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + (expire_minutes * 60),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """Decode and verify a JWT access token.

    Raises HTTPException(401) if the token is expired, tampered with, or invalid.
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired, please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_id(
    auth: Optional[HTTPAuthorizationCredentials] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    """FastAPI Dependency: Extract and verify the authenticated user ID.

    Supports two scenarios:
    1. Forwarded by API Gateway: Gateway verifies JWT and injects verified user ID in 'X-User-Id'.
    2. Direct call to service: Validates 'Authorization: Bearer <token>' header directly.
    """
    # 1. API Gateway injected header
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()

    # 2. Bearer token in request header
    if auth and auth.credentials:
        payload = decode_token(auth.credentials, settings.jwt_secret)
        user_id = payload.get("sub")
        if user_id:
            return str(user_id)

    # Missing authentication
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required to access this resource",
        headers={"WWW-Authenticate": "Bearer"},
    )
