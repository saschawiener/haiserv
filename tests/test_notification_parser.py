"""Unit tests for the iServ notification API JSON parser."""

from __future__ import annotations

from datetime import datetime

from custom_components.haiserv.notification import Notification, parse_notifications

BASE_URL = "https://school.iserv.de"

# Real-world response envelope, as returned by GET /iserv/user/api/notifications.
_SAMPLE_RESPONSE = """{
    "status": "success",
    "data": {
        "lastEventId": 0,
        "lastId": 1157927,
        "since": null,
        "count": 1,
        "notifications": [{
            "type": "mail",
            "id": 1157927,
            "groupId": "mail-14ce3dd3a49349bb0d25bee596d9870ab918b5b2",
            "groupTitle": "",
            "autoGrouping": false,
            "message": "E-Mail von user@demo.iserv.de",
            "groupMessage": "E-Mail von user@demo.iserv.de",
            "title": "",
            "content": "",
            "trigger": null,
            "url": "/iserv/notification/goto/1157927",
            "icon": "envelope",
            "date": "2026-07-19T18:33:24+02:00",
            "publishAt": null,
            "published": true
        }]
    }
}"""


class TestParseNotifications:
    """Tests for parse_notifications."""

    def test_parses_sample_response(self):
        notifications = parse_notifications(_SAMPLE_RESPONSE)
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification.id == 1157927
        assert notification.type == "mail"
        assert notification.message == "E-Mail von user@demo.iserv.de"
        assert notification.icon == "envelope"
        assert notification.published is True
        assert notification.date == datetime.fromisoformat(
            "2026-07-19T18:33:24+02:00"
        )

    def test_empty_title_falls_back_to_message(self):
        """iServ leaves title empty for some types (e.g. mail); use message instead."""
        notifications = parse_notifications(_SAMPLE_RESPONSE)
        assert notifications[0].title == "E-Mail von user@demo.iserv.de"

    def test_title_used_when_present(self):
        response = """{"status": "success", "data": {"notifications": [
            {"id": 1, "type": "exercise", "title": "Hausaufgabe fällig",
             "message": "Mathe bis Montag", "url": "", "icon": "", "date": null}
        ]}}"""
        notifications = parse_notifications(response)
        assert notifications[0].title == "Hausaufgabe fällig"

    def test_url_resolved_against_base_url(self):
        notifications = parse_notifications(_SAMPLE_RESPONSE, base_url=BASE_URL)
        assert (
            notifications[0].url
            == f"{BASE_URL}/iserv/notification/goto/1157927"
        )

    def test_url_left_relative_without_base_url(self):
        notifications = parse_notifications(_SAMPLE_RESPONSE)
        assert notifications[0].url == "/iserv/notification/goto/1157927"

    def test_empty_response_returns_empty_list(self):
        assert parse_notifications("") == []
        assert parse_notifications("   ") == []

    def test_malformed_json_returns_empty_list(self):
        assert parse_notifications("not json") == []

    def test_missing_notifications_key_returns_empty_list(self):
        assert parse_notifications('{"status": "success", "data": {}}') == []

    def test_non_dict_entries_skipped(self):
        response = '{"status": "success", "data": {"notifications": ["bad", 1, null]}}'
        assert parse_notifications(response) == []

    def test_entries_without_int_id_skipped(self):
        response = """{"status": "success", "data": {"notifications": [
            {"type": "mail", "message": "no id"}
        ]}}"""
        assert parse_notifications(response) == []

    def test_multiple_notifications_preserve_order(self):
        response = """{"status": "success", "data": {"notifications": [
            {"id": 1, "type": "mail", "title": "First", "message": "m1"},
            {"id": 2, "type": "exercise", "title": "Second", "message": "m2"}
        ]}}"""
        notifications = parse_notifications(response)
        assert [n.id for n in notifications] == [1, 2]

    def test_unparseable_date_returns_none(self):
        response = """{"status": "success", "data": {"notifications": [
            {"id": 1, "type": "mail", "title": "T", "message": "m", "date": "not-a-date"}
        ]}}"""
        notifications = parse_notifications(response)
        assert notifications[0].date is None

    def test_missing_published_defaults_true(self):
        response = """{"status": "success", "data": {"notifications": [
            {"id": 1, "type": "mail", "title": "T", "message": "m"}
        ]}}"""
        assert parse_notifications(response)[0].published is True


class TestNotificationDataclass:
    """Sanity checks on the Notification dataclass shape."""

    def test_construct_with_all_fields(self):
        notification = Notification(
            id=1,
            type="mail",
            title="T",
            message="m",
            url="https://example.invalid/x",
            icon="envelope",
            date=datetime(2024, 1, 1),
            published=True,
        )
        assert notification.id == 1
        assert notification.published is True
