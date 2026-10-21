"""Single entry for party communication used by the session.

Holds the leader/member link handles and exposes tick helpers. Wire format and
transport stay in ``Engine/websocket``; this only owns the call surface.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from ..sync import member_states
from . import ingest, link, publish, status
from .orders import member_orders, reset_orders, self_name_from_party

LogFn = Callable[[str], None]


class PartyComms:
    """Process-local party link + publish/ingest helpers."""

    def __init__(self) -> None:
        self._leader: Optional[link.LeaderLink] = None
        self._member: Optional[link.MemberLink] = None
        self._hb_err = ""
        self._reset_member_watch()

    def _reset_member_watch(self) -> None:
        self._was_connected = False
        self._lost_at = 0.0
        self._last_restart_at = 0.0
        self.member_drops = 0
        self.member_restarts = 0

    # --- handles (for monitor / legacy accessors) ---

    @property
    def watchdog(self) -> Any:
        return None if self._leader is None else self._leader.watchdog

    @property
    def client(self) -> Any:
        return None if self._member is None else self._member.client

    @property
    def heartbeat(self) -> Any:
        return None if self._member is None else self._member.heartbeat

    @property
    def server(self) -> Any:
        wd = self.watchdog
        return getattr(wd, "server", None) if wd is not None else None

    @property
    def leader_owned(self) -> bool:
        return bool(self._leader is not None and self._leader.owned)

    # --- lifecycle ---

    def start_leader(self, *, port: Any = 8765, log: Optional[LogFn] = None) -> bool:
        self.stop_leader(log=log)
        member_states.clear()
        self._leader = link.start_leader_link(port=port, log=log)
        return self._leader is not None

    def stop_leader(self, *, log: Optional[LogFn] = None) -> None:
        link.stop_leader_link(self._leader, log=log)
        self._leader = None

    def start_member(
        self,
        *,
        host: str,
        port: Any = 8765,
        log: Optional[LogFn] = None,
    ) -> bool:
        self.stop_member(log=log)
        self._member = link.start_member_link(host=host, port=port, log=log)
        return self._member is not None

    def stop_member(self, *, log: Optional[LogFn] = None) -> None:
        link.stop_member_link(self._member, log=log)
        self._member = None
        self._reset_member_watch()

    @property
    def member_connected(self) -> bool:
        client = self.client
        return bool(client is not None and getattr(client, "connected", False))

    def wait_member_connected(
        self,
        timeout_s: float,
        *,
        stopped: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Block until the member client is connected, the timeout ends, or ``stopped()``."""
        if self.client is None:
            return False
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            if self.member_connected:
                self._was_connected = True
                return True
            if stopped is not None and stopped():
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

    def watch_member(self, *, log: Optional[LogFn] = None) -> None:
        """Log drops / reconnects and restart a client whose IO thread died."""
        client = self.client
        if client is None:
            return
        note = log or (lambda _m: None)
        now = time.monotonic()
        connected = self.member_connected
        if connected:
            if not self._was_connected and self._lost_at > 0.0:
                note(
                    f"Party member: leader socket reconnected after "
                    f"{now - self._lost_at:.0f}s (drop #{self.member_drops})"
                )
            self._was_connected = True
            self._lost_at = 0.0
            return
        if self._was_connected:
            self._was_connected = False
            self._lost_at = now
            self.member_drops += 1
            note(
                f"Party member: leader socket lost (drop #{self.member_drops}) — "
                "reconnecting; farming continues on the last policy"
            )
        elif self._lost_at <= 0.0:
            self._lost_at = now
        if getattr(client, "running", True):
            return
        if now - self._last_restart_at < 5.0:
            return
        self._last_restart_at = now
        self.member_restarts += 1
        try:
            client.connect(wait=False)
            note(
                f"Party member: socket client restarted "
                f"(#{self.member_restarts})"
            )
        except Exception as exc:
            note(f"Party member: socket client restart failed: {exc}")

    def member_link_info(self) -> dict[str, Any]:
        lost = (
            round(time.monotonic() - self._lost_at, 1)
            if self._lost_at > 0.0 and not self.member_connected
            else 0.0
        )
        return {
            "drops": int(self.member_drops),
            "restarts": int(self.member_restarts),
            "down_s": lost,
        }

    def stop_all(self, *, log: Optional[LogFn] = None) -> None:
        self.stop_leader(log=log)
        self.stop_member(log=log)
        reset_orders()
        member_states.clear()

    # --- leader ticks ---

    def publish_recovery(
        self,
        *,
        map_id: Optional[int],
        x: Optional[int],
        y: Optional[int],
    ) -> int:
        return publish.publish_recovery(map_id=map_id, x=x, y=y)

    def publish_policy(self, **kwargs: Any) -> int:
        return publish.publish_policy(**kwargs)

    def publish_decision(
        self,
        action: Any,
        world: Any = None,
        *,
        map_id: Optional[int] = None,
    ) -> str:
        return publish.publish_leader_decision(action, world, map_id=map_id)

    def drain_reports(
        self,
        *,
        start_rally: Any = None,
        party_snapshot: Any = None,
        roster_names: Optional[set[str]] = None,
        log: Optional[LogFn] = None,
    ) -> int:
        return ingest.drain_leader_reports(
            server=self.server,
            start_rally=start_rally,
            party_snapshot=party_snapshot,
            roster_names=roster_names,
            log=log,
        )

    # --- member ticks ---

    def ingest_orders(self) -> None:
        ingest.ingest_member_orders(self.client)

    def send_policy_ack(self, *, name: str, policy_id: str) -> bool:
        return status.send_policy_ack(self.client, name=name, policy_id=policy_id)

    def send_member_state(self, body: dict) -> bool:
        return status.send_member_state(self.client, body)

    def send_status(
        self,
        world: Any,
        *,
        map_id: Optional[int] = None,
        x: Any = None,
        y: Any = None,
        log: Optional[LogFn] = None,
    ) -> None:
        note = log or (lambda _m: None)
        name = self_name_from_party(
            getattr(world, "last_party", None), map_id, x, y
        )
        try:
            if member_orders.take_report():
                status.send_member_status(
                    self.heartbeat,
                    world,
                    map_id=map_id,
                    name=name,
                    x=x,
                    y=y,
                    force_report=True,
                )
                note(
                    f"Party member reported buffs and items at "
                    f"{member_orders.order_kind or 'gather'}"
                )
            else:
                status.send_member_status(
                    self.heartbeat,
                    world,
                    map_id=map_id,
                    name=name,
                    x=x,
                    y=y,
                    force_report=False,
                )
        except Exception as exc:
            err = str(exc)
            if err != self._hb_err:
                self._hb_err = err
                note(f"Party member status send failed: {err}")


__all__ = ["PartyComms"]
