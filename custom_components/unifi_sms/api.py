"""SSH client for the uiwwand daemon on a UniFi U5G modem."""

from __future__ import annotations

import asyncio
import json
import logging

import asyncssh

from . import hook
from .sms import ubus_command

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 60


class U5GError(Exception):
    """The modem reported a failure or returned something unexpected."""


class U5GConnectionError(U5GError):
    """The modem could not be reached."""


class U5GAuthError(U5GError):
    """The modem rejected the client key."""


class U5GHostKeyError(U5GError):
    """The modem presented a different host key than the pinned one."""


def generate_key() -> tuple[str, str]:
    """Return a new (private OpenSSH, public OpenSSH) ed25519 key pair."""
    key = asyncssh.generate_private_key("ssh-ed25519", comment="home-assistant-unifi-sms")
    return key.export_private_key().decode(), key.export_public_key().decode().strip()


def public_key_of(private_key: str) -> str:
    return asyncssh.import_private_key(private_key).export_public_key().decode().strip()


def fingerprint(public_key: str) -> str:
    """SHA256 fingerprint as printed by ssh-keygen -l."""
    return asyncssh.import_public_key(public_key).get_fingerprint("sha256")


class U5GModem:
    """One SSH connection to the modem, reopened on demand."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        private_key: str,
        host_key: str | None,
        install_hook: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._client_key = asyncssh.import_private_key(private_key)
        self._host_key = host_key
        self._conn: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()
        self._install_hook = install_hook
        self.hook_state: str | None = None

    async def _connect(self) -> asyncssh.SSHClientConnection:
        # Without a pinned host key (first contact in the config flow) any key is accepted
        # and the caller stores it via server_host_key().
        known_hosts = ([asyncssh.import_public_key(self._host_key)], [], []) if self._host_key else None
        try:
            return await asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                client_keys=[self._client_key],
                known_hosts=known_hosts,
                config=None,
                agent_path=None,
                connect_timeout=CONNECT_TIMEOUT,
                keepalive_interval=30,
            )
        except asyncssh.PermissionDenied as err:
            raise U5GAuthError(str(err)) from err
        except asyncssh.HostKeyNotVerifiable as err:
            raise U5GHostKeyError(str(err)) from err
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as err:
            raise U5GConnectionError(f"{self._host}:{self._port}: {err}") from err

    async def _ensure(self) -> asyncssh.SSHClientConnection:
        if self._conn is None or self._conn.is_closed():
            conn = await self._connect()
            if self._install_hook:
                try:
                    await self._ensure_hook(conn)
                except U5GError:
                    conn.close()
                    raise
            self._conn = conn
        return self._conn

    async def _ensure_hook(self, conn: asyncssh.SSHClientConnection) -> None:
        """(Re)install the receive hook; a new connection may follow a modem reboot."""
        try:
            result = await conn.run("sh -s", input=hook.INSTALL_SCRIPT, check=False, timeout=COMMAND_TIMEOUT)
        except (asyncssh.Error, OSError) as err:
            raise U5GConnectionError(f"install hook: {err}") from err
        state = (result.stdout if isinstance(result.stdout, str) else "").strip()
        if state != self.hook_state:
            log = _LOGGER.warning if state not in (hook.RESULT_INSTALLED, hook.RESULT_PRESENT) else _LOGGER.debug
            log("Receive hook on %s: %s %s", self._host, state or "failed", result.stderr or "")
        self.hook_state = state

    def server_host_key(self) -> str:
        """Host key of the open connection, in OpenSSH public key format."""
        if self._conn is None:
            raise U5GError("not connected")
        return self._conn.get_server_host_key().export_public_key().decode().strip()

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _run(self, command: str, label: str, stdin: str | None = None) -> asyncssh.SSHCompletedProcess:
        async with self._lock:
            for attempt in (1, 2):
                conn = await self._ensure()
                try:
                    return await conn.run(command, input=stdin, check=False, timeout=COMMAND_TIMEOUT)
                except (asyncssh.Error, OSError) as err:
                    # A dropped keepalive connection surfaces here; reconnect once.
                    self._conn = None
                    if attempt == 2:
                        raise U5GConnectionError(f"{label}: {err}") from err
                    _LOGGER.debug("Reconnecting after %s failed: %s", label, err)
        raise AssertionError("unreachable")

    async def call(self, method: str, params: dict | None = None) -> dict:
        result = await self._run(ubus_command(method, params, timeout=COMMAND_TIMEOUT - 5), method)
        out = result.stdout if isinstance(result.stdout, str) else ""
        if result.exit_status != 0:
            raise U5GError(f"{method}: ubus exited {result.exit_status}: {result.stderr!s}".strip())
        try:
            data = json.loads(out)
        except json.JSONDecodeError as err:
            raise U5GError(f"{method}: unexpected output {out!r}") from err
        if "error" in data:
            # uiwwand only logs the reason (logread), the reply is just {"error": -1}.
            raise U5GError(f"{method} failed with {data['error']} (see `logread` on the modem)")
        return data.get("result", {})

    async def send_part(self, to: str, text: str, iccid: str | None = None) -> None:
        """Send one SMS; the caller splits text to fit MAX_TEXT_BYTES."""
        params = {"to": to, "text": text}
        if iccid:
            params["iccid"] = iccid
        await self.call("send-sms", params)

    async def system_info(self) -> dict[str, str]:
        """UniFi firmware version and board name, e.g. 5G-Link.7.5.3 / U5G-Max-Outdoor."""
        result = await self._run(
            "cat /etc/version; echo; grep '^board.name=' /etc/board.info 2>/dev/null", "system info"
        )
        lines = [line.strip() for line in str(result.stdout or "").splitlines() if line.strip()]
        info: dict[str, str] = {}
        for line in lines:
            if line.startswith("board.name="):
                info["model"] = line.partition("=")[2]
            elif "version" not in info:
                info["version"] = line
        return info

    async def read_spool(self) -> list[tuple[str, dict | None]]:
        """Messages spooled by the receive hook, oldest first. Delete them with ack_spool()."""
        result = await self._run(hook.READ_COMMAND, "read spool")
        records = hook.parse_spool(result.stdout if isinstance(result.stdout, str) else "")
        return sorted(records, key=lambda record: record[0])

    async def ack_spool(self, names: list[str]) -> None:
        await self._run(hook.delete_command(names), "ack spool")

    async def remove_hook(self) -> None:
        await self._run("sh -s", "remove hook", stdin=hook.UNINSTALL_SCRIPT)

    async def sim_state(self) -> dict:
        return await self.call("get-sim-state")

    async def device_info(self) -> dict:
        return await self.call("get-device-info")
