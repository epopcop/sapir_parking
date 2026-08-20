"""Constants."""

# Base component constants
NAME = "Sapir Parking"
DOMAIN = "sapir_parking"
VERSION = "0.0.1"

# Configuration and options
CONF_PHONE = "phone"
CONF_LICENSE = "license"
CONF_SESSION_COOKIE = "session_cookie"

STARTUP_MESSAGE = f"""Initializing {NAME} (v{VERSION}) integration..."""

DATE_FORMAT = "%Y-%m-%d"

PARKING_ENTITY = f"{DOMAIN}.parking"

RESERVED_STATE = "reserved"
NOT_RESERVED_STATE = "not_reserved"
