"""LAN address helpers for the party socket UI. No sockets are left open."""
from __future__ import annotations

import socket
from typing import Iterable, Optional

# Adapter-name markers that are almost never the home/office LAN clients use.
_VPN_MARKERS = (
    "vpn",
    "sstap",
    "tap-windows",
    "tap ",
    "tun",
    "wireguard",
    "wg ",
    "openvpn",
    "nordlynx",
    "nordvpn",
    "expressvpn",
    "astrill",
    "surfshark",
    "mullvad",
    "proton",
    "hamachi",
    "zerotier",
    "tailscale",
    "outline",
    "wintun",
    "cisco anyconnect",
    "globalprotect",
)
_VIRT_MARKERS = (
    "vmware",
    "virtualbox",
    "vbox",
    "hyper-v",
    "vethernet",
    "wsl",
    "docker",
    "virbr",
    "br-",
    "bluetooth",
    "loopback",
)


def _ipv4_parts(ip: str) -> Optional[tuple[int, int, int, int]]:
    text = str(ip or "").strip()
    parts = text.split(".")
    if len(parts) != 4:
        return None
    try:
        nums = tuple(int(p) for p in parts)
    except ValueError:
        return None
    if any(n < 0 or n > 255 for n in nums):
        return None
    return nums  # type: ignore[return-value]


def _is_loopback(ip: str) -> bool:
    return str(ip or "").startswith("127.")


def _is_link_local(ip: str) -> bool:
    return str(ip or "").startswith("169.254.")


def _is_cgnat_or_tailscale(ip: str) -> bool:
    """100.64.0.0/10 — CGNAT / Tailscale-style overlay."""
    parts = _ipv4_parts(ip)
    if parts is None:
        return False
    a, b = parts[0], parts[1]
    return a == 100 and 64 <= b <= 127


def _is_rfc1918(ip: str) -> bool:
    parts = _ipv4_parts(ip)
    if parts is None:
        return False
    a, b = parts[0], parts[1]
    if a == 10:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def _name_penalty(name: str) -> int:
    text = str(name or "").lower()
    if any(m in text for m in _VPN_MARKERS):
        return 10_000
    if any(m in text for m in _VIRT_MARKERS):
        return 5_000
    return 0


def _address_penalty(ip: str) -> int:
    """Lower is better. Prefer typical home LAN ``192.168.*`` over VPN ``10.*``."""
    if _is_loopback(ip) or _is_link_local(ip):
        return 100_000
    if _is_cgnat_or_tailscale(ip):
        return 8_000
    parts = _ipv4_parts(ip)
    if parts is None:
        return 90_000
    a, b, _c, d = parts
    if a == 192 and b == 168:
        # Host .1 is often a VMware/Hyper-V virtual switch, not the PC clients hit.
        return 10 + (40 if d == 1 else 0)
    if a == 172 and 16 <= b <= 31:
        return 200 + (40 if d == 1 else 0)
    if a == 10:
        # Common VPN overlay (SSTAP / OpenVPN). Still usable if nothing else exists.
        return 1_000
    # Public / other — last resort for advertise.
    return 3_000


def _default_route_ipv4() -> Optional[str]:
    """IPv4 the OS would use toward the public internet (often the VPN)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = str(sock.getsockname()[0] or "")
        finally:
            sock.close()
    except OSError:
        return None
    if ip and not _is_loopback(ip):
        return ip
    return None


def _iter_local_ipv4() -> Iterable[tuple[str, str]]:
    """Yield ``(adapter_name, ipv4)`` for configured interfaces."""
    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if st is not None and not bool(getattr(st, "isup", True)):
                continue
            for addr in addrs:
                if getattr(addr, "family", None) != socket.AF_INET:
                    continue
                ip = str(getattr(addr, "address", "") or "")
                if ip:
                    yield str(name), ip
        return
    except Exception:
        pass
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = str(info[4][0] if info and info[4] else "")
            if ip:
                yield "", ip
    except OSError:
        return


def local_ipv4_candidates() -> list[str]:
    """LAN-first IPv4 list other PCs can try (no loopback / link-local)."""
    default = _default_route_ipv4()
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for name, ip in _iter_local_ipv4():
        if ip in seen or _is_loopback(ip) or _is_link_local(ip):
            continue
        seen.add(ip)
        score = _name_penalty(name) + _address_penalty(ip)
        # The internet default route is usually VPN while clients stay on LAN.
        if default and ip == default:
            score += 2_000
        scored.append((score, ip))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [ip for _score, ip in scored]


def local_ipv4() -> str:
    """IPv4 other PCs on this LAN can use to reach this machine.

    Prefers a private LAN adapter (``192.168.*`` Ethernet/Wi-Fi) over the
    default internet route, which is often a VPN (SSTAP / WireGuard / …).
    Falls back to the route address, hostname lookup, then loopback.
    """
    candidates = local_ipv4_candidates()
    if candidates:
        return candidates[0]
    default = _default_route_ipv4()
    if default:
        return default
    try:
        ip = str(socket.gethostbyname(socket.gethostname()) or "")
        if ip and not _is_loopback(ip):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


__all__ = ["local_ipv4", "local_ipv4_candidates"]
