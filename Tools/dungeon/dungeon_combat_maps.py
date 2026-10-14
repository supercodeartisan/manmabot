"""Dungeon Combat map catalog: discover packs + EN/KO/ZH display names.

Used only by ``dungeon_combat_gui``. Does not change engine decision logic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

from settings.dungeon_assets import engine_maps_dir, load_pack_meta
from session.paths import VERSION1_ROOT
from i18n.strings import LANG_EN, LANG_KO, LANG_ZH, normalize_language

# Folder / pack exclusions agreed for the combat tool map list.
_EXCLUDED_DIR_NAMES = frozenset(
    {
        "dungeons",
        "_legacy_dungeons",
        "obstacle_tiles_raw",
    }
)
_EXCLUDED_PACK_PREFIXES = ("gerard_test", "unknown_99")
_EXCLUDED_PACK_NEEDLES = ("ship",)

_WORLD_NAV_MAPS = (
    VERSION1_ROOT
    / "Extra_data(temporary)"
    / "world_nav_ready"
    / "providers"
    / "00_maps.json"
)

# Longest-first EN phrase → Simplified Chinese (Lineage Classic style).
_ZH_PHRASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            ("Talking Island", "说话之岛"),
            ("Air Temple of Fairies", "妖精空中神殿"),
            ("Polluted Land of Blessing", "被污染的祝福之地"),
            ("Tower of Insolence", "傲慢之塔"),
            ("Underground Passageway", "地下通道"),
            ("Underground Path", "地下通道"),
            ("Iron Gate Guild", "铁门公会"),
            ("Lair of Antharas", "安塔瑞斯巢穴"),
            ("Lair of Fafurion", "法利昂巢穴"),
            ("Lair of Valakas", "巴拉卡斯巢穴"),
            ("Land of the Abandoned", "被遗弃之地"),
            ("Island of Dreams", "梦之岛"),
            ("Forgotten Island", "遗忘之岛"),
            ("Ice Crystal Cave", "冰晶洞穴"),
            ("Ice Queen", "冰之女王"),
            ("Elven Forest", "妖精森林"),
            ("Dragon Valley", "龙之谷"),
            ("Ivory Tower", "象牙塔"),
            ("Sanctuary of Eva", "伊娃圣所"),
            ("Kingdom of Eva", "伊娃王国"),
            ("Eva Kingdom", "伊娃王国"),
            ("Fallen Cave", "堕落洞穴"),
            ("Gunters House", "甘特之家"),
            ("Gunter's House", "甘特之家"),
            ("Mutant Ant", "变异蚂蚁"),
            ("Ant Caves", "蚂蚁洞穴"),
            ("Ant Cave", "蚂蚁洞穴"),
            ("Mage Quest", "法师任务"),
            ("Inner Castle", "城内"),
            ("Hardin", "哈丁"),
            ("Laboratory", "研究所"),
            ("Gludio", "古鲁丁"),
            ("Gludin", "古鲁丁"),
            ("Giran", "奇岩"),
            ("Heine", "海音"),
            ("Aden", "亚丁"),
            ("Oren", "欧瑞"),
            ("Kent", "肯特"),
            ("Windawood", "风木"),
            ("Thebes", "底比斯"),
            ("Desert", "沙漠"),
            ("Training", "修炼"),
            ("Underwater", "水下"),
            ("Darkelf", "黑暗精灵"),
            ("Dupelgenon", "杜佩尔杰农"),
            ("Nerupa", "聂鲁帕"),
            ("Sepia", "深渊"),
            ("Hell", "地狱"),
            ("Castle", "城"),
            ("Prison", "地监"),
            ("Dungeon", "地下城"),
            ("Cave", "洞穴"),
            ("Jim", "吉姆"),
        ),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
)


@dataclass(frozen=True)
class CombatMapEntry:
    """One selectable dungeon pack for the combat tool."""

    pack_id: str
    game_map_id: Optional[int]
    name_en: str
    name_ko: str
    name_zh: str

    def display(self, lang: str) -> str:
        code = normalize_language(lang)
        if code == LANG_KO:
            return self.name_ko
        if code == LANG_ZH:
            return self.name_zh
        return self.name_en

    def search_blob(self) -> str:
        parts = (
            self.pack_id,
            self.name_en,
            self.name_ko,
            self.name_zh,
            "" if self.game_map_id is None else str(self.game_map_id),
        )
        return " ".join(parts).casefold()

    def combo_label(self, lang: str) -> str:
        return f"{self.display(lang)}  ({self.pack_id})"


def _load_map_catalog() -> dict[int, dict]:
    path = _WORLD_NAV_MAPS
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, dict] = {}
    for row in doc.get("maps") or []:
        try:
            mid = int(row["mapId"])
        except (KeyError, TypeError, ValueError):
            continue
        out[mid] = row
    return out


def english_to_zh(english: str) -> str:
    """Best-effort Simplified Chinese label from the English catalog name."""
    text = str(english or "").strip()
    if not text:
        return ""
    # "Floor 1" / "1F" / "F1" → "1层"
    text = re.sub(r"(?i)\s*Floor\s+(\d+)\s*", r"\1层", text)
    text = re.sub(r"(?i)\b(\d+)\s*F\b", r"\1层", text)
    text = re.sub(r"(?i)\bF(\d+)\b", r"\1层", text)
    for eng, zh in _ZH_PHRASES:
        text = text.replace(eng, zh)
    text = re.sub(r"\s+", "", text)
    text = text.replace("'s", "").replace("'", "")
    return text or english


def _pack_excluded(pack_id: str) -> bool:
    low = pack_id.casefold()
    if pack_id in _EXCLUDED_DIR_NAMES:
        return True
    if any(low.startswith(p) for p in _EXCLUDED_PACK_PREFIXES):
        return True
    if any(n in low for n in _EXCLUDED_PACK_NEEDLES):
        return True
    if "dungeon" not in low:
        return True
    return False


def _title_from_pack(pack_id: str) -> str:
    return pack_id.replace("_", " ").strip().title()


def discover_combat_maps(
    maps_root: Path | None = None,
    catalog: dict[int, dict] | None = None,
) -> tuple[CombatMapEntry, ...]:
    """Load dungeon packs under ``Engine/data/maps`` (nav + meta required)."""
    root = Path(maps_root) if maps_root is not None else engine_maps_dir()
    cat = _load_map_catalog() if catalog is None else catalog
    rows: list[CombatMapEntry] = []
    if not root.is_dir():
        return tuple()

    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir() or _pack_excluded(child.name):
            continue
        nav = child / "nav.png"
        meta_path = child / "meta.yaml"
        if not nav.is_file() or not meta_path.is_file():
            continue
        meta = load_pack_meta(child.name) or {}
        raw = meta.get("raw_map")
        game_id: Optional[int]
        try:
            game_id = int(str(raw).strip()) if raw is not None and str(raw).strip() else None
        except (TypeError, ValueError):
            game_id = None
        cat_row = cat.get(game_id) if game_id is not None else None
        name_en = str(
            (cat_row or {}).get("en")
            or meta.get("name")
            or _title_from_pack(child.name)
        ).strip()
        name_ko = str((cat_row or {}).get("kr") or name_en).strip()
        name_zh = english_to_zh(name_en) or name_en
        rows.append(
            CombatMapEntry(
                pack_id=child.name,
                game_map_id=game_id,
                name_en=name_en,
                name_ko=name_ko,
                name_zh=name_zh,
            )
        )
    return tuple(rows)


def filter_combat_maps(
    maps: Iterable[CombatMapEntry],
    query: str,
) -> tuple[CombatMapEntry, ...]:
    """Match query against pack id and EN/KO/ZH names (any language)."""
    q = str(query or "").strip().casefold()
    if not q:
        return tuple(maps)
    return tuple(m for m in maps if q in m.search_blob())


def label_for_lang(lang: str) -> str:
    code = normalize_language(lang)
    if code == LANG_KO:
        return "한국어"
    if code == LANG_ZH:
        return "简体中文"
    return "English"
