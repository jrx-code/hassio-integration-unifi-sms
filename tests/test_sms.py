import json
import shlex

import pytest

from custom_components.unifi_sms.const import MAX_TEXT_BYTES
from custom_components.unifi_sms.sms import normalize_number, parse_recipients, split_text, ubus_command


def test_short_text_is_one_part():
    assert split_text("Test SMS") == ["Test SMS"]


def test_parts_respect_byte_limit():
    text = "Brama otwarta. " * 20
    parts = split_text(text)
    assert len(parts) > 1
    assert all(len(p.encode()) <= MAX_TEXT_BYTES for p in parts)
    assert " ".join(parts) == " ".join(text.split())


def test_limit_counts_utf8_bytes_not_characters():
    # 40 two-byte characters = 80 bytes, must not fit in one 64-byte part.
    assert [len(p.encode()) for p in split_text("ł" * 40)] == [64, 16]


def test_long_word_is_cut():
    assert split_text("x" * 130) == ["x" * 64, "x" * 64, "xx"]


def test_empty_text_has_no_parts():
    assert split_text("   ") == []


def test_tiny_limit_rejected():
    with pytest.raises(ValueError):
        split_text("abc", limit=3)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("+48 123 456 789", "+48123456789"), ("0048-123-456-789", "+48123456789"), ("+1 (555) 0100123", "+15550100123")],
)
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


@pytest.mark.parametrize("raw", ["123456789", "+48", "+48abc123456", ""])
def test_normalize_number_rejects(raw):
    with pytest.raises(ValueError):
        normalize_number(raw)


def test_parse_recipients():
    assert parse_recipients("+48123456789, +48 987 654 321;\n") == ["+48123456789", "+48987654321"]
    assert parse_recipients(["+48123456789"]) == ["+48123456789"]
    assert parse_recipients(None) == []


def test_ubus_command_is_shell_safe():
    cmd = ubus_command("send-sms", {"to": "+48123456789", "text": "it's \"quoted\" $HOME"})
    argv = shlex.split(cmd)
    assert argv[:6] == ["ubus", "-t", "60", "call", "uiwwand", "call"]
    assert json.loads(argv[6]) == {
        "method": "send-sms",
        "params": {"to": "+48123456789", "text": "it's \"quoted\" $HOME"},
    }


def test_to_ascii():
    from custom_components.unifi_sms.sms import to_ascii

    assert to_ascii("Zażółć GĘŚLĄ JAŹŃ, Łódź") == "Zazolc GESLA JAZN, Lodz"
    assert to_ascii("„a” ‘b’ – c — d…") == '"a" \'b\' - c - d...'
    assert to_ascii("emoji 🙂") == "emoji ?"


def test_is_trusted():
    from custom_components.unifi_sms.sms import is_trusted

    trusted = ["+48111111111"]
    assert is_trusted("+48111111111", trusted)
    assert is_trusted("0048 111 111 111", trusted)
    assert not is_trusted("+48222222222", trusted)
    assert not is_trusted("Vikingowie", trusted)
    assert not is_trusted("+48111111111", [])
