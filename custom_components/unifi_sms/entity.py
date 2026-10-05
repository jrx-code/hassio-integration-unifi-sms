"""Base entity for the UniFi 5G SMS integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnifiSmsCoordinator


class UnifiSmsEntity(CoordinatorEntity[UnifiSmsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: UnifiSmsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer="Ubiquiti",
            model="UniFi 5G modem",
            name=entry.title,
        )
