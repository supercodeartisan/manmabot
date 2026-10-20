"""Focus fire with overkill prevention.

The leader's target is filled first: shooters (largest expected damage first)
are added until their combined damage covers the target's HP times
``overkill_margin``. Leftover shooters move to the next target by priority,
then distance. A boss, or a target whose HP is unknown, takes every shooter
that can reach it. Shooters left after every target is covered pile onto the
focus target.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class Target:
    id: int
    hp: Optional[float] = None
    max_hp: Optional[float] = None
    priority: float = 0.0
    dist: Optional[int] = None
    boss: bool = False


@dataclass(frozen=True)
class Shooter:
    name: str
    expected_damage: float
    # ``None`` = can reach every target.
    reach: Optional[frozenset[int]] = None

    def can_hit(self, target_id: int) -> bool:
        return self.reach is None or int(target_id) in self.reach


def _is_boss(t: Target, boss_hp: Optional[float]) -> bool:
    if t.boss:
        return True
    if boss_hp is None:
        return False
    hp = t.max_hp if t.max_hp is not None else t.hp
    return hp is not None and float(hp) >= float(boss_hp)


def _ordered_targets(focus_id: Optional[int], targets: Iterable[Target]) -> list[Target]:
    rows = list(targets)
    focus = [t for t in rows if focus_id is not None and int(t.id) == int(focus_id)]
    rest = [t for t in rows if not (focus_id is not None and int(t.id) == int(focus_id))]
    rest.sort(
        key=lambda t: (
            -float(t.priority),
            t.dist if t.dist is not None else 1 << 30,
            int(t.id),
        )
    )
    return focus + rest


def allocate_targets(
    focus_id: Optional[int],
    targets: Iterable[Target],
    shooters: Sequence[Shooter],
    *,
    overkill_margin: float = 1.15,
    boss_hp: Optional[float] = None,
) -> dict[str, Optional[int]]:
    """Map each shooter name to a target id (``None`` when nothing is reachable)."""
    order = _ordered_targets(focus_id, targets)
    free = sorted(shooters, key=lambda s: (-float(s.expected_damage), s.name))
    out: dict[str, Optional[int]] = {s.name: None for s in shooters}
    margin = max(1.0, float(overkill_margin))

    for t in order:
        if not free:
            break
        need = None if t.hp is None or _is_boss(t, boss_hp) else max(0.0, float(t.hp)) * margin
        dealt = 0.0
        keep: list[Shooter] = []
        for s in free:
            if not s.can_hit(t.id) or (need is not None and dealt >= need):
                keep.append(s)
                continue
            out[s.name] = int(t.id)
            dealt += max(0.0, float(s.expected_damage))
        free = keep

    if focus_id is not None and any(int(t.id) == int(focus_id) for t in order):
        for s in free:
            if s.can_hit(focus_id):
                out[s.name] = int(focus_id)
    return out


__all__ = ["Shooter", "Target", "allocate_targets"]
