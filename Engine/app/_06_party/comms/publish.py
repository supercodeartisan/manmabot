"""Leader → members: decision / recovery / body broadcast."""
from __future__ import annotations

from typing import Any, Optional


def publish_body(body: dict[str, Any]) -> int:
    from websocket.leader_decisions import publish_body as _publish

    return int(_publish(body) or 0)


def publish_leader_decision(
    action: Any,
    world: Any = None,
    *,
    map_id: Optional[int] = None,
) -> str:
    from websocket.leader_decisions import publish_leader_decision as _pub

    return str(_pub(action, world, map_id=map_id) or "")


def publish_recovery(
    *,
    map_id: Optional[int],
    x: Optional[int],
    y: Optional[int],
) -> int:
    from .orders import recovery_message

    return publish_body(recovery_message(map_id=map_id, x=x, y=y))


def publish_policy(**kwargs: Any) -> int:
    from .orders import policy_message

    return publish_body(policy_message(**kwargs))


def publish_beep(*, why: str = "already_in_party") -> int:
    from .orders import beep_message

    return publish_body(beep_message(who="leader", why=why))


def publish_shop_reports(
    world: Any,
    roster: Any,
    leader_name: str,
    map_id: Optional[int],
    x: Any,
    y: Any,
    *,
    hunt_open: bool = False,
    away: Any = None,
) -> int:
    """Send every stored member report plus the leader's own report.

    Only the roster shopkeeper receives it. The wait is ``HEARTBEAT_S``,
    the same clock member ``report`` frames use. Returns sockets reached.
    """
    import time

    from websocket.active import current
    from websocket.member_status import build_report, member_reports
    from websocket.party_orders import leader_session
    from websocket.protocol import PartyMessage
    from websocket.traffic_log import note

    from ..sync import member_states

    now = time.monotonic()
    if not member_reports.due(now):
        return 0
    leader = str(leader_name or "").strip() or "leader"
    buff_sent = publish_party_buffs(
        world,
        leader,
        map_id,
        x,
        y,
    )
    peers: list[str] = []
    for name in _shopkeeper_names(roster):
        peer = member_states.peer_for(name)
        if peer and peer not in peers:
            peers.append(peer)
    if not peers:
        if buff_sent:
            member_reports.mark_sent(now)
        return 0
    watchdog = current()
    if watchdog is None or not watchdog.running or not getattr(watchdog.server, "listening", False):
        if buff_sent:
            member_reports.mark_sent(now)
        return 0
    reports = [
        row
        for row in member_reports.snapshot()
        if str(row.get("from") or "").strip().casefold() != leader.casefold()
    ]
    reports.append(
        build_report(world, map_id, name=leader, x=x, y=y, arrived=False, order="")
    )
    blocked = {
        str(name).strip().casefold()
        for name in (away or [])
        if str(name).strip()
    }
    open_hunt = bool(hunt_open)
    for row in reports:
        who = str(row.get("from") or "").strip().casefold()
        row["supply_ok"] = bool(open_hunt and who not in blocked)
        row["hunt_open"] = open_hunt
    body: dict[str, Any] = {
        "type": "party_reports",
        "from": "leader",
        "hunt_open": open_hunt,
        "reports": reports,
    }
    session = leader_session()
    if session:
        body["session"] = session
    frame = PartyMessage(sender="leader", message=body)
    sent = 0
    for peer in peers:
        try:
            if watchdog.server.send_to(peer, frame, sender="leader"):
                sent += 1
        except Exception:
            continue
    if sent:
        note("sent", frame)
    if sent or buff_sent:
        member_reports.mark_sent(now)
    return sent


def publish_party_buffs(
    world: Any,
    leader_name: str,
    map_id: Optional[int],
    x: Any,
    y: Any,
) -> int:
    """Send each bot's buffs and ailments to every connected member.

    The shopkeeper supply bundle stays on ``party_reports``. This frame is
    only the buff clock a party mage reads.
    """
    import time

    from websocket.active import current
    from websocket.member_status import build_report, member_reports
    from websocket.party_orders import leader_session
    from websocket.protocol import PartyMessage
    from websocket.traffic_log import note

    from ..sync import member_states

    peers = member_states.peer_ids()
    if not peers:
        return 0
    watchdog = current()
    if watchdog is None or not watchdog.running or not getattr(watchdog.server, "listening", False):
        return 0
    leader = str(leader_name or "").strip() or "leader"
    rows = [
        _buff_row(row)
        for row in member_reports.snapshot()
        if str(row.get("from") or "").strip().casefold() != leader.casefold()
    ]
    own = build_report(world, map_id, name=leader, x=x, y=y, arrived=False, order="")
    own["noted_at"] = time.time()
    rows.append(_buff_row(own))
    body: dict[str, Any] = {
        "type": "party_buffs",
        "from": "leader",
        "rows": rows,
    }
    session = leader_session()
    if session:
        body["session"] = session
    frame = PartyMessage(sender="leader", message=body)
    sent = 0
    for peer in peers:
        try:
            if watchdog.server.send_to(peer, frame, sender="leader"):
                sent += 1
        except Exception:
            continue
    if sent:
        note("sent", frame)
    return sent


def _buff_row(report: dict[str, Any]) -> dict[str, Any]:
    try:
        noted = float(report.get("noted_at") or 0.0)
    except (TypeError, ValueError):
        noted = 0.0
    return {
        "from": str(report.get("from") or "").strip(),
        "buffs": list(report.get("buffs") or []),
        "debuffs": list(report.get("debuffs") or []),
        "poisoned": bool(report.get("poisoned")),
        "noted_at": noted,
    }


def _shopkeeper_names(roster: Any) -> list[str]:
    names: list[str] = []
    rows = roster if isinstance(roster, (list, tuple)) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "").strip().lower() != "shopkeeper":
            continue
        name = str(row.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


__all__ = [
    "publish_beep",
    "publish_body",
    "publish_leader_decision",
    "publish_party_buffs",
    "publish_policy",
    "publish_recovery",
    "publish_shop_reports",
]
