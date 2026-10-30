"""Forwards one request to a service and streams back its answer (status, body, headers)."""
import logging
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("gateway.proxy")

# Never forwarded: hop-by-hop headers, and identity headers only the gateway may set.
DROP_REQUEST_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade",
                        "authorization", "x-user-id"}
DROP_RESPONSE_HEADERS = {"content-length", "connection", "keep-alive", "transfer-encoding", "content-encoding"}


class ReverseProxy:
    def __init__(self, timeout_s: float = 20.0, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    async def forward(self, request: Request, upstream: str, service: str, path: str, user_id: str | None,
                      request_id: str, client_ip: str) -> Response:
        headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQUEST_HEADERS}
        headers.update({"X-Request-Id": request_id, "X-Forwarded-For": client_ip})
        if user_id:
            headers["X-User-Id"] = user_id  # the only trusted identity for services
        try:
            res = await self._client.request(request.method, upstream + path, params=request.query_params,
                                             content=await request.body(), headers=headers)
        except httpx.HTTPError as e:
            log.warning("%s %s -> %s unavailable: %s", request.method, path, service, e)
            return JSONResponse({"detail": f"{service} is unavailable, try again"}, status_code=502)
        out_headers = {k: v for k, v in res.headers.items() if k.lower() not in DROP_RESPONSE_HEADERS}
        return Response(res.content, status_code=res.status_code, headers=out_headers)

    async def close(self) -> None:
        await self._client.aclose()
