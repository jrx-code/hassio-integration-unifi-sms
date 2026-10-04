"""Send and read SMS on a UniFi U5G modem through its `uiwwand` ubus API over SSH."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

# uiwwand rejects longer texts with `send-sms: text too long (N > 64)`; N is the UTF-8 byte length.
MAX_TEXT_BYTES = 64


class U5GError(RuntimeError):
    """The modem or the SSH transport reported a failure."""


def split_text(text: str, limit: int = MAX_TEXT_BYTES) -> list[str]:
    """Split text into chunks of at most `limit` UTF-8 bytes, preferring word boundaries."""
    if limit < 4:
        raise ValueError("limit must fit at least one UTF-8 character")
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
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


def ubus_call(method: str, params: dict | None = None, timeout: int = 60) -> str:
    """Build the remote shell command for one uiwwand ubus method."""
    payload = json.dumps({"method": method, "params": params or {}}, ensure_ascii=False)
    return f"ubus -t {int(timeout)} call uiwwand call {shlex.quote(payload)}"


@dataclass
class U5GClient:
    """SSH access to the modem, optionally through the UniFi gateway as a jump host."""

    host: str
    user: str = "root"
    jump: str | None = None
    iccid: str | None = None
    ssh_timeout: int = 10

    def _ssh(self, remote_cmd: str) -> str:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.ssh_timeout}"]
        if self.jump:
            cmd += ["-J", self.jump]
        cmd += [f"{self.user}@{self.host}", remote_cmd]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.ssh_timeout + 90)
        if proc.returncode != 0:
            raise U5GError(f"ssh exited {proc.returncode}: {proc.stderr.strip()}")
        return proc.stdout

    def call(self, method: str, params: dict | None = None) -> dict:
        out = self._ssh(ubus_call(method, params))
        try:
            data = json.loads(out)
        except json.JSONDecodeError as err:
            raise U5GError(f"unexpected ubus output: {out!r}") from err
        if "error" in data:
            raise U5GError(f"{method} failed: {data['error']}")
        return data.get("result", {})

    def send(self, to: str, text: str) -> int:
        """Send text to an E.164 number, split into modem-sized parts. Returns the part count."""
        parts = split_text(text)
        if not parts:
            raise ValueError("empty message")
        for part in parts:
            params = {"to": to, "text": part}
            if self.iccid:
                params["iccid"] = self.iccid
            self.call("send-sms", params)
        return len(parts)

    def inbox(self) -> list[dict]:
        """Messages uiwwand currently holds. Not durable: the list empties after a few minutes."""
        return self.call("get-sms").get("sms", [])

    def sim_state(self) -> dict:
        return self.call("get-sim-state")
