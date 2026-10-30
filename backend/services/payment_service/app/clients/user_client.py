"""Calls to user-service (owner of users, accounts and balances)."""
from dataclasses import dataclass
from decimal import Decimal
from app.clients.base import ServiceClient


@dataclass(frozen=True)
class Payer:
    user_id: str
    full_name: str
    email: str
    phone: str
    balance: Decimal


class UserClient(ServiceClient):
    name = "user-service"

    def get_payer(self, user_id: str) -> Payer:
        """Payer info + current balance, read on the server (client-sent payer data is never used).
        """
        d = self._request("GET", f"/internal/users/{user_id}")
        return Payer(d["id"], d["full_name"], d["email"], d.get("phone", ""), Decimal(str(d.get("balance", "0"))))

    def debit(self, user_id: str, amount: Decimal, txn_id: str) -> Decimal:
        """Conditional debit (balance >= amount), at most once per txn_id -> balance after.
        """
        d = self._request("POST", "/internal/accounts/debit",
                          {"user_id": user_id, "amount": str(amount), "transaction_id": txn_id})
        return Decimal(str(d["balance_after"]))

    def refund(self, user_id: str, amount: Decimal, txn_id: str) -> Decimal:
        """Compensation of `debit` (money back), at most once per txn_id -> balance after.
        """
        d = self._request("POST", "/internal/accounts/credit",
                          {"user_id": user_id, "amount": str(amount), "transaction_id": txn_id})
        return Decimal(str(d["balance_after"]))

    def record_history(self, user_id: str, student_id: str, tuition_id: str, amount: Decimal, status: str,
                       failure_reason: str | None) -> None:
        """Write the final result into the user's history. Not idempotent there -> no retry.
        """
        self._request("POST", "/internal/history",
                      {"user_id": user_id, "student_id": student_id, "tuition_id": tuition_id,
                       "amount": str(amount), "status": status, "failure_reason": failure_reason}, retry=False)
