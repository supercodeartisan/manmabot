"""A live spell circle is a cast point. An out-of-range circle is not a miss."""
from __future__ import annotations

from app._05_action import cursor_verify as cv
from app._05_action.cursor_catalog import CursorCategory
from app._05_action.cursor_match import CursorMatch


class _Mouse:
    def __init__(self) -> None:
        self._last_pos = (10, 10)

    def move(self, _x: float, _y: float, *, snap: bool = False) -> None:
        del snap


class _Executor:
    def __init__(self) -> None:
        self.mouse = _Mouse()
        self.last_cursor_match = None
        self.last_cursor_reject_reason = None
        self._attack_aim_lock = None
        self._attack_aim_idx = 0
        self.mage_spell_ready = False
        self.spell_aim_suppressed = False


class _Matcher:
    min_score = 0.98


def _match(label: str, score: float = 1.0) -> CursorMatch:
    category = (
        CursorCategory.SPELL if label.startswith("spell") else CursorCategory.ATTACK
    )
    return CursorMatch(label=label, category=category, score=score)


def test_ready_spell_is_the_aim_point() -> None:
    executor = _Executor()
    original_probe = cv._probe_labels
    original_matcher = cv.get_cursor_matcher
    try:
        cv._probe_labels = lambda *_a, **_k: _match("spell")  # type: ignore[assignment]
        cv.get_cursor_matcher = lambda: _Matcher()  # type: ignore[assignment]
        hit = cv.find_attack_aim_point(executor, [(40.0, 50.0)], target_id=2)
    finally:
        cv._probe_labels = original_probe  # type: ignore[assignment]
        cv.get_cursor_matcher = original_matcher  # type: ignore[assignment]
    assert hit == (40.0, 50.0)
    assert executor.mage_spell_ready is True
    assert executor.spell_aim_suppressed is False


def test_out_of_range_circle_cancels_without_a_miss() -> None:
    executor = _Executor()
    reasons: list[str] = []
    original_probe = cv._probe_labels
    original_matcher = cv.get_cursor_matcher
    original_cancel = cv.cancel_spell_aim
    try:
        cv._probe_labels = lambda *_a, **_k: _match("spell_out_range")  # type: ignore[assignment]
        cv.get_cursor_matcher = lambda: _Matcher()  # type: ignore[assignment]

        def _cancel(_executor: object, *, reason: str = "") -> bool:
            reasons.append(reason)
            return True

        cv.cancel_spell_aim = _cancel  # type: ignore[assignment]
        hit = cv.find_attack_aim_point(executor, [(40.0, 50.0)], target_id=2)
    finally:
        cv._probe_labels = original_probe  # type: ignore[assignment]
        cv.get_cursor_matcher = original_matcher  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert hit is None
    assert executor.spell_aim_suppressed is True
    assert executor.last_cursor_reject_reason is None
    assert reasons == ["aim:spell circle"]


if __name__ == "__main__":
    test_ready_spell_is_the_aim_point()
    test_out_of_range_circle_cancels_without_a_miss()
    print("spell aim hold tests ok")
