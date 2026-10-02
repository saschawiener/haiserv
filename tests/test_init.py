"""Unit tests for async_setup_entry's graceful degradation on endpoint failure.

Verifies that a config-entry-blocking failure of the primary timetable
coordinator no longer aborts the whole integration setup (matching the
behavior already used for the next-week/parent-letter/notification
coordinators), and that the API client is wired for debug logging.

The coordinator classes themselves are replaced with lightweight stubs here
rather than relying on the real DataUpdateCoordinator-based classes, since
several other test modules in this suite repeatedly delete and reimport
``custom_components.haiserv.coordinator`` with their own fake base class —
depending on that shared, order-sensitive module state would make this test
fragile to collection order.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeConfigEntryNotReady(Exception):
    """Stub for homeassistant.exceptions.ConfigEntryNotReady.

    No other test module in this suite touches homeassistant.exceptions, so
    this assignment is stable regardless of test collection order.
    """


def _setup_ha_mocks() -> None:
    """Ensure the homeassistant modules used by __init__.py exist."""
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = MagicMock()
    if "homeassistant.core" not in sys.modules:
        sys.modules["homeassistant.core"] = MagicMock()
    if "homeassistant.config_entries" not in sys.modules:
        sys.modules["homeassistant.config_entries"] = MagicMock()
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = MagicMock()
    if "homeassistant.helpers.aiohttp_client" not in sys.modules:
        sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()
    if "homeassistant.helpers.update_coordinator" not in sys.modules:
        sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()

    exceptions_mod = sys.modules.get("homeassistant.exceptions")
    if exceptions_mod is None:
        exceptions_mod = MagicMock()
        sys.modules["homeassistant.exceptions"] = exceptions_mod
    exceptions_mod.ConfigEntryNotReady = _FakeConfigEntryNotReady


_setup_ha_mocks()

import custom_components.haiserv as haiserv  # noqa: E402
from custom_components.haiserv.const import DOMAIN  # noqa: E402


class _StubCoordinator:
    """Stand-in for IServCoordinator: configurable first-refresh outcome."""

    fail_offsets: set[int] = set()

    def __init__(self, hass, client, week_offset: int = 0) -> None:
        self.hass = hass
        self.client = client
        self.week_offset = week_offset
        self.data = None

    async def async_config_entry_first_refresh(self) -> None:
        if self.week_offset in self.__class__.fail_offsets:
            raise _FakeConfigEntryNotReady("No timetable endpoint is available")
        self.data = []


class _StubAuxCoordinator:
    """Stand-in for the parent-letter/notification coordinators."""

    should_fail = False

    def __init__(self, hass, client) -> None:
        self.hass = hass
        self.client = client
        self.data = None

    async def async_config_entry_first_refresh(self) -> None:
        if self.__class__.should_fail:
            raise _FakeConfigEntryNotReady("unreachable")
        self.data = []


@pytest.fixture
def hass():
    """Minimal fake HomeAssistant instance for async_setup_entry."""
    instance = MagicMock()
    instance.data = {}
    instance.config.path = MagicMock(side_effect=lambda name: f"/tmp/{name}")
    instance.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
    return instance


@pytest.fixture
def entry():
    """Minimal fake ConfigEntry with iServ credentials."""
    instance = MagicMock()
    instance.entry_id = "test_entry"
    instance.data = {
        "url": "https://school.iserv.de",
        "username": "testuser",
        "password": "testpass",
    }
    return instance


async def test_setup_succeeds_when_timetable_endpoint_unreachable(hass, entry):
    """Setup succeeds and other sensors stay functional even when no
    timetable endpoint is reachable, instead of raising ConfigEntryNotReady
    and blocking the whole integration."""
    _StubCoordinator.fail_offsets = {0}
    _StubAuxCoordinator.should_fail = False
    try:
        with patch(
            "custom_components.haiserv.coordinator.IServCoordinator", _StubCoordinator
        ), patch(
            "custom_components.haiserv.coordinator.IServParentLetterCoordinator",
            _StubAuxCoordinator,
        ), patch(
            "custom_components.haiserv.coordinator.IServNotificationCoordinator",
            _StubAuxCoordinator,
        ), patch("custom_components.haiserv.api.IServClient") as mock_client_cls:
            result = await haiserv.async_setup_entry(hass, entry)
    finally:
        _StubCoordinator.fail_offsets = set()

    assert result is True

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data == []  # unreachable, but setup did not abort

    # The other coordinators (and platform forwarding) still ran.
    assert hass.data[DOMAIN][f"{entry.entry_id}_next_week"].data == []
    assert hass.data[DOMAIN][f"{entry.entry_id}_parentletter"].data == []
    assert hass.data[DOMAIN][f"{entry.entry_id}_notifications"].data == []
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    # The client was wired with a debug_callback for request-level diagnostics.
    _, kwargs = mock_client_cls.call_args
    assert kwargs.get("debug_callback") is not None


async def test_setup_succeeds_when_all_endpoints_reachable(hass, entry):
    """Sanity check: setup still works normally when nothing fails."""
    _StubCoordinator.fail_offsets = set()
    _StubAuxCoordinator.should_fail = False

    with patch(
        "custom_components.haiserv.coordinator.IServCoordinator", _StubCoordinator
    ), patch(
        "custom_components.haiserv.coordinator.IServParentLetterCoordinator",
        _StubAuxCoordinator,
    ), patch(
        "custom_components.haiserv.coordinator.IServNotificationCoordinator",
        _StubAuxCoordinator,
    ), patch("custom_components.haiserv.api.IServClient"):
        result = await haiserv.async_setup_entry(hass, entry)

    assert result is True
    assert hass.data[DOMAIN][entry.entry_id].data == []


async def test_setup_blocks_when_all_coordinators_fail(hass, entry):
    """If literally nothing is reachable, first refresh still fails per
    coordinator but setup as a whole keeps succeeding (per-sensor
    unavailability, not a blocked config entry)."""
    _StubCoordinator.fail_offsets = {0, 1}
    _StubAuxCoordinator.should_fail = True
    try:
        with patch(
            "custom_components.haiserv.coordinator.IServCoordinator", _StubCoordinator
        ), patch(
            "custom_components.haiserv.coordinator.IServParentLetterCoordinator",
            _StubAuxCoordinator,
        ), patch(
            "custom_components.haiserv.coordinator.IServNotificationCoordinator",
            _StubAuxCoordinator,
        ), patch("custom_components.haiserv.api.IServClient"):
            result = await haiserv.async_setup_entry(hass, entry)
    finally:
        _StubCoordinator.fail_offsets = set()
        _StubAuxCoordinator.should_fail = False

    assert result is True
    assert hass.data[DOMAIN][entry.entry_id].data == []
    assert hass.data[DOMAIN][f"{entry.entry_id}_next_week"].data == []
    assert hass.data[DOMAIN][f"{entry.entry_id}_parentletter"].data == []
    assert hass.data[DOMAIN][f"{entry.entry_id}_notifications"].data == []
