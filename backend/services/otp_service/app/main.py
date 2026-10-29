import logging
from fastapi import FastAPI
from app.api.routes import router, test_router
from app.core.config import settings

app = FastAPI(title="OTP Service", version="0.1.0")
app.include_router(router)
if settings.otp_test_echo:
    logging.getLogger("otp").warning("OTP_TEST_ECHO is ON: plain OTPs are readable via /internal/test/otp. Load tests only!")
    app.include_router(test_router)


@app.get("/health")
async def health():  # async: answered by the event loop even when the threadpool is saturated
    return {"status": "ok", "service": "otp-service"}
