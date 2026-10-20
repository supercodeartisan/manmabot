"""Spell MP costs from data/catalog/list spell.json (name → consumables.mp)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_LIST_ROOT = Path(__file__).resolve().parents[1] / "data" / "catalog" / "list"
_SPACE = re.compile(r"\s+")

# When the live hotbar name is missing, resolve cost via these catalog names.
_ROLE_FALLBACK_NAMES: dict[str, tuple[str, ...]] = {
    "heal": ("힐", "初級治癒術", "初级治愈术"),
    "teleport": ("텔레포트", "傳送術", "传送术"),
    "mother_tree": ("텔레포트 투 마더", "世界樹的呼喚", "世界树的呼唤"),
    "light": ("라이트", "日光術", "日光术"),
    "hp_to_mp": ("바디 투 마인드", "體能激發", "体能激发"),
    "armor_up": ("실드", "防護罩", "防护罩"),
    "power_up": ("홀리 웨폰", "神聖武器", "神圣武器"),
}


def _fold_key(text: str) -> str:
    return _SPACE.sub("", str(text or "").strip()).lower()


def _read_contents(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("contents") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@lru_cache(maxsize=1)
def _mp_by_name() -> dict[str, int]:
    """Folded name → MP cost from Korean + Chinese spell catalogs."""
    out: dict[str, int] = {}
    for lang in ("korean", "chinese"):
        for row in _read_contents(_LIST_ROOT / lang / "spell.json"):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            cons = row.get("consumables")
            if not isinstance(cons, dict):
                continue
            try:
                mp = int(cons.get("mp") or 0)
            except (TypeError, ValueError):
                continue
            if mp < 0:
                continue
            key = _fold_key(name)
            # Prefer first (Korean) when both define the same key.
            out.setdefault(key, mp)
    return out


def mp_cost_by_spell_name(name: str) -> Optional[int]:
    """Catalog MP for a bare spell name, or None if unknown."""
    key = _fold_key(name)
    if not key:
        return None
    table = _mp_by_name()
    if key in table:
        return int(table[key])
    return None


def mp_cost_for_role_fallback(role: str) -> Optional[int]:
    """Catalog MP via known names for a bot role (no live hotbar)."""
    for name in _ROLE_FALLBACK_NAMES.get(str(role or "").strip(), ()):
        cost = mp_cost_by_spell_name(name)
        if cost is not None:
            return cost
    return None


def clear_spell_mana_cache() -> None:
    """Tests: drop the cached catalog table."""
    _mp_by_name.cache_clear()
