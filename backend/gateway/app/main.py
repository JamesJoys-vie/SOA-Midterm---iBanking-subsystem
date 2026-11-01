"""API Gateway: the single entry point of the backend (nginx forwards /api/* here).

Pipeline of one request:  allow-list route -> JWT check -> rate limit -> forward with X-User-Id -> log.
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from shared.redis_client import get_redis
from app.core.config import Settings
from app.core.route_table import RouteTable
from app.middleware.rate_limiter import RateLimiter
from app.proxy.reverse_proxy import ReverseProxy
from app.security.jwt_guard import AuthError, JwtGuard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("gateway")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def create_app(settings: Settings | None = None, redis_client=None, transport=None) -> FastAPI:
    """Build the app; tests pass a fake Redis and a mock HTTP transport.
    """
    settings = settings or Settings()
    routes = RouteTable.default(settings)
    guard = JwtGuard(settings.jwt_secret)
    limiter = RateLimiter(redis_client or get_redis(settings.redis_url), settings.rate_limit_multiplier)
    proxy = ReverseProxy(settings.upstream_timeout_seconds, transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await proxy.close()

    app = FastAPI(title="API Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "gateway"}

    @app.api_route("/api/{path:path}", methods=METHODS)
    async def handle(path: str, request: Request) -> Response:
        started, request_id = time.perf_counter(), request.headers.get("x-request-id") or str(uuid.uuid4())
        path, ip, user_id = "/" + path.strip("/"), client_ip(request), None
        route, path_known = routes.match(request.method, path)
        if route is None:
            response = error(405 if path_known else 404, "Method not allowed" if path_known else "Not found")
        else:
            try:
                user_id = None if route.public else guard.user_id_from(request.headers.get("authorization"))
                wait = 0
                if route.limit_per_minute:
                    wait = await run_in_threadpool(limiter.hit, route.name, user_id or ip, route.limit_per_minute)
                if wait:
                    response = error(429, "Too many requests, try again later", {"Retry-After": str(wait)})
                else:
                    response = await proxy.forward(request, route.upstream, route.service, path, user_id,
                                                   request_id, ip)
            except AuthError as e:
                response = error(401, str(e), {"WWW-Authenticate": "Bearer"})
        response.headers["X-Request-Id"] = request_id  # same id in every service log (tracing)
        log.info("%s %s -> %s %d %.0fms user=%s rid=%s", request.method, path, route.service if route else "-",
                 response.status_code, (time.perf_counter() - started) * 1000, user_id or "-", request_id)
        return response

    return app


def client_ip(request: Request) -> str:
    """Real client IP: nginx puts it in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def error(status: int, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


app = create_app()
