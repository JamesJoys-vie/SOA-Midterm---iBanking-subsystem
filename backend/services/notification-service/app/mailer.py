"""Sending mail over SMTP (the Mailtrap testing inbox in development)."""
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.config import Settings, settings

class MailerError(Exception):
    """The mail server could not be reached or refused the message."""

class Mailer:
    """Sends one multipart (plain text + HTML) email per call."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def send(self, to: str, subject: str, text: str, html: str) -> None:
        """Send the email, or raise MailerError."""
        msg = EmailMessage()
        msg["From"] = self.cfg.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain="ibanking.local")
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port,
                              timeout=self.cfg.smtp_timeout_seconds) as smtp:
                if self.cfg.smtp_starttls:
                    smtp.starttls()
                if self.cfg.smtp_user:
                    smtp.login(self.cfg.smtp_user, self.cfg.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailerError(str(exc)) from exc

def get_mailer() -> Mailer:
    """FastAPI dependency, so tests can swap in a fake mailer."""
    return Mailer(settings)
