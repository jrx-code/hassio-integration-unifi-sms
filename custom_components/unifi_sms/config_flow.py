"""Config flow: connection, SSH key authorisation, host key pinning."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    U5GAuthError,
    U5GConnectionError,
    U5GError,
    U5GHostKeyError,
    U5GModem,
    generate_key,
    public_key_of,
)
from .const import (
    CONF_ASCII_ONLY,
    CONF_DAILY_LIMIT,
    CONF_HOST_KEY,
    CONF_ICCID,
    CONF_ONLY_TRUSTED,
    CONF_PRIVATE_KEY,
    CONF_RECIPIENTS,
    CONF_TRUSTED,
    DEFAULT_PORT,
    DOMAIN,
)
from .coordinator import UnifiSmsConfigEntry
from .sms import parse_recipients

_LOGGER = logging.getLogger(__name__)

CONF_ACCEPT_HOST_KEY = "accept_new_host_key"


async def _probe(data: dict[str, Any], host_key: str | None) -> tuple[str, dict, dict]:
    """Connect once. Returns (host key, device info, SIM state)."""
    modem = U5GModem(
        data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], data[CONF_PRIVATE_KEY], host_key
    )
    try:
        device = await modem.device_info()
        sim = await modem.sim_state()
        return modem.server_host_key(), device, sim
    finally:
        await modem.close()


def _error_key(err: U5GError) -> str:
    if isinstance(err, U5GAuthError):
        return "invalid_auth"
    if isinstance(err, U5GHostKeyError):
        return "host_key_changed"
    if isinstance(err, U5GConnectionError):
        return "cannot_connect"
    return "unknown"


class UnifiSmsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: UnifiSmsConfigEntry) -> UnifiSmsOptionsFlow:
        return UnifiSmsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_PRIVATE_KEY) or "").strip()
            try:
                if key:
                    key += "\n"
                    public_key_of(key)
            except Exception:  # noqa: BLE001 - asyncssh raises several key parse errors
                errors[CONF_PRIVATE_KEY] = "invalid_key"
            else:
                self._data = {
                    CONF_HOST: user_input[CONF_HOST].strip(),
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PRIVATE_KEY: key or generate_key()[0],
                }
                if key:
                    return await self.async_step_connect()
                return await self.async_step_authorize()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(1, 65535)),
                vol.Required(CONF_USERNAME): str,
                vol.Optional(CONF_PRIVATE_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    def _authorize_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        """Public key to add in UniFi; host, port and user stay editable so a typo
        does not force a new key."""
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT): vol.All(int, vol.Range(1, 65535)),
                vol.Required(CONF_USERNAME): str,
            }
        )
        return self.async_show_form(
            step_id="authorize",
            data_schema=self.add_suggested_values_to_schema(schema, self._data),
            description_placeholders={"public_key": public_key_of(self._data[CONF_PRIVATE_KEY])},
            errors=errors or {},
        )

    async def async_step_authorize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self._authorize_form()
        self._data.update(
            {
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: user_input[CONF_PORT],
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
            }
        )
        return await self.async_step_connect()

    async def async_step_connect(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        try:
            host_key, device, sim = await _probe(self._data, None)
        except U5GError as err:
            _LOGGER.debug("Probe failed: %s", err)
            errors["base"] = _error_key(err)
        else:
            imei = device.get("imei")
            if not imei:
                errors["base"] = "not_a_u5g"
            else:
                await self.async_set_unique_id(imei)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"UniFi 5G SMS ({sim.get('spn') or self._data[CONF_HOST]})",
                    data={**self._data, CONF_HOST_KEY: host_key},
                )
        return self._authorize_form(errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Retry with the stored key; re-pin the host key only when the user says so."""
        errors: dict[str, str] = {}
        if user_input is not None:
            accept = user_input.get(CONF_ACCEPT_HOST_KEY, False)
            pinned = None if accept else self._data.get(CONF_HOST_KEY)
            try:
                host_key, device, _sim = await _probe(self._data, pinned)
            except U5GError as err:
                errors["base"] = _error_key(err)
            else:
                entry = self._get_reauth_entry()
                if device.get("imei") != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST_KEY: host_key})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_ACCEPT_HOST_KEY, default=False): BooleanSelector()}),
            description_placeholders={"public_key": public_key_of(self._data[CONF_PRIVATE_KEY])},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change address, port or user; the key and the pinned host key stay."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **entry.data,
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: user_input[CONF_PORT],
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
            }
            try:
                _host_key, device, _sim = await _probe(data, entry.data[CONF_HOST_KEY])
            except U5GError as err:
                errors["base"] = _error_key(err)
            else:
                if device.get("imei") != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={k: data[k] for k in (CONF_HOST, CONF_PORT, CONF_USERNAME)},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT): vol.All(int, vol.Range(1, 65535)),
                vol.Required(CONF_USERNAME): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or entry.data),
            description_placeholders={"public_key": public_key_of(entry.data[CONF_PRIVATE_KEY])},
            errors=errors,
        )


class UnifiSmsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            numbers: dict[str, list[str]] = {}
            for key in (CONF_RECIPIENTS, CONF_TRUSTED):
                try:
                    numbers[key] = parse_recipients(user_input.get(key, ""))
                except ValueError:
                    errors[key] = "invalid_number"
            if not errors and user_input.get(CONF_ONLY_TRUSTED) and not numbers[CONF_TRUSTED]:
                errors[CONF_TRUSTED] = "trusted_required"
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_RECIPIENTS: ", ".join(numbers[CONF_RECIPIENTS]),
                        CONF_ICCID: (user_input.get(CONF_ICCID) or "").strip(),
                        CONF_TRUSTED: ", ".join(numbers[CONF_TRUSTED]),
                        CONF_ONLY_TRUSTED: bool(user_input.get(CONF_ONLY_TRUSTED)),
                        CONF_DAILY_LIMIT: int(user_input.get(CONF_DAILY_LIMIT) or 0),
                        CONF_ASCII_ONLY: bool(user_input.get(CONF_ASCII_ONLY)),
                    }
                )
        schema = vol.Schema(
            {
                vol.Optional(CONF_RECIPIENTS): str,
                vol.Optional(CONF_TRUSTED): str,
                vol.Optional(CONF_ONLY_TRUSTED, default=False): BooleanSelector(),
                vol.Optional(CONF_DAILY_LIMIT, default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_ASCII_ONLY, default=False): BooleanSelector(),
                vol.Optional(CONF_ICCID): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or self.config_entry.options),
            errors=errors,
        )
