"""Keep :class:`PartyServer` alive with an outer monitor thread.

If the serve thread dies or the listen socket stops accepting, the watchdog
stops the dead instance and starts it again. Intentional ``watchdog.stop()``
disables restarts.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any, Optional

from .server import PartyServer

_log = logging.getLogger("websocket.watchdog")


class PartyServerWatchdog:
    """Supervise one :class:`PartyServer` on a background monitor thread."""

    def __init__(
        self,
        server: Optional[PartyServer] = None,
        *,
        host: str = "0.0.0.0",
        port: int = 8765,
        check_interval_s: float = 1.0,
        restart_delay_s: float = 0.5,
        unhealthy_grace_s: float = 2.0,
        probe_port: bool = False,
        **server_kwargs: Any,
    ) -> None:
        if server is None:
            server = PartyServer(host=host, port=port, **server_kwargs)
        self.server = server
        self.check_interval_s = max(0.2, float(check_interval_s))
        self.restart_delay_s = max(0.1, float(restart_delay_s))
        self.unhealthy_grace_s = max(0.0, float(unhealthy_grace_s))
        self.probe_port = bool(probe_port)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._restart_count = 0
        self._last_ok_at = 0.0
        self._unhealthy_since = 0.0
        self._last_error = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def status(self) -> dict[str, Any]:
        snap = self.server.status()
        snap.update(
            {
                "watchdog_running": self.running,
                "restarts": self._restart_count,
                "last_ok_at": self._last_ok_at,
                "watchdog_error": self._last_error,
            }
        )
        return snap

    def start(self, *, timeout: float = 5.0) -> PartyServer:
        """Start the server (if needed) and the keep-alive monitor thread."""
        if self.running:
            return self.server
        self._stop.clear()
        self._last_error = ""
        if not self.server.running:
            self.server.start(timeout=timeout)
        self._last_ok_at = time.time()
        self._unhealthy_since = 0.0
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"party-ws-watchdog:{self.server.port}",
            daemon=True,
        )
        self._thread.start()
        _log.info(
            "party watchdog started host=%s port=%s interval=%.1fs",
            self.server.host,
            self.server.port,
            self.check_interval_s,
        )
        self._log_status("watchdog_started")
        return self.server

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop monitor first (no more restarts), then stop the server."""
        self._log_status("watchdog_stopping")
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, float(timeout)))
        self._thread = None
        self.server.stop(timeout=timeout)
        self._log_status("watchdog_stopped")

    def _log_status(self, event: str) -> None:
        snap = self.status()
        _log.info(
            "party watchdog status event=%s server_running=%s listening=%s "
            "clients=%s restarts=%s err=%s",
            event,
            snap.get("running"),
            snap.get("listening"),
            snap.get("clients"),
            snap.get("restarts"),
            snap.get("watchdog_error") or snap.get("last_error") or "-",
        )

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                healthy, reason = self._health_check()
                if healthy:
                    self._last_ok_at = time.time()
                    self._unhealthy_since = 0.0
                    self._last_error = ""
                else:
                    now = time.time()
                    if self._unhealthy_since <= 0.0:
                        self._unhealthy_since = now
                        _log.warning(
                            "party watchdog unhealthy: %s (grace=%.1fs)",
                            reason,
                            self.unhealthy_grace_s,
                        )
                        self._log_status("watchdog_unhealthy")
                    elif (now - self._unhealthy_since) >= self.unhealthy_grace_s:
                        self._fix(reason)
            except Exception as exc:
                self._last_error = str(exc)
                _log.exception("party watchdog monitor error")
                self._log_status("watchdog_monitor_error")
                if not self._stop.is_set():
                    time.sleep(self.restart_delay_s)
                    self._fix(f"monitor_error:{exc}")
            self._stop.wait(self.check_interval_s)
        _log.info("party watchdog monitor exit port=%s", self.server.port)

    def _health_check(self) -> tuple[bool, str]:
        if self._stop.is_set():
            return True, "stopping"
        if not self.server.running:
            return False, "server_thread_dead"
        if not self.server.listening:
            return False, "not_listening"
        if self.probe_port and not self._port_accepts():
            return False, "port_not_accepting"
        return True, "ok"

    def _port_accepts(self) -> bool:
        host = self.server.host
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        try:
            with socket.create_connection((host, self.server.port), timeout=0.5):
                return True
        except OSError:
            return False

    def _fix(self, reason: str) -> None:
        if self._stop.is_set():
            return
        self._last_error = reason
        self._restart_count += 1
        _log.warning(
            "party watchdog restart #%s reason=%s delay=%.1fs",
            self._restart_count,
            reason,
            self.restart_delay_s,
        )
        self._log_status("watchdog_restart")
        try:
            self.server.stop(timeout=3.0)
        except Exception as exc:
            _log.warning("party watchdog stop-before-restart failed: %s", exc)
        if self._stop.is_set():
            return
        time.sleep(self.restart_delay_s)
        if self._stop.is_set():
            return
        try:
            self.server.start(timeout=5.0)
            self._last_ok_at = time.time()
            self._unhealthy_since = 0.0
            self._last_error = ""
            _log.info(
                "party watchdog recovered listening=%s epoch=%s",
                self.server.listening,
                self.server.status().get("listen_epoch"),
            )
            self._log_status("watchdog_recovered")
        except Exception as exc:
            self._last_error = str(exc)
            self._unhealthy_since = time.time()
            _log.error("party watchdog restart failed: %s", exc)
            self._log_status("watchdog_restart_failed")


__all__ = ["PartyServerWatchdog"]
