"""Sensors: operator of the active SIM, last received SMS."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import UnifiSmsConfigEntry
from .entity import UnifiSmsEntity

# Home Assistant rejects states longer than 255 characters; the full text stays in `text`.
MAX_STATE_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiSmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            UnifiSmsSimSensor(entry.runtime_data, "active_sim"),
            UnifiSmsLastMessageSensor(entry.runtime_data, "last_sms"),
        ]
    )


class UnifiSmsSimSensor(UnifiSmsEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.sim.get("spn")

    @property
    def extra_state_attributes(self) -> dict:
        sim = self.coordinator.data.sim
        return {
            "slot": sim.get("slot"),
            "esim": sim.get("esim"),
            "active": sim.get("active"),
            "iccid": sim.get("iccid"),
        }


class UnifiSmsLastMessageSensor(UnifiSmsEntity, SensorEntity, RestoreEntity):
    """Text of the newest received SMS, kept across restarts."""

    _unrecorded_attributes = frozenset({"text"})

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._message: dict = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and "from" in last.attributes:
            self._message = {
                "from": last.attributes.get("from"),
                "text": last.attributes.get("text", last.state),
                "timestamp": last.attributes.get("timestamp"),
                "iccid": last.attributes.get("iccid"),
            }

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data.new_messages:
            self._message = self.coordinator.data.new_messages[-1]
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> str | None:
        text = self._message.get("text")
        return text[:MAX_STATE_LENGTH] if isinstance(text, str) else None

    @property
    def extra_state_attributes(self) -> dict:
        if not self._message:
            return {}
        timestamp = self._message.get("timestamp")
        received = (
            datetime.fromtimestamp(timestamp, UTC).isoformat() if isinstance(timestamp, (int, float)) else None
        )
        return {
            "from": self._message.get("from"),
            "text": self._message.get("text"),
            "timestamp": timestamp,
            "received": received,
            "iccid": self._message.get("iccid"),
        }
