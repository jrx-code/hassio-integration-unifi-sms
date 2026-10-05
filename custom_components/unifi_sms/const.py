"""Constants for the UniFi 5G SMS integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "unifi_sms"

CONF_PRIVATE_KEY = "private_key"
CONF_HOST_KEY = "host_key"
CONF_ICCID = "iccid"
CONF_RECIPIENTS = "recipients"
CONF_TRUSTED = "trusted_senders"
CONF_ONLY_TRUSTED = "only_trusted"
CONF_DAILY_LIMIT = "daily_limit"
CONF_ASCII_ONLY = "ascii_only"
CONF_MODE = "mode"

MODE_SEND_RECEIVE = "send_receive"
MODE_SEND_ONLY = "send_only"
# Entities that only make sense when this entry receives (unique_id suffixes).
RECEIVE_ENTITY_KEYS = ("received", "last_sms", "receive_hook")

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)

# uiwwand rejects longer texts with `send-sms: text too long (N > 64)`; N is the UTF-8 byte length.
MAX_TEXT_BYTES = 64

EVENT_SMS_RECEIVED = f"{DOMAIN}_received"
SERVICE_SEND = "send"

# How many received message ids to remember, so a restart does not replay them.
SEEN_IDS_LIMIT = 200
