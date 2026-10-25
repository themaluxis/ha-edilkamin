"""Constants for the Edilkamin integration."""

DOMAIN = "edilkamin"

MAC_ADDRESS = "mac_address"
USERNAME = "username"
PASSWORD = "password"  # noqa: S105

# Polling period of device/info, aligned on the official app
UPDATE_INTERVAL = 15  # seconds
# Global timeout of one coordinator cycle (read + check + wait + read)
UPDATE_TIMEOUT = 30  # seconds
# status.timestamp older than this triggers a "check" command
STALE_AFTER = 90  # seconds
# Wait between the "check" command and the second read of device/info
CHECK_DELAY = 12  # seconds
# Minimum time between two "check" commands
CHECK_COOLDOWN = 60  # seconds
# Entities become unavailable when status.timestamp is older than this
UNAVAILABLE_AFTER = 300  # seconds
# Maximum time an optimistic value is kept after a command
OPTIMISTIC_TIMEOUT = 60  # seconds
