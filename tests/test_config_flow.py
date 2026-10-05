from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_sms.api import U5GAuthError, U5GHostKeyError
from custom_components.unifi_sms.const import CONF_HOST_KEY, CONF_PRIVATE_KEY, CONF_RECIPIENTS, DOMAIN

from .conftest import HOST_KEY, IMEI, PRIVATE_KEY, PUBLIC_KEY

USER_INPUT = {"host": "10.0.0.2", "port": 22, "username": "admin"}


async def test_generated_key_flow(hass, modem):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "authorize"
    public_key = result["description_placeholders"]["public_key"]
    assert public_key.startswith("ssh-ed25519 ")

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "UniFi 5G SMS (Test Mobile)"
    assert result["result"].unique_id == IMEI
    assert result["data"][CONF_HOST_KEY] == HOST_KEY
    assert result["data"][CONF_PRIVATE_KEY].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


async def test_own_key_connects_directly(hass, modem):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PRIVATE_KEY: PRIVATE_KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRIVATE_KEY] == PRIVATE_KEY


async def test_bad_key_text(hass, modem):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PRIVATE_KEY: "not a key"}
    )
    assert result["errors"] == {CONF_PRIVATE_KEY: "invalid_key"}


async def test_rejected_key_then_retry(hass, modem):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    modem.device_info.side_effect = U5GAuthError("denied")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "authorize"
    assert result["errors"] == {"base": "invalid_auth"}

    modem.device_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_aborts(hass, modem):
    MockConfigEntry(domain=DOMAIN, unique_id=IMEI, data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PRIVATE_KEY: PRIVATE_KEY}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=IMEI,
        title="UniFi 5G SMS (Test Mobile)",
        data={**USER_INPUT, CONF_PRIVATE_KEY: PRIVATE_KEY, CONF_HOST_KEY: "ssh-ed25519 OLD"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reauth_keeps_pin_unless_accepted(hass, modem):
    entry = _entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["public_key"] == PUBLIC_KEY

    modem.device_info.side_effect = U5GHostKeyError("changed")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"accept_new_host_key": False})
    assert result["errors"] == {"base": "host_key_changed"}

    modem.device_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"accept_new_host_key": True})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_HOST_KEY] == HOST_KEY


async def test_options_validate_numbers(hass, modem):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_RECIPIENTS: "12345"})
    assert result["errors"] == {CONF_RECIPIENTS: "invalid_number"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_RECIPIENTS: "+48 123 456 789"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RECIPIENTS] == "+48123456789"
