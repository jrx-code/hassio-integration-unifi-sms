"""Pure helpers for SMS text handling (no Home Assistant or SSH imports)."""

from __future__ import annotations

import json
import re
import shlex
import unicodedata

from .const import MAX_TEXT_BYTES

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def split_text(text: str, limit: int = MAX_TEXT_BYTES) -> list[str]:
    """Split text into chunks of at most `limit` UTF-8 bytes, preferring word boundaries."""
    if limit < 4:
        raise ValueError("limit must fit at least one UTF-8 character")
    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate.encode()) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        # A single word longer than the limit is cut at character boundaries.
        while len(word.encode()) > limit:
            cut = limit
            while len(word[:cut].encode()) > limit:
                cut -= 1
            chunks.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        chunks.append(current)
    return chunks


def normalize_number(number: str) -> str:
    """Strip spaces and dashes and require E.164 (+ and country code)."""
    cleaned = re.sub(r"[\s\-()]", "", number)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not _E164.match(cleaned):
        raise ValueError(f"not an E.164 number: {number!r}")
    return cleaned


def parse_recipients(value: str | list[str] | None) -> list[str]:
    """Accept a list or a comma/semicolon/newline separated string."""
    if not value:
        return []
    items = value if isinstance(value, list) else re.split(r"[,;\n]", value)
    return [normalize_number(item) for item in items if item.strip()]


_ASCII_MAP = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ø": "o",
        "Ø": "O",
        "ß": "ss",
        "“": '"',
        "”": '"',
        "„": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "…": "...",
        " ": " ",
    }
)


def to_ascii(text: str) -> str:
    """Drop diacritics (zażółć -> zazolc) so every character costs one byte of the 64-byte limit."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_ASCII_MAP))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.encode("ascii", "replace").decode("ascii")


def is_trusted(sender: str | None, trusted: list[str]) -> bool:
    """True when the sender's number is on the list; alphanumeric senders never match."""
    if not sender or not trusted:
        return False
    try:
        return normalize_number(sender) in trusted
    except ValueError:
        return False


def ubus_command(method: str, params: dict | None = None, timeout: int = 60) -> str:
    """Remote shell command for one uiwwand ubus method."""
    payload = json.dumps({"method": method, "params": params or {}}, ensure_ascii=False)
    return f"ubus -t {int(timeout)} call uiwwand call {shlex.quote(payload)}"
