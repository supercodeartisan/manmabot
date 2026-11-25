"""Party leader Windows firewall helper (unit, no real netsh required)."""
from __future__ import annotations

from unittest.mock import patch

from websocket import win_firewall as wf


def test_ensure_party_leader_inbound_noop_off_windows() -> None:
    notes: list[str] = []
    with patch.object(wf.os, "name", "posix"):
        lines = wf.ensure_party_leader_inbound(ws_port=8765, log=notes.append)
    assert lines == []
    assert notes == []


def test_ensure_party_leader_inbound_warns_when_not_admin() -> None:
    notes: list[str] = []
    with (
        patch.object(wf.os, "name", "nt"),
        patch.object(wf, "_is_admin", return_value=False),
    ):
        lines = wf.ensure_party_leader_inbound(ws_port=8765, log=notes.append)
    assert len(lines) == 1
    assert "not elevated" in lines[0]
    assert "38765" in lines[0]
    assert "8765" in lines[0]


def test_ensure_inbound_allow_skips_when_already_matching() -> None:
    with (
        patch.object(wf, "_rule_exists", return_value=True),
        patch.object(wf, "_rule_matches_port", return_value=True),
        patch.object(wf, "_add_allow") as add,
    ):
        msg = wf.ensure_inbound_allow(name="T", protocol="UDP", port=38765)
    assert "already allowed" in msg
    add.assert_not_called()


def test_ensure_inbound_allow_recreates_when_port_changed() -> None:
    with (
        patch.object(wf, "_rule_exists", return_value=True),
        patch.object(wf, "_rule_matches_port", return_value=False),
        patch.object(wf, "_delete_rule") as delete,
        patch.object(wf, "_add_allow", return_value=(True, "")),
    ):
        msg = wf.ensure_inbound_allow(name="T", protocol="TCP", port=9000)
    delete.assert_called_once_with("T")
    assert "allowed inbound TCP/9000" in msg


def test_start_leader_calls_firewall_helper() -> None:
    from app._06_party.comms.facade import PartyComms

    notes: list[str] = []
    fake_link = type(
        "L",
        (),
        {"port": 8765, "owned": True, "watchdog": None, "advertise": "1.2.3.4"},
    )()
    called: dict[str, object] = {}

    def _fake_fw(*, ws_port: int, log=None):
        called["ws_port"] = ws_port
        if log:
            log("Party firewall: test ok")
        return ["Party firewall: test ok"]

    with (
        patch(
            "app._06_party.comms.link.start_leader_link",
            return_value=fake_link,
        ),
        patch("websocket.lan_discover.LanAnnouncer") as announcer_cls,
        patch(
            "websocket.win_firewall.ensure_party_leader_inbound",
            side_effect=_fake_fw,
        ),
        patch("websocket.member_status.member_reports"),
    ):
        announcer_cls.return_value.start = lambda: None
        ok = PartyComms().start_leader(
            port=8765,
            log=notes.append,
            leader_id="abc",
            display_name="Boss",
        )
    assert ok is True
    assert called.get("ws_port") == 8765
    assert any("firewall" in n.casefold() for n in notes)
