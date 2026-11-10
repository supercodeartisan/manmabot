"""A confirmed party read is the member list. A stored join does not outvote it."""
from app._01_perception import lc_view
from app._06_party.invite import PartyInviter
from app._06_party.sync import memory_in_party


def _inviter():
    clock = {"t": 0.0}
    inv = PartyInviter(
        ["poorboy"],
        clock=lambda: clock["t"],
        log=lambda _message: None,
        left_confirm_s=10.0,
    )
    return inv, clock


def _party(*names: str) -> dict:
    return {
        "subs_ok": True,
        "in_party": bool(names),
        "members": [{"name": name} for name in names],
    }


def test_a_confirmed_absence_drops_the_stored_join():
    inv, clock = _inviter()
    inv.observe(_party("poorboy"))
    assert inv.rows[0].joined

    gone = _party("leader")
    still_says_in = lambda _name: True
    inv.observe(gone, reported=still_says_in, reported_out=lambda _name: False)
    assert inv.rows[0].joined

    clock["t"] = 10.0
    inv.observe(gone, reported=still_says_in, reported_out=lambda _name: False)
    assert not inv.rows[0].joined
    inv.observe(gone, reported=still_says_in)
    assert not inv.rows[0].joined


def test_an_unknown_read_keeps_the_join():
    inv, _clock = _inviter()
    inv.observe(_party("poorboy"))
    inv.observe(None, reported_out=lambda _name: True)
    assert inv.rows[0].joined
    assert memory_in_party(None) is None


def test_a_blind_sample_is_not_an_empty_party(monkeypatch):
    monkeypatch.setattr(lc_view.session, "text", lambda _name: "party_verify=blind\n")
    snap = lc_view.party()
    assert snap["subs_ok"] is False
    assert memory_in_party(snap) is None
