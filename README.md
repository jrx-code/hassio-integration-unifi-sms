# UniFi 5G SMS for Home Assistant

Send and receive SMS in Home Assistant through the cellular modem of a **UniFi U5G**
(tested on U5G-Max-Outdoor, firmware 7.5.3) adopted by a UniFi gateway. No extra
hardware, no cloud SMS provider, and it keeps working when the fixed-line internet
is down.

## How it works

The UniFi UI has no SMS feature, but the modem daemon on the U5G (`uiwwand`) does.
The integration keeps an SSH connection to the modem and:

- **sends** with the daemon's `send-sms` method, split into 64-byte parts (the
  firmware limit);
- **receives** through a one-line hook in the modem's SMS event script, which spools
  each incoming message to `/tmp/unifi_sms`. The integration reads and deletes the
  spool every 15 seconds. The modem's root filesystem lives in RAM, so the hook is
  reinstalled on every new SSH connection, including after a modem reboot. Removing
  the integration takes the hook off again.

Details and firmware quirks: [docs/u5g-sms-internals.md](docs/u5g-sms-internals.md).

## Supported devices

| Device | Status |
|---|---|
| UniFi 5G Max Outdoor (U5G-Max-Outdoor) | **tested**, firmware 7.5.3 |
| UniFi 5G Max (indoor), UniFi 5G Backup (U5G) | expected to work: same `uiwwand` daemon and ubus methods, per a [public write-up](https://gist.github.com/keyz182/96a901d5ba1bf5f4b9701f5eba8729ad); not tested here |
| UniFi LTE Backup Pro (U-LTE-Pro) | not supported: no `uiwwand`. SMS is reachable on the inner Sierra Legato module through a second SSH hop and `cm sms ...` ([example](https://github.com/CppBunny/unifi_sms_gateway)), which would need its own backend |
| UniFi Mobile Router (UMR family) | not supported: no known way to read or send SMS; community requests for the feature have no Ubiquiti answer ([thread](https://community.ui.com/questions/UMR-Industrial-SMS/68d10331-f138-4e4e-90ef-e864eb91a639)) |
| Dream Router 5G Max (UDR-5G-Max) | unknown: built-in modem, no public information on SMS access |

## Requirements

- A U5G adopted in UniFi Network, with an active SIM that has SMS service.
- Device SSH enabled in UniFi Network (Settings → System → Device SSH
  Authentication). This applies to all adopted devices; key-only is recommended.
- Home Assistant able to reach the modem's IP on port 22. On a UDM the modem sits on
  an internal bridge that is routed from the LAN.

## Installation

HACS → Integrations → ⋮ → Custom repositories → add this repository as an
*Integration*, install **UniFi 5G SMS**, restart Home Assistant.

## Setup

1. Settings → Devices & services → Add integration → **UniFi 5G SMS**.
2. Enter the modem IP and the Device SSH username. Leave the private key empty and
   the integration generates one.
3. Add the shown public key in UniFi Network → Device SSH Authentication → SSH keys.
   Provisioning to the modem takes up to a minute. Submit.

The modem's SSH host key is pinned on first contact. If it changes, the integration
asks to re-authenticate and only accepts the new key when you tick the box.

Options: default recipients for the notify entity, and the ICCID of the SIM to send
from (empty = active SIM).

## Entities and actions

| | |
|---|---|
| `notify.<name>_sms` | sends to the default recipients from the options |
| `event.<name>_sms_received` | fires `received` with `from`, `text`, `timestamp`, `iccid` |
| `sensor.<name>_last_sms` | text of the newest SMS (state cut at 255 characters, full text in `text`), kept across restarts |
| `sensor.<name>_active_sim` | operator of the active SIM (diagnostic) |
| `unifi_sms.send` | `to` (number or list), `message`; returns the part count |
| event `unifi_sms_received` | the same data as the event entity, for automations |

```yaml
action: unifi_sms.send
data:
  to: "+48123456789"
  message: "Garage door open for 10 minutes"
```

```yaml
triggers:
  - trigger: event
    event_type: unifi_sms_received
    event_data:
      from: "+48123456789"
actions:
  - action: persistent_notification.create
    data:
      message: "{{ trigger.event.data.text }}"
```

## Known limitations

- **64 bytes per SMS** on the outgoing side (firmware). Longer texts go out as
  several messages.
- **Incoming texts whose length is a multiple of 8 lose their last character**
  (firmware 7.5.3, inside `uiwwand`). `12345678` arrives as `1234567`. For SMS
  commands, avoid such lengths or end the command with a space or a dot.
- Messages that arrive between a modem reboot and Home Assistant's reconnect are
  not spooled.
- A firmware update may change the event script. If the hook cannot be placed, the
  integration logs a warning and keeps sending; receiving stops until it is fixed.

## Development

```sh
pip install pytest pytest-homeassistant-custom-component "asyncssh>=2.21.0" ruff
pytest -q
ruff check .
```

## License

MIT
