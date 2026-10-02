"""The iServ integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = ["sensor"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iServ from a config entry.

    Creates the API client, coordinators, triggers first data refreshes,
    stores the coordinators in hass.data, and forwards sensor platform setup.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.
    """
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from homeassistant.exceptions import ConfigEntryNotReady

    from .api import IServClient
    from .cache import ResponseCache
    from .const import DOMAIN
    from .coordinator import (
        IServCoordinator,
        IServNotificationCoordinator,
        IServParentLetterCoordinator,
    )

    # Get credentials from config entry data
    url = entry.data["url"]
    username = entry.data["username"]
    password = entry.data["password"]

    # Create aiohttp session via Home Assistant's session manager
    session = async_get_clientsession(hass)

    # Instantiate the iServ API client with a local timetable cache so a
    # temporarily disabled module (e.g. HTTP 403) can serve the last result.
    # debug_callback logs every request's status/redirects/cookies at DEBUG
    # level, so enabling debug logging for this integration shows exactly
    # which endpoint generation iServ accepted or rejected.
    cache = ResponseCache(hass.config.path("haiserv_cache"))
    client = IServClient(
        session, url, username, password, debug_callback=_LOGGER.debug, cache=cache
    )

    # Create and refresh the current-week coordinator. If the school has no
    # reachable timetable endpoint, proceed with setup anyway (as the other
    # coordinators below already do) so the timetable sensor is created and
    # reports unavailable instead of blocking the whole config entry.
    coordinator = IServCoordinator(hass, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        coordinator.data = []

    # Fetch the following week for a separate overview entity. Keep the
    # current-week entity usable if this optional request is unavailable.
    next_week_coordinator = IServCoordinator(hass, client, week_offset=1)
    try:
        await next_week_coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        next_week_coordinator.data = []

    # Store the coordinators for platform entities
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    hass.data[DOMAIN][f"{entry.entry_id}_next_week"] = next_week_coordinator

    # Set up the Elternbrief coordinator. On failure, the sensor will be
    # unavailable but setup proceeds so timetable entities remain functional.
    parentletter_coordinator = IServParentLetterCoordinator(hass, client)
    try:
        await parentletter_coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        parentletter_coordinator.data = []
    hass.data[DOMAIN][f"{entry.entry_id}_parentletter"] = parentletter_coordinator

    # Set up the notification coordinator. On failure, the sensor will be
    # unavailable but setup proceeds so timetable entities remain functional.
    notification_coordinator = IServNotificationCoordinator(hass, client)
    try:
        await notification_coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        notification_coordinator.data = []
    hass.data[DOMAIN][f"{entry.entry_id}_notifications"] = notification_coordinator

    # Forward platform setup to the sensor module
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an iServ config entry.

    Unloads sensor platforms and cleans up stored data.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        True if unloading was successful.
    """
    from .const import DOMAIN

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_next_week", None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_parentletter", None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_notifications", None)

    return unload_ok
