"""Web scraping module for wiener-wohn-bot.

Public API:
        - :class:`Apartment`: metadata + full HTML (if fetched)
        - :func:`fetch_apartments`: returns a list of Apartment objects; by default fetches each
            apartment's detail HTML so downstream code can parse freely.
        - :func:`parse_apartment_detail_html`: extracts structured fields from a detail page.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, List, Iterable, Tuple
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from config import URL, get_cookies

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en-AT;q=0.9,en;q=0.8,de;q=0.7",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
}

def _build_cookies():
    cookies = get_cookies()
    if cookies:
        logging.debug("Using %d cookie(s) for request: %s", len(cookies), list(cookies.keys()))
    else:
        logging.debug("No cookies provided; proceeding without session cookies")
    return cookies

@dataclass
class Apartment:
    """Represents a single apartment listing reference.

    Attributes:
        apt_id: The opaque ID value from the query string.
        relative_url: The relative URL as found on the search page (e.g. '/?page=wohnung&id=...').
        absolute_url: Fully qualified URL.
        detail_html: (Optional) Full HTML of the apartment detail page if fetched.
    """
    apt_id: str
    relative_url: str
    absolute_url: str
    detail_html: Optional[str] = None


def _fetch_listing_page(session: requests.Session) -> str:
    """Retrieve the raw HTML for the search results page."""
    logging.info("Fetching apartment search results page ...")
    response = session.get(URL, headers=DEFAULT_HEADERS, cookies=_build_cookies(), timeout=30)
    logging.debug("Listing page status %s", response.status_code)
    response.raise_for_status()
    return response.text


################################################################################
# Core logic: extract links & fetch details
################################################################################
_APT_LINK_REGEX = re.compile(r"^/\?page=wohnung&id=([a-fA-F0-9]{32})$")


def _extract_apartment_links(html: str, base_url: str) -> List[Apartment]:
    """Parse all unique apartment links from the search results HTML.

    The site presents multiple anchor tags that match the pattern '/?page=wohnung&id=<32hex>'.
    We de-duplicate by the extracted 32-char hex ID.
    """
    soup = BeautifulSoup(html, 'html.parser')
    apartments: Dict[str, Apartment] = {}
    for a in soup.find_all('a', href=True):
        m = _APT_LINK_REGEX.match(a['href'])
        if not m:
            continue
        apt_id = m.group(1)
        if apt_id in apartments:
            continue  # already captured
        absolute = urljoin(base_url, a['href'])
        apartments[apt_id] = Apartment(
            apt_id=apt_id,
            relative_url=a['href'],
            absolute_url=absolute,
        )
    logging.info("Extracted %d unique apartment link(s)", len(apartments))
    return list(apartments.values())


def _fetch_apartment_details(apartments: Iterable[Apartment], session: requests.Session, headers: Dict[str, str], cookies: Dict[str, str], delay: float = 0.0) -> None:
    """Populate each apartment object's ``detail_html`` in-place.

    Parameters:
        apartments: Iterable of Apartment objects to enrich.
        session: requests.Session to reuse TCP connection + cookies.
        headers: HTTP headers to send.
        cookies: Cookies for auth / session.
        delay: Optional sleep (seconds) between requests to be polite.
    """
    for idx, apt in enumerate(apartments, start=1):
        try:
            logging.debug("Fetching apartment %s (%d/%d): %s", apt.apt_id, idx, len(list(apartments)), apt.absolute_url)
            resp = session.get(apt.absolute_url, headers=headers, cookies=cookies, timeout=30)
            resp.raise_for_status()
            apt.detail_html = resp.text
        except Exception as e:  # pragma: no cover - network variability
            logging.warning("Failed to fetch detail page for %s: %s", apt.apt_id, e)
        if delay:
            time.sleep(delay)


def fetch_apartments(
    fetch_details: bool = True,
    detail_delay: float = 0.0,
    session: Optional[requests.Session] = None,
    limit: Optional[int] = None,
) -> List[Apartment]:
    """Return a list of apartment listings (with optional detail HTML).

    Args:
        fetch_details: Whether to download each apartment's detail page HTML (default True).
        detail_delay: Sleep seconds between detail fetches (politeness / throttling).
        session: Optional requests.Session to reuse.
        limit: Limit number of apartments (after de-duplication) for testing.

    Returns:
        List[Apartment]
    """
    sess = session or requests.Session()
    listing_html = _fetch_listing_page(sess)
    apartments = _extract_apartment_links(listing_html, base_url=URL)
    if not apartments and 'einloggen' in listing_html.lower():
        logging.warning(
            "The site returned its login page instead of search results; "
            "your session cookies are missing or expired. Log in at %s in your "
            "browser and update WB_COOKIE_PHPSESSID (and WB_COOKIE_StickySession) in .env.",
            URL,
        )
    if limit is not None:
        apartments = apartments[:limit]
    if fetch_details and apartments:
        logging.info("Fetching detail pages for %d apartment(s)...", len(apartments))
        _fetch_apartment_details(apartments, sess, DEFAULT_HEADERS, _build_cookies(), delay=detail_delay)
    return apartments

################################################################################
# Parsing helpers for detail_html
################################################################################

def _extract_address(soup: BeautifulSoup) -> Optional[str]:
    # Address appears in an h2 with spans for postal code, street, etc.
    h2 = soup.find('h2', class_='wbw-blue')
    if not h2:
        return None
    text = ' '.join(h2.stripped_strings)
    return text

def _extract_table_key_values(table) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not table:
        return data
    for tr in table.find_all('tr'):
        th = tr.find('th')
        td = tr.find('td')
        if not th or not td:
            continue
        key = ' '.join(th.stripped_strings)
        val = ' '.join(td.stripped_strings)
        if key:
            data[key] = val
    return data

def _extract_panel_table_by_heading(soup: BeautifulSoup, heading_text: str) -> Dict[str, str]:
    # Find a panel with a heading equal to heading_text and parse first table inside
    for panel in soup.find_all(class_='panel'):
        head = panel.find(class_='panel-heading')
        if not head:
            continue
        if heading_text.lower() in ' '.join(head.stripped_strings).lower():
            table = panel.find('table')
            return _extract_table_key_values(table)
    return {}

def _extract_zusatzinformation_text(soup: BeautifulSoup) -> Optional[str]:
    """Return free-form text inside the Zusatzinformation panel (if any)."""
    for panel in soup.find_all(class_='panel'):
        head = panel.find(class_='panel-heading')
        if not head:
            continue
        if 'zusatzinformation' in ' '.join(head.stripped_strings).lower():
            body = panel.find(class_='panel-body')
            if body:
                return ' '.join(body.stripped_strings)
    return None

def _extract_google_maps_link(soup: BeautifulSoup) -> Optional[str]:
    # The map link is inside an <a> with google.com/maps/place
    a = soup.find('a', href=re.compile(r'google.com/maps/place'))
    if a:
        return a['href']
    return None

def parse_apartment_detail_html(html: str) -> Dict[str, object]:
    """Parse an apartment detail page HTML and extract structured fields.

    Returns a dict with keys: address, basisdaten, detailinformation, zusatzinformation, location
    """
    soup = BeautifulSoup(html, 'html.parser')
    address = _extract_address(soup)
    basisdaten = _extract_panel_table_by_heading(soup, 'Basisdaten')
    detailinformation = _extract_panel_table_by_heading(soup, 'Detailinformation')
    zusatzinfo_table = _extract_panel_table_by_heading(soup, 'Zusatzinformation')
    zusatzinfo_text = _extract_zusatzinformation_text(soup)
    location = _extract_google_maps_link(soup)
    return {
        'address': address,
        'basisdaten': basisdaten,
        'detailinformation': detailinformation,
        'zusatzinformation': {**zusatzinfo_table, **({'__text': zusatzinfo_text} if zusatzinfo_text else {})},
        'location': location,
    }

__all__ = ["Apartment", "fetch_apartments", "parse_apartment_detail_html"]


def fetch_apartment_detail(apt: Apartment, session: Optional[requests.Session] = None, delay: float = 0.0) -> bool:
    """Fetch and populate the detail_html for a single Apartment if not already present.

    Returns True on success, False on failure. If detail_html is already populated,
    it is left untouched and True is returned.
    """
    if apt.detail_html is not None:
        return True
    sess = session or requests.Session()
    try:
        logging.debug("Fetching single apartment detail %s", apt.apt_id)
        resp = sess.get(apt.absolute_url, headers=DEFAULT_HEADERS, cookies=_build_cookies(), timeout=30)
        resp.raise_for_status()
        apt.detail_html = resp.text
        if delay:
            time.sleep(delay)
        return True
    except Exception as e:  # pragma: no cover (network variability)
        logging.warning("Failed to fetch single detail page for %s: %s", apt.apt_id, e)
        return False

__all__.append("fetch_apartment_detail")
