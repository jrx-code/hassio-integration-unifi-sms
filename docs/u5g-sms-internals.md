# UniFi U5G SMS internals

Observed on a **U5G-Max-Outdoor** (model `UMBBE631`, firmware 7.5.3, Sierra Wireless
EM9291 modem) adopted by a UDM Pro Max. Other U5G models share the `uiwwand` daemon,
but nothing below was tested on them.

## Access

The UniFi Network application has no SMS interface, and the controller API exposes
only SIM, APN and radio data. SMS works on the device itself, which needs SSH:

1. UniFi Network → UniFi Devices → Device Updates and Settings → Device SSH Settings
   (Settings → System → Advanced → Device Authentication before 9.2.87). Through the API
   this is `rest/setting/mgmt/<id>` with `x_ssh_enabled`, `x_ssh_keys` and
   `x_ssh_auth_password_enabled`. It is a **site-wide** setting: every adopted
   device accepts SSH afterwards. Prefer key-only.
2. The modem sits on an internal bridge of the gateway,
   so reach it with the gateway as a jump host: `ssh -J <gateway> <user>@<modem-ip>`.
   The user is the "Device SSH" username, not `root`.

## Daemon API

`uiwwand` owns the modem (QMI and AT). Every call goes through ubus:

```sh
ubus -t 60 call uiwwand call '{"method":"<method>","params":{...}}'
```

| Method | Params | Notes |
|---|---|---|
| `send-sms` | `to` (E.164), `text`, optional `iccid` | `{"result":{"send-sms":"ok"}}` on success |
| `get-sms` | none | messages currently held in memory |
| `get-sim-state` | none | active slot, ICCID, SPN, PIN state |

A failed call returns `{"error": -1}`. The reason is only in the syslog
(`logread`), e.g. `daemon.err uiwwand: ctl: send-sms: text too long (83 > 64)`.

## Quirks

### Outgoing text limit: 64 bytes

`send-sms` refuses texts over **64 UTF-8 bytes**. The check counts bytes, not
characters: an 82-character text with one `ł` was rejected as 83. Longer messages
must be split by the caller. Whether non-GSM characters arrive intact on the
recipient side was not tested.

### Incoming texts lose the last character when the length is a multiple of 8

Confirmed with test messages from a phone:

| Sent | Length | Length mod 8 | Received |
|---|---|---|---|
| `12345678` | 8 | 0 | `1234567` |
| `123456789` | 9 | 1 | `123456789` |
| `Test SMS zwrotny` | 16 | 0 | `Test SMS zwrotn` |
| two carrier messages | 106, 149 | 2, 5 | complete |

The text is already truncated in `get-sms`, so the loss happens inside `uiwwand`
when it unpacks GSM 7-bit data: 8 septets fill exactly 7 octets, and the last
septet is treated as padding. Workaround for SMS commands: avoid lengths of
8, 16, 24, ... or end the command with a space or a dot.

### `get-sms` is not a mailbox

Messages stay in the list only for seconds, without a daemon restart (same PID
before and after). Two SMS that reached the modem were never seen by a client
polling `get-sms` every 15 seconds; one of them was already gone 26 seconds after
arrival. The exact retention was not measured. Do not poll it for receiving.

### Receive hook

For every incoming SMS `uiwwand` runs `/etc/mbbcfg/uiwwand_event.sh sms` with a
JSON object on stdin (`id`, `from`, `text`, `timestamp`, `iccid`). The stock script
raises a UniFi alert `EVT_MBB_SMS` and logs `Received SMS <from>: <text>`.

The root filesystem is an overlay whose upper layer is a tmpfs, so edits to the
script work immediately but are gone after a reboot. The integration therefore adds
its line right after `sms="$(cat -)"` on every new SSH connection (idempotent, marker
`# unifi_sms hook`) and removes it, restoring the original file byte for byte, when
the integration is deleted. The hook pipes `$sms` to a helper that writes one JSON
file per message under `/tmp/unifi_sms` (written as `.tmp`, then renamed).

Measured on the tested unit: an SMS logged by the modem at 13:38:57 fired the Home
Assistant event at 13:39:05, with Polish diacritics intact.

### eSIM profiles

On the tested unit, one carrier's eSIM profile carried data but failed SMS in both
directions (`WmsMessageDeliveryFailure`, `+CEER: Service option not supported`).
The physical SIM in slot 1 sends and receives fine. Pass `iccid` to pick the card.

### AT commands

Use `uiwwand-chat -t <seconds> "AT..."`; the daemon owns the AT port. `AT+CMGL`
returns nothing because messages are routed `transfer-and-ack` with no storage.
Do not change the routes.
