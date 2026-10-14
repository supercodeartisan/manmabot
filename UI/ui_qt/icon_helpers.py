"""PIL → QPixmap helpers for Hunt (40px) and Magic (28px) icons."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QPixmap

_HUNT_CELL = 32
_HUNT_PAD = 4
HUNT_ICON_SIZE = _HUNT_CELL + _HUNT_PAD * 2  # 40
MAGIC_ICON_SIZE = 28

_CACHE: dict[tuple[str, int, bool], QPixmap] = {}


def _fit_icon(image, size: int):
    from PIL import Image

    bounds = image.getbbox()
    if bounds:
        image = image.crop(bounds)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, size - _HUNT_PAD * 2)
    if image.width < 1 or image.height < 1:
        return canvas
    scale = min(inner / image.width, inner / image.height)
    width = min(inner, max(1, int(round(image.width * scale))))
    height = min(inner, max(1, int(round(image.height * scale))))
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    canvas.paste(
        image,
        ((size - image.width) // 2, (size - image.height) // 2),
        image,
    )
    return canvas


def _pil_to_qpixmap(image) -> QPixmap:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(
        data,
        image.width,
        image.height,
        image.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    # Copy so QImage owns its buffer after PIL buffer may free.
    return QPixmap.fromImage(qimage.copy())


def hunt_icon(path: Path | str | None, *, enabled: bool = True, size: int = HUNT_ICON_SIZE) -> QPixmap:
    key_path = str(path or "")
    cache_key = (key_path, int(size), bool(enabled))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    from PIL import Image, ImageEnhance
    from settings.map_previews import placeholder_thumb

    image = None
    file_path = Path(path) if path else None
    if file_path is not None and file_path.is_file():
        try:
            image = Image.open(file_path)
            image.load()
        except OSError:
            image = None
    if image is None:
        image = placeholder_thumb(size)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    image = _fit_icon(image, size)
    if not enabled:
        gray = ImageEnhance.Color(image).enhance(0)
        faded = ImageEnhance.Brightness(gray).enhance(1.2)
        plate = Image.new("RGBA", image.size, (243, 244, 246, 255))
        image = Image.blend(faded, plate, 0.5)
    pixmap = _pil_to_qpixmap(image)
    _CACHE[cache_key] = pixmap
    return pixmap


def magic_icon(path: Path | str | None, *, size: int = MAGIC_ICON_SIZE) -> QPixmap:
    key_path = str(path or "")
    cache_key = (key_path, int(size), True)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    from PIL import Image

    file_path = Path(path) if path else None
    if file_path is not None and file_path.is_file():
        try:
            image = Image.open(file_path).convert("RGBA")
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            pixmap = _pil_to_qpixmap(image)
            _CACHE[cache_key] = pixmap
            return pixmap
        except OSError:
            pass
    image = Image.new("RGBA", (size, size), (219, 234, 254, 255))
    pixmap = _pil_to_qpixmap(image)
    _CACHE[cache_key] = pixmap
    return pixmap
