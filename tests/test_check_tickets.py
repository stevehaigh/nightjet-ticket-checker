import base64
import hashlib
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

import check_tickets


def make_challenge(number: int = 42, maxnumber: int = 100) -> dict:
    salt = "somesalt?expires=123"
    return {
        "algorithm": "SHA-256",
        "challenge": hashlib.sha256((salt + str(number)).encode()).hexdigest(),
        "maxnumber": maxnumber,
        "salt": salt,
        "signature": "sig",
    }


class TestSolveChallenge:
    def test_solves_and_encodes(self):
        result = check_tickets.solve_challenge(make_challenge(number=42))
        decoded = json.loads(base64.urlsafe_b64decode(result))
        assert decoded["number"] == 42
        assert decoded["algorithm"] == "SHA-256"
        assert decoded["signature"] == "sig"

    def test_unsolvable_raises(self):
        challenge = make_challenge(number=42, maxnumber=100)
        challenge["challenge"] = "0" * 64
        with pytest.raises(RuntimeError, match="proof-of-work"):
            check_tickets.solve_challenge(challenge)


class TestFetchConnections:
    def _mock_session(self, search_json):
        session = MagicMock()
        init_resp = MagicMock()
        init_resp.json.return_value = {"token": "jwt-token"}
        challenge_resp = MagicMock()
        challenge_resp.json.return_value = make_challenge()
        search_resp = MagicMock()
        search_resp.json.return_value = search_json
        session.post.return_value = init_resp
        session.get.side_effect = [challenge_resp, search_resp]
        return session

    def test_returns_connections(self):
        session = self._mock_session({"connections": [{"id": 1}, {"id": 2}]})
        with patch.object(check_tickets.requests, "Session", return_value=session):
            result = check_tickets.fetch_connections("8400058", "8100108", "2027-03-26")
        assert len(result) == 2

    def test_no_connections_key_returns_empty(self):
        session = self._mock_session({"njCode": "NJ-37"})
        with patch.object(check_tickets.requests, "Session", return_value=session):
            result = check_tickets.fetch_connections("8400058", "8100108", "2027-03-26")
        assert result == []

    def test_null_connections_returns_empty(self):
        session = self._mock_session({"connections": None})
        with patch.object(check_tickets.requests, "Session", return_value=session):
            result = check_tickets.fetch_connections("8400058", "8100108", "2027-03-26")
        assert result == []


class TestValidateDate:
    def test_future_date_ok(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        assert check_tickets.validate_date(future).isoformat() == future

    def test_past_date_raises(self):
        with pytest.raises(ValueError, match="in the past"):
            check_tickets.validate_date("2020-01-01")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError):
            check_tickets.validate_date("26/03/2027")


class TestHeartbeatDay:
    def test_matching_weekday(self, monkeypatch):
        monkeypatch.setenv("HEARTBEAT_WEEKDAY", "6")
        sunday = date(2026, 6, 14)
        assert check_tickets.is_heartbeat_day(sunday) is True

    def test_non_matching_weekday(self, monkeypatch):
        monkeypatch.setenv("HEARTBEAT_WEEKDAY", "6")
        thursday = date(2026, 6, 11)
        assert check_tickets.is_heartbeat_day(thursday) is False

    def test_empty_disables(self, monkeypatch):
        monkeypatch.setenv("HEARTBEAT_WEEKDAY", "")
        sunday = date(2026, 6, 14)
        assert check_tickets.is_heartbeat_day(sunday) is False


class TestMain:
    @pytest.fixture(autouse=True)
    def env(self, monkeypatch):
        future = (date.today() + timedelta(days=30)).isoformat()
        monkeypatch.setenv("DATE_TO_CHECK", future)
        monkeypatch.setenv("HEARTBEAT_WEEKDAY", "")
        self.date_to_check = future

    def test_sends_alert_when_available(self):
        with patch.object(check_tickets, "fetch_connections", return_value=[{"id": 1}]), \
             patch.object(check_tickets, "send_email") as send:
            check_tickets.main()
        send.assert_called_once()
        assert self.date_to_check in send.call_args.kwargs["subject"]

    def test_no_email_when_unavailable(self):
        with patch.object(check_tickets, "fetch_connections", return_value=[]), \
             patch.object(check_tickets, "send_email") as send:
            check_tickets.main()
        send.assert_not_called()

    def test_heartbeat_when_unavailable_on_heartbeat_day(self, monkeypatch):
        monkeypatch.setenv("HEARTBEAT_WEEKDAY", str(date.today().weekday()))
        with patch.object(check_tickets, "fetch_connections", return_value=[]), \
             patch.object(check_tickets, "send_email") as send:
            check_tickets.main()
        send.assert_called_once()
        assert "heartbeat" in send.call_args.kwargs["subject"].lower()

    def test_missing_date_raises(self, monkeypatch):
        monkeypatch.delenv("DATE_TO_CHECK")
        with pytest.raises(RuntimeError, match="DATE_TO_CHECK"):
            check_tickets.main()
