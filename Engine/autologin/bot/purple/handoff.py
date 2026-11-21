"""Handoff — transfer the engine's result to the bot/pipeline contract.

The old S1-S3 path ended by setting bot.phase=GAME_LOGIN and flagging
_purple_logged_in. This module centralizes that. It is the ONLY place that
writes the handoff flags; the engine itself stays pure.
"""
from __future__ import annotations

import time

from .observe import S_GAME_READY, S_HANDOFF


def _raise_game_on_top_via_input(bot) -> bool:
    """Force the game window to the top, bypassing UIPI foreground lock.

    SetForegroundWindow fails under UIPI when the caller is medium integrity.
    Interception's device-level input (title-bar click + Alt+Esc) works, but
    Alt+Esc leaves a Shell_InputSwitchDismissOverlay that can cover the game
    center — so we always dismiss it (Esc) and re-verify after use.
    """
    game = getattr(bot, "game", None)
    if game is None or not getattr(game, "valid", False):
        return False

    def on_top():
        try:
            return bool(getattr(bot, "_game_on_top", lambda: False)())
        except Exception:
            return False

    try:
        # Preferred: the bot's own verified helper (minimize Purple + raise LC
        # + verify center pixel). Short attempts to avoid burning time.
        prepare = getattr(bot, "_prepare_game_foreground", None)
        if callable(prepare) and prepare(attempts=3):
            return True
    except Exception:
        pass
    try:
        from win import interception
        if not interception.init():
            return False
        rect = game.rect
        title_x = rect.left + rect.width // 2
        title_y = rect.top + 15
        interception.move(title_x, title_y)
        time.sleep(0.05)
        interception.click(title_x, title_y)
        time.sleep(0.4)
        if on_top():
            return True
        for _ in range(3):
            interception.key_down(0x12)   # Alt
            interception.tap(0x1B)        # Esc
            interception.key_up(0x12)
            time.sleep(0.3)
            # Dismiss the Alt+Esc input-switch overlay so it cannot cover the
            # game center. Press Esc once more after the Alt+Esc combo.
            interception.tap(0x1B)
            time.sleep(0.4)
            if on_top():
                return True
    except Exception:
        pass
    return False


def apply_handoff(bot, ctx, engine=None) -> None:
    """Set the S4+ consumed contract after a successful game-ready run."""
    shake_armed = bool(
        getattr(bot, "_shake_after_relaunch", False)
        or getattr(ctx, "shake_armed", False))
    # Attach the real game window if the bot hasn't found it yet. The engine
    # has already verified a visible GLFW30 window; find_game attaches it.
    try:
        if not getattr(bot, "game", None) or not getattr(bot.game, "valid", False):
            if callable(getattr(bot, "find_game", None)):
                bot.find_game()
    except Exception:
        pass
    # GameFlow owns AUTH classification and the bounded close/relaunch/shake
    # sequence. A generic webview class alone does not identify AUTH_CHOICE.
    # The game window must be the visible, focused top window before S5/GameFlow
    # starts OCR and clicks. S4 re-verifies, but this makes the contract hold
    # at hand-off time instead of silently proceeding covered.
    # When shake is armed, keep foreground work short — boot-status UI is brief.
    if shake_armed:
        try:
            prepare = getattr(bot, "_prepare_game_foreground", None)
            if callable(prepare):
                prepare(attempts=2)
            else:
                _raise_game_on_top_via_input(bot)
        except Exception:
            pass
    else:
        _raise_game_on_top_via_input(bot)
    bot._purple_logged_in = True
    bot._game_proc_seen = True
    ctx.purple_logged_in = True
    # AUTH relaunch marker must reach S5; never clear it during Purple handoff.
    if shake_armed:
        bot._shake_after_relaunch = True
        ctx.shake_armed = True
    # The bot's phase machine will move to GAME_LOGIN via its own S4/flow;
    # we set the safe baseline here and leave the final transition to the
    # existing pipeline (which still owns the game window).
    try:
        from base import Phase
        bot._set_phase(Phase.GAME_LOGIN)
    except Exception:
        pass


def engine_succeeded(engine) -> bool:
    return engine.state in (S_GAME_READY, S_HANDOFF)
