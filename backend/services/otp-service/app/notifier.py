"""Client for notification-service, which emails the code to the payer."""
from dataclasses import dataclass

import httpx

from app.config import Settings, settings

class NotifierError(Exception):
    """notification-service could not be reached or did not send the email."""

@dataclass
class OtpEmail:
    """What the OTP email needs. Everything but the code comes from payment-service's request."""
    to: str
    payer_name: str
    mssv: str
    student_name: str
    amount: int  # VND
    code: str = ""  # filled in by send_otp once the OTP exists
    expires_in: int = 0  # seconds, filled in by send_otp

class Notifier:
    """Calls notification-service over HTTP with the internal token."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def send_otp_email(self, email: OtpEmail) -> None:
        """POST /emails/otp, or raise NotifierError."""
        try:
            res = httpx.post(
                f"{self.cfg.notification_url}/emails/otp",
                json=email.__dict__,
                headers={"X-Internal-Token": self.cfg.notification_token},
                timeout=self.cfg.notification_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise NotifierError(f"notification-service unreachable: {exc}") from exc
        if res.status_code != 200:
            raise NotifierError(f"notification-service answered {res.status_code}: {res.text[:200]}")

def get_notifier() -> Notifier:
    """FastAPI dependency, so tests can swap in a fake notifier."""
    return Notifier(settings)
