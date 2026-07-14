"""Email sending module for wiener-wohn-bot."""
from __future__ import annotations
import smtplib
import logging
from email.message import EmailMessage
from typing import Sequence

from config import EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENTS, SMTP_SERVER, SMTP_PORT


def send_email(subject: str, body: str, recipients: Sequence[str] | None = None) -> None:
    if recipients is None:
        recipients = EMAIL_RECIPIENTS
    if not recipients:
        logging.warning("No recipients provided; email not sent")
        return
    email = EmailMessage()
    email["From"] = EMAIL_SENDER
    email["To"] = ", ".join(recipients)
    email["Subject"] = subject
    email.set_content(body)
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(email)
        server.quit()
        logging.info("Email '%s' sent to %s", subject, recipients)
    except Exception as e:  # pragma: no cover
        logging.error("Failed to send email '%s': %s", subject, e)


def send_error(error_message: str) -> None:
    subject = "wiener-wohn-bot Script Error"
    body = f"Es trat ein Fehler auf:\n{error_message}"
    # Send only to first recipient to reduce spam if massive failures
    recipients = EMAIL_RECIPIENTS[:1]
    send_email(subject, body, recipients)

__all__ = ["send_email", "send_error"]
