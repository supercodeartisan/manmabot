"""Windows inbound allow rules for party LAN discover + WebSocket.

Called when the leader bot starts party mode so nearby browse (UDP) and
member sockets (TCP) work without a manual firewall click. Idempotent:
existing matching rules are left alone. Best-effort — never raises to the
caller; returns short status lines for the party log.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Callable, Optional

from websocket.lan_discover import LAN_DISCOVER_PORT

_log = logging.getLogger("websocket.win_firewall")

RULE_LAN = "Manma Party LAN Discover"
RULE_WS = "Manma Party WebSocket"

LogFn = Callable[[str], None]


def _is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_netsh(args: list[str], *, timeout: float = 8.0) -> tuple[int, str]:
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(
            ["netsh", "advfirewall", "firewall", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creation,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return int(proc.returncode or 0), out


def _rule_exists(name: str) -> bool:
    code, out = _run_netsh(["show", "rule", f"name={name}"])
    if code != 0:
        return False
    text = out.casefold()
    if "no rules match" in text or "지정한 조건과 일치하는 규칙이 없습니다" in out:
        return False
    return name.casefold() in text or "enabled" in text or "사용" in out


def _rule_matches_port(name: str, *, protocol: str, port: int) -> bool:
    code, out = _run_netsh(["show", "rule", f"name={name}", "verbose"])
    if code != 0:
        return False
    text = out.casefold()
    if "no rules match" in text:
        return False
    proto_ok = protocol.casefold() in text
    port_ok = str(int(port)) in out
    return proto_ok and port_ok


def _delete_rule(name: str) -> None:
    _run_netsh(["delete", "rule", f"name={name}"])


def _add_allow(*, name: str, protocol: str, port: int) -> tuple[bool, str]:
    code, out = _run_netsh(
        [
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            f"protocol={protocol}",
            f"localport={int(port)}",
            "profile=any",
            "enable=yes",
        ]
    )
    if code == 0:
        return True, ""
    return False, (out or "netsh failed").strip()[:200]


def ensure_inbound_allow(
    *,
    name: str,
    protocol: str,
    port: int,
) -> str:
    """Ensure one inbound allow rule. Returns a short status phrase."""
    port_i = int(port)
    if port_i < 1 or port_i > 65535:
        return f"{name}: invalid port"
    if _rule_exists(name) and _rule_matches_port(name, protocol=protocol, port=port_i):
        return f"{name}: already allowed ({protocol.upper()}/{port_i})"
    if _rule_exists(name):
        _delete_rule(name)
    ok, err = _add_allow(name=name, protocol=protocol, port=port_i)
    if ok:
        return f"{name}: allowed inbound {protocol.upper()}/{port_i}"
    return f"{name}: failed ({err or 'unknown'})"


def ensure_party_leader_inbound(
    *,
    ws_port: int = 8765,
    discover_port: int = LAN_DISCOVER_PORT,
    log: Optional[LogFn] = None,
) -> list[str]:
    """Ensure UDP discover + TCP WebSocket inbound allows on Windows.

    Non-Windows: no-op. Not elevated: log a one-line skip. Never raises.
    """
    note = log or (lambda _m: None)
    lines: list[str] = []

    def _emit(msg: str) -> None:
        lines.append(msg)
        note(msg)
        _log.info("%s", msg)

    if os.name != "nt":
        return lines
    if not _is_admin():
        _emit(
            "Party firewall: not elevated — open UDP "
            f"{int(discover_port)} and TCP {int(ws_port)} inbound manually, "
            "or restart the bot as administrator."
        )
        return lines
    try:
        _emit(
            ensure_inbound_allow(
                name=RULE_LAN, protocol="UDP", port=int(discover_port)
            )
        )
        _emit(
            ensure_inbound_allow(
                name=RULE_WS, protocol="TCP", port=int(ws_port)
            )
        )
    except Exception as exc:
        _emit(f"Party firewall: skipped ({exc})")
    return lines


__all__ = [
    "RULE_LAN",
    "RULE_WS",
    "ensure_inbound_allow",
    "ensure_party_leader_inbound",
]
