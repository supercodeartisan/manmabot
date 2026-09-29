"""Item icon template packs: hotbar ``icons_unique`` and shop-sell ``shopping_slots``.

Hotbar detection keeps using ``icons_unique``. Shopping Practice sell matching and
slot-crop saves use ``manmabot_v1/shopping_slots`` (same ``items/<category>/<name>.png``).
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

PackName = Literal["hotbar", "sell"]


@dataclass(frozen=True)
class ItemTemplateEntry:
    """One inventory item icon from a template pack."""

    kr_name: str
    category: str
    template: str  # path relative to pack root, forward slashes
    zh_name: str = ""


def hotbar_dir() -> Path:
    return Path(__file__).resolve().parent


def manmabot_v1_dir() -> Path:
    return hotbar_dir().parent


def icons_unique_root() -> Path:
    return hotbar_dir() / "icons_unique"


def shopping_slots_root() -> Path:
    """Shop-sell slot templates under ``manmabot_v1/shopping_slots``."""
    return manmabot_v1_dir() / "shopping_slots"


def icons_sell_root() -> Path:
    """Alias for ``shopping_slots_root`` (legacy name)."""
    return shopping_slots_root()


def pack_root(pack: PackName = "hotbar") -> Path:
    return shopping_slots_root() if pack == "sell" else icons_unique_root()


def items_root(pack: PackName = "hotbar") -> Path:
    return pack_root(pack) / "items"


def _migrate_legacy_icons_sell() -> None:
    """Move leftover ``hotbar/icons_sell`` into ``shopping_slots`` once, if needed."""
    legacy = hotbar_dir() / "icons_sell"
    dest = shopping_slots_root()
    if not legacy.is_dir():
        return
    if dest.is_dir():
        # Destination already exists — drop empty legacy scaffold only.
        try:
            has_png = any(legacy.rglob("*.png"))
        except OSError:
            has_png = True
        if not has_png:
            shutil.rmtree(legacy, ignore_errors=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(dest))


SELL_CATEGORIES: tuple[str, ...] = (
    "weapon",
    "armor",
    "supply",
    "book",
    "other",
)

# Old Korean hotbar folder names → one of SELL_CATEGORIES (for one-time migrate).
_LEGACY_SELL_CATEGORY_MAP: dict[str, str] = {
    "한손검": "weapon",
    "양손검": "weapon",
    "둔기": "weapon",
    "창": "weapon",
    "지팡이": "weapon",
    "화살": "weapon",
    "갑옷": "armor",
    "투구": "armor",
    "티셔츠": "armor",
    "망토": "armor",
    "장갑": "armor",
    "부츠": "armor",
    "방패": "armor",
    "벨트": "armor",
    "목걸이": "armor",
    "반지": "armor",
    "물약": "supply",
    "주문서": "supply",
    "마법서": "book",
    "기타": "other",
}


def ensure_sell_pack_scaffold() -> Path:
    """Create ``shopping_slots/items/{weapon,armor,supply,book,other}/``."""
    _migrate_legacy_icons_sell()
    sell = shopping_slots_root()
    items = sell / "items"
    items.mkdir(parents=True, exist_ok=True)
    for cat in SELL_CATEGORIES:
        (items / cat).mkdir(parents=True, exist_ok=True)
    _migrate_legacy_sell_categories(items)
    readme = sell / "README.txt"
    readme.write_text(
        "Shop-sell icon templates for Shopping Practice slot matching.\n"
        "Layout: shopping_slots/items/<category>/<name>.png\n"
        "Categories (only these five):\n"
        "  weapon  armor  supply  book  other\n"
        "Hotbar detection continues to use icons_unique/ — do not put sell\n"
        "crops there. Fill this pack via Sell → Slot positions → Save slot crop.\n",
        encoding="utf-8",
    )
    return sell


def _migrate_legacy_sell_categories(items: Path) -> None:
    """Move PNGs out of old Korean category folders into the five sell categories."""
    if not items.is_dir():
        return
    for folder in list(items.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if folder.name in SELL_CATEGORIES:
            continue
        target_cat = _LEGACY_SELL_CATEGORY_MAP.get(folder.name, "other")
        dest_dir = items / target_cat
        dest_dir.mkdir(parents=True, exist_ok=True)
        for png in list(folder.glob("*.png")):
            dest = dest_dir / png.name
            if dest.exists():
                # Keep existing; drop duplicate from legacy folder.
                png.unlink(missing_ok=True)
                continue
            png.rename(dest)
        # Remove empty leftover folder (ignore if non-empty / locked).
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass


@lru_cache(maxsize=1)
def _zh_item_names() -> dict[str, str]:
    path = icons_unique_root() / "zh_names.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = data.get("itemNameToZh") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for kr, zh in raw.items():
        name = str(kr or "").strip()
        if name:
            out[name] = str(zh or "").strip()
    return out


def list_item_templates(
    *,
    pack: PackName = "hotbar",
    root: Optional[Path] = None,
) -> list[ItemTemplateEntry]:
    """Walk ``<pack>/items/**/*.png`` → unique KR names (sorted by category, name)."""
    if root is not None:
        base = root
        pack_base = root.parent if root.name == "items" else root
    else:
        if pack == "sell":
            ensure_sell_pack_scaffold()
        base = items_root(pack)
        pack_base = pack_root(pack)
    if not base.is_dir():
        return []
    zh_map = _zh_item_names()
    by_name: dict[str, ItemTemplateEntry] = {}
    for png in sorted(base.rglob("*.png")):
        if not png.is_file():
            continue
        try:
            rel = png.relative_to(pack_base)
        except ValueError:
            try:
                rel = png.relative_to(base)
            except ValueError:
                continue
        parts = rel.as_posix().split("/")
        if parts and parts[0] == "items" and len(parts) >= 3:
            category = parts[1]
            template = "/".join(parts)
        elif len(parts) >= 2:
            category = parts[0]
            template = f"items/{'/'.join(parts)}"
        else:
            category = ""
            template = rel.as_posix()
        kr_name = png.stem.strip()
        if not kr_name:
            continue
        if kr_name in by_name:
            continue
        by_name[kr_name] = ItemTemplateEntry(
            kr_name=kr_name,
            category=category,
            template=template,
            zh_name=zh_map.get(kr_name, ""),
        )
    return sorted(
        by_name.values(),
        key=lambda e: (e.category.lower(), e.kr_name.lower()),
    )


def item_display_name(entry: ItemTemplateEntry, language: str | None) -> str:
    """Console language label from the UI language tables."""
    from manmabot_v1.localized_names import item_catalog_display_name

    shown = item_catalog_display_name(entry.kr_name, language)
    if shown:
        return shown
    lang = (language or "en").split("-")[0].lower()
    if lang == "zh" and entry.zh_name:
        return entry.zh_name
    return entry.kr_name


def list_item_categories(*, pack: PackName = "hotbar") -> list[str]:
    """Category folder names under items/."""
    if pack == "sell":
        ensure_sell_pack_scaffold()
        return list(SELL_CATEGORIES)
    seen: list[str] = []
    base = items_root(pack)
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if p.is_dir() and not p.name.startswith(".") and p.name not in seen:
                seen.append(p.name)
    for entry in list_item_templates(pack=pack):
        if entry.category and entry.category not in seen:
            seen.append(entry.category)
    return seen


def new_item_template_rel(category: str, kr_name: str, *, pack: PackName = "hotbar") -> str:
    """Relative path ``items/<category>/<name>.png`` for a new template."""
    cat = str(category or "").strip().strip("/\\")
    if not cat or cat in (".", "..") or "/" in cat or "\\" in cat:
        raise ValueError("category must be a single folder name under items/")
    if pack == "sell" and cat not in SELL_CATEGORIES:
        raise ValueError(
            f"sell category must be one of: {', '.join(SELL_CATEGORIES)}"
        )
    stem = _safe_item_stem(kr_name)
    return f"items/{cat}/{stem}.png"


def template_abs_path(template_rel: str, *, pack: PackName = "hotbar") -> Path:
    """``items/…/name.png`` → absolute path under the pack root."""
    if pack == "sell":
        ensure_sell_pack_scaffold()
    rel = str(template_rel or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("empty template path")
    return pack_root(pack) / Path(*rel.split("/"))


def find_template_path_by_kr_name(
    kr_name: str, *, pack: PackName = "hotbar"
) -> Optional[Path]:
    """Resolve KR display name → on-disk PNG path (first catalog hit)."""
    want = str(kr_name or "").strip()
    if not want:
        return None
    for entry in list_item_templates(pack=pack):
        if entry.kr_name == want:
            path = template_abs_path(entry.template, pack=pack)
            return path if path.is_file() else None
    return None


def write_png_unicode(path: Path, image) -> None:
    """Write BGR/BGRA via imencode (Windows-safe for non-ASCII paths)."""
    import cv2
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.ascontiguousarray(image)
    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        raise RuntimeError(f"cv2.imencode failed for {path}")
    buf.tofile(os.fspath(path))


def backup_template_png(src: Path, *, pack: PackName = "hotbar") -> Path:
    """Copy existing template aside under ``<pack>/_replaced_backup/``."""
    import shutil
    from datetime import datetime

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)
    root = pack_root(pack)
    try:
        rel = src.relative_to(root)
    except ValueError:
        rel = Path(src.name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = root / "_replaced_backup" / stamp / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def replace_template_with_bgr_crop(
    template_rel_or_path: str | Path,
    bgr_crop,
    *,
    backup: bool = True,
    pack: PackName = "hotbar",
) -> Path:
    """Write a BGR crop as opaque BGRA PNG into the given pack (backup if exists)."""
    import cv2
    import numpy as np

    if isinstance(template_rel_or_path, Path):
        dest = template_rel_or_path
    else:
        text = str(template_rel_or_path).strip().replace("\\", "/")
        dest = (
            Path(text)
            if Path(text).is_file() or ":/" in text or text.startswith("/")
            else template_abs_path(text, pack=pack)
        )
    crop = np.ascontiguousarray(bgr_crop)
    if crop.ndim != 3 or crop.shape[2] < 3:
        raise ValueError("crop must be HxWx3+ BGR")
    if crop.shape[0] < 4 or crop.shape[1] < 4:
        raise ValueError("crop too small")
    bgr = crop[:, :, :3]
    alpha = np.full(bgr.shape[:2], 255, dtype=np.uint8)
    bgra = cv2.merge([bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2], alpha])
    if backup and dest.is_file():
        # Infer pack from path when possible.
        backup_pack = pack
        try:
            dest.relative_to(shopping_slots_root())
            backup_pack = "sell"
        except ValueError:
            try:
                dest.relative_to(icons_unique_root())
                backup_pack = "hotbar"
            except ValueError:
                pass
        backup_template_png(dest, pack=backup_pack)
    write_png_unicode(dest, bgra)
    return dest


def _safe_item_stem(kr_name: str) -> str:
    """KR item name usable as a PNG stem (no path separators)."""
    name = str(kr_name or "").strip()
    if not name:
        raise ValueError("item name is empty")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("item name must not contain path separators")
    return name


def make_sell_icon_matcher(*, threads=None, slot_layout=None):
    """``IconMatcher`` rooted at ``shopping_slots`` (empty pack allowed until crops exist)."""
    from manmabot_v1.hotbar.icon_matcher import IconMatcher

    ensure_sell_pack_scaffold()
    return IconMatcher(
        icon_root=str(shopping_slots_root()),
        threads=threads,
        slot_layout=slot_layout if slot_layout is not None else {},
        allow_empty=True,
    )


def save_new_item_template(
    category: str,
    kr_name: str,
    bgr_crop,
    *,
    overwrite: bool = False,
    pack: PackName = "sell",
) -> Path:
    """Write a new item PNG under ``<pack>/items/<category>/``.

    Defaults to the sell pack so Shopping Practice does not touch hotbar icons.
    Raises ``FileExistsError`` if the file already exists and ``overwrite`` is false.
    """
    if pack == "sell":
        ensure_sell_pack_scaffold()
    rel = new_item_template_rel(category, kr_name, pack=pack)
    dest = template_abs_path(rel, pack=pack)
    if dest.is_file() and not overwrite:
        raise FileExistsError(
            f"template already exists: {rel} — pick Replace, or choose another name"
        )
    return replace_template_with_bgr_crop(
        dest, bgr_crop, backup=dest.is_file(), pack=pack
    )
