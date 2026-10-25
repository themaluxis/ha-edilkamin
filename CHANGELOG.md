# Changelog

All notable changes to this integration are documented in this file.

## [Unreleased]

### Added

- Data freshness is now driven by the coordinator. On every poll (15 s, like the
  official app) it measures the age of `status.timestamp`. When the data is older than
  90 s it sends a `check` command, waits 12 s and reads `device/info` again. At most one
  `check` is sent per 60 s. If the data is still stale after a check, a warning with the
  measured age is logged and the data is kept.
- Diagnostic sensors `Data age` (seconds) and `Last stove update` (timestamp of the
  last status published by the stove). Both stay available when the cloud is frozen.
- All other entities become unavailable when the stove has not published for more
  than 300 s, instead of silently showing frozen values.
- Commands (target temperature, HVAC mode, preset, fan speed, switches) update the
  entity at once with the requested value instead of bouncing back to the old value.
  The requested value is kept until the stove publishes data newer than the command
  (`status.timestamp`, or `nvm.timestamp` for values stored in `nvm`: target
  temperature, fan speed, preset, chrono, standby), or for 60 s at most. Older polls
  in between no longer overwrite it.
- After a command the coordinator sends a `check` (within the 60 s cooldown) and
  refreshes 12 s later. Close commands re-arm the same timer, so a burst of clicks
  gives one `check` and one delayed refresh.
- A command refused by the cloud leaves the state unchanged and shows a readable
  error in the UI (including "standby only available from auto mode", which was
  silently ignored when turning standby off).
- Thresholds (`STALE_AFTER`, `CHECK_DELAY`, `CHECK_COOLDOWN`, `UNAVAILABLE_AFTER`)
  are constants in `const.py`.

- Reauthentication: when the Edilkamin password changes, Home Assistant shows a
  "reauthentication required" notification; entering the new password restores the
  integration without removing it.

### Changed

- When the cloud answers HTTP 401 or 403 (token revoked server side), the integration
  drops its token, signs in again and retries once, for both `device/info` and
  commands. Invalid credentials raise `ConfigEntryAuthFailed`.
- Errors are told apart in the logs: network (cannot reach the cloud), HTTP status,
  authentication, and unexpected response format. Tokens and passwords are never
  logged.
- Turning standby on or off sends a single `mqtt/command`: auto mode is checked on
  the data already read by the coordinator instead of an extra `device/info` call.

- **Binary sensor `Check configuration` no longer sends anything.** It used to be
  polled by Home Assistant every 30 s and send a `check` command on each poll; that
  side effect was the only thing keeping the data fresh, and disabling the entity froze
  every value without any warning. It now reflects the coordinator instead (no own
  polling): it is "problem" when the last cloud read or the last `check` sent by the
  coordinator failed. Its `unique_id` and `entity_id` are unchanged.
- The coordinator timeout is raised from 10 s to 30 s to absorb the wait after a
  `check`.
- Coordinator and API are now stored per config entry (`entry.runtime_data`) instead
  of a global `hass.data[DOMAIN]["coordinator"]` key: several stoves can be configured
  side by side without overwriting each other.
- Startup uses `async_config_entry_first_refresh`: when the Edilkamin cloud is
  unreachable, the entry goes into "Retrying setup" and connects as soon as the cloud
  is back, instead of starting with empty entities.
- Unloading or reloading the integration shuts the coordinator down: no orphan polling.
- All entities share a common base class (`EdilkaminEntity`) with
  `has_entity_name = True` and a common `DeviceInfo`. `unique_id`s are unchanged, so
  existing entities and `entity_id`s are kept. Friendly names are now prefixed by the
  device name (e.g. "Edilkamin Stove Tank"); the climate entity takes the device name.
