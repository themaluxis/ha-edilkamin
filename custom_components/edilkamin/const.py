"""Constants for the Edilkamin integration."""

DOMAIN = "edilkamin"

MAC_ADDRESS = "mac_address"
USERNAME = "username"
PASSWORD = "password"  # noqa: S105

# Polling period of device/info, aligned on the official app
UPDATE_INTERVAL = 15  # seconds
# Global timeout of one coordinator cycle (read + check + wait + read)
UPDATE_TIMEOUT = 30  # seconds
# Measured with scripts/measure_check.py (2026-10-25): after a "check" the stove
# publishes its status within ~4 s, then every ~2 s for ~2 min, then stops. A check
# does not refresh the nvm block, so only status.timestamp drives freshness.
# With these values the data is never older than ~110 s (90 s + one 15 s poll +
# ~4 s publication delay), for about one check every 3.5 min.

# status.timestamp older than this triggers a "check" command
STALE_AFTER = 90  # seconds
# Wait between the "check" command and the second read of device/info
# (first publication measured at ~4 s, kept with a margin)
CHECK_DELAY = 12  # seconds
# Minimum time between two "check" commands
CHECK_COOLDOWN = 60  # seconds
# Entities become unavailable when status.timestamp is older than this
UNAVAILABLE_AFTER = 300  # seconds
# Maximum time an optimistic value is kept after a command
OPTIMISTIC_TIMEOUT = 60  # seconds

# Target temperature range of the climate entity. Not widened: the bounds accepted
# by the stove could not be verified yet (see CHANGELOG)
MIN_TARGET_TEMPERATURE = 14  # °C
MAX_TARGET_TEMPERATURE = 24  # °C
TARGET_TEMPERATURE_STEP = 0.5  # °C
