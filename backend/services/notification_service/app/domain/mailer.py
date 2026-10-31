import logging
import smtplib
from email.message import EmailMessage
from app.core.config import settings

log = logging.getLogger("notification.mailer")
SSL_PORT = 465  # implicit TLS from the first byte; any other port (587, 25, 2525) upgrades with STARTTLS


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_user:
        # Dev fallback: no SMTP configured in .env -> print the email to the container log instead of failing.
        log.warning("SMTP not configured; email NOT sent.\nTo: %s\nSubject: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    if settings.smtp_port == SSL_PORT:
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with smtp as s:
        if settings.smtp_port != SSL_PORT:
            s.starttls()
        s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


def is_permanent(exc: Exception) -> bool:
    """True when the server refused the recipient for good (5xx), so a retry would get the same answer.
    Auth / connection / 4xx errors stay retryable: they are usually fixed by config or time."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return bool(exc.recipients) and all(code >= 500 for code, _ in exc.recipients.values())
    return False
