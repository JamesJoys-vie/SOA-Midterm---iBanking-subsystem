"""Consumes `otp.requested` and `payment.completed` from Redis Streams (consumer group `notification`) and sends emails.
Handlers must be idempotent: a message can be delivered more than once (see shared/events.py)."""
import hashlib
import logging
import threading
from shared import events
from shared.redis_client import get_redis
from app.domain.mailer import send_email

log = logging.getLogger("notification.consumer")
GROUP = "notification"
DEDUPE_TTL_S = 86_400


def _vnd(amount) -> str:
    return f"{float(amount):,.0f} VND"


def _render(event_type: str, p: dict) -> tuple[str, str, str]:
    """-> (dedupe id, subject, body)"""
    if event_type == events.OTP_REQUESTED:
        # a resend reuses the transaction id with a new code -> include the code (hashed) in the dedupe id
        otp_id = hashlib.sha256(p["otp"].encode()).hexdigest()[:16]
        return (f"{p['transaction_id']}:{otp_id}", "Your tuition payment OTP",
                f"Hello {p['full_name']},\n\n"
                f"Your one-time password is {p['otp']}.\n"
                f"It expires in {p['expires_in'] // 60} minutes and can be used once.\n"
                f"Transaction: {p['transaction_id']}\n\n"
                f"If you did not start this payment, ignore this email and do not share the code.")
    return (p["transaction_id"], "Tuition payment successful",
            f"Hello {p['full_name']},\n\n"
            f"Your payment of {_vnd(p['amount'])} for student {p['student_id']} was successful.\n"
            f"Remaining balance: {_vnd(p['balance_after'])}\n"
            f"Transaction: {p['transaction_id']}\n")


def make_handler(r):
    def handle(event_type: str, payload: dict) -> None:
        if event_type not in (events.OTP_REQUESTED, events.PAYMENT_COMPLETED):
            return
        dedupe_id, subject, body = _render(event_type, payload)
        key = f"notif:sent:{event_type}:{dedupe_id}"
        if not r.set(key, 1, nx=True, ex=DEDUPE_TTL_S):
            return  # already sent (redelivery)
        try:
            send_email(payload["email"], subject, body)
        except Exception:
            r.delete(key)  # let the redelivery try again
            raise
    return handle


def _run(r, stop: threading.Event) -> None:
    """Keep the consumer alive across Redis hiccups (consume() raises on connection errors)."""
    handler = make_handler(r)
    while not stop.is_set():
        try:
            events.consume(r, GROUP, [events.OTP_REQUESTED, events.PAYMENT_COMPLETED], handler, stop=stop)
        except Exception:
            log.exception("stream consumer crashed; restarting in 3s")
            stop.wait(3)


def start(redis_url: str, stop: threading.Event | None = None) -> threading.Thread:
    t = threading.Thread(target=_run, daemon=True, name="stream-consumer",
                         args=(get_redis(redis_url), stop or threading.Event()))
    t.start()
    return t
