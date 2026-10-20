"""AI scoring client module.

Scores apartment listings with any provider that offers an OpenAI-compatible
Chat Completions API (OpenAI, Gemini, DeepInfra, OpenRouter, Ollama, ...):
the provider is chosen via OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL. If AI is
disabled or the key is missing, returns a fallback summary.
"""
from __future__ import annotations
import logging
import re
from typing import Optional, Tuple

from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, ENABLE_AI, APT_EVAL_BASE_PROMPT

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

OPENAI_TIMEOUT_S = 60.0


def _init_client():  # lazy init
    if not ENABLE_AI:
        logging.info("AI disabled via ENABLE_AI=0")
        return None
    if not OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY not set; returning fallback summaries")
        return None
    if OpenAI is None:
        logging.warning("openai not installed; returning fallback summaries")
        return None
    try:
        # Timeout per request: a hanging request must not stall the whole run
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL or None, timeout=OPENAI_TIMEOUT_S, max_retries=1)
    except Exception as e:  # pragma: no cover
        logging.error("Failed to initialize AI client: %s", e)
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
    """Evaluate a full apartment message body (including summary + raw fields).

    Supplies the entire message content to the model together with the base
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
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content if resp.choices else '') or ''
        # Some reasoning models prepend their thoughts in <think> tags
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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
