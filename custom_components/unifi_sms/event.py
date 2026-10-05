"""Event entity firing for every incoming SMS."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UnifiSmsConfigEntry
from .entity import UnifiSmsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiSmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([UnifiSmsReceivedEvent(entry.runtime_data, "received")])


class UnifiSmsReceivedEvent(UnifiSmsEntity, EventEntity):
    _attr_event_types = ["received"]

    @callback
    def _handle_coordinator_update(self) -> None:
        for message in self.coordinator.data.new_messages:
            self._trigger_event(
                "received",
                {
                    "from": message.get("from"),
                    "text": message.get("text"),
                    "timestamp": message.get("timestamp"),
                    "iccid": message.get("iccid"),
                },
            )
        super()._handle_coordinator_update()
