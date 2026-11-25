"""Solo field Heal / Body to Mind. Mother-tree and party paths stay out."""
from __future__ import annotations

import pytest

from app._02_state.objects import Position
from app._02_state.player import PlayerState, StatusEffect
from app._03_world import ActionType, GameState
from app._04_decision import player_mode as pm
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.mode_actions import apply_hp_actions
from app._04_decision.blackboard import Blackboard
from app._04_decision.field_recovery import (
    begin_field_recovery_session,
    field_recovery_capability_checked,
    invalidate_field_recovery_capability,
    is_field_auto_recovery_enabled,
    refresh_field_recovery_capability,
    select_field_recovery_skill,
    try_field_auto_recovery,
)
from app._04_decision.potion_sides import arm_potion_side_intents
from app._04_decision.player_mode import PlayerMode
from app._04_decision.spells import maybe_hp_to_mp
from app._06_party.recovery import PartyRecovery, bind


def _player(*, hp: int, mp: int, max_hp: int = 100, max_mp: int = 100) -> PlayerState:
    return PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        hp=hp,
        mp=mp,
        max_hp=max_hp,
        max_mp=max_mp,
        level=40,
    )


def _state(*, hp: int, mp: int) -> GameState:
    state = GameState(player=_player(hp=hp, mp=mp))
    state.last_buff = {"buffs": [], "cache": 0}
    return state


def _bar(*names: tuple[int, str, str]) -> dict:
    return {
        "slots": [
            {"box": box, "key": key, "name": name}
            for box, key, name in names
        ]
    }


_BOTH = _bar((1, "f11", "힐"), (2, "f5", "바디 투 마인드"))


def _board() -> Blackboard:
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    board.nav_goal = (120, 80)
    return board


@pytest.fixture
def hunt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pm, "FIELD_RECOVERY_ENABLED", True)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_HP_START", 0.80)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_MP_START", 0.50)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_STOP", 0.85)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_HP_STOP", 0.85)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_MP_STOP", 0.85)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_MIN_HP", 0.60)
    monkeypatch.setattr(pm, "FIELD_RECOVERY_MIN_MP", 0.20)
    monkeypatch.setattr(pm, "USE_HEAL", True)
    monkeypatch.setattr(pm, "USE_HP_POTION", True)
    monkeypatch.setattr(pm, "USE_MP_POTION", False)
    monkeypatch.setattr(pm, "MP_RECOVER_ENABLED", False)
    monkeypatch.setattr(
        pm,
        "HP_ACTIONS",
        [
            {"id": "hp_potion", "enabled": True, "hp_below": 0.30},
            {"id": "heal", "enabled": True, "hp_below": 0.40},
            {"id": "retreat", "enabled": True, "hp_below": 0.20},
        ],
    )
    monkeypatch.setattr(
        "app._04_decision.world_nav.routine.routine_hunt_zone_inside",
        lambda _blackboard: True,
    )
    begin_field_recovery_session()
    refresh_field_recovery_capability(_BOTH)
    yield monkeypatch
    begin_field_recovery_session()


def test_hp_low_mp_sufficient_selects_heal(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    skill = select_field_recovery_skill(_state(hp=75, mp=90), _board())
    assert skill == "heal"


def test_hp_sufficient_mp_low_selects_body_to_mind(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    skill = select_field_recovery_skill(_state(hp=96, mp=30), _board())
    assert skill == "hp_to_mp"


def test_both_low_skips_unsafe_body_to_mind(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    # HP 45% is above the existing heal line (40%) but below the 60% reserve.
    # MP cannot pay Heal and still keep the 20% reserve.
    state = _state(hp=45, mp=10)
    assert select_field_recovery_skill(state, _board()) is None
    assert try_field_auto_recovery(state, _board()) is None


def test_both_low_heals_when_mana_can_pay(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    skill = select_field_recovery_skill(_state(hp=45, mp=90), _board())
    assert skill == "heal"


def test_above_targets_does_not_start(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    assert try_field_auto_recovery(_state(hp=96, mp=90), board) is None
    assert board.intent is None
    assert board.nav_goal == (120, 80)


def test_hp_stop_leaves_mp_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert select_field_recovery_skill(_state(hp=96, mp=40), board) == "hp_to_mp"


def test_mp_stop_leaves_hp_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert select_field_recovery_skill(_state(hp=75, mp=90), board) == "heal"


def test_both_stops_exit(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert try_field_auto_recovery(_state(hp=96, mp=90), board) is None
    assert "field_recovery_active" not in board.scratch


def test_full_hp_low_mp_keeps_comparing_hp(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    state = _state(hp=100, mp=40)
    board = _board()
    assert try_field_auto_recovery(state, board) is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.HP_TO_MP
    assert board.scratch.get("field_recovery_active") is True
    state = _state(hp=60, mp=80)
    board.intent = None
    board.magic_last_cast = 0.0
    assert try_field_auto_recovery(state, board) is None
    again = try_field_auto_recovery(state, board)
    assert again is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.HEAL
    assert board.intent.reason == "field recover hp"


def test_low_hp_full_mp_selects_heal(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.20},
        {"id": "heal", "enabled": True, "hp_below": 0.20},
        {"id": "retreat", "enabled": True, "hp_below": 0.20},
    ]
    board = _board()
    result = try_field_auto_recovery(_state(hp=40, mp=100), board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.HEAL
    assert board.intent.reason == "field recover hp"


def test_priority_flips_after_each_read(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    assert select_field_recovery_skill(_state(hp=90, mp=60), board) == "hp_to_mp"
    assert select_field_recovery_skill(_state(hp=70, mp=80), board) == "heal"
    assert select_field_recovery_skill(_state(hp=88, mp=70), board) == "hp_to_mp"


def test_resource_above_stop_is_recovered_when_it_falls(
    hunt: pytest.MonkeyPatch,
) -> None:
    del hunt
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert select_field_recovery_skill(_state(hp=90, mp=40), board) == "hp_to_mp"
    assert select_field_recovery_skill(_state(hp=78, mp=90), board) == "heal"


def test_one_side_at_stop_does_not_end(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    rows = ((100, 40), (90, 70), (80, 90), (85, 84))
    for hp, mp in rows:
        board = _board()
        board.scratch["field_recovery_active"] = True
        result = try_field_auto_recovery(_state(hp=hp, mp=mp), board)
        assert result is Status.SUCCESS
        assert board.scratch.get("field_recovery_active") is True


def test_both_at_shared_stop_end(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    for hp, mp in ((85, 85), (90, 87)):
        board = _board()
        board.scratch["field_recovery_active"] = True
        assert try_field_auto_recovery(_state(hp=hp, mp=mp), board) is None
        assert "field_recovery_active" not in board.scratch
        assert board.intent is None


def test_unsafe_lower_skill_is_not_replaced(hunt: pytest.MonkeyPatch) -> None:
    board = _board()
    # MP is lower, but Body to Mind would leave HP under the 60% reserve.
    # Heal could pay. It must not be cast in Heal's place.
    assert select_field_recovery_skill(_state(hp=65, mp=40), board) is None
    assert try_field_auto_recovery(_state(hp=65, mp=40), board) is None
    # HP is lower, but Heal's slot is off. Body to Mind is still safe.
    # It must not be cast in Heal's place.
    hunt.setattr(
        "app._05_action.spell_box.slot_is_enabled",
        lambda name: name != "heal",
    )
    assert select_field_recovery_skill(_state(hp=70, mp=90), board) is None


def test_equal_percents_use_the_random_choice(
    hunt: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    del hunt
    board = _board()
    monkeypatch.setattr(
        "app._04_decision.field_recovery.random.choice",
        lambda _options: "heal",
    )
    assert select_field_recovery_skill(_state(hp=70, mp=70), board) == "heal"
    monkeypatch.setattr(
        "app._04_decision.field_recovery.random.choice",
        lambda _options: "hp_to_mp",
    )
    assert select_field_recovery_skill(_state(hp=70, mp=70), board) == "hp_to_mp"


def test_old_split_stops_load_as_the_shared_default(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    from settings.profile import Profile
    from settings.schedule import ScheduleTask, profile_snapshot
    from settings.task_runtime import apply_runtime_settings

    saved = profile_snapshot(Profile())
    assert saved["recovery"]["field_recovery_stop"] == 85
    assert "field_recovery_hp_stop" not in saved["recovery"]
    assert "field_recovery_mp_stop" not in saved["recovery"]

    profile = Profile(
        field_recovery_stop_ratio=0.70,
        field_recovery_hp_stop_ratio=0.95,
        field_recovery_mp_stop_ratio=0.80,
    )
    old = ScheduleTask(
        character="elf",
        settings={
            "recovery": {
                "field_recovery_hp_stop": 95,
                "field_recovery_mp_stop": 80,
            }
        },
    )
    apply_runtime_settings(old, profile)
    assert profile.field_recovery_stop_ratio == 0.85
    assert profile.field_recovery_hp_stop_ratio == 0.85
    assert profile.field_recovery_mp_stop_ratio == 0.85

    changed = ScheduleTask(
        character="elf",
        settings={"recovery": {"field_recovery_stop": 90}},
    )
    apply_runtime_settings(changed, profile)
    assert profile.field_recovery_stop_ratio == 0.90
    assert profile.field_recovery_hp_stop_ratio == 0.90
    assert profile.field_recovery_mp_stop_ratio == 0.90

    actions = pm.HP_ACTIONS
    from app._04_decision.configure import configure_decision

    configure_decision(
        {
            "decision": {
                "field_recovery": {
                    "enabled": True,
                    "hp_stop_ratio": 0.95,
                    "mp_stop_ratio": 0.80,
                    "stop_ratio": profile.field_recovery_stop_ratio,
                }
            }
        }
    )
    assert pm.FIELD_RECOVERY_STOP == 0.90
    assert pm.FIELD_RECOVERY_HP_STOP == 0.90
    assert pm.FIELD_RECOVERY_MP_STOP == 0.90
    pm.HP_ACTIONS = actions
    pm.FIELD_RECOVERY_STOP = 0.85
    pm.FIELD_RECOVERY_HP_STOP = 0.85
    pm.FIELD_RECOVERY_MP_STOP = 0.85


def test_monster_interrupts(hunt: pytest.MonkeyPatch) -> None:
    hunt.setattr(
        "app._04_decision.combat_query.nearest_attackable",
        lambda *_args, **_kwargs: object(),
    )
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert try_field_auto_recovery(_state(hp=75, mp=30), board) is None
    assert "field_recovery_active" not in board.scratch
    assert board.nav_goal == (120, 80)


def test_damage_spike_interrupts(hunt: pytest.MonkeyPatch) -> None:
    hunt.setattr(
        "app._04_decision.behaviors.mode_actions.hp_spike_drop",
        lambda _blackboard: True,
    )
    hunt.setattr(
        "app._04_decision.behaviors.mode_actions._combat_hp_threat",
        lambda _state, _blackboard: True,
    )
    board = _board()
    board.scratch["field_recovery_active"] = True
    assert try_field_auto_recovery(_state(hp=96, mp=30), board) is None
    assert "field_recovery_active" not in board.scratch


def test_hp_potion_keeps_the_tick(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.90},
        {"id": "heal", "enabled": True, "hp_below": 0.40},
        {"id": "retreat", "enabled": True, "hp_below": 0.20},
    ]
    assert try_field_auto_recovery(_state(hp=75, mp=30), board) is None
    assert board.intent is None


def test_existing_heal_is_the_only_heal_this_tick(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.20},
        {"id": "heal", "enabled": True, "hp_below": 0.70},
        {"id": "retreat", "enabled": True, "hp_below": 0.20},
    ]
    board = _board()
    result = apply_hp_actions(_state(hp=50, mp=90), board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.HEAL
    assert board.intent.reason == "recover hp"


def test_body_to_mind_without_blessing(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    state = _state(hp=96, mp=30)
    board = _board()
    assert maybe_hp_to_mp(state, board) is None
    result = try_field_auto_recovery(state, board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.HP_TO_MP
    assert board.intent.reason == "field recover mp"


def test_mother_tree_cast_still_requires_blessing(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    pm.FIELD_RECOVERY_ENABLED = False
    state = _state(hp=90, mp=40)
    state.player.buffs.append(
        StatusEffect(name="세계수의 가호", duration=1.0, str_id=993, perpetual=True)
    )
    board = _board()
    board.scratch["mother_tree_trip"] = "recharge"
    assert maybe_hp_to_mp(state, board) is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.reason == "hp to mp"
    board.intent = None
    board.magic_last_cast = 0.0
    assert try_field_auto_recovery(state, board) is None


def test_party_recovery_does_not_gain_field_casts(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    board = _board()
    with bind(PartyRecovery()):
        assert try_field_auto_recovery(_state(hp=75, mp=30), board) is None
    assert board.intent is None


def test_navigation_resumes_on_the_next_tick(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    state = _state(hp=96, mp=30)
    board = _board()
    assert try_field_auto_recovery(state, board) is Status.SUCCESS
    assert board.nav_goal == (120, 80)
    assert try_field_auto_recovery(state, board) is None
    assert board.nav_goal == (120, 80)
    assert board.scratch.get("field_recovery_yield") is None
    board.magic_last_cast = 0.0
    again = try_field_auto_recovery(state, board)
    assert again is Status.SUCCESS
    assert board.nav_goal == (120, 80)


def test_unavailable_skill_does_not_repeat(hunt: pytest.MonkeyPatch) -> None:
    hunt.setattr(
        "app._05_action.spell_box.slot_is_enabled",
        lambda _name: False,
    )
    board = _board()
    state = _state(hp=75, mp=30)
    for _ in range(5):
        assert try_field_auto_recovery(state, board) is None
    assert board.intent is None


def test_retreat_death_and_map_change_reset(hunt: pytest.MonkeyPatch) -> None:
    class _Pose:
        map_id = 7

    hunt.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: _Pose(),
    )
    retreat = _board()
    retreat.player_mode = PlayerMode.RETREATING
    retreat.scratch["field_recovery_active"] = True
    assert try_field_auto_recovery(_state(hp=75, mp=30), retreat) is None
    assert "field_recovery_active" not in retreat.scratch

    dead = _board()
    dead.scratch["field_recovery_active"] = True
    assert try_field_auto_recovery(_state(hp=0, mp=30), dead) is None
    assert "field_recovery_active" not in dead.scratch

    moved = _board()
    moved.scratch["field_recovery_active"] = True
    moved.scratch["field_recovery_map"] = 3
    assert try_field_auto_recovery(_state(hp=75, mp=30), moved) is None
    assert "field_recovery_active" not in moved.scratch


def test_routine_change_resets(hunt: pytest.MonkeyPatch) -> None:
    del hunt

    class _Cursor:
        def active(self) -> dict:
            return {"map_id": "isle", "kind": "battle", "selected_farms": ["east"]}

    board = _board()
    board.scratch["routine_cursor"] = _Cursor()
    board.scratch["field_recovery_active"] = True
    board.scratch["field_recovery_routine"] = "isle|battle|west"
    assert try_field_auto_recovery(_state(hp=75, mp=30), board) is None
    assert "field_recovery_active" not in board.scratch


def test_startup_hotbar_failure_keeps_the_run_and_disables_recovery(
    hunt: pytest.MonkeyPatch,
) -> None:
    del hunt
    from session.bot_controller import BotController

    epoch = begin_field_recovery_session()
    assert refresh_field_recovery_capability(_BOTH, epoch=epoch) is True

    class _Ui:
        logs = {"hotbar_failed": "hotbar failed: {error}"}

    class _Host:
        def __init__(self) -> None:
            self.stopped = False
            self.committed = False
            self.messages: list[str] = []

        def log(self, msg: str) -> None:
            self.messages.append(str(msg))

        def _ui(self) -> _Ui:
            return _Ui()

        def _set_state(self, *_args) -> None:
            self.stopped = True

        def _commit_hotbar_scan(self, *_args, **_kwargs) -> None:
            self.committed = True

    host = _Host()
    BotController._record_startup_hotbar(
        host, None, None, None, RuntimeError("memory read failed"), epoch
    )
    assert host.stopped is False
    assert host.committed is False
    assert is_field_auto_recovery_enabled() is False
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.20},
        {"id": "heal", "enabled": True, "hp_below": 0.70},
        {"id": "retreat", "enabled": True, "hp_below": 0.20},
    ]
    board = _board()
    result = apply_hp_actions(_state(hp=50, mp=90), board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.reason == "recover hp"


def test_both_hotbar_skills_enable_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    assert refresh_field_recovery_capability(_BOTH) is True
    assert is_field_auto_recovery_enabled() is True


def test_heal_alone_disables_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    assert refresh_field_recovery_capability(_bar((1, "f11", "힐"))) is False
    assert is_field_auto_recovery_enabled() is False


def test_body_to_mind_alone_disables_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    assert refresh_field_recovery_capability(_bar((2, "f5", "바디 투 마인드"))) is False
    assert is_field_auto_recovery_enabled() is False


def test_neither_skill_disables_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    assert refresh_field_recovery_capability(_bar((1, "f6", "라이트"))) is False
    assert is_field_auto_recovery_enabled() is False


def test_failed_hotbar_read_disables_recovery(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    assert refresh_field_recovery_capability(None) is False
    assert refresh_field_recovery_capability({}) is False
    assert refresh_field_recovery_capability({"slots": []}) is False
    assert is_field_auto_recovery_enabled() is False


def test_catalog_spell_without_a_hotbar_slot_stays_off(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    # Heal and Body to Mind exist in the spell catalog. This bar does not hold them.
    assert refresh_field_recovery_capability(_bar((1, "f8", "실드"))) is False
    assert try_field_auto_recovery(_state(hp=75, mp=30), _board()) is None


def test_session_checks_hotbar_on_start_resume_and_restart(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    state = _state(hp=75, mp=30)
    begin_field_recovery_session()
    assert field_recovery_capability_checked() is False
    assert try_field_auto_recovery(state, _board()) is None

    assert refresh_field_recovery_capability(_BOTH) is True
    assert try_field_auto_recovery(state, _board()) is Status.SUCCESS

    invalidate_field_recovery_capability()
    assert is_field_auto_recovery_enabled() is False
    paused = _board()
    assert try_field_auto_recovery(state, paused) is None
    assert paused.intent is None

    assert refresh_field_recovery_capability(_bar((1, "f11", "힐"))) is False
    assert try_field_auto_recovery(state, _board()) is None

    begin_field_recovery_session()
    assert is_field_auto_recovery_enabled() is False
    assert refresh_field_recovery_capability(_BOTH) is True
    assert is_field_auto_recovery_enabled() is True


def test_new_session_does_not_keep_the_previous_character(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    first = begin_field_recovery_session()
    assert refresh_field_recovery_capability(_BOTH, epoch=first) is True
    second = begin_field_recovery_session()
    assert is_field_auto_recovery_enabled() is False
    assert refresh_field_recovery_capability(_bar((1, "f6", "라이트")), epoch=first) is False
    assert is_field_auto_recovery_enabled() is False
    assert refresh_field_recovery_capability(_BOTH, epoch=second) is True
    assert refresh_field_recovery_capability(None, epoch=first) is True
    assert is_field_auto_recovery_enabled() is True


def test_running_ticks_do_not_reread_the_hotbar(hunt: pytest.MonkeyPatch) -> None:
    calls = {"role": 0, "refresh": 0}
    real_refresh = refresh_field_recovery_capability

    def _refresh(*args, **kwargs):
        calls["refresh"] += 1
        return real_refresh(*args, **kwargs)

    def _role(*_args, **_kwargs):
        calls["role"] += 1
        return (1, "f11")

    hunt.setattr(
        "app._04_decision.field_recovery.refresh_field_recovery_capability",
        _refresh,
    )
    hunt.setattr("hotbar.inspect.find_role_on_hotbar", _role)
    state = _state(hp=99, mp=99)
    state.last_hotbar = _BOTH
    assert try_field_auto_recovery(state, _board()) is None
    assert try_field_auto_recovery(state, _board()) is None
    assert calls == {"role": 0, "refresh": 0}


def test_existing_heal_still_runs_when_field_recovery_is_off(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    invalidate_field_recovery_capability()
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.20},
        {"id": "heal", "enabled": True, "hp_below": 0.70},
        {"id": "retreat", "enabled": True, "hp_below": 0.20},
    ]
    board = _board()
    result = apply_hp_actions(_state(hp=50, mp=90), board)
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.reason == "recover hp"


def test_hp_potion_still_runs_when_field_recovery_is_off(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    invalidate_field_recovery_capability()
    pm.HP_ACTIONS = [
        {"id": "hp_potion", "enabled": True, "hp_below": 0.90, "box": 1, "key": "f5"},
        {"id": "heal", "enabled": True, "hp_below": 0.20},
        {"id": "retreat", "enabled": True, "hp_below": 0.10},
    ]
    board = _board()
    arm_potion_side_intents(_state(hp=50, mp=90), board)
    assert any(item.action is ActionType.USE_HP_POTION for item in board.side_intents)


def test_mother_tree_and_party_ignore_the_hotbar_gate(hunt: pytest.MonkeyPatch) -> None:
    del hunt
    invalidate_field_recovery_capability()
    state = _state(hp=90, mp=40)
    state.player.buffs.append(
        StatusEffect(name="세계수의 가호", duration=1.0, str_id=993, perpetual=True)
    )
    board = _board()
    assert maybe_hp_to_mp(state, board) is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.reason == "hp to mp"
    with bind(PartyRecovery()):
        assert try_field_auto_recovery(_state(hp=75, mp=30), _board()) is None
