"""A party-list key waits while the spell cursor is already up."""
from __future__ import annotations

import time

from app._02_state.enums import ActionType
from app._05_action import cursor_verify as cv
from app._05_action.controller import ActionExecutor
from app._05_action.window_bounds import WindowBounds
from app._06_party.types import ActionIntent


def _executor() -> ActionExecutor:
    executor = ActionExecutor(enabled=False, humanize=False)
    executor.pressed = []  # type: ignore[attr-defined]
    executor.box_pressed = []  # type: ignore[attr-defined]

    def _press(name: str, *_args, **_kwargs) -> None:
        executor.pressed.append(name)  # type: ignore[attr-defined]

    def _box(_box: int, key: str, *_args, **_kwargs) -> None:
        executor.box_pressed.append(key)  # type: ignore[attr-defined]

    executor._press_assigned_skill = _press  # type: ignore[method-assign]
    executor._press_box_skill = _box  # type: ignore[method-assign]
    return executor


def _bounds() -> WindowBounds:
    return WindowBounds(left=0, top=0, width=800, height=600)


def test_party_list_heal_does_not_press_while_the_cursor_is_spell() -> None:
    executor = _executor()
    clicks: list[tuple] = []
    cancels: list[str] = []
    executor.mouse.click = lambda *args, **_kwargs: clicks.append(args)  # type: ignore[method-assign]
    intent = ActionIntent(
        action=ActionType.HEAL,
        reason="party_member:list heal",
        hotbar_box=1,
        hotbar_key="f5",
        click_x=75,
        click_y=227,
    )

    def _cancel(_executor: object, *, reason: str = "") -> bool:
        cancels.append(reason)
        return True

    original_aim = cv.cursor_is_spell_aim
    original_cancel = cv.cancel_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]
        cv.cancel_spell_aim = _cancel  # type: ignore[assignment]
        executor._heal(_bounds(), intent)
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert executor.pressed == []  # type: ignore[attr-defined]
    assert clicks == []
    assert cancels == ["press held:heal"]
    assert executor._last_magic_at == 0.0


def test_heal_all_does_not_press_while_the_cursor_is_spell() -> None:
    executor = _executor()
    intent = ActionIntent(action=ActionType.HEAL, reason="party_member:heal all")
    original = cv.cursor_is_spell_aim
    original_cancel = cv.cancel_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]
        cv.cancel_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]
        executor._heal(_bounds(), intent)
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert executor.pressed == []  # type: ignore[attr-defined]


def test_self_heal_still_presses_while_the_cursor_is_spell() -> None:
    executor = _executor()
    intent = ActionIntent(action=ActionType.HEAL, reason="self heal")
    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]
        executor._heal(_bounds(), intent)
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert executor.pressed == ["heal"]  # type: ignore[attr-defined]


def test_party_list_heal_presses_once_the_cursor_is_down() -> None:
    executor = _executor()
    intent = ActionIntent(
        action=ActionType.HEAL,
        reason="party_member:list heal",
        hotbar_box=1,
        hotbar_key="f5",
        click_x=75,
        click_y=227,
    )
    original_aim = cv.cursor_is_spell_aim
    original_wait = cv.wait_party_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        cv.wait_party_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        executor._heal(_bounds(), intent)
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.wait_party_spell_aim = original_wait  # type: ignore[assignment]
    assert executor.pressed == ["heal"]  # type: ignore[attr-defined]


def test_party_list_buff_does_not_press_while_the_cursor_is_spell() -> None:
    executor = _executor()
    clicks: list[tuple] = []
    cancels: list[str] = []
    executor.mouse.click = lambda *args, **_kwargs: clicks.append(args)  # type: ignore[method-assign]
    intent = ActionIntent(
        action=ActionType.BUFF,
        reason="party_member:holy weapon",
        hotbar_box=1,
        hotbar_key="f10",
        click_x=75,
        click_y=227,
    )

    def _cancel(_executor: object, *, reason: str = "") -> bool:
        cancels.append(reason)
        return True

    original_aim = cv.cursor_is_spell_aim
    original_cancel = cv.cancel_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]
        cv.cancel_spell_aim = _cancel  # type: ignore[assignment]
        handled = executor._party_list_buff(intent, _bounds())
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert handled is True
    assert executor.box_pressed == []  # type: ignore[attr-defined]
    assert clicks == []
    assert cancels == ["press held:party_member:holy weapon"]
    assert executor._last_magic_at == 0.0


def _list_heal() -> ActionIntent:
    return ActionIntent(
        action=ActionType.HEAL,
        reason="party_member:list heal",
        hotbar_box=1,
        hotbar_key="f5",
        click_x=75,
        click_y=227,
    )


def test_party_list_keys_wait_two_seconds_after_a_row_click() -> None:
    executor = _executor()
    executor._party_list_click_at = time.time()
    cancels: list[str] = []
    original_aim = cv.cursor_is_spell_aim
    original_cancel = cv.cancel_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        cv.cancel_spell_aim = lambda *_a, **_k: cancels.append("cancel") or True  # type: ignore[assignment]
        executor._heal(_bounds(), _list_heal())
        executor._heal(
            _bounds(), ActionIntent(action=ActionType.HEAL, reason="party_member:heal all")
        )
        handled = executor._party_list_buff(
            ActionIntent(
                action=ActionType.BUFF,
                reason="party_member:holy weapon",
                hotbar_box=1,
                hotbar_key="f10",
                click_x=75,
                click_y=227,
            ),
            _bounds(),
        )
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert handled is True
    assert executor.pressed == []  # type: ignore[attr-defined]
    assert executor.box_pressed == []  # type: ignore[attr-defined]
    assert cancels == []


def test_self_heal_still_presses_during_the_party_list_settle() -> None:
    executor = _executor()
    executor._party_list_click_at = time.time()
    original = cv.cursor_is_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        executor._heal(_bounds(), ActionIntent(action=ActionType.HEAL, reason="self heal"))
    finally:
        cv.cursor_is_spell_aim = original  # type: ignore[assignment]
    assert executor.pressed == ["heal"]  # type: ignore[attr-defined]


def test_party_list_heal_presses_again_after_the_settle() -> None:
    executor = _executor()
    executor._party_list_click_at = time.time() - 3.0
    original_aim = cv.cursor_is_spell_aim
    original_wait = cv.wait_party_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        cv.wait_party_spell_aim = lambda *_args, **_kwargs: False  # type: ignore[assignment]
        executor._heal(_bounds(), _list_heal())
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.wait_party_spell_aim = original_wait  # type: ignore[assignment]
    assert executor.pressed == ["heal"]  # type: ignore[attr-defined]


def test_a_spell_circle_during_the_settle_still_holds_the_key() -> None:
    executor = _executor()
    executor._party_list_click_at = time.time()
    cancels: list[str] = []
    original_aim = cv.cursor_is_spell_aim
    original_cancel = cv.cancel_spell_aim
    try:
        cv.cursor_is_spell_aim = lambda *_args, **_kwargs: True  # type: ignore[assignment]

        def _cancel(_executor: object, *, reason: str = "") -> bool:
            cancels.append(reason)
            return True

        cv.cancel_spell_aim = _cancel  # type: ignore[assignment]
        executor._heal(_bounds(), _list_heal())
    finally:
        cv.cursor_is_spell_aim = original_aim  # type: ignore[assignment]
        cv.cancel_spell_aim = original_cancel  # type: ignore[assignment]
    assert executor.pressed == []  # type: ignore[attr-defined]
    assert cancels == ["press held:heal"]


def test_party_list_cast_waits_match_the_late_circle() -> None:
    assert cv.PARTY_LIST_AIM_WAIT_S == 1.5
    assert cv.PARTY_LIST_RECAST_S == 2.0
