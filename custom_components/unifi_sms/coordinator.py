"""Polls the modem for incoming SMS and SIM state, and owns sending (limits, counters)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import U5GError, U5GModem
from .const import (
    CONF_ASCII_ONLY,
    CONF_DAILY_LIMIT,
    CONF_ICCID,
    CONF_MODE,
    CONF_ONLY_TRUSTED,
    CONF_TRUSTED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_SMS_RECEIVED,
    MODE_SEND_RECEIVE,
    SEEN_IDS_LIMIT,
)
from .sms import is_trusted, parse_recipients, split_text, to_ascii

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
        self.system: dict[str, str] = {}
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.seen")
        self._seen: list[str] = []
        self._sent: dict = {}
        self._sim: dict = {}
        self._sim_age = SIM_REFRESH
        # Fixed for the lifetime of the entry; a mode change reloads it.
        self.receive = entry.options.get(CONF_MODE, MODE_SEND_RECEIVE) == MODE_SEND_RECEIVE

    @property
    def iccid(self) -> str | None:
        return self.config_entry.options.get(CONF_ICCID) or None

    @property
    def trusted_senders(self) -> list[str]:
        try:
            return parse_recipients(self.config_entry.options.get(CONF_TRUSTED))
        except ValueError:
            return []

    async def _async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._seen = list(stored.get("seen", []))
        self._sent = dict(stored.get("sent", {}))
        try:
            self.system = await self.modem.system_info()
        except U5GError as err:
            _LOGGER.debug("Could not read modem system info: %s", err)

    async def _async_save(self) -> None:
        await self._store.async_save({"seen": self._seen, "sent": self._sent})

    # Sent counters -------------------------------------------------------------------------

    def _roll_counters(self) -> None:
        now = dt_util.now()
        day, month = now.date().isoformat(), now.strftime("%Y-%m")
        if self._sent.get("day") != day:
            self._sent.update(day=day, today=0)
        if self._sent.get("month_key") != month:
            self._sent.update(month_key=month, month=0)

    @property
    def sent_today(self) -> int:
        self._roll_counters()
        return self._sent["today"]

    @property
    def sent_month(self) -> int:
        self._roll_counters()
        return self._sent["month"]

    async def async_send(self, numbers: list[str], text: str) -> int:
        """Send text to every number. Returns the SMS part count per recipient."""
        options = self.config_entry.options
        if options.get(CONF_ASCII_ONLY):
            text = to_ascii(text)
        parts = split_text(text)
        if not parts:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="empty_message")
        needed = len(parts) * len(numbers)
        limit = int(options.get(CONF_DAILY_LIMIT) or 0)
        if limit and self.sent_today + needed > limit:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="daily_limit",
                translation_placeholders={"limit": str(limit), "sent": str(self.sent_today), "needed": str(needed)},
            )
        try:
            for number in numbers:
                for part in parts:
                    await self.modem.send_part(number, part, self.iccid)
                    self._roll_counters()
                    self._sent["today"] += 1
                    self._sent["month"] += 1
        except U5GError as err:
            raise HomeAssistantError(f"SMS to {number} failed: {err}") from err
        finally:
            await self._async_save()
            self.async_update_listeners()
        return len(parts)

    # Polling -------------------------------------------------------------------------------

    async def _async_update_data(self) -> UnifiSmsData:
        try:
            if self._sim_age >= SIM_REFRESH:
                self._sim = await self.modem.sim_state()
                self._sim_age = timedelta()
            else:
                self._sim_age += self.update_interval or DEFAULT_SCAN_INTERVAL
            spooled = await self.modem.read_spool() if self.receive else []
        except U5GError as err:
            raise UpdateFailed(str(err)) from err

        trusted = self.trusted_senders
        only_trusted = bool(self.config_entry.options.get(CONF_ONLY_TRUSTED)) and bool(trusted)
        new: list[dict] = []
        fresh_ids: list[str] = []
        for name, message in spooled:
            if message is None:
                _LOGGER.warning("Dropping unreadable spooled SMS %s", name)
                continue
            if not message.get("id") or message["id"] in self._seen:
                continue
            fresh_ids.append(message["id"])
            message = {**message, "trusted": is_trusted(message.get("from"), trusted)}
            if only_trusted and not message["trusted"]:
                _LOGGER.info("Ignoring SMS from untrusted sender %s", message.get("from"))
                continue
            new.append(message)

        if fresh_ids:
            self._seen = (self._seen + fresh_ids)[-SEEN_IDS_LIMIT:]
            # Saved right away: new SMS are rare and a reload must not replay them.
            await self._async_save()
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
                        "trusted": message["trusted"],
                    },
                )
        if spooled:
            # Deleted only after the ids are stored, so a crash in between replays nothing twice.
            try:
                await self.modem.ack_spool([name for name, _ in spooled])
            except U5GError as err:
                _LOGGER.debug("Spool cleanup failed, retrying next poll: %s", err)
        return UnifiSmsData(sim=self._sim, new_messages=new)
