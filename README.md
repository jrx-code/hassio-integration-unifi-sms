# UniFi 5G SMS for Home Assistant

Send and receive SMS in Home Assistant through the cellular modem of a **UniFi U5G**
(tested on U5G-Max-Outdoor) adopted by a UniFi gateway. No extra hardware, no cloud
SMS provider, and it keeps working when the fixed-line internet is down.

> **Status:** early. The repo has a tested Python client and CLI. The Home Assistant
> integration (`custom_components/`) is the next step, see the roadmap below.

## How it works

The UniFi UI has no SMS feature, but the modem daemon on the U5G (`uiwwand`) does.
The client logs in over SSH, using the gateway as a jump host, and calls the
daemon's `send-sms` / `get-sms` methods through `ubus`. Details and firmware quirks:
[docs/u5g-sms-internals.md](docs/u5g-sms-internals.md).

## Requirements

- A U5G adopted in UniFi Network, with an active SIM that has SMS service.
- Device SSH enabled in UniFi Network (Settings → System → Device SSH
  Authentication), ideally key-only. This applies to all adopted devices.
- SSH access to the gateway, and from the host running this code to the modem
  with `ssh -J <gateway> <device-ssh-user>@<modem-ip>`.

## CLI

```sh
export U5G_HOST=<modem-ip>        # modem IP behind the gateway
export U5G_USER=<device-ssh-user>
export U5G_JUMP=root@<gateway>    # optional
export U5G_ICCID=<iccid>          # optional, defaults to the active SIM

python -m u5g_sms send +48123456789 "Brama otwarta od 10 minut" --dry-run
python -m u5g_sms send +48123456789 "Brama otwarta od 10 minut"
python -m u5g_sms inbox
python -m u5g_sms sim
```

Texts longer than 64 bytes are split into several SMS on word boundaries.

## Known limitations

- **64-byte limit per SMS** on the outgoing side (firmware). The client splits.
- **Incoming texts whose length is a multiple of 8 lose their last character**
  (firmware 7.5.3). `12345678` arrives as `1234567`.
- `get-sms` holds messages only for a few minutes. Reliable receiving needs the
  event hook on the modem.

## Roadmap

1. Home Assistant integration: config flow (modem host, jump host, SSH key, SIM),
   `notify` entity and a `unifi_sms.send` action.
2. Receiving: event hook on the modem publishing to MQTT, plus an HA event entity.
3. Check that the hook survives modem reboots and firmware updates.
4. HACS packaging.

## Development

```sh
pip install pytest ruff
pytest -q
ruff check .
```

## License

MIT
