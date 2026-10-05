"""Diagnostics download, with keys, numbers and SIM identifiers redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .api import fingerprint
from .const import CONF_HOST_KEY, CONF_ICCID, CONF_PRIVATE_KEY, CONF_RECIPIENTS, CONF_TRUSTED
from .coordinator import UnifiSmsConfigEntry

TO_REDACT = {CONF_PRIVATE_KEY, CONF_HOST_KEY, CONF_ICCID, CONF_RECIPIENTS, CONF_TRUSTED, "gid1"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    try:
        host_key = fingerprint(entry.data[CONF_HOST_KEY])
    except Exception:  # noqa: BLE001 - only informational
        host_key = None
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "host_key_fingerprint": host_key,
        },
        "modem": {
            "system": coordinator.system,
            "receive_hook": coordinator.modem.hook_state,
            "sim": async_redact_data(coordinator.data.sim if coordinator.data else {}, TO_REDACT),
        },
        "polling": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
            "update_interval_s": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
        },
        "sent": {"today": coordinator.sent_today, "month": coordinator.sent_month},
    }
