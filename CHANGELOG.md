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

- Climate `hvac_action`: "Heating" (phase on), "Preheating" (ignition), "Idle"
  (automatic standby, and shutdown / cooling / final cleaning while powered on) and
  "Off" (turned off by the user). Alarm and unknown phases give no action (debug log).
- New sensors read from `status` (created only when the stove reports the value):
  `Smoke temperature` (thermocouple), and the diagnostics `Alarm code`,
  `Board temperature`, `Hours before service`, plus `NTC probe 1`,
  `Operational phase code` and `Sub operational phase` (disabled by default).
  `status.state.actual_power` was already exposed by `Actual power`.
- Sensors read from `nvm` (`Fan N`, `Nb alarms`, `Power ons`) expose an
  `nvm_timestamp` attribute, as this block can be older than `status`.

- `scripts/measure_check.py`: development tool measuring the publication window after a
  `check` and whether `nvm` is refreshed by it (see README, Development notes).

### Measurements

Measured on the reference stove with `scripts/measure_check.py` (2026-10-25, stove in
phase 0, no other client sending checks):

- after a `check`, the first status publication arrives in ~4 s;
- the stove then publishes every ~2 s (1–4 s) for ~2 min (last publication at
  +118 s), then stops: the data starts ageing again;
- a `check` does **not** refresh `nvm` (`nvm.timestamp` stayed ~33 min old,
  `crc16_nvm` unchanged). `nvm` is therefore not used to decide freshness.

The defaults are kept: with `STALE_AFTER` = 90 s the data is never older than
~110 s, for about one `check` every 3.5 min (the old binary sensor sent 120 per hour).

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
- Climate target temperature bounds moved to constants (`MIN_TARGET_TEMPERATURE`,
  `MAX_TARGET_TEMPERATURE`) and the 0.5 °C step is now explicit
  (`target_temperature_step`). The 14–24 °C range is unchanged: the bounds accepted
  by the stove have not been verified yet.
- edilkamin library upgraded from 1.6.0 to 1.7.0 (type hints only, no API change;
  `sign_in` is still synchronous and still run in the executor).
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
