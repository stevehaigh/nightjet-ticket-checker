# Nightjet ticket checker

Checks daily whether [Nightjet](https://www.nightjet.com/) sleeper tickets are
bookable for a given date, and emails an alert the moment they are.

Runs entirely on GitHub Actions — no servers, no cloud resources, free.

## How it works

A [scheduled workflow](.github/workflows/check-tickets.yml) runs
[`check_tickets.py`](check_tickets.py) every day at 05:37 UTC. The script:

1. Calls the Nightjet booking API's `/init/start` to get a session token.
2. Fetches and solves the SHA-256 proof-of-work challenge that protects the
   connection search (Altcha-style — brute-force a number whose salted hash
   matches the target).
3. Queries `/connection/{from}/{to}/{date}` for the configured route and date.
4. If any connections are found, sends an email via Gmail SMTP.
5. Once a week (Sunday by default) it sends a heartbeat email so you know it
   is still alive.

If the script fails (API change, bad config, expired date), the workflow run
goes red and GitHub emails you about the failure — so silence means
"checked, nothing available".

## Configuration

Set as **repository variables** (Settings → Secrets and variables → Actions →
Variables) — editable any time without touching code:

| Variable | Meaning | Default |
|---|---|---|
| `DATE_TO_CHECK` | Travel date, `YYYY-MM-DD` | required |
| `FROM_STATION` | Departure station EVA number | `8400058` (Amsterdam Centraal) |
| `TO_STATION` | Arrival station EVA number | `8100108` (Innsbruck Hbf) |
| `GMAIL_ADDRESS` | Gmail account that sends the alert | required for email |
| `RECIPIENT_EMAIL` | Where alerts go | same as `GMAIL_ADDRESS` |
| `HEARTBEAT_WEEKDAY` | Weekly "still alive" email day, `0`=Mon … `6`=Sun, empty to disable | `6` |

And one **secret**:

| Secret | Meaning |
|---|---|
| `GMAIL_APP_PASSWORD` | A [Gmail app password](https://myaccount.google.com/apppasswords) for `GMAIL_ADDRESS` |

Station EVA numbers for other routes: fetch the full station list from
`https://www.nightjet.com/nj-booking-ocp/stations/find?lang=en` and search it
for your station name.

## Disabling / re-enabling

Actions tab → "Check Nightjet tickets" → ⋯ menu → **Disable workflow**.
Re-enable the same way. (After booking your tickets, disable it or set a new
date.)

## Development

```sh
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Run a one-off check locally:

```sh
DATE_TO_CHECK=2027-03-26 python check_tickets.py
```

Without `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD` set, the check still runs but
fails loudly if it needs to send an email — handy as a dry run.
