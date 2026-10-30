"""Calls to tuition-service. reserve / commit / release are idempotent per transaction_id, so they are retried."""
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote
from app.clients.base import ServiceClient

UNPAID, RESERVED, PAID = "UNPAID", "RESERVED", "PAID"


@dataclass(frozen=True)
class Tuition:
    tuition_id: str
    student_id: str
    student_name: str
    term: str
    amount: Decimal
    status: str


class TuitionClient(ServiceClient):
    name = "tuition-service"

    def lookup(self, student_id: str) -> Tuition:
        """Tuition to pay for a MSSV (the oldest unpaid term)."""
        return _tuition(self._request("GET", f"/tuitions/{quote(student_id.strip(), safe='')}"))

    def reserve(self, tuition_id: str, txn_id: str) -> Tuition:
        """Hold the tuition for this transaction (UNPAID -> RESERVED). 409 if paid or held by another one.
        Calling it again with the same transaction extends the hold.
        """
        return _tuition(self._request("POST", f"/internal/tuitions/{tuition_id}/reserve", {"transaction_id": txn_id}))

    def commit(self, tuition_id: str, txn_id: str) -> None:
        """Mark-paid: RESERVED by this transaction -> PAID. 409 if this transaction no longer holds it.
        """
        self._request("POST", f"/internal/tuitions/{tuition_id}/commit", {"transaction_id": txn_id})

    def release(self, tuition_id: str, txn_id: str) -> bool:
        """Undo `reserve` (back to UNPAID). False = nothing to release (hold gone or not ours).
        """
        return bool(self._request("POST", f"/internal/tuitions/{tuition_id}/release",
                                  {"transaction_id": txn_id}).get("released"))


def _tuition(d: dict) -> Tuition:
    return Tuition(d["tuition_id"], d["student_id"], d.get("student_name", ""), d.get("term", ""),
                   Decimal(str(d["amount"])), d["status"])
