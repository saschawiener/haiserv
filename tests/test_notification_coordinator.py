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
    return client


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
