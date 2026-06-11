"""Check Nightjet ticket availability for a given date and email an alert.

The Nightjet booking API protects its connection search behind a SHA-256
proof-of-work challenge (Altcha-style): fetch a challenge, brute-force the
number whose hash matches, and pass the solved challenge as a query param.

Configuration is via environment variables:
    DATE_TO_CHECK        travel date, YYYY-MM-DD (required)
    FROM_STATION         EVA number of departure station (default 8400058, Amsterdam C)
    TO_STATION           EVA number of arrival station (default 8100108, Innsbruck Hbf)
    GMAIL_ADDRESS        Gmail address used to send mail
    GMAIL_APP_PASSWORD   Gmail app password (https://myaccount.google.com/apppasswords)
    RECIPIENT_EMAIL      where to send alerts (default: GMAIL_ADDRESS)
    HEARTBEAT_WEEKDAY    weekday (0=Mon .. 6=Sun) to send an "I'm alive" email,
                         "off" to disable (default 6)
"""

import base64
import hashlib
import json
import logging
import os
import smtplib
import sys
from datetime import date, datetime
from email.mime.text import MIMEText

import requests

BASE_URL = "https://www.nightjet.com/nj-booking-ocp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.nightjet.com/",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def solve_challenge(challenge: dict) -> str:
    """Brute-force the proof-of-work and return the base64url captcha param."""
    target = challenge["challenge"]
    salt = challenge["salt"]
    for number in range(challenge.get("maxnumber", 1_000_000) + 1):
        if hashlib.sha256((salt + str(number)).encode()).hexdigest() == target:
            solved = {
                "algorithm": challenge["algorithm"],
                "challenge": target,
                "number": number,
                "salt": salt,
                "signature": challenge["signature"],
            }
            return base64.urlsafe_b64encode(json.dumps(solved).encode()).decode()
    raise RuntimeError("Could not solve proof-of-work challenge")


def fetch_connections(from_station: str, to_station: str, travel_date: str) -> list:
    """Return the list of connections for the given route and date."""
    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.post(f"{BASE_URL}/init/start", json={"lang": "en"}, timeout=30)
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = session.get(
        f"{BASE_URL}/captcha/challenge/connection",
        params={"from": from_station, "to": to_station},
        headers={"X-Token": token},
        timeout=30,
    )
    resp.raise_for_status()
    captcha = solve_challenge(resp.json())

    resp = session.get(
        f"{BASE_URL}/connection/{from_station}/{to_station}/{travel_date}",
        params={"captcha": captcha},
        headers={"x-token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("connections") or []


def send_email(subject: str, body: str) -> None:
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        raise RuntimeError(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set - cannot send email"
        )
    recipient = os.environ.get("RECIPIENT_EMAIL") or sender

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)
    log.info("Email sent to %s: %s", recipient, subject)


def is_heartbeat_day(today: date) -> bool:
    weekday = os.environ.get("HEARTBEAT_WEEKDAY") or "6"
    return weekday.isdigit() and today.weekday() == int(weekday)


def validate_date(date_str: str) -> date:
    travel_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    if travel_date < date.today():
        raise ValueError(
            f"DATE_TO_CHECK ({date_str}) is in the past - update the repo variable"
        )
    return travel_date


def main() -> None:
    date_to_check = os.environ.get("DATE_TO_CHECK")
    if not date_to_check:
        raise RuntimeError("DATE_TO_CHECK is not set")
    validate_date(date_to_check)

    # unset GitHub repo variables arrive as empty strings, so `or` not get-default
    from_station = os.environ.get("FROM_STATION") or "8400058"
    to_station = os.environ.get("TO_STATION") or "8100108"

    connections = fetch_connections(from_station, to_station, date_to_check)
    log.info("Found %d connection(s) for %s", len(connections), date_to_check)

    if connections:
        send_email(
            subject=f"🚂 Nightjet tickets available for {date_to_check}",
            body=(
                f"{len(connections)} connection(s) found for {date_to_check} "
                f"({from_station} -> {to_station}).\n\n"
                "Book now: https://www.nightjet.com/\n\n"
                "Remember to update or disable the checker once you have booked."
            ),
        )
    elif is_heartbeat_day(date.today()):
        send_email(
            subject="Nightjet checker heartbeat",
            body=(
                f"Still alive and checking {date_to_check} "
                f"({from_station} -> {to_station}). No tickets yet."
            ),
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Ticket check failed")
        sys.exit(1)
