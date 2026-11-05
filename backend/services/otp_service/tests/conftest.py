"""app.core.config needs these at import time; the API tests use db 15 and a throwaway key."""
import os
from cryptography.fernet import Fernet

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["OTP_EVENT_KEY"] = os.environ.get("OTP_EVENT_KEY") or Fernet.generate_key().decode()  # also replaces ""
