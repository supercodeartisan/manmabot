"""Vision preview marks enter/next-farm walk-around detours."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app._02_vision.preview import (
    DETOUR_REASON,
    draw_vision_preview,
    enter_farm_detour_active,
)
from app._03_world import ActionType, GameState, Position


def _action(*, reason: str, dest=(0.55, 0.42)):
    return SimpleNamespace(
        action=ActionType.TRAVELING,
        reason=reason,
        target_id=None,
        destination=Position(x=dest[0], y=dest[1]),
    )


def test_enter_farm_detour_active_by_reason():
    assert enter_farm_detour_active(_action(reason=DETOUR_REASON))
    assert not enter_farm_detour_active(_action(reason="enter farm area"))


def test_enter_farm_detour_active_by_blackboard_state():
    board = SimpleNamespace(
        travel_purpose="enter_farm",
        travel_unstick_active=True,
        scratch={"enter_farm_detour_origin": [10, 20]},
    )
    assert enter_farm_detour_active(
        _action(reason="enter farm area"), board
    )
    board.travel_unstick_active = False
    assert not enter_farm_detour_active(
        _action(reason="enter farm area"), board
    )


def test_draw_vision_preview_shows_detour_hud_line():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    world = GameState()
    board = SimpleNamespace(
        nav_waypoint=(12, 34),
        nav_goal=(40, 50),
        world_origin=SimpleNamespace(x=10, y=20),
        travel_purpose="next_farm",
        travel_unstick_active=True,
        scratch={
            "enter_farm_detour_origin": [10, 20],
            "enter_farm_detour_tried": [[11, 20], [12, 21]],
        },
    )
    preview = draw_vision_preview(
        frame,
        _action(reason=DETOUR_REASON),
        world,
        blackboard=board,
        scale=0.5,
    )
    assert preview is not None and preview.size > 0
    # HUD strip is under the game pane; ensure DETOUR text was rendered
    # by checking non-black pixels exist in the info region.
    game_h = int(240 * 0.5)
    info = preview[game_h:]
    assert info.shape[0] > 0
    assert int(info.max()) > 0
