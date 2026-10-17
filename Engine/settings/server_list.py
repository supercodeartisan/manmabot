"""Load selectable Lineage server names from the bundled autologin data."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_LOCALE_TO_FILE = {
    "ko": "servers_ko.json",
    "zh-CN": "servers_zh-CN.json",
    "zh-TW": "servers_zh-TW.json",
    "ja": "servers_en.json",
    "en": "servers_en.json",
}


def _sort_key(value: object) -> tuple:
    text = str(value)
    return (0, int(text)) if text.isdigit() else (1, text)


def _read_server_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
        raw = re.sub(r",\s*([}\]])", r"\1", raw)
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _names_from_table(data: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for _slot, name in _slots_from_table(data):
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _slots_from_table(data: dict) -> list[tuple[tuple[str, str, str], str]]:
    """Server cells in page/row/side order. The same cell is one server."""
    slots: list[tuple[tuple[str, str, str], str]] = []
    for page in sorted(data.keys(), key=_sort_key):
        rows = data.get(page)
        if not isinstance(rows, dict):
            continue
        for row in sorted(rows.keys(), key=_sort_key):
            cols = rows.get(row)
            if not isinstance(cols, dict):
                continue
            for side in ("left", "right"):
                name = str(cols.get(side) or "").strip()
                slots.append(((str(page), str(row), side), name))
    return slots


def _server_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        from login.autologin_service import resolve_autologin_root

        root = resolve_autologin_root()
        dirs.extend((root / "bot" / "data", root / "bot"))
    except Exception:
        pass
    return dirs


@lru_cache(maxsize=16)
def server_names_for_locale(locale: str) -> tuple[str, ...]:
    """Return ordered server names for an account locale."""
    filename = _LOCALE_TO_FILE.get(str(locale or "").strip(), "servers_ko.json")
    for base in _server_search_dirs():
        path = base / filename
        if path.is_file():
            names = tuple(_names_from_table(_read_server_json(path)))
            if names:
                return names
    # Fall back to Korean list if the requested locale file is missing.
    if filename != "servers_ko.json":
        for base in _server_search_dirs():
            path = base / "servers_ko.json"
            if path.is_file():
                return tuple(_names_from_table(_read_server_json(path)))
    return ()


def server_names_list(locale: str) -> list[str]:
    return list(server_names_for_locale(locale))


_TRANSLATE_LOCALES = ("ko", "zh-CN", "zh-TW", "en", "ja")


def _load_locale_table(locale: str) -> dict:
    filename = _LOCALE_TO_FILE.get(str(locale or "").strip(), "servers_ko.json")
    for base in _server_search_dirs():
        path = base / filename
        if path.is_file():
            data = _read_server_json(path)
            if data:
                return data
    return {}


@lru_cache(maxsize=16)
def _server_slot_index(locale: str) -> tuple[dict[tuple[str, str, str], str], dict[str, tuple[str, str, str]]]:
    """Cell → name, and the first cell that holds each name."""
    cells: dict[tuple[str, str, str], str] = {}
    by_name: dict[str, tuple[str, str, str]] = {}
    for slot, name in _slots_from_table(_load_locale_table(locale)):
        cells[slot] = name
        if name and name not in by_name:
            by_name[name] = slot
    return cells, by_name


def server_cells_list(locale: str) -> list[tuple[str, str]]:
    """Ordered ``(name, slot)`` cells. ``slot`` is ``page|row|side``."""
    target = str(locale or "").strip() or "ko"
    ordered = [
        (name, "|".join(slot))
        for slot, name in _slots_from_table(_load_locale_table(target))
        if name
    ]
    if ordered or target == "ko":
        return ordered
    return server_cells_list("ko")


def server_name_at_slot(locale: str, slot_key: str) -> str:
    """Name written in ``locale`` for one grid cell."""
    parts = str(slot_key or "").split("|")
    if len(parts) != 3:
        return ""
    return str(
        _server_slot_index(locale)[0].get((parts[0], parts[1], parts[2])) or ""
    ).strip()


def server_slot_key(name: str, from_locale: str = "") -> str:
    """Grid cell of ``name``, or empty when the name is not in any server table."""
    text = str(name or "").strip()
    if not text:
        return ""
    sources: list[str] = []
    origin = str(from_locale or "").strip()
    if origin:
        sources.append(origin)
    for locale in _TRANSLATE_LOCALES:
        if locale not in sources:
            sources.append(locale)
    for locale in sources:
        slot = _server_slot_index(locale)[1].get(text)
        if slot is not None:
            return "|".join(slot)
    return ""


def translate_server_name(name: str, to_locale: str, from_locale: str = "") -> str:
    """Same server cell, written in ``to_locale``.

    An unknown name stays as typed. It is not replaced by the first server.
    """
    text = str(name or "").strip()
    target = str(to_locale or "").strip() or "ko"
    if not text:
        return ""
    if text in _server_slot_index(target)[1]:
        return text
    sources: list[str] = []
    origin = str(from_locale or "").strip()
    if origin and origin != target:
        sources.append(origin)
    for locale in _TRANSLATE_LOCALES:
        if locale != target and locale not in sources:
            sources.append(locale)
    target_cells = _server_slot_index(target)[0]
    for locale in sources:
        slot = _server_slot_index(locale)[1].get(text)
        if slot is None:
            continue
        translated = str(target_cells.get(slot) or "").strip()
        if translated:
            return translated
    return text
