# UniFi 5G SMS for Home Assistant

**English** | [Polski](README.pl.md)

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
- Device SSH enabled in UniFi Network: UniFi Devices → Device Updates and Settings
  (bottom left) → Device SSH Settings → Device SSH Authentication. On UniFi Network
  older than 9.2.87 it is Settings → System → Advanced → Device Authentication. It
  applies to all adopted devices; key-only is recommended.
- Home Assistant able to reach the modem's IP on port 22. On a UDM the modem sits on
  an internal network that is routed from the LAN.

## Installation

HACS → Integrations → ⋮ → Custom repositories → add this repository as an
*Integration*, install **UniFi 5G SMS**, restart Home Assistant.

## Setup

1. Settings → Devices & services → Add integration → **UniFi 5G SMS**.
2. **Modem IP address**: UniFi Network → UniFi Devices → the 5G modem → Overview →
   IP Address. **Device SSH username**: the Device SSH Settings page above. Leave the
   private key empty and the integration generates one.
3. Add the shown public key under Device SSH Settings → SSH Keys. Provisioning to the
   modem takes up to a minute. Submit. If the login fails, the same screen lets you
   fix the address or the username; the key stays the same.

Home Assistant then connects straight to the modem over SSH and keeps the connection
open. The modem's host key is pinned on first contact; if it changes, the integration
asks to re-authenticate and only accepts the new key when you tick the box.

If the modem's IP or the username changes later: the integration's ⋮ menu →
**Reconfigure**. The key and the pinned host key stay.

Where it connects and whether it works is visible on the device page: the
*Modem connection* sensor (host, port, user, host key fingerprint) and the *Receive
hook* sensor. **Download diagnostics** gives the same with keys and numbers redacted.

## Options

| Option | |
|---|---|
| Default recipients | numbers the notify entity sends to |
| Trusted senders | incoming SMS get `trusted: true/false`; check it in automations that act on SMS commands |
| Ignore SMS from other senders | untrusted SMS fire no event and do not update the last SMS sensor |
| Daily SMS limit | maximum SMS parts per day (0 = none); sending beyond it fails instead of running up the bill |
| Send without diacritics | `zażółć` → `zazolc`; every character then takes one of the 64 bytes |
| Send from SIM (ICCID) | empty = active SIM |

## Entities and actions

| | |
|---|---|
| `notify.<name>_sms` | sends to the default recipients from the options |
| `event.<name>_sms_received` | fires `received` with `from`, `text`, `timestamp`, `iccid`, `trusted` |
| `sensor.<name>_last_sms` | text of the newest SMS (state cut at 255 characters, full text in `text`), kept across restarts |
| `sensor.<name>_sms_sent_today`, `..._sms_sent_this_month` | SMS parts sent, for the operator's bill |
| `binary_sensor.<name>_modem_connection` | SSH link up; host, port, user, host key fingerprint (diagnostic) |
| `sensor.<name>_receive_hook` | `active`, `anchor_missing` or `failed` (diagnostic) |
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
      trusted: true
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
- **One Home Assistant instance per modem.** The receive spool is shared, so two
  instances connected to the same modem would each get only part of the messages.
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
