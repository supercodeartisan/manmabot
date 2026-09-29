"""Ground-item pickup filter. Names may be Korean or Chinese.

``all`` picks up every ground item (adena-only mode is applied earlier).
``blacklist`` skips listed names. ``whitelist`` picks up only listed names.
A listed Korean name also matches its Chinese label, and the reverse.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_MODE_ALL = "all"
_MODE_BLACKLIST = "blacklist"
_MODE_WHITELIST = "whitelist"
_MODES = {_MODE_ALL, _MODE_BLACKLIST, _MODE_WHITELIST}

# Names that are the same item across languages, even without the icon pack.
_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"아데나", "金幣", "金币", "adena"}),
)

_mode = _MODE_ALL
_wanted: set[str] = set()
_alias_of: dict[str, str] = {}


def _fold(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _zh_names_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "manmabot_v1"
        / "hotbar"
        / "icons_unique"
        / "zh_names.json"
    )


def _load_icon_pairs(path: Optional[Path] = None) -> list[tuple[str, str]]:
    src = path if path is not None else _zh_names_path()
    if not src.is_file():
        return []
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    table = data.get("itemNameToZh")
    if not isinstance(table, dict):
        table = {
            key: value
            for key, value in data.items()
            if isinstance(value, str)
        }
    pairs: list[tuple[str, str]] = []
    for key, value in table.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        kr = key.strip()
        zh = value.strip()
        if not kr or not zh or "/" in kr or "\\" in kr:
            continue
        pairs.append((kr, zh))
    return pairs


def _merge_names(groups: list[set[str]]) -> list[set[str]]:
    """Fold names and join groups that share one (아데나 / 金幣 / adena)."""
    merged: list[set[str]] = []
    for group in groups:
        folded = {_fold(name) for name in group if _fold(name)}
        if not folded:
            continue
        joined = folded
        keep: list[set[str]] = []
        for existing in merged:
            if existing & joined:
                joined |= existing
            else:
                keep.append(existing)
        keep.append(joined)
        merged = keep
    return merged


def configure_ground_loot(
    mode: str | None = None,
    names: list[str] | None = None,
    *,
    zh_path: Optional[Path] = None,
) -> None:
    """Install the pickup filter. Empty names + ``all`` is the default."""
    global _mode, _wanted, _alias_of
    cleaned = str(mode or _MODE_ALL).strip().lower()
    _mode = cleaned if cleaned in _MODES else _MODE_ALL
    _alias_of = {}
    groups: list[set[str]] = [set(group) for group in _GROUPS]
    for kr, zh in _load_icon_pairs(zh_path):
        groups.append({kr, zh})
    try:
        from app._03_world.game_catalog import list_item_rows

        for row in list_item_rows():
            groups.append(set(row.aliases()))
    except Exception:
        pass
    _wanted = set()
    for folded in _merge_names(groups):
        canonical = sorted(folded)[0]
        for name in folded:
            _alias_of[name] = canonical
    for raw in names or []:
        key = _fold(raw)
        if not key:
            continue
        _wanted.add(_alias_of.get(key, key))


def ground_loot_mode() -> str:
    return _mode


def _object_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    for attr in ("species_name", "detail_classification", "label"):
        key = _fold(getattr(obj, attr, "") or "")
        if key:
            keys.add(_alias_of.get(key, key))
    identity = getattr(obj, "identity", None)
    if identity is not None:
        key = _fold(getattr(identity, "name", "") or "")
        if key:
            keys.add(_alias_of.get(key, key))
    return keys


def ground_item_allowed(obj: Any) -> bool:
    """True when this ground item should be picked up."""
    if _mode == _MODE_ALL or not _wanted:
        if _mode == _MODE_WHITELIST:
            return False
        return True
    hit = bool(_object_keys(obj) & _wanted)
    if _mode == _MODE_WHITELIST:
        return hit
    return not hit
