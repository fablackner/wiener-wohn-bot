"""Data access module for wiener-wohn-bot.

The site (meinwohnticket.wien) is a single-page app backed by several GraphQL
services under ``/api/<service>/graphql``. All of them require a logged-in
session cookie.

Public API:
        - :class:`Apartment`: metadata + raw detail data (if fetched)
        - :func:`fetch_apartments`: returns all apartments matching the configured search URL.
        - :func:`fetch_apartment_detail`: fetches the detail data for one apartment.
        - :func:`parse_apartment_detail`: turns the detail data into labelled, human readable fields.
        - :func:`apply_for_apartment` / :func:`cancel_application`: register / withdraw interest.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
import requests

from config import BASE_URL, SEARCH_URL, get_cookies

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en-AT;q=0.9,en;q=0.8,de;q=0.7",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
}

GEOCODER_URL = "https://data.wien.gv.at/daten/OGDAddressService.svc/GetAddressInfo"
SEARCH_PAGE_SIZE = 24


class SessionExpiredError(RuntimeError):
    """Raised when the API answers with the login page instead of JSON."""


class GraphQLError(RuntimeError):
    """Raised when the API returns GraphQL errors."""


@dataclass
class Apartment:
    """Represents a single apartment listing reference.

    Attributes:
        apt_id: The apartment's UUID (``angebotUuid``).
        absolute_url: Fully qualified URL of the apartment's page.
        detail: (Optional) Raw detail data as returned by the API if fetched.
    """
    apt_id: str
    absolute_url: str
    detail: Optional[Dict[str, Any]] = None


def _graphql(session: requests.Session, service: str, operation: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """POST a GraphQL operation to ``/api/<service>/graphql`` and return its ``data``."""
    url = f"{BASE_URL}/api/{service}/graphql"
    payload = {"operationName": operation, "variables": variables, "query": query}
    headers = dict(DEFAULT_HEADERS)
    headers["Referer"] = BASE_URL + "/"
    response = session.post(url, json=payload, headers=headers, cookies=get_cookies(), timeout=30)
    logging.debug("%s %s status %s", service, operation, response.status_code)
    response.raise_for_status()
    if "json" not in response.headers.get("Content-Type", ""):
        # Unauthenticated requests get redirected to the HTML login portal
        raise SessionExpiredError(
            "The site returned its login page instead of data; your session cookie is "
            f"missing or expired. Log in at {BASE_URL} in your browser and update "
            "WB_SESSION_COOKIE in .env."
        )
    body = response.json()
    if body.get("errors"):
        messages = "; ".join(str(e.get("message")) for e in body["errors"])
        raise GraphQLError(f"{operation}: {messages}")
    return body.get("data") or {}


################################################################################
# Search
################################################################################
_SEARCH_QUERY = """
query searchWohnungen($filter: WohnungSearchFilter, $page: Page!) {
  searchWohnungen(filter: $filter, page: $page) {
    totalHits
    hits {
      angebotUuid
    }
  }
}
"""

# URL query parameter -> filter field (list parameters are '~' separated)
_LIST_PARAMS = {
    "ausstattung": "ausstattung",
    "bezirke": "bezirke",
    "foerderungen": "foerderungen",
    "freiflaechen": "freiflaechen",
    "nutzung": "nutzung",
    "wohnungsarten": "wohnungsarten",
}
# URL query parameter -> filter field (range parameters look like 'min-max', either side optional)
_RANGE_PARAMS = {
    "anzahlRaeume": "anzahlRaeume",
    "flaeche": "qmZinsflaeche",
    "monatlicheKosten": "mieteGesamt",
    "einmaligeKosten": "einmaligeKosten",
}


def _parse_range(value: str) -> Dict[str, float]:
    low, _, high = value.partition("-")
    result: Dict[str, float] = {}
    for key, part in (("min", low), ("max", high)):
        part = part.strip()
        if part:
            number = float(part)
            result[key] = int(number) if number.is_integer() else number
    return result


def search_filter_from_url(url: str) -> Dict[str, Any]:
    """Translate a meinwohnticket.wien search URL into the API's search filter.

    Example: '.../wohnungen?anzahlRaeume=3-7&bezirke=1010~1220&flaeche=65-'
    """
    params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items() if v}
    search_filter: Dict[str, Any] = {field: [] for field in _LIST_PARAMS.values()}
    for param, field in _LIST_PARAMS.items():
        if params.get(param):
            search_filter[field] = [v for v in params[param].split("~") if v]
    for param, field in _RANGE_PARAMS.items():
        if params.get(param):
            rng = _parse_range(params[param])
            if rng:
                search_filter[field] = rng
    # Newest first, regardless of the sort order chosen in the browser
    search_filter["sort"] = {"field": "ERSTELLUNGSZEITPUNKT", "direction": "DESC"}
    return search_filter


def fetch_apartments(
    fetch_details: bool = True,
    detail_delay: float = 0.0,
    session: Optional[requests.Session] = None,
    limit: Optional[int] = None,
) -> List[Apartment]:
    """Return a list of apartments matching ``SEARCH_URL`` (with optional detail data).

    Args:
        fetch_details: Whether to download each apartment's detail data (default True).
        detail_delay: Sleep seconds between detail fetches (politeness / throttling).
        session: Optional requests.Session to reuse.
        limit: Limit number of apartments for testing.

    Returns:
        List[Apartment]
    """
    sess = session or requests.Session()
    search_filter = search_filter_from_url(SEARCH_URL)
    logging.info("Fetching apartment search results ...")
    apartments: Dict[str, Apartment] = {}
    offset = 0
    try:
        while True:
            data = _graphql(sess, "was", "searchWohnungen", _SEARCH_QUERY, {
                "filter": search_filter,
                "page": {"size": SEARCH_PAGE_SIZE, "offset": offset},
            })
            result = data.get("searchWohnungen") or {}
            hits = result.get("hits") or []
            for hit in hits:
                apt_id = hit["angebotUuid"]
                apartments.setdefault(apt_id, Apartment(apt_id=apt_id, absolute_url=f"{BASE_URL}/wohnungen/{apt_id}"))
            offset += len(hits)
            if not hits or offset >= (result.get("totalHits") or 0):
                break
    except SessionExpiredError as e:
        logging.warning("%s", e)
        return []
    logging.info("Found %d apartment(s)", len(apartments))
    result_list = list(apartments.values())
    if limit is not None:
        result_list = result_list[:limit]
    if fetch_details:
        for apt in result_list:
            fetch_apartment_detail(apt, session=sess, delay=detail_delay)
    return result_list


################################################################################
# Details
################################################################################
_DETAIL_QUERY = """
query wohnungsangebot($angebotUuid: ID!) {
  getWohnungsangebotByUuid(angebotUuid: $angebotUuid) {
    angebotsstatus
    vergabetyp
    wohnungsart
    adresse { orientierungsnummer strasse stiege tuernummer plz }
    wohnungDetails {
      bezugsdatum bezugAbSofort qmZinsflaeche foerderungsart rechtsform anzahlWohnraeume
      qmBalkonTerrasse qmLoggiaVeranda qmLoggia qmBalkon qmTerrasse qmGarten qmTerrassenanteil
      kellerabteilVorhanden qmKeller heizwaermebedarf gesamtenergieeffizienzfaktor kategorie
      zustand erstbezug raumhoehe nutzungsart baujahr stufenZurWohnung wohnungInErdgeschoss
      smartZusicherung stock mehrereWohnebenen
    }
    kosten {
      eigenmittelGesamt eigenmittelGrundkosten eigenmittelBaukosten par10Abloese nettoKaltmiete
      kaufpreis kaution wohnbaufoerderung kostenNotizen betriebskosten sonstigeKosten umsatzsteuer
      mieteGesamt erhaltungsUndVerbesserungsbeitrag parkplatzMiete gefoerderterKaufpreis
    }
    ausstattung
    stiege { projektname projektwebseite }
    bautraeger { firmenname firmenwebseite }
  }
}
"""


def fetch_apartment_detail(apt: Apartment, session: Optional[requests.Session] = None, delay: float = 0.0) -> bool:
    """Fetch and populate ``apt.detail`` if not already present.

    Returns True on success, False on failure. If detail is already populated,
    it is left untouched and True is returned.
    """
    if apt.detail is not None:
        return True
    sess = session or requests.Session()
    try:
        logging.debug("Fetching apartment detail %s", apt.apt_id)
        data = _graphql(sess, "wav", "wohnungsangebot", _DETAIL_QUERY, {"angebotUuid": apt.apt_id})
        apt.detail = data.get("getWohnungsangebotByUuid")
        if delay:
            time.sleep(delay)
        return apt.detail is not None
    except Exception as e:  # pragma: no cover (network variability)
        logging.warning("Failed to fetch detail for %s: %s", apt.apt_id, e)
        return False


def geocode_address(street_and_number: str, plz: Optional[str] = None) -> Optional[Tuple[float, float]]:
    """Return (lat, lon) for a Vienna address via the city's open-data address service."""
    try:
        resp = requests.get(GEOCODER_URL, params={"Address": street_and_number, "crs": "EPSG:4326"}, timeout=15)
        resp.raise_for_status()
        features = resp.json().get("features") or []
    except Exception as e:  # pragma: no cover (network variability)
        logging.warning("Geocoding failed for %r: %s", street_and_number, e)
        return None
    if plz:
        features = [f for f in features if f.get("properties", {}).get("PostalCode") == plz] or features
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"][:2]
    return lat, lon


def _fmt_number(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(value):,}".replace(",", ".")


def _fmt_euro(value: Any) -> Optional[str]:
    if value is None:
        return None
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_enum(value: Any) -> Optional[str]:
    if not value:
        return None
    return str(value).replace("_", " ").capitalize()


def _fmt_bool(value: Any) -> Optional[str]:
    if value is None:
        return None
    return "Ja" if value else "Nein"


def _compact(d: Dict[str, Optional[str]]) -> Dict[str, str]:
    return {k: v for k, v in d.items() if v not in (None, "")}


def parse_apartment_detail(detail: Dict[str, Any], geocode: bool = True) -> Dict[str, object]:
    """Turn raw apartment detail data into labelled, human readable fields.

    Returns a dict with keys: address, basisdaten, detailinformation, zusatzinformation, location.
    ``location`` is a Google Maps link (with coordinates when geocoding succeeds).
    """
    adresse = detail.get("adresse") or {}
    wd = detail.get("wohnungDetails") or {}
    kosten = detail.get("kosten") or {}
    ausstattung = detail.get("ausstattung") or []
    stiege = detail.get("stiege") or {}
    bautraeger = detail.get("bautraeger") or {}

    street_and_number = " ".join(p for p in (adresse.get("strasse"), adresse.get("orientierungsnummer")) if p)
    full_number = "/".join(str(p) for p in (adresse.get("orientierungsnummer"), adresse.get("stiege"), adresse.get("tuernummer")) if p)
    plz = adresse.get("plz")
    address = f"{plz or ''} Wien, {adresse.get('strasse') or ''} {full_number}".strip()

    basisdaten = _compact({
        "Größe/m²": _fmt_number(wd.get("qmZinsflaeche")),
        "Zimmer": _fmt_number(wd.get("anzahlWohnraeume")),
        "Monatl. Kosten": _fmt_euro(kosten.get("mieteGesamt")),
        "Eigenmittel": _fmt_euro(kosten.get("eigenmittelGesamt")),
        "Betriebskosten": _fmt_euro(kosten.get("betriebskosten")),
        "Nettomiete": _fmt_euro(kosten.get("nettoKaltmiete")),
        "Sonstige Kosten": _fmt_euro(kosten.get("sonstigeKosten")),
        "Umsatzsteuer": _fmt_euro(kosten.get("umsatzsteuer")),
        "EVB": _fmt_euro(kosten.get("erhaltungsUndVerbesserungsbeitrag")),
        "Kaution": _fmt_euro(kosten.get("kaution")),
        "Kaufpreis": _fmt_euro(kosten.get("kaufpreis") or kosten.get("gefoerderterKaufpreis")),
        "Ablöse §10": _fmt_euro(kosten.get("par10Abloese")) if kosten.get("par10Abloese") else None,
        "Parkplatzmiete": _fmt_euro(kosten.get("parkplatzMiete")),
    })

    freiflaechen = [
        f"{label} {_fmt_number(wd.get(key))} m²"
        for label, key in (
            ("Loggia", "qmLoggia"), ("Balkon", "qmBalkon"), ("Terrasse", "qmTerrasse"),
            ("Garten", "qmGarten"), ("Balkon/Terrasse", "qmBalkonTerrasse"),
            ("Loggia/Veranda", "qmLoggiaVeranda"), ("Terrassenanteil", "qmTerrassenanteil"),
        )
        if wd.get(key)
    ]
    if wd.get("bezugAbSofort"):
        bezug = "Ab sofort"
    else:
        bezug = wd.get("bezugsdatum")
    stock = wd.get("stock") or ("Erdgeschoß" if wd.get("wohnungInErdgeschoss") else None)

    detailinformation = _compact({
        "Bezugsdatum": bezug,
        "Wohnungstyp": _fmt_enum(detail.get("wohnungsart")),
        "Wohnungskategorie": wd.get("kategorie"),
        "Geschoß": stock,
        "Aufzug": "Ja" if "LIFT" in ausstattung else "Nein",
        "Freifläche": ", ".join(freiflaechen) or None,
        "Baujahr": _fmt_number(wd.get("baujahr")),
        "Förderungsart": _fmt_enum(wd.get("foerderungsart")),
        "Rechtsform": _fmt_enum(wd.get("rechtsform")),
        "Vergabetyp": _fmt_enum(detail.get("vergabetyp")),
        "Status": _fmt_enum(detail.get("angebotsstatus")),
        "Erstbezug": _fmt_bool(wd.get("erstbezug")),
        "Zustand": _fmt_enum(wd.get("zustand")),
        "Mehrere Wohnebenen": "Ja" if wd.get("mehrereWohnebenen") else None,
        "Stufen zur Wohnung": _fmt_number(wd.get("stufenZurWohnung")),
        "Kellerabteil": _fmt_bool(wd.get("kellerabteilVorhanden")),
        "HWB": _fmt_number(wd.get("heizwaermebedarf")),
        "fGEE": _fmt_number(wd.get("gesamtenergieeffizienzfaktor")),
        "SMART-Wohnung": "Ja" if wd.get("smartZusicherung") else None,
        "Ausstattung": ", ".join(_fmt_enum(a) for a in ausstattung) or None,
    })

    zusatzinformation = _compact({
        "Projekt": stiege.get("projektname"),
        "Projektwebseite": stiege.get("projektwebseite"),
        "Bauträger": bautraeger.get("firmenname"),
        "__text": kosten.get("kostenNotizen"),
    })

    location = None
    if street_and_number:
        coords = geocode_address(street_and_number, plz) if geocode else None
        if coords:
            location = f"https://www.google.com/maps/place/{coords[0]:.8f},{coords[1]:.8f}"
        else:
            query = f"{street_and_number}, {plz or ''} Wien".replace(" ", "+")
            location = f"https://www.google.com/maps/search/?api=1&query={query}"

    return {
        'address': address,
        'basisdaten': basisdaten,
        'detailinformation': detailinformation,
        'zusatzinformation': zusatzinformation,
        'location': location,
    }


################################################################################
# Applications (Wohnungsanmeldungen)
################################################################################
_APPLY_MUTATION = """
mutation addAnmeldung($angebotUuid: ID!) {
  addAnmeldung(angebotUuid: $angebotUuid)
}
"""

_VERGABE_QUERY = """
query vergabe($angebotUuid: ID!) {
  vergabe(angebotUuid: $angebotUuid) {
    angebotUuid
    anmeldefenster { anmeldefensterUuid }
  }
}
"""

_CANCEL_MUTATION = """
mutation removeAnmeldung($angebotUuid: ID!, $anmeldefensterUuid: ID!) {
  removeAnmeldung(angebotUuid: $angebotUuid, anmeldefensterUuid: $anmeldefensterUuid)
}
"""


def apply_for_apartment(apt_id: str, session: Optional[requests.Session] = None) -> bool:
    """Register interest (``Interesse anmelden``) for an apartment. Returns True on success."""
    sess = session or requests.Session()
    try:
        data = _graphql(sess, "vs", "addAnmeldung", _APPLY_MUTATION, {"angebotUuid": apt_id})
        logging.info("Application for %s: %s", apt_id, data.get("addAnmeldung"))
        return True
    except Exception as e:  # pragma: no cover (network variability)
        logging.error("Application for %s failed: %s", apt_id, e)
        return False


def cancel_application(apt_id: str, session: Optional[requests.Session] = None) -> bool:
    """Withdraw interest (``Interesse abmelden``) for an apartment. Returns True on success."""
    sess = session or requests.Session()
    try:
        data = _graphql(sess, "vs", "vergabe", _VERGABE_QUERY, {"angebotUuid": apt_id})
        fenster = ((data.get("vergabe") or {}).get("anmeldefenster") or {}).get("anmeldefensterUuid")
        if not fenster:
            logging.error("Cancel application for %s: no registration window found", apt_id)
            return False
        data = _graphql(sess, "vs", "removeAnmeldung", _CANCEL_MUTATION, {
            "angebotUuid": apt_id,
            "anmeldefensterUuid": fenster,
        })
        logging.info("Cancel application for %s: %s", apt_id, data.get("removeAnmeldung"))
        return True
    except Exception as e:  # pragma: no cover (network variability)
        logging.error("Cancel application for %s failed: %s", apt_id, e)
        return False


__all__ = [
    "Apartment", "SessionExpiredError", "GraphQLError", "fetch_apartments", "fetch_apartment_detail",
    "parse_apartment_detail", "search_filter_from_url", "geocode_address",
    "apply_for_apartment", "cancel_application",
]
