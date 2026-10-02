"""Unit tests for IServNotificationCoordinator lifecycle.

Tests verify:
- Notification update interval configuration
- Session re-authentication on expiry
- Consecutive failure counter increments and resets
- Parsed notification data and base_url resolution
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeDataUpdateCoordinator:
    """Minimal stub for DataUpdateCoordinator to test coordinator logic."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeUpdateFailed(Exception):
    """Stub for homeassistant UpdateFailed exception."""


_ha_update_coord_mod = sys.modules["homeassistant.helpers.update_coordinator"]
_ha_update_coord_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
_ha_update_coord_mod.UpdateFailed = _FakeUpdateFailed

_ha_core_mod = sys.modules["homeassistant.core"]
_ha_core_mod.HomeAssistant = MagicMock

if "custom_components.haiserv.coordinator" in sys.modules:
    del sys.modules["custom_components.haiserv.coordinator"]

from custom_components.haiserv.coordinator import IServNotificationCoordinator  # noqa: E402
from custom_components.haiserv.api import AuthenticationError, CannotConnect  # noqa: E402
from custom_components.haiserv.const import DEFAULT_NOTIFICATION_UPDATE_INTERVAL  # noqa: E402

_SAMPLE_RESPONSE = """{
    "status": "success",
    "data": {
        "notifications": [
            {"id": 1, "type": "mail", "title": "", "message": "E-Mail von a@b.de",
             "url": "/iserv/notification/goto/1", "icon": "envelope", "date": null}
        ]
    }
}"""


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.authenticate = AsyncMock()
    client.fetch_notifications = AsyncMock()
    client.base_url = "https://school.iserv.de"
    # Default: no watermark persisted yet (first-ever poll).
    client.load_last_notification_id = MagicMock(return_value=None)
    client.store_last_notification_id = MagicMock()
    return client


def _response_with_ids(*ids: int) -> str:
    """Build a minimal notifications API response with the given IDs."""
    import json

    entries = [
        {
            "id": notification_id,
            "type": "mail",
            "title": "",
            "message": f"Notification {notification_id}",
            "url": "",
            "icon": "",
            "date": None,
        }
        for notification_id in ids
    ]
    return json.dumps({"status": "success", "data": {"notifications": entries}})


@pytest.fixture
def coordinator(mock_hass, mock_client):
    return IServNotificationCoordinator(mock_hass, mock_client)


class TestUpdateInterval:
    def test_update_interval_matches_constant(self, coordinator):
        expected = timedelta(minutes=DEFAULT_NOTIFICATION_UPDATE_INTERVAL)
        assert coordinator.update_interval == expected


class TestDataParsing:
    async def test_returns_parsed_notifications(self, coordinator, mock_client):
        mock_client.fetch_notifications.return_value = _SAMPLE_RESPONSE

        result = await coordinator._async_update_data()

        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].title == "E-Mail von a@b.de"

    async def test_url_resolved_with_client_base_url(self, coordinator, mock_client):
        mock_client.fetch_notifications.return_value = _SAMPLE_RESPONSE

        result = await coordinator._async_update_data()

        assert result[0].url == "https://school.iserv.de/iserv/notification/goto/1"


class TestReAuthentication:
    async def test_reauth_on_auth_error_then_success(self, coordinator, mock_client):
        mock_client.fetch_notifications.side_effect = [
            AuthenticationError("Session expired"),
            _SAMPLE_RESPONSE,
        ]
        mock_client.authenticate.return_value = True

        result = await coordinator._async_update_data()

        mock_client.authenticate.assert_called_once()
        assert mock_client.fetch_notifications.call_count == 2
        assert len(result) == 1

    async def test_reauth_failure_raises_update_failed(self, coordinator, mock_client):
        mock_client.fetch_notifications.side_effect = [
            AuthenticationError("Session expired"),
            AuthenticationError("Still expired"),
        ]
        mock_client.authenticate.return_value = True

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

    async def test_reauth_authenticate_raises_error(self, coordinator, mock_client):
        mock_client.fetch_notifications.side_effect = AuthenticationError("Session expired")
        mock_client.authenticate.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()


class TestConsecutiveFailures:
    def test_initial_failure_count_is_zero(self, coordinator):
        assert coordinator.consecutive_failures == 0

    async def test_increment_on_cannot_connect(self, coordinator, mock_client):
        mock_client.fetch_notifications.side_effect = CannotConnect("Network error")

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 1

    async def test_reset_on_success(self, coordinator, mock_client):
        mock_client.fetch_notifications.side_effect = CannotConnect("Network error")
        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 1

        mock_client.fetch_notifications.side_effect = None
        mock_client.fetch_notifications.return_value = _SAMPLE_RESPONSE

        await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 0

    async def test_warning_logged_on_cannot_connect(
        self, coordinator, mock_client, caplog
    ):
        mock_client.fetch_notifications.side_effect = CannotConnect("Connection refused")

        with caplog.at_level(logging.WARNING):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()

        assert "Failed to connect to iServ for notifications" in caplog.text
        assert "consecutive failures: 1" in caplog.text


class TestNotificationWatermark:
    """Tests for the persisted last-seen-notification-ID tracking.

    This is what lets Home Assistant detect a new notification even when the
    pending count didn't grow because an older notification was read
    directly in iServ between polls while a new one arrived.
    """

    async def test_first_poll_establishes_baseline_without_new_notifications(
        self, coordinator, mock_client
    ):
        """On the very first poll (nothing persisted yet), nothing already
        pending should be treated as newly arrived."""
        mock_client.fetch_notifications.return_value = _response_with_ids(5, 7)

        result = await coordinator._async_update_data()

        assert len(result) == 2
        assert coordinator.new_notifications == []
        assert coordinator.last_known_id == 7
        mock_client.store_last_notification_id.assert_called_once_with(7)

    async def test_higher_id_than_watermark_is_new(self, coordinator, mock_client):
        """A notification with an ID above the persisted watermark is new."""
        mock_client.load_last_notification_id.return_value = 7
        mock_client.fetch_notifications.return_value = _response_with_ids(7, 9)

        await coordinator._async_update_data()

        assert [n.id for n in coordinator.new_notifications] == [9]
        assert coordinator.last_known_id == 9
        mock_client.store_last_notification_id.assert_called_once_with(9)

    async def test_watermark_does_not_regress_when_highest_is_dismissed(
        self, coordinator, mock_client
    ):
        """Regression test for the reported bug: if the previously
        highest-numbered notification is dismissed in iServ between polls,
        last_known_id must not fall back to a lower current max."""
        mock_client.load_last_notification_id.return_value = 101
        # id 101 was read/dismissed in iServ; only a lower, already-seen one remains.
        mock_client.fetch_notifications.return_value = _response_with_ids(50)

        await coordinator._async_update_data()

        assert coordinator.last_known_id == 101
        assert coordinator.new_notifications == []
        mock_client.store_last_notification_id.assert_called_once_with(101)

    async def test_new_notification_detected_even_without_count_increase(
        self, coordinator, mock_client
    ):
        """Exact scenario reported: the pending count stays flat between
        polls (one dismissed, one new arrives), but the new one must still
        be detected."""
        mock_client.load_last_notification_id.return_value = 101
        # 101 was dismissed; 105 is new. Count (2 -> 2) is unchanged.
        mock_client.fetch_notifications.return_value = _response_with_ids(50, 105)

        await coordinator._async_update_data()

        assert [n.id for n in coordinator.new_notifications] == [105]
        assert coordinator.last_known_id == 105
        mock_client.store_last_notification_id.assert_called_once_with(105)

    async def test_no_notifications_pending_keeps_watermark(
        self, coordinator, mock_client
    ):
        """An empty feed (everything read) must not erase the watermark."""
        mock_client.load_last_notification_id.return_value = 101
        mock_client.fetch_notifications.return_value = _response_with_ids()

        result = await coordinator._async_update_data()

        assert result == []
        assert coordinator.last_known_id == 101
        assert coordinator.new_notifications == []
        mock_client.store_last_notification_id.assert_called_once_with(101)
