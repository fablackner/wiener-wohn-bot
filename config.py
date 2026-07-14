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
URL = 'https://wohnungssuche.wohnberatung-wien.at/?page=suche&art=gefoerdert'
SENT_IDS_FILE = os.getenv('SENT_IDS_FILE', 'sent_apartments.txt')
DETAIL_DELAY = float(os.getenv('DETAIL_DELAY', '0.3'))

# Email settings
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_RECIPIENTS = [addr.strip() for addr in os.getenv('EMAIL_RECIPIENTS', '').split(',') if addr.strip()]
SMTP_SERVER = os.getenv('SMTP_SERVER', 'mail.gmx.net')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

# Gemini / AI settings
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-flash-latest')
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

# Logging
LOG_FILE = os.getenv('LOG_FILE', 'logfile.log')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Feature flags
ENABLE_AI = os.getenv('ENABLE_AI', '1') == '1'
AUTOMATIC_APPLICATION = os.getenv('AUTOMATIC_APPLICATION', '0') == '1'

# Automatic application criteria. An apartment must satisfy ALL of these
# before an application is submitted.
AUTO_MAX_DISTANCE_M = int(os.getenv('AUTO_MAX_DISTANCE_M', '3000'))
AUTO_MIN_SIZE_SQM = float(os.getenv('AUTO_MIN_SIZE_SQM', '74'))
AUTO_MIN_FLOOR_LEVEL = int(os.getenv('AUTO_MIN_FLOOR_LEVEL', '3'))

# Optional: If set, cancel an existing application for this apartment ID
# before submitting a new automatic application.
CANCEL_APPLICATION_APT_ID = os.getenv('CANCEL_APPLICATION_APT_ID', '').strip()

# Cookies (optional, some pages may need a session to show full results)
WB_COOKIE_PHPSESSID = os.getenv('WB_COOKIE_PHPSESSID', '').strip()
WB_COOKIE_StickySession = os.getenv('WB_COOKIE_StickySession', '').strip()
WB_COOKIE_CC_COOKIE = os.getenv('WB_COOKIE_CC_COOKIE', '').strip()  # keep raw JSON string


def get_cookies():
    """Return a cookies dict including only values that are set.

    This keeps requests flexible: if no cookies provided, request goes without them.
    """
    cookies = {}
    if WB_COOKIE_PHPSESSID:
        cookies['PHPSESSID'] = WB_COOKIE_PHPSESSID
    if WB_COOKIE_StickySession:
        cookies['StickySession'] = WB_COOKIE_StickySession
    if WB_COOKIE_CC_COOKIE:
        cookies['cc_cookie'] = WB_COOKIE_CC_COOKIE
    return cookies


def validate_config():
    missing = []
    if not EMAIL_SENDER:
        missing.append('EMAIL_SENDER')
    if not EMAIL_PASSWORD:
        missing.append('EMAIL_PASSWORD')
    if not EMAIL_RECIPIENTS:
        missing.append('EMAIL_RECIPIENTS')
    if missing:
        raise ValueError(f"Missing required email configuration values: {', '.join(missing)}")
    # Gemini key optional if AI disabled
    if ENABLE_AI and not GEMINI_API_KEY:
        raise ValueError('ENABLE_AI=1 but GEMINI_API_KEY is not set')

__all__ = [
    'URL','SENT_IDS_FILE','DETAIL_DELAY','EMAIL_SENDER','EMAIL_PASSWORD','EMAIL_RECIPIENTS',
    'SMTP_SERVER','SMTP_PORT','GEMINI_API_KEY','GEMINI_MODEL','APT_EVAL_BASE_PROMPT','ENABLE_AI',
    'AUTOMATIC_APPLICATION','AUTO_MAX_DISTANCE_M',
    'AUTO_MIN_SIZE_SQM','AUTO_MIN_FLOOR_LEVEL','CANCEL_APPLICATION_APT_ID','LOG_FILE','LOG_LEVEL',
    'validate_config','get_cookies','COORD_REF','REF_LAT','REF_LON'
]
