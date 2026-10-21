"""Inbound party frames: member orders, leader reports."""
from __future__ import annotations

from typing import Any, Callable, Optional

LogFn = Callable[[str], None]


def ingest_member_orders(client: Any) -> None:
    """Drain the member client inbox into ``member_orders``."""
    from .orders import member_orders

    if client is None:
        return
    member_orders.ingest(client.drain())


def drain_leader_reports(
    *,
    server: Any,
    start_rally: Any = None,
    party_snapshot: Any = None,
    roster_names: Optional[set[str]] = None,
    log: Optional[LogFn] = None,
) -> int:
    """Apply member ``report`` frames to the rally and ``policy_ack`` frames to
    ``policy_acks``; advance ``start_rally``.

    Returns the current WebSocket client count (0 when there is no server).
    """
    from .orders import POLICY_ACK, REPORT, party_member_names, policy_acks, rally

    note = log or (lambda _m: None)
    if server is None:
        return 0
    try:
        frames = server.drain()
    except Exception:
        frames = []
    names = (
        (start_rally.expected if start_rally is not None else set())
        or party_member_names(party_snapshot)
    )
    for frame in frames:
        body = getattr(frame, "message", None)
        if not isinstance(body, dict):
            continue
        kind = str(body.get("type") or "")
        who = str(body.get("from") or getattr(frame, "sender", "") or "")
        if kind == POLICY_ACK:
            first = not policy_acks.acked(who, body.get("policy_id"))
            booked = policy_acks.note(who, body, roster_names or names)
            if booked and first:
                note(f"Party policy confirmed by {booked} (id {body.get('policy_id') or '—'})")
            continue
        if kind != REPORT:
            continue
        rally.note_report(who, body, names)
    try:
        connected = int(server.client_count())
    except Exception:
        connected = 0
    if rally.repeat_if_members_joined(connected):
        note("Party rally repeated for a new member")
    if start_rally is not None:
        start_rally.update(connected, party_snapshot)
    return connected


__all__ = [
    "drain_leader_reports",
    "ingest_member_orders",
]
