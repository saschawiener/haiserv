# HAiServ — AI Agent Guide

This file is the project's persistent context for AI coding agents (Claude Code, Cursor,
Aider, Codex CLI, etc.). It replaces the previous Kiro-specific steering docs under
`.kiro/steering/`. Feature-level specs (requirements/design/tasks) live under
`docs/specs/` — see [Feature specs](#feature-specs) below.

## Product Summary

HAiServ is a Home Assistant custom integration that connects to IServ, a German school
portal platform. It authenticates with an existing IServ account and exposes timetable
and Elternbrief (parent letter) data as Home Assistant sensors.

Core functionality:

- Authenticates against an IServ server using username/password credentials (session-cookie based)
- Fetches the current and next week's timetable via IServ's internal API
- Parses timetables into structured lesson objects (day, time, subject, room)
- Exposes a sensor showing the next upcoming lesson, with the full timetable (list + Markdown table) as attributes
- Monitors the Elternbrief (parent letter) inbox and exposes an unread-count sensor
- Caches the last successfully fetched timetable locally and serves it if a later fetch fails
- Polls on a configurable interval (default: 60 minutes)

Domain context:

- IServ is widely used in German schools for scheduling, file sharing, and communication
- Users configure the integration via a UI config flow (URL + credentials)
- The integration uses cloud polling (no local network access needed)
- Timetable data is organized by weekday (Monday–Friday) with time slots

### IServ API reference

IServ has no official public API documentation. Endpoint paths, authentication flow, and
response formats were derived from these community projects:

- **IServAPI** (Python): https://pypi.org/project/IServAPI/ — login, timetable, mail, notifications, file access
- **IServ (Node.js)**: https://github.com/dunklesToast/IServ — exercises, mail, badges, notifications, files; session cookie handling
- **iserv** (Python): https://github.com/RoRo160/iserv — authentication, timetable parsing, file downloads

Known endpoints (community-derived):

| Purpose | Method | Path |
|---|---|---|
| Login | POST | `/iserv/auth/login` (form fields: `_username`, `_password`) |
| Timetable (raw) | GET | `/iserv/plan/show/raw` (query param: `week`) |
| Exercises | GET | `/iserv/exercise` |
| Mail (inbox) | GET | `/iserv/mail/api/message/list` |
| Notifications | GET | `/iserv/user/api/notifications` |
| Files | GET | `/iserv/file/-/Files/` |
| Badges | GET | `/iserv/user/api/badge` |

Authentication notes:

- Session-cookie-based auth (form POST login, then cookies for subsequent requests)
- A successful login typically returns an HTTP 302 redirect followed by 200
- Sessions can expire; the client must detect 401/403 on data fetch and re-authenticate transparently
- All IServ instances share the same endpoint structure — only the base URL differs per school

## Project Structure

```
haiserv/
├── custom_components/
│   └── haiserv/                    # Main integration package
│       ├── __init__.py             # Entry point: async_setup_entry / async_unload_entry
│       ├── api.py                  # IServClient: authentication + timetable/parent-letter fetching
│       ├── cache.py                # Local JSON cache for last-known-good timetable
│       ├── config_flow.py          # UI config flow (URL, username, password)
│       ├── const.py                # Constants: DOMAIN, timeouts, intervals, DAY_ORDER
│       ├── coordinator.py          # DataUpdateCoordinator: polling + error recovery
│       ├── manifest.json           # HA integration metadata (domain, version, requirements)
│       ├── notification.py         # Elternbrief/notification fetching + parsing
│       ├── parentletter_parser.py  # Parent-letter response parsing
│       ├── parser.py               # Lesson dataclass, parse/sort/format logic
│       ├── sensor.py               # Timetable + parent-letter/notification sensor entities
│       └── strings.json            # UI strings for config flow
├── tests/
│   ├── conftest.py                 # Shared fixtures + HA module mocking
│   ├── test_api.py                 # API client tests
│   ├── test_config_flow.py         # Config flow tests
│   ├── test_coordinator.py         # Coordinator tests
│   ├── test_sensor.py              # Sensor entity tests
│   ├── test_notification_*.py      # Elternbrief/notification coordinator/parser/sensor tests
│   ├── test_parentletter_*.py      # Parent-letter parser/sensor tests
│   ├── test_strings.py             # strings.json validation
│   ├── test_*_properties.py        # Hypothesis property-based tests
│   └── test_integration.py         # End-to-end integration tests
├── dashboards/                     # Example Lovelace dashboard configs
├── docs/specs/                     # Feature specs (requirements/design/tasks) — see below
├── pytest.ini                      # Pytest configuration
└── .hypothesis/                    # Hypothesis test database (auto-generated)
```

### Architecture

The integration follows the standard Home Assistant custom component pattern:

1. **Config Flow** (`config_flow.py`) — validates credentials and creates a config entry
2. **Setup** (`__init__.py`) — creates `IServClient` and `IServCoordinator`, forwards to the sensor platform
3. **API Client** (`api.py`) — handles HTTP auth and data fetching with retry on session expiry
4. **Coordinator** (`coordinator.py`) — polls on interval, handles errors, stores parsed data, falls back to `cache.py` on fetch failure
5. **Parsers** (`parser.py`, `parentletter_parser.py`, `notification.py`) — transform raw responses into dataclass instances
6. **Sensors** (`sensor.py`) — expose timetable and parent-letter/notification data as HA entities with state + attributes

### Conventions

- One module per concern (api, parser, coordinator, sensor, config_flow, const, cache, notification)
- All async I/O uses `async`/`await` — no blocking calls
- Google-style docstrings with `Args:`, `Returns:`, `Raises:` sections
- Full type annotations on all function signatures
- `from __future__ import annotations` throughout
- Custom exceptions (`AuthenticationError`, `CannotConnect`) defined in `api.py`
- Constants live in `const.py` and are imported where needed
- Tests mock Home Assistant entirely via `conftest.py` — no HA install required

## Tech Stack & Build

- **Language**: Python 3
- **Framework**: Home Assistant custom component (HACS-compatible). Uses HA patterns: `ConfigEntry`, `DataUpdateCoordinator`, `CoordinatorEntity`, `SensorEntity`
- **Key libraries**: `aiohttp` (async HTTP), `voluptuous` (config flow schema validation), `dataclasses` (domain models), `asyncio`
- **Testing**: `pytest` with `asyncio_mode = auto` (no manual `@pytest.mark.asyncio` needed), `hypothesis` for property-based testing, `unittest.mock` (`MagicMock`/`AsyncMock`) for HA and aiohttp stubs — Home Assistant is fully mocked in `conftest.py`, no HA installation required
- **Project config**: `manifest.json` declares domain, version, requirements, and IoT class; `pytest.ini` configures the test runner (`testpaths = tests`); no `pyproject.toml`/`setup.py`/`requirements.txt` — dependencies are declared in `manifest.json` only

Common commands:

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_parser_properties.py

# Run tests with verbose output
pytest -v
```

## Feature Specs

Non-trivial features are documented as specs under `docs/specs/<feature-name>/`, each with:

- `requirements.md` — user stories + EARS-style acceptance criteria ("WHEN ... THE ... SHALL ...")
- `design.md` — architecture, component interfaces, data models, correctness properties, error handling, testing strategy
- `tasks.md` — an ordered implementation checklist, each task tagged with the requirements it satisfies

When implementing a new non-trivial feature, follow the same pattern: write `requirements.md`
and `design.md` first, derive `tasks.md` from them, and keep the checkboxes in `tasks.md`
up to date as work progresses. Existing specs:

- [`docs/specs/iserv-homeassistant-integration/`](docs/specs/iserv-homeassistant-integration/) — the original integration (config flow, API client, coordinator, timetable sensor)
- [`docs/specs/setup-flow-improvements/`](docs/specs/setup-flow-improvements/) — config flow UX improvements (welcome text, entry title, duplicate detection)
