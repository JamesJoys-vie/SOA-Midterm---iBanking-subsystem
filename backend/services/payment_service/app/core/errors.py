"""Business errors of the payment flow, each one bound to an HTTP status code.

The saga raises them; one exception handler turns them into `{"detail": "..."}` (same shape as FastAPI errors).
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse


class PaymentError(Exception):
    status_code = 400

    def __init__(self, detail: str, headers: dict | None = None):
        super().__init__(detail)
        self.detail, self.headers = detail, headers


class BadRequest(PaymentError):  # bad Idempotency-Key, wrong / expired / locked OTP
    status_code = 400


class NotFound(PaymentError):  # unknown transaction (or another user's one), student, tuition
    status_code = 404


class Conflict(PaymentError):  # tuition paid / held, transaction not in the needed status
    status_code = 409


class Gone(PaymentError):  # transaction expired (OTP window is over)
    status_code = 410


class InsufficientBalance(PaymentError):
    status_code = 422


class TooManyRequests(PaymentError):  # OTP resend limit (Retry-After from otp-service)
    status_code = 429


class UpstreamError(PaymentError):  # a service we depend on did not answer; safe to retry
    status_code = 502


def add_error_handler(app: FastAPI) -> None:
    @app.exception_handler(PaymentError)
    async def _payment_error(request, exc: PaymentError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
