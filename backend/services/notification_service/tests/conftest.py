"""Tests run against a real Redis (streams, consumer groups, XAUTOCLAIM). Uses db 15 and flushes it.
Run inside the compose network (tests are not baked into the image, so mount them):
    docker compose run --rm --no-deps --entrypoint sh -e REDIS_URL=redis://redis:6379/15
        -v ./backend/services/notification_service/tests:/srv/service/tests notification-service
        -c "pip install -q pytest && python -m pytest -q tests"
"""
import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # app.core.config needs it at import time

import pytest
import redis


@pytest.fixture
def r():
    client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not reachable")
    assert client.connection_pool.connection_kwargs.get("db") == 15, "tests flush the db: point REDIS_URL at db 15"
    client.flushdb()
    yield client
    client.flushdb()
