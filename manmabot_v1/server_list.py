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
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


def _server_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        from manmabot_v1.autologin_service import resolve_autologin_root

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
