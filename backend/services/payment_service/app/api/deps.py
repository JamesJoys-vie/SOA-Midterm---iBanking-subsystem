"""FastAPI dependencies: who is calling (X-User-Id set by the gateway) and a saga wired with its clients."""
from functools import lru_cache
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.clients.otp_client import OtpClient
from app.clients.tuition_client import TuitionClient
from app.clients.user_client import UserClient
from app.core.config import settings
from app.core.database import get_db
from app.domain.payment_saga import PaymentSaga
from app.repositories.transaction_repo import TransactionRepository


def current_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> str:
    """The gateway verified the JWT and put the user id here (a client-sent X-User-Id is dropped there).
    """
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return x_user_id.strip()


@lru_cache
def clients() -> tuple[UserClient, TuitionClient, OtpClient]:
    """One client per service per process (httpx keeps a connection pool)."""
    opts = {"timeout_s": settings.http_timeout_seconds, "retries": settings.http_retries}
    return (UserClient(settings.user_service_url, **opts), TuitionClient(settings.tuition_service_url, **opts),
            OtpClient(settings.otp_service_url, **opts))


def make_saga(db: Session) -> PaymentSaga:
    return PaymentSaga(TransactionRepository(db), *clients(), otp_ttl_seconds=settings.otp_ttl_seconds)


def get_saga(db: Session = Depends(get_db)) -> PaymentSaga:
    return make_saga(db)
