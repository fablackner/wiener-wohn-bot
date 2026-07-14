"""Gemini AI client module.

Provides a thin wrapper around the Google Gen AI SDK to score apartment
listings. If AI is disabled or the key is missing, returns a fallback summary.
"""
from __future__ import annotations
import logging
import re
from typing import Optional, Tuple

from config import GEMINI_API_KEY, GEMINI_MODEL, ENABLE_AI, APT_EVAL_BASE_PROMPT

try:
    from google import genai  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    genai = None  # type: ignore


def _init_client():  # lazy init
    if not ENABLE_AI:
        logging.info("AI disabled via ENABLE_AI=0")
        return None
    if not GEMINI_API_KEY:
        logging.warning("GEMINI_API_KEY not set; returning fallback summaries")
        return None
    if genai is None:
        logging.warning("google-genai not installed; returning fallback summaries")
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:  # pragma: no cover
        logging.error("Failed to initialize Gemini client: %s", e)
        return None


_client_cache = None
_client_initialized = False


def _ensure_client():
    global _client_cache, _client_initialized
    if not _client_initialized:
        _client_cache = _init_client()
        _client_initialized = True
    return _client_cache


def evaluate_full_email(email_body: str) -> Tuple[Optional[int], str]:
    """Evaluate a full apartment email body (including summary + raw fields).

    Supplies the entire email content to the model together with the base
    evaluation prompt and extracts a 0-100 score from the response.
    Returns (score, raw_model_text).
    """
    client = _ensure_client()
    if client is None:
        return None, "AI disabled"
    prompt = (
        f"{APT_EVAL_BASE_PROMPT}\n\n"  # base criteria
        "Bewerte das folgende Email-Inhalt zur Wohnung. \n"
        "Antwortformat strikt:\nSCORE: <0-100>\nSUMMARY: <eine oder zwei prägnante Sätze in Deutsch>.\n\n"
        "EMAIL-INHALT BEGINN\n" + email_body + "\nEMAIL-INHALT ENDE\n"
    )
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = getattr(resp, 'text', '') or ''
        cleaned = text.strip()
        m = re.search(r"(\b|^)\D?(100|\d{1,2})(?=\D|$)", cleaned)
        score = None
        if m:
            try:
                val = int(m.group(2))
                if 0 <= val <= 100:
                    score = val
            except ValueError:
                pass
        return score, cleaned
    except Exception as e:  # pragma: no cover
        logging.error("Full email evaluation failed: %s", e)
        return None, "AI Fehler bei Bewertung"


__all__ = ["evaluate_full_email"]
