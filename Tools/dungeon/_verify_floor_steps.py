"""Offline checks for dungeon floor steps. Does not click or walk."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "Engine"
for path in (ROOT, ENGINE):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from app._04_decision.dungeon_floor_route import (  # noqa: E402
    FloorRouteSession,
    FloorTransition,
    FloorWalk,
    PickedPoint,
    choice_for_pack,
    floor_of_pack,
    needs_floor_route,
    plan_floor_steps,
    same_dungeon_family,
    world_nav_entrance_map_id,
    _snap,
    _terrain_from_nav,
)


def _start(pack_id: str, world_xy: tuple[int, int]):
    choice = choice_for_pack(pack_id)
    assert choice is not None
    scale = choice.pixel_scale
    nav = (
        (int(world_xy[0]) - choice.origin_x) // scale,
        (int(world_xy[1]) - choice.origin_y) // scale,
    )
    terrain = _terrain_from_nav(choice.nav_path, scale)
    snapped = _snap(terrain, nav) if terrain is not None else nav
    assert snapped is not None, pack_id
    return PickedPoint(choice=choice, nav_x=snapped[0], nav_y=snapped[1])


def _show(title: str, steps) -> None:
    print(f"== {title} steps={len(steps)}")
    for index, step in enumerate(steps):
        if isinstance(step, FloorWalk):
            print(f"  {index} WALK map={step.map_id} cell={step.cell}")
        else:
            print(
                f"  {index} TRANSITION {step.kind} "
                f"{step.from_map_id}->{step.to_map_id} "
                f"entrance={step.entrance_world} land={step.landing_world} "
                f"gate={step.gate_compatible}"
            )


def main() -> int:
    f1 = "gludio_dungeon_F1"
    f2 = "gludio_dungeon_F2"
    f3 = "gludio_dungeon_F3"
    giran = "giran_dungeon_F1"

    # 1. Entrance floor keeps the old world-nav goal.
    assert needs_floor_route(f1) is False
    assert world_nav_entrance_map_id(f1) is None
    print("F1 goal: existing world nav (no floor route)")

    # 2. F2 world nav stops on F1 (map 7).
    assert needs_floor_route(f2) is True
    assert world_nav_entrance_map_id(f2) == 7
    start = _start(f1, (32740, 32807))
    to_f2 = plan_floor_steps(start, f2)
    _show("F1 -> F2", to_f2)
    assert to_f2, "F2 route empty"
    assert isinstance(to_f2[0], FloorWalk)
    assert all(isinstance(step, FloorWalk) or step.gate_compatible for step in to_f2)
    assert isinstance(to_f2[-1], FloorTransition)
    assert to_f2[-1].to_map_id == 8
    assert len([step for step in to_f2 if isinstance(step, FloorWalk)]) == 1
    assert all(step.map_id == 7 for step in to_f2 if isinstance(step, FloorWalk))

    # 3. F3 keeps F1 then F2 then F3, and confirms each transition.
    assert world_nav_entrance_map_id(f3) == 7
    to_f3 = plan_floor_steps(start, f3)
    _show("F1 -> F3", to_f3)
    transitions = [step for step in to_f3 if isinstance(step, FloorTransition)]
    assert [step.to_map_id for step in transitions] == [8, 9]
    assert len([step for step in to_f3 if isinstance(step, FloorWalk)]) == 2
    maps_before = []
    seen = 7
    for step in to_f3:
        if isinstance(step, FloorWalk):
            assert step.map_id == seen
        else:
            assert step.from_map_id == seen
            maps_before.append(step.to_map_id)
            seen = step.to_map_id
    assert maps_before == [8, 9]

    # 7. Another dungeon's floor is not this family.
    assert same_dungeon_family(f1, f2) is True
    assert same_dungeon_family(f1, giran) is False
    assert floor_of_pack(giran) is not None
    assert floor_of_pack(f2).complex_name != floor_of_pack(giran).complex_name

    # 6. A failed gate does not advance the route.
    session = FloorRouteSession(target_pack=f2, complex_name="글루디오 던전", steps=to_f2)
    session.phase = "transition"
    session.index = len(to_f2) - 1
    session.note_gate(False, 7)
    assert session.index == len(to_f2) - 1
    assert session.gate_ok is False
    print("failed gate keeps index", session.index)

    # 10. Unknown pack fails closed.
    try:
        plan_floor_steps(start, "not_a_dungeon_pack")
    except Exception as exc:
        print("missing pack:", type(exc).__name__)
    else:
        raise SystemExit("missing pack was accepted")

    print("floor step checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
