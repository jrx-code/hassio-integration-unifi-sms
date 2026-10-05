# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Home Assistant integration `unifi_sms`: SMS through a UniFi U5G modem over SSH
(asyncssh, pinned to the version HA core uses). Firmware findings live in
`docs/u5g-sms-internals.md`; keep it current when behaviour is verified on a device.

```
custom_components/unifi_sms/
├── api.py          # U5GModem: one asyncssh connection, ubus calls, hook install on connect
├── hook.py         # shell scripts for the receive hook + spool parsing (pure)
├── sms.py          # text splitting (64-byte limit), E.164 parsing, ubus command (pure)
├── coordinator.py  # 15 s poll: spool -> events, SIM state every 5 min, seen ids in Store
├── config_flow.py  # key generation, host key pinning, reauth, options (recipients, ICCID)
└── event.py, notify.py, sensor.py, services.yaml
```

## Commands

- Tests: `.venv/bin/pytest -q` (venv: Python 3.14 + pytest-homeassistant-custom-component)
- Lint: `uvx ruff check .`
- `tests/test_hook.py` runs the real install/uninstall scripts against a stand-in event script.

## Rules

- Sending reaches a real phone and costs money. Do not send unless asked.
- Test on the dev HA instance first, production only through HACS releases.
- The hook edits a firmware script on the modem. Any change to `hook.py` must keep
  uninstall restoring the original file byte for byte; verify on a device.
- Public on GitHub: no ICCIDs, IMEIs, phone numbers, device SSH usernames or internal
  hostnames in code, docs, tests or commits. Placeholders only.
- Remotes: `origin` = Forgejo, `github` = public mirror. Commit email is the GitHub
  noreply address (set per repo).
