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
    # Engine/hotbar/icons_unique (not the deprecated Engine/manmabot_v1 shim).
    return (
        Path(__file__).resolve().parents[2]
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
        from app._03_world.catalog.game_catalog import list_item_rows

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


# Main-intent loot: FREE piles, or my damage share strictly above this.
LOOT_CONTRIB_MIN = 50


def loot_ownership_allowed(obj: Any) -> bool:
    """True when drop claim allows a main-intent loot approach/pickup.

    Policy (extra_ent): ``own == FREE`` or ``contrib > LOOT_CONTRIB_MIN``.
    Missing claim fields (tests / old snapshots) stay allowed. Side-intent
    F4 bypasses this via ``list_lootable(..., ownership_filter=False)``.
    """
    own = getattr(obj, "loot_own", None)
    contrib = getattr(obj, "loot_contrib", None)
    if own is None and contrib is None:
        return True
    if str(own or "").strip().upper() == "FREE":
        return True
    try:
        if contrib is not None and int(contrib) > LOOT_CONTRIB_MIN:
            return True
    except (TypeError, ValueError):
        pass
    return False


def format_loot_claim(obj: Any) -> str:
    """Claim fields at the moment a pile is chosen, for the loot log.

    Missing ``own`` / ``contrib`` / ``guid`` are ``-``. ``allowed`` is the
    main-intent gate (``loot_ownership_allowed``), even when the caller
    skips that gate.
    """
    if obj is None:
        return "name=- guid=- own=- contrib=- allowed=- cell=- rel=-"
    name = str(
        getattr(obj, "species_name", None)
        or getattr(obj, "label", None)
        or getattr(getattr(obj, "identity", None), "name", None)
        or "-"
    ).strip() or "-"
    guid = str(getattr(obj, "memory_guid", None) or "").strip() or "-"
    own_raw = getattr(obj, "loot_own", None)
    own = str(own_raw).strip() if own_raw not in (None, "") else "-"
    contrib_raw = getattr(obj, "loot_contrib", None)
    try:
        contrib = str(int(contrib_raw)) if contrib_raw is not None else "-"
    except (TypeError, ValueError):
        contrib = "-"
    allowed = "1" if loot_ownership_allowed(obj) else "0"
    cx = getattr(obj, "world_cx", None)
    cy = getattr(obj, "world_cy", None)
    cell = f"({int(cx)},{int(cy)})" if cx is not None and cy is not None else "-"
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    rel = f"({int(rx)},{int(ry)})" if rx is not None and ry is not None else "-"
    return (
        f"name={name} guid={guid} own={own} contrib={contrib} "
        f"allowed={allowed} cell={cell} rel={rel}"
    )


__all__ = [
    "configure_ground_loot",
    "format_loot_claim",
    "ground_item_allowed",
    "ground_loot_mode",
    "loot_ownership_allowed",
    "LOOT_CONTRIB_MIN",
]
