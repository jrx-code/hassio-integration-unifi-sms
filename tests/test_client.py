import json
import shlex

import pytest

from u5g_sms.client import MAX_TEXT_BYTES, split_text, ubus_call


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
    parts = split_text("ł" * 40)
    assert [len(p.encode()) for p in parts] == [64, 16]


def test_long_word_is_cut():
    parts = split_text("x" * 130)
    assert parts == ["x" * 64, "x" * 64, "xx"]


def test_empty_text_has_no_parts():
    assert split_text("   ") == []


def test_tiny_limit_rejected():
    with pytest.raises(ValueError):
        split_text("abc", limit=3)


def test_ubus_call_is_shell_safe():
    cmd = ubus_call("send-sms", {"to": "+48123456789", "text": "it's \"quoted\" $HOME"})
    argv = shlex.split(cmd)
    assert argv[:5] == ["ubus", "-t", "60", "call", "uiwwand"]
    assert argv[5] == "call"
    assert json.loads(argv[6]) == {
        "method": "send-sms",
        "params": {"to": "+48123456789", "text": "it's \"quoted\" $HOME"},
    }
