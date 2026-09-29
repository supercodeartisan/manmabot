"""Global hotkeys bound from profile."""
from __future__ import annotations

import ctypes
import sys
from typing import Callable, Optional

import keyboard

from manmabot_v1.strings import DEFAULT_HOTKEYS

# Windows virtual keys: Alt, left Alt, right Alt.
_VK_ALTS = (0x12, 0xA4, 0xA5)
_KEYEVENTF_KEYUP = 0x0002

_MOD_ALIASES = {"control": "ctrl", "option": "alt"}
_MOD_KEYS = {
    "alt": ("alt", "left alt", "right alt", "alt gr"),
    "ctrl": ("ctrl", "left ctrl", "right ctrl", "control"),
    "shift": ("shift", "left shift", "right shift"),
}
_ALL_MOD_NAMES = {n for names in _MOD_KEYS.values() for n in names}


def _force_alt_up() -> None:
    """Clear a latched Alt if Windows still thinks it is down."""
    try:
        keyboard.release("alt")
        keyboard.release("right alt")
        keyboard.release("alt gr")
    except Exception:
        pass
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        for vk in _VK_ALTS:
            user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def _mod_down(mod: str) -> bool:
    return any(keyboard.is_pressed(name) for name in _MOD_KEYS.get(mod, (mod,)))


def _parse_combo(combo: str) -> tuple[frozenset[str], str]:
    parts = [p.strip().lower() for p in str(combo).split("+") if p.strip()]
    if not parts:
        raise ValueError("empty shortcut")
    key = parts[-1]
    mods = frozenset(_MOD_ALIASES.get(p, p) for p in parts[:-1])
    return mods, key


def install_alt_menu_guard(widget) -> None:
    """Stop Tk from treating Alt as a menu mnemonic (looks like stuck Alt).

    Do not subclass the Win32 WndProc on a Tk/CustomTkinter HWND — CallWindowProc
    against Tk's wrapper is unsafe and can access-violate.
    """

    def _break(_event=None):
        return "break"

    for seq in (
        "<KeyPress-Alt_L>",
        "<KeyRelease-Alt_L>",
        "<KeyPress-Alt_R>",
        "<KeyRelease-Alt_R>",
        "<Alt-Key>",
        "<Alt-KeyPress>",
        "<Alt-KeyRelease>",
    ):
        widget.bind_all(seq, _break)


class HotkeyManager:
    def __init__(self) -> None:
        self._handles: list = []
        self._hook = None

    def clear(self) -> None:
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
        for h in self._handles:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._handles.clear()

    def bind(
        self,
        hotkeys: dict[str, str],
        *,
        on_pause_resume: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> Optional[str]:
        """Register hotkeys. Returns error message on conflict/failure."""
        self.clear()
        mapping = dict(DEFAULT_HOTKEYS)
        mapping.update({k: str(v).lower() for k, v in hotkeys.items()})
        # Drop removed actions (e.g. legacy toggle_preview in saved profiles).
        mapping = {k: v for k, v in mapping.items() if k in DEFAULT_HOTKEYS}

        # Duplicate check
        seen: dict[str, str] = {}
        for action, combo in mapping.items():
            if combo in seen:
                return f"That shortcut is already used by {seen[combo]}."
            seen[combo] = action

        try:
            parsed: list[tuple[frozenset[str], str, Callable[[], None]]] = [
                (*_parse_combo(mapping["pause_resume"]), on_pause_resume),
                (*_parse_combo(mapping["stop"]), on_stop),
            ]
        except ValueError as exc:
            return f"Failed to bind hotkeys: {exc}"

        def _hook(event) -> bool:
            # Let Alt (and other modifiers) through. Suppressing them with
            # add_hotkey(..., suppress=True) leaves VK_MENU stuck down.
            try:
                if getattr(event, "event_type", None) != "down":
                    return True
                name = str(getattr(event, "name", "") or "").lower()
                if name in _ALL_MOD_NAMES:
                    return True
                for mods, key, cb in parsed:
                    if name != key:
                        continue
                    if any(_mod_down(m) is False for m in mods):
                        continue
                    extra = False
                    for m in _MOD_KEYS:
                        if m not in mods and _mod_down(m):
                            extra = True
                            break
                    if extra:
                        continue
                    try:
                        cb()
                    finally:
                        _force_alt_up()
                    return False
                return True
            except Exception:
                return True

        try:
            # Do not suppress every key. suppress=True plus Interception
            # injection can swallow the real keyboard after login.
            self._hook = keyboard.hook(_hook, suppress=False)
        except Exception as exc:
            self.clear()
            return f"Failed to bind hotkeys: {exc}"
        return None
