"""Run the hook scripts against a stand-in event script in a temp dir."""

import subprocess

import pytest

from custom_components.unifi_sms import hook

# Minimal stand-in for the firmware's uiwwand_event.sh, with the same SMS block shape.
EVENT_SCRIPT = """\
#!/bin/sh
[ "$1" = "sms" ] && {
    sms="$(cat -)"
    echo "Received SMS: $sms" > /dev/null
}
"""


@pytest.fixture
def modem_fs(tmp_path):
    event = tmp_path / "uiwwand_event.sh"
    event.write_text(EVENT_SCRIPT)
    event.chmod(0o755)
    paths = {
        hook.EVENT_SCRIPT: str(event),
        hook.SPOOL_SCRIPT: str(tmp_path / "unifi_sms_spool.sh"),
        hook.SPOOL_DIR: str(tmp_path / "spool"),
    }

    def localize(script: str) -> str:
        for remote, local in paths.items():
            script = script.replace(remote, local)
        return script

    def run(script: str, stdin: str | None = None, *args: str) -> str:
        return subprocess.run(
            ["sh", "-c", localize(script), "sh", *args], input=stdin, capture_output=True, text=True, check=True
        ).stdout

    return tmp_path, event, run, localize


def test_install_is_idempotent_and_uninstall_restores(modem_fs):
    _, event, run, _ = modem_fs
    assert run(hook.INSTALL_SCRIPT).strip() == hook.RESULT_INSTALLED
    assert run(hook.INSTALL_SCRIPT).strip() == hook.RESULT_PRESENT
    lines = event.read_text().splitlines()
    assert lines[3].endswith(hook.MARKER)
    assert lines[2] == '    sms="$(cat -)"'
    assert run(hook.UNINSTALL_SCRIPT).strip() == "removed"
    assert event.read_text() == EVENT_SCRIPT


def test_missing_anchor_is_reported(modem_fs):
    _, event, run, _ = modem_fs
    event.write_text("#!/bin/sh\necho changed firmware\n")
    assert run(hook.INSTALL_SCRIPT).strip() == hook.RESULT_NO_ANCHOR
    assert hook.MARKER not in event.read_text()


def test_spool_roundtrip(modem_fs):
    tmp_path, _, run, localize = modem_fs
    run(hook.INSTALL_SCRIPT)
    message = '{"id":"a-1","from":"+48111111111","text":"zażółć \\"x\\"","timestamp":1,"iccid":"x"}'
    subprocess.run(["sh", localize(hook.EVENT_SCRIPT), "sms"], input=message, text=True, check=True)
    records = hook.parse_spool(run(hook.READ_COMMAND))
    assert len(records) == 1
    name, parsed = records[0]
    assert parsed["text"] == 'zażółć "x"'
    run(hook.delete_command([name]))
    assert list((tmp_path / "spool").iterdir()) == []


def test_parse_spool_skips_bad_names_and_marks_bad_json():
    out = "\x1e1-2.json\n{\"id\": \"a\"}\n\x1e../etc.json\n{}\n\x1e3-4.json\nnot json\n"
    assert hook.parse_spool(out) == [("1-2.json", {"id": "a"}), ("3-4.json", None)]


def test_delete_command_only_touches_spool_names():
    assert hook.delete_command(["1-2.json", "../x.json", "*.json"]) == f"cd {hook.SPOOL_DIR} && rm -f -- 1-2.json"
    assert hook.delete_command(["; rm -rf /"]) == "true"
