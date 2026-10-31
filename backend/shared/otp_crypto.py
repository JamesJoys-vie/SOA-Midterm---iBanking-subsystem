"""Encrypts the OTP inside the `otp.requested` event, so the stream, Redis' AOF file and dead letters only hold
ciphertext. Only otp-service (encrypts) and notification-service (decrypts) get OTP_EVENT_KEY; every other service
on the shared Redis sees an opaque token.

Fernet = AES-128-CBC + HMAC-SHA256 with a timestamp. The token carries {otp, transaction_id}: decrypting checks the
transaction id, so a token copied into another transaction's event is rejected.
Generate a key:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import json
import time

from cryptography.fernet import Fernet, InvalidToken


class OtpTokenError(Exception):
    """Wrong key, tampered token, or a token issued for another transaction."""


class OtpTokenExpired(Exception):
    """Valid token, but older than the OTP lifetime: the code can no longer be used."""


def validate_key(key: str) -> str:
    """Raises ValueError unless `key` is a Fernet key (32 url-safe base64 bytes); used by the settings classes."""
    Fernet(key)
    return key


class OtpCipher:
    def __init__(self, key: str):
        self._fernet = Fernet(key)

    def encrypt(self, transaction_id: str, code: str) -> str:
        return self._fernet.encrypt(json.dumps({"otp": code, "transaction_id": transaction_id}).encode()).decode()

    def decrypt(self, token: str, transaction_id: str, max_age_s: int) -> str:
        """-> the plain code. Raises OtpTokenExpired / OtpTokenError."""
        try:
            issued_at = self._fernet.extract_timestamp(token.encode())  # checks the signature first
            if time.time() - issued_at >= max_age_s:
                raise OtpTokenExpired(f"token is {time.time() - issued_at:.0f} s old")
            data = json.loads(self._fernet.decrypt(token.encode()))
        except (InvalidToken, ValueError, TypeError, AttributeError) as e:
            raise OtpTokenError("cannot decrypt the OTP token") from e
        if data.get("transaction_id") != transaction_id:
            raise OtpTokenError("token was issued for another transaction")
        return data["otp"]
