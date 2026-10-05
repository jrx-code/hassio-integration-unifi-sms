"""Notify entity sending to the default recipients from the options."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import U5GError
from .const import CONF_RECIPIENTS, DOMAIN
from .coordinator import UnifiSmsConfigEntry
from .entity import UnifiSmsEntity
from .sms import parse_recipients


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiSmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([UnifiSmsNotify(entry.runtime_data, "sms")])


class UnifiSmsNotify(UnifiSmsEntity, NotifyEntity):
    async def async_send_message(self, message: str, title: str | None = None) -> None:
        recipients = parse_recipients(self.coordinator.config_entry.options.get(CONF_RECIPIENTS))
        if not recipients:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_recipients"
            )
        text = f"{title}: {message}" if title else message
        for number in recipients:
            try:
                await self.coordinator.modem.send(number, text, self.coordinator.iccid)
            except U5GError as err:
                raise HomeAssistantError(f"SMS to {number} failed: {err}") from err
