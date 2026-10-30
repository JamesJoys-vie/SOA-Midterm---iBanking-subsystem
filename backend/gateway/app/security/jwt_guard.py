"""JWT check at the edge: the gateway is the only place that reads the token.

Services behind it trust the X-User-Id header, which the gateway sets from the token's `sub` claim
(a client-sent X-User-Id is always removed, see proxy/reverse_proxy.py).
"""
import jwt
from shared.security import decode_token


class AuthError(Exception):
    pass


class JwtGuard:
    def __init__(self, secret: str):
        self.secret = secret

    def user_id_from(self, authorization: str | None) -> str:
        """"Bearer <jwt>" -> user id, or AuthError (-> 401)."""
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError("Not authenticated")
        try:
            claims = decode_token(token.strip(), self.secret)
        except jwt.ExpiredSignatureError:
            raise AuthError("Token expired, please log in again")
        except jwt.PyJWTError:
            raise AuthError("Invalid token")
        if not claims.get("sub"):
            raise AuthError("Invalid token")
        return str(claims["sub"])
