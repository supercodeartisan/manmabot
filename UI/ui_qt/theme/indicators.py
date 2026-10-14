"""Classic-style checkbox / radio indicator PNGs for QSS."""

from __future__ import annotations

from pathlib import Path

from ui_qt.theme import tokens as t

_SIZE = 14
_DIR: Path | None = None


def indicator_dir() -> Path:
    global _DIR
    if _DIR is not None and _DIR.is_dir():
        return _DIR
    try:
        from session.paths import ensure_userdata, manmabot_root

        ensure_userdata()
        root = Path(manmabot_root()) / "UserData" / "cache" / "qt_indicators"
    except Exception:
        root = Path.home() / ".manmabot" / "qt_indicators"
    root.mkdir(parents=True, exist_ok=True)
    _DIR = root
    _write_all(root)
    return root


def qss_url(path: Path) -> str:
    return path.resolve().as_posix()


def _write_all(root: Path) -> None:
    specs = {
        "cb_off.png": _checkbox(False, False),
        "cb_on.png": _checkbox(True, False),
        "cb_off_dis.png": _checkbox(False, True),
        "cb_on_dis.png": _checkbox(True, True),
        "rb_off.png": _radio(False, False),
        "rb_on.png": _radio(True, False),
        "rb_off_dis.png": _radio(False, True),
        "rb_on_dis.png": _radio(True, True),
        # Spin / combo stepper arrows (filled triangles).
        "spin_up.png": _chevron(up=True, disabled=False, active=False),
        "spin_down.png": _chevron(up=False, disabled=False, active=False),
        "spin_up_hov.png": _chevron(up=True, disabled=False, active=True),
        "spin_down_hov.png": _chevron(up=False, disabled=False, active=True),
        "spin_up_dis.png": _chevron(up=True, disabled=True, active=False),
        "spin_down_dis.png": _chevron(up=False, disabled=True, active=False),
        "combo_down.png": _chevron(up=False, disabled=False, active=False),
        "combo_down_hov.png": _chevron(up=False, disabled=False, active=True),
        "combo_down_dis.png": _chevron(up=False, disabled=True, active=False),
    }
    for name, image in specs.items():
        path = root / name
        # Always refresh tiny glyphs so style tweaks apply without cache stale.
        image.save(str(path), "PNG")


def _checkbox(checked: bool, disabled: bool):
    from PIL import Image, ImageDraw

    size = _SIZE
    # Transparent canvas — unchecked has no white fill plate (avoids a "box in a box"
    # on selected table rows). Checked uses accent fill + white tick.
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if checked:
        fill = "#c5d4ea" if disabled else t.ACCENT
        edge = fill
        mark = "#ffffff"
    else:
        fill = None
        edge = "#d0d5dc" if disabled else t.BUTTON_EDGE
        mark = ""
    inset = 1
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=3,
        fill=fill,
        outline=edge,
        width=1,
    )
    if checked and mark:
        ax, ay = int(size * 0.24), int(size * 0.52)
        bx, by = int(size * 0.42), int(size * 0.70)
        cx, cy = int(size * 0.78), int(size * 0.30)
        draw.line([(ax, ay), (bx, by), (cx, cy)], fill=mark, width=2, joint="curve")
    return image


def _radio(checked: bool, disabled: bool):
    from PIL import Image, ImageDraw

    size = _SIZE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ring = "#d0d5dc" if disabled else (t.ACCENT if checked else "#8b939e")
    fill = "#f3f4f6" if disabled else t.SURFACE
    dot = "#b0b6be" if disabled else t.ACCENT
    pad = 1
    draw.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=fill, outline=ring, width=1)
    if checked:
        m = 4
        draw.ellipse((m, m, size - m - 1, size - m - 1), fill=dot)
    return image


def _chevron(*, up: bool, disabled: bool, active: bool = False):
    """Filled triangle used inside spin/combo steppers."""
    from PIL import Image, ImageDraw

    size = 9
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if disabled:
        color = "#c5cad1"
    elif active:
        color = t.ACCENT
    else:
        color = "#4b5563"
    mid = size // 2
    if up:
        points = [(1, size - 2), (mid, 1), (size - 2, size - 2)]
    else:
        points = [(1, 1), (mid, size - 2), (size - 2, 1)]
    draw.polygon(points, fill=color)
    return image
