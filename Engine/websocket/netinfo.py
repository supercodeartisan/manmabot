"""LAN address helpers for the party socket UI. No sockets are left open."""
from __future__ import annotations

import socket


def local_ipv4() -> str:
    """IPv4 other PCs on this LAN can use to reach this machine.

    Opens a UDP socket and asks the OS which interface would reach a public
    address. Nothing is sent. Falls back to the hostname, then loopback.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = str(sock.getsockname()[0] or "")
        finally:
            sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = str(socket.gethostbyname(socket.gethostname()) or "")
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


__all__ = ["local_ipv4"]
