"""Dispatch notifications to the enabled channels (Telegram and/or email)."""
from __future__ import annotations

from config import ENABLE_EMAIL, ENABLE_TELEGRAM
from emailer import send_email, send_error
from telegram_client import send_telegram


def notify(subject: str, body: str) -> None:
    """Send an apartment notification to all enabled channels."""
    if ENABLE_TELEGRAM:
        send_telegram(f"{subject}\n\n{body}")
    if ENABLE_EMAIL:
        send_email(subject, body)


def notify_error(error_message: str) -> None:
    """Send an error notification to all enabled channels."""
    if ENABLE_TELEGRAM:
        send_telegram(f"⚠️ wiener-wohn-bot Fehler:\n{error_message}")
    if ENABLE_EMAIL:
        send_error(error_message)


__all__ = ["notify", "notify_error"]
