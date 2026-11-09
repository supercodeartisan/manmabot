"""Leader follow pose is this tick's memory read, not a preserved snapshot."""
import time

from app._02_state.gamestate import GameState
from app._02_state.objects import Position
from app._02_state.player import PlayerState
from app._03_world.merge.apply_perception import apply_perception_buffer
from app._06_party.config import PartyMemberConfig
from app._06_party.leader import LeaderView, resolve_leader
from app._06_party.manager import PartyMemberManager
from app._06_party.state import MemberRuntime


class _Buf:
    def __init__(self, party, party_ok=True):
        self.player_ok = False
        self.attacks_me = None
        self.contested_mobs = None
        self.print_state_ok = False
        self.inventory_ok = False
        self.hotbar_ok = False
        self.buff_ok = False
        self.uidialog_ok = False
        self.party_ok = party_ok
        self.party = party


def _world() -> GameState:
    return GameState(
        player=PlayerState(track_id=1, position=Position(x=0, y=0)),
    )


def _party():
    return {
        "subs_ok": True,
        "in_party": True,
        "leader": {"name": "Lead", "x": 33000, "y": 33010, "map_id": 4, "hp": 80},
        "members": [],
    }


def test_failed_read_does_not_refresh_the_pose_clock():
    world = _world()
    apply_perception_buffer(world, None, _Buf(_party()))
    assert world.party_read_ok is True
    assert world.party_pose_seq == 1
    stamped = world.party_pose_at
    apply_perception_buffer(world, None, _Buf(_party(), party_ok=False))
    assert world.party_read_ok is False
    assert world.party_pose_seq == 1
    assert world.party_pose_at == stamped
    assert world.last_party["leader"]["name"] == "Lead"


def test_preserved_snapshot_is_not_a_follow_tile():
    world = _world()
    world.last_party = _party()
    world.party_read_ok = False
    view = resolve_leader(world, PartyMemberConfig(leader_name="Lead"), local_map_id=4)
    assert view.tile is None
    assert view.fresh is False
    assert view.name == "Lead"

    world.party_read_ok = True
    live = resolve_leader(world, PartyMemberConfig(leader_name="Lead"), local_map_id=4)
    assert live.tile is not None
    assert live.fresh is True
    assert live.map_id == 4


def test_cached_pose_is_not_copied_back():
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    live = LeaderView(tile=(10, 12), map_id=4, same_map=True, fresh=True, source="party")
    mgr._apply_sticky_party_pose(live)
    assert mgr.runtime.sticky_leader_tile == (10, 12)
    stamped = mgr.runtime.sticky_leader_pose_at

    missed = LeaderView(same_map=True, fresh=False, source="")
    time.sleep(0.01)
    mgr._apply_sticky_party_pose(missed)
    assert missed.tile is None
    assert mgr.runtime.sticky_leader_tile == (10, 12)
    assert mgr.runtime.sticky_leader_pose_at == stamped


def test_missing_sample_resets_stationary_evidence():
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    assert mgr._leader_is_moving((3, 4)) is True
    mgr.runtime.scratch["leader_walk_at"] = time.monotonic() - 1.0
    assert mgr._leader_is_moving((3, 4)) is False
    assert mgr._leader_is_moving(None) is False
    assert "leader_walk_tile" not in mgr.runtime.scratch
    assert mgr._leader_is_moving((3, 4)) is True


if __name__ == "__main__":
    test_failed_read_does_not_refresh_the_pose_clock()
    test_preserved_snapshot_is_not_a_follow_tile()
    test_cached_pose_is_not_copied_back()
    test_missing_sample_resets_stationary_evidence()
    print("ok")
