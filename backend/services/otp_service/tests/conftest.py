"""app.core.config needs these at import time; the API tests use db 15 and a throwaway key."""
import os
from cryptography.fernet import Fernet

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("OTP_EVENT_KEY", Fernet.generate_key().decode())
