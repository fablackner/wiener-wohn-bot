"""wiener-wohn-bot CLI: single-shot run that processes only new apartments.

This utility is designed for cron. It will:
  1) Fetch current apartment listing (IDs only)
  2) Compare with the sent IDs file
  3) For each NEW ID: fetch detail HTML, build summary, evaluate AI score, send email
  4) Append processed IDs to the sent IDs file

Exit codes:
  0 = Success (even if no new apartments)
  1 = Configuration invalid
  2 = Unhandled runtime error
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import List, Optional

from config import (
    LOG_FILE,
    LOG_LEVEL,
    SENT_IDS_FILE,
    DETAIL_DELAY,
    validate_config,
    AUTOMATIC_APPLICATION,
    AUTO_MAX_DISTANCE_M,
    AUTO_MIN_SIZE_SQM,
    AUTO_MIN_FLOOR_LEVEL,
    CANCEL_APPLICATION_APT_ID,
    get_cookies,
)
from scraper import (
    fetch_apartments,
    fetch_apartment_detail,
    parse_apartment_detail_html,
    DEFAULT_HEADERS,
)
from summary import (
    build_apartment_summary,
    distance_from_reference,
)
from ai_client import evaluate_full_email
from emailer import send_email, send_error
import requests


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def load_sent_ids(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    try:
        return {line.strip() for line in p.read_text().splitlines() if line.strip()}
    except Exception:
        logging.warning("Could not read sent IDs file: %s", path)
        return set()


def append_sent_ids(path: str | Path, new_ids: List[str]) -> None:
    if not new_ids:
        return
    try:
        with Path(path).open('a') as f:
            for _id in new_ids:
                f.write(_id + '\n')
    except Exception as e:  # pragma: no cover
        logging.error("Failed to append sent IDs: %s", e)


def build_email_body(
    absolute_url: str,
    parsed: dict,
    *,
    summary_dict: Optional[dict[str, str]] = None,
    distance_m: Optional[int] = None,
) -> str:
    """Return the email body for an apartment.

    Includes URL, location URL and distance (if available), followed by the
    summary fields (Address as a standalone line). Raw coordinates and the
    internal apartment ID are intentionally omitted.
    """
    summary_dict = summary_dict or build_apartment_summary(parsed)
    location_url = parsed.get('location') or ''
    dist = distance_m if distance_m is not None else (distance_from_reference(location_url) if location_url else None)

    lines: List[str] = []
    lines.append(f"URL: {absolute_url}")
    if location_url:
        lines.append(f"Location URL: {location_url}")
    if dist is not None:
        lines.append(f"Distance to Reference (m): {dist}")
    for k, v in summary_dict.items():
        if k in ('Map',):
            continue
        if k == 'Address':
            lines.append(v)
        else:
            lines.append(f"{k}: {v}")
    return '\n'.join(lines) + '\n'


def _parse_float_from_text(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"[-+]?\d[\d.,]*", value)
    if not match:
        return None
    number = match.group().replace('\xa0', '').replace(' ', '')
    if ',' in number:
        number = number.replace('.', '').replace(',', '.')
    try:
        return float(number)
    except ValueError:
        return None


def _parse_floor_level(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"\d+", value)
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def process_new_once(
    *,
    state_file: str | Path,
    detail_delay: float,
    dry_run: bool,
) -> int:
    """Process newly discovered apartments exactly once.

    Returns the number of new apartments processed (emailed or previewed).
    """
    # Reuse a single HTTP session for consistent cookies/headers
    session = requests.Session()
    # Fetch listing with IDs only for speed
    apartments = fetch_apartments(fetch_details=False, session=session)
    id_to_apartment = {a.apt_id: a for a in apartments}

    sent_ids = load_sent_ids(state_file)
    new_ids = [apt_id for apt_id in id_to_apartment if apt_id not in sent_ids]

    if not new_ids:
        logging.info("No new apartments to process.")
        return 0

    processed: List[str] = []
    cancel_attempted = False  # ensure we cancel at most once per run
    for apt_id in new_ids:
        apt = id_to_apartment[apt_id]
        if not fetch_apartment_detail(apt, session=session, delay=detail_delay):
            continue
        if not apt.detail_html:
            continue
        try:
            parsed = parse_apartment_detail_html(apt.detail_html)
            summary_dict = build_apartment_summary(parsed)
            location_url = parsed.get('location') or ''
            distance_m = distance_from_reference(location_url) if location_url else None
            base_body = build_email_body(
                apt.absolute_url,
                parsed,
                summary_dict=summary_dict,
                distance_m=distance_m,
            )
            # Subject should use address instead of ID
            subj_summary = summary_dict
            address_raw = subj_summary.get('Address') or parsed.get('address') or 'Unbekannte Adresse'
            address = ' '.join(str(address_raw).split())  # collapse whitespace/newlines

            score, ai_text = evaluate_full_email(base_body)

            # Avoid duplicate score lines if AI text also includes a score header
            def _strip_leading_score(text: Optional[str]) -> str:
                if not text:
                    return ''
                lines = text.splitlines()
                if lines and lines[0].strip().lower().startswith('score'):
                    lines = lines[1:]
                return '\n'.join(lines).strip()

            ai_text_clean = _strip_leading_score(ai_text)

            if score is not None:
                head = f"SCORE: {score}"
                final_body = head + ("\n" + ai_text_clean if ai_text_clean else '') + "\n\n" + base_body
                subject = f"Wohnung {address} | Score {score}"
            else:
                final_body = (ai_text_clean + "\n\n" + base_body) if ai_text_clean else base_body
                subject = f"Wohnung {address} | Score n/a"

            if dry_run:
                print("\n--- EMAIL PREVIEW BEGIN ---")
                print(f"Subject: {subject}")
                print(final_body)
                print("--- EMAIL PREVIEW END ---\n")
                processed.append(apt_id)
            else:
                send_email(subject, final_body)
                processed.append(apt_id)
                # Conditional automatic application trigger (no-op in dry-run)
                size_text = (
                    summary_dict.get('Größe/m²')
                    or summary_dict.get('Wohnfläche')
                    or summary_dict.get('Nutzfläche')
                )
                size_sqm = _parse_float_from_text(size_text)
                floor_text = summary_dict.get('Geschoß') or summary_dict.get('Geschoss')
                floor_level = _parse_floor_level(floor_text)
                distance_ok = distance_m is not None and distance_m < AUTO_MAX_DISTANCE_M
                size_ok = size_sqm is not None and size_sqm > AUTO_MIN_SIZE_SQM
                floor_ok = floor_level is not None and floor_level >= AUTO_MIN_FLOOR_LEVEL

                if AUTOMATIC_APPLICATION:
                    if distance_ok and size_ok and floor_ok:
                        logging.info(
                            "Auto application criteria met for %s (distance=%s m, size=%.2f m², floor=%s)",
                            apt.apt_id,
                            distance_m,
                            size_sqm,
                            floor_level,
                        )
                        # If configured, first cancel an existing application for another apartment
                        if (
                            not cancel_attempted
                            and CANCEL_APPLICATION_APT_ID
                            and CANCEL_APPLICATION_APT_ID != apt.apt_id
                        ):
                            cancel_url = (
                                f"https://wohnungssuche.wohnberatung-wien.at/?page=wohnung&id={CANCEL_APPLICATION_APT_ID}&delete_confirm=true"
                            )
                            try:
                                cookies = get_cookies()
                                if not cookies:
                                    logging.warning("Cancel request configured but no cookies set; request may not be authenticated")
                                headers = dict(DEFAULT_HEADERS)
                                headers.setdefault('Upgrade-Insecure-Requests', '1')
                                # Use the canceled apartment as referer
                                headers['Referer'] = f"https://wohnungssuche.wohnberatung-wien.at/?page=wohnung&id={CANCEL_APPLICATION_APT_ID}"
                                r = session.get(cancel_url, headers=headers, cookies=cookies, timeout=30, allow_redirects=True)
                                print(
                                    f"Cancel-application GET status {r.status_code} for {CANCEL_APPLICATION_APT_ID}"
                                )
                                logging.info(
                                    "Cancel application for %s status=%s final_url=%s redirects=%d",
                                    CANCEL_APPLICATION_APT_ID, r.status_code, getattr(r, 'url', ''), len(getattr(r, 'history', []))
                                )
                                cancel_attempted = True
                                # No success heuristic; rely on status/logs only.
                            except Exception as e:  # pragma: no cover
                                cancel_attempted = True
                                logging.error("Cancel application request failed for %s: %s", CANCEL_APPLICATION_APT_ID, e)

                        apply_url = f"https://wohnungssuche.wohnberatung-wien.at/?page=wohnung&id={apt.apt_id}&anmelden_confirm=true"
                        try:
                            cookies = get_cookies()
                            if not cookies:
                                logging.warning("Auto application enabled but no cookies set; request may not be authenticated")
                            headers = dict(DEFAULT_HEADERS)
                            # Some servers check Referer/Upgrade-Insecure-Requests like browsers
                            headers.setdefault('Upgrade-Insecure-Requests', '1')
                            headers['Referer'] = apt.absolute_url
                            r = session.get(apply_url, headers=headers, cookies=cookies, timeout=30, allow_redirects=True)
                            print(f"Auto-application GET status {r.status_code} for {apt.apt_id}")
                            logging.info(
                                "Auto application for %s status=%s final_url=%s redirects=%d",
                                apt.apt_id, r.status_code, getattr(r, 'url', ''), len(getattr(r, 'history', []))
                            )
                        except Exception as e:  # pragma: no cover
                            logging.error("Auto application request failed for %s: %s", apt.apt_id, e)
                    else:
                        logging.info(
                            "Auto application skipped for %s (distance_ok=%s, size_ok=%s, floor_ok=%s, distance=%s, size=%s, floor=%s)",
                            apt.apt_id,
                            distance_ok,
                            size_ok,
                            floor_ok,
                            distance_m,
                            size_sqm,
                            floor_level,
                        )
        except Exception as e:  # pragma: no cover
            logging.error("Failed processing apartment %s: %s", apt_id, e)

    if processed and not dry_run:
        append_sent_ids(state_file, processed)

    return len(processed)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="wiener-wohn-bot CLI: process only new apartments once")
    # Only keep dry-run; all other settings come from config/.env
    p.add_argument("--dry-run", action="store_true", help="Do everything except actually send emails and write state")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    # Use LOG_LEVEL from config
    setup_logging(LOG_LEVEL)
    try:
        # If dry-run, allow missing email config (we just preview)
        if not args.dry_run:
            validate_config()
    except Exception as e:
        logging.error("Configuration invalid: %s", e)
        send_error(f"Konfiguration fehlerhaft: {e}")
        return 1

    try:
        count = process_new_once(
            state_file=SENT_IDS_FILE,
            detail_delay=DETAIL_DELAY,
            dry_run=args.dry_run,
        )
        print(f"Processed {count} new apartment(s)")
        return 0
    except Exception as e:  # pragma: no cover
        logging.error("CLI run failed: %s", e)
        if not args.dry_run:
            send_error(str(e))
        return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
