"""shared/otp_crypto: the token in `otp.requested` round-trips, and every way it can be wrong is rejected."""
import base64
import time
import pytest
from cryptography.fernet import Fernet
from shared.otp_crypto import OtpCipher, OtpTokenError, OtpTokenExpired, validate_key

CIPHER = OtpCipher(Fernet.generate_key().decode())


def test_round_trip():
    token = CIPHER.encrypt("t1", "123456")
    assert "123456" not in token
    assert CIPHER.decrypt(token, "t1", 300) == "123456"


def test_same_code_gives_a_different_token_each_time():
    assert CIPHER.encrypt("t1", "123456") != CIPHER.encrypt("t1", "123456")


def test_wrong_key():
    token = OtpCipher(Fernet.generate_key().decode()).encrypt("t1", "123456")
    with pytest.raises(OtpTokenError):
        CIPHER.decrypt(token, "t1", 300)


def test_tampered_token():
    raw = bytearray(base64.urlsafe_b64decode(CIPHER.encrypt("t1", "123456")))
    raw[30] ^= 0x01  # one bit of the ciphertext
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
    with pytest.raises(OtpTokenError):
        CIPHER.decrypt(tampered, "t1", 300)


def test_token_for_another_transaction():
    with pytest.raises(OtpTokenError, match="another transaction"):
        CIPHER.decrypt(CIPHER.encrypt("t1", "123456"), "t2", 300)


@pytest.mark.parametrize("token", ["", "garbage", None])
def test_not_a_token(token):
    with pytest.raises(OtpTokenError):
        CIPHER.decrypt(token, "t1", 300)


def test_expired_token():
    old = CIPHER._fernet.encrypt_at_time(b'{"otp": "123456", "transaction_id": "t1"}', int(time.time()) - 301)
    with pytest.raises(OtpTokenExpired):
        CIPHER.decrypt(old.decode(), "t1", 300)


@pytest.mark.parametrize("key", ["", "not-a-key", "a" * 44])
def test_validate_key_rejects(key):
    with pytest.raises(ValueError):
        validate_key(key)
