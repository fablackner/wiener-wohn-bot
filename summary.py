"""Apartment summary builder.

Provides `build_apartment_summary(parsed_dict)` which formats the parsed
apartment detail dictionary (as returned by `parse_apartment_detail_html`),
plus helpers to compute the distance from the configured reference point.
"""
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, OrderedDict
from config import COORD_REF
import re
import math

def build_apartment_summary(parsed: Dict[str, Any]) -> Dict[str, str]:
    """Build a rich apartment summary as an ordered key/value mapping.

    Parameters
    ----------
    parsed: dict
        Dict with keys like 'address', 'basisdaten', 'detailinformation',
        'zusatzinformation', 'location'.

    Returns
    -------
    Dict[str, str]
        Ordered mapping of attribute name -> value. Keys chosen to be
        human readable and unique. (Address kept as its own key so it can
        be rendered specially if desired.)
    """
    address = parsed.get('address') or 'Unbekannte Adresse'
    basis = parsed.get('basisdaten') or {}
    details = parsed.get('detailinformation') or {}
    zusatz = parsed.get('zusatzinformation') or {}
    location = parsed.get('location') or ''

    key_basis_fields = ['Größe/m²', 'Zimmer', 'Monatl. Kosten', 'Eigenmittel', 'Betriebskosten', 'Heizkosten']
    key_detail_fields = ['Bezugsdatum', 'Wohnungstyp', 'Wohnungskategorie', 'Geschoß', 'Aufzug', 'Freifläche', 'Baujahr']

    summary: Dict[str, str] = {}
    if location:
        summary['Map'] = location
    summary['Address'] = address

    def add_fields(fields, source):
        for f in fields:
            if f in source:
                v = source.get(f)
                if v not in (None, ''):
                    summary[f] = str(v)

    # Primary / key fields
    add_fields(key_basis_fields, basis)
    add_fields(key_detail_fields, details)

    # Remaining / secondary fields
    for f in sorted(basis.keys()):
        if f not in key_basis_fields:
            v = basis.get(f)
            if v not in (None, ''):
                summary[f] = str(v)
    for f in sorted(details.keys()):
        if f not in key_detail_fields:
            v = details.get(f)
            if v not in (None, ''):
                summary[f] = str(v)

    # Zusatz information: key/value + optional free text
    extra_text = ''
    if isinstance(zusatz, dict):
        extra_text = zusatz.get('__text') or ''
        for k in sorted(zusatz.keys()):
            if k == '__text':
                continue
            v = zusatz.get(k)
            if v not in (None, ''):
                summary[f"Zusatz {k}"] = str(v)
    if extra_text:
        trimmed = extra_text.strip()
        if len(trimmed) > 600:
            trimmed = trimmed[:600] + '...'
        summary['ExtraText'] = trimmed

    return summary

__all__ = ["build_apartment_summary"]


def extract_coordinates_from_maps_link(url: str) -> Optional[Tuple[float, float]]:
    """Extract (lat, lon) from a Google Maps place URL if present.

    Supports patterns like:
        https://www.google.com/maps/place/48.29702470,16.42380430/@48.29702470,16.42380430,17z
    We capture the first occurrence of two comma-separated floats.
    """
    if not url:
        return None
    m = re.search(r"/maps/(?:place/)?([0-9.+-]+),([0-9.+-]+)", url)
    if not m:
        return None
    try:
        lat = float(m.group(1))
        lon = float(m.group(2))
        return lat, lon
    except ValueError:
        return None

def rough_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Return a rough distance in meters (not precise great-circle) using equirectangular approximation."""
    # Convert degrees to radians
    rlat1 = math.radians(lat1); rlat2 = math.radians(lat2)
    rlon1 = math.radians(lon1); rlon2 = math.radians(lon2)
    x = (rlon2 - rlon1) * math.cos((rlat1 + rlat2) / 2.0)
    y = (rlat2 - rlat1)
    R = 6371000.0
    d = math.sqrt(x*x + y*y) * R
    return int(d)

def distance_from_reference(url: str) -> Optional[int]:
    coords = extract_coordinates_from_maps_link(url)
    if not coords:
        return None
    lat, lon = coords
    return rough_distance_m(lat, lon, COORD_REF[0], COORD_REF[1])

__all__ += ["extract_coordinates_from_maps_link", "distance_from_reference", "COORD_REF"]
