"""Unit tests for IServNotificationSensor entity."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# HA stub setup (mirrors the pattern from test_parentletter_sensor.py)
# ---------------------------------------------------------------------------


class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeSensorEntity:
    pass


class _FakeDataUpdateCoordinator:
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeUpdateFailed(Exception):
    pass


def _setup_ha_mocks() -> None:
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = MagicMock()
    if "homeassistant.core" not in sys.modules:
        sys.modules["homeassistant.core"] = MagicMock()
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = MagicMock()

    uc_mod = sys.modules.get("homeassistant.helpers.update_coordinator")
    if uc_mod is None:
        uc_mod = MagicMock()
        sys.modules["homeassistant.helpers.update_coordinator"] = uc_mod
        uc_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
        uc_mod.UpdateFailed = _FakeUpdateFailed
    uc_mod.CoordinatorEntity = _FakeCoordinatorEntity

    if "homeassistant.helpers.entity_platform" not in sys.modules:
        sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
    if "homeassistant.components" not in sys.modules:
        sys.modules["homeassistant.components"] = MagicMock()

    sensor_mod = sys.modules.get("homeassistant.components.sensor")
    if sensor_mod is None:
        sensor_mod = MagicMock()
        sys.modules["homeassistant.components.sensor"] = sensor_mod
    sensor_mod.SensorEntity = _FakeSensorEntity

    if "homeassistant.config_entries" not in sys.modules:
        sys.modules["homeassistant.config_entries"] = MagicMock()


_setup_ha_mocks()

# Force fresh import
for _mod in list(sys.modules):
    if _mod.startswith("custom_components.haiserv.sensor"):
        del sys.modules[_mod]

from custom_components.haiserv.sensor import IServNotificationSensor  # noqa: E402
from custom_components.haiserv.notification import Notification  # noqa: E402
from custom_components.haiserv.const import MAX_CONSECUTIVE_FAILURES  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_notifications() -> list[Notification]:
    return [
        Notification(
            id=100,
            type="mail",
            title="E-Mail von user@demo.iserv.de",
            message="E-Mail von user@demo.iserv.de",
            url="https://school.iserv.de/iserv/notification/goto/100",
            icon="envelope",
            date=datetime(2024, 3, 15, 9, 30),
            published=True,
        ),
        Notification(
            id=101,
            type="exercise",
            title="Hausaufgabe fällig",
            message="Mathe bis Montag",
            url="https://school.iserv.de/iserv/notification/goto/101",
            icon="tasks",
            date=datetime(2024, 3, 16, 7, 0),
            published=True,
        ),
    ]


@pytest.fixture
def mock_coordinator(sample_notifications):
    coordinator = MagicMock()
    coordinator.data = sample_notifications
    coordinator.consecutive_failures = 0
    return coordinator


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_notif"
    return entry


@pytest.fixture
def sensor(mock_coordinator, mock_entry):
    return IServNotificationSensor(mock_coordinator, mock_entry)


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------


class TestNotificationSensorState:
    def test_two_notifications(self, sensor):
        assert sensor.native_value == "2 notifications"

    def test_one_notification(self, mock_entry, sample_notifications):
        coord = MagicMock()
        coord.data = sample_notifications[:1]
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        assert s.native_value == "1 notifications"

    def test_empty_list(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        assert s.native_value == "No notifications"

    def test_none_data(self, mock_entry):
        coord = MagicMock()
        coord.data = None
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        assert s.native_value == "No notifications"


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


class TestNotificationSensorAttributes:
    def test_notifications_key_present(self, sensor, sample_notifications):
        attrs = sensor.extra_state_attributes
        assert "notifications" in attrs
        assert isinstance(attrs["notifications"], list)
        assert len(attrs["notifications"]) == len(sample_notifications)

    def test_count_correct(self, sensor, sample_notifications):
        attrs = sensor.extra_state_attributes
        assert attrs["count"] == len(sample_notifications)

    def test_last_id_is_max_id(self, sensor):
        attrs = sensor.extra_state_attributes
        assert attrs["last_id"] == 101

    def test_last_id_none_when_empty(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        attrs = s.extra_state_attributes
        assert attrs["last_id"] is None

    def test_last_updated_is_iso_string(self, sensor):
        frozen = datetime(2024, 4, 1, 12, 0, 0)
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen
            attrs = sensor.extra_state_attributes
        assert attrs["last_updated"] == frozen.isoformat()

    def test_notification_dict_contains_expected_keys(self, sensor):
        attrs = sensor.extra_state_attributes
        notification_dict = attrs["notifications"][0]
        for key in (
            "id", "type", "title", "message", "url", "icon", "date", "published",
        ):
            assert key in notification_dict, f"Missing key: {key}"

    def test_date_serialised_as_iso_string(self, sensor):
        attrs = sensor.extra_state_attributes
        date_value = attrs["notifications"][0]["date"]
        assert date_value == datetime(2024, 3, 15, 9, 30).isoformat()

    def test_date_none_serialised_as_none(self, mock_entry):
        notifications = [
            Notification(
                id=1, type="mail", title="T", message="m", url="", icon="",
                date=None,
            )
        ]
        coord = MagicMock()
        coord.data = notifications
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        attrs = s.extra_state_attributes
        assert attrs["notifications"][0]["date"] is None

    def test_empty_notifications_attributes(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = 0
        s = IServNotificationSensor(coord, mock_entry)
        attrs = s.extra_state_attributes
        assert attrs["notifications"] == []
        assert attrs["count"] == 0


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


class TestNotificationSensorAvailability:
    def test_available_no_failures(self, sensor):
        assert sensor.available is True

    def test_available_below_threshold(self, mock_coordinator, mock_entry):
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1
        s = IServNotificationSensor(mock_coordinator, mock_entry)
        assert s.available is True

    def test_available_with_data_at_threshold(self, mock_coordinator, mock_entry):
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        # data is not empty — sensor should stay available
        s = IServNotificationSensor(mock_coordinator, mock_entry)
        assert s.available is True

    def test_unavailable_no_data_at_threshold(self, mock_entry):
        coord = MagicMock()
        coord.data = None
        coord.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        s = IServNotificationSensor(coord, mock_entry)
        assert s.available is False

    def test_unavailable_empty_data_at_threshold(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        s = IServNotificationSensor(coord, mock_entry)
        assert s.available is False


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestNotificationSensorIdentity:
    def test_unique_id(self, sensor, mock_entry):
        assert sensor._attr_unique_id == f"{mock_entry.entry_id}_notifications"

    def test_name(self, sensor):
        assert sensor._attr_name == "iServ Notifications"
