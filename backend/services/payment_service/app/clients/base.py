"""Base HTTP client for service-to-service calls (internal network, no JWT).

Two failure kinds, because the saga reacts differently:
  UpstreamRejected    -> the service answered 4xx: a clear "no" (e.g. 409 tuition held, 422 balance too low)
  UpstreamUnavailable -> timeout / 5xx: the outcome is UNKNOWN (the call may have been applied)
"""
import logging
import time
import httpx

log = logging.getLogger("payment.clients")


class UpstreamRejected(Exception):
    def __init__(self, service: str, status_code: int, detail: str, headers: dict | None = None):
        super().__init__(f"{service} -> {status_code}: {detail}")
        self.service, self.status_code, self.detail, self.headers = service, status_code, detail, headers or {}


class UpstreamUnavailable(Exception):
    pass


class ServiceClient:
    name = "service"

    def __init__(self, base_url: str, timeout_s: float = 5.0, retries: int = 2,
                 transport: httpx.BaseTransport | None = None):
        self.retries = retries
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)

    def _request(self, method: str, path: str, json: dict | None = None, retry: bool = True) -> dict:
        """Send one request. Retries only when `retry` is True (the endpoint must be idempotent).
        """
        attempts = self.retries + 1 if retry else 1
        last_error = "no attempt"
        for attempt in range(attempts):
            if attempt:
                time.sleep(0.2 * attempt)  # small linear backoff
            try:
                res = self._http.request(method, path, json=json)
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {e}"
                continue
            if res.status_code >= 500:
                last_error = f"HTTP {res.status_code}"
                continue
            if res.status_code >= 400:
                raise UpstreamRejected(self.name, res.status_code, _detail(res), dict(res.headers))
            return res.json()
        log.warning("%s %s %s unavailable after %d attempt(s): %s", self.name, method, path, attempts, last_error)
        raise UpstreamUnavailable(f"{self.name} is unavailable ({last_error})")


def _detail(res: httpx.Response) -> str:
    try:
        detail = res.json().get("detail")
    except ValueError:
        return res.text or res.reason_phrase
    if isinstance(detail, list):  # FastAPI validation error list
        return detail[0].get("msg", "Invalid request") if detail else "Invalid request"
    return str(detail)
