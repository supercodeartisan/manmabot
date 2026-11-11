"""A same-map scroll is skipped only when the body is already at that hub."""

from app._04_decision.behavior_tree import Status
from app._04_decision.world_nav.ready.planner import PlanResult, PlanStep
from app._04_decision.world_nav.session import SCROLL_LOCAL_TILES, WorldNavSession


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.intent = None
        self.current_goal = None

    def emit(self, *_args, **kwargs) -> None:
        self.intent = kwargs.get("reason")


def _scroll(to_x: int, to_y: int, map_id: int = 0) -> PlanStep:
    return PlanStep(
        op="talking_scroll",
        cost_tiles=10,
        detail={
            "from": {"mapId": map_id, "x": 32538, "y": 33098},
            "to": {"mapId": map_id, "x": to_x, "y": to_y},
            "label": "말하는 섬/마법서 상인",
            "ui": {
                "click": {"x": 64, "y": 160},
                "snapshot_size": {"width": 800, "height": 600},
            },
        },
    )


def _walk() -> PlanStep:
    return PlanStep(
        op="walk",
        cost_tiles=20,
        detail={
            "from": {"mapId": 0, "x": 32560, "y": 33088},
            "to": {"mapId": 0, "x": 32626, "y": 33150},
        },
    )


def _session(scroll: PlanStep) -> WorldNavSession:
    session = WorldNavSession(reason="party_schedule", phase="ready")
    session.plan = PlanResult(ok=True, steps=[scroll, _walk()])
    return session


def test_the_logged_meet_skips_the_nearby_hub_and_walks(monkeypatch) -> None:
    """02:12 meet (32538, 33098) sat 22 tiles from the spellbook hub."""
    started: dict = {}
    cast: dict = {}

    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": 0, "x": 32538, "y": 33098}
        )(),
    )

    def _walk_step(self, step, pose, blackboard, state):
        started["to"] = (step.detail["to"]["x"], step.detail["to"]["y"])
        return Status.SUCCESS

    def _cast(*_a, **_k):
        cast["hit"] = True
        return Status.SUCCESS

    monkeypatch.setattr(WorldNavSession, "_start_walk", _walk_step)
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll_uv",
        _cast,
    )
    session = _session(_scroll(32560, 33088))
    assert max(abs(32538 - 32560), abs(33098 - 33088)) <= SCROLL_LOCAL_TILES
    status = session.tick(object(), _Board())
    assert status is Status.SUCCESS
    assert "hit" not in cast
    assert started["to"] == (32626, 33150)
    assert session.step_i == 1


def test_a_far_same_map_scroll_still_casts(monkeypatch) -> None:
    cast: dict = {}
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": 0, "x": 32538, "y": 33098}
        )(),
    )

    def _cast(*_a, **_k):
        cast["hit"] = True
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll_uv",
        _cast,
    )
    session = _session(_scroll(32538 + 400, 33098))
    session.tick(object(), _Board())
    assert cast["hit"] is True
    assert session.phase == "scroll"
    assert session.step_i == 0


def test_a_different_map_still_casts(monkeypatch) -> None:
    cast: dict = {}
    monkeypatch.setattr(
        "app._04_decision.world_nav.session.live_pose_from_state",
        lambda _state, fresh=False: type(
            "P", (), {"map_id": 4, "x": 32560, "y": 33088}
        )(),
    )

    def _cast(*_a, **_k):
        cast["hit"] = True
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll_uv",
        _cast,
    )
    session = _session(_scroll(32560, 33088, map_id=0))
    session.tick(object(), _Board())
    assert cast["hit"] is True
    assert session.phase == "scroll"
