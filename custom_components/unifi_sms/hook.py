"""Receive hook on the modem.

uiwwand runs /etc/mbbcfg/uiwwand_event.sh for every incoming SMS with the message as
JSON on stdin, but keeps the message readable via get-sms only for a few seconds.
One line added after `sms="$(cat -)"` spools each message to a file under /tmp, which
the integration reads and deletes. The modem's root filesystem is an overlay in RAM,
so the hook is gone after a reboot; it is reinstalled on every new SSH connection.
"""

from __future__ import annotations

import json
import re

EVENT_SCRIPT = "/etc/mbbcfg/uiwwand_event.sh"
SPOOL_SCRIPT = "/etc/mbbcfg/unifi_sms_spool.sh"
SPOOL_DIR = "/tmp/unifi_sms"
MARKER = "# unifi_sms hook"

RESULT_INSTALLED = "installed"
RESULT_PRESENT = "present"
RESULT_NO_ANCHOR = "anchor-missing"

_SPOOL_NAME = re.compile(r"^\d+-\d+\.json$")
_RECORD_SEP = "\x1e"

INSTALL_SCRIPT = f"""\
set -e
F={EVENT_SCRIPT}
H={SPOOL_SCRIPT}
cat > "$H" <<'EOS'
#!/bin/sh
# Installed by the Home Assistant unifi_sms integration: spool one incoming SMS (JSON on stdin).
d={SPOOL_DIR}
mkdir -p "$d"
f="$d/$(date +%s)-$$"
cat > "$f.tmp" && mv "$f.tmp" "$f.json"
EOS
chmod 755 "$H"
if grep -q '{MARKER}' "$F"; then echo {RESULT_PRESENT}; exit 0; fi
grep -q 'sms="$(cat -)"' "$F" || {{ echo {RESULT_NO_ANCHOR}; exit 0; }}
HOOK='    printf "%s" "$sms" | {SPOOL_SCRIPT} {MARKER}'
awk -v hook="$HOOK" '{{print}} index($0, "sms=\\"$(cat -)\\"") && !done {{print hook; done=1}}' "$F" > "$F.new"
sh -n "$F.new"
cat "$F.new" > "$F"
rm "$F.new"
grep -q '{MARKER}' "$F" && echo {RESULT_INSTALLED}
"""

UNINSTALL_SCRIPT = f"""\
F={EVENT_SCRIPT}
if grep -q '{MARKER}' "$F"; then
  grep -v '{MARKER}' "$F" > "$F.new" && sh -n "$F.new" && cat "$F.new" > "$F"
  rm -f "$F.new"
fi
rm -f {SPOOL_SCRIPT}
rm -rf {SPOOL_DIR}
echo removed
"""

READ_COMMAND = (
    f'for f in {SPOOL_DIR}/*.json; do [ -e "$f" ] || continue; '
    'printf "\\036%s\\n" "${f##*/}"; cat "$f"; echo; done'
)


def parse_spool(output: str) -> list[tuple[str, dict | None]]:
    """Split READ_COMMAND output into (file name, message or None if unreadable)."""
    records: list[tuple[str, dict | None]] = []
    for chunk in output.split(_RECORD_SEP):
        if not chunk.strip():
            continue
        name, _, body = chunk.partition("\n")
        name = name.strip()
        if not _SPOOL_NAME.match(name):
            continue
        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            message = None
        records.append((name, message if isinstance(message, dict) else None))
    return records


def delete_command(names: list[str]) -> str:
    """rm for spool files; names are validated so nothing outside the spool can be hit."""
    safe = [n for n in names if _SPOOL_NAME.match(n)]
    if not safe:
        return "true"
    return f"cd {SPOOL_DIR} && rm -f -- " + " ".join(safe)
