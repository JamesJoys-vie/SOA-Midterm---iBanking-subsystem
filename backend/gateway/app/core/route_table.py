"""Allow-list of the public API: (method, path) -> service. Anything not listed answers 404.

An allow-list (not "forward every /api/<prefix>") keeps internal endpoints unreachable from the browser,
e.g. POST /internal/accounts/debit or the /tuitions/{id}/reserve alias.
"""
import re
from dataclasses import dataclass, field
from app.core.config import Settings


@dataclass(frozen=True)
class ApiRoute:
    name: str
    method: str
    path: str  # regex of the path after /api
    service: str
    upstream: str
    public: bool = False  # True = no JWT needed (login only)
    limit_per_minute: int | None = None  # per user (per IP when public)
    pattern: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "pattern", re.compile(self.path))


class RouteTable:
    def __init__(self, routes: list[ApiRoute]):
        self.routes = routes

    def match(self, method: str, path: str) -> tuple[ApiRoute | None, bool]:
        """-> (route, path_known). path_known without route means wrong method (405).
        """
        same_path = [r for r in self.routes if r.pattern.fullmatch(path)]
        route = next((r for r in same_path if r.method == method), None)
        return route, bool(same_path)

    @classmethod
    def default(cls, s: Settings) -> "RouteTable":
        user, tuition, payment = s.user_service_url, s.tuition_service_url, s.payment_service_url
        txn = r"/transactions/[\w-]+"
        return cls([
            # section 1: login, profile, balance, history (user-service, Hieu)
            ApiRoute("login", "POST", r"/auth/login", "user-service", user, public=True, limit_per_minute=10),
            ApiRoute("profile", "GET", r"/users/me", "user-service", user),
            ApiRoute("account", "GET", r"/accounts/me", "user-service", user),
            ApiRoute("user-history", "GET", r"/history", "user-service", user),
            # section 2: tuition lookup (tuition-service, Hieu)
            ApiRoute("tuition", "GET", r"/tuitions/[\w-]+", "tuition-service", tuition),
            ApiRoute("tuition-query", "GET", r"/tuitions", "tuition-service", tuition),
            # sections 2-4: payment flow (payment-service, Binh)
            ApiRoute("create-transaction", "POST", r"/transactions", "payment-service", payment, limit_per_minute=20),
            ApiRoute("transactions", "GET", r"/transactions", "payment-service", payment),
            ApiRoute("transaction", "GET", txn, "payment-service", payment),
            ApiRoute("verify-otp", "POST", txn + "/verify-otp", "payment-service", payment, limit_per_minute=10),
            ApiRoute("resend-otp", "POST", txn + "/resend-otp", "payment-service", payment, limit_per_minute=5),
            ApiRoute("cancel", "POST", txn + "/cancel", "payment-service", payment),
        ])
