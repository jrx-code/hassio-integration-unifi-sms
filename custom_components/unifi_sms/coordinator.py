"""Polls the modem for incoming SMS and SIM state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import U5GError, U5GModem
from .const import CONF_ICCID, DEFAULT_SCAN_INTERVAL, DOMAIN, EVENT_SMS_RECEIVED, SEEN_IDS_LIMIT

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SIM_REFRESH = timedelta(minutes=5)

type UnifiSmsConfigEntry = ConfigEntry[UnifiSmsCoordinator]


@dataclass
class UnifiSmsData:
    sim: dict = field(default_factory=dict)
    new_messages: list[dict] = field(default_factory=list)


class UnifiSmsCoordinator(DataUpdateCoordinator[UnifiSmsData]):
    """Reads the receive hook's spool; see hook.py for why get-sms is not used."""

    config_entry: UnifiSmsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UnifiSmsConfigEntry, modem: U5GModem) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.modem = modem
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.seen")
        self._seen: list[str] = []
        self._sim: dict = {}
        self._sim_age = SIM_REFRESH

    @property
    def iccid(self) -> str | None:
        return self.config_entry.options.get(CONF_ICCID) or None

    async def _async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._seen = list(stored.get("seen", []))

    async def _async_update_data(self) -> UnifiSmsData:
        try:
            if self._sim_age >= SIM_REFRESH:
                self._sim = await self.modem.sim_state()
                self._sim_age = timedelta()
            else:
                self._sim_age += self.update_interval or DEFAULT_SCAN_INTERVAL
            spooled = await self.modem.read_spool()
        except U5GError as err:
            raise UpdateFailed(str(err)) from err

        new: list[dict] = []
        for name, message in spooled:
            if message is None:
                _LOGGER.warning("Dropping unreadable spooled SMS %s", name)
            elif message.get("id") and message["id"] not in self._seen:
                new.append(message)
        if new:
            self._seen = (self._seen + [m["id"] for m in new])[-SEEN_IDS_LIMIT:]
            # Saved right away: new SMS are rare and a reload must not replay them.
            await self._store.async_save({"seen": self._seen})
            for message in new:
                self.hass.bus.async_fire(
                    EVENT_SMS_RECEIVED,
                    {
                        "config_entry_id": self.config_entry.entry_id,
                        "id": message.get("id"),
                        "from": message.get("from"),
                        "text": message.get("text"),
                        "timestamp": message.get("timestamp"),
                        "iccid": message.get("iccid"),
                    },
                )
        if spooled:
            # Deleted only after the ids are stored, so a crash in between replays nothing twice.
            try:
                await self.modem.ack_spool([name for name, _ in spooled])
            except U5GError as err:
                _LOGGER.debug("Spool cleanup failed, retrying next poll: %s", err)
        return UnifiSmsData(sim=self._sim, new_messages=new)
