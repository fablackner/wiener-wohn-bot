"""Configuration module for wiener-wohn-bot.

Loads environment variables (optionally from a .env file if present) and exposes
constants used across modules. Avoids hardcoding secrets in source code.
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=False)

# Scraper settings
BASE_URL = 'https://www.meinwohnticket.wien'
# Paste the URL of your filtered search from the browser here (filters are read from it)
SEARCH_URL = os.getenv('SEARCH_URL', '').strip() or f'{BASE_URL}/wohnungen'
SENT_IDS_FILE = os.getenv('SENT_IDS_FILE', 'sent_apartments.txt')
DETAIL_DELAY = float(os.getenv('DETAIL_DELAY', '0.3'))

# Login credentials for meinwohnticket.wien (Stadt Wien Konto / mein.wien.gv.at)
WB_USERNAME = os.getenv('WB_USERNAME', '').strip()
WB_PASSWORD = os.getenv('WB_PASSWORD', '')

# Telegram settings
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.getenv('TELEGRAM_CHAT_ID', '').split(',') if cid.strip()]

# Email settings
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_RECIPIENTS = [addr.strip() for addr in os.getenv('EMAIL_RECIPIENTS', '').split(',') if addr.strip()]
SMTP_SERVER = os.getenv('SMTP_SERVER', 'mail.gmx.net')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

# AI settings: any OpenAI-compatible Chat Completions API (empty base URL = OpenAI)
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', '').strip()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini').strip()
APT_EVAL_BASE_PROMPT = os.getenv('APT_EVAL_BASE_PROMPT', (
    "Bewerte die Qualität der Wohnung auf einer Skala von 0 bis 100 und gib eine kurze "
    "Begründung für deine Bewertung. Berücksichtige Größe, Zimmeranzahl, Kosten, Stockwerk, "
    "Freiflächen und die Distanz zum Referenzpunkt (kleiner ist besser)."
))

# Reference point (coordinates) for distance calculations.
# Default: Stephansplatz, Vienna city center — set REF_LAT/REF_LON to a point
# that matters to you (e.g. your workplace) in .env.
try:
    REF_LAT = float(os.getenv('REF_LAT', '48.208490'))
    REF_LON = float(os.getenv('REF_LON', '16.372080'))
except ValueError:
    REF_LAT, REF_LON = 48.208490, 16.372080
COORD_REF = (REF_LAT, REF_LON)

# Logging (an empty LOG_FILE logs to stderr, e.g. on GitHub Actions)
LOG_FILE = os.getenv('LOG_FILE', 'logfile.log')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Feature flags
ENABLE_AI = os.getenv('ENABLE_AI', '1') == '1'
ENABLE_TELEGRAM = os.getenv('ENABLE_TELEGRAM', '1') == '1'
ENABLE_EMAIL = os.getenv('ENABLE_EMAIL', '0') == '1'
AUTOMATIC_APPLICATION = os.getenv('AUTOMATIC_APPLICATION', '0') == '1'

# Automatic application criteria. An apartment must satisfy ALL of these
# before an application is submitted.
AUTO_MAX_DISTANCE_M = int(os.getenv('AUTO_MAX_DISTANCE_M', '3000'))
AUTO_MIN_SIZE_SQM = float(os.getenv('AUTO_MIN_SIZE_SQM', '74'))
AUTO_MIN_FLOOR_LEVEL = int(os.getenv('AUTO_MIN_FLOOR_LEVEL', '3'))

# Optional: If set, cancel an existing application for this apartment ID (UUID)
# before submitting a new automatic application.
CANCEL_APPLICATION_APT_ID = os.getenv('CANCEL_APPLICATION_APT_ID', '').strip()


def validate_config(*, notifications: bool = True):
    """Raise ValueError if required settings are missing.

    ``notifications=False`` skips the checks for Telegram/email (e.g. dry-run).
    """
    missing = []
    if not WB_USERNAME:
        missing.append('WB_USERNAME')
    if not WB_PASSWORD:
        missing.append('WB_PASSWORD')
    if notifications:
        if ENABLE_TELEGRAM:
            if not TELEGRAM_BOT_TOKEN:
                missing.append('TELEGRAM_BOT_TOKEN')
            if not TELEGRAM_CHAT_IDS:
                missing.append('TELEGRAM_CHAT_ID')
        if ENABLE_EMAIL:
            if not EMAIL_SENDER:
                missing.append('EMAIL_SENDER')
            if not EMAIL_PASSWORD:
                missing.append('EMAIL_PASSWORD')
            if not EMAIL_RECIPIENTS:
                missing.append('EMAIL_RECIPIENTS')
    if missing:
        raise ValueError(f"Missing required configuration values: {', '.join(missing)}")
    if notifications and not (ENABLE_TELEGRAM or ENABLE_EMAIL):
        raise ValueError('No notification channel enabled (set ENABLE_TELEGRAM=1 or ENABLE_EMAIL=1)')
    # AI key optional if AI disabled
    if ENABLE_AI and not OPENAI_API_KEY:
        raise ValueError('ENABLE_AI=1 but OPENAI_API_KEY is not set')

__all__ = [
    'BASE_URL','SEARCH_URL','SENT_IDS_FILE','DETAIL_DELAY','WB_USERNAME','WB_PASSWORD',
    'TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_IDS','EMAIL_SENDER','EMAIL_PASSWORD','EMAIL_RECIPIENTS',
    'SMTP_SERVER','SMTP_PORT','OPENAI_BASE_URL','OPENAI_API_KEY','OPENAI_MODEL','APT_EVAL_BASE_PROMPT','ENABLE_AI',
    'ENABLE_TELEGRAM','ENABLE_EMAIL','AUTOMATIC_APPLICATION','AUTO_MAX_DISTANCE_M',
    'AUTO_MIN_SIZE_SQM','AUTO_MIN_FLOOR_LEVEL','CANCEL_APPLICATION_APT_ID','LOG_FILE','LOG_LEVEL',
    'validate_config','COORD_REF','REF_LAT','REF_LON'
]
