"""Constants."""

from datetime import timedelta

from homeassistant.const import Platform

NAME = "Sapir Parking"
DOMAIN = "sapir_parking"

PLATFORMS = [Platform.SENSOR]

# Configuration and options
CONF_AUTH_METHOD = "auth_method"
CONF_PHONE = "phone"
CONF_LICENSE = "license"
CONF_SESSION_COOKIE = "session_cookie"
CONF_FLARESOLVERR_URL = "flaresolverr_url"

AUTH_METHOD_COOKIE = "cookie"
AUTH_METHOD_LOGIN = "login"

DATE_FORMAT = "%Y-%m-%d"

UPDATE_INTERVAL = timedelta(minutes=15)

RESERVED_STATE = "reserved"
NOT_RESERVED_STATE = "not_reserved"
