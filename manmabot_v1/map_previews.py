"""Artwork files under the product ``images/`` folder."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from manmabot_v1.paths import app_root

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
# User folder is Fantasy_Maps; also accept the names people use when adding files.
MAP_PREVIEW_FOLDERS = ("Fantasy_Maps", "map_fantasy", "fantasy_maps")
# 1:1 art that replaces pack terrain in the UI (same pixel size as nav.png).
REAL_MAP_FOLDERS = ("real_maps", "Real_Maps")
CHARACTER_FOLDERS = ("Characters", "characters")
MONSTER_FOLDERS = ("Monsters", "monsters")
LOOT_ICON_FOLDERS = ("Adena_vs_All", "adena_vs_all")
LOOT_ICON_STEMS = {
    "all_items": ("everything", "all_items"),
    "adena_only": ("adena_only", "adena"),
}

_STEM_ID = re.compile(r"^(.*)_(\d+)$")


def _find_named_image(folders: tuple[str, ...], stem: str) -> Optional[Path]:
    name = str(stem or "").strip()
    if not name:
        return None
    images = app_root() / "images"
    if not images.is_dir():
        return None
    want = {f"{name}{ext}".lower() for ext in IMAGE_EXTS}
    for folder_name in folders:
        folder = images / folder_name
        if not folder.is_dir():
            continue
        for ext in IMAGE_EXTS:
            exact = folder / f"{name}{ext}"
            if exact.is_file():
                return exact
        try:
            for path in folder.iterdir():
                if path.is_file() and path.name.lower() in want:
                    return path
        except OSError:
            continue
    return None


def real_map_path(map_id: str) -> Optional[Path]:
    """``images/real_maps/<map_id>.png`` — same resolution as pack terrain."""
    return _find_named_image(REAL_MAP_FOLDERS, map_id)


def open_real_map_image(map_id: str):
    """RGB art map for UI canvases. None if the file is missing (never pack terrain)."""
    path = real_map_path(map_id)
    if path is None:
        return None
    from PIL import Image

    try:
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    except OSError:
        return None


def map_preview_path(map_id: str) -> Optional[Path]:
    """``images/Fantasy_Maps/<map_id>.png`` (or jpg/webp). Setup tab only."""
    return _find_named_image(MAP_PREVIEW_FOLDERS, map_id)


def brand_icon_path() -> Optional[Path]:
    """``images/icon.png`` (or ``icon.ico``) for the Version 1 window and header."""
    images = app_root() / "images"
    if not images.is_dir():
        return None
    for name in ("icon.png", "icon.ico"):
        path = images / name
        if path.is_file():
            return path
    return None


def character_portrait_path(character_id: str) -> Optional[Path]:
    """``images/Characters/<id>.png`` (Mage.png, Elf.png, …)."""
    return _find_named_image(CHARACTER_FOLDERS, character_id)


def loot_icon_path(loot_mode: str) -> Optional[Path]:
    """``images/Adena_vs_All/everything.png`` or ``adena_only.png``."""
    for stem in LOOT_ICON_STEMS.get(str(loot_mode or "").strip().lower(), ()):
        found = _find_named_image(LOOT_ICON_FOLDERS, stem)
        if found is not None:
            return found
    return None


def normalize_monster_name(name: str) -> str:
    """Collapse spaces so ``다크엘프`` matches ``다크 엘프``."""
    return re.sub(r"\s+", "", str(name or "")).strip().lower()


def _image_display_name(stem: str) -> tuple[str, int]:
    """``오크_0`` → (``오크``, 0). Missing id sorts last."""
    m = _STEM_ID.match(stem)
    if m:
        return m.group(1), int(m.group(2))
    return stem, 10**9


_monster_index: dict[str, Path] | None = None


def index_monster_images() -> dict[str, Path]:
    """Normalized Korean name → best file in ``images/Monsters`` (lowest id)."""
    global _monster_index
    if _monster_index is not None:
        return _monster_index
    best: dict[str, tuple[int, Path]] = {}
    images = app_root() / "images"
    for folder_name in MONSTER_FOLDERS:
        folder = images / folder_name
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            name, rank = _image_display_name(path.stem)
            key = normalize_monster_name(name)
            if not key:
                continue
            prev = best.get(key)
            if prev is None or rank < prev[0]:
                best[key] = (rank, path)
    _monster_index = {key: path for key, (_, path) in best.items()}
    return _monster_index


def monster_image_path(display_name: str) -> Optional[Path]:
    """``images/Monsters/<name>_<id>.png`` for a catalog display name."""
    key = normalize_monster_name(display_name)
    if not key:
        return None
    return index_monster_images().get(key)


def fitted_image(path: Path, max_w: int, max_h: int):
    """Open ``path`` and shrink to fit ``max_w`` x ``max_h`` (no upscale)."""
    from PIL import Image

    im = Image.open(path)
    im.load()
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    w, h = im.size
    scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    return im


def placeholder_thumb(size: int = 64):
    """Gray square used when a species has no monster image yet."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (size, size), (48, 48, 56, 255))
    draw = ImageDraw.Draw(canvas)
    inset = max(2, size // 16)
    draw.rectangle(
        [inset, inset, size - inset - 1, size - inset - 1],
        outline=(120, 120, 132, 255),
        width=max(1, size // 28),
    )
    return canvas


def monster_thumb(display_name: str, size: int = 64):
    """Square thumbnail for a species cell. Placeholder if no file."""
    from PIL import Image

    path = monster_image_path(display_name)
    if path is None:
        return placeholder_thumb(size)
    try:
        im = fitted_image(path, size, size)
    except OSError:
        return placeholder_thumb(size)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - im.size[0]) // 2
    y = (size - im.size[1]) // 2
    canvas.paste(im, (x, y), im)
    return canvas
