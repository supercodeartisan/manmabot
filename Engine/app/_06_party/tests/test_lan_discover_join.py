"""LAN browse, hello roster gate, and reconnect identity."""
from __future__ import annotations

from types import SimpleNamespace

from app._06_party.comms.ingest import drain_leader_reports
from app._06_party.member_discovery import MembershipStatus, discovery
from websocket.lan_discover import (
    LanAnnouncer,
    LanBrowser,
    announce_body,
    ensure_leader_id,
    parse_announce,
)
from websocket.party_orders import (
    HELLO_OK,
    HELLO_REJECT,
    hello_ok_message,
    hello_reject_message,
)
from websocket.protocol import PartyMessage, coerce_message


def test_announce_round_trip_keeps_leader_id_and_port() -> None:
    body = announce_body(
        leader_id="abc123",
        session_id="sess01",
        name="Lead",
        ws_port=8765,
        ready=True,
    )
    parsed = parse_announce(body, source_ip="10.0.0.8")
    assert parsed is not None
    assert parsed["leader_id"] == "abc123"
    assert parsed["host"] == "10.0.0.8"
    assert parsed["ws_port"] == 8765
    assert parsed["status_label"] == "초대 가능"


def test_ensure_leader_id_is_stable_on_profile() -> None:
    profile = SimpleNamespace(party_leader_id="")
    first = ensure_leader_id(profile)
    second = ensure_leader_id(profile)
    assert first and first == second == profile.party_leader_id


def test_lan_announcer_answers_browser_probe() -> None:
    announcer = LanAnnouncer(
        leader_id="leader-fixed",
        ws_port=9876,
        name="Alpha",
        session_id="s1",
        ready=True,
    )
    browser = LanBrowser()
    try:
        announcer.start()
        rows = browser.probe_once(timeout_s=1.5)
        hit = next((r for r in rows if r.get("leader_id") == "leader-fixed"), None)
        assert hit is not None
        assert hit["ws_port"] == 9876
        assert hit["name"] == "Alpha"
        assert hit["ready"] is True
    finally:
        announcer.stop(timeout=1.0)
        browser.stop(timeout=0.5)


def test_hello_reject_and_ok_survive_party_message_wrap() -> None:
    reject = hello_reject_message(reason="not_on_roster", name="Bob", leader_id="L1")
    ok = hello_ok_message(name="Bob", leader_id="L1", in_party=True)
    wrapped_r = coerce_message(PartyMessage(sender="leader", message=reject))
    wrapped_o = coerce_message(PartyMessage(sender="leader", message=ok))
    assert wrapped_r.message["type"] == HELLO_REJECT
    assert wrapped_o.message["type"] == HELLO_OK
    assert wrapped_o.message["in_party"] is True


class _FakeServer:
    def __init__(self) -> None:
        self.frames: list = []
        self.sent: list[tuple[str, dict]] = []
        self._dropped: list[str] = []

    def take_dropped(self) -> list[str]:
        out = list(self._dropped)
        self._dropped.clear()
        return out

    def drain(self) -> list:
        out = list(self.frames)
        self.frames.clear()
        return out

    def client_count(self) -> int:
        return 1

    def send_to(self, peer, message, sender="leader") -> bool:
        body = getattr(message, "message", message)
        self.sent.append((str(peer), dict(body) if isinstance(body, dict) else {}))
        return True


def _hello_frame(name: str, *, client_id: str, peer: str = "c1") -> PartyMessage:
    return PartyMessage(
        sender=name,
        peer=peer,
        message={
            "type": "member_hello",
            "from": name,
            "client_id": client_id,
            "character": {"name": name, "class": "knight", "level": 40},
        },
    )


def test_pending_hello_is_rejected_and_does_not_deliver_snapshot() -> None:
    discovery.clear()
    server = _FakeServer()
    server.frames.append(_hello_frame("Stranger", client_id="cid-a"))
    delivered: list[tuple[str, str]] = []

    def _deliver(name: str, peer: str):
        delivered.append((name, peer))
        return [{"type": "party_sync", "rev": 1}]

    drain_leader_reports(
        server=server,
        roster_names=["Alice", "Bob"],
        deliver=_deliver,
        log=lambda _m: None,
    )
    assert delivered == []
    assert any(
        body.get("type") == HELLO_REJECT and body.get("reason") == "not_on_roster"
        for _peer, body in server.sent
    )
    row = next(iter(discovery.by_connection.values()))
    assert row.status is MembershipStatus.PENDING


def test_matched_hello_delivers_and_release_peer_clears_only_that_socket() -> None:
    discovery.clear()
    server = _FakeServer()
    server.frames.append(_hello_frame("Alice", client_id="cid-1", peer="c1"))
    delivered: list[tuple[str, str]] = []

    def _deliver(name: str, peer: str):
        delivered.append((name, peer))
        return [{"type": "party_sync", "session": "s", "rev": 3}]

    drain_leader_reports(
        server=server,
        roster_names=["Alice"],
        deliver=_deliver,
        log=lambda _m: None,
    )
    assert delivered == [("Alice", "c1")]
    assert discovery.by_connection["cid-1"].status is MembershipStatus.MATCHED

    # Second socket for same name while first is live → conflict reject.
    server.frames.append(_hello_frame("Alice", client_id="cid-2", peer="c2"))
    drain_leader_reports(
        server=server,
        roster_names=["Alice"],
        deliver=_deliver,
        log=lambda _m: None,
    )
    assert discovery.by_connection["cid-2"].status is MembershipStatus.CONFLICT

    # Drop only c1; survivor is restored to MATCHED (no lingering CONFLICT).
    server._dropped.append("c1")
    drain_leader_reports(
        server=server,
        roster_names=["Alice"],
        deliver=_deliver,
        log=lambda _m: None,
    )
    assert "cid-1" not in discovery.by_connection
    assert discovery.by_connection["cid-2"].status is MembershipStatus.MATCHED
