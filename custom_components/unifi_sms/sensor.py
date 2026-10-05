"""Sensors: active SIM, last received SMS, receive hook state, sent counters."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import hook
from .coordinator import UnifiSmsConfigEntry, UnifiSmsCoordinator
from .entity import UnifiSmsEntity

# Home Assistant rejects states longer than 255 characters; the full text stays in `text`.
MAX_STATE_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiSmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        UnifiSmsSimSensor(coordinator, "active_sim"),
        UnifiSmsSentSensor(coordinator, "sent_today", lambda c: c.sent_today),
        UnifiSmsSentSensor(coordinator, "sent_month", lambda c: c.sent_month),
    ]
    if coordinator.receive:
        entities += [
            UnifiSmsLastMessageSensor(coordinator, "last_sms"),
            UnifiSmsHookSensor(coordinator, "receive_hook"),
        ]
    async_add_entities(entities)


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
                "trusted": last.attributes.get("trusted"),
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
            "trusted": self._message.get("trusted"),
        }


class UnifiSmsHookSensor(UnifiSmsEntity, SensorEntity):
    """Whether incoming SMS reach Home Assistant (the hook on the modem is in place)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["active", "anchor_missing", "failed"]

    @property
    def native_value(self) -> str | None:
        state = self.coordinator.modem.hook_state
        if state is None:
            return None
        if state in (hook.RESULT_INSTALLED, hook.RESULT_PRESENT):
            return "active"
        if state == hook.RESULT_NO_ANCHOR:
            return "anchor_missing"
        return "failed"


class UnifiSmsSentSensor(UnifiSmsEntity, SensorEntity):
    """SMS parts sent today / this month (what the operator bills)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "SMS"

    def __init__(self, coordinator: UnifiSmsCoordinator, key: str, value) -> None:
        super().__init__(coordinator, key)
        self._value = value

    @property
    def native_value(self) -> int:
        return self._value(self.coordinator)
