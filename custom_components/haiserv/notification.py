"""Parser for iServ notification API JSON responses."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

_LOGGER = logging.getLogger(__name__)


@dataclass
class Notification:
    """Represents a single iServ notification.

    Attributes:
        id: Numeric notification ID, stable across polls.
        type: iServ notification type (e.g. "mail", "exercise", "parentletter").
        title: Short title. iServ leaves this empty for some types (e.g. mail),
            in which case it is filled in from ``message``.
        message: Human-readable notification text.
        url: Absolute URL the notification links to (deep link into iServ),
            or an empty string if iServ did not provide one.
        icon: iServ icon identifier (e.g. "envelope").
        date: Timestamp the notification was created.
        published: Whether iServ marks the notification as published.
    """

    id: int
    type: str
    title: str
    message: str
    url: str
    icon: str
    date: datetime | None
    published: bool = True


def parse_notifications(
    raw_response: str, base_url: str | None = None
) -> list[Notification]:
    """Parse the iServ notifications API response into Notification objects.

    Expects the envelope returned by ``GET /iserv/user/api/notifications``::

        {"status": "success", "data": {"notifications": [...], ...}}

    Args:
        raw_response: Raw JSON response body.
        base_url: iServ base URL (e.g. "https://school.iserv.de") used to
            resolve each notification's relative ``url`` to an absolute link.
            Relative URLs are left untouched when omitted.

    Returns:
        List of Notification objects in the order returned by the server.
        Returns an empty list if the response cannot be parsed.
    """
    if not raw_response or not raw_response.strip():
        return []

    try:
        payload = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError):
        _LOGGER.warning("Failed to parse notifications response as JSON")
        return []

    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    entries = data.get("notifications") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []

    notifications: list[Notification] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        notification_id = entry.get("id")
        if not isinstance(notification_id, int):
            continue

        message = _string(entry, "message")
        title = _string(entry, "title") or message
        url = _string(entry, "url")
        if url and base_url:
            url = urljoin(base_url, url)

        notifications.append(
            Notification(
                id=notification_id,
                type=_string(entry, "type"),
                title=title,
                message=message,
                url=url,
                icon=_string(entry, "icon"),
                date=_parse_date(entry.get("date")),
                published=bool(entry.get("published", True)),
            )
        )

    return notifications


def _string(entry: dict[str, object], key: str) -> str:
    """Return the value at ``key`` if it is a string, else an empty string."""
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def _parse_date(value: object) -> datetime | None:
    """Parse an ISO 8601 notification timestamp, tolerating missing data."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
