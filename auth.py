"""Login module for wiener-wohn-bot.

meinwohnticket.wien uses the City of Vienna's SAML login ("Stadt Wien Konto",
mein.wien.gv.at). An unauthenticated request to the site answers with a small
page that redirects (via JavaScript) to the identity provider's login form.
:func:`login` walks through that flow like a browser would:

    1) follow JavaScript redirects (``window.location = "..."``)
    2) fill in and submit the username/password form
    3) submit the auto-posting SAML forms back to meinwohnticket.wien

All cookies end up in the given ``requests.Session``.
"""
from __future__ import annotations
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import BASE_URL, WB_USERNAME, WB_PASSWORD

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
# Any API endpoint redirects to the login flow when not logged in
LOGIN_ENTRY_URL = f"{BASE_URL}/api/was/graphql"
MAX_STEPS = 15

_JS_REDIRECT = re.compile(r"window\.location(?:\.href)?\s*=\s*[\"']([^\"']+)[\"']")


class LoginError(RuntimeError):
    """Raised when logging in to meinwohnticket.wien fails."""


def make_session() -> requests.Session:
    """Return a session that retries GET requests on temporary server errors (502/503/504).

    POSTs (login form, applications) are never retried, so nothing is sent twice.
    """
    retry = Retry(
        total=3,
        backoff_factor=2,  # retry at once, then after 4s and 8s
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,  # hand back the last response, so raise_for_status() reports it
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _form_fields(form) -> dict[str, str]:
    """Return name -> value for all named <input> fields of a form."""
    return {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}


def _auto_submit_form(soup: BeautifulSoup):
    """Return a form that a browser would submit automatically (e.g. SAMLResponse), if any."""
    for form in soup.find_all("form"):
        inputs = [i for i in form.find_all("input") if i.get("name")]
        if form.get("action") and inputs and all(i.get("type", "text").lower() == "hidden" for i in inputs):
            return form
    return None


def login(session: requests.Session) -> None:
    """Log in with ``WB_USERNAME`` / ``WB_PASSWORD``, storing the session cookies in ``session``.

    Raises:
        LoginError: if credentials are missing, rejected, or the flow ends unexpectedly.
    """
    if not (WB_USERNAME and WB_PASSWORD):
        raise LoginError("WB_USERNAME and WB_PASSWORD must be set in .env")
    session.headers.setdefault("User-Agent", USER_AGENT)
    logging.info("Logging in to %s ...", BASE_URL)

    response = session.get(LOGIN_ENTRY_URL, timeout=30)
    credentials_sent = False
    for _ in range(MAX_STEPS):
        response.raise_for_status()
        if "json" in response.headers.get("Content-Type", ""):
            break  # landed on the API -> logged in
        soup = BeautifulSoup(response.text, "html.parser")

        uid_field = soup.find("input", attrs={"name": "auth_uid"})
        if uid_field is not None:
            if credentials_sent:
                error = soup.find(id="fehler")
                reason = error.get_text(" ", strip=True) if error else ""
                raise LoginError(f"Login rejected by mein.wien.gv.at: {reason or 'unknown reason'}")
            form = uid_field.find_parent("form")
            data = _form_fields(form)
            data.update({
                "auth_uid": WB_USERNAME,
                "auth_pwd": WB_PASSWORD,
                # Set by JavaScript in the browser
                "stdportal_TsOriginalRequestUrl": response.url,
                "Senden": "",
            })
            response = session.post(urljoin(response.url, form.get("action") or ""), data=data, timeout=30)
            credentials_sent = True
            continue

        form = _auto_submit_form(soup)
        if form is not None:
            response = session.post(urljoin(response.url, form["action"]), data=_form_fields(form), timeout=30)
            continue

        match = _JS_REDIRECT.search(response.text)
        if match:
            response = session.get(urljoin(response.url, match.group(1)), timeout=30)
            continue
        break

    if not credentials_sent:
        raise LoginError(f"Login form not found (ended at {response.url}); the site may have changed")
    logging.info("Login finished at %s", response.url)


__all__ = ["login", "LoginError", "USER_AGENT", "make_session"]
