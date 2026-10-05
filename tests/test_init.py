from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events, async_fire_time_changed

from custom_components.unifi_sms.api import U5GAuthError, U5GConnectionError
from custom_components.unifi_sms.const import (
    CONF_HOST_KEY,
    CONF_ICCID,
    CONF_PRIVATE_KEY,
    CONF_RECIPIENTS,
    DOMAIN,
    EVENT_SMS_RECEIVED,
)

from .conftest import HOST_KEY, IMEI, PRIVATE_KEY

SMS_1 = {"id": "a-1", "from": "+48111111111", "text": "Hello", "timestamp": 1000, "iccid": "x"}
SMS_2 = {"id": "a-2", "from": "+48222222222", "text": "World", "timestamp": 1001, "iccid": "x"}


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=IMEI,
        title="UniFi 5G SMS (Test Mobile)",
        data={"host": "10.0.0.2", "port": 22, "username": "admin", CONF_PRIVATE_KEY: PRIVATE_KEY, CONF_HOST_KEY: HOST_KEY},
        options=options or {},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass, modem):
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.unifi_5g_sms_test_mobile_active_sim").state == "Test Mobile"
    assert hass.states.get("event.unifi_5g_sms_test_mobile_sms_received") is not None
    assert hass.states.get("notify.unifi_5g_sms_test_mobile_sms") is not None


async def test_auth_failure_starts_reauth(hass, modem):
    modem.sim_state.side_effect = U5GAuthError("denied")
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_unreachable_retries(hass, modem):
    modem.sim_state.side_effect = U5GConnectionError("timeout")
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_incoming_sms_fires_once(hass, modem):
    events = async_capture_events(hass, EVENT_SMS_RECEIVED)
    await _setup(hass)

    modem.read_spool.return_value = [("1000-1.json", SMS_1)]
    await _tick(hass)
    state = hass.states.get("event.unifi_5g_sms_test_mobile_sms_received")
    assert state.attributes["text"] == "Hello"

    modem.ack_spool.assert_awaited_with(["1000-1.json"])

    # A spool file whose delete failed is read again: no second event.
    modem.read_spool.return_value = [("1000-1.json", SMS_1), ("1001-2.json", SMS_2)]
    await _tick(hass)
    assert [e.data["id"] for e in events] == ["a-1", "a-2"]
    assert hass.states.get("event.unifi_5g_sms_test_mobile_sms_received").attributes["from"] == "+48222222222"


async def test_seen_ids_survive_reload(hass, modem):
    events = async_capture_events(hass, EVENT_SMS_RECEIVED)
    entry = await _setup(hass)
    modem.read_spool.return_value = [("1000-1.json", SMS_1)]
    await _tick(hass)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _tick(hass)
    assert len(events) == 1


async def test_send_action(hass, modem):
    await _setup(hass, {CONF_ICCID: "8900"})
    response = await hass.services.async_call(
        DOMAIN, "send", {"to": "+48 123 456 789", "message": "Test"}, blocking=True, return_response=True
    )
    modem.send.assert_awaited_once_with("+48123456789", "Test", "8900")
    assert response == {"recipients": ["+48123456789"], "parts_per_recipient": 1}


async def test_send_action_rejects_bad_number(hass, modem):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "send", {"to": "123", "message": "Test"}, blocking=True)


async def test_notify_uses_default_recipients(hass, modem):
    await _setup(hass, {CONF_RECIPIENTS: "+48111111111, +48222222222"})
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.unifi_5g_sms_test_mobile_sms", "message": "Alarm", "title": "Garage"},
        blocking=True,
    )
    assert [c.args for c in modem.send.await_args_list] == [
        ("+48111111111", "Garage: Alarm", None),
        ("+48222222222", "Garage: Alarm", None),
    ]


async def test_notify_without_recipients(hass, modem):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "notify", "send_message", {"entity_id": "notify.unifi_5g_sms_test_mobile_sms", "message": "x"}, blocking=True
        )


async def test_unreadable_spool_file_is_dropped(hass, modem):
    events = async_capture_events(hass, EVENT_SMS_RECEIVED)
    await _setup(hass)
    modem.read_spool.return_value = [("1000-1.json", None), ("1001-2.json", SMS_2)]
    await _tick(hass)
    assert [e.data["id"] for e in events] == ["a-2"]
    modem.ack_spool.assert_awaited_with(["1000-1.json", "1001-2.json"])


async def test_remove_entry_takes_hook_off(hass, modem):
    entry = await _setup(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    modem.remove_hook.assert_awaited_once()


async def test_last_sms_sensor(hass, modem):
    await _setup(hass)
    sensor = "sensor.unifi_5g_sms_test_mobile_last_sms"
    assert hass.states.get(sensor).state == "unknown"

    long_text = "x" * 300
    modem.read_spool.return_value = [
        ("1000-1.json", SMS_1),
        ("1001-2.json", {**SMS_2, "text": long_text}),
    ]
    await _tick(hass)
    state = hass.states.get(sensor)
    assert state.state == "x" * 255
    assert state.attributes["text"] == long_text
    assert state.attributes["from"] == "+48222222222"
    assert state.attributes["received"] == "1970-01-01T00:16:41+00:00"

    # No new messages: the sensor keeps the last one.
    modem.read_spool.return_value = []
    await _tick(hass)
    assert hass.states.get(sensor).attributes["from"] == "+48222222222"


async def test_last_sms_sensor_restores(hass, modem):
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    mock_restore_cache(
        hass,
        [
            State(
                "sensor.unifi_5g_sms_test_mobile_last_sms",
                "Hello",
                {"from": "+48111111111", "text": "Hello", "timestamp": 1000, "iccid": "x"},
            )
        ],
    )
    await _setup(hass)
    state = hass.states.get("sensor.unifi_5g_sms_test_mobile_last_sms")
    assert state.state == "Hello"
    assert state.attributes["from"] == "+48111111111"
