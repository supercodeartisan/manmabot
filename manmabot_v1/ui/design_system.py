"""Light, flat control styles shared by schedule views."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#f4f6f8"
SURFACE = "#ffffff"
CHROME = "#f7f9fb"
CONTROL = "#f4f7fb"
BORDER = "#d5dbe3"
BORDER_STRONG = "#b4bcc6"
TEXT = "#1f2328"
TEXT_MUTED = "#6b7280"
ACCENT = "#3a82f6"
ACCENT_HOVER = "#2f6fdb"
ACCENT_SOFT = "#e8f1fe"
ACCENT_PRESS = "#d3e4fc"
TABLE_HEADER = "#e7eef8"
BUTTON_EDGE = "#a3b8cc"
SELECTED = ACCENT
SELECTED_HOVER = ACCENT_HOVER
FONT_BODY_KR = ("Manmabot Noto KR Medium", 11)
FONT_BUTTON_KR = ("Manmabot Noto KR Medium", 11)
FONT_SECTION_KR = ("Manmabot Noto KR", 12, "bold")
FONT_TITLE_KR = ("Manmabot Noto KR", 15, "bold")
FONT_BODY_ZH = ("Manmabot Noto SC Medium", 11)
FONT_BUTTON_ZH = ("Manmabot Noto SC Medium", 11)
FONT_SECTION_ZH = ("Manmabot Noto SC", 12, "bold")
FONT_TITLE_ZH = ("Manmabot Noto SC", 15, "bold")
FONT_BODY_EN = ("Manmabot Inter Medium", 11)
FONT_BUTTON_EN = ("Manmabot Inter Medium", 11)
FONT_SECTION_EN = ("Manmabot Inter", 12, "bold")
FONT_TITLE_EN = ("Manmabot Inter", 15, "bold")
FONT_BODY = FONT_BODY_EN
FONT_BUTTON = FONT_BUTTON_EN
FONT_SECTION = FONT_SECTION_EN
FONT_TITLE = FONT_TITLE_EN
FONT = FONT_BODY

# Schedule window was designed at ~1760×1000. Default size is 1187×806.
DESIGN_WIDTH = 1760
DESIGN_HEIGHT = 1000
DEFAULT_WIDTH = 1187
DEFAULT_HEIGHT = 806
MIN_WIDTH = 800
MIN_HEIGHT = 600
MIN_FONT_SIZE = 8
UI_SCALE = DEFAULT_WIDTH / DESIGN_WIDTH


def compute_ui_scale(width: int, height: int) -> float:
    """Map a live window size onto the original 1760×1000 design."""
    fallback = DEFAULT_WIDTH / DESIGN_WIDTH
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return fallback
    if width < 50 or height < 50:
        return fallback
    return max(0.55, min(1.0, min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)))


def scaled(value: int | float, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * UI_SCALE)))


def _scale_font(spec: tuple, scale: float | None = None) -> tuple:
    amount = UI_SCALE if scale is None else float(scale)
    family = spec[0]
    size = max(MIN_FONT_SIZE, int(round(int(spec[1]) * amount)))
    extra = spec[2:]
    return (family, size, *extra)

_INDICATOR = 16
_BUTTON_WIDTH = 18
_BUTTON_HEIGHT = 28
_BUTTON_SLICE = 5
_indicator_images: list[tk.PhotoImage] = []


def _in_round_rect(x: float, y: float, size: int, radius: float, inset: float) -> bool:
    left = top = inset
    right = bottom = size - inset
    if x < left or y < top or x > right or y > bottom:
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _rounded_plate(image: tk.PhotoImage, size: int, fill: str, edge: str) -> None:
    radius = 3.2
    for y in range(size):
        for x in range(size):
            px = x + 0.5
            py = y + 0.5
            if not _in_round_rect(px, py, size, radius, 0.6):
                continue
            color = fill if _in_round_rect(px, py, size, radius - 0.15, 1.6) else edge
            image.put(color, to=(x, y, x + 1, y + 1))


def _stamp_check(image: tk.PhotoImage, size: int, color: str) -> None:
    ax, ay = int(size * 0.24), int(size * 0.52)
    bx, by = int(size * 0.42), int(size * 0.70)
    cx, cy = int(size * 0.78), int(size * 0.30)

    def line(x0: int, y0: int, x1: int, y1: int) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            x = int(round(x0 + (x1 - x0) * step / steps))
            y = int(round(y0 + (y1 - y0) * step / steps))
            for dx, dy in ((0, 0), (1, 0), (0, 1)):
                px, py = x + dx, y + dy
                if 0 <= px < size and 0 <= py < size:
                    image.put(color, to=(px, py, px + 1, py + 1))

    line(ax, ay, bx, by)
    line(bx, by, cx, cy)


def checkbox_image(
    root: tk.Misc, checked: bool, disabled: bool = False, size: int = _INDICATOR,
) -> tk.PhotoImage:
    image = tk.PhotoImage(master=root, width=size, height=size)
    if checked:
        fill = "#c5d4ea" if disabled else ACCENT
        edge = fill
        mark = "#ffffff"
    else:
        fill = "#f3f4f6" if disabled else SURFACE
        edge = "#d0d5dc" if disabled else BUTTON_EDGE
        mark = ""
    _rounded_plate(image, size, fill, edge)
    if checked:
        _stamp_check(image, size, mark)
    return image


def _radio_image(root: tk.Misc, checked: bool, disabled: bool = False) -> tk.PhotoImage:
    size = _INDICATOR
    image = tk.PhotoImage(master=root, width=size, height=size)
    ring = "#d0d5dc" if disabled else ("#3a82f6" if checked else "#8b939e")
    fill = "#f3f4f6" if disabled else SURFACE
    dot = "#b0b6be" if disabled else ACCENT
    cx = cy = (size - 1) / 2
    outer = 6.3
    inner = 5.15
    for y in range(size):
        for x in range(size):
            dist = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if dist <= inner:
                image.put(fill, to=(x, y, x + 1, y + 1))
            elif dist <= outer:
                image.put(ring, to=(x, y, x + 1, y + 1))
    if checked:
        for y in range(size):
            for x in range(size):
                dist = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
                if dist <= 2.7:
                    image.put(dot, to=(x, y, x + 1, y + 1))
    return image


def style_text(widget: tk.Text) -> None:
    """Flat text area with a hairline border and an accent focus ring."""
    widget.configure(
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        background=SURFACE,
        foreground=TEXT,
        insertbackground=TEXT,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        font=FONT,
        padx=6,
        pady=4,
    )


def _mix(start: str, end: str, amount: float) -> str:
    def rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    left = rgb(start)
    right = rgb(end)
    mixed = tuple(int(left[i] + (right[i] - left[i]) * amount) for i in range(3))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _in_round_box(
    x: float, y: float, width: int, height: int, radius: float, inset: float,
) -> bool:
    left = top = inset
    right = width - inset
    bottom = height - inset
    if x < left or y < top or x > right or y > bottom:
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def _button_plate(root: tk.Misc, top: str, bottom: str, edge: str) -> tk.PhotoImage:
    """Nine-slice face tall enough for the label, with a thin blue-gray border."""
    width = _BUTTON_WIDTH
    height = _BUTTON_HEIGHT
    image = tk.PhotoImage(master=root, width=width, height=height)
    radius = 4.0
    for y in range(height):
        fill = _mix(top, bottom, y / (height - 1))
        for x in range(width):
            px = x + 0.5
            py = y + 0.5
            if not _in_round_box(px, py, width, height, radius, 0.35):
                continue
            inner = _in_round_box(px, py, width, height, radius - 1.05, 1.25)
            image.put(fill if inner else edge, to=(x, y, x + 1, y + 1))
    return image


def _tab_plate(root: tk.Misc, top: str, bottom: str, edge: str) -> tk.PhotoImage:
    """A fixed-size nine-slice tab with softly rounded top corners."""
    width, height, radius = 26, 30, 6.0
    image = tk.PhotoImage(master=root, width=width, height=height)

    def inside(px: float, py: float, inset: float) -> bool:
        left, right = inset, width - inset
        if px < left or px > right or py < inset or py > height:
            return False
        corner = max(0.0, radius - inset)
        corner_y = inset + corner
        if py >= corner_y:
            return True
        if px < left + corner:
            return (px - left - corner) ** 2 + (py - corner_y) ** 2 <= corner ** 2
        if px > right - corner:
            return (px - right + corner) ** 2 + (py - corner_y) ** 2 <= corner ** 2
        return True

    for y in range(height):
        fill = _mix(top, bottom, y / (height - 1))
        for x in range(width):
            px, py = x + 0.5, y + 0.5
            if inside(px, py, 0.3):
                image.put(
                    fill if inside(px, py, 1.35) else edge,
                    to=(x, y, x + 1, y + 1),
                )
    return image


def _install_rounded_tabs(root: tk.Misc, style: ttk.Style) -> None:
    images = getattr(root, "_rounded_tab_images", None)
    if images is None:
        images = (
            _tab_plate(root, "#ffffff", "#f1f7ff", "#b9cde8"),
            _tab_plate(root, "#eaf4ff", "#d9eaff", "#8fb6e7"),
            _tab_plate(root, "#4a9cf0", "#196bd0", "#1764bd"),
        )
        root._rounded_tab_images = images  # type: ignore[attr-defined]
    try:
        style.element_create(
            "Manmabot.RoundedTab",
            "image",
            images[0],
            ("selected", images[2]),
            ("active", images[1]),
            border=(7, 7, 7, 1),
            sticky="nswe",
        )
    except tk.TclError:
        pass
    for name in ("MainTabs", "SubTabs"):
        style.configure(
            f"{name}.TNotebook",
            background=BG,
            bordercolor=BORDER,
            borderwidth=1,
            tabmargins=(scaled(6), scaled(4), scaled(2), 0),
        )
        style.layout(
            f"{name}.TNotebook.Tab",
            [("Manmabot.RoundedTab", {
                "sticky": "nswe",
                "children": [("Notebook.padding", {
                    "sticky": "nswe",
                    "children": [("Notebook.label", {"sticky": "nswe"})],
                })],
            })],
        )
        tab_pad = (scaled(12), scaled(4, 2))
        style.configure(
            f"{name}.TNotebook.Tab",
            padding=tab_pad,
            font=FONT_BUTTON,
            foreground=TEXT,
        )
        style.map(
            f"{name}.TNotebook.Tab",
            foreground=[("selected", "#ffffff"), ("!selected", TEXT)],
            padding=[("selected", tab_pad), ("!selected", tab_pad)],
        )


def _install_button_border(
    style: ttk.Style, name: str, images: tuple[tk.PhotoImage, ...],
) -> None:
    try:
        style.element_create(
            name,
            "image",
            images[0],
            ("disabled", images[3]),
            ("pressed", images[2]),
            ("active", images[1]),
            border=_BUTTON_SLICE,
            padding=(4, 2, 4, 2),
            sticky="nswe",
        )
    except tk.TclError:
        pass


def _button_layout(style: ttk.Style, widget: str, element: str) -> None:
    style.layout(
        widget,
        [
            (
                element,
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Button.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    ("Button.label", {"sticky": "nswe"})
                                ],
                            },
                        )
                    ],
                },
            )
        ],
    )


def _install_indicator(
    style: ttk.Style, name: str, images: tuple[tk.PhotoImage, ...],
) -> None:
    try:
        style.element_create(
            name,
            "image",
            images[0],
            ("disabled", "selected", images[3]),
            ("disabled", images[2]),
            ("selected", images[1]),
            width=_INDICATOR,
            sticky="w",
        )
    except tk.TclError:
        pass


def _indicator_layout(style: ttk.Style, widget: str, indicator: str) -> None:
    base = widget[1:] if widget.startswith("T") else widget
    style.layout(
        widget,
        [
            (
                f"{base}.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        (indicator, {"side": "left", "sticky": ""}),
                        (
                            f"{base}.focus",
                            {
                                "side": "left",
                                "sticky": "w",
                                "children": [
                                    (f"{base}.label", {"sticky": "nswe"})
                                ],
                            },
                        ),
                    ],
                },
            )
        ],
    )


def use_ui_fonts(language: str, scale: float | None = None) -> None:
    """Point the shared font roles at the active interface language."""
    global FONT_BODY, FONT_BUTTON, FONT_SECTION, FONT_TITLE, FONT, UI_SCALE
    if scale is not None:
        UI_SCALE = max(0.55, min(1.15, float(scale)))
    fonts = {
        "ko": (FONT_BODY_KR, FONT_BUTTON_KR, FONT_SECTION_KR, FONT_TITLE_KR),
        "zh": (FONT_BODY_ZH, FONT_BUTTON_ZH, FONT_SECTION_ZH, FONT_TITLE_ZH),
    }.get(language, (FONT_BODY_EN, FONT_BUTTON_EN, FONT_SECTION_EN, FONT_TITLE_EN))
    FONT_BODY = _scale_font(fonts[0])
    FONT_BUTTON = _scale_font(fonts[1])
    FONT_SECTION = _scale_font(fonts[2])
    FONT_TITLE = _scale_font(fonts[3])
    FONT = FONT_BODY
    try:
        import customtkinter as ctk

        ctk.ThemeManager.theme["CTkFont"]["family"] = FONT_BODY[0]
    except (ImportError, KeyError, TypeError):
        pass


def apply_classic_style(root: tk.Misc, language: str = "en") -> ttk.Style:
    from manmabot_v1.ui.fonts import load_bundled_fonts

    load_bundled_fonts()
    use_ui_fonts(language)
    root.option_add("*Font", FONT_BODY)
    root.option_add("*Background", BG)
    root.option_add("*highlightThickness", 0)
    style = ttk.Style(root)
    try:
        # Vista draws native tab backgrounds itself and can ignore our selected
        # background while still applying white text, making labels invisible.
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=FONT)
    style.configure("TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE, foreground=TEXT, font=FONT_BODY)
    style.configure("Chrome.TFrame", background=CHROME)
    style.configure("Chrome.TLabel", background=CHROME, foreground=TEXT, font=FONT_BODY)
    style.configure(
        "TCheckbutton",
        background=SURFACE,
        foreground=TEXT,
        indicatormargin=(2, 2, 6, 2),
        padding=(2, 2),
        font=FONT_BODY,
    )
    style.configure(
        "TRadiobutton",
        background=SURFACE,
        foreground=TEXT,
        indicatormargin=(2, 2, 6, 2),
        padding=(2, 2),
        font=FONT_BODY,
    )
    style.configure("Chrome.TCheckbutton", background=CHROME, foreground=TEXT, font=FONT_BODY)
    checkbox_images = (
        checkbox_image(root, False),
        checkbox_image(root, True),
        checkbox_image(root, False, True),
        checkbox_image(root, True, True),
    )
    radio_images = (
        _radio_image(root, False),
        _radio_image(root, True),
        _radio_image(root, False, True),
        _radio_image(root, True, True),
    )
    root._checkbox_images = checkbox_images  # type: ignore[attr-defined]
    root._radio_images = radio_images  # type: ignore[attr-defined]
    _indicator_images.extend(checkbox_images)
    _indicator_images.extend(radio_images)
    _install_indicator(
        style,
        "Classic.Checkbutton.indicator",
        checkbox_images,
    )
    _install_indicator(
        style,
        "Classic.Radiobutton.indicator",
        radio_images,
    )
    _indicator_layout(style, "TCheckbutton", "Classic.Checkbutton.indicator")
    _indicator_layout(style, "TRadiobutton", "Classic.Radiobutton.indicator")
    style.layout(
        "InTree.TCheckbutton",
        [("Classic.Checkbutton.indicator", {"side": "left", "sticky": ""})],
    )
    style.configure(
        "InTree.TCheckbutton",
        background=SURFACE,
        padding=0,
        indicatormargin=(0, 0, 0, 0),
    )
    style.map(
        "InTree.TCheckbutton",
        background=[("active", SURFACE), ("pressed", SURFACE)],
    )
    style.map(
        "TCheckbutton",
        background=[("active", SURFACE)],
        foreground=[("disabled", TEXT_MUTED)],
    )
    style.map(
        "TRadiobutton",
        background=[("active", SURFACE)],
        foreground=[("disabled", TEXT_MUTED)],
    )
    style.map(
        "Chrome.TCheckbutton",
        background=[("active", CHROME)],
        foreground=[("disabled", TEXT_MUTED)],
    )
    normal_buttons = (
        _button_plate(root, "#ffffff", "#e6eef7", BUTTON_EDGE),
        _button_plate(root, "#f5f9fd", "#dce8f6", "#8eabc4"),
        _button_plate(root, "#e3edf8", "#d0e0f2", "#7f9db8"),
        _button_plate(root, "#f6f7f8", "#eceff2", "#d8dee6"),
    )
    accent_buttons = (
        _button_plate(root, "#f7fbff", "#d9e7fb", BUTTON_EDGE),
        _button_plate(root, "#eef5ff", "#c9def8", "#8eabc4"),
        _button_plate(root, "#d4e4f8", "#bdd4f3", "#7f9db8"),
        _button_plate(root, "#f6f7f8", "#eceff2", "#d8dee6"),
    )
    root._button_images = normal_buttons + accent_buttons  # type: ignore[attr-defined]
    _indicator_images.extend(normal_buttons)
    _indicator_images.extend(accent_buttons)
    _install_button_border(style, "Rounded.TButton.border", normal_buttons)
    _install_button_border(style, "Rounded.Accent.TButton.border", accent_buttons)
    _button_layout(style, "TButton", "Rounded.TButton.border")
    _button_layout(style, "Accent.TButton", "Rounded.Accent.TButton.border")
    style.configure(
        "TButton",
        padding=(scaled(8), scaled(1)),
        background=CONTROL,
        foreground=TEXT,
        borderwidth=0,
        focusthickness=0,
        relief="flat",
        font=FONT_BUTTON,
    )
    style.map(
        "TButton",
        foreground=[("disabled", "#a0a6ad")],
    )
    style.configure(
        "Accent.TButton",
        padding=(scaled(8), scaled(1)),
        background=ACCENT_SOFT,
        foreground="#17345c",
        borderwidth=0,
        focusthickness=0,
        relief="flat",
        font=FONT_BUTTON,
    )
    style.map(
        "Accent.TButton",
        foreground=[("disabled", "#a0a6ad")],
    )
    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(scaled(6), scaled(2)),
        relief="flat",
        font=FONT_BODY,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT), ("disabled", "#e4e7ec")],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
        fieldbackground=[("disabled", "#f3f4f6")],
        foreground=[("disabled", TEXT_MUTED)],
    )
    style.configure(
        "TCombobox",
        fieldbackground=CONTROL,
        background=CONTROL,
        foreground=TEXT,
        arrowcolor="#4b5563",
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(scaled(4), scaled(2)),
        relief="flat",
        arrowsize=scaled(13, 10),
        font=FONT_BODY,
    )
    # Readonly comboboxes keep a hidden selection highlight on clam; force the
    # current value to stay readable whether focused or not.
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", "focus", SURFACE),
            ("readonly", CONTROL),
            ("disabled", "#f3f4f6"),
        ],
        foreground=[("readonly", TEXT), ("disabled", TEXT_MUTED)],
        selectbackground=[("readonly", CONTROL), ("!readonly", ACCENT)],
        selectforeground=[("readonly", TEXT), ("!readonly", "#ffffff")],
        background=[
            ("readonly", "focus", SURFACE),
            ("readonly", CONTROL),
            ("active", ACCENT_SOFT),
            ("disabled", "#f3f4f6"),
        ],
        bordercolor=[("focus", ACCENT), ("active", ACCENT), ("disabled", "#e4e7ec")],
        arrowcolor=[("active", ACCENT), ("disabled", "#c5cad1")],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*Listbox.background", SURFACE)
    root.option_add("*Listbox.foreground", TEXT)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", "#ffffff")
    root.option_add("*Listbox.font", FONT)
    root.option_add("*Listbox.relief", "flat")
    root.option_add("*Listbox.highlightThickness", 1)
    root.option_add("*Listbox.highlightBackground", BORDER)
    root.option_add("*Listbox.highlightColor", ACCENT)

    def _clear_combobox_selection(event: tk.Event) -> None:
        widget = event.widget
        try:
            widget.selection_clear()
            widget.icursor("end")
        except Exception:
            pass

    root.bind_class("TCombobox", "<<ComboboxSelected>>", _clear_combobox_selection, add="+")
    root.bind_class("TCombobox", "<FocusOut>", _clear_combobox_selection, add="+")
    root.bind_class("TCombobox", "<FocusIn>", _clear_combobox_selection, add="+")
    style.configure(
        "TSpinbox",
        fieldbackground=SURFACE,
        background=CONTROL,
        foreground=TEXT,
        arrowcolor="#4b5563",
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(scaled(4), scaled(2)),
        relief="flat",
        arrowsize=scaled(12, 10),
        font=FONT_BODY,
    )
    style.map(
        "TSpinbox",
        bordercolor=[("focus", ACCENT), ("disabled", "#e4e7ec")],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
        fieldbackground=[("disabled", "#f3f4f6"), ("readonly", SURFACE)],
        background=[("active", ACCENT_SOFT), ("disabled", "#f3f4f6")],
        arrowcolor=[("active", ACCENT), ("disabled", "#c5cad1")],
        foreground=[("disabled", TEXT_MUTED)],
    )
    style.configure(
        "TLabelframe",
        background=SURFACE,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=SURFACE,
        foreground=ACCENT,
        font=FONT_SECTION,
    )
    style.configure(
        "Card.TLabelframe",
        background=SURFACE,
        bordercolor="#c5daf6",
        lightcolor="#c5daf6",
        darkcolor="#c5daf6",
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=SURFACE,
        foreground=ACCENT,
        font=FONT_SECTION,
    )
    style.configure("Title.TLabel", background=SURFACE, foreground=TEXT, font=FONT_TITLE)
    style.configure("Page.TFrame", background="#f4f8fc")
    style.configure("Page.TLabel", background="#f4f8fc", foreground=TEXT, font=FONT_BODY)
    style.configure(
        "Field.TLabel",
        background=SURFACE,
        foreground=ACCENT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        relief="solid",
        borderwidth=1,
        padding=(scaled(12), scaled(3)),
        anchor="center",
        font=FONT_BODY,
    )
    style.configure("Accent.TLabel", background=SURFACE, foreground=ACCENT, font=FONT_BODY)
    style.configure("TSeparator", background=BORDER)
    style.configure(
        "TScrollbar",
        background="#d5dce6",
        troughcolor="#f3f5f8",
        bordercolor="#f3f5f8",
        arrowcolor="#5c6570",
        lightcolor="#d5dce6",
        darkcolor="#d5dce6",
        relief="flat",
        borderwidth=0,
        arrowsize=scaled(12, 10),
    )
    style.map(
        "TScrollbar",
        background=[
            ("pressed", ACCENT),
            ("active", "#b7c3d4"),
            ("disabled", "#eceff3"),
        ],
        arrowcolor=[("active", ACCENT), ("pressed", "#ffffff"), ("disabled", "#c5cad1")],
    )
    style.configure("TPanedwindow", background=BG)
    style.configure(
        "Sash",
        background=BG,
        lightcolor=BG,
        darkcolor=BG,
        bordercolor=BG,
        sashthickness=8,
        gripcount=0,
    )
    style.configure(
        "TNotebook",
        background=BG,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=1,
        tabmargins=(scaled(6), scaled(4), scaled(2), 0),
    )
    style.configure(
        "TNotebook.Tab",
        padding=(scaled(10), scaled(4)),
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=SURFACE,
        darkcolor=BORDER,
        borderwidth=1,
        focuscolor=ACCENT,
        font=FONT_BUTTON,
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", ACCENT),
            ("active", ACCENT_SOFT),
            ("!selected", SURFACE),
        ],
        foreground=[
            ("selected", "#ffffff"),
            ("active", "#17345c"),
            ("!selected", TEXT),
        ],
        bordercolor=[
            ("selected", ACCENT),
            ("active", ACCENT),
            ("!selected", BORDER),
        ],
        lightcolor=[
            ("selected", ACCENT),
            ("active", ACCENT_SOFT),
            ("!selected", SURFACE),
        ],
        darkcolor=[
            ("selected", ACCENT),
            ("active", "#c9daf6"),
            ("!selected", BORDER),
        ],
    )
    _install_rounded_tabs(root, style)
    style.configure(
        "Treeview",
        rowheight=scaled(28, 18),
        font=FONT_BODY,
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Treeview.Heading",
        padding=(scaled(6), scaled(3)),
        background=TABLE_HEADER,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=TABLE_HEADER,
        darkcolor=BORDER,
        borderwidth=1,
        relief="flat",
        font=FONT_SECTION,
    )
    style.map(
        "Treeview.Heading",
        background=[("active", "#d7e4f5")],
        foreground=[("active", "#17345c")],
    )
    style.configure(
        "Grid.Treeview",
        rowheight=scaled(28, 18),
        font=FONT_BODY,
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.map(
        "Grid.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Grid.Treeview.Heading",
        padding=(scaled(6), scaled(3)),
        background=TABLE_HEADER,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=TABLE_HEADER,
        darkcolor=BORDER,
        borderwidth=1,
        relief="flat",
        font=FONT_SECTION,
    )
    style.map(
        "Grid.Treeview.Heading",
        background=[("active", "#d7e4f5")],
        foreground=[("active", "#17345c")],
    )
    return style


def group(parent: tk.Misc, text: str) -> ttk.LabelFrame:
    return ttk.LabelFrame(parent, text=text, padding=(scaled(8), scaled(4)))


def refresh_ui_scale(root: tk.Misc, language: str, scale: float) -> None:
    """Update shared fonts and compact ttk metrics after a window resize."""
    use_ui_fonts(language, scale)
    root.option_add("*Font", FONT_BODY)
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*Listbox.font", FONT)
    style = ttk.Style(root)
    style.configure(".", font=FONT)
    style.configure("TLabel", font=FONT_BODY)
    style.configure("Chrome.TLabel", font=FONT_BODY)
    style.configure("TCheckbutton", font=FONT_BODY, padding=(scaled(2), scaled(1)))
    style.configure("TRadiobutton", font=FONT_BODY, padding=(scaled(2), scaled(1)))
    style.configure("Chrome.TCheckbutton", font=FONT_BODY)
    style.configure("TButton", font=FONT_BUTTON, padding=(scaled(8), scaled(1)))
    style.configure("Accent.TButton", font=FONT_BUTTON, padding=(scaled(8), scaled(1)))
    style.configure("TEntry", font=FONT_BODY, padding=(scaled(6), scaled(2)))
    style.configure(
        "TCombobox",
        font=FONT_BODY,
        padding=(scaled(4), scaled(2)),
        arrowsize=scaled(13, 10),
    )
    style.configure(
        "TSpinbox",
        font=FONT_BODY,
        padding=(scaled(4), scaled(2)),
        arrowsize=scaled(12, 10),
    )
    style.configure("TLabelframe.Label", font=FONT_SECTION)
    style.configure("Card.TLabelframe.Label", font=FONT_SECTION)
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("Page.TLabel", font=FONT_BODY)
    style.configure("Field.TLabel", font=FONT_BODY, padding=(scaled(12), scaled(3)))
    style.configure("Accent.TLabel", font=FONT_BODY)
    style.configure("TScrollbar", arrowsize=scaled(12, 10))
    style.configure("TNotebook.Tab", font=FONT_BUTTON, padding=(scaled(10), scaled(4)))
    tab_pad = (scaled(12), scaled(4, 2))
    for name in ("MainTabs", "SubTabs"):
        style.configure(f"{name}.TNotebook.Tab", font=FONT_BUTTON, padding=tab_pad)
        style.map(
            f"{name}.TNotebook.Tab",
            padding=[("selected", tab_pad), ("!selected", tab_pad)],
        )
    style.configure("Treeview", font=FONT_BODY, rowheight=scaled(28, 18))
    style.configure("Treeview.Heading", font=FONT_SECTION, padding=(scaled(6), scaled(3)))
    style.configure("Grid.Treeview", font=FONT_BODY, rowheight=scaled(28, 18))
    style.configure(
        "Grid.Treeview.Heading", font=FONT_SECTION, padding=(scaled(6), scaled(3)),
    )


def show_combobox_value(
    combo: ttk.Combobox,
    value: object,
    values: list[str] | tuple[str, ...] | None = None,
) -> None:
    """Keep the combobox field filled with the current selection."""
    text = str(value or "")
    if values is not None:
        items = list(values)
        if text and text not in items:
            items.insert(0, text)
        combo.configure(values=items)
    combo.set(text)
    try:
        combo.selection_clear()
        combo.icursor("end")
    except Exception:
        pass
