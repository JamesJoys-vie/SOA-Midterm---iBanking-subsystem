import logging
import smtplib
from email.message import EmailMessage
from app.core.config import settings

log = logging.getLogger("notification.mailer")


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_user:
        # Dev fallback: no SMTP configured in .env -> print the email to the container log instead of failing.
        log.warning("SMTP not configured; email NOT sent.\nTo: %s\nSubject: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        s.starttls()
        s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
