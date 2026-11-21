"""Party kick types only for a listed member, then retries until they leave."""
from app._06_party.invite import (
    KickWatch,
    LeaderInvites,
    clear_roster_flags,
    kick_command,
    member_listed,
)


def _party(*names: str) -> dict:
    return {
        "subs_ok": True,
        "in_party": True,
        "members": [{"name": name} for name in names],
    }


def test_kick_command_uses_the_party_prefix():
    assert kick_command("poorboy") == "/파티추방 poorboy"


def test_unknown_memory_does_not_type():
    sent = []
    clock = {"t": 0.0}
    watch = KickWatch("poorboy", clock=lambda: clock["t"], confirm_s=2.0)
    assert member_listed(None, "poorboy") is None
    text = watch.begin(None, sent.append)
    assert text.startswith("rejected")
    assert sent == []
    assert watch.phase == "skipped"


def test_absent_name_is_not_typed():
    sent = []
    watch = KickWatch("poorboy", clock=lambda: 0.0)
    text = watch.begin(_party("other"), sent.append)
    assert text == "rejected: not in party"
    assert sent == []


def test_listed_name_is_typed_once_when_they_leave():
    sent = []
    clock = {"t": 0.0}
    watch = KickWatch("poorboy", clock=lambda: clock["t"], confirm_s=2.0)
    text = watch.begin(_party("poorboy", "leader"), lambda line: sent.append(line) or True)
    assert text == "manual /파티추방 poorboy"
    assert sent == ["/파티추방 poorboy"]
    clock["t"] = 1.0
    assert watch.tick(_party("leader"), lambda line: sent.append(line) or True, can_send=True) is None
    clock["t"] = 3.0
    assert watch.tick(_party("leader"), lambda line: sent.append(line) or True, can_send=True) == "left"
    assert sent == ["/파티추방 poorboy"]
    assert watch.phase == "left"


def test_still_listed_name_is_sent_twice_more_then_stops():
    sent = []
    clock = {"t": 0.0}
    watch = KickWatch("poorboy", clock=lambda: clock["t"], confirm_s=2.0, retries=2)
    watch.begin(_party("poorboy"), lambda line: sent.append(line) or True)
    clock["t"] = 2.0
    watch.tick(_party("poorboy"), lambda line: sent.append(line) or True, can_send=True)
    clock["t"] = 4.0
    watch.tick(_party("poorboy"), lambda line: sent.append(line) or True, can_send=True)
    clock["t"] = 6.0
    assert watch.tick(_party("poorboy"), lambda line: sent.append(line) or True, can_send=True) == "failed"
    assert sent == ["/파티추방 poorboy", "/파티추방 poorboy", "/파티추방 poorboy"]
    assert watch.phase == "failed"


def test_unknown_read_does_not_spend_a_retry():
    sent = []
    clock = {"t": 0.0}
    watch = KickWatch("poorboy", clock=lambda: clock["t"], confirm_s=2.0)
    watch.begin(_party("poorboy"), lambda line: sent.append(line) or True)
    clock["t"] = 5.0
    assert watch.tick(None, lambda line: sent.append(line) or True, can_send=True) is None
    assert len(sent) == 1
    assert watch.phase == "waiting"


def test_confirmed_leave_clears_use_and_wait_and_drops_the_invite():
    rows = [
        {"name": "poorboy", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
        {"name": "other", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
    ]
    assert clear_roster_flags(rows, "PoorBoy")
    assert rows[0]["enabled"] == "0" and rows[0]["required"] == "0"
    assert rows[0]["name"] == "poorboy"
    assert rows[1]["enabled"] == "1" and rows[1]["required"] == "1"

    fresh = [
        {"name": "poorboy", "role": "member", "loot": "none", "enabled": "1", "required": "1"},
        {"name": "other", "role": "mage", "loot": "none", "enabled": "1", "required": "1"},
    ]
    clock = {"t": 0.0}
    invites = LeaderInvites(
        clock=lambda: clock["t"],
        log=lambda _message: None,
        send_chat=lambda _line: True,
    )
    invites.start(fresh, snapshot=_party("poorboy", "other"), self_name="leader")
    assert invites.inviter is not None
    assert any(row.name == "poorboy" for row in invites.inviter.rows)
    invites.hold_kick("poorboy")
    assert invites._ready("poorboy") is False
    invites.drop_kicked("poorboy")
    assert all(row.name.casefold() != "poorboy" for row in invites.inviter.rows)
    assert "poorboy" not in [name.casefold() for name in invites._wanted]
    assert "poorboy" not in [name.casefold() for name in invites._required]
