"""SMTP connection choice (465 = implicit TLS, else STARTTLS), the dev fallback, and which errors are permanent."""
import smtplib
import pytest
from app.core.config import settings
from app.domain import mailer


class FakeSMTP:
    """Records what the mailer does instead of opening a connection."""
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, msg):
        self.sent.append(msg)


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "user")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from", "ibanking@example.com")
    return FakeSMTP.instances


@pytest.mark.parametrize("port", [587, 2525])
def test_starttls_ports(smtp, monkeypatch, port):
    monkeypatch.setattr(settings, "smtp_port", port)
    mailer.send_email("a@example.com", "Hi", "Body")
    s, = smtp
    assert type(s) is FakeSMTP and s.port == port
    assert s.calls == ["starttls", "login", "quit"]
    msg, = s.sent
    assert msg["To"] == "a@example.com" and msg["From"] == "ibanking@example.com" and msg["Subject"] == "Hi"


def test_port_465_uses_implicit_tls(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_port", 465)
    mailer.send_email("a@example.com", "Hi", "Body")
    s, = smtp
    assert type(s) is FakeSMTPSSL and s.calls == ["login", "quit"]  # no STARTTLS on an already-encrypted link


def test_no_smtp_config_logs_instead(smtp, monkeypatch, caplog):
    monkeypatch.setattr(settings, "smtp_host", "")
    mailer.send_email("a@example.com", "Hi", "Body")
    assert smtp == [] and "SMTP not configured" in caplog.text


@pytest.mark.parametrize("exc, permanent", [
    (smtplib.SMTPRecipientsRefused({"a@x": (550, b"no such user")}), True),
    (smtplib.SMTPRecipientsRefused({"a@x": (550, b"no"), "b@x": (451, b"later")}), False),
    (smtplib.SMTPRecipientsRefused({"a@x": (452, b"mailbox full")}), False),
    (smtplib.SMTPAuthenticationError(535, b"bad credentials"), False),
    (smtplib.SMTPServerDisconnected("gone"), False),
    (TimeoutError(), False),
])
def test_is_permanent(exc, permanent):
    assert mailer.is_permanent(exc) is permanent
