"""Telegram sending module for wiener-wohn-bot (Bot API ``sendMessage``)."""
from __future__ import annotations
import logging
from typing import Sequence

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LENGTH = 4096  # Telegram's limit per message


def send_telegram(text: str, chat_ids: Sequence[str] | None = None) -> bool:
    """Send ``text`` as plain text to every chat ID. Returns True if all sends succeeded."""
    if chat_ids is None:
        chat_ids = TELEGRAM_CHAT_IDS
    if not TELEGRAM_BOT_TOKEN or not chat_ids:
        logging.warning("Telegram bot token or chat ID missing; message not sent")
        return False
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH - 3] + "..."
    ok = True
    for chat_id in chat_ids:
        try:
            response = requests.post(
                API_URL.format(token=TELEGRAM_BOT_TOKEN),
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=30,
            )
            if not response.ok:
                # Don't log the URL: it contains the bot token
                logging.error("Telegram send to %s failed: %s %s", chat_id, response.status_code, response.text[:200])
                ok = False
            else:
                logging.info("Telegram message sent to %s", chat_id)
        except requests.RequestException as e:  # pragma: no cover
            logging.error("Telegram send to %s failed: %s", chat_id, type(e).__name__)
            ok = False
    return ok


__all__ = ["send_telegram"]
