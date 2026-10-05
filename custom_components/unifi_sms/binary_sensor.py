"""Connectivity of the SSH link to the modem."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import fingerprint
from .const import CONF_HOST_KEY
from .coordinator import UnifiSmsConfigEntry
from .entity import UnifiSmsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiSmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([UnifiSmsConnection(entry.runtime_data, "connection")])


class UnifiSmsConnection(UnifiSmsEntity, BinarySensorEntity):
    """On while polling the modem works; attributes say where and how it connects."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.config_entry.data
        try:
            host_key = fingerprint(data[CONF_HOST_KEY])
        except Exception:  # noqa: BLE001 - only informational
            host_key = None
        return {
            "host": data[CONF_HOST],
            "port": data[CONF_PORT],
            "username": data[CONF_USERNAME],
            "host_key_fingerprint": host_key,
            "receive_hook": self.coordinator.modem.hook_state,
        }
