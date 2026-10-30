import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.db import add_busy_handler
from shared.redis_client import get_redis
from app.api.deps import make_saga
from app.api.routes import router
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import add_error_handler
from app.workers.expiry_job import ExpiryJob
from app.workers.outbox_relay import OutboxRelay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    workers = []
    if settings.run_workers:  # off in unit tests
        workers = [ExpiryJob(SessionLocal, make_saga, settings.expiry_job_interval_seconds,
                             settings.stuck_processing_seconds).start(),
                   OutboxRelay(SessionLocal, get_redis(settings.redis_url), settings.outbox_interval_seconds).start()]
    yield
    for w in workers:
        w.stop()


app = FastAPI(title="Payment Service", version="0.1.0", lifespan=lifespan)
app.include_router(router)
add_error_handler(app)
add_busy_handler(app)


@app.get("/health")
async def health():  # async: answered by the event loop even when the threadpool is saturated
    return {"status": "ok", "service": "payment-service"}
