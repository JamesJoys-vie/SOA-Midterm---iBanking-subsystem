import logging
import threading
from fastapi import FastAPI
from app.core.config import settings
from app.workers.stream_consumer import start

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

app = FastAPI(title="Notification Service", version="0.1.0")
_stop = threading.Event()


@app.on_event("startup")
def start_consumer():
    start(settings.redis_url, _stop)


@app.on_event("shutdown")
def stop_consumer():
    _stop.set()


@app.get("/health")
async def health():  # async: answered by the event loop even when the threadpool is saturated
    return {"status": "ok", "service": "notification-service"}
