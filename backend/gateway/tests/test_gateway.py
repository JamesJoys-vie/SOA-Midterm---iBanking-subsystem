"""Gateway with a fake Redis and a mock upstream (records what each service would receive).

Run from backend/gateway:   pip install pytest fakeredis && python -m pytest -q tests
"""
import sys
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[1]
for p in (GATEWAY_DIR, GATEWAY_DIR.parent):  # app/ and backend/ (for shared/)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from shared.security import create_access_token
from app.core.config import Settings
from app.main import create_app

SECRET = "test-secret-for-gateway-unit-tests-0123456789"


@pytest.fixture
def ctx():
    seen = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "payment-service" and request.url.path == "/down":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"service": request.url.host, "path": request.url.path,
                                         "user": request.headers.get("x-user-id")})

    settings = Settings(jwt_secret=SECRET)
    app = create_app(settings, fakeredis.FakeRedis(decode_responses=True), httpx.MockTransport(upstream))
    with TestClient(app) as client:
        yield client, seen


def auth(user="u1"):
    return {"Authorization": f"Bearer {create_access_token(user, SECRET)}"}


def test_login_is_public_and_routed_to_user_service(ctx):
    client, _ = ctx
    res = client.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert res.status_code == 200 and res.json()["service"] == "user-service"


def test_protected_route_needs_jwt(ctx):
    client, _ = ctx
    assert client.get("/api/users/me").status_code == 401
    assert client.get("/api/users/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_routing_and_user_id_from_token(ctx):
    client, _ = ctx
    assert client.get("/api/tuitions/52100001", headers=auth()).json()["service"] == "tuition-service"
    body = client.post("/api/transactions/abc/verify-otp", json={"otp": "123456"}, headers=auth("u7")).json()
    assert body == {"service": "payment-service", "path": "/transactions/abc/verify-otp", "user": "u7"}


def test_spoofed_user_id_is_replaced(ctx):
    client, seen = ctx
    client.get("/api/transactions", headers={**auth("real"), "X-User-Id": "victim"})
    assert seen[-1].headers["x-user-id"] == "real"
    assert "authorization" not in seen[-1].headers


def test_internal_and_unknown_routes_are_blocked(ctx):
    client, seen = ctx
    assert client.post("/api/internal/accounts/debit", headers=auth()).status_code == 404
    assert client.post("/api/tuitions/t1/reserve", headers=auth()).status_code == 404
    assert client.delete("/api/transactions", headers=auth()).status_code == 405
    assert seen == []


def test_rate_limit_on_resend_otp(ctx):
    client, _ = ctx
    codes = [client.post("/api/transactions/abc/resend-otp", headers=auth()).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_request_id_is_returned(ctx):
    client, _ = ctx
    assert client.get("/api/users/me", headers=auth()).headers["x-request-id"]
