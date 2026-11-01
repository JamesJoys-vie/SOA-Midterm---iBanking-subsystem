"""Fixed-window rate limit on Redis: INCR rl:<route>:<who>:<minute>, key expires with the window.
Shared by all gateway replicas because the counter lives in Redis.
"""
import logging
import time
import redis

log = logging.getLogger("gateway.rate_limit")


class RateLimiter:
    def __init__(self, r: redis.Redis, multiplier: int = 1, window_s: int = 60):
        self.r, self.multiplier, self.window_s = r, max(multiplier, 1), window_s

    def hit(self, bucket: str, identity: str, limit: int) -> int:
        """Count one request. 0 = allowed, otherwise seconds until the window resets (Retry-After).
        """
        now = time.time()
        key = f"rl:{bucket}:{identity}:{int(now // self.window_s)}"
        try:
            with self.r.pipeline() as p:
                count, _ = p.incr(key).expire(key, self.window_s + 1).execute()
        except redis.RedisError:
            log.warning("Redis unavailable, rate limit skipped for %s", bucket)  # fail open: availability first
            return 0
        if count > limit * self.multiplier:
            return max(int(self.window_s - now % self.window_s), 1)
        return 0
