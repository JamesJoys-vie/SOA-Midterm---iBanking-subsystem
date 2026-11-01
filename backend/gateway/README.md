# API Gateway

Owner: **Phan Huy Binh (524H0081)**. Single entry point of the backend: nginx (`web`) forwards `/api/*` here.

Per request: **allow-list route -> JWT check -> rate limit -> forward with `X-User-Id` -> access log**.

| Path | Role |
|---|---|
| `app/core/route_table.py` | `RouteTable`: (method, path) -> service. Not listed = 404 (internal endpoints are never reachable) |
| `app/security/jwt_guard.py` | `JwtGuard`: verifies `Authorization: Bearer <jwt>` (HS256, `shared/security.py`) -> user id |
| `app/middleware/rate_limiter.py` | `RateLimiter`: Redis fixed window, 429 + `Retry-After` |
| `app/proxy/reverse_proxy.py` | `ReverseProxy`: forwards with httpx, drops client `X-User-Id` / `Authorization`, 502 if a service is down |
| `app/main.py` | `create_app()` wires the pipeline; adds `X-Request-Id` and one log line per request |

Routes: `POST /auth/login` (public) and `GET /users/me`, `GET /accounts/me`, `GET /history` -> user-service;
`GET /tuitions/{mssv}` -> tuition-service; `/transactions...` -> payment-service.
Limits per minute: login 10 / IP, create transaction 20, verify-otp 10, resend-otp 5 / user (`RATE_LIMIT_MULTIPLIER`).

```
cd backend/gateway
pip install -r ../requirements.txt pytest fakeredis
python -m pytest -q tests
```
