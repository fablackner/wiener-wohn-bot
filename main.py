"""wiener-wohn-bot CLI: single-shot run that processes only new apartments.

This utility is designed for cron / GitHub Actions. It will:
  1) Log in and fetch the current apartment listing (IDs only)
  2) Compare with the sent IDs file
  3) For each NEW ID: fetch details, build summary, evaluate AI score, send notification
     (Telegram and/or email)
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
)
from scraper import (
    fetch_apartments,
    fetch_apartment_detail,
    parse_apartment_detail,
    apply_for_apartment,
    cancel_application,
)
from summary import (
    build_apartment_summary,
    distance_from_reference,
)
from ai_client import evaluate_full_email
from notifier import notify, notify_error
from auth import make_session


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        filename=LOG_FILE or None,  # empty -> stderr
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
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open('a') as f:
            for _id in new_ids:
                f.write(_id + '\n')
    except Exception as e:  # pragma: no cover
        logging.error("Failed to append sent IDs: %s", e)


def build_message_body(
    absolute_url: str,
    parsed: dict,
    *,
    summary_dict: Optional[dict[str, str]] = None,
    distance_m: Optional[int] = None,
) -> str:
    """Return the notification body for an apartment.

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
    mark_seen: bool = False,
) -> int:
    """Process newly discovered apartments exactly once.

    With ``mark_seen``, new apartments are only recorded as sent (no details,
    notifications or applications) — useful to seed the state file.

    Returns the number of new apartments processed (notified, previewed or marked).
    """
    # Reuse a single HTTP session for consistent cookies/headers
    session = make_session()
    # Fetch listing with IDs only for speed
    apartments = fetch_apartments(fetch_details=False, session=session)
    id_to_apartment = {a.apt_id: a for a in apartments}

    sent_ids = load_sent_ids(state_file)
    new_ids = [apt_id for apt_id in id_to_apartment if apt_id not in sent_ids]

    if not new_ids:
        logging.info("No new apartments to process.")
        return 0

    if mark_seen:
        if not dry_run:
            append_sent_ids(state_file, new_ids)
        return len(new_ids)

    processed: List[str] = []
    cancel_attempted = False  # ensure we cancel at most once per run
    for apt_id in new_ids:
        apt = id_to_apartment[apt_id]
        if not fetch_apartment_detail(apt, session=session, delay=detail_delay):
            continue
        if not apt.detail:
            continue
        try:
            parsed = parse_apartment_detail(apt.detail)
            summary_dict = build_apartment_summary(parsed)
            location_url = parsed.get('location') or ''
            distance_m = distance_from_reference(location_url) if location_url else None
            base_body = build_message_body(
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
                print("\n--- MESSAGE PREVIEW BEGIN ---")
                print(f"Subject: {subject}")
                print(final_body)
                print("--- MESSAGE PREVIEW END ---\n")
                processed.append(apt_id)
            else:
                notify(subject, final_body)
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
                            ok = cancel_application(CANCEL_APPLICATION_APT_ID, session=session)
                            print(f"Cancel application for {CANCEL_APPLICATION_APT_ID}: {'ok' if ok else 'FAILED'}")
                            cancel_attempted = True

                        ok = apply_for_apartment(apt.apt_id, session=session)
                        print(f"Auto application for {apt.apt_id}: {'ok' if ok else 'FAILED'}")
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
    p.add_argument("--dry-run", action="store_true", help="Do everything except actually send notifications and write state")
    p.add_argument("--mark-seen", action="store_true",
                   help="Record all currently listed apartments as already sent, without notifying or applying")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    # Use LOG_LEVEL from config
    setup_logging(LOG_LEVEL)
    try:
        # Dry-run and mark-seen send nothing, so notification settings aren't needed
        validate_config(notifications=not (args.dry_run or args.mark_seen))
    except Exception as e:
        logging.error("Configuration invalid: %s", e)
        print(f"Configuration invalid: {e}")
        notify_error(f"Konfiguration fehlerhaft: {e}")
        return 1

    try:
        count = process_new_once(
            state_file=SENT_IDS_FILE,
            detail_delay=DETAIL_DELAY,
            dry_run=args.dry_run,
            mark_seen=args.mark_seen,
        )
        print(f"{'Marked' if args.mark_seen else 'Processed'} {count} new apartment(s)")
        return 0
    except Exception as e:  # pragma: no cover
        logging.error("CLI run failed: %s", e)
        print(f"Run failed: {e}")
        if not args.dry_run:
            notify_error(str(e))
        return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
