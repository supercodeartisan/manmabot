"""Official Korean / Chinese monster and item lists from analysis/list."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app._03_world.zh_convert import chinese_aliases, to_simplified

_LIST_ROOT = Path(__file__).resolve().parents[2] / "analysis" / "list"
_ANALYSIS_ROOT = Path(__file__).resolve().parents[2] / "analysis"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_STEM_ID = re.compile(r"^(.*)_(\d+)$")
_MONSTER_IMAGE_FOLDERS = ("monsters", "monster", "몬스터")
_ITEM_IMAGE_FOLDERS = ("item", "items", "아이템")


def _fold(text: str) -> str:
    return "".join(str(text or "").split()).lower()


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


def _by_id(rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            key = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        out[key] = row
    return out


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def _unique_ids(values: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    for raw in values:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        seen.add(sid)
    return tuple(sorted(seen))


def _file_name_key(name: str) -> str:
    """``얼음 여왕`` → ``얼음_여왕`` as used by the official PNG stems."""
    return re.sub(r"\s+", "_", str(name or "").strip())


def _compact_name(name: str) -> str:
    return re.sub(r"[\s_]+", "", str(name or "")).strip().lower()


def _image_roots(kind: str) -> tuple[Path, ...]:
    folders = _MONSTER_IMAGE_FOLDERS if kind == "monster" else _ITEM_IMAGE_FOLDERS
    bases = (
        _ANALYSIS_ROOT / "list" / "image",
        _ANALYSIS_ROOT / "image",
    )
    return tuple(base / folder for base in bases for folder in folders)


@lru_cache(maxsize=2)
def _image_indexes(kind: str) -> tuple[dict[tuple[str, int], Path], dict[str, Path]]:
    """``(filename_name, id)`` and lowest-id-by-name indexes."""
    by_id: dict[tuple[str, int], Path] = {}
    best: dict[str, tuple[int, Path]] = {}
    for folder in _image_roots(kind):
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
                continue
            match = _STEM_ID.match(path.stem)
            if match:
                stem_name, sid = match.group(1), int(match.group(2))
            else:
                stem_name, sid = path.stem, 10**9
            keys = {_file_name_key(stem_name), _compact_name(stem_name)}
            for key in keys:
                if not key:
                    continue
                if sid < 10**9:
                    by_id[(key, sid)] = path
                prev = best.get(key)
                if prev is None or sid < prev[0]:
                    best[key] = (sid, path)
    return by_id, {key: path for key, (_sid, path) in best.items()}


def resolve_catalog_image(
    kind: str,
    names: Iterable[str],
    ids: Iterable[int] = (),
) -> Path | None:
    """Match ``{name with spaces as _}_{id}.png`` then the lowest-id name file."""
    by_id, by_name = _image_indexes("monster" if kind == "monster" else "item")
    name_keys: list[str] = []
    for raw in names:
        text = str(raw or "").strip()
        if not text:
            continue
        for key in (_file_name_key(text), _compact_name(text)):
            if key and key not in name_keys:
                name_keys.append(key)
    for key in name_keys:
        for sid in _unique_ids(ids):
            found = by_id.get((key, sid))
            if found is not None:
                return found
    for key in name_keys:
        found = by_name.get(key)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class MonsterCatalogRow:
    key: str
    name_ko: str
    name_zh: str
    name_zh_cn: str
    level: int
    regions_ko: tuple[str, ...]
    regions_zh: tuple[str, ...]
    regions_zh_cn: tuple[str, ...]
    ids: tuple[int, ...] = ()

    def display_name(self, language: str | None) -> str:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.name_zh_cn or self.name_zh or self.name_ko
        if lang.startswith("ko"):
            return self.name_ko
        return self.name_ko

    def display_regions(self, language: str | None) -> tuple[str, ...]:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.regions_zh_cn or self.regions_zh or self.regions_ko
        return self.regions_ko

    def region_text(self, language: str | None) -> str:
        return ", ".join(self.display_regions(language))

    def search_names(self) -> tuple[str, ...]:
        """JSON ``name`` fields used to match memory entities (고블린, not monster_고블린)."""
        names = [self.name_ko, self.name_zh, self.name_zh_cn]
        names.extend(chinese_aliases(self.name_zh))
        names.extend(chinese_aliases(self.name_zh_cn))
        return _unique(names)

    def aliases(self) -> tuple[str, ...]:
        return _unique([self.key, *self.search_names()])

    def image_path(self) -> Path | None:
        return resolve_catalog_image(
            "monster",
            (self.name_ko, self.name_zh, self.name_zh_cn),
            self.ids,
        )


@dataclass(frozen=True)
class ItemCatalogRow:
    key: str
    name_ko: str
    name_zh: str
    name_zh_cn: str
    category_ko: str
    category_zh: str
    category_zh_cn: str
    ids: tuple[int, ...] = ()

    def display_name(self, language: str | None) -> str:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.name_zh_cn or self.name_zh or self.name_ko
        if lang.startswith("ko"):
            return self.name_ko
        return self.name_ko

    def display_category(self, language: str | None) -> str:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.category_zh_cn or self.category_zh or self.category_ko
        return self.category_ko

    def search_names(self) -> tuple[str, ...]:
        """JSON ``name`` fields used to match memory entities (아데나, 金幣)."""
        names = [self.name_ko, self.name_zh, self.name_zh_cn]
        names.extend(chinese_aliases(self.name_zh))
        names.extend(chinese_aliases(self.name_zh_cn))
        return _unique(names)

    def aliases(self) -> tuple[str, ...]:
        return _unique([self.key, *self.search_names()])

    def image_path(self) -> Path | None:
        return resolve_catalog_image(
            "item",
            (self.name_ko, self.name_zh, self.name_zh_cn),
            self.ids,
        )


def _monster_key(name_ko: str) -> str:
    return f"monster_{name_ko.strip()}"


@lru_cache(maxsize=1)
def list_monster_rows() -> tuple[MonsterCatalogRow, ...]:
    korean = _by_id(_read_contents(_LIST_ROOT / "korean" / "monster.json"))
    chinese = _by_id(_read_contents(_LIST_ROOT / "chinese" / "monster.json"))
    merged: dict[str, MonsterCatalogRow] = {}
    for sid, ko in korean.items():
        name_ko = str(ko.get("name") or "").strip()
        if not name_ko:
            continue
        zh = chinese.get(sid) or {}
        name_zh = str(zh.get("name") or "").strip()
        name_cn = to_simplified(name_zh) if name_zh else ""
        try:
            level = int(ko.get("level") or zh.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        regions_ko = _unique(ko.get("regionNames") or [])
        regions_zh = _unique(zh.get("regionNames") or [])
        regions_cn = _unique(to_simplified(name) for name in regions_zh)
        key = _monster_key(name_ko)
        previous = merged.get(key)
        if previous is None:
            merged[key] = MonsterCatalogRow(
                key=key,
                name_ko=name_ko,
                name_zh=name_zh,
                name_zh_cn=name_cn,
                level=max(1, level),
                regions_ko=regions_ko,
                regions_zh=regions_zh,
                regions_zh_cn=regions_cn,
                ids=(sid,),
            )
            continue
        merged[key] = MonsterCatalogRow(
            key=previous.key,
            name_ko=previous.name_ko,
            name_zh=previous.name_zh or name_zh,
            name_zh_cn=previous.name_zh_cn or name_cn,
            level=previous.level or max(1, level),
            regions_ko=_unique([*previous.regions_ko, *regions_ko]),
            regions_zh=_unique([*previous.regions_zh, *regions_zh]),
            regions_zh_cn=_unique([*previous.regions_zh_cn, *regions_cn]),
            ids=_unique_ids([*previous.ids, sid]),
        )
    return tuple(sorted(merged.values(), key=lambda row: (row.level, row.name_ko)))


@lru_cache(maxsize=1)
def list_item_rows() -> tuple[ItemCatalogRow, ...]:
    korean = _by_id(_read_contents(_LIST_ROOT / "korean" / "item.json"))
    chinese = _by_id(_read_contents(_LIST_ROOT / "chinese" / "item.json"))
    merged: dict[str, ItemCatalogRow] = {}
    for sid, ko in korean.items():
        name_ko = str(ko.get("name") or "").strip()
        if not name_ko:
            continue
        zh = chinese.get(sid) or {}
        name_zh = str(zh.get("name") or "").strip()
        cat_ko = str(ko.get("categoryName") or "").strip()
        cat_zh = str(zh.get("categoryName") or "").strip()
        previous = merged.get(name_ko)
        row = ItemCatalogRow(
            key=name_ko,
            name_ko=name_ko,
            name_zh=name_zh or (previous.name_zh if previous else ""),
            name_zh_cn=(
                to_simplified(name_zh) if name_zh
                else (previous.name_zh_cn if previous else "")
            ),
            category_ko=cat_ko or (previous.category_ko if previous else ""),
            category_zh=cat_zh or (previous.category_zh if previous else ""),
            category_zh_cn=(
                to_simplified(cat_zh) if cat_zh
                else (previous.category_zh_cn if previous else cat_ko)
            ),
            ids=_unique_ids([*(previous.ids if previous else ()), sid]),
        )
        merged[name_ko] = row
    return tuple(sorted(merged.values(), key=lambda row: (row.category_ko, row.name_ko)))


def _strip_monster_prefix(text: str) -> str:
    """``monster_고블린`` / ``monster_고블린_2`` → ``고블린`` for name search."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    folded = raw.lower()
    if folded.startswith("monster_") and "-" not in raw[len("monster_") :]:
        raw = raw[len("monster_") :]
    parts = raw.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        raw = "_".join(parts[:-1])
    return raw.strip()


def _index_names(names: Iterable[str], key: str, index: dict[str, str]) -> None:
    for alias in names:
        text = str(alias or "").strip()
        if not text:
            continue
        index[text] = key
        index[text.lower()] = key
        index[_fold(text)] = key


@lru_cache(maxsize=1)
def monster_alias_index() -> dict[str, str]:
    """Memory/UI names → catalog id. Search keys are JSON ``name`` only."""
    index: dict[str, str] = {}
    for row in list_monster_rows():
        _index_names(row.search_names(), row.key, index)
    return index


@lru_cache(maxsize=1)
def item_alias_index() -> dict[str, str]:
    """Memory/UI names → Korean item name. Search keys are JSON ``name`` only."""
    index: dict[str, str] = {}
    for row in list_item_rows():
        _index_names(row.search_names(), row.key, index)
    return index


def monster_by_key(key: str) -> MonsterCatalogRow | None:
    catalog = resolve_monster_key(key)
    if not catalog:
        return None
    for row in list_monster_rows():
        if row.key == catalog:
            return row
    return None


def item_by_key(key: str) -> ItemCatalogRow | None:
    catalog = resolve_item_key(key)
    if not catalog:
        return None
    for row in list_item_rows():
        if row.key == catalog:
            return row
    return None


def _index_get(index: dict[str, str], text: str) -> str | None:
    if not text:
        return None
    return index.get(text) or index.get(text.lower()) or index.get(_fold(text))


def resolve_monster_key(display: str) -> str | None:
    """Match a memory name like ``고블린`` / ``哥布林`` to the catalog row.

    Incoming ``monster_고블린`` is stripped to ``고블린`` before search.
    """
    text = str(display or "").strip()
    if not text:
        return None
    index = monster_alias_index()
    queries = [text, _strip_monster_prefix(text)]
    queries.extend(chinese_aliases(text))
    queries.extend(chinese_aliases(_strip_monster_prefix(text)))
    seen: set[str] = set()
    for query in queries:
        if not query or query in seen:
            continue
        seen.add(query)
        found = _index_get(index, query)
        if found:
            return found
    return None


def resolve_item_key(display: str) -> str | None:
    """Match a memory name like ``아데나`` / ``金幣`` to the Korean item name."""
    text = str(display or "").strip()
    if not text:
        return None
    index = item_alias_index()
    queries = [text, *chinese_aliases(text)]
    seen: set[str] = set()
    for query in queries:
        if not query or query in seen:
            continue
        seen.add(query)
        found = _index_get(index, query)
        if found:
            return found
    return None


def monster_region_labels(language: str | None) -> tuple[str, ...]:
    labels: list[str] = []
    for row in list_monster_rows():
        for name in row.display_regions(language):
            if name not in labels:
                labels.append(name)
    return tuple(sorted(labels))


def item_category_labels(language: str | None) -> tuple[str, ...]:
    labels: list[str] = []
    for row in list_item_rows():
        name = row.display_category(language)
        if name and name not in labels:
            labels.append(name)
    return tuple(sorted(labels))


_HP_AMOUNT = re.compile(r"회복량")
_HP_CONSUME = re.compile(r"(마시면|먹으면).{0,20}체력")
# Memory inventory uses 80 for 체력 회복제 (same stack as catalog id 14).
_HP_EXTRA_IDS = {14: (80,)}
_HP_PREFERRED = ("빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매")


@dataclass(frozen=True)
class HpRestoreItem:
    """Consumable that restores HP (official item.json 회복량 / drink-eat text)."""

    key: str
    name_ko: str
    name2: str
    name_zh: str
    name_zh_cn: str
    ids: tuple[int, ...]
    heal_text: str = ""

    def action_id(self) -> str:
        return f"item:{self.key}"

    def display_name(self, language: str | None) -> str:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.name_zh_cn or self.name_zh or self.name_ko
        return self.name_ko

    def aliases(self) -> tuple[str, ...]:
        names = [self.key, self.name_ko, self.name2, self.name_zh, self.name_zh_cn]
        names.extend(chinese_aliases(self.name_zh))
        names.extend(chinese_aliases(self.name_zh_cn))
        return _unique(names)


@lru_cache(maxsize=1)
def list_hp_restore_items() -> tuple[HpRestoreItem, ...]:
    """Potions and foods that restore HP. Gear with passive regen is excluded."""
    korean = _by_id(_read_contents(_LIST_ROOT / "korean" / "item.json"))
    chinese = _by_id(_read_contents(_LIST_ROOT / "chinese" / "item.json"))
    merged: dict[str, HpRestoreItem] = {}
    for sid, ko in korean.items():
        options = ko.get("options") or []
        desc = str(ko.get("description") or "")
        if isinstance(options, list):
            opt_text = " ".join(str(part) for part in options)
        else:
            opt_text = str(options)
        if not (_HP_AMOUNT.search(opt_text) or _HP_CONSUME.search(desc)):
            continue
        name_ko = str(ko.get("name") or "").strip()
        if not name_ko:
            continue
        zh = chinese.get(sid) or {}
        name_zh = str(zh.get("name") or "").strip()
        previous = merged.get(name_ko)
        extra = _HP_EXTRA_IDS.get(sid, ())
        merged[name_ko] = HpRestoreItem(
            key=name_ko,
            name_ko=name_ko,
            name2=str(ko.get("name2") or (previous.name2 if previous else "")).strip(),
            name_zh=name_zh or (previous.name_zh if previous else ""),
            name_zh_cn=(
                to_simplified(name_zh) if name_zh
                else (previous.name_zh_cn if previous else "")
            ),
            ids=_unique_ids([*(previous.ids if previous else ()), sid, *extra]),
            heal_text=opt_text.strip() or (previous.heal_text if previous else ""),
        )
    preferred = [merged[key] for key in _HP_PREFERRED if key in merged]
    rest = sorted(
        (row for key, row in merged.items() if key not in _HP_PREFERRED),
        key=lambda row: row.name_ko,
    )
    return tuple(preferred + rest)


def hp_restore_item(key: str) -> HpRestoreItem | None:
    text = str(key or "").strip()
    if text.startswith("item:"):
        text = text[5:]
    if text == "hp_potion":
        text = "빨간 물약"
    for row in list_hp_restore_items():
        if row.key == text or text in row.aliases() or text in {str(sid) for sid in row.ids}:
            return row
        folded = {_fold(alias) for alias in row.aliases()}
        if _fold(text) in folded:
            return row
    return None
