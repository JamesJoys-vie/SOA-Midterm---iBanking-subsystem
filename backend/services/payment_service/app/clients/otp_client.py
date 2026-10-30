"""Calls to otp-service. Never retried: issuing twice hits the resend cooldown and a verify consumes the code."""
from dataclasses import dataclass
from app.clients.base import ServiceClient


@dataclass(frozen=True)
class OtpCheck:
    valid: bool
    reason: str | None = None  # invalid | expired | locked
    attempts_left: int | None = None


class OtpClient(ServiceClient):
    name = "otp-service"

    def issue(self, txn_id: str, email: str, full_name: str) -> int:
        """New 6-digit OTP bound to txn_id, emailed by notification-service -> seconds until it expires.
        """
        d = self._request("POST", "/internal/otp", {"transaction_id": txn_id, "email": email, "full_name": full_name},
                          retry=False)
        return int(d["expires_in"])

    def verify(self, txn_id: str, code: str) -> OtpCheck:
        """Single-use check: a correct code is accepted exactly once."""
        d = self._request("POST", "/internal/otp/verify", {"transaction_id": txn_id, "otp": code}, retry=False)
        return OtpCheck(bool(d["valid"]), d.get("reason"), d.get("attempts_left"))
