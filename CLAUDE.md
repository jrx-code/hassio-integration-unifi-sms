# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

SMS for Home Assistant through a UniFi U5G modem. `u5g_sms/` is a stdlib-only client
and CLI that SSHes to the modem (gateway as jump host) and calls `uiwwand` over ubus.
The HA integration under `custom_components/` does not exist yet. Firmware findings:
`docs/u5g-sms-internals.md`; keep it current when behaviour is verified.

## Commands

- Tests: `uvx pytest -q` (no network, no SSH)
- Lint: `uvx ruff check .`
- Read-only live check: `U5G_HOST=... U5G_USER=... U5G_JUMP=... python -m u5g_sms sim`

## Rules

- `send` costs money and reaches a real phone. Use `--dry-run` unless a send was asked for.
- Public on GitHub: no ICCIDs, phone numbers, device SSH usernames or internal
  hostnames in code, docs, tests or commits. Placeholders only.
- Remotes: `origin` = Forgejo, `github` = public mirror. Commit email is the GitHub
  noreply address (set per repo).
