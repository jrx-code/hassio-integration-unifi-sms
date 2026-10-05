"""SMS in Home Assistant through a UniFi U5G modem."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import U5GAuthError, U5GError, U5GHostKeyError, U5GModem
from .const import (
    CONF_HOST_KEY,
    CONF_MODE,
    CONF_PRIVATE_KEY,
    DOMAIN,
    MODE_SEND_RECEIVE,
    RECEIVE_ENTITY_KEYS,
    SERVICE_SEND,
)
from .coordinator import UnifiSmsConfigEntry, UnifiSmsCoordinator
from .sms import parse_recipients

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.NOTIFY, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_TO = "to"
ATTR_MESSAGE = "message"
ATTR_ENTRY = "config_entry_id"

SEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TO): vol.Any(cv.string, [cv.string]),
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def send(call: ServiceCall) -> ServiceResponse:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if entry_id := call.data.get(ATTR_ENTRY):
            entries = [e for e in entries if e.entry_id == entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="pick_entry")
        coordinator: UnifiSmsCoordinator = entries[0].runtime_data
        try:
            recipients = parse_recipients(call.data[ATTR_TO])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        if not recipients:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_recipients")
        parts = await coordinator.async_send(recipients, call.data[ATTR_MESSAGE])
        return {"recipients": recipients, "parts_per_recipient": parts}

    hass.services.async_register(
        DOMAIN, SERVICE_SEND, send, schema=SEND_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> bool:
    modem = U5GModem(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PRIVATE_KEY],
        entry.data[CONF_HOST_KEY],
        install_hook=receives(entry),
    )
    try:
        await modem.sim_state()
    except (U5GAuthError, U5GHostKeyError) as err:
        await modem.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except U5GError as err:
        await modem.close()
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = UnifiSmsCoordinator(hass, entry, modem)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    if not coordinator.receive:
        _remove_receive_entities(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def receives(entry: UnifiSmsConfigEntry) -> bool:
    return entry.options.get(CONF_MODE, MODE_SEND_RECEIVE) == MODE_SEND_RECEIVE


def _remove_receive_entities(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> None:
    """Send-only entries do not provide the receive entities; drop leftovers from receive mode."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if any(entity.unique_id.endswith(f"_{key}") for key in RECEIVE_ENTITY_KEYS):
            registry.async_remove(entity.entity_id)


async def _async_reload(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> None:
    coordinator = entry.runtime_data
    if coordinator.receive and not receives(entry):
        # This entry installed the hook; leaving it would pile up spool files nobody reads.
        try:
            await coordinator.modem.remove_hook()
        except U5GError as err:
            _LOGGER.warning("Could not remove the receive hook from %s: %s", entry.data[CONF_HOST], err)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> None:
    """Take the receive hook off the modem if this entry owned it; best effort."""
    if not receives(entry):
        return
    modem = U5GModem(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PRIVATE_KEY],
        entry.data[CONF_HOST_KEY],
    )
    try:
        await modem.remove_hook()
    except U5GError as err:
        _LOGGER.warning("Could not remove the receive hook from %s: %s", entry.data[CONF_HOST], err)
    finally:
        await modem.close()


async def async_unload_entry(hass: HomeAssistant, entry: UnifiSmsConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.modem.close()
    return unloaded
