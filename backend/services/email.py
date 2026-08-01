from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from backend.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    def send(self, recipient: str, subject: str, text: str) -> None:
        if settings.email_backend == "console":
            if settings.is_production:
                raise RuntimeError("Console email backend is forbidden in production")
            logger.info("Development email to %s: %s\n%s", recipient, subject, text)
            return
        if settings.email_backend != "smtp":
            raise RuntimeError("Unsupported email backend")
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


sender = EmailSender()


def send_verification_email(email: str, token: str) -> None:
    link = f"{settings.public_base_url}/verify-email?token={token}"
    sender.send(email, "Подтвердите email Axel One", f"Подтвердите email:\n{link}\nСсылка ограничена по времени.")


def send_password_reset_email(email: str, token: str) -> None:
    link = f"{settings.public_base_url}/reset-password?token={token}"
    sender.send(email, "Сброс пароля Axel One", f"Задайте новый пароль:\n{link}\nЕсли запрос был не ваш, ничего не делайте.")
