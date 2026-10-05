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
    modem.send_part.assert_awaited_once_with("+48123456789", "Test", "8900")
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
    assert [c.args for c in modem.send_part.await_args_list] == [
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


SENSOR_TODAY = "sensor.unifi_5g_sms_test_mobile_sms_sent_today"
SENSOR_MONTH = "sensor.unifi_5g_sms_test_mobile_sms_sent_this_month"


async def _send(hass, message, to="+48123456789"):
    return await hass.services.async_call(
        DOMAIN, "send", {"to": to, "message": message}, blocking=True, return_response=True
    )


async def test_device_and_diagnostic_entities(hass, modem):
    from homeassistant.helpers import device_registry as dr

    entry = await _setup(hass)
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert (DOMAIN, IMEI) in device.identifiers
    assert device.model == "U5G-Max-Outdoor"
    assert device.sw_version == "5G-Link.7.5.3"

    conn = hass.states.get("binary_sensor.unifi_5g_sms_test_mobile_modem_connection")
    assert conn.state == "on"
    assert conn.attributes["host"] == "10.0.0.2"
    assert conn.attributes["username"] == "admin"
    assert conn.attributes["host_key_fingerprint"].startswith("SHA256:")
    assert hass.states.get("sensor.unifi_5g_sms_test_mobile_receive_hook").state == "active"


async def test_connection_sensor_goes_off_when_polling_fails(hass, modem):
    await _setup(hass)
    modem.read_spool.side_effect = U5GConnectionError("gone")
    await _tick(hass)
    assert hass.states.get("binary_sensor.unifi_5g_sms_test_mobile_modem_connection").state == "off"


async def test_counters_and_daily_limit(hass, modem):
    from homeassistant.exceptions import HomeAssistantError

    await _setup(hass, {"daily_limit": 3})
    response = await _send(hass, "x" * 100)  # 2 parts
    assert response["parts_per_recipient"] == 2
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_TODAY).state == "2"
    assert hass.states.get(SENSOR_MONTH).state == "2"

    with pytest.raises(HomeAssistantError, match="limit"):
        await _send(hass, "x" * 100)  # would make 4 > 3
    assert modem.send_part.await_count == 2

    await _send(hass, "ok")  # 3 == limit
    assert hass.states.get(SENSOR_TODAY).state == "3"


async def test_counters_roll_over_at_midnight(hass, modem, freezer):
    freezer.move_to("2026-10-05 22:00:00+00:00")
    await _setup(hass)
    await _send(hass, "a")
    freezer.move_to("2026-10-06 22:30:00+00:00")
    await _send(hass, "b")
    assert hass.states.get(SENSOR_TODAY).state == "1"
    assert hass.states.get(SENSOR_MONTH).state == "2"


async def test_ascii_only_option(hass, modem):
    await _setup(hass, {"ascii_only": True})
    await _send(hass, "Zażółć gęślą jaźń „cytat” – koniec…")
    modem.send_part.assert_awaited_once_with("+48123456789", 'Zazolc gesla jazn "cytat" - koniec...', None)


async def test_trusted_attribute(hass, modem):
    events = async_capture_events(hass, EVENT_SMS_RECEIVED)
    await _setup(hass, {"trusted_senders": "+48111111111"})
    modem.read_spool.return_value = [("1000-1.json", SMS_1), ("1001-2.json", SMS_2)]
    await _tick(hass)
    assert [(e.data["id"], e.data["trusted"]) for e in events] == [("a-1", True), ("a-2", False)]
    assert hass.states.get("sensor.unifi_5g_sms_test_mobile_last_sms").attributes["trusted"] is False


async def test_only_trusted_drops_others(hass, modem):
    events = async_capture_events(hass, EVENT_SMS_RECEIVED)
    await _setup(hass, {"trusted_senders": "+48111111111", "only_trusted": True})
    modem.read_spool.return_value = [("1000-1.json", SMS_1), ("1001-2.json", SMS_2)]
    await _tick(hass)
    assert [e.data["id"] for e in events] == ["a-1"]
    assert hass.states.get("sensor.unifi_5g_sms_test_mobile_last_sms").attributes["from"] == "+48111111111"
    # The untrusted one is still acknowledged and never replayed.
    modem.ack_spool.assert_awaited_with(["1000-1.json", "1001-2.json"])
    await _tick(hass)
    assert len(events) == 1


async def test_diagnostics_redact(hass, modem):
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.unifi_sms.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass, {"recipients": "+48111111111", "trusted_senders": "+48111111111"})
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"][CONF_PRIVATE_KEY] == REDACTED
    assert diag["entry"]["data"][CONF_HOST_KEY] == REDACTED
    assert diag["entry"]["options"]["recipients"] == REDACTED
    assert diag["modem"]["sim"]["iccid"] == REDACTED
    assert diag["modem"]["system"]["model"] == "U5G-Max-Outdoor"
    assert "+48111111111" not in str(diag)


RECEIVE_ENTITIES = (
    "event.unifi_5g_sms_test_mobile_sms_received",
    "sensor.unifi_5g_sms_test_mobile_last_sms",
    "sensor.unifi_5g_sms_test_mobile_receive_hook",
)


async def test_send_only_mode(hass, modem):
    await _setup(hass, {"mode": "send_only"})
    assert modem.factory.call_args.kwargs["install_hook"] is False
    await _tick(hass)
    modem.read_spool.assert_not_awaited()
    for entity_id in RECEIVE_ENTITIES:
        assert hass.states.get(entity_id) is None
    assert hass.states.get("binary_sensor.unifi_5g_sms_test_mobile_modem_connection").attributes["mode"] == "send_only"
    await _send(hass, "still sends")
    modem.send_part.assert_awaited_once()


async def test_default_mode_receives(hass, modem):
    await _setup(hass)
    assert modem.factory.call_args.kwargs["install_hook"] is True
    for entity_id in RECEIVE_ENTITIES:
        assert hass.states.get(entity_id) is not None


async def test_switch_to_send_only_removes_hook_and_entities(hass, modem):
    from homeassistant.helpers import entity_registry as er

    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"mode": "send_only"})
    await hass.async_block_till_done()
    modem.remove_hook.assert_awaited_once()
    registry = er.async_get(hass)
    for entity_id in RECEIVE_ENTITIES:
        assert registry.async_get(entity_id) is None
    assert entry.state is ConfigEntryState.LOADED

    # And back: the hook is reinstalled with the new connection, entities return.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"mode": "send_receive"})
    await hass.async_block_till_done()
    assert modem.factory.call_args.kwargs["install_hook"] is True
    assert hass.states.get("sensor.unifi_5g_sms_test_mobile_last_sms") is not None
    modem.remove_hook.assert_awaited_once()


async def test_other_option_change_keeps_hook(hass, modem):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"daily_limit": 5})
    await hass.async_block_till_done()
    modem.remove_hook.assert_not_awaited()


async def test_removing_send_only_entry_keeps_hook(hass, modem):
    entry = await _setup(hass, {"mode": "send_only"})
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    modem.remove_hook.assert_not_awaited()
