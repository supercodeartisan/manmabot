"""Game / memory / map probes for status lamps."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from session.paths import (
    overlay_farms_path,
    overlay_patrol_path,
    overlay_safe_path,
    manmabot_root,
)


class Lamp(Enum):
    GRAY = "gray"
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class GameProbe:
    lamp: Lamp
    detail: str
    hwnd: int = 0
    focused: bool = False
    cursor_inside: bool = False
    minimized: bool = False


@dataclass
class MemoryProbe:
    lamp: Lamp
    detail: str
    reader_ok: bool = False
    has_snapshot: bool = False


@dataclass
class MapProbe:
    lamp: Lamp
    detail: str
    farm_names: list[str]
    map_id: str = ""
    map_name: str = ""
    dungeon: bool = False
    patrol_count: int = 0


def _ensure_manmabot_on_path() -> Path:
    root = manmabot_root()
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


def _ensure_ui_on_path() -> None:
    """Product ``UI/`` holds the ``ui`` package (sibling of ``Engine/``)."""
    from session.paths import app_root

    ui_root = app_root() / "UI"
    text = str(ui_root.resolve())
    if ui_root.is_dir() and text not in sys.path:
        sys.path.insert(0, text)


def load_map_pack_safe(map_id: str):
    """Return MapPack or None."""
    try:
        _ensure_manmabot_on_path()
        from app._03_world.space.map_pack import list_map_packs, load_map_pack, resolve_maps_dir

        maps_dir = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
        if maps_dir is None:
            maps_dir = manmabot_root() / "data" / "maps"
        mid = str(map_id or "").strip()
        if not mid:
            return None
        return load_map_pack(maps_dir, mid)
    except Exception:
        return None


def list_map_choices(language: str | None = None) -> list[tuple[str, str, bool]]:
    """``(pack_id, display_name, is_dungeon)`` sorted by id."""
    try:
        _ensure_manmabot_on_path()
        from app._03_world.space.map_pack import list_map_packs, resolve_maps_dir
        from app._04_decision.dungeon import is_dungeon_map
        from i18n.localized_names import map_display_name

        maps_dir = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
        if maps_dir is None:
            maps_dir = manmabot_root() / "data" / "maps"
        packs = list_map_packs(maps_dir)
        return [
            (
                p.id,
                map_display_name(p.id, language, p.name),
                is_dungeon_map(p.id, p.name),
            )
            for p in packs
        ]
    except Exception:
        return []


def is_dungeon_map_id(map_id: str) -> bool:
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return "dungeon" in str(map_id).lower()
    from app._04_decision.dungeon import is_dungeon_map

    return is_dungeon_map(pack.id, pack.name)


def normalize_map_style(value: str | None) -> str:
    return "dungeon" if str(value or "").strip().lower() == "dungeon" else "normal"


def map_style_is_dungeon(map_id: str, map_style: str | None = None) -> bool:
    """Dungeon pack id always wins; island packs still honor explicit style.

    A leftover profile ``map_style=normal`` must not turn ``giran_dungeon_F1``
    into island farming. ``talking_island`` / ``mainland`` stay island unless
    the operator set style to dungeon.
    """
    if is_dungeon_map_id(map_id):
        return True
    if map_style is not None and str(map_style).strip() != "":
        return normalize_map_style(map_style) == "dungeon"
    return False


def engine_farms_yaml_path(map_id: str) -> Optional[Path]:
    """Shipped pack ``farms.yaml`` (read-only from Version 1)."""
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return None
    if pack.farm_areas_path is not None:
        return Path(pack.farm_areas_path)
    return pack.root / "farms.yaml"


def engine_patrol_yaml_path(map_id: str) -> Optional[Path]:
    """Shipped pack ``patrol.yaml`` (read-only from Version 1)."""
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return None
    if pack.patrol_path is not None:
        return Path(pack.patrol_path)
    return pack.root / "patrol.yaml"


def farms_yaml_path(map_id: str) -> Optional[Path]:
    """Read path: userdata overlay if present, else engine pack."""
    overlay = overlay_farms_path(map_id)
    if overlay.is_file():
        return overlay
    return engine_farms_yaml_path(map_id)


def patrol_yaml_path(map_id: str) -> Optional[Path]:
    """Read path: userdata overlay if present, else engine pack."""
    overlay = overlay_patrol_path(map_id)
    if overlay.is_file():
        return overlay
    return engine_patrol_yaml_path(map_id)


def writable_farms_yaml_path(map_id: str) -> Path:
    """Always Version 1 ``UserData/maps/<id>/farms.yaml``."""
    return overlay_farms_path(map_id)


def writable_patrol_yaml_path(map_id: str) -> Path:
    """Always Version 1 ``UserData/maps/<id>/patrol.yaml``."""
    return overlay_patrol_path(map_id)


def engine_safe_yaml_path(map_id: str) -> Optional[Path]:
    """Shipped pack ``safe.yaml`` (read-only from Version 1)."""
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return None
    if pack.safe_areas_path is not None:
        return Path(pack.safe_areas_path)
    return pack.root / "safe.yaml"


def safe_yaml_path(map_id: str) -> Optional[Path]:
    """Read path: userdata rest overlay if present, else engine pack."""
    overlay = overlay_safe_path(map_id)
    if overlay.is_file():
        return overlay
    return engine_safe_yaml_path(map_id)


def writable_safe_yaml_path(map_id: str) -> Path:
    """Always Version 1 ``UserData/maps/<id>/safe.yaml``."""
    return overlay_safe_path(map_id)


def apply_userdata_area_files(
    nav: dict[str, Any],
    map_id: str,
    *,
    include_farms: bool = True,
) -> None:
    """Point navigation at UserData combat/rest files when those overlays exist.

    Inline ``farm_areas`` already chosen by the operator are left in place.
    """
    if include_farms and not nav.get("farm_areas"):
        farms = overlay_farms_path(map_id)
        if farms.is_file():
            nav["farm_areas_file"] = str(farms)
    safe = overlay_safe_path(map_id)
    if safe.is_file():
        nav["safe_areas_file"] = str(safe)


def _farm_range_note(area: dict[str, Any]) -> str:
    """Notes column text: inclusive nav-tile range ``(x0, y0 ~ x1, y1)``."""
    try:
        x0, y0 = int(area["x0"]), int(area["y0"])
        x1, y1 = int(area["x1"]), int(area["y1"])
    except (KeyError, TypeError, ValueError):
        memo = area.get("memo") or area.get("note") or area.get("label") or ""
        return str(memo).strip() if memo else ""
    return f"({x0}, {y0} ~ {x1}, {y1})"


def list_farm_details(map_id: str) -> tuple[list[tuple[str, str]], Optional[str]]:
    """Return ((area name, notes), error).

    Notes show the farm rectangle range start/end in nav tiles
    ``(x0, y0 ~ x1, y1)``, matching the map editor list.
    """
    try:
        _ensure_manmabot_on_path()
        import yaml

        pack = load_map_pack_safe(map_id)
        if pack is None:
            return [], "Map pack could not be loaded."
        path = farms_yaml_path(map_id)
        if path is None or not path.is_file():
            return [], None
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        areas = doc.get("areas") or doc.get("farm_areas") or []
        rows: list[tuple[str, str]] = []
        for area in areas:
            if not isinstance(area, dict) or not area.get("name"):
                continue
            rows.append((str(area["name"]), _farm_range_note(area)))
        return rows, None
    except Exception as exc:
        return [], f"Farm data could not be loaded. ({exc})"


def list_safe_details(map_id: str) -> tuple[list[tuple[str, str]], Optional[str]]:
    """Rest-area names from ``safe.yaml`` (userdata overlay, else pack)."""
    try:
        _ensure_manmabot_on_path()
        import yaml

        pack = load_map_pack_safe(map_id)
        if pack is None:
            return [], "Map pack could not be loaded."
        path = safe_yaml_path(map_id)
        if path is None or not path.is_file():
            return [], None
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        areas = doc.get("areas") or doc.get("safe_areas") or doc.get("farm_areas") or []
        rows: list[tuple[str, str]] = []
        for area in areas:
            if not isinstance(area, dict) or not area.get("name"):
                continue
            rows.append((str(area["name"]), _farm_range_note(area)))
        return rows, None
    except Exception as exc:
        return [], f"Rest areas could not be loaded. ({exc})"


def list_farms_for_map(map_id: str) -> tuple[list[str], Optional[str]]:
    """Return (farm names, error_message)."""
    rows, error = list_farm_details(map_id)
    return [name for name, _memo in rows], error


def list_talking_island_farms() -> tuple[list[str], Optional[str]]:
    """Back-compat wrapper."""
    return list_farms_for_map("talking_island")


def load_selected_farm_rects(
    selected: list[str],
    map_id: str = "talking_island",
) -> list[dict[str, Any]]:
    """YAML area dicts in the user's selected order (for nav override)."""
    _ensure_manmabot_on_path()
    import yaml

    from settings.farm_schedule import farm_rects_in_selection_order

    path = farms_yaml_path(map_id)
    if path is None or not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    areas = doc.get("areas") or doc.get("farm_areas") or []
    return farm_rects_in_selection_order(
        [a for a in areas if isinstance(a, dict)],
        [str(name) for name in selected],
    )


def list_patrol_entries(map_id: str) -> list[tuple[int, int, str]]:
    try:
        _ensure_manmabot_on_path()
        from app._04_decision.patrol import load_patrol_entries_from_yaml

        return load_patrol_entries_from_yaml(patrol_yaml_path(map_id))
    except Exception:
        return []


def _probe_texts(language: str | None) -> dict[str, str]:
    from i18n.strings import normalize_language

    _ensure_ui_on_path()
    from ui.schedule_i18n import tr

    return tr(normalize_language(language))


def localize_probe_detail(detail: str, language: str | None) -> str:
    """Show a probe status line in the operator UI language."""
    text = str(detail or "")
    if not text:
        return text
    texts = _probe_texts(language)
    key = _PROBE_DETAIL_KEYS.get(text)
    if key:
        return str(texts.get(key, text))
    if text.startswith("Game probe failed: "):
        return str(texts.get("probe_game_failed", "Game probe failed: {error}")).format(
            error=text[len("Game probe failed: ") :]
        )
    if text.startswith("Memory monitor disconnected ("):
        inner = text[len("Memory monitor disconnected (") :]
        if inner.endswith(")"):
            inner = inner[:-1]
        return str(
            texts.get("probe_memory_disconnected_err", "Memory monitor disconnected ({error})")
        ).format(error=inner)
    return text


_PROBE_DETAIL_KEYS = {
    "Game window not found": "probe_game_not_found",
    "Game window is minimized": "probe_game_minimized",
    "Game is not in focus": "probe_game_unfocused",
    "Cursor is outside the game window": "probe_game_cursor_out",
    "Game ready": "probe_game_ready",
    "Memory monitor disconnected": "probe_memory_disconnected",
    "Memory connected — waiting for player data": "probe_memory_waiting",
    "Memory connected": "probe_memory_ok",
    "Map data is missing": "probe_map_missing",
    "Add patrol points on the Map tab": "probe_map_add_patrol",
    "Draw at least one farm on the Farms tab": "probe_map_draw_farm",
    "Select at least one farm": "probe_map_select_farm",
}


def probe_map(
    selected_farms: list[str],
    map_id: str = "talking_island",
    language: str | None = None,
    map_style: str | None = None,
) -> MapProbe:
    from i18n.localized_names import map_display_name

    texts = _probe_texts(language)
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return MapProbe(
            Lamp.RED,
            str(texts.get("probe_map_missing", "Map data is missing")),
            [],
            map_id=str(map_id or ""),
        )
    title = map_display_name(pack.id, language, pack.name)
    dungeon = map_style_is_dungeon(pack.id, map_style)
    names, err = list_farms_for_map(pack.id)
    patrol = list_patrol_entries(pack.id)
    if err and not names and not dungeon:
        return MapProbe(
            Lamp.RED,
            err,
            [],
            map_id=pack.id,
            map_name=title,
            dungeon=False,
        )
    if dungeon:
        if not patrol:
            return MapProbe(
                Lamp.YELLOW,
                str(texts.get("probe_map_add_patrol", "Add patrol points on the Map tab")),
                names,
                map_id=pack.id,
                map_name=title,
                dungeon=True,
                patrol_count=0,
            )
        return MapProbe(
            Lamp.GREEN,
            str(texts.get("probe_map_patrol", "{title} · {n} patrol points")).format(
                title=title, n=len(patrol)
            ),
            names,
            map_id=pack.id,
            map_name=title,
            dungeon=True,
            patrol_count=len(patrol),
        )
    chosen = [n for n in selected_farms if n in names]
    if not names:
        return MapProbe(
            Lamp.YELLOW,
            str(texts.get("probe_map_draw_farm", "Draw at least one farm on the Farms tab")),
            [],
            map_id=pack.id,
            map_name=title,
        )
    if not chosen:
        return MapProbe(
            Lamp.YELLOW,
            str(texts.get("probe_map_select_farm", "Select at least one farm")),
            names,
            map_id=pack.id,
            map_name=title,
        )
    return MapProbe(
        Lamp.GREEN,
        str(texts.get("probe_map_farms", "{title} · {n} farms")).format(
            title=title, n=len(chosen)
        ),
        names,
        map_id=pack.id,
        map_name=title,
    )


def _hwnd_pid(hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes

    from win32_prototypes import bind_user32

    pid = wintypes.DWORD()
    user32 = ctypes.windll.user32
    bind_user32(user32)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _is_game_focused(game_hwnd: int) -> bool:
    """True if the foreground window belongs to the same process as the game.

    Games often put a child/owned window in front; exact hwnd equality is too
    strict and keeps the bot stuck in pause after the user clicks the game.
    """
    import ctypes

    from win32_prototypes import bind_user32

    user32 = ctypes.windll.user32
    bind_user32(user32)
    fg = int(user32.GetForegroundWindow() or 0)
    if not fg or not game_hwnd:
        return False
    if fg == int(game_hwnd):
        return True
    # Walk up to root owner / parent
    root = int(user32.GetAncestor(fg, 2) or 0)  # GA_ROOT = 2
    if root and root == int(game_hwnd):
        return True
    try:
        return _hwnd_pid(fg) == _hwnd_pid(game_hwnd) and _hwnd_pid(game_hwnd) != 0
    except Exception:
        return False


def probe_game(process_name: str = "LC.exe") -> GameProbe:
    try:
        _ensure_manmabot_on_path()
        from app._05_action.window_bounds import (
            find_game_window,
            get_client_bounds,
            is_window_minimized,
        )
        import ctypes
        from ctypes import wintypes

        from win32_prototypes import bind_user32

        user32 = ctypes.windll.user32
        bind_user32(user32)
        hwnd = find_game_window(process_name) or 0
        if not hwnd:
            return GameProbe(Lamp.RED, "Game window not found")

        minimized = bool(is_window_minimized(hwnd))
        if minimized:
            return GameProbe(
                Lamp.YELLOW,
                "Game window is minimized",
                hwnd=hwnd,
                minimized=True,
            )

        focused = _is_game_focused(hwnd)
        bounds = get_client_bounds(hwnd)
        cursor_inside = False
        if bounds is not None and bounds.valid:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cursor_inside = (
                bounds.left <= pt.x < bounds.left + bounds.width
                and bounds.top <= pt.y < bounds.top + bounds.height
            )

        if not focused:
            return GameProbe(
                Lamp.YELLOW,
                "Game is not in focus",
                hwnd=hwnd,
                focused=False,
                cursor_inside=cursor_inside,
            )
        if not cursor_inside:
            return GameProbe(
                Lamp.YELLOW,
                "Cursor is outside the game window",
                hwnd=hwnd,
                focused=True,
                cursor_inside=False,
            )
        return GameProbe(
            Lamp.GREEN,
            "Game ready",
            hwnd=hwnd,
            focused=True,
            cursor_inside=True,
        )
    except Exception as exc:
        return GameProbe(Lamp.RED, f"Game probe failed: {exc}")


def bring_game_to_front(hwnd: int) -> None:
    if not hwnd:
        return
    import ctypes

    from win32_prototypes import bind_user32

    user32 = ctypes.windll.user32
    bind_user32(user32)
    # Allow SetForegroundWindow from a background process (best-effort).
    try:
        user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:
        pass
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    try:
        user32.BringWindowToTop(hwnd)
    except Exception:
        pass


def memory_probe_from_player(
    snap: Any,
    *,
    reader_ok: bool,
    error: str | None = None,
) -> MemoryProbe:
    """Classify player memory for the UI chip vs the Start snapshot gate.

    The in-process DLL is "on" as soon as it is loaded (``reader_ok``). A live
    LC.exe snapshot is separate (``has_snapshot``). Start must wait for the
    snapshot; the chip must not show 꺼짐 just because the character is not
    in the world yet.
    """
    if isinstance(snap, dict):
        raw = snap.get("player") or {}
        pos = raw.get("pos")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            return MemoryProbe(
                Lamp.YELLOW,
                "Memory connected — waiting for player data",
                reader_ok=True,
                has_snapshot=True,
            )
        if int(pos[0]) == 0 and int(pos[1]) == 0:
            return MemoryProbe(
                Lamp.YELLOW,
                "Memory connected — waiting for player data",
                reader_ok=True,
                has_snapshot=True,
            )
        return MemoryProbe(
            Lamp.GREEN, "Memory connected", reader_ok=True, has_snapshot=True
        )
    if reader_ok:
        return MemoryProbe(
            Lamp.YELLOW,
            "Memory connected — waiting for player data",
            reader_ok=True,
            has_snapshot=False,
        )
    return MemoryProbe(
        Lamp.RED,
        error or "Memory monitor disconnected",
        reader_ok=False,
        has_snapshot=False,
    )


def probe_memory() -> MemoryProbe:
    try:
        from app._01_perception.sensors import shared_sensors

        sensors = shared_sensors()
        snap = sensors.pull_player()
        reader_ok = bool(
            getattr(sensors, "_memory_enabled", False)
            and getattr(sensors, "_monitor", None) is not None
        )
        return memory_probe_from_player(snap, reader_ok=reader_ok)
    except Exception as exc:
        return MemoryProbe(
            Lamp.RED,
            f"Memory monitor disconnected ({exc})",
            reader_ok=False,
            has_snapshot=False,
        )


def pause_reason_from_game(
    game: GameProbe,
    *,
    require_cursor_inside: bool = True,
) -> Optional[str]:
    """Return reason code if Running should auto-pause, else None.

    ``require_cursor_inside``: for auto-resume after the user focuses the game
    (e.g. Alt-Tab), only require focus — the cursor may still sit over our UI.
    """
    if game.lamp == Lamp.RED:
        return None  # start gate, not mid-run pause code
    if game.minimized:
        return "minimized"
    if not game.focused:
        return "not_focused"
    if require_cursor_inside and not game.cursor_inside:
        return "cursor_outside"
    return None
