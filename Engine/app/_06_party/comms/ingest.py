"""Inbound party frames: member orders, leader reports."""
from __future__ import annotations

from typing import Any, Callable, Optional

LogFn = Callable[[str], None]


def _name_in_conflict(who: str, connection_id: str) -> bool:
    """True when this name is claimed by two live connections."""
    from ..member_discovery import MembershipStatus, discovery

    key = str(who or "").strip().casefold()
    cid = str(connection_id or "").strip()
    for row in discovery.by_connection.values():
        if row.status != MembershipStatus.CONFLICT:
            continue
        if cid and row.connection_id == cid:
            return True
        if key and str(row.name or "").strip().casefold() == key:
            return True
    return False


def ingest_member_orders(client: Any) -> None:
    """Drain the member client inbox into ``member_orders``.

    Frames that are not from the leader, or that fail the field checks,
    never reach the member brain.
    """
    from ..frame_check import reject_leader_frame
    from .orders import member_orders

    if client is None:
        return
    kept = []
    for frame in client.drain():
        body = getattr(frame, "message", None)
        if reject_leader_frame(body):
            continue
        kept.append(frame)
    member_orders.ingest(kept)


def drain_leader_reports(
    *,
    server: Any,
    start_rally: Any = None,
    party_snapshot: Any = None,
    roster_names: Optional[Any] = None,
    log: Optional[LogFn] = None,
) -> int:
    """Apply member ``report`` frames to the rally, ``member_state`` frames to
    ``sync.member_states`` (and their ``policy_id`` to ``policy_acks``),
    ``invite_accept`` frames to ``sync.invite_accepts``, legacy ``policy_ack``
    frames to ``policy_acks``; advance ``start_rally``.

    Returns the current WebSocket client count (0 when there is no server).
    """
    from ..frame_check import character_name, reject_member_frame
    from ..member_discovery import MembershipStatus, discovery
    from ..sync import invite_accepts, member_states
    from .orders import (
        BEEP,
        INVITE_ACCEPT,
        MEMBER_HELLO,
        MEMBER_STATE,
        POLICY_ACK,
        REPORT,
        leader_session,
        party_member_names,
        policy_acks,
        rally,
    )

    note = log or (lambda _m: None)
    if server is None:
        return 0
    try:
        dropped_peers = list(server.take_dropped())
    except Exception:
        dropped_peers = []
    dropped_set = {str(peer) for peer in dropped_peers if str(peer)}
    for peer in dropped_peers:
        held = member_states.name_for_peer(peer)
        member_states.forget_peer(peer)
        if not held:
            continue
        member_states.hold_until_fresh(held)
        note(
            f"Party socket dropped for {held} — "
            "keeping invite progress, waiting for a fresh member_state"
        )
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
        dropped = reject_member_frame(body)
        if dropped:
            note(f"Party frame dropped: {dropped}")
            continue
        kind = str(body.get("type") or "")
        who = str(body.get("from") or getattr(frame, "sender", "") or "")
        cid = str(body.get("client_id") or "").strip()
        roster = names if roster_names is None else roster_names
        peer = str(getattr(frame, "peer", "") or "")
        if peer and peer in dropped_set:
            continue
        if kind == MEMBER_HELLO:
            character = body.get("character") if isinstance(body.get("character"), dict) else {}
            hello_name = str(character.get("name") or who or "").strip()
            if peer and hello_name:
                member_states.bind_peer(peer, hello_name)
            row = discovery.observe(
                connection_id=cid,
                name=hello_name,
                character_class=str(character.get("class") or ""),
                level=character.get("level"),
                roster=roster,
            )
            note(
                f"Party hello {hello_name or '—'} "
                f"[{row.status.value}] id={cid or '—'}"
            )
            continue
        if kind == BEEP:
            why = str(body.get("why") or "already_in_party")
            note(f"Party beep from {who or 'member'} — socket ok ({why})")
            continue
        if kind == MEMBER_STATE:
            state_name = character_name(who)
            found = discovery.observe(
                connection_id=cid,
                name=state_name,
                roster=roster,
            )
            if found.status != MembershipStatus.MATCHED:
                if found.status == MembershipStatus.UNIDENTIFIED:
                    member_states.unnamed_at = member_states._clock()
                continue
            booked = member_states.note(who, body, roster, session=leader_session())
            if not booked:
                continue
            if peer:
                member_states.bind_peer(peer, booked)
            row = member_states.row(booked)
            pid = str(row.get("policy_id") or "")
            if pid:
                first = not policy_acks.acked(booked, pid)
                policy_acks.note(
                    booked,
                    {
                        "policy_id": pid,
                        "client_id": body.get("client_id") or "",
                    },
                    roster,
                )
                if first:
                    note(f"Party policy confirmed by {booked} (id {pid}, member state)")
            if body.get("changed"):
                party = row.get("party") or {}
                inv = row.get("invite") or {}
                note(
                    f"Party member state {booked}: mem={party.get('mem') or '—'} "
                    f"in_party={party.get('in_party')} leader={party.get('leader') or '—'} "
                    f"invite={inv.get('id') or '—'}:{inv.get('phase') or '—'} "
                    f"seq={row.get('seq')}"
                )
            continue
        if kind == INVITE_ACCEPT:
            if not character_name(who) or _name_in_conflict(who, cid):
                continue
            booked, first = invite_accepts.note(
                who, body, roster, session=leader_session()
            )
            if booked and first:
                note(
                    f"Party invite accepted by {booked} (Y closed the popup, "
                    f"id {body.get('accept_id') or '—'}, inviter "
                    f"{body.get('inviter') or '—'}, {int(body.get('presses') or 0)} press(es))"
                )
            continue
        if kind == POLICY_ACK:
            if not character_name(who) or _name_in_conflict(who, cid):
                continue
            booked = policy_acks.note(who, body, roster)
            if booked:
                count = int(policy_acks.row(booked).get("count") or 0)
                if count == 1:
                    note(
                        f"Party policy confirmed by {booked} "
                        f"(id {body.get('policy_id') or '—'})"
                    )
            continue
        if kind != REPORT:
            continue
        if not character_name(who) or _name_in_conflict(who, cid):
            continue
        rally.note_report(who, body, names)
    try:
        connected = int(server.client_count())
    except Exception:
        connected = 0
    # After the start rally a late member follows the leader, not the old point.
    rally_over = start_rally is not None and bool(getattr(start_rally, "done", False))
    if not rally_over and rally.repeat_if_members_joined(connected):
        note("Party rally repeated for a new member")
    if start_rally is not None:
        start_rally.update(connected, party_snapshot)
    return connected


__all__ = [
    "drain_leader_reports",
    "ingest_member_orders",
]
