# Changelog

All notable changes to this integration are documented in this file.

## [Unreleased]

### Changed

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
