"""A live spell circle is a cast point. An out-of-range circle is not a miss."""
from __future__ import annotations

import time

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


def test_party_list_waits_for_the_spell_cursor() -> None:
    seen = {"n": 0}

    def _aim(_executor: object = None) -> bool:
        seen["n"] += 1
        return seen["n"] >= 2

    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = _aim  # type: ignore[assignment]
        ready = cv.wait_party_spell_aim(None, reason="buff", wait_s=0.2, poll_s=0.01)
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert ready is True
    assert seen["n"] >= 2


class _Keys:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _ClickMouse:
    def __init__(self) -> None:
        self._last_pos = (1.0, 1.0)
        self.clicks: list[tuple[float, float, str]] = []

    def click(self, x: float, y: float, button: str = "left", *, snap: bool = False) -> None:
        del snap
        self.clicks.append((float(x), float(y), button))


class _Bounds:
    valid = True
    left = 100
    top = 50
    width = 800
    height = 600


class _Capture:
    content_bounds = _Bounds()


def test_stuck_spell_right_clicks_inside_the_view() -> None:
    executor = _Executor()
    executor.keyboard = _Keys()
    executor.mouse = _ClickMouse()
    executor._perception_capture = _Capture()
    seen = {"n": 0}

    def _aim(_executor: object = None) -> bool:
        seen["n"] += 1
        return seen["n"] < 4

    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = _aim  # type: ignore[assignment]
        active = cv.cancel_spell_aim(executor, reason="party buff")
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert active is True
    assert executor.keyboard.pressed == []
    assert executor.mouse.clicks == [(100 + 800 * 0.62, 50 + 600 * 0.45, "right")]


def test_a_failed_view_cancel_is_not_repeated_until_the_cursor_drops() -> None:
    executor = _Executor()
    executor.keyboard = _Keys()
    executor.mouse = _ClickMouse()
    executor._perception_capture = _Capture()
    seen = {"spell": True}

    def _aim(_executor: object = None) -> bool:
        return bool(seen["spell"])

    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = _aim  # type: ignore[assignment]
        cv.cancel_spell_aim(executor, reason="heal")
        cv.cancel_spell_aim(executor, reason="heal")
        assert len(executor.mouse.clicks) == 1
        seen["spell"] = False
        assert cv.cancel_spell_aim(executor, reason="heal") is False
        seen["spell"] = True
        cv.cancel_spell_aim(executor, reason="heal")
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert [click[2] for click in executor.mouse.clicks] == ["right", "right"]
    assert executor.keyboard.pressed == []


def test_a_stuck_circle_presses_the_party_key_once_and_retries_the_view() -> None:
    executor = _Executor()
    executor.keyboard = _Keys()
    executor.mouse = _ClickMouse()
    executor._perception_capture = _Capture()
    cv.remember_spell_aim_key(executor, "f10", 1)

    def _aim(_executor: object = None) -> bool:
        return True

    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = _aim  # type: ignore[assignment]
        cv.cancel_spell_aim(executor, reason="party buff")
        cv.cancel_spell_aim(executor, reason="party buff")
        assert executor.keyboard.pressed == ["f10"]
        assert len(executor.mouse.clicks) == 1
        executor._spell_view_click_at = time.monotonic() - cv.SPELL_AIM_VIEW_RETRY_S
        cv.cancel_spell_aim(executor, reason="party buff")
        cv.cancel_spell_aim(executor, reason="party buff")
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert [click[2] for click in executor.mouse.clicks] == ["right", "right"]
    assert executor.keyboard.pressed == ["f10"]


def test_a_late_circle_keeps_the_party_key_until_it_appears() -> None:
    executor = _Executor()
    executor.keyboard = _Keys()
    cv.remember_spell_aim_key(executor, "f10", 1)
    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        assert cv.cancel_spell_aim(executor, reason="aim missed") is False
        assert executor._spell_aim_key == "f10"
        executor._spell_aim_key_at = time.monotonic() - cv.SPELL_AIM_KEY_GRACE_S
        assert cv.cancel_spell_aim(executor, reason="aim missed") is False
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert executor._spell_aim_key == ""


def test_party_list_skips_the_click_when_the_cursor_stays_down() -> None:
    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        ready = cv.wait_party_spell_aim(None, reason="buff", wait_s=0.0)
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert ready is False


if __name__ == "__main__":
    test_ready_spell_is_the_aim_point()
    test_out_of_range_circle_cancels_without_a_miss()
    test_party_list_waits_for_the_spell_cursor()
    test_party_list_skips_the_click_when_the_cursor_stays_down()
    test_stuck_spell_right_clicks_inside_the_view()
    test_a_failed_view_cancel_is_not_repeated_until_the_cursor_drops()
    print("spell aim hold tests ok")
