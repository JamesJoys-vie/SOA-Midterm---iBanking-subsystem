"""Password hashing + JWT helpers shared by user-service (issues) and gateway (verifies)."""
import time
import bcrypt
import jwt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str, secret: str, expire_minutes: int = 30) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + expire_minutes * 60}, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """Raises jwt.PyJWTError if invalid/expired."""
    return jwt.decode(token, secret, algorithms=["HS256"])
