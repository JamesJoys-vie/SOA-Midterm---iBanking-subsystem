"""One cached Redis client per URL (thread-safe connection pool inside redis-py)."""
from functools import lru_cache
import redis

# Must stay above the blocking XREADGROUP wait in shared/events.py (block_ms=5000); redis-py 8 defaults to 5 s,
# which made the blocking read time out and crash the consumer loop.
SOCKET_TIMEOUT_S = 30


@lru_cache
def get_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=SOCKET_TIMEOUT_S, socket_connect_timeout=5)
