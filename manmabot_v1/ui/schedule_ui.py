"""Unified classic-Tk schedule and operator console."""
from __future__ import annotations

import copy
import ctypes
import json
import os
import shutil
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import keyboard

from manmabot_v1.accounts import Account, AccountStore, AccountStoreError
from manmabot_v1.bot_controller import RunState
from manmabot_v1.game_shutdown import close_game_client
from manmabot_v1.hp_actions import (
    FIXED_HP_ACTION_IDS,
    item_action_id,
    item_key_from_action,
    is_item_action,
    normalize_hp_actions,
    sync_legacy_from_actions,
)
from manmabot_v1.hotbar.item_catalog import (
    item_display_name,
    list_item_templates,
)
from manmabot_v1.localized_names import (
    item_catalog_display_name,
    item_category_display_name,
    item_search_names,
    language_display_name,
    map_display_name,
    memory_name_for_ui,
    monster_region_candidates,
    route_point_display_name,
    scroll_label_display,
    shop_npc_display,
    species_display_name_ui,
    species_search_names,
)
from manmabot_v1.map_previews import (
    brand_icon_path,
    monster_image_path,
    placeholder_thumb,
)
from manmabot_v1.paths import LOG_DIR, USERDATA, ensure_userdata, is_portable, manmabot_root
from manmabot_v1.farm_schedule import (
    DEFAULT_FARM_STAY_S,
    MAX_FARM_STAY_MIN,
    MIN_FARM_STAY_MIN,
    normalize_farm_stays_s,
    stay_minutes_from_s,
    stay_s_from_minutes,
    stay_seconds_for,
)
from manmabot_v1.probes import (
    Lamp,
    list_farm_details,
    list_map_choices,
    list_patrol_entries,
    localize_probe_detail,
    normalize_map_style,
    probe_game,
)
from manmabot_v1.strings import START_FAIL
from manmabot_v1.profile import (
    Profile, delete_named_profile, list_profile_names, load_named_profile, load_profile,
    named_profile_path, reset_profile, save_named_profile, save_profile,
)
from manmabot_v1.schedule import ScheduleStore, ScheduleTask, profile_snapshot
from manmabot_v1.schedule_clock import ScheduleSession
from manmabot_v1.server_list import server_names_list
from manmabot_v1.spell_defaults import SKILL_GRID, SKILL_KEYS
from manmabot_v1.strings import DEFAULT_HOTKEYS, ui_language, ui_strings
from manmabot_v1.task_runtime import (
    JITTER_MS_MAX,
    JITTER_MS_MIN,
    apply_runtime_settings,
    clamp_jitter_ms,
)
from manmabot_v1.ui.design_system import (
    ACCENT, ACCENT_SOFT, BG, BORDER, BUTTON_EDGE, CHROME, FONT_BODY, FONT_SECTION, SELECTED,
    SURFACE, TABLE_HEADER, TEXT, TEXT_MUTED, apply_classic_style, checkbox_image,
    group, show_combobox_value, style_text,
)
from manmabot_v1.ui import design_system as ui_theme
from manmabot_v1.ui.fonts import load_bundled_fonts
from manmabot_v1.ui.icon_warmup import hunt_icon_cache_key, prepare_hunt_icons
from manmabot_v1.ui.operator_coordinator import OperatorCoordinator
from manmabot_v1.ui.schedule_i18n import LANGUAGES, LANGUAGE_NAMES, tr
from manmabot_v1.ui.sell_filter_panel import SellFilterPanel


def _no_activate(widget: tk.Misc) -> None:
    """Show a window without taking focus away from the game."""
    try:
        hwnd = int(widget.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x08000080)
    except (tk.TclError, OSError, AttributeError):
        pass


def _disable_window_maximize(widget: tk.Misc) -> None:
    """Keep drag-resize, but drop the title-bar maximize button.

    ``winfo_id()`` is the client HWND. The caption (min/max/close) lives on
    its parent. ``resizable(True, True)`` puts ``WS_MAXIMIZEBOX`` back, so
    callers must run this again after that.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(ctypes.windll.user32.GetParent(int(widget.winfo_id())) or 0)
        if not hwnd:
            return
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
        cleared = style & ~0x00010000  # WS_MAXIMIZEBOX
        if cleared == style:
            return
        ctypes.windll.user32.SetWindowLongW(hwnd, -16, cleared)
        # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED — refresh the title bar.
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except (tk.TclError, OSError, AttributeError, ValueError):
        pass


def _clone(task: ScheduleTask) -> ScheduleTask:
    return ScheduleTask.from_dict(copy.deepcopy(task.to_dict()))


# Square thumbnail. The same pad sits on every side, and the column matches that box.
_FARM_MAP_IDS = frozenset({"talking_island", "mainland"})
_HUNT_CELL = 32
_HUNT_PAD = 4
# Detected hotbar slot tiles (Other / Game F keys). Base sizes; live layout scales.
_HOTBAR_SLOT = 56
_HOTBAR_SLOT_MIN = 40
_HOTBAR_SLOT_MAX = 72
_HOTBAR_SLOT_BG = "#2b3340"
_HOTBAR_SLOT_EDGE = "#4a5568"


def _hunt_icon_box() -> int:
    """Thumbnail plus the same padding on every side."""
    return _HUNT_CELL + _HUNT_PAD * 2


def _hunt_row_height() -> int:
    return _hunt_icon_box()


def _fit_icon(image, size: int):
    """Center the sprite in a square with equal padding on every side."""
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


def _filled_icon(path: Path | None, size: int, *, enabled: bool):
    """Fit an icon in the cell, and fade it when the row is not allowed."""
    from PIL import Image, ImageEnhance

    image = None
    if path is not None and path.is_file():
        try:
            image = Image.open(path)
            image.load()
        except OSError:
            image = None
    if image is None:
        image = placeholder_thumb(size)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    image = _fit_icon(image, size)
    if enabled:
        return image
    gray = ImageEnhance.Color(image).enhance(0)
    faded = ImageEnhance.Brightness(gray).enhance(1.2)
    plate = Image.new("RGBA", image.size, (243, 244, 246, 255))
    return Image.blend(faded, plate, 0.5)


def _tree_row(tree: ttk.Treeview, x: int, y: int) -> str:
    if tree.identify_region(x, y) not in ("cell", "tree"):
        return ""
    return tree.identify_row(y) or ""


def table_name_matches(needle: str, *parts: object) -> bool:
    """True when the search box is empty or the needle appears in any part."""
    text = str(needle or "").strip().lower()
    if not text:
        return True
    haystack = " ".join(str(part or "") for part in parts).lower()
    return text in haystack


def _combo_char_width(values: list[str] | tuple[str, ...], *, minimum: int = 8) -> int:
    """Combobox character width that keeps the longest label fully visible."""
    texts = [str(value) for value in values]
    fallback = max([minimum, *(len(text) + 2 for text in texts)], default=minimum)
    try:
        font = tkfont.nametofont("TkDefaultFont")
        unit = max(1, font.measure("0"))
        widest = max((font.measure(text) for text in texts), default=0)
    except (tk.TclError, RuntimeError):
        return fallback
    return max(minimum, int(widest / unit) + 2)


def _size_readonly_combo(
    combo: ttk.Combobox,
    values: list[str] | tuple[str, ...],
    *,
    fit: bool = True,
) -> None:
    values = list(values)
    if fit:
        combo.configure(values=values, width=_combo_char_width(values))
        return
    combo.configure(values=values)


def _bind_wraplength(
    label: ttk.Label, host: tk.Misc, *, pad: int = 16, minimum: int = 160
) -> None:
    def _sync(_event: tk.Event | None = None) -> None:
        width = max(minimum, int(host.winfo_width()) - pad)
        label.configure(wraplength=width)

    host.bind("<Configure>", _sync, add="+")
    _sync()


# Blue summary bullet. Wrapped lines start at the same column as the text after it.
_SUMMARY_BULLET = "●  "


def _summary_bullet_indent(box: tk.Text) -> int:
    """Pixel width of the blue bullet, used as the hanging indent."""
    try:
        font = tkfont.Font(font=box.cget("font"))
    except tk.TclError:
        font = tkfont.Font(font=FONT_BODY)
    return max(1, int(font.measure(_SUMMARY_BULLET)))


def _configure_summary_text(box: tk.Text) -> None:
    """Keep every summary line inside the card, hung from the blue bullet."""
    hang = _summary_bullet_indent(box)
    box.tag_configure("mark", foreground=ACCENT)
    box.tag_configure(
        "item",
        lmargin1=0,
        lmargin2=hang,
        rmargin=ui_theme.scaled(4, 2),
        spacing1=3,
    )
    box.tag_configure("body", foreground=TEXT, spacing1=3)
    box.tag_raise("mark")


def _insert_summary_bullet(box: tk.Text, line: str) -> None:
    box.insert("end", _SUMMARY_BULLET, ("item", "mark"))
    box.insert("end", f"{line}\n", ("item", "body"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


_JITTER_VAR_NAMES = (
    "hunt.attack_jitter_ms",
    "hunt.target_delay_min_ms",
    "hunt.target_delay_max_ms",
)


def _mount_scroll_column(parent: ttk.Frame) -> ttk.Frame:
    """Vertical scroll host so a stacked card column can show every row."""
    style = ttk.Style(parent)
    background = str(style.lookup("Page.TFrame", "background") or "#ffffff")
    canvas = tk.Canvas(parent, highlightthickness=0, bd=0, background=background)
    bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas, style="Page.TFrame")
    window = canvas.create_window((0, 0), window=inner, anchor="nw")
    fitted = {"width": 0}

    def _fit(_event: tk.Event | None = None) -> None:
        width = max(1, int(canvas.winfo_width()))
        if fitted["width"] != width:
            fitted["width"] = width
            canvas.itemconfigure(window, width=width)
        canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

    inner.bind("<Configure>", _fit)
    canvas.bind("<Configure>", _fit)
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return inner


def _tree_data_column(tree: ttk.Treeview, event_x: int) -> str:
    raw = tree.identify_column(event_x)
    if not raw or raw == "#0":
        return ""
    try:
        index = int(raw[1:]) - 1
    except ValueError:
        return ""
    columns = [str(column) for column in tree["columns"]]
    if 0 <= index < len(columns):
        return columns[index]
    return ""


def _set_tree_column_value(tree: ttk.Treeview, iid: str, column: str, value: object) -> None:
    columns = [str(item) for item in tree["columns"]]
    values = list(tree.item(iid, "values"))
    if column not in columns:
        return
    index = columns.index(column)
    while len(values) <= index:
        values.append("")
    values[index] = value
    tree.item(iid, values=values)


def _configure_hunt_icon_column(tree: ttk.Treeview, *, heading: str = "") -> None:
    width = _hunt_icon_box()
    tree.heading("#0", text=heading, anchor="center")
    tree.column("#0", width=width, minwidth=width, stretch=False, anchor="center")


def _lock_hunt_icon_column(tree: ttk.Treeview) -> None:
    """Keep the picture column the same width as the thumbnail after auto-fit."""
    width = _hunt_icon_box()
    tree.column("#0", width=width, minwidth=width, stretch=False, anchor="center")


def _configure_hunt_tree(widget: tk.Misc) -> None:
    style = ttk.Style(widget)
    style.configure(
        "Hunt.Treeview",
        rowheight=_hunt_row_height(),
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        borderwidth=1,
        relief="solid",
        indent=0,
    )
    # Drop the disclosure arrow so the icon sits at the left of the row
    # and does not spill into the name column.
    style.layout(
        "Hunt.Treeview.Item",
        [
            (
                "Treeitem.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        ("Treeitem.image", {"side": "left", "sticky": ""}),
                        ("Treeitem.text", {"side": "left", "sticky": ""}),
                    ],
                },
            )
        ],
    )
    style.configure("Hunt.Treeview.Item", padding=(0, 0, 0, 0))
    style.map(
        "Hunt.Treeview",
        background=[("selected", SELECTED)],
        foreground=[("selected", "#ffffff")],
    )


def _mark_allow_tree(tree: ttk.Treeview) -> None:
    tree.tag_configure("denied", foreground=TEXT_MUTED)


def _checkbox_photo(master: tk.Misc, checked: bool) -> tk.PhotoImage:
    """Blue checkbox drawn into the farm-area table."""
    return checkbox_image(master, checked, size=14)


def _mount_vertical_scroll(parent: ttk.Frame, tree: ttk.Treeview) -> None:
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    scroll = ttk.Scrollbar(parent, orient="vertical")

    def yset(*args: str) -> None:
        scroll.set(*args)
        _refresh_cell_grid(tree)

    scroll.configure(command=tree.yview)
    tree.configure(yscrollcommand=yset)
    tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")


def _mount_tree_scrolls(parent: ttk.Frame, tree: ttk.Treeview) -> None:
    """Vertical and horizontal scroll so every table field stays reachable."""
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    yscroll = ttk.Scrollbar(parent, orient="vertical")
    xscroll = ttk.Scrollbar(parent, orient="horizontal")

    def yset(*args: str) -> None:
        yscroll.set(*args)
        _refresh_cell_grid(tree)

    def xset(*args: str) -> None:
        xscroll.set(*args)
        _refresh_cell_grid(tree)

    yscroll.configure(command=tree.yview)
    xscroll.configure(command=tree.xview)
    tree.configure(yscrollcommand=yset, xscrollcommand=xset)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")

    def shift_wheel(event: tk.Event) -> str:
        tree.xview_scroll(int(-event.delta / 120), "units")
        _refresh_cell_grid(tree)
        return "break"

    tree.bind("<Shift-MouseWheel>", shift_wheel)


def _show_parts(tree: ttk.Treeview) -> set[str]:
    show = tree.cget("show")
    if isinstance(show, str):
        return set(show.split())
    return {str(part) for part in show}


def _grid_columns(tree: ttk.Treeview) -> list[str]:
    columns = [str(column) for column in tree["columns"]]
    if "tree" in _show_parts(tree):
        return ["#0", *columns]
    return columns


def _enable_cell_grid(tree: ttk.Treeview) -> None:
    """Draw borders around each visible Treeview cell."""
    lines: list[tk.Frame] = []
    pending: str | None = None

    def draw() -> None:
        nonlocal pending
        pending = None
        for line in lines:
            line.destroy()
        lines.clear()
        visible = [
            tree.bbox(iid)
            for iid in tree.get_children()
            if tree.bbox(iid)
        ]
        if not visible:
            return
        top = min(box[1] for box in visible)
        bottom = max(box[1] + box[3] for box in visible)
        width = min(
            tree.winfo_width() - 2,
            sum(int(tree.column(column, "width")) for column in tree["columns"]),
        )
        for y in sorted({top, *(box[1] + box[3] for box in visible)}):
            line = tk.Frame(tree, background=BORDER, height=1)
            line.place(x=1, y=y - 1, width=max(1, width))
            lines.append(line)
        x = 1
        for column in tree["columns"]:
            x += int(tree.column(column, "width"))
            line = tk.Frame(tree, background=BORDER, width=1)
            line.place(x=x - 1, y=0, height=bottom)
            lines.append(line)

    def schedule(_event=None) -> None:
        nonlocal pending
        if pending is not None:
            tree.after_cancel(pending)
        pending = tree.after_idle(draw)

    tree.bind("<Configure>", schedule, add="+")
    tree.bind("<Map>", schedule, add="+")
    tree.bind("<MouseWheel>", schedule, add="+")
    tree.bind("<ButtonRelease-1>", schedule, add="+")
    tree.bind("<KeyRelease>", schedule, add="+")
    tree._refresh_cell_grid = schedule  # type: ignore[attr-defined]
    schedule()


def _refresh_cell_grid(tree: ttk.Treeview) -> None:
    refresh = getattr(tree, "_refresh_cell_grid", None)
    if refresh is not None:
        refresh()


def _center_dialog(dialog: tk.Toplevel, owner: tk.Misc) -> None:
    dialog.update_idletasks()
    owner.update_idletasks()
    width = dialog.winfo_width()
    height = dialog.winfo_height()
    placed = width > 1 and height > 1
    if not placed:
        width = max(dialog.winfo_reqwidth(), 1)
        height = max(dialog.winfo_reqheight(), 1)
    x = owner.winfo_rootx() + max(0, (owner.winfo_width() - width) // 2)
    y = owner.winfo_rooty() + max(0, (owner.winfo_height() - height) // 2)
    # geometry y is the outer frame; winfo_rooty is the client area below the title bar.
    chrome_y = owner.winfo_rooty() - owner.winfo_y()
    chrome_x = owner.winfo_rootx() - owner.winfo_x()
    x -= chrome_x
    y -= chrome_y
    if placed:
        dialog.geometry(f"+{x}+{y}")
    else:
        dialog.geometry(f"{width}x{height}+{x}+{y}")


_DEFAULT_PURPLE_PATH = r"C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe"
_DEFAULT_GAME_PATH = r"C:\Program Files (x86)\NC\Lineage Classic\LC.exe"
# heading key, preferred width, stretch, anchor
_ACCOUNT_COLUMNS = (
    ("display_name", "display_name", 120, True, "w"),
    ("server", "server", 100, True, "w"),
    ("character_number", "character_order", 108, False, "center"),
    ("username", "username", 210, True, "w"),
    ("password", "password", 84, False, "w"),
    ("region", "region", 72, False, "w"),
    ("locale", "server_language", 124, False, "w"),
    ("character_type", "character_type", 108, False, "center"),
    ("purple_path", "purple_path", 140, True, "w"),
    ("game_path", "game_path", 140, True, "w"),
)
_ACCOUNT_PATH_COLUMNS = ("purple_path", "game_path")
_ACCOUNT_CELL_PAD = 18
_ACCOUNT_HEAD_PAD = 22

# Fields shown on the New schedule form. Kept narrow so the list pane
# does not push the form off the window.
_SCHEDULE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("enabled", "enabled", 64),
    ("account", "account", 110),
    ("character_slot", "character_order", 72),
    ("character", "character_type", 80),
    ("server", "server", 72),
    ("when", "time_choice", 136),
    ("repeat_daily", "repeat_daily", 72),
    ("weekdays", "weekdays", 100),
)

# Schedule UI category ids. Skill rows come from skill_catalog.
_MAGIC_CATEGORIES = (
    "attack_buff",
    "defense_buff",
    "vision",
    "recovery",
    "mp",
    "attack_magic",
    "utility",
)


def _label_for(ids: dict[str, str], code: str) -> str:
    for label, item_id in ids.items():
        if item_id == str(code):
            return label
    return str(code)


def _narrow_species_columns(tree: ttk.Treeview) -> None:
    """Take a little padding off the monster name and level columns."""
    for column, trim in (("name", 20), ("level", 14)):
        try:
            current = int(float(tree.column(column, "width")))
            anchor = str(tree.column(column, "anchor") or "w")
        except (tk.TclError, TypeError, ValueError):
            continue
        width = max(44, current - trim)
        tree.column(column, width=width, minwidth=width, stretch=False, anchor=anchor)


def _fit_tree_columns(
    tree: ttk.Treeview, *, include_tree: bool = False, stretch_last: bool = False,
) -> None:
    """Size every column to its full heading and cell text. Nothing is clipped."""
    style_name = str(tree.cget("style") or "Treeview") or "Treeview"
    style = ttk.Style(tree)
    from manmabot_v1.ui import design_system as ui_theme
    body = tkfont.Font(font=style.lookup(style_name, "font") or ui_theme.FONT_BODY)
    head = tkfont.Font(
        font=style.lookup(f"{style_name}.Heading", "font") or ui_theme.FONT_SECTION,
    )
    columns = [str(column) for column in tree["columns"]]
    if include_tree and "tree" in _show_parts(tree):
        columns = ["#0", *columns]
    value_columns = [str(column) for column in tree["columns"]]
    for column in columns:
        title = str(tree.heading(column, "text"))
        width = head.measure(title) + 40
        anchor = str(tree.column(column, "anchor") or "w")
        if column == "#0":
            width = max(width, 52)
        elif column in value_columns:
            index = value_columns.index(column)
            for iid in tree.get_children():
                values = tree.item(iid, "values")
                if index < len(values):
                    width = max(width, body.measure(str(values[index])) + 28)
            if column == "enabled":
                width = max(width, 52)
        stretch = bool(stretch_last and column == columns[-1])
        tree.column(
            column, width=width, minwidth=width, stretch=stretch, anchor=anchor,
        )


def _tree_fonts(tree: ttk.Treeview) -> tuple[tkfont.Font, tkfont.Font]:
    style_name = str(tree.cget("style") or "Treeview") or "Treeview"
    style = ttk.Style(tree)
    from manmabot_v1.ui import design_system as ui_theme
    body = tkfont.Font(font=style.lookup(style_name, "font") or ui_theme.FONT_BODY)
    head = tkfont.Font(
        font=style.lookup(f"{style_name}.Heading", "font") or ui_theme.FONT_SECTION,
    )
    return body, head


def _ellipsize(text: str, font: tkfont.Font, width: int) -> str:
    """Shorten text with \"...\" so it fits inside a column."""
    value = str(text or "")
    if width <= 0 or font.measure(value) <= width:
        return value
    ellipsis = "..."
    if font.measure(ellipsis) >= width:
        return ellipsis
    low, high = 0, len(value)
    best = ellipsis
    while low <= high:
        mid = (low + high) // 2
        candidate = value[:mid] + ellipsis
        if font.measure(candidate) <= width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _fit_account_columns(
    tree: ttk.Treeview,
    full_paths: dict[str, tuple[str, str]],
    available: int,
) -> None:
    """Size account columns to the window and ellipsize long launcher paths."""
    if available < 80:
        return
    body, head = _tree_fonts(tree)
    columns = [str(column) for column in tree["columns"]]
    path_columns = [column for column in columns if column in _ACCOUNT_PATH_COLUMNS]
    if not columns:
        return

    def heading_width(column: str) -> int:
        return head.measure(str(tree.heading(column, "text"))) + _ACCOUNT_HEAD_PAD

    widths: dict[str, int] = {}
    for column in columns:
        if column in _ACCOUNT_PATH_COLUMNS:
            widths[column] = heading_width(column)
            continue
        index = columns.index(column)
        width = heading_width(column)
        for iid in tree.get_children():
            values = tree.item(iid, "values")
            if index < len(values):
                width = max(width, body.measure(str(values[index])) + _ACCOUNT_CELL_PAD)
        widths[column] = width

    def shrink(group: list[str], floors: dict[str, int], overflow: int) -> int:
        slack = {column: max(0, widths[column] - floors[column]) for column in group}
        pool = sum(slack.values())
        if pool <= 0 or overflow <= 0:
            return overflow
        take = min(overflow, pool)
        consumed = 0
        keys = [column for column in group if slack[column]]
        for index, column in enumerate(keys):
            if index == len(keys) - 1:
                cut = take - consumed
            else:
                cut = take * slack[column] // pool
            cut = min(cut, slack[column], take - consumed)
            widths[column] -= cut
            consumed += cut
        return overflow - consumed

    heading_floors = {column: heading_width(column) for column in columns}
    text_columns = [column for column in columns if column not in _ACCOUNT_PATH_COLUMNS]
    overflow = shrink(
        text_columns,
        heading_floors,
        sum(widths[column] for column in columns) - available,
    )
    if overflow > 0:
        shrink(columns, {column: 48 for column in columns}, overflow)
    spare = available - sum(widths[column] for column in columns)
    if spare > 0 and path_columns:
        share, remainder = divmod(spare, len(path_columns))
        for index, column in enumerate(path_columns):
            widths[column] += share + (1 if index < remainder else 0)

    drift = sum(widths[column] for column in columns) - available
    if path_columns and drift:
        last = path_columns[-1]
        widths[last] = max(48, widths[last] - drift)

    for column in columns:
        anchor = str(tree.column(column, "anchor") or "w")
        tree.column(
            column,
            width=max(40, int(widths[column])),
            minwidth=40,
            stretch=False,
            anchor=anchor,
        )

    purple_index = columns.index("purple_path") if "purple_path" in columns else -1
    game_index = columns.index("game_path") if "game_path" in columns else -1
    for iid, (purple, game) in full_paths.items():
        if not tree.exists(iid):
            continue
        values = list(tree.item(iid, "values"))
        if 0 <= purple_index < len(values):
            values[purple_index] = _ellipsize(
                purple, body, int(widths.get("purple_path", 0)) - _ACCOUNT_CELL_PAD,
            )
        if 0 <= game_index < len(values):
            values[game_index] = _ellipsize(
                game, body, int(widths.get("game_path", 0)) - _ACCOUNT_CELL_PAD,
            )
        tree.item(iid, values=tuple(values))


def _enable_bbox_grid(tree: ttk.Treeview) -> None:
    """Draw cell borders from the real cell rectangles, including while scrolling."""
    lines: list[tk.Frame] = []
    pending: str | None = None

    def draw() -> None:
        nonlocal pending
        pending = None
        for line in lines:
            line.destroy()
        lines.clear()
        rows: list[list[tuple]] = []
        columns = _grid_columns(tree)
        for iid in tree.get_children():
            cells = [
                box for column in columns
                if (box := tree.bbox(iid, column))
            ]
            if cells:
                rows.append(cells)
        if not rows:
            retries = int(getattr(tree, "_grid_retries", 0))
            if tree.get_children() and retries < 8:
                tree._grid_retries = retries + 1
                try:
                    pending = tree.after(50, draw)
                except tk.TclError:
                    pending = None
            return
        tree._grid_retries = 0
        columns = _grid_columns(tree)
        sample: dict[str, tuple] = {}
        for iid in tree.get_children():
            found = {
                column: box
                for column in columns
                if (box := tree.bbox(iid, column))
            }
            if len(found) > len(sample):
                sample = found
            if len(found) == len(columns):
                break
        if len(sample) == len(columns):
            edges = [int(sample[columns[0]][0])]
            for column in columns:
                box = sample[column]
                edges.append(int(box[0]) + int(box[2]))
        else:
            total = sum(max(1, int(tree.column(column, "width"))) for column in columns)
            try:
                origin = -int(round(float(tree.xview()[0]) * total))
            except (tk.TclError, ValueError, IndexError):
                origin = 0
            edges = [origin]
            for column in columns:
                edges.append(edges[-1] + max(1, int(tree.column(column, "width"))))
        try:
            x0, x1 = (float(value) for value in tree.xview())
        except (tk.TclError, ValueError):
            x0, x1 = 0.0, 1.0
        last = columns[-1]
        stretched = str(tree.column(last, "stretch")) not in ("0", "false", "False")
        if stretched and x0 <= 0.001 and x1 >= 0.999:
            edges[-1] = max(edges[-1], max(1, tree.winfo_width() - 1))
        top = min(int(box[1]) for row in rows for box in row)
        bottom = max(int(box[1]) + int(box[3]) for row in rows for box in row)
        height = max(1, bottom)
        for x in edges:
            line = tk.Frame(tree, background=BORDER, width=1, height=1)
            line.place(x=x, y=0, width=1, height=height)
            lines.append(line)
        span = max(1, edges[-1] - edges[0])
        ys = {0, top, bottom}
        for row in rows:
            ys.add(int(row[0][1]))
            ys.add(int(row[0][1]) + int(row[0][3]))
        for y in sorted(ys):
            line = tk.Frame(tree, background=BORDER, width=1, height=1)
            line.place(x=edges[0], y=y, width=span, height=1)
            lines.append(line)

    def schedule(_event=None) -> None:
        nonlocal pending
        if pending is not None:
            try:
                tree.after_cancel(pending)
            except tk.TclError:
                pass
        try:
            pending = tree.after_idle(draw)
        except tk.TclError:
            pending = None

    tree.bind("<Configure>", schedule, add="+")
    tree.bind("<Map>", schedule, add="+")
    tree.bind("<MouseWheel>", schedule, add="+")
    tree.bind("<ButtonRelease-1>", schedule, add="+")
    tree.bind("<KeyRelease>", schedule, add="+")
    tree._refresh_cell_grid = schedule  # type: ignore[attr-defined]
    schedule()


class _TimeField(ttk.Frame):
    """Hour and minute spin boxes. Seconds stay at 00 in the stored clock."""

    def __init__(self, master, variable: tk.StringVar, *, with_seconds: bool = False) -> None:
        super().__init__(master)
        self.variable = variable
        self._guard = False
        self._parts: list[tuple[tk.StringVar, int, ttk.Spinbox]] = []
        limits = (23, 59, 59) if with_seconds else (23, 59)
        for index, limit in enumerate(limits):
            if index:
                ttk.Label(self, text=":").pack(side="left")
            part = tk.StringVar(self, value="00")
            spin = ttk.Spinbox(
                self,
                from_=0,
                to=limit,
                width=3,
                justify="center",
                textvariable=part,
                command=lambda p=part, lim=limit: self._normalize(p, lim),
            )
            spin.pack(side="left")
            spin.bind("<FocusOut>", lambda _event, p=part, lim=limit: self._normalize(p, lim))
            spin.bind("<Return>", lambda _event, p=part, lim=limit: self._normalize(p, lim))
            part.trace_add(
                "write", lambda *_args, p=part, lim=limit: self._on_part(p, lim)
            )
            self._parts.append((part, limit, spin))
        variable.trace_add("write", self._pull)
        self._pull()

    def _pull(self, *_args) -> None:
        if self._guard:
            return
        bits = str(self.variable.get() or "00:00:00").split(":")
        self._guard = True
        try:
            for (part, limit, _spin), bit in zip(self._parts, bits + ["0", "0", "0"]):
                try:
                    value = int(str(bit).split(".", 1)[0])
                except ValueError:
                    value = 0
                part.set(f"{max(0, min(limit, value)):02d}")
        finally:
            self._guard = False

    def _on_part(self, _part: tk.StringVar, _limit: int) -> None:
        if not self._guard:
            self._push()

    def _normalize(self, part: tk.StringVar, limit: int) -> None:
        raw = part.get().strip().split(".", 1)[0]
        try:
            value = int(raw)
        except ValueError:
            value = 0
        padded = f"{max(0, min(limit, value)):02d}"
        self._guard = True
        try:
            if part.get() != padded:
                part.set(padded)
        finally:
            self._guard = False
        self._push()

    def _push(self) -> None:
        if self._guard:
            return
        values: list[int] = []
        for part, limit, _spin in self._parts:
            raw = part.get().strip().split(".", 1)[0]
            try:
                value = int(raw) if raw else 0
            except ValueError:
                value = 0
            values.append(max(0, min(limit, value)))
        while len(values) < 3:
            values.append(0)
        text = f"{values[0]:02d}:{values[1]:02d}:{values[2]:02d}"
        if str(self.variable.get()) != text:
            self._guard = True
            try:
                self.variable.set(text)
            finally:
                self._guard = False

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for _part, _limit, spin in self._parts:
            spin.configure(state=state)


class UnifiedTaskEditor(ttk.Frame):
    """Persistent, non-modal editor for the selected schedule task."""

    def __init__(self, master, app: "ScheduleWindow") -> None:
        super().__init__(master, padding=(4, 0))
        self.app = app
        self.t = app.t
        self.s = ui_strings(app.language)
        self.task: ScheduleTask | None = None
        self.vars: dict[str, tk.Variable] = {}
        self._inputs: dict[str, list[tk.Widget]] = {}
        self.species_rows: dict[str, tuple[tk.BooleanVar, tk.StringVar]] = {}
        self.slot_rows: dict[str, tuple[tk.BooleanVar, tk.StringVar, tk.StringVar]] = {}
        self._suppress_delay_warn = False
        self._delay_range_guard = False
        self._target_delay_ok = (20, 50)
        self._build()

    def _value(self, section: str, key: str, default: Any) -> Any:
        return (self.task.settings.get(section, {}) if self.task else {}).get(key, default)

    def _var(self, name: str, value: Any, kind: str = "str") -> tk.Variable:
        cls = {"str": tk.StringVar, "bool": tk.BooleanVar, "int": tk.IntVar}[kind]
        var = cls(self, value=value)
        self.vars[name] = var
        return var

    def _row(self, parent, row: int, label: str, name: str, value: Any,
             kind: str = "str", suffix: str = "") -> tk.Variable:
        var = self._var(name, value, kind)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 5), pady=2)
        value_frame = ttk.Frame(parent)
        value_frame.grid(row=row, column=1, sticky="w", pady=2)
        entry = ttk.Entry(value_frame, textvariable=var, width=13)
        entry.pack(side="left")
        self._remember(name, entry)
        if suffix:
            ttk.Label(value_frame, text=suffix).pack(side="left", padx=(3, 0))
        return var

    def _check(self, parent, row: int, label: str, name: str, value: bool) -> tk.Variable:
        var = self._var(name, value, "bool")
        button = ttk.Checkbutton(parent, text=label, variable=var)
        button.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        self._remember(name, button)
        return var

    def _remember(self, name: str, widget: tk.Widget) -> None:
        self._inputs.setdefault(name, []).append(widget)

    def _set_inputs(self, names: tuple[str, ...], enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for name in names:
            for widget in self._inputs.get(name, ()):
                widget.configure(state=state)

    def _bind_gate(self, gate: str, *fields: str) -> None:
        """Disable related inputs while the checkbox is off."""

        def _sync(*_args: object) -> None:
            on = False
            variable = self.vars.get(gate)
            if variable is not None:
                try:
                    on = bool(variable.get())
                except (tk.TclError, TypeError, ValueError):
                    on = False
            self._set_inputs(fields, on)

        if gate in self.vars:
            self.vars[gate].trace_add("write", _sync)
        _sync()

    def _build(self) -> None:
        self._character_ids = {
            self.t[key]: key for key in ("royal", "knight", "elf", "mage")
        }
        self.character_var = self._var("task.character", self.t["mage"])
        self.vars["task.server"] = tk.StringVar(self, value="")
        self.vars["task.character_slot"] = tk.IntVar(self, value=1)
        empty = self.t["value_empty"]
        self.order_display = tk.StringVar(self, value=empty)
        self.type_display = tk.StringVar(self, value=empty)
        self.server_display = tk.StringVar(self, value=empty)
        self._repeat_guard = False
        self._build_account_identity()
        self._build_schedule_timing()

        tabs = ttk.Notebook(self, style="MainTabs.TNotebook")
        self._main_tabs = tabs
        self.pages = {}
        for key in ("move", "hunt", "recovery", "magic", "equipment", "other"):
            page = ttk.Frame(tabs, padding=6)
            tabs.add(page, text=self.t[key])
            self.pages[key] = page
        self._build_move()
        self._build_hunt()
        self._build_recovery()
        self._build_magic()
        self._build_equipment()
        self._build_other()

        commit_bar = ttk.Frame(self)
        commit_bar.pack(side="bottom", fill="x", pady=(16, 8))
        self.commit_button = ttk.Button(
            commit_bar, text=self.t["add_schedule"], command=self.commit,
            style="Accent.TButton",
        )
        self.commit_button.pack(anchor="center")
        tabs.pack(fill="both", expand=True)
        tabs.bind("<<NotebookTabChanged>>", self._on_main_tab_changed, add="+")

    def _build_account_identity(self) -> None:
        """Account, character, and server. Stays with the schedule editor."""
        identity = group(self, self.t["task_details"])
        self.identity_box = identity
        identity.pack(fill="x", pady=(0, 4))
        row = ttk.Frame(identity)
        row.pack(fill="x")
        row.columnconfigure(1, weight=1)
        row.columnconfigure(2, weight=1)
        account = ttk.Frame(row)
        account.grid(row=0, column=0, sticky="w")
        ttk.Label(account, text=self.t["account"], foreground=TEXT_MUTED).pack(
            side="left", padx=(0, 8),
        )
        self.account_combo = ttk.Combobox(account, state="readonly", width=18)
        self.vars["task.account_id"] = tk.StringVar(self)
        self.account_combo.configure(textvariable=self.vars["task.account_id"])
        self.account_combo.bind("<<ComboboxSelected>>", self._account_changed)
        self.account_combo.pack(side="left")
        value_font = (FONT_BODY[0], FONT_BODY[1], "bold")
        facts = (
            (self.t["server"], self.server_display),
            (self.t["character_order"], self.order_display),
            (self.t["character_type"], self.type_display),
        )
        for index, (label, variable) in enumerate(facts, start=1):
            cell = ttk.Frame(row)
            cell.grid(
                row=0, column=index, sticky="e" if index == len(facts) else "w",
                padx=(16, 0),
            )
            ttk.Label(cell, text=label, foreground=TEXT_MUTED).pack(side="left")
            ttk.Label(
                cell, textvariable=variable, foreground=TEXT, font=value_font,
            ).pack(side="left", padx=(8, 0))

    def _build_schedule_timing(self) -> None:
        """Time, account, and weekdays for the schedule list header."""
        host = self.app.schedule_timing_host
        for child in host.winfo_children():
            child.destroy()
        form = ttk.Frame(host)
        form.pack(fill="x", anchor="w")
        mode = self._var("task.time_mode", "window")

        ttk.Label(form, text=self.t["account"]).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4),
        )
        self.schedule_account_combo = ttk.Combobox(
            form,
            state="readonly",
            width=22,
            textvariable=self.vars["task.account_id"],
        )
        self.schedule_account_combo.grid(row=0, column=1, sticky="w", pady=(0, 4))
        self.schedule_account_combo.bind("<<ComboboxSelected>>", self._account_changed)

        ttk.Radiobutton(
            form, text=self.t["time_choice"], value="window", variable=mode,
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 2))
        window_row = ttk.Frame(form)
        window_row.grid(row=1, column=1, sticky="w", pady=(0, 2))
        self.start_time = _TimeField(
            window_row, self._var("task.start_time", "00:00:00")
        )
        self.start_time.pack(side="left")
        ttk.Label(window_row, text="~").pack(side="left", padx=3)
        self.end_time = _TimeField(
            window_row, self._var("task.end_time", "23:59:59")
        )
        self.end_time.pack(side="left")

        ttk.Radiobutton(
            form, text=self.t["duration_choice"], value="duration", variable=mode,
        ).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 2))
        duration_row = ttk.Frame(form)
        duration_row.grid(row=2, column=1, sticky="w", pady=(0, 2))
        self.duration_spin = ttk.Spinbox(
            duration_row,
            from_=1,
            to=10080,
            width=6,
            textvariable=self._var("task.duration_minutes", 90, "int"),
        )
        self.duration_spin.pack(side="left")
        ttk.Label(duration_row, text=self.t["minutes"]).pack(side="left", padx=(4, 0))
        mode.trace_add("write", lambda *_args: self._sync_timing_inputs())
        self._sync_timing_inputs()

        days = ttk.Frame(host)
        days.pack(fill="x", anchor="w", pady=(4, 2))
        repeat = self._var("task.repeat_daily", True, "bool")
        ttk.Checkbutton(days, text=self.t["repeat_daily"], variable=repeat).pack(
            side="left", padx=(0, 8),
        )
        repeat.trace_add("write", self._on_repeat_daily)
        self.weekday_vars = []
        for _day, key in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
            variable = tk.BooleanVar(self, value=True)
            self.weekday_vars.append(variable)
            variable.trace_add("write", self._on_weekday_toggled)
            ttk.Checkbutton(days, text=self.t[key], variable=variable).pack(
                side="left", padx=(0, 4),
            )
        ttk.Button(
            days, text=self.t["add"], command=self.app._new,
        ).pack(side="left", padx=(8, 0))

    def _on_repeat_daily(self, *_args: object) -> None:
        """Repeat daily turns every weekday on, or all of them off."""
        if self._repeat_guard:
            return
        try:
            on = bool(self.vars["task.repeat_daily"].get())
        except (tk.TclError, TypeError, ValueError):
            return
        self._repeat_guard = True
        try:
            for variable in self.weekday_vars:
                if bool(variable.get()) != on:
                    variable.set(on)
        finally:
            self._repeat_guard = False

    def _on_weekday_toggled(self, *_args: object) -> None:
        """Keep Repeat daily checked only while every weekday is checked."""
        if self._repeat_guard:
            return
        self._align_repeat_daily_checkbox()

    def _align_repeat_daily_checkbox(self) -> None:
        repeat = self.vars.get("task.repeat_daily")
        if repeat is None or not getattr(self, "weekday_vars", None):
            return
        try:
            all_on = all(bool(variable.get()) for variable in self.weekday_vars)
            current = bool(repeat.get())
        except (tk.TclError, TypeError, ValueError):
            return
        if current == all_on:
            return
        self._repeat_guard = True
        try:
            repeat.set(all_on)
        finally:
            self._repeat_guard = False

    def _nested(
        self,
        page: ttk.Frame,
        keys: tuple[str, ...],
        *,
        store_as: str | None = None,
    ) -> dict[str, ttk.Frame]:
        book = ttk.Notebook(page, style="SubTabs.TNotebook")
        book.pack(fill="both", expand=True)
        result = {}
        for key in keys:
            frame = ttk.Frame(book, padding=7)
            book.add(frame, text=self.t[key])
            result[key] = frame
        if store_as:
            setattr(self, store_as, book)
        return result

    def _on_main_tab_changed(self, _event: object = None) -> None:
        self._maybe_load_deferred_views()

    def _on_equipment_tab_changed(self, _event: object = None) -> None:
        self._maybe_load_deferred_views()

    def _on_hunt_tab_changed(self, _event: object = None) -> None:
        self._maybe_load_deferred_views()

    def _on_magic_tab_changed(self, _event: object = None) -> None:
        self._maybe_load_deferred_views()

    def _maybe_load_deferred_views(self) -> None:
        """Fill heavy Hunt/Magic/Sell views only when that tab is visible."""
        self._maybe_load_sell_filters()
        tabs = getattr(self, "_main_tabs", None)
        if tabs is None:
            return
        try:
            main_text = str(tabs.tab(tabs.select(), "text") or "")
        except tk.TclError:
            return
        if main_text == self.t["hunt"]:
            hunt = getattr(self, "_hunt_tabs", None)
            if hunt is None:
                return
            try:
                sub = str(hunt.tab(hunt.select(), "text") or "")
            except tk.TclError:
                return
            if sub == self.t["monsters"]:
                self._ensure_species_view()
            elif sub == self.t["hunt_items"]:
                self._ensure_items_view()
        elif main_text == self.t["magic"]:
            magic = getattr(self, "_magic_tabs", None)
            if magic is None:
                return
            try:
                sub = str(magic.tab(magic.select(), "text") or "")
            except tk.TclError:
                return
            if sub == self.t["individual"]:
                self._ensure_magic_skills_view()

    def _ensure_species_view(self) -> None:
        if getattr(self, "_species_view_loaded", False):
            return
        was_clean = not self.form_is_dirty()
        self._load_species()
        if was_clean:
            self.mark_form_clean()

    def _ensure_items_view(self) -> None:
        if getattr(self, "_items_view_loaded", False):
            return
        was_clean = not self.form_is_dirty()
        self._load_item_names()
        if was_clean:
            self.mark_form_clean()

    def _ensure_magic_skills_view(self) -> None:
        if getattr(self, "_magic_skills_shown", False):
            return
        was_clean = not self.form_is_dirty()
        self._show_magic_skills()
        if was_clean:
            self.mark_form_clean()

    def _maybe_load_sell_filters(self) -> None:
        """Load sell catalog/icons only when Equipment → Sell is the visible tab."""
        panel = getattr(self, "sell_filter_panel", None)
        if panel is None:
            return
        tabs = getattr(self, "_main_tabs", None)
        equip = getattr(self, "_equipment_tabs", None)
        if tabs is None or equip is None:
            return
        try:
            main_text = str(tabs.tab(tabs.select(), "text") or "")
            sub_text = str(equip.tab(equip.select(), "text") or "")
        except tk.TclError:
            return
        if main_text == self.t["equipment"] and sub_text == self.t["sell"]:
            panel.ensure_loaded()

    def _build_move(self) -> None:
        page = self.pages["move"]
        self._farm_check_on = _checkbox_photo(self, True)
        self._farm_check_off = _checkbox_photo(self, False)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        settings = group(page, self.t["map_settings"])
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        picker = ttk.Frame(settings)
        picker.pack(fill="x")
        ttk.Label(picker, text=self.t["map_select"]).pack(side="left")
        self.map_var = self._var("move.map_id", "")
        self.map_combo = ttk.Combobox(
            picker, state="readonly", width=28, textvariable=self.map_var,
        )
        self.map_combo.pack(side="left", padx=(8, 8))
        self.map_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_map_combo())
        self.btn_edit_map = ttk.Button(
            picker, text=self.t["edit"], command=self.app.open_map_editor,
        )
        self.btn_edit_map.pack(side="left")

        style_row = ttk.Frame(settings)
        style_row.pack(fill="x", pady=(8, 0))
        ttk.Label(style_row, text=self.t["map_style"]).pack(side="left")
        self.map_style_var = self._var("move.map_style", "normal")
        ttk.Radiobutton(
            style_row,
            text=self.t["map_style_normal"],
            value="normal",
            variable=self.map_style_var,
        ).pack(side="left", padx=(8, 4))
        ttk.Radiobutton(
            style_row,
            text=self.t["map_style_dungeon"],
            value="dungeon",
            variable=self.map_style_var,
        ).pack(side="left", padx=4)
        self.map_style_var.trace_add(
            "write", lambda *_args: self._on_map_style_changed()
        )

        self.map_hint = ttk.Label(
            settings, text=self.t["map_setup_hint"], wraplength=ui_theme.scaled(360, 180), justify="left",
        )
        self.map_hint.pack(anchor="w", fill="x", pady=(6, 2))

        def _fit_map_hint(event: tk.Event) -> None:
            self.map_hint.configure(wraplength=max(240, int(event.width) - 24))

        settings.bind("<Configure>", _fit_map_hint)
        self._farm_schedule_loading = False

        self.areas_group = group(page, self.t["farms"])
        self.areas_group.grid(row=1, column=0, sticky="nsew")
        farm_buttons = ttk.Frame(self.areas_group)
        farm_buttons.pack(side="bottom", fill="x", pady=(6, 0))
        self.btn_select_all_farms = ttk.Button(
            farm_buttons, text=self.t["select_all"], command=self._select_all_farms,
        )
        self.btn_select_all_farms.pack(side="left")
        self.btn_deselect_all_farms = ttk.Button(
            farm_buttons, text=self.t["deselect_all"], command=self._clear_farms,
        )
        self.btn_deselect_all_farms.pack(side="left", padx=(4, 0))
        self.btn_farm_up = ttk.Button(
            farm_buttons, text=self.t["up"], command=lambda: self._move_farm_row(-1),
        )
        self.btn_farm_up.pack(side="left", padx=(8, 0))
        self.btn_farm_down = ttk.Button(
            farm_buttons, text=self.t["down"], command=lambda: self._move_farm_row(1),
        )
        self.btn_farm_down.pack(side="left", padx=(4, 0))
        farm_wrap = ttk.Frame(self.areas_group)
        farm_wrap.pack(fill="both", expand=True)
        ttk.Style(self).configure("Map.Treeview", rowheight=30, indent=0)
        self._farm_stays_s: dict[str, float] = {}
        self.farm_tree = ttk.Treeview(
            farm_wrap,
            columns=("name", "order", "stay", "memo"),
            show="tree headings",
            selectmode="browse",
            style="Map.Treeview",
        )
        self.farm_tree.heading("#0", text=self.t["area_use"], anchor="center")
        self.farm_tree.column("#0", width=72, minwidth=56, stretch=False, anchor="center")
        self.farm_tree.heading("name", text=self.t["area_name"], anchor="center")
        self.farm_tree.column("name", width=140, minwidth=90, stretch=False, anchor="center")
        self.farm_tree.heading("order", text=self.t["farm_order"], anchor="center")
        self.farm_tree.column("order", width=56, minwidth=48, stretch=False, anchor="center")
        self.farm_tree.heading("stay", text=self.t["farm_stay"], anchor="center")
        self.farm_tree.column("stay", width=80, minwidth=64, stretch=False, anchor="center")
        self.farm_tree.heading("memo", text=self.t["notes"], anchor="center")
        self.farm_tree.column("memo", width=180, minwidth=100, stretch=True, anchor="center")
        self.farm_tree.bind("<ButtonRelease-1>", self._on_farm_tree_click)
        self.farm_tree.bind("<Double-1>", self._on_farm_tree_click)
        _mount_vertical_scroll(farm_wrap, self.farm_tree)
        _enable_bbox_grid(self.farm_tree)

        info = group(page, self.t["selection_info"])
        info.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.map_selected_label = ttk.Label(info, text="")
        self.map_registered_label = ttk.Label(info, text="")
        self.map_checked_label = ttk.Label(info, text="")
        self.map_schedule_label = ttk.Label(info, text="")
        for label in (
            self.map_selected_label,
            self.map_registered_label,
            self.map_checked_label,
            self.map_schedule_label,
        ):
            label.pack(anchor="w")
        self._sync_map_areas_ui()

    def _attack_card(self, parent: ttk.Frame, title: str) -> ttk.LabelFrame:
        return ttk.LabelFrame(
            parent,
            text=title,
            padding=(
                ui_theme.scaled(10),
                ui_theme.scaled(10),
                ui_theme.scaled(10),
                ui_theme.scaled(6),
            ),
            style="Card.TLabelframe",
        )

    def _attack_flag(self, parent: tk.Misc, text: str, name: str, default: bool) -> tk.BooleanVar:
        variable = self._var(name, default, "bool")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        button = ttk.Checkbutton(row, variable=variable)
        button.pack(side="left", anchor="n")
        label = ttk.Label(row, text=text, justify="left", wraplength=160)
        label.pack(side="left", fill="x", expand=True, padx=(4, 0))
        label.bind("<Button-1>", lambda _event: variable.set(not bool(variable.get())))
        self._remember(name, button)

        def fit(event: tk.Event) -> None:
            label.configure(wraplength=max(48, int(event.width) - 28))

        row.bind("<Configure>", fit)
        return variable  # type: ignore[return-value]

    def _attack_spin(
        self, parent: tk.Misc, name: str, default: int, low: int, high: int, width: int = 5,
    ) -> ttk.Spinbox:
        variable = self._var(name, default, "int")
        spin = ttk.Spinbox(
            parent, from_=low, to=high, width=width, textvariable=variable,
        )
        self._remember(name, spin)

        def _clamp(_event: tk.Event | None = None) -> None:
            try:
                raw = int(variable.get())
            except (tk.TclError, TypeError, ValueError):
                raw = default
            limited = max(low, min(high, raw))
            if raw != limited:
                variable.set(limited)

        delay_keys = ("hunt.target_delay_min_ms", "hunt.target_delay_max_ms")

        def _commit(_event: tk.Event | None = None) -> None:
            _clamp()
            if name in delay_keys:
                self._enforce_target_delay_order(name)

        spin.bind("<FocusOut>", _commit, add="+")
        spin.bind("<Return>", _commit, add="+")
        if name in delay_keys:
            spin.configure(command=lambda n=name: self._enforce_target_delay_order(n))
        return spin

    def _target_delay_pair(self) -> tuple[int, int] | None:
        try:
            start = clamp_jitter_ms(self.vars["hunt.target_delay_min_ms"].get(), 20)
            end = clamp_jitter_ms(self.vars["hunt.target_delay_max_ms"].get(), 50)
        except (tk.TclError, TypeError, ValueError, KeyError):
            return None
        return start, end

    def _remember_target_delay(self) -> None:
        pair = self._target_delay_pair()
        if pair is not None and pair[0] <= pair[1]:
            self._target_delay_ok = pair

    def _enforce_target_delay_order(self, changed: str = "") -> None:
        if self._suppress_delay_warn or self._delay_range_guard:
            return
        pair = self._target_delay_pair()
        if pair is None:
            return
        start, end = pair
        if start <= end:
            self._target_delay_ok = pair
            return
        ok_start, ok_end = self._target_delay_ok
        self._delay_range_guard = True
        try:
            if changed == "hunt.target_delay_min_ms":
                self.vars["hunt.target_delay_min_ms"].set(ok_start)
            elif changed == "hunt.target_delay_max_ms":
                self.vars["hunt.target_delay_max_ms"].set(ok_end)
            else:
                self.vars["hunt.target_delay_min_ms"].set(ok_start)
                self.vars["hunt.target_delay_max_ms"].set(ok_end)
        finally:
            self._delay_range_guard = False
        messagebox.showwarning(
            self.t["target_delay"],
            self.t["target_delay_order"],
            parent=self.winfo_toplevel(),
        )

    def _attack_value_row(
        self, parent: tk.Misc, label: str, name: str, default: int, low: int, high: int,
        suffix: str = "",
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label).pack(side="left")
        self._attack_spin(row, name, default, low, high).pack(side="left", padx=(8, 0))
        if suffix:
            ttk.Label(row, text=suffix).pack(side="left", padx=(4, 0))

    def _attack_inline(
        self,
        parent: tk.Misc,
        name: str,
        default: bool,
        parts: list[tuple[str, object]],
    ) -> tk.BooleanVar:
        """Checkbox row with labels and spin boxes kept on one line."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        variable = self._var(name, default, "bool")
        button = ttk.Checkbutton(row, variable=variable)
        button.pack(side="left")
        self._remember(name, button)
        self._pack_attack_parts(row, variable, parts)
        self._gate_spin_parts(variable, (parts,))
        return variable  # type: ignore[return-value]

    def _attack_note(self, parent: tk.Misc, text: str) -> None:
        hint = ttk.Label(parent, text=text, justify="left")
        hint.pack(fill="x", padx=(22, 4), pady=(0, 4))
        _bind_wraplength(hint, parent, pad=36, minimum=48)

    def _attack_stack(
        self,
        parent: tk.Misc,
        name: str,
        default: bool,
        label: str,
        *field_rows: list[tuple[str, object]],
        spin_width: int = 6,
    ) -> tk.BooleanVar:
        """Checkbox on the first line; number fields on full-width rows below."""
        block = ttk.Frame(parent)
        block.pack(fill="x", pady=2)
        variable = self._var(name, default, "bool")
        head = ttk.Frame(block)
        head.pack(fill="x")
        button = ttk.Checkbutton(head, variable=variable)
        button.pack(side="left", anchor="n")
        title = ttk.Label(head, text=label, justify="left", wraplength=160)
        title.pack(side="left", fill="x", expand=True, padx=(4, 0))
        title.bind("<Button-1>", lambda _event: variable.set(not bool(variable.get())))
        self._remember(name, button)

        def fit(event: tk.Event) -> None:
            title.configure(wraplength=max(48, int(event.width) - 28))

        head.bind("<Configure>", fit)
        for parts in field_rows:
            fields = ttk.Frame(block)
            fields.pack(fill="x", padx=(22, 0), pady=(2, 0))
            self._pack_attack_parts(fields, variable, parts, spin_width=spin_width)
        self._gate_spin_parts(variable, field_rows)
        return variable  # type: ignore[return-value]

    def _pack_attack_parts(
        self,
        row: tk.Misc,
        variable: tk.Variable,
        parts: list[tuple[str, object]],
        *,
        spin_width: int = 5,
    ) -> None:
        for kind, value in parts:
            if kind == "check":
                text = str(value)
                if text:
                    label = ttk.Label(row, text=text)
                    label.pack(side="left", padx=(4, 0))
                    label.bind(
                        "<Button-1>",
                        lambda _event, var=variable: var.set(not bool(var.get())),
                    )
            elif kind == "text":
                ttk.Label(row, text=str(value)).pack(side="left", padx=(6, 0))
            elif kind == "spin":
                spin_name, spin_default, low, high = value  # type: ignore[misc]
                self._attack_spin(
                    row,
                    str(spin_name),
                    int(spin_default),
                    int(low),
                    int(high),
                    width=spin_width,
                ).pack(side="left", padx=(6, 0))

    def _gate_spin_parts(
        self,
        variable: tk.Variable,
        field_rows: tuple[list[tuple[str, object]], ...] | list[list[tuple[str, object]]],
    ) -> None:
        names = tuple(
            str(value[0])
            for parts in field_rows
            for kind, value in parts
            if kind == "spin"
        )
        if not names:
            return

        def _sync(*_args: object) -> None:
            try:
                on = bool(variable.get())
            except (tk.TclError, TypeError, ValueError):
                on = False
            self._set_inputs(names, on)

        variable.trace_add("write", _sync)
        _sync()

    def _build_attack(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        for column in range(3):
            body.columnconfigure(column, weight=1, uniform="attack")
        body.rowconfigure(0, weight=1)

        left_host = ttk.Frame(body, style="Page.TFrame")
        middle = ttk.Frame(body, style="Page.TFrame")
        right = ttk.Frame(body, style="Page.TFrame")
        left_host.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        middle.grid(row=0, column=1, sticky="nsew", padx=6)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        left = _mount_scroll_column(left_host)

        combat = self._attack_card(left, self.t["attack_method"])
        combat.pack(fill="x", pady=(0, 8))
        mode = self._var("hunt.attack_mode", "ranged")
        modes = ttk.Frame(combat)
        modes.pack(fill="x", pady=(0, 2))
        for value, text in (
            ("ranged", self.t["ranged"]),
            ("magic", self.t["magic_attack"]),
            ("melee", self.t["melee"]),
        ):
            ttk.Radiobutton(
                modes, text=text, value=value, variable=mode,
            ).pack(side="left", padx=(0, 14))
        self._attack_value_row(
            combat, self.t["attack_range"], "hunt.attack_range", 16, 1, 30,
        )
        self._attack_flag(combat, self.t["close_attack_allow"], "hunt.close_attack", False)
        self._attack_inline(
            combat, "hunt.keep_distance", True, [
                ("check", self.t["keep_distance"]),
                ("spin", ("hunt.keep_distance_tiles", 3, 0, 20)),
                ("text", self.t["tiles"]),
            ],
        )

        assist = self._attack_card(left, self.t["combat_assist"])
        assist.pack(fill="x", pady=(0, 8))
        self._attack_flag(assist, self.t["antidote_auto"], "hunt.antidote_auto", False)
        self._attack_stack(
            assist,
            "hunt.attack_jitter",
            False,
            self.t["attack_jitter"],
            [
                ("text", "±"),
                ("spin", ("hunt.attack_jitter_ms", 35, JITTER_MS_MIN, JITTER_MS_MAX)),
                ("text", self.t["ms_unit"]),
            ],
        )
        self._attack_note(assist, self.t["attack_jitter_hint"])
        self._attack_stack(
            assist,
            "hunt.target_delay",
            False,
            self.t["target_delay"],
            [
                ("spin", ("hunt.target_delay_min_ms", 20, JITTER_MS_MIN, JITTER_MS_MAX)),
                ("text", "~"),
                ("spin", ("hunt.target_delay_max_ms", 50, JITTER_MS_MIN, JITTER_MS_MAX)),
                ("text", self.t["ms_unit"]),
            ],
        )
        self._attack_note(assist, self.t["target_delay_hint"])

        abandon = self._attack_card(left, self.t["abandon_target"])
        abandon.pack(fill="x")
        self._attack_inline(
            abandon, "hunt.abandon_same", False, [
                ("check", self.t["abandon_prefix"]),
                ("spin", ("hunt.abandon_seconds", 20, 1, 600)),
                ("text", self.t["abandon_suffix"]),
            ],
        )

        magic = self._attack_card(middle, self.t["magic_use"])
        magic.pack(fill="x", pady=(0, 8))
        self._attack_value_row(
            magic, self.t["mp_above"], "hunt.mp_spell_above", 80, 0, 100, "[%]",
        )
        self._attack_value_row(
            magic, self.t["spell_count"], "hunt.spell_count", 1, 1, 99, f"[{self.t['times']}]",
        )
        self._attack_value_row(
            magic, self.t["basic_attack_count"], "hunt.ranged_count", 1, 1, 99,
            f"[{self.t['times']}]",
        )
        self._attack_flag(magic, self.t["fallback"], "hunt.fallback_melee", False)
        self._attack_value_row(
            magic, "MP <", "hunt.fallback_mp_below", 20, 0, 100, "[%]",
        )
        self._bind_gate("hunt.fallback_melee", "hunt.fallback_mp_below")

        priority = self._attack_card(middle, self.t["target_priority"])
        priority.pack(fill="x", pady=(0, 8))
        priority_flags = (
            ("prefer_nearest", "hunt.prefer_nearest", True),
            ("prefer_aggressor", "hunt.prefer_aggressor", True),
            ("prefer_strong", "hunt.prefer_strong", False),
            ("ignore_weak", "hunt.ignore_weak", True),
            ("prefer_caster", "hunt.prefer_caster", True),
            ("prefer_low_hp", "hunt.prefer_low_hp", True),
            ("exclude_busy", "hunt.exclude_busy", True),
            ("stick_target", "hunt.stick_target", True),
        )
        priority_grid = ttk.Frame(priority)
        priority_grid.pack(fill="x")
        priority_grid.columnconfigure(0, weight=1, uniform="target_priority")
        priority_grid.columnconfigure(1, weight=1, uniform="target_priority")
        for index, (key, name, default) in enumerate(priority_flags):
            cell = ttk.Frame(priority_grid)
            cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 4))
            self._attack_flag(cell, self.t[key], name, default)

        area = self._attack_card(middle, self.t["area_switch"])
        area.pack(fill="x")
        self._attack_inline(
            area, "hunt.area_empty", False, [
                ("check", ""),
                ("spin", ("hunt.area_empty_seconds", 60, 1, 600)),
                ("text", self.t["area_empty_suffix"]),
            ],
        )
        self._attack_stack(
            area,
            "hunt.area_low_yield",
            False,
            self.t["area_low_yield"],
            [
                ("text", self.t["area_low_yield_adena"]),
                ("spin", ("hunt.area_low_yield_adena", 1000, 1, 10_000_000)),
                ("text", self.t["area_low_yield_adena_unit"]),
            ],
            [
                ("text", self.t["area_low_yield_time"]),
                ("spin", ("hunt.area_low_yield_seconds", 180, 1, 600)),
                ("text", self.t["seconds"]),
            ],
            spin_width=8,
        )
        self._attack_inline(
            area, "hunt.area_players", False, [
                ("check", self.t["area_players_prefix"]),
                ("spin", ("hunt.area_player_count", 3, 1, 20)),
                ("text", self.t["area_players_suffix"]),
            ],
        )

        summary = self._attack_card(right, self.t["settings_summary"])
        summary.pack(fill="both", expand=True)
        self.attack_summary = tk.Text(
            summary, wrap="word", height=ui_theme.scaled(18, 8), relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.attack_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.attack_summary)
        self.attack_summary.configure(state="disabled")
        for name, variable in self.vars.items():
            if name.startswith("hunt."):
                variable.trace_add("write", self._refresh_attack_summary)
        self._refresh_attack_summary()

    def _summary_number(self, name: str, fallback: int) -> int:
        try:
            return int(self.vars[name].get())
        except (tk.TclError, ValueError, KeyError):
            return fallback

    def _summary_on(self, name: str) -> bool:
        try:
            return bool(self.vars[name].get())
        except (tk.TclError, ValueError, KeyError):
            return False

    def _refresh_attack_summary(self, *_args: object) -> None:
        if not hasattr(self, "attack_summary"):
            return
        mode = str(self.vars["hunt.attack_mode"].get() or "ranged")
        mode_label = {
            "ranged": self.t["ranged"],
            "magic": self.t["magic_attack"],
            "melee": self.t["melee"],
        }.get(mode, mode)
        lines: list[str] = [
            f"{self.t['attack_method']}: {mode_label}",
            f"{self.t['attack_range']}: {self._summary_number('hunt.attack_range', 16)}",
        ]
        if self._summary_on("hunt.close_attack"):
            lines.append(f"{self.t['close_attack_allow']}: {self.t['summary_on']}")
        if self._summary_on("hunt.keep_distance"):
            tiles = self._summary_number("hunt.keep_distance_tiles", 3)
            lines.append(f"{self.t['keep_distance']}: {tiles} {self.t['tiles']}")
        above = self._summary_number("hunt.mp_spell_above", 80)
        lines.append(f"{self.t['mp_above']}: {above}%")
        lines.append(
            f"{self.t['spell_count']}: {self._summary_number('hunt.spell_count', 1)}{self.t['times']}"
        )
        lines.append(
            f"{self.t['basic_attack_count']}: "
            f"{self._summary_number('hunt.ranged_count', 1)}{self.t['times']}"
        )
        if self._summary_on("hunt.fallback_melee"):
            below = self._summary_number("hunt.fallback_mp_below", 20)
            lines.append(f"{self.t['fallback']}: {self.t['summary_on']} (MP < {below}%)")
        priorities = [
            self.t[key]
            for key, name in (
                ("prefer_nearest", "hunt.prefer_nearest"),
                ("prefer_aggressor", "hunt.prefer_aggressor"),
                ("prefer_strong", "hunt.prefer_strong"),
                ("ignore_weak", "hunt.ignore_weak"),
                ("prefer_caster", "hunt.prefer_caster"),
                ("prefer_low_hp", "hunt.prefer_low_hp"),
                ("exclude_busy", "hunt.exclude_busy"),
                ("stick_target", "hunt.stick_target"),
            )
            if self._summary_on(name)
        ]
        if priorities:
            lines.append(f"{self.t['target_priority']}: {', '.join(priorities)}")
        if self._summary_on("hunt.abandon_same"):
            seconds = self._summary_number("hunt.abandon_seconds", 20)
            lines.append(
                f"{self.t['abandon_prefix']} {seconds} {self.t['abandon_suffix']}"
            )
        area_bits = []
        if self._summary_on("hunt.area_empty"):
            seconds = self._summary_number("hunt.area_empty_seconds", 60)
            area_bits.append(f"{seconds} {self.t['area_empty_suffix']}")
        if self._summary_on("hunt.area_low_yield"):
            adena = self._summary_number("hunt.area_low_yield_adena", 1000)
            seconds = self._summary_number("hunt.area_low_yield_seconds", 180)
            area_bits.append(
                f"{self.t['area_low_yield']}: {adena} {self.t['area_low_yield_adena_unit']} / "
                f"{seconds} {self.t['seconds']}"
            )
        if self._summary_on("hunt.area_players"):
            count = self._summary_number("hunt.area_player_count", 3)
            area_bits.append(
                f"{self.t['area_players_prefix']} {count} {self.t['area_players_suffix']}"
            )
        if area_bits:
            lines.append(f"{self.t['area_switch']}: {', '.join(area_bits)}")
        if self._summary_on("hunt.antidote_auto"):
            lines.append(self.t["antidote_auto"])
        if self._summary_on("hunt.attack_jitter"):
            jitter = self._summary_number("hunt.attack_jitter_ms", 35)
            lines.append(f"{self.t['attack_jitter']}: ±{jitter} {self.t['ms_unit']}")
        if self._summary_on("hunt.target_delay"):
            low = self._summary_number("hunt.target_delay_min_ms", 20)
            high = self._summary_number("hunt.target_delay_max_ms", 50)
            lines.append(f"{self.t['target_delay']}: {low} ~ {high} {self.t['ms_unit']}")

        box = self.attack_summary
        box.configure(state="normal", height=max(len(lines), 1))
        box.delete("1.0", "end")
        for line in lines:
            _insert_summary_bullet(box, line)
        box.configure(state="disabled")

    def _build_hunt(self) -> None:
        pages = self._nested(
            self.pages["hunt"],
            ("attack", "monsters", "hunt_items"),
            store_as="_hunt_tabs",
        )
        hunt_tabs = getattr(self, "_hunt_tabs", None)
        if hunt_tabs is not None:
            hunt_tabs.bind("<<NotebookTabChanged>>", self._on_hunt_tab_changed, add="+")
        self._build_attack(pages["attack"])
        self._build_hunt_monsters(pages["monsters"])
        self._build_hunt_items(pages["hunt_items"])

    def _build_hunt_monsters(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=4, minsize=520)
        body.columnconfigure(1, weight=1, minsize=200)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Page.TFrame")
        right = ttk.Frame(body, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(4, weight=1)
        left.columnconfigure(0, weight=1)

        search_row = ttk.Frame(left)
        search_row.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        search_row.columnconfigure(1, weight=1)
        self.species_search_var = tk.StringVar(self, value="")
        ttk.Label(search_row, text=self.t["filter_search"]).grid(row=0, column=0, sticky="w")
        species_search = ttk.Entry(search_row, textvariable=self.species_search_var)
        species_search.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.species_search_var.trace_add("write", lambda *_args: self._refresh_species_rows())

        filter_row = ttk.Frame(left)
        filter_row.grid(row=1, column=0, sticky="ew", pady=(0, 3))
        filter_row.columnconfigure(5, weight=1)
        self._sort_ids = {
            self.t["sort_name"]: "name",
            self.t["sort_level"]: "level",
        }
        self.species_sort_var = self._var(
            "hunt.species_sort",
            next(
                (
                    label for label, sort_id in self._sort_ids.items()
                    if sort_id == self.app.profile.species_sort
                ),
                self.t["sort_name"],
            ),
        )
        ttk.Label(filter_row, text=self.t["sort"]).grid(row=0, column=0, sticky="w")
        self.species_sort_combo = ttk.Combobox(
            filter_row, state="readonly",
            values=list(self._sort_ids), textvariable=self.species_sort_var,
        )
        _size_readonly_combo(self.species_sort_combo, list(self._sort_ids))
        self.species_sort_combo.grid(row=0, column=1, sticky="w", padx=(4, 12))
        self.species_sort_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_species())
        show_combobox_value(
            self.species_sort_combo, self.species_sort_var.get(), list(self._sort_ids)
        )
        self._species_show_ids = {
            self.t["filter_all"]: "all",
            self.t["filter_allowed"]: "allowed",
            self.t["filter_unallowed"]: "unallowed",
        }
        self.species_show_var = tk.StringVar(self, value=self.t["filter_all"])
        ttk.Label(filter_row, text=self.t["filter_show"]).grid(row=0, column=2, sticky="w")
        self.species_show_combo = ttk.Combobox(
            filter_row,
            state="readonly",
            values=list(self._species_show_ids),
            textvariable=self.species_show_var,
        )
        _size_readonly_combo(self.species_show_combo, list(self._species_show_ids))
        self.species_show_combo.grid(row=0, column=3, sticky="w", padx=(4, 12))
        self.species_show_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: (self._refresh_species_rows(), self._refresh_monsters_summary()),
        )
        ttk.Label(filter_row, text=self.t["filter_region"]).grid(row=0, column=4, sticky="w")
        self.species_region_var = tk.StringVar(self, value=self.t["filter_all"])
        self._species_region_user_set = False
        self.species_region_combo = ttk.Combobox(
            filter_row,
            state="readonly",
            values=[self.t["filter_all"]],
            textvariable=self.species_region_var,
        )
        _size_readonly_combo(self.species_region_combo, [self.t["filter_all"]], fit=False)
        self.species_region_combo.grid(row=0, column=5, sticky="ew", padx=(4, 0))
        self.species_region_combo.bind(
            "<<ComboboxSelected>>",
            self._on_species_region_selected,
        )

        species_mode = ttk.Frame(left)
        species_mode.grid(row=2, column=0, sticky="ew", pady=(0, 3))
        self.species_mode_var = self._var("hunt.species_filter_mode", "blacklist")
        ttk.Radiobutton(
            species_mode, text=self.t["filter_blacklist"], value="blacklist",
            variable=self.species_mode_var,
            command=self._on_species_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            species_mode, text=self.t["filter_whitelist"], value="whitelist",
            variable=self.species_mode_var,
            command=self._on_species_mode_change,
        ).pack(side="left", padx=(8, 0))
        species_hint = ttk.Label(
            left, text=self.t["species_filter_hint"], justify="left",
        )
        species_hint.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        _bind_wraplength(species_hint, left)

        species_buttons = ttk.Frame(left)
        species_buttons.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(
            species_buttons, text=self.t["toggle"], command=self._toggle_species,
        ).pack(side="left")
        _configure_hunt_tree(self)
        self._species_order: list[str] = []
        self._species_allowed: dict[str, bool] = {}
        self._species_level: dict[str, int] = {}
        self._species_defaults: dict[str, int] = {}
        self._species_labels: dict[str, str] = {}
        self._species_search: dict[str, str] = {}
        self._species_region_text: dict[str, str] = {}
        self._species_region_values: dict[str, tuple[str, ...]] = {}
        self._species_on_mainland: dict[str, bool] = {}
        self._species_mainland_label = ""
        self._species_icons: dict[str, Path | None] = {}
        species_wrap = ttk.Frame(left)
        species_wrap.grid(row=4, column=0, sticky="nsew")
        self.species_tree = ttk.Treeview(
            species_wrap,
            columns=("name", "level", "allow", "region"),
            show="tree headings",
            height=8,
            selectmode="extended",
            style="Hunt.Treeview",
        )
        _configure_hunt_icon_column(self.species_tree, heading=self.t["species_image"])
        self.species_tree.heading("name", text=self.t["species_name"])
        self.species_tree.heading("level", text=self.t["species_level"])
        self.species_tree.heading("allow", text=self.t["allowed"])
        self.species_tree.heading("region", text=self.t["species_regions"], anchor="w")
        self.species_tree.column("name", width=140, minwidth=88, stretch=False)
        self.species_tree.column("level", width=56, minwidth=44, anchor="center", stretch=False)
        self.species_tree.column("allow", width=90, minwidth=70, anchor="center", stretch=False)
        self.species_tree.column("region", width=220, minwidth=120, stretch=True)
        self.species_tree.bind("<Double-1>", self._edit_species_cell)
        self.species_tree.bind("<ButtonPress-1>", self._start_species_drag)
        self.species_tree.bind("<B1-Motion>", self._drag_species_selection)
        self._species_drag_anchor = ""
        _mark_allow_tree(self.species_tree)
        _mount_tree_scrolls(species_wrap, self.species_tree)
        _enable_bbox_grid(self.species_tree)

        summary = self._attack_card(right, self.t["settings_summary"])
        summary.pack(fill="both", expand=True)
        self.monsters_summary = tk.Text(
            summary, wrap="word", height=ui_theme.scaled(16, 8), relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.monsters_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.monsters_summary)
        self.monsters_summary.configure(state="disabled")
        self._refresh_monsters_summary()

    def _build_hunt_items(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=4, minsize=520)
        body.columnconfigure(1, weight=1, minsize=200)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Page.TFrame")
        right = ttk.Frame(body, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew")
        left.rowconfigure(4, weight=1)
        left.columnconfigure(0, weight=1)

        search_row = ttk.Frame(left)
        search_row.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        search_row.columnconfigure(1, weight=1)
        self.item_search_var = tk.StringVar(self, value="")
        ttk.Label(search_row, text=self.t["filter_search"]).grid(row=0, column=0, sticky="w")
        item_search = ttk.Entry(search_row, textvariable=self.item_search_var)
        item_search.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.item_search_var.trace_add("write", lambda *_args: self._refresh_item_rows())
        filter_row = ttk.Frame(left)
        filter_row.grid(row=1, column=0, sticky="ew", pady=(0, 3))
        filter_row.columnconfigure(3, weight=1)
        self._item_show_ids = {
            self.t["filter_all"]: "all",
            self.t["filter_allowed"]: "allowed",
            self.t["filter_unallowed"]: "unallowed",
        }
        self.item_show_var = tk.StringVar(self, value=self.t["filter_all"])
        ttk.Label(filter_row, text=self.t["filter_show"]).grid(row=0, column=0, sticky="w")
        self.item_show_combo = ttk.Combobox(
            filter_row,
            state="readonly",
            values=list(self._item_show_ids),
            textvariable=self.item_show_var,
        )
        _size_readonly_combo(self.item_show_combo, list(self._item_show_ids))
        self.item_show_combo.grid(row=0, column=1, sticky="w", padx=(4, 12))
        self.item_show_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: (self._refresh_item_rows(), self._refresh_items_summary()),
        )
        ttk.Label(filter_row, text=self.t["filter_category"]).grid(row=0, column=2, sticky="w")
        default_category = self._default_item_category_label()
        self.item_category_var = tk.StringVar(self, value=default_category)
        initial_categories = [self.t["filter_all"]]
        if default_category not in initial_categories:
            initial_categories.append(default_category)
        self.item_category_combo = ttk.Combobox(
            filter_row,
            state="readonly",
            values=initial_categories,
            textvariable=self.item_category_var,
        )
        _size_readonly_combo(self.item_category_combo, initial_categories, fit=False)
        self.item_category_combo.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self.item_category_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: (self._refresh_item_rows(), self._refresh_items_summary()),
        )
        item_mode = ttk.Frame(left)
        item_mode.grid(row=2, column=0, sticky="ew", pady=(0, 3))
        self.item_mode_var = self._var("other.item_pickup_mode", "blacklist")
        ttk.Radiobutton(
            item_mode, text=self.t["filter_blacklist"], value="blacklist",
            variable=self.item_mode_var,
            command=self._on_item_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            item_mode, text=self.t["filter_whitelist"], value="whitelist",
            variable=self.item_mode_var,
            command=self._on_item_mode_change,
        ).pack(side="left", padx=(8, 0))
        item_hint = ttk.Label(
            left, text=self.t["item_pickup_hint"], justify="left",
        )
        item_hint.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        _bind_wraplength(item_hint, left)
        tools = ttk.Frame(left)
        tools.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(tools, text=self.t["toggle"], command=self._toggle_items).pack(side="left")
        item_wrap = ttk.Frame(left)
        item_wrap.grid(row=4, column=0, sticky="nsew")
        self._item_order: list[str] = []
        self._item_allowed: dict[str, bool] = {}
        self._item_labels: dict[str, str] = {}
        self._item_search: dict[str, str] = {}
        self._item_categories: dict[str, str] = {}
        self._item_icons: dict[str, Path | None] = {}
        self.item_tree = ttk.Treeview(
            item_wrap,
            columns=("name", "category", "allow"),
            show="tree headings",
            height=8,
            selectmode="extended",
            style="Hunt.Treeview",
        )
        _configure_hunt_icon_column(self.item_tree, heading=self.t["species_image"])
        self.item_tree.heading("name", text=self.t["item_name"])
        self.item_tree.heading("category", text=self.t["filter_category"])
        self.item_tree.heading("allow", text=self.t["allowed"])
        self.item_tree.column("name", width=200, minwidth=120, stretch=True)
        self.item_tree.column("category", width=140, minwidth=90, stretch=False)
        self.item_tree.column("allow", width=90, minwidth=70, anchor="center", stretch=False)
        self.item_tree.bind("<Double-1>", self._toggle_item_cell)
        self.item_tree.bind("<ButtonPress-1>", self._start_item_drag)
        self.item_tree.bind("<B1-Motion>", self._drag_item_selection)
        self._item_drag_anchor = ""
        _mark_allow_tree(self.item_tree)
        _mount_tree_scrolls(item_wrap, self.item_tree)
        _enable_bbox_grid(self.item_tree)

        summary = self._attack_card(right, self.t["settings_summary"])
        summary.pack(fill="both", expand=True)
        self.items_summary = tk.Text(
            summary, wrap="word", height=ui_theme.scaled(16, 8), relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.items_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.items_summary)
        self.items_summary.configure(state="disabled")
        self._refresh_items_summary()

    def _write_summary_lines(
        self,
        box: tk.Text,
        lines: list[str],
        *,
        section: str | None = None,
        bullets: list[str] | None = None,
    ) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        for line in lines:
            _insert_summary_bullet(box, line)
        if section:
            box.insert("end", "\n")
            box.insert("end", section + "\n", "body")
        if bullets:
            if not section:
                box.insert("end", "\n")
            for name in bullets:
                _insert_summary_bullet(box, name)
        box.configure(state="disabled")

    def _refresh_monsters_summary(self, *_args: object) -> None:
        if not hasattr(self, "monsters_summary"):
            return
        mode = "blacklist"
        if hasattr(self, "species_mode_var"):
            mode = str(self.species_mode_var.get() or "blacklist").strip().lower()
        mode_label = (
            self.t["filter_whitelist"] if mode == "whitelist" else self.t["filter_blacklist"]
        )
        sort_label = str(getattr(self, "species_sort_var", tk.StringVar()).get() or self.t["sort_name"])
        show_label = str(getattr(self, "species_show_var", tk.StringVar()).get() or self.t["filter_all"])
        order = list(getattr(self, "_species_order", []) or [])
        allowed_map = getattr(self, "_species_allowed", {}) or {}
        allowed_n = sum(1 for key in order if bool(allowed_map.get(key, True)))
        total = len(order)
        lines = [
            f"{self.t['summary_filter_mode']}: {mode_label}",
            f"{self.t['summary_sort']}: {sort_label}",
            f"{self.t['summary_show']}: {show_label}",
            self.t["summary_allowed_count"].format(allowed=allowed_n, total=total),
        ]
        focus_allowed = mode == "whitelist"
        list_title = (
            self.t["summary_allowed_list"] if focus_allowed else self.t["summary_denied_list"]
        )
        named: list[str] = []
        for key in order:
            is_allowed = bool(allowed_map.get(key, True))
            if focus_allowed and not is_allowed:
                continue
            if not focus_allowed and is_allowed:
                continue
            named.append(species_display_name_ui(key, self._catalog_language()))
        limit = 40
        bullets = named[:limit]
        if len(named) > limit:
            bullets.append(self.t["summary_more"].format(count=len(named) - limit))

        box = self.monsters_summary
        self._write_summary_lines(box, lines, section=list_title, bullets=bullets)

    def _refresh_items_summary(self, *_args: object) -> None:
        if not hasattr(self, "items_summary"):
            return
        mode = "blacklist"
        if hasattr(self, "item_mode_var"):
            mode = str(self.item_mode_var.get() or "blacklist").strip().lower()
        mode_label = (
            self.t["filter_whitelist"] if mode == "whitelist" else self.t["filter_blacklist"]
        )
        show_label = str(getattr(self, "item_show_var", tk.StringVar()).get() or self.t["filter_all"])
        order = list(getattr(self, "_item_order", []) or [])
        allowed_map = getattr(self, "_item_allowed", {}) or {}
        labels = getattr(self, "_item_labels", {}) or {}
        allowed_n = sum(1 for key in order if bool(allowed_map.get(key, True)))
        total = len(order)
        lines = [
            f"{self.t['summary_filter_mode']}: {mode_label}",
            f"{self.t['summary_show']}: {show_label}",
            self.t["summary_allowed_count"].format(allowed=allowed_n, total=total),
        ]
        focus_allowed = mode == "whitelist"
        list_title = (
            self.t["summary_allowed_list"] if focus_allowed else self.t["summary_denied_list"]
        )
        named: list[str] = []
        for key in order:
            is_allowed = bool(allowed_map.get(key, True))
            if focus_allowed and not is_allowed:
                continue
            if not focus_allowed and is_allowed:
                continue
            named.append(str(labels.get(key, key)))
        limit = 40
        bullets = named[:limit]
        if len(named) > limit:
            bullets.append(self.t["summary_more"].format(count=len(named) - limit))
        self._write_summary_lines(
            self.items_summary, lines, section=list_title, bullets=bullets,
        )

    def _catalog_language(self) -> str:
        """UI display language for official catalog labels."""
        return str(getattr(self.app, "language", "") or "ko")

    def _on_catalog_language(self) -> None:
        self._load_species()
        self._load_item_names()

    def _on_species_mode_change(self) -> None:
        self._load_species()
        self._refresh_monsters_summary()

    def _on_item_mode_change(self) -> None:
        self._load_item_names()
        self._refresh_items_summary()

    def _fix_open(self, parent: tk.Misc) -> dict[str, Any]:
        """Aligned form: checkbox, wrapping label, spin, suffix."""
        sheet = ttk.Frame(parent)
        sheet.pack(fill="x")
        sheet.columnconfigure(1, weight=1)
        state: dict[str, Any] = {
            "sheet": sheet,
            "row": 0,
            "titles": [],
            "suffixes": [],
        }

        def fit(event: tk.Event) -> None:
            suffix_w = 0
            for label in state["suffixes"]:
                try:
                    suffix_w = max(suffix_w, int(label.winfo_reqwidth()))
                except tk.TclError:
                    pass
            width = max(0, int(event.width))
            meter_wrap = max(88, width - suffix_w - 116)
            flag_wrap = max(120, width - 40)
            for title, kind in state["titles"]:
                if kind == "stack":
                    continue
                try:
                    title.configure(
                        wraplength=meter_wrap if kind == "meter" else flag_wrap,
                    )
                except tk.TclError:
                    pass

        sheet.bind("<Configure>", fit)
        return state

    def _fix_take_row(self, state: dict[str, Any]) -> int:
        row = int(state["row"])
        state["row"] = row + 1
        return row

    def _fix_note(self, parent: tk.Misc, text: str) -> None:
        hint = ttk.Label(
            parent,
            text=text,
            justify="left",
            foreground=ui_theme.TEXT_MUTED,
        )
        hint.pack(fill="x", anchor="w", pady=(0, 6))
        _bind_wraplength(hint, parent, pad=4, minimum=160)

    def _fix_meter(
        self,
        state: dict[str, Any],
        *,
        gate: str,
        gate_default: bool,
        label: str,
        name: str,
        default: int,
        suffix: str,
        low: int = 0,
        high: int = 100,
        indent: int = 0,
        bind: bool = True,
        stack: bool = False,
    ) -> tk.BooleanVar:
        sheet: ttk.Frame = state["sheet"]
        row = self._fix_take_row(state)
        variable = self._var(gate, gate_default, "bool")
        button = ttk.Checkbutton(sheet, variable=variable)
        button.grid(row=row, column=0, sticky="nw", pady=(3, 0) if stack else 3)
        self._remember(gate, button)
        title = ttk.Label(
            sheet,
            text=label,
            justify="left",
            anchor="w",
            wraplength=220 if stack else 140,
        )
        if stack:
            title.grid(
                row=row, column=1, columnspan=3, sticky="ew",
                padx=(4 + indent, 0), pady=(3, 0),
            )
        else:
            title.grid(row=row, column=1, sticky="ew", padx=(4 + indent, 8), pady=3)
        title.bind(
            "<Button-1>",
            lambda _event, var=variable: var.set(not bool(var.get())),
        )
        state["titles"].append((title, "stack" if stack else "meter"))
        if stack:
            def _fit_stack(event: tk.Event, label_widget: ttk.Label = title) -> None:
                label_widget.configure(wraplength=max(48, int(event.width)))

            title.bind("<Configure>", _fit_stack, add="+")
        spin = ttk.Spinbox(
            sheet, from_=low, to=high, width=5,
            textvariable=self._var(name, default, "int"),
        )
        self._remember(name, spin)
        suffix_label = ttk.Label(sheet, text=suffix, anchor="w")
        if stack:
            value_row = self._fix_take_row(state)
            spin.grid(
                row=value_row, column=1, sticky="w",
                padx=(4 + indent, 0), pady=(2, 4),
            )
            suffix_label.grid(
                row=value_row, column=2, columnspan=2, sticky="w",
                padx=(6, 0), pady=(2, 4),
            )
        else:
            spin.grid(row=row, column=2, sticky="e", pady=3)
            suffix_label.grid(row=row, column=3, sticky="w", padx=(6, 0), pady=3)
            state["suffixes"].append(suffix_label)
        if bind:
            self._bind_gate(gate, name)
        return variable  # type: ignore[return-value]

    def _fix_flag(
        self,
        state: dict[str, Any],
        label: str,
        name: str,
        default: bool,
        *,
        indent: int = 0,
    ) -> tk.BooleanVar:
        sheet: ttk.Frame = state["sheet"]
        row = self._fix_take_row(state)
        variable = self._var(name, default, "bool")
        button = ttk.Checkbutton(sheet, variable=variable)
        button.grid(row=row, column=0, sticky="nw", pady=2)
        self._remember(name, button)
        title = ttk.Label(
            sheet, text=label, justify="left", anchor="w", wraplength=200,
        )
        title.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(4 + indent, 0), pady=2)
        title.bind(
            "<Button-1>",
            lambda _event, var=variable: var.set(not bool(var.get())),
        )
        state["titles"].append((title, "flag"))
        return variable  # type: ignore[return-value]

    def _fix_value(
        self,
        state: dict[str, Any],
        label: str,
        name: str,
        default: int,
        *,
        low: int = 0,
        high: int = 999,
    ) -> None:
        sheet: ttk.Frame = state["sheet"]
        row = self._fix_take_row(state)
        title = ttk.Label(
            sheet, text=label, justify="left", anchor="w", wraplength=140,
        )
        title.grid(row=row, column=1, sticky="ew", padx=(4, 8), pady=3)
        state["titles"].append((title, "meter"))
        spin = ttk.Spinbox(
            sheet, from_=low, to=high, width=5,
            textvariable=self._var(name, default, "int"),
        )
        spin.grid(row=row, column=2, sticky="e", pady=3)
        self._remember(name, spin)

    def _build_recovery(self) -> None:
        pages = self._nested(
            self.pages["recovery"],
            ("fix_options", "hp_and_inventory"),
        )
        self._build_recovery_options(pages["fix_options"])
        self._build_hp_and_inventory(pages["hp_and_inventory"])

    def _build_recovery_options(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        for column in range(3):
            body.columnconfigure(
                column, weight=1, uniform="fixopt", minsize=ui_theme.scaled(240, 160),
            )
        body.rowconfigure(0, weight=1, uniform="fixrow")
        body.rowconfigure(1, weight=1, uniform="fixrow")

        # Hidden legacy keys — kept so old schedules still load/save.
        self._var("recovery.hp_recover_enabled", True, "bool")
        self._var("recovery.hp_potion_below", 55, "int")
        self._var("recovery.use_hp_potion", True, "bool")
        self._var("recovery.use_heal", True, "bool")
        self._var("recovery.escape_hp_below", 30, "int")
        self._var("hunt.return_hp_enabled", False, "bool")
        self._var("hunt.return_hp_below", 30, "int")
        self._var("hunt.return_then_resume", True, "bool")
        self._var("hunt.recover_before_hunt", True, "bool")

        session = self._attack_card(body, self.t["fix_recovery"])
        session.grid(row=0, column=0, sticky="nsew", padx=4, pady=(0, 4))
        recover = self._fix_open(session)
        self._fix_meter(
            recover,
            gate="recovery.mp_recover_enabled", gate_default=False,
            label="MP", name="recovery.mp_potion_below", default=30,
            suffix=self.t["pct_or_less"],
        )
        self._fix_flag(
            recover, self.t["use_mp_potion"], "recovery.use_mp_potion", False, indent=18,
        )
        self._bind_gate("recovery.mp_recover_enabled", "recovery.use_mp_potion")
        self._fix_flag(recover, self.t["resurrect"], "recovery.resurrect_if_dead", True)
        self._fix_flag(recover, self.t["resume_login"], "recovery.resume_after_relogin", True)
        self._fix_value(recover, self.t["retries"], "recovery.max_retries", 3, low=0, high=999)

        returning = self._attack_card(body, self.t["fix_return"])
        returning.grid(row=1, column=0, sticky="nsew", padx=4, pady=(4, 0))
        back = self._fix_open(returning)
        self._fix_meter(
            back,
            gate="hunt.return_mp_enabled", gate_default=True,
            label=self.t["return_mp"], name="hunt.return_mp_below", default=15,
            suffix=self.t["pct_or_less"],
        )
        self._fix_meter(
            back,
            gate="hunt.return_idle_enabled", gate_default=False,
            label=self.t["return_idle"], name="hunt.return_idle_seconds", default=60,
            suffix=self.t["seconds_when"], low=1, high=3600,
        )

        teleport = self._attack_card(body, self.t["fix_teleport"])
        teleport.grid(row=0, column=1, sticky="nsew", padx=4, pady=(0, 4))
        self._fix_note(teleport, self.t["fix_teleport_note"])
        warp = self._fix_open(teleport)
        teleport_enabled = self._fix_flag(
            warp, self.t["random_teleport"], "recovery.random_teleport_enabled", False,
        )
        self._fix_flag(
            warp, self.t["teleport_player"], "recovery.teleport_on_player", False, indent=18,
        )
        self._fix_meter(
            warp,
            gate="recovery.teleport_when_surrounded", gate_default=False,
            label=self.t["teleport_surrounded"],
            name="recovery.teleport_surround_count",
            default=4,
            suffix=self.t["teleport_surround_count_suffix"],
            low=2,
            high=20,
            indent=18,
            bind=False,
            stack=True,
        )
        _teleport_fields = (
            "recovery.teleport_on_player",
            "recovery.teleport_when_surrounded",
            "recovery.teleport_surround_count",
        )

        def _sync_teleport(*_args: object) -> None:
            on = bool(teleport_enabled.get())
            self._set_inputs(_teleport_fields, on)
            if on:
                self._set_inputs(
                    ("recovery.teleport_surround_count",),
                    bool(self.vars["recovery.teleport_when_surrounded"].get()),
                )

        teleport_enabled.trace_add("write", _sync_teleport)
        self.vars["recovery.teleport_when_surrounded"].trace_add("write", _sync_teleport)
        _sync_teleport()

        supplies = self._attack_card(body, self.t["fix_return_supplies"])
        supplies.grid(row=1, column=1, sticky="nsew", padx=4, pady=(4, 0))
        stock = self._fix_open(supplies)
        self._fix_meter(
            stock,
            gate="hunt.return_potion_enabled", gate_default=True,
            label=self.t["return_potion_count"], name="hunt.return_potion_count",
            default=20, suffix=self.t["count_or_fewer"], low=0, high=999,
        )
        self._fix_meter(
            stock,
            gate="hunt.return_arrow_enabled", gate_default=True,
            label=self.t["return_arrow_count"], name="hunt.return_arrow_count",
            default=300, suffix=self.t["count_or_fewer"], low=0, high=9999,
        )
        self._fix_meter(
            stock,
            gate="hunt.return_depoison_enabled", gate_default=True,
            label=self.t["return_depoison_count"], name="hunt.return_depoison_count",
            default=1, suffix=self.t["count_or_fewer"], low=0, high=999,
        )
        self._fix_meter(
            stock,
            gate="hunt.return_satiety_enabled", gate_default=True,
            label=self.t["return_satiety"], name="hunt.return_satiety_below",
            default=25, suffix=self.t["pct_or_less"],
        )
        self._fix_meter(
            stock,
            gate="hunt.return_weight_enabled", gate_default=True,
            label=self.t["weight_gauge"], name="hunt.return_weight_above",
            default=85, suffix=self.t["pct_or_more"],
        )
        self._fix_flag(stock, self.t["return_supplies"], "hunt.return_no_supplies", True)

        summary = self._attack_card(body, self.t["settings_summary"])
        summary.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=4)
        summary.rowconfigure(0, weight=1)
        summary.columnconfigure(0, weight=1)
        summary_wrap = ttk.Frame(summary)
        summary_wrap.grid(row=0, column=0, sticky="nsew")
        summary_wrap.rowconfigure(0, weight=1)
        summary_wrap.columnconfigure(0, weight=1)
        self.fix_summary = tk.Text(
            summary_wrap, wrap="word", width=1, height=6, relief="flat", borderwidth=0,
            highlightthickness=0, background=ui_theme.SURFACE, foreground=ui_theme.TEXT,
            font=FONT_BODY, padx=2, pady=2, cursor="arrow",
        )
        self.fix_summary.grid(row=0, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(summary_wrap, command=self.fix_summary.yview)

        def _summary_scroll(*args: str) -> None:
            summary_scroll.set(*args)
            try:
                first = float(args[0])
                last = float(args[1])
            except (IndexError, TypeError, ValueError):
                return
            if last - first < 0.995:
                summary_scroll.grid(row=0, column=1, sticky="ns")
            else:
                summary_scroll.grid_remove()

        self.fix_summary.configure(yscrollcommand=_summary_scroll)
        self.fix_summary.bind(
            "<MouseWheel>",
            lambda event: self.fix_summary.yview_scroll(int(-event.delta / 120), "units"),
        )
        _configure_summary_text(self.fix_summary)
        head_font = FONT_BODY
        if isinstance(head_font, tuple) and len(head_font) >= 2:
            head_font = (head_font[0], head_font[1], "bold")
        self.fix_summary.tag_configure(
            "head", foreground=ui_theme.TEXT, font=head_font, spacing1=2, spacing3=2,
        )
        self.fix_summary.configure(state="disabled")
        for name, variable in self.vars.items():
            if name.startswith("recovery.") or name.startswith("hunt.return_"):
                variable.trace_add("write", self._refresh_fix_summary)
        self._refresh_fix_summary()

    def _build_hp_and_inventory(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        page.columnconfigure(0, weight=5, minsize=ui_theme.scaled(420, 220))
        page.columnconfigure(1, weight=4, minsize=ui_theme.scaled(320, 180))
        page.rowconfigure(0, weight=1)
        left = ttk.Frame(page, style="Page.TFrame")
        right = ttk.Frame(page, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_hp_action_order(left)
        self._build_fix_inventory(right)

    def _build_hp_action_order(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        card = self._attack_card(page, self.t["hp_action_order"])
        card.pack(fill="both", expand=True)
        ttk.Label(
            card, text=self.t["hp_action_note"], justify="left", wraplength=420,
        ).pack(anchor="w", pady=(0, 4))
        self._hp_actions = self._normalize_hp_actions_for_ui(None)
        self._hp_action_rows: dict[str, tuple[tk.BooleanVar, tk.IntVar]] = {}
        self._hp_action_hotbar_labels: dict[str, ttk.Label] = {}
        self._hp_inventory_keys: tuple[str, ...] | None = None
        self._hp_user_item_ids: set[str] = set()
        self._hp_removed_item_ids: set[str] = set()
        holder = ttk.Frame(card)
        holder.pack(fill="both", expand=True, pady=(8, 4))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        canvas = tk.Canvas(holder, highlightthickness=0, bd=0, background="#ffffff")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        self._hp_action_body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=self._hp_action_body, anchor="nw")

        def _sync_scroll(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        self._hp_action_body.bind("<Configure>", _sync_scroll)
        canvas.bind("<Configure>", _sync_width)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self._hp_action_canvas = canvas
        self._rebuild_hp_action_rows()
        self._refresh_fix_summary()

    def _build_fix_inventory(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        card = self._attack_card(page, self.t["fix_inventory"])
        card.pack(fill="both", expand=True)
        ttk.Label(
            card, text=self.t["inventory_live_note"], wraplength=360, justify="left",
        ).pack(anchor="w")
        ttk.Label(
            card, text=self.t["inventory_hp_hint"], wraplength=360, justify="left",
        ).pack(anchor="w", pady=(2, 0))
        head = ttk.Frame(card)
        head.pack(fill="x", pady=(4, 6))
        self.fix_inventory_status = ttk.Label(head, text=self.t["inventory_empty"])
        self.fix_inventory_status.pack(side="left", fill="x", expand=True)
        self.fix_inventory_refresh_btn = ttk.Button(
            head,
            text=self.t["inventory_refresh"],
            command=self._on_inventory_refresh,
        )
        self.fix_inventory_refresh_btn.pack(side="right")
        table = ttk.Frame(card)
        table.pack(fill="both", expand=True)
        columns = ("slot", "name", "count")
        self.fix_inventory_tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Grid.Treeview",
        )
        headings = {
            "slot": self.t.get("debug_slot", "Slot"),
            "name": self.t.get("item_name", self.t.get("debug_name", "Item")),
            "count": self.t.get("debug_count", "Count"),
        }
        widths = {"slot": 48, "name": 220, "count": 64}
        for column in columns:
            self.fix_inventory_tree.heading(column, text=headings[column])
            self.fix_inventory_tree.column(
                column,
                width=widths[column],
                minwidth=40,
                stretch=column == "name",
                anchor="w" if column == "name" else "center",
            )
        _mount_vertical_scroll(table, self.fix_inventory_tree)
        _enable_bbox_grid(self.fix_inventory_tree)
        self.fix_inventory_tree.bind("<Double-1>", self._on_inventory_add_hp)
        ttk.Button(
            card,
            text=self.t["hp_action_add_item"],
            command=self._add_selected_inventory_hp_item,
        ).pack(anchor="w", pady=(8, 0))
        self._fix_inventory_stamp = None
        self._fix_inventory_raw: list[dict] = []
        self._fix_inventory_scanning = False
        self._refresh_fix_inventory()

    def _on_inventory_refresh(self) -> None:
        if getattr(self, "_fix_inventory_scanning", False):
            return
        self._fix_inventory_scanning = True
        button = getattr(self, "fix_inventory_refresh_btn", None)
        status = getattr(self, "fix_inventory_status", None)
        if button is not None:
            button.configure(state="disabled")
        if status is not None:
            status.configure(text=self.t["inventory_refreshing"])

        def work() -> None:
            snap = None
            error = ""
            try:
                from app._03_world.inventory_listen_reader import shared_inventory

                snap = shared_inventory().snapshot()
            except Exception as exc:
                error = str(exc)
            try:
                self.after(0, lambda: self._finish_inventory_refresh(snap, error))
            except tk.TclError:
                self._fix_inventory_scanning = False

        threading.Thread(target=work, name="inventory-refresh", daemon=True).start()

    def _inventory_rows_from_snapshot(self, snap: object) -> list[dict]:
        raw = snap.get("items") if isinstance(snap, dict) else None
        if not isinstance(raw, list):
            return []
        rows: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "slot": item.get("slot"),
                    "id": item.get("id"),
                    "name": item.get("name") or item.get("name_tw") or "—",
                    "tw": item.get("name_tw") or "—",
                    "name_tw": item.get("name_tw") or "",
                    "name_cn": item.get("name_cn") or "",
                    "name_en": item.get("name_en") or "",
                    "count": item.get("count"),
                    "kind": item.get("kind"),
                    "fmt": item.get("fmt") or "—",
                }
            )
        return rows

    def _publish_inventory_table(self, items: list[dict]) -> None:
        controller = getattr(getattr(self.app, "coordinator", None), "controller", None)
        if controller is None:
            return
        lock = getattr(controller, "_debug_lock", None)
        if lock is None:
            return
        with lock:
            snap = getattr(controller, "_debug_snapshot", None)
            if not isinstance(snap, dict):
                snap = {}
            updated = dict(snap)
            tables = dict(updated.get("tables") or {})
            tables["inventory"] = list(items)
            updated["tables"] = tables
            controller._debug_snapshot = updated

    def _finish_inventory_refresh(self, snap: object, error: str) -> None:
        button = getattr(self, "fix_inventory_refresh_btn", None)
        status = getattr(self, "fix_inventory_status", None)
        have_list = isinstance(snap, dict) and isinstance(snap.get("items"), list)
        items = self._inventory_rows_from_snapshot(snap) if have_list else []
        if have_list:
            self._publish_inventory_table(items)
            self._hp_inventory_keys = None
            self._paint_fix_inventory(items, force=True)
        else:
            self._paint_fix_inventory(None, force=True)
            if status is not None:
                status.configure(
                    text=self.t["inventory_refresh_failed"].format(
                        error=error or self.t["inventory_empty"]
                    )
                )
        self._fix_inventory_scanning = False
        if button is not None:
            button.configure(state="normal")

    def _refresh_fix_inventory(self, *, force: bool = False) -> None:
        if getattr(self, "_fix_inventory_scanning", False) and not force:
            return
        try:
            snapshot = self.app.coordinator.controller.debug_snapshot()
        except Exception:
            snapshot = {}
        tables = snapshot.get("tables") if isinstance(snapshot, dict) else {}
        if not isinstance(tables, dict):
            tables = {}
        items = [
            item for item in list(tables.get("inventory") or [])
            if isinstance(item, dict)
        ]
        weight = ""
        for row in list(tables.get("player") or []):
            if isinstance(row, dict) and row.get("field") == "weight":
                weight = str(row.get("value") or "").strip()
                break
        if not weight:
            player = snapshot.get("player") if isinstance(snapshot, dict) else {}
            if isinstance(player, dict):
                weight = str(player.get("weight_text") or "").strip()
        self._paint_fix_inventory(items, weight=weight, force=force)

    def _paint_fix_inventory(
        self,
        items: list[dict] | None,
        *,
        weight: str = "",
        force: bool = False,
    ) -> None:
        tree = getattr(self, "fix_inventory_tree", None)
        status = getattr(self, "fix_inventory_status", None)
        if tree is None or status is None:
            return
        if items is None:
            items = list(getattr(self, "_fix_inventory_raw", []) or [])
        self._fix_inventory_raw = list(items)

        def cell(value: object) -> str:
            if value is None or value == "":
                return "—"
            return str(value)

        from manmabot_v1.localized_names import inventory_name_for_ui

        language = str(getattr(self.app, "language", "") or "ko")
        rows = []
        for item in items:
            rows.append(
                (
                    cell(item.get("slot")),
                    inventory_name_for_ui(
                        name=str(item.get("name") or ""),
                        name_tw=str(item.get("name_tw") or item.get("tw") or ""),
                        name_cn=str(item.get("name_cn") or ""),
                        name_en=str(item.get("name_en") or ""),
                        language=language,
                    ),
                    cell(item.get("count")),
                )
            )
        stamp = (tuple(rows), weight)
        if not force and stamp == getattr(self, "_fix_inventory_stamp", None):
            self._sync_hp_actions_from_inventory(items)
            return
        self._fix_inventory_stamp = stamp
        selected = tree.selection()
        yview = tree.yview()
        tree.delete(*tree.get_children())
        for index, row in enumerate(rows):
            tree.insert("", "end", iid=str(index), values=row)
        if selected and selected[0] in tree.get_children():
            tree.selection_set(selected)
        if rows and yview and not force:
            try:
                tree.yview_moveto(yview[0])
            except tk.TclError:
                pass
        if rows:
            line = self.t["inventory_count_line"].format(n=len(rows))
            if weight and weight != "—":
                line = f"{line}  ·  {self.t['weight_gauge']}: {weight}"
            status.configure(text=line)
        else:
            status.configure(text=self.t["inventory_empty"])
        self._sync_hp_actions_from_inventory(items)

    def _normalize_hp_actions_for_ui(self, raw: Any, **kwargs: Any) -> list[dict]:
        extras = kwargs.pop("extra_item_keys", None)
        return normalize_hp_actions(
            raw,
            extra_item_keys=extras,
            fill_catalog=False,
            **kwargs,
        )

    def _sync_hp_actions_from_inventory(self, items: list[dict]) -> None:
        """No-op: bag rows are not auto-inserted into the HP order."""
        return

    def _inventory_status(self, text: str) -> None:
        status = getattr(self, "fix_inventory_status", None)
        if status is not None and text:
            status.configure(text=text)

    def _selected_inventory_item(
        self, event: tk.Event | None = None
    ) -> dict | None:
        tree = getattr(self, "fix_inventory_tree", None)
        raw = list(getattr(self, "_fix_inventory_raw", []) or [])
        if tree is None:
            return None
        iid = ""
        if event is not None:
            try:
                iid = str(tree.identify_row(event.y) or "")
            except tk.TclError:
                iid = ""
            if iid:
                tree.selection_set(iid)
                tree.focus(iid)
        if not iid:
            selected = tree.selection()
            iid = str(selected[0]) if selected else ""
        if not iid:
            return None
        try:
            index = int(iid)
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= len(raw):
            return None
        item = raw[index]
        return item if isinstance(item, dict) else None

    def _on_inventory_add_hp(self, event: tk.Event | None = None) -> None:
        self._add_selected_inventory_hp_item(event)

    def _add_selected_inventory_hp_item(
        self, event: tk.Event | None = None
    ) -> None:
        from manmabot_v1.hp_actions import inventory_item_key_for_hp_action

        item = self._selected_inventory_item(event)
        if item is None:
            self._inventory_status(self.t.get("hp_action_select_item", ""))
            return
        key = inventory_item_key_for_hp_action(item)
        if not key:
            self._inventory_status(self.t.get("hp_action_not_restore", ""))
            return
        self._add_hp_item_action(key, user_added=True)

    def _add_hp_item_action(self, item_key: str, *, user_added: bool = False) -> None:
        key = str(item_key or "").strip()
        if not key:
            return
        action_id = item_action_id(key)
        if not hasattr(self, "_hp_user_item_ids"):
            self._hp_user_item_ids = set()
        if not hasattr(self, "_hp_removed_item_ids"):
            self._hp_removed_item_ids = set()
        if not hasattr(self, "_hp_actions"):
            self._hp_actions = self._normalize_hp_actions_for_ui(None)
        self._snapshot_hp_actions_from_rows()
        if user_added:
            self._hp_user_item_ids.add(action_id)
            self._hp_removed_item_ids.discard(action_id)
        existing = next(
            (
                row
                for row in self._hp_actions
                if str(row.get("id") or "") == action_id
            ),
            None,
        )
        if existing is not None:
            existing["enabled"] = True
            self._hp_actions = self._normalize_hp_actions_for_ui(self._hp_actions)
            self._rebuild_hp_action_rows()
            self._refresh_fix_summary()
            self._inventory_status(
                self.t.get("hp_action_already", "").format(
                    name=self._hp_action_label(action_id)
                )
            )
            return
        insert_at = len(self._hp_actions)
        for index, row in enumerate(self._hp_actions):
            if str(row.get("id") or "") in {"teleport", "safe_zone"}:
                insert_at = index
                break
        self._hp_actions.insert(
            insert_at,
            {"id": action_id, "enabled": True, "hp_below": 55},
        )
        self._hp_actions = self._normalize_hp_actions_for_ui(self._hp_actions)
        if not any(str(row.get("id") or "") == action_id for row in self._hp_actions):
            # Normalize dropped the row — keep it explicitly.
            self._hp_actions.insert(
                min(insert_at, len(self._hp_actions)),
                {"id": action_id, "enabled": True, "hp_below": 55},
            )
        self._rebuild_hp_action_rows()
        self._refresh_fix_summary()
        self._inventory_status(
            self.t.get("hp_action_added", "").format(
                name=self._hp_action_label(action_id)
            )
        )

    def _remove_hp_action(self, index: int) -> None:
        if index < 0 or index >= len(self._hp_actions):
            return
        action_id = str(self._hp_actions[index].get("id") or "")
        if action_id in FIXED_HP_ACTION_IDS or not is_item_action(action_id):
            return
        self._snapshot_hp_actions_from_rows()
        self._hp_user_item_ids.discard(action_id)
        self._hp_removed_item_ids.add(action_id)
        self._hp_actions = [
            row for row in self._hp_actions if str(row.get("id") or "") != action_id
        ]
        self._hp_actions = self._normalize_hp_actions_for_ui(self._hp_actions)
        self._rebuild_hp_action_rows()
        self._refresh_fix_summary()

    def _hp_action_label(self, action_id: str) -> str:
        if is_item_action(action_id):
            key = item_key_from_action(action_id)
            shown = memory_name_for_ui(key, self.app.language) if key else ""
            return shown or key or action_id
        return self.t.get(f"hp_action_{action_id}", action_id)

    def _snapshot_hp_actions_from_rows(self) -> None:
        updated: list[dict[str, object]] = []
        for row in self._hp_actions:
            key = str(row.get("id"))
            pair = self._hp_action_rows.get(key)
            if pair is None:
                updated.append(dict(row))
                continue
            enabled, percent = pair
            try:
                hp_below = max(5, min(95, int(percent.get())))
            except (TypeError, ValueError, tk.TclError):
                hp_below = int(row.get("hp_below", 30))
            updated.append(
                {
                    "id": key,
                    "enabled": bool(enabled.get()),
                    "hp_below": hp_below,
                }
            )
        self._hp_actions = self._normalize_hp_actions_for_ui(updated)

    def _rebuild_hp_action_rows(self) -> None:
        if not hasattr(self, "_hp_action_body"):
            return
        for child in self._hp_action_body.winfo_children():
            child.destroy()
        self._hp_action_rows = {}
        self._hp_action_hotbar_labels = {}
        body = self._hp_action_body
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        for column in (2, 3, 4, 5, 6):
            body.columnconfigure(column, weight=0)
        compact = {"width": 4, "padding": (2, 0)}
        for index, row in enumerate(self._hp_actions):
            key = str(row["id"])
            enabled = tk.BooleanVar(self, value=bool(row.get("enabled", True)))
            percent = tk.IntVar(self, value=int(row.get("hp_below", 30)))
            ttk.Checkbutton(body, variable=enabled).grid(
                row=index, column=0, sticky="w", pady=2,
            )
            ttk.Label(body, text=self._hp_action_label(key)).grid(
                row=index, column=1, sticky="ew", padx=(4, 6),
            )
            hotbar = ttk.Label(body, text=self._hp_action_hotbar_text(key))
            hotbar.grid(row=index, column=2, sticky="w", padx=(0, 8))
            self._hp_action_hotbar_labels[key] = hotbar
            spin = ttk.Spinbox(body, from_=5, to=95, width=4, textvariable=percent)
            spin.grid(row=index, column=3, sticky="w")
            ttk.Label(body, text=self.t["pct_or_less"]).grid(
                row=index, column=4, sticky="w", padx=(2, 4),
            )
            moves = ttk.Frame(body)
            up = ttk.Button(
                moves,
                text=self.t["hp_action_up"],
                command=lambda i=index: self._move_hp_action(i, -1),
                **compact,
            )
            down = ttk.Button(
                moves,
                text=self.t["hp_action_down"],
                command=lambda i=index: self._move_hp_action(i, 1),
                **compact,
            )
            up.pack(side="left", padx=(0, 2))
            down.pack(side="left")
            moves.grid(row=index, column=5, sticky="e", pady=1)
            if is_item_action(key):
                ttk.Button(
                    body,
                    text=self.t["hp_action_remove"],
                    command=lambda i=index: self._remove_hp_action(i),
                    **compact,
                ).grid(row=index, column=6, sticky="e", padx=(4, 0), pady=1)
            if index == 0:
                up.configure(state="disabled")
            if index == len(self._hp_actions) - 1:
                down.configure(state="disabled")
            enabled.trace_add("write", self._on_hp_action_change)
            percent.trace_add("write", self._on_hp_action_change)
            self._hp_action_rows[key] = (enabled, percent)
        body.after_idle(self._lock_hp_action_columns)

    def _hp_action_hotbar_source(self) -> tuple[object | None, dict]:
        layout = self._value("magic", "hotbar_layout", {})
        if not isinstance(layout, dict) or not layout:
            layout = getattr(self.app.profile, "hotbar_layout", {}) or {}
        if not isinstance(layout, dict):
            layout = {}
        world = None
        # Prefer live memory 24-slot snap (works even before debug tables fill).
        try:
            from app._03_world.hotbar_listen_reader import shared_hotbar

            snap = shared_hotbar().snapshot()
            if isinstance(snap, dict) and isinstance(snap.get("slots"), list):
                world = type("HotbarWorld", (), {"last_hotbar": snap})()
        except Exception:
            world = None
        if world is None:
            try:
                snapshot = self.app.coordinator.controller.debug_snapshot()
            except Exception:
                snapshot = {}
            tables = snapshot.get("tables") if isinstance(snapshot, dict) else {}
            hotbar = tables.get("hotbar") if isinstance(tables, dict) else None
            if isinstance(hotbar, list) and hotbar:
                slots: list[dict] = []
                for row in hotbar:
                    if not isinstance(row, dict):
                        continue
                    box_text = str(row.get("box") or "").upper().replace("F", "")
                    key = str(row.get("key") or "").strip().lower()
                    try:
                        box = int(box_text)
                    except (TypeError, ValueError):
                        box = 0
                    slots.append(
                        {
                            "name": row.get("name") or row.get("label") or "",
                            "label": row.get("label") or "",
                            "count": row.get("count"),
                            "box": box,
                            "key": key,
                        }
                    )
                world = type("HotbarWorld", (), {"last_hotbar": {"slots": slots}})()
        return world, layout

    def _hp_action_role_id(self, action_id: str) -> str:
        key = str(action_id or "").strip()
        return {
            "heal": "heal",
            "teleport": "teleport",
            "mother_tree": "mother_tree",
            "safe_zone": "talking_scroll",
        }.get(key, "")

    def _hp_action_setup_slot(
        self, role: str
    ) -> tuple[int, str] | None:
        """Fallback: Setup / magic.spell_slots binding when live bar misses."""
        if not role:
            return None
        slots = self._value("magic", "spell_slots", {})
        if not isinstance(slots, dict) or not slots:
            slots = getattr(self.app.profile, "spell_slots", {}) or {}
        if not isinstance(slots, dict):
            return None
        spec = slots.get(role)
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            return None
        try:
            box = int(spec.get("box") or 0)
        except (TypeError, ValueError):
            box = 0
        key = str(spec.get("key") or "").strip().lower()
        if box in (1, 2, 3) and key:
            return box, key
        return None

    def _hp_action_hotbar_text(self, action_id: str) -> str:
        from manmabot_v1.hp_actions import is_item_action, item_key_from_action

        try:
            from app._04_decision.hp_actions import (
                find_hp_restore_hotbar,
                format_hotbar_binding,
            )
        except Exception:
            return self.t["hp_action_hotbar_none"]

        world, layout = self._hp_action_hotbar_source()
        snap = getattr(world, "last_hotbar", None) if world is not None else None
        slot: tuple[int, str] | None = None
        extra = ""

        if is_item_action(action_id):
            item_key = item_key_from_action(action_id)
            slot = find_hp_restore_hotbar(world, item_key, layout=layout)
            if slot is not None and isinstance(snap, dict):
                for raw in snap.get("slots") or []:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        box = int(raw.get("box") or 0)
                    except (TypeError, ValueError):
                        box = 0
                    key = str(raw.get("key") or "").strip().lower()
                    if (box, key) != slot:
                        continue
                    count = raw.get("count")
                    try:
                        count_i = int(count) if count is not None else None
                    except (TypeError, ValueError):
                        count_i = None
                    if count_i is not None:
                        extra = f" ×{count_i}"
                    break
        else:
            role = self._hp_action_role_id(action_id)
            if role:
                try:
                    from manmabot_v1.hotbar.inspect import find_role_on_hotbar

                    if isinstance(snap, dict):
                        slot = find_role_on_hotbar(snap, role)
                except Exception:
                    slot = None
                if slot is None:
                    slot = self._hp_action_setup_slot(role)

        shown = format_hotbar_binding(slot)
        if shown:
            return f"{shown}{extra}"
        return self.t["hp_action_hotbar_none"]

    def _refresh_hp_action_hotbar_keys(self) -> None:
        labels = getattr(self, "_hp_action_hotbar_labels", None)
        if not labels:
            return
        for action_id, label in labels.items():
            try:
                label.configure(text=self._hp_action_hotbar_text(action_id))
            except tk.TclError:
                continue

    def _lock_hp_action_columns(self) -> None:
        """Keep spin boxes and the compact reorder pair visible on the right."""
        body = getattr(self, "_hp_action_body", None)
        if body is None:
            return
        try:
            body.update_idletasks()
        except tk.TclError:
            return
        for column in (0, 2, 3, 4, 5, 6):
            width = 0
            for child in body.grid_slaves(column=column):
                width = max(width, int(child.winfo_reqwidth()))
            if width:
                body.columnconfigure(column, minsize=width, weight=0)
        body.columnconfigure(1, minsize=0, weight=1)

    def _on_hp_action_change(self, *_args: object) -> None:
        self._snapshot_hp_actions_from_rows()
        self._refresh_fix_summary()

    def _move_hp_action(self, index: int, delta: int) -> None:
        self._snapshot_hp_actions_from_rows()
        dest = index + delta
        if dest < 0 or dest >= len(self._hp_actions):
            return
        self._hp_actions[index], self._hp_actions[dest] = (
            self._hp_actions[dest],
            self._hp_actions[index],
        )
        self._rebuild_hp_action_rows()
        self._refresh_fix_summary()

    def _load_hp_actions(self) -> None:
        potion = 55
        escape = 30
        try:
            potion = int(self.vars["recovery.hp_potion_below"].get())
        except (KeyError, TypeError, ValueError, tk.TclError):
            pass
        try:
            escape = int(self.vars["recovery.escape_hp_below"].get())
        except (KeyError, TypeError, ValueError, tk.TclError):
            pass
        loaded = self._normalize_hp_actions_for_ui(
            self._value("recovery", "hp_actions", None),
            potion_pct=potion,
            escape_pct=escape,
            use_heal=bool(self.vars.get("recovery.use_heal", tk.BooleanVar(value=True)).get())
            if "recovery.use_heal" in self.vars
            else True,
            use_potion=bool(self.vars["recovery.use_hp_potion"].get())
            if "recovery.use_hp_potion" in self.vars
            else True,
        )
        trimmed: list[dict] = []
        for row in loaded:
            rid = str(row.get("id") or "")
            if rid in FIXED_HP_ACTION_IDS or not is_item_action(rid) or row.get("enabled"):
                trimmed.append(row)
        self._hp_actions = self._normalize_hp_actions_for_ui(trimmed)
        self._hp_user_item_ids = {
            str(row.get("id") or "")
            for row in self._hp_actions
            if is_item_action(str(row.get("id") or ""))
        }
        self._hp_removed_item_ids = set()
        self._hp_inventory_keys = None
        self._rebuild_hp_action_rows()
        self._sync_hp_actions_from_inventory(list(getattr(self, "_fix_inventory_raw", []) or []))

    def _refresh_fix_summary(self, *_args: object) -> None:
        box = getattr(self, "fix_summary", None)
        if box is None:
            return

        def state(name: str) -> str:
            return self.t["summary_on"] if self._summary_on(name) else self.t["summary_off"]

        def gate_line(label: str, gate: str, detail: str) -> str:
            if self._summary_on(gate):
                return f"{label}  {detail}"
            return f"{label}: {self.t['summary_off']}"

        blocks: list[tuple[str, list[str]]] = []

        actions = list(getattr(self, "_hp_actions", None) or [])
        hp_lines = [
            f"{self._hp_action_label(str(row.get('id')))}  ≤ {int(row.get('hp_below', 0))}%"
            for row in actions
            if row.get("enabled")
        ]
        if actions and not hp_lines:
            hp_lines.append(self.t["summary_off"])
        if hp_lines:
            blocks.append((self.t["hp_action_order"], hp_lines))

        mp_detail = f"≤ {self._summary_number('recovery.mp_potion_below', 30)}%"
        if self._summary_on("recovery.use_mp_potion"):
            mp_detail = f"{mp_detail} · {self.t['use_mp_potion']}"
        blocks.append((
            self.t["fix_recovery"],
            [
                gate_line("MP", "recovery.mp_recover_enabled", mp_detail),
                f"{self.t['resurrect']}: {state('recovery.resurrect_if_dead')}",
                f"{self.t['resume_login']}: {state('recovery.resume_after_relogin')}",
                f"{self.t['retries']}: {self._summary_number('recovery.max_retries', 3)}",
            ],
        ))
        blocks.append((
            self.t["fix_return"],
            [
                gate_line(
                    self.t["return_mp"],
                    "hunt.return_mp_enabled",
                    f"≤ {self._summary_number('hunt.return_mp_below', 15)}%",
                ),
                gate_line(
                    self.t["return_idle"],
                    "hunt.return_idle_enabled",
                    f"{self._summary_number('hunt.return_idle_seconds', 60)} {self.t['seconds_when']}",
                ),
            ],
        ))
        blocks.append((
            self.t["fix_return_supplies"],
            [
                gate_line(
                    self.t["return_potion_count"],
                    "hunt.return_potion_enabled",
                    f"≤ {self._summary_number('hunt.return_potion_count', 20)}",
                ),
                gate_line(
                    self.t["return_arrow_count"],
                    "hunt.return_arrow_enabled",
                    f"≤ {self._summary_number('hunt.return_arrow_count', 300)}",
                ),
                gate_line(
                    self.t["return_depoison_count"],
                    "hunt.return_depoison_enabled",
                    f"≤ {self._summary_number('hunt.return_depoison_count', 1)}",
                ),
                gate_line(
                    self.t["return_satiety"],
                    "hunt.return_satiety_enabled",
                    f"≤ {self._summary_number('hunt.return_satiety_below', 25)}%",
                ),
                gate_line(
                    self.t["weight_gauge"],
                    "hunt.return_weight_enabled",
                    f"≥ {self._summary_number('hunt.return_weight_above', 85)}%",
                ),
                f"{self.t['return_supplies']}: {state('hunt.return_no_supplies')}",
            ],
        ))
        teleport_lines = [
            f"{self.t['random_teleport']}: {state('recovery.random_teleport_enabled')}",
        ]
        if self._summary_on("recovery.random_teleport_enabled"):
            teleport_lines.append(
                f"{self.t['teleport_player']}: {state('recovery.teleport_on_player')}"
            )
            teleport_lines.append(
                gate_line(
                    self.t["teleport_surrounded"],
                    "recovery.teleport_when_surrounded",
                    (
                        f"{self._summary_number('recovery.teleport_surround_count', 4)} "
                        f"{self.t['teleport_surround_count_suffix']}"
                    ),
                )
            )
        blocks.append((self.t["fix_teleport"], teleport_lines))

        box.configure(state="normal")
        box.delete("1.0", "end")
        for index, (title, lines) in enumerate(blocks):
            if index:
                box.insert("end", "\n", "body")
            box.insert("end", title + "\n", "head")
            for line in lines:
                _insert_summary_bullet(box, line)
        box.configure(state="disabled")
        box.yview_moveto(0)

    def _build_magic(self) -> None:
        pages = self._nested(
            self.pages["magic"], ("general", "individual"), store_as="_magic_tabs",
        )
        magic_tabs = getattr(self, "_magic_tabs", None)
        if magic_tabs is not None:
            magic_tabs.bind(
                "<<NotebookTabChanged>>", self._on_magic_tab_changed, add="+",
            )
        self._build_magic_general(pages["general"])
        self._build_magic_individual(pages["individual"])

    def _magic_percent_row(
        self, parent: tk.Misc, label: str, name: str, default: int, *, indent: int = 0,
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2, padx=(indent, 0))
        ttk.Label(row, text=label).pack(side="left")
        ttk.Label(row, text="%").pack(side="right")
        self._attack_spin(row, name, default, 0, 100).pack(side="right", padx=(8, 4))

    def _build_magic_general(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        body = ttk.Frame(page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3, minsize=ui_theme.scaled(480, 260))
        body.columnconfigure(1, weight=1, minsize=ui_theme.scaled(220, 160))
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Page.TFrame")
        right = ttk.Frame(body, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew")

        general = self._attack_card(left, self.t["magic_general_settings"])
        general.pack(fill="x", pady=(0, 8))
        self._magic_percent_row(general, self.t["heal_until"], "magic.heal_until_hp_pct", 50)
        self._magic_percent_row(general, self.t["reserve_mp"], "magic.spell_reserve_pct", 20)
        self._attack_flag(general, self.t["disable_combat"], "magic.disable_in_combat", False)
        self._attack_flag(general, self.t["stop_mp"], "magic.stop_below_mp", False)
        self._magic_percent_row(
            general, "MP <", "magic.stop_below_mp_pct", 20, indent=22,
        )
        self._bind_gate("magic.stop_below_mp", "magic.stop_below_mp_pct")

        extra = self._attack_card(left, self.t["magic_extra"])
        extra.pack(fill="x")
        self._attack_flag(extra, self.t["buff_after_death"], "magic.buff_after_death", True)
        self._attack_inline(
            extra, "magic.cast_delay", True, [
                ("check", self.t["magic_cast_delay"]),
                ("spin", ("magic.cast_delay_min_ms", 80, 0, 5000)),
                ("text", "~"),
                ("spin", ("magic.cast_delay_max_ms", 180, 0, 5000)),
                ("text", self.t["ms_unit"]),
            ],
        )
        self._attack_flag(extra, self.t["buff_after_combat"], "magic.buff_after_combat", True)
        self._attack_flag(extra, self.t["town_general_only"], "magic.town_general_only", True)

        summary = self._attack_card(right, self.t["settings_summary"])
        summary.pack(fill="both", expand=True)
        self.magic_summary = tk.Text(
            summary, wrap="word", width=24, height=ui_theme.scaled(16, 8), relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.magic_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.magic_summary)
        self.magic_summary.configure(state="disabled")
        for name, variable in self.vars.items():
            if name.startswith("magic.") and not name.startswith("magic.skill_"):
                variable.trace_add("write", self._refresh_magic_summary)
        self._refresh_magic_summary()

    def _refresh_magic_summary(self, *_args: object) -> None:
        if not hasattr(self, "magic_summary"):
            return
        hp = self._summary_number("magic.heal_until_hp_pct", 50)
        reserve = self._summary_number("magic.spell_reserve_pct", 20)
        stop_pct = self._summary_number("magic.stop_below_mp_pct", 20)
        low = self._summary_number("magic.cast_delay_min_ms", 80)
        high = self._summary_number("magic.cast_delay_max_ms", 180)

        def state(name: str) -> str:
            return self.t["summary_on"] if self._summary_on(name) else self.t["summary_off"]

        lines = [
            f"{self.t['heal_until']}: {hp}%",
            f"{self.t['reserve_mp']}: {reserve}%",
            f"{self.t['disable_combat']}: {state('magic.disable_in_combat')}",
            f"{self.t['stop_mp_summary'].format(pct=stop_pct)}: {state('magic.stop_below_mp')}",
            f"{self.t['buff_after_death']}: {state('magic.buff_after_death')}",
            f"{self.t['magic_delay_summary']}: {low} ~ {high} {self.t['ms_unit']}"
            if self._summary_on("magic.cast_delay")
            else f"{self.t['magic_delay_summary']}: {self.t['summary_off']}",
            f"{self.t['buff_after_combat']}: {state('magic.buff_after_combat')}",
            f"{self.t['town_general_only']}: {state('magic.town_general_only')}",
        ]
        box = self.magic_summary
        box.configure(state="normal", height=max(len(lines), 1))
        box.delete("1.0", "end")
        for line in lines:
            _insert_summary_bullet(box, line)
        box.configure(state="disabled")

    def _magic_icon(self, icon: Path | None, key: str) -> tk.PhotoImage:
        cache = getattr(self, "_magic_icons", None)
        if cache is None:
            self._magic_icons = {}
            cache = self._magic_icons
        photo = cache.get(key)
        if photo is not None:
            return photo
        from PIL import Image, ImageTk

        if icon is not None and icon.is_file():
            image = Image.open(icon).convert("RGBA")
            image = image.resize((28, 28), Image.Resampling.LANCZOS)
        else:
            image = Image.new("RGBA", (28, 28), (219, 234, 254, 255))
        photo = ImageTk.PhotoImage(image, master=self)
        cache[key] = photo
        return photo

    def _build_magic_individual(self, page: ttk.Frame) -> None:
        page.configure(style="Page.TFrame")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(
            page, text=self.t["individual_magic"], style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        body = ttk.Frame(page, style="Page.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(2, weight=1)

        picker = ttk.Frame(body, style="Page.TFrame")
        picker.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(picker, text=self.t["magic_class"]).pack(side="left")
        self._magic_class_ids = {
            self.t[name]: name for name in ("elf", "mage", "knight", "royal")
        }
        self.magic_class_var = tk.StringVar(self, value="elf")
        self.magic_class_combo = ttk.Combobox(
            picker, state="readonly", width=12, values=list(self._magic_class_ids),
        )
        self.magic_class_combo.pack(side="left", padx=(8, 8))
        show_combobox_value(self.magic_class_combo, self.t["elf"], list(self._magic_class_ids))
        self.magic_class_combo.bind("<<ComboboxSelected>>", self._on_magic_class)
        ttk.Label(picker, text=self.t["class_magic_hint"]).pack(side="left")

        categories = ttk.Frame(body, style="Page.TFrame")
        categories.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        from manmabot_v1.skill_catalog import load_skill_catalog

        self._skill_catalog = load_skill_catalog()
        self.magic_category_var = tk.StringVar(self, value="attack_buff")
        self._magic_category_buttons: list[tuple[str, ttk.Button]] = []
        for key in _MAGIC_CATEGORIES:
            button = ttk.Button(
                categories,
                text=self._skill_catalog.category_label(key, self.app.language),
                command=lambda name=key: self._select_magic_category(name),
            )
            self._magic_category_buttons.append((key, button))
        self._reflow_magic_categories(categories)
        categories.bind("<Configure>", lambda event: self._reflow_magic_categories(categories, event.width))

        left = ttk.Frame(body, style="Page.TFrame")
        right = ttk.Frame(body, style="Page.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=2, column=1, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        # Column minimums (px) sized for KO/ZH headers + controls.
        # Name grows only when the viewport is wider than this sum.
        # enabled, icon, name, auto, priority
        self._magic_col_fixed = tuple(
            ui_theme.scaled(value, 36) for value in (72, 48, 220, 100, 96)
        )
        self._magic_name_col = 2
        self._magic_widths = list(self._magic_col_fixed)
        self._magic_content_width = int(sum(self._magic_widths))

        table_wrap = ttk.Frame(left, style="Page.TFrame")
        table_wrap.grid(row=0, column=0, sticky="nsew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        shell = tk.Frame(table_wrap, background=BORDER, highlightthickness=0, bd=0)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        # One sheet for title row + field rows so every column is the same grid.
        body_host = tk.Frame(shell, background="#ffffff", bd=0)
        body_host.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        body_host.rowconfigure(0, weight=1)
        body_host.columnconfigure(0, weight=1)

        self._magic_canvas = tk.Canvas(
            body_host, highlightthickness=0, borderwidth=0, background="#ffffff",
        )
        self._magic_canvas.grid(row=0, column=0, sticky="nsew")
        self._magic_sheet = tk.Frame(self._magic_canvas, background="#ffffff", bd=0)
        self._magic_header = self._magic_sheet
        self._magic_table = self._magic_sheet
        self._magic_window = self._magic_canvas.create_window(
            (0, 0), window=self._magic_sheet, anchor="nw",
        )

        self._magic_scroll = ttk.Scrollbar(
            table_wrap, orient="vertical", command=self._magic_canvas.yview,
        )
        self._magic_scroll.grid(row=0, column=1, sticky="ns")
        self._magic_hscroll = ttk.Scrollbar(
            table_wrap, orient="horizontal", command=self._magic_canvas.xview,
        )
        # Span under canvas + vscroll so the thumb maps to the full table width.
        self._magic_hscroll.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._magic_canvas.configure(
            yscrollcommand=self._magic_scroll.set,
            xscrollcommand=self._magic_hscroll.set,
        )

        def fit_magic_body(_event: object = None) -> None:
            self._update_magic_scrollregion()

        def fit_magic_viewport(event: tk.Event) -> None:
            self._fit_magic_table_width(max(int(event.width), 1))

        self._magic_sheet.bind("<Configure>", fit_magic_body)
        self._magic_canvas.bind("<Configure>", fit_magic_viewport)
        self._magic_canvas.bind("<MouseWheel>", self._magic_list_wheel)
        self._magic_canvas.bind("<Shift-MouseWheel>", self._magic_list_shift_wheel)
        self._apply_magic_column_widths(self._magic_content_width)
        for skill in self._skill_catalog.skills:
            key = skill.setting_key
            enabled = self._var(f"magic.skill_{key}", False, "bool")
            self._var(f"magic.skill_{key}_auto", True, "bool")
            self._var(f"magic.skill_{key}_priority", 1, "int")
            self._var(f"magic.skill_{key}_hotkey", "")
            enabled.trace_add("write", self._refresh_magic_pick_summary)

        tools = ttk.Frame(left)
        tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for text, command in (
            (self.t["select_all"], lambda: self._set_visible_magic(True)),
            (self.t["deselect_all"], lambda: self._set_visible_magic(False)),
            (self.t["reset_magic"], self._reset_visible_magic),
        ):
            ttk.Button(tools, text=text, command=command).pack(side="left", padx=(0, 4))

        summary = self._attack_card(right, self.t["settings_summary"])
        summary.pack(fill="both", expand=True)
        self.magic_pick_summary = tk.Text(
            summary, wrap="word", height=ui_theme.scaled(12, 7), relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.magic_pick_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.magic_pick_summary)
        self.magic_pick_summary.configure(state="disabled")
        self._select_magic_category("attack_buff")

    def _reflow_magic_categories(self, parent: ttk.Frame, width: int | None = None) -> None:
        buttons = [button for _key, button in self._magic_category_buttons]
        width = parent.winfo_width() if width is None else int(width)
        if width <= 1:
            for column, button in enumerate(buttons):
                button.grid(row=0, column=column, padx=(0, 4), pady=2, sticky="w")
            return
        x = 0
        row = 0
        column = 0
        for button in buttons:
            need = button.winfo_reqwidth() + 6
            if column and x + need > width:
                row += 1
                column = 0
                x = 0
            button.grid(row=row, column=column, padx=(0, 4), pady=2, sticky="w")
            column += 1
            x += need

    def _magic_list_wheel(self, event: tk.Event) -> str:
        self._magic_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _magic_list_shift_wheel(self, event: tk.Event) -> str:
        self._magic_canvas.xview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _fit_magic_table_width(self, viewport: int) -> None:
        # Never shrink below fixed column totals — hscroll reveals overflow fields.
        min_w = self._magic_table_min_width()
        target = max(int(viewport), min_w)
        if target != getattr(self, "_magic_content_width", None):
            self._apply_magic_column_widths(target)
        self._update_magic_scrollregion()

    def _update_magic_scrollregion(self) -> None:
        body = getattr(self, "_magic_canvas", None)
        sheet = getattr(self, "_magic_sheet", None)
        if body is None or sheet is None:
            return
        min_w = self._magic_table_min_width()
        planned = int(getattr(self, "_magic_content_width", 0) or 0)
        try:
            req_w = max(int(sheet.winfo_reqwidth()), 0)
            req_h = max(int(sheet.winfo_reqheight()), 1)
        except tk.TclError:
            req_w = 0
            req_h = 1
        # Content width is the full table (all fields), never the clipped viewport.
        content_w = max(planned, min_w, req_w)
        self._magic_content_width = content_w
        body.itemconfigure(self._magic_window, width=content_w)
        try:
            body.update_idletasks()
            bbox = body.bbox("all")
        except tk.TclError:
            bbox = None
        if bbox is not None:
            # Ensure scrollregion covers every column even if bbox is tight.
            x0, y0, x1, y1 = bbox
            body.configure(scrollregion=(x0, y0, max(x1, content_w), max(y1, req_h)))
        else:
            body.configure(scrollregion=(0, 0, content_w, req_h))

    def _on_magic_class(self, _event: object = None) -> None:
        class_id = self._magic_class_ids.get(self.magic_class_combo.get(), "elf")
        self.magic_class_var.set(class_id)
        self._show_magic_skills()

    def _select_magic_category(self, category: str) -> None:
        self.magic_category_var.set(category)
        for key, button in self._magic_category_buttons:
            button.configure(style="Accent.TButton" if key == category else "TButton")
        self._show_magic_skills()

    def _visible_magic_skills(self):
        class_id = str(self.magic_class_var.get() or "elf")
        category = str(self.magic_category_var.get() or "attack_buff")
        return self._skill_catalog.for_filter(class_id, category)

    def _magic_table_min_width(self) -> int:
        return int(sum(self._magic_col_fixed))

    def _magic_column_widths(self, available: int) -> list[int]:
        fixed = list(self._magic_col_fixed)
        widths = list(fixed)
        extra = max(0, int(available) - sum(fixed))
        if extra:
            widths[self._magic_name_col] = fixed[self._magic_name_col] + extra
        return widths

    def _apply_magic_column_widths(self, available: int) -> None:
        widths = self._magic_column_widths(max(int(available), self._magic_table_min_width()))
        self._magic_widths = widths
        self._magic_content_width = int(sum(widths))
        sheet = getattr(self, "_magic_sheet", None)
        if sheet is not None:
            for column, width in enumerate(widths):
                sheet.columnconfigure(column, minsize=width, weight=0, uniform="")
            try:
                sheet.configure(width=self._magic_content_width)
            except tk.TclError:
                pass
        for holder, column in getattr(self, "_magic_cell_refs", []):
            if 0 <= column < len(widths):
                try:
                    holder.configure(width=widths[column])
                except tk.TclError:
                    pass

    def _magic_cell(
        self,
        parent: tk.Misc,
        row: int,
        column: int,
        *,
        header: bool = False,
        zebra: bool = False,
    ) -> tk.Frame:
        """One table cell locked to the shared column width (title == field)."""
        widths = getattr(self, "_magic_widths", None) or list(self._magic_col_fixed)
        width = widths[column] if column < len(widths) else widths[-1]
        bg = TABLE_HEADER if header else ("#f7f8fa" if zebra else "#ffffff")
        holder = tk.Frame(
            parent,
            background=BORDER,
            highlightthickness=0,
            bd=0,
            width=width,
        )
        holder.grid(row=row, column=column, sticky="nsew")
        holder.grid_propagate(False)
        cell = tk.Frame(holder, background=bg, highlightthickness=0, bd=0)
        cell.pack(fill="both", expand=True, padx=(0, 1), pady=(0, 1))
        refs = getattr(self, "_magic_cell_refs", None)
        if refs is None:
            self._magic_cell_refs = []
            refs = self._magic_cell_refs
        refs.append((holder, column))
        return cell

    def _show_magic_skills(self) -> None:
        sheet = getattr(self, "_magic_sheet", None)
        if sheet is None:
            return
        self._magic_skills_shown = True
        for child in sheet.winfo_children():
            child.destroy()
        self._magic_cell_refs = []

        headers = (
            self.t["enabled"],
            self.t["col_icon"],
            self.t["col_magic_name"],
            self.t["col_auto"],
            self.t["col_priority"],
        )
        try:
            viewport = max(int(self._magic_canvas.winfo_width()), 1)
        except tk.TclError:
            viewport = self._magic_table_min_width()
        self._apply_magic_column_widths(max(viewport, self._magic_table_min_width()))

        # Title row and field rows share this same grid → identical column widths.
        for column, text in enumerate(headers):
            cell = self._magic_cell(sheet, 0, column, header=True)
            inner = tk.Frame(cell, background=TABLE_HEADER)
            inner.pack(fill="both", expand=True)
            anchor = "w" if column == self._magic_name_col else "center"
            tk.Label(
                inner,
                text=text,
                anchor=anchor,
                background=TABLE_HEADER,
                foreground=TEXT,
                font=FONT_SECTION,
            ).pack(fill="both", expand=True, padx=6, pady=6)

        language = self.app.language
        for row_index, skill in enumerate(self._visible_magic_skills(), start=1):
            key = skill.setting_key
            enabled = self.vars[f"magic.skill_{key}"]
            auto = self.vars[f"magic.skill_{key}_auto"]
            priority = self.vars[f"magic.skill_{key}_priority"]
            zebra = row_index % 2 == 0

            enabled_cell = self._magic_cell(sheet, row_index, 0, zebra=zebra)
            ttk.Checkbutton(enabled_cell, variable=enabled).pack(expand=True, pady=6)

            icon_cell = self._magic_cell(sheet, row_index, 1, zebra=zebra)
            icon = ttk.Label(icon_cell, image=self._magic_icon(skill.icon, key))
            icon.pack(expand=True, pady=4)

            name_cell = self._magic_cell(sheet, row_index, 2, zebra=zebra)
            ttk.Label(name_cell, text=skill.label(language), anchor="w").pack(
                fill="x", expand=True, padx=8, pady=6,
            )

            auto_cell = self._magic_cell(sheet, row_index, 3, zebra=zebra)
            ttk.Checkbutton(auto_cell, variable=auto).pack(expand=True, pady=6)

            priority_cell = self._magic_cell(sheet, row_index, 4, zebra=zebra)
            ttk.Spinbox(
                priority_cell, from_=1, to=99, width=4, textvariable=priority,
            ).pack(expand=True, pady=6)

        for child in sheet.winfo_children():
            child.bind("<MouseWheel>", self._magic_list_wheel, add="+")
            child.bind("<Shift-MouseWheel>", self._magic_list_shift_wheel, add="+")
            for nested in child.winfo_children():
                if nested.winfo_class() not in ("TSpinbox", "TEntry"):
                    nested.bind("<MouseWheel>", self._magic_list_wheel, add="+")
                    nested.bind("<Shift-MouseWheel>", self._magic_list_shift_wheel, add="+")

        self._magic_canvas.yview_moveto(0)
        self._magic_canvas.xview_moveto(0)
        self.update_idletasks()
        self._update_magic_scrollregion()
        self._refresh_magic_pick_summary()

    def _set_visible_magic(self, enabled: bool) -> None:
        for skill in self._visible_magic_skills():
            self.vars[f"magic.skill_{skill.setting_key}"].set(enabled)

    def _reset_visible_magic(self) -> None:
        for skill in self._visible_magic_skills():
            key = skill.setting_key
            self.vars[f"magic.skill_{key}"].set(False)
            self.vars[f"magic.skill_{key}_auto"].set(True)
            self.vars[f"magic.skill_{key}_priority"].set(1)
            self.vars[f"magic.skill_{key}_hotkey"].set("")

    def _sync_magic_class(self, *, show_skills: bool = True) -> None:
        if not hasattr(self, "magic_class_combo"):
            return
        character = str(getattr(self.task, "character", "") or "")
        if character not in ("elf", "mage", "knight", "royal"):
            character = "elf"
        self.magic_class_var.set(character)
        show_combobox_value(
            self.magic_class_combo, self.t[character], list(self._magic_class_ids),
        )
        if show_skills:
            self._show_magic_skills()
        else:
            self._magic_skills_shown = False
            sheet = getattr(self, "_magic_sheet", None)
            if sheet is not None:
                for child in sheet.winfo_children():
                    child.destroy()
                self._magic_cell_refs = []
            if hasattr(self, "magic_pick_summary"):
                self._refresh_magic_pick_summary()

    def _refresh_magic_pick_summary(self, *_args: object) -> None:
        if not hasattr(self, "magic_pick_summary"):
            return
        class_id = str(self.magic_class_var.get() or "elf")
        category = str(self.magic_category_var.get() or "attack_buff")
        selected = []
        for skill in self._skill_catalog.for_filter(class_id, category):
            try:
                enabled = bool(self.vars[f"magic.skill_{skill.setting_key}"].get())
            except (tk.TclError, KeyError):
                enabled = False
            if enabled:
                selected.append(skill.label(self.app.language))
        lines = [
            f"{self.t['summary_class']}: {self.t[class_id]}",
            f"{self.t['summary_category']}: {self._skill_catalog.category_label(category, self.app.language)}",
            f"{self.t['selected_magic']}: {self.t['magic_selected_count'].format(count=len(selected))}",
        ]
        box = self.magic_pick_summary
        box.configure(state="normal")
        box.delete("1.0", "end")
        for line in lines:
            box.insert("end", line + "\n", "body")
        box.insert("end", "\n")
        if selected:
            for name in selected:
                _insert_summary_bullet(box, name)
        box.configure(state="disabled")

    def _build_slot_tree(self, parent: ttk.Frame) -> None:
        """Legacy spell-slot table (kept for Magick tooling; unused by Game F keys)."""
        self.slot_tree = ttk.Treeview(
            parent,
            columns=("spell", "enabled", "box", "key"),
            show="headings",
            height=10,
            selectmode="browse",
            style="Grid.Treeview",
        )
        for col, text in (("spell", self.t["spell"]), ("enabled", self.t["enabled"]),
                          ("box", self.t["hotbar_box"]), ("key", self.t["hotbar_key"])):
            self.slot_tree.heading(col, text=text)
        self.slot_tree.column("spell", width=210, minwidth=120, stretch=True)
        for col in ("enabled", "box", "key"):
            self.slot_tree.column(col, width=90, minwidth=65, anchor="center", stretch=False)
        self.slot_tree.pack(fill="both", expand=True)
        _enable_cell_grid(self.slot_tree)

    def _build_game_f_keys(self, page: ttk.Frame) -> None:
        """Detected F1–F3 hotbar pages as F5–F12 key grids (Other / Game F keys)."""
        page.configure(style="Page.TFrame")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        shell = self._surface_card(page)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.configure(background=SURFACE)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        # Scrollable host so narrow/short windows stay usable.
        host = tk.Frame(shell, background=SURFACE)
        host.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)

        self._hotbar_canvas = tk.Canvas(
            host, background=SURFACE, highlightthickness=0, borderwidth=0,
        )
        self._hotbar_canvas.grid(row=0, column=0, sticky="nsew")
        hotbar_y = ttk.Scrollbar(host, orient="vertical", command=self._hotbar_canvas.yview)
        hotbar_y.grid(row=0, column=1, sticky="ns")
        hotbar_x = ttk.Scrollbar(host, orient="horizontal", command=self._hotbar_canvas.xview)
        hotbar_x.grid(row=1, column=0, sticky="ew")
        self._hotbar_canvas.configure(
            yscrollcommand=hotbar_y.set, xscrollcommand=hotbar_x.set,
        )

        inner = tk.Frame(self._hotbar_canvas, background=SURFACE)
        self._hotbar_inner = inner
        self._hotbar_window = self._hotbar_canvas.create_window(
            (0, 0), window=inner, anchor="nw",
        )
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(1, weight=1)

        def _hotbar_scrollregion(_event: object = None) -> None:
            self._hotbar_canvas.configure(
                scrollregion=self._hotbar_canvas.bbox("all") or (0, 0, 0, 0),
            )

        def _hotbar_canvas_size(event: tk.Event) -> None:
            width = max(int(event.width), 1)
            self._hotbar_canvas.itemconfigure(self._hotbar_window, width=width)
            self._layout_hotbar_tiles()
            _hotbar_scrollregion()

        inner.bind("<Configure>", _hotbar_scrollregion)
        self._hotbar_canvas.bind("<Configure>", _hotbar_canvas_size)
        self._hotbar_canvas.bind(
            "<MouseWheel>",
            lambda event: (
                self._hotbar_canvas.yview_scroll(int(-event.delta / 120), "units"),
                "break",
            )[1],
        )

        header = tk.Frame(inner, background=SURFACE)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        header.columnconfigure(0, weight=1)
        title_row = tk.Frame(header, background=SURFACE)
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(0, weight=1)
        tk.Label(
            title_row,
            text=self.t["detected_hotbar"],
            background=SURFACE,
            foreground=ACCENT,
            font=FONT_SECTION,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self._hotbar_refresh_btn = ttk.Button(
            title_row,
            text=self.t["hotbar_refresh"],
            command=self._on_hotbar_refresh,
        )
        self._hotbar_refresh_btn.grid(row=0, column=1, sticky="e")
        meta = tk.Frame(header, background=SURFACE)
        meta.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._hotbar_basis = tk.Label(
            meta,
            text=self.t["hotbar_memory_basis"],
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=FONT_BODY,
            anchor="w",
        )
        self._hotbar_basis.pack(side="left", padx=(0, 14))
        self._hotbar_updated = tk.Label(
            meta,
            text=self.t["hotbar_last_update"].format(time="—"),
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=FONT_BODY,
            anchor="w",
        )
        self._hotbar_updated.pack(side="left", padx=(0, 14))
        self._hotbar_total = tk.Label(
            meta,
            text=self.t["hotbar_total_slots"].format(count=24),
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=FONT_BODY,
            anchor="w",
        )
        self._hotbar_total.pack(side="left")
        self._hotbar_empty = tk.Label(
            header,
            text=self.t["hotbar_waiting_scan"],
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=FONT_BODY,
            anchor="w",
            wraplength=640,
            justify="left",
        )
        self._hotbar_empty.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._hotbar_scanning = False

        body = tk.Frame(inner, background=SURFACE)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self._hotbar_body = body
        for column in range(3):
            body.columnconfigure(column, weight=1, uniform="hotbarbox")
        body.rowconfigure(0, weight=1)

        self._hotbar_slot_tiles: dict[tuple[int, str], tk.Frame] = {}
        self._hotbar_slot_badges: dict[tuple[int, str], tk.Label] = {}
        self._hotbar_slot_names: dict[tuple[int, str], tk.Label] = {}
        self._hotbar_box_cards: list[tk.Frame] = []
        self._hotbar_slot_size = _HOTBAR_SLOT
        class_marks = ("⚔", "🗡", "✦")

        for index, box in enumerate((1, 2, 3)):
            card = tk.Frame(
                body,
                background=SURFACE,
                highlightbackground=BORDER,
                highlightcolor=BORDER,
                highlightthickness=1,
                bd=0,
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            self._hotbar_box_cards.append(card)
            title_row = tk.Frame(card, background=ACCENT_SOFT)
            title_row.pack(fill="x")
            tk.Label(
                title_row,
                text=f"{class_marks[index]}  {self.t['hotbar_class_n'].format(n=box)}",
                background=ACCENT_SOFT,
                foreground=TEXT,
                font=FONT_SECTION,
                anchor="w",
            ).pack(side="left", padx=10, pady=8)
            tk.Frame(card, background=BORDER, height=1).pack(fill="x")

            grid = tk.Frame(card, background=SURFACE)
            grid.pack(fill="both", expand=True, padx=8, pady=8)
            for col in range(4):
                grid.columnconfigure(col, weight=1, uniform=f"hb{box}")
            for row_i in range(2):
                grid.rowconfigure(row_i, weight=1, uniform=f"hb{box}r")
            for row_i, row_keys in enumerate(SKILL_GRID):
                for col_i, key in enumerate(row_keys):
                    tile = tk.Frame(
                        grid,
                        background=_HOTBAR_SLOT_BG,
                        highlightbackground=_HOTBAR_SLOT_EDGE,
                        highlightcolor=_HOTBAR_SLOT_EDGE,
                        highlightthickness=1,
                        width=_HOTBAR_SLOT,
                        height=_HOTBAR_SLOT,
                    )
                    tile.grid(row=row_i, column=col_i, sticky="nsew", padx=3, pady=3)
                    tile.grid_propagate(False)
                    caption = tk.Label(
                        tile,
                        text="",
                        background=_HOTBAR_SLOT_BG,
                        foreground="#e5e7eb",
                        font=("Segoe UI", 7),
                        wraplength=max(32, _HOTBAR_SLOT - 8),
                        justify="center",
                    )
                    caption.place(relx=0.5, rely=0.97, anchor="s")
                    badge = tk.Label(
                        tile,
                        text=key.upper(),
                        background="#111827",
                        foreground="#ffffff",
                        font=("Segoe UI", 7, "bold"),
                    )
                    self._place_hotbar_key_badge(badge, _HOTBAR_SLOT)
                    self._hotbar_slot_tiles[(box, key)] = tile
                    self._hotbar_slot_badges[(box, key)] = badge
                    self._hotbar_slot_names[(box, key)] = caption

        self.after_idle(self._layout_hotbar_tiles)
        self._refresh_hotbar_view()

    def _on_hotbar_refresh(self) -> None:
        """Read live 24-slot hotbar from memory and refresh this view + HP order keys."""
        if getattr(self, "_hotbar_scanning", False):
            return
        self._hotbar_scanning = True
        button = getattr(self, "_hotbar_refresh_btn", None)
        if button is not None:
            button.configure(state="disabled")
        updated = getattr(self, "_hotbar_updated", None)
        if updated is not None:
            updated.configure(text=self.t["hotbar_refreshing"])
        empty = getattr(self, "_hotbar_empty", None)
        if empty is not None:
            empty.configure(text=self.t["hotbar_refreshing"])
            empty.grid()

        def work() -> None:
            layout = None
            slots = None
            error = ""
            try:
                from manmabot_v1.hotbar.inspect import inspect_hotbars

                detected = inspect_hotbars()
                layout = detected.to_profile_dict()
                slots = detected.spell_slots
            except Exception as exc:
                error = str(exc)
            try:
                self.after(
                    0,
                    lambda: self._finish_hotbar_refresh(layout, slots, error),
                )
            except tk.TclError:
                self._hotbar_scanning = False

        threading.Thread(target=work, name="hotbar-refresh", daemon=True).start()

    def _finish_hotbar_refresh(
        self,
        layout: dict | None,
        slots: dict | None,
        error: str,
    ) -> None:
        button = getattr(self, "_hotbar_refresh_btn", None)
        if button is not None:
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass
        self._hotbar_scanning = False
        if error or not isinstance(layout, dict):
            empty = getattr(self, "_hotbar_empty", None)
            if empty is not None:
                empty.configure(
                    text=self.t["hotbar_refresh_failed"].format(
                        error=error or "—"
                    )
                )
                empty.grid()
            updated = getattr(self, "_hotbar_updated", None)
            if updated is not None:
                updated.configure(
                    text=self.t["hotbar_last_update"].format(time="—"),
                )
            return

        stamped = dict(layout)
        stamped["updated_at"] = f"{datetime.now():%H:%M:%S}"
        merged_slots = slots if isinstance(slots, dict) else {}
        try:
            from manmabot_v1.hotbar.inspect import merge_detected_spell_slots
            from manmabot_v1.hp_actions import apply_recovery_to_spell_slots

            previous = self._value("magic", "spell_slots", {})
            if not isinstance(previous, dict) or not previous:
                previous = getattr(self.app.profile, "spell_slots", {}) or {}
            hp_actions = None
            recovery = self.task.settings.get("recovery")
            if isinstance(recovery, dict):
                hp_actions = recovery.get("hp_actions")
            if hp_actions is None:
                hp_actions = getattr(self.app.profile, "hp_actions", None)
            merged_slots = apply_recovery_to_spell_slots(
                merge_detected_spell_slots(merged_slots, previous),
                hp_actions,
            )
        except Exception:
            pass

        magic = self.task.settings.setdefault("magic", {})
        magic["hotbar_layout"] = copy.deepcopy(stamped)
        if merged_slots:
            magic["spell_slots"] = copy.deepcopy(merged_slots)

        on_hotbar = getattr(self.app, "_on_hotbar", None)
        if callable(on_hotbar):
            try:
                on_hotbar(stamped, merged_slots or {})
                self._refresh_hp_action_hotbar_keys()
                return
            except Exception:
                pass
        try:
            self.app.profile.hotbar_layout = stamped
            if merged_slots:
                self.app.profile.spell_slots = copy.deepcopy(merged_slots)
        except Exception:
            pass
        self._refresh_hotbar_view()
        self._refresh_hp_action_hotbar_keys()

    def _place_hotbar_key_badge(self, badge: tk.Label, slot: int) -> None:
        """Keep F5–F12 in a top-left chip (1/3 wide, 1/4 tall) above the name."""
        width = max(16, int(slot) // 3)
        height = max(12, int(slot) // 4)
        font_px = max(6, min(9, height - 5))
        badge.configure(font=("Segoe UI", font_px, "bold"))
        badge.place(x=1, y=1, width=width, height=height)
        badge.lift()

    def _layout_hotbar_tiles(self, *_args: object) -> None:
        """Scale F-key tiles to the available width so the grid stays responsive."""
        body = getattr(self, "_hotbar_body", None)
        tiles = getattr(self, "_hotbar_slot_tiles", None)
        if body is None or not tiles:
            return
        try:
            width = int(body.winfo_width())
        except tk.TclError:
            return
        if width <= 1:
            return
        # Three cards with gutters; four slots per row with padding.
        card_w = max(120, (width - 24) // 3)
        inner = max(80, card_w - 24)
        slot = max(_HOTBAR_SLOT_MIN, min(_HOTBAR_SLOT_MAX, (inner - 24) // 4))
        size_changed = slot != getattr(self, "_hotbar_slot_size", 0)
        self._hotbar_slot_size = slot
        for tile in tiles.values():
            tile.configure(width=slot, height=slot)
        names = getattr(self, "_hotbar_slot_names", None)
        if names:
            wrap = max(28, slot - 8)
            for caption in names.values():
                caption.configure(wraplength=wrap)
        badges = getattr(self, "_hotbar_slot_badges", None)
        if badges:
            for badge in badges.values():
                self._place_hotbar_key_badge(badge, slot)
        if size_changed and hasattr(self, "_hotbar_canvas"):
            self._hotbar_canvas.configure(
                scrollregion=self._hotbar_canvas.bbox("all") or (0, 0, 0, 0),
            )

    def _refresh_hotbar_view(self, *_args: object) -> None:
        if not getattr(self, "_hotbar_slot_badges", None):
            return
        layout = self._value("magic", "hotbar_layout", {})
        if not isinstance(layout, dict) or not layout:
            layout = getattr(self.app.profile, "hotbar_layout", {}) or {}
        boxes = layout.get("boxes") if isinstance(layout, dict) else {}
        if not isinstance(boxes, dict):
            boxes = {}
        filled = 0
        badge_colors = {
            "SPELL": ("#166534", "#dcfce7"),
            "ITEM": ("#1d4ed8", "#dbeafe"),
            "STALE": ("#92400e", "#fef3c7"),
            "EMPTY": ("#111827", "#ffffff"),
        }
        for box in (1, 2, 3):
            box_cells = boxes.get(str(box)) if isinstance(boxes.get(str(box)), dict) else {}
            for key in SKILL_KEYS:
                cell = box_cells.get(key) if isinstance(box_cells.get(key), dict) else {}
                raw_name = str(cell.get("kr_name") or cell.get("label") or "").strip()
                name = memory_name_for_ui(raw_name, self.app.language) if raw_name else ""
                kind = str(cell.get("kind") or "").upper()
                if not kind:
                    kind = "EMPTY" if not name else ""
                count = cell.get("count")
                if count in (None, "") and raw_name:
                    from manmabot_v1.hotbar.inspect import count_from_hotbar_label

                    count = count_from_hotbar_label(raw_name)
                badge = self._hotbar_slot_badges.get((box, key))
                caption = self._hotbar_slot_names.get((box, key))
                if badge is None:
                    continue
                bits: list[str] = []
                if name:
                    bits.append(name)
                    filled += 1
                if kind == "ITEM" and count not in (None, "", 0):
                    bits.append(f"×{count}")
                if caption is not None:
                    caption.configure(text=" ".join(bits))
                bg, fg = badge_colors.get(kind or "EMPTY", ("#111827", "#ffffff"))
                badge.configure(text=key.upper(), background=bg, foreground=fg)
                badge.lift()

        stamp = str(layout.get("updated_at") or "").strip() if isinstance(layout, dict) else ""
        if not stamp and boxes:
            stamp = f"{datetime.now():%H:%M:%S}"
        if hasattr(self, "_hotbar_updated"):
            self._hotbar_updated.configure(
                text=self.t["hotbar_last_update"].format(time=stamp or "—"),
            )
        if hasattr(self, "_hotbar_total"):
            self._hotbar_total.configure(
                text=self.t["hotbar_total_slots"].format(count=24),
            )
        empty = getattr(self, "_hotbar_empty", None)
        if empty is not None:
            if filled:
                empty.grid_remove()
            else:
                try:
                    wrap = max(240, int(self._hotbar_inner.winfo_width()) - 32)
                except (tk.TclError, AttributeError):
                    wrap = 640
                empty.configure(wraplength=wrap)
                empty.grid()
        canvas = getattr(self, "_hotbar_canvas", None)
        self._refresh_hp_action_hotbar_keys()
        if canvas is not None:
            canvas.after_idle(
                lambda: canvas.configure(
                    scrollregion=canvas.bbox("all") or (0, 0, 0, 0),
                )
            )

    def _build_equipment(self) -> None:
        pages = self._nested(
            self.pages["equipment"],
            ("buy", "sell", "routing"),
            store_as="_equipment_tabs",
        )
        equip_tabs = getattr(self, "_equipment_tabs", None)
        if equip_tabs is not None:
            equip_tabs.bind(
                "<<NotebookTabChanged>>", self._on_equipment_tab_changed, add="+",
            )
        buy_page = pages["buy"]
        buy_page.configure(style="Page.TFrame")
        buy_body = ttk.Frame(buy_page, style="Page.TFrame")
        buy_body.pack(fill="both", expand=True)
        buy_body.columnconfigure(0, weight=1, uniform="buy")
        buy_body.columnconfigure(1, weight=1, uniform="buy")
        buy_body.rowconfigure(0, weight=0)
        buy_left = ttk.Frame(buy_body, style="Page.TFrame")
        buy_right = ttk.Frame(buy_body, style="Page.TFrame")
        buy_left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        buy_right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        arrows = self._attack_card(buy_left, self.t["buy_arrows"])
        arrows.pack(fill="x", pady=(0, 8))
        buy_arrows = self._check(arrows, 0, self.t["buy_arrows"], "equipment.buy_arrows", True)
        self._var("equipment.buy_normal_arrows", True, "bool")
        self._var("equipment.buy_silver_arrows", False, "bool")
        self._arrow_kind = tk.StringVar(self, value="normal")
        for value, text in (
            ("normal", self.t["buy_normal_arrows"]),
            ("silver", self.t["buy_silver_arrows"]),
        ):
            choice = ttk.Radiobutton(
                arrows, text=text, value=value, variable=self._arrow_kind,
            )
            choice.grid(row=1 if value == "normal" else 3, column=0, columnspan=3, sticky="w", pady=2)
            self._remember("equipment.arrow_kind", choice)
        self._row(
            arrows, 2, self.t["normal_arrow_qty"],
            "equipment.arrow_quantity", 200, "int",
        )
        self._row(
            arrows, 4, self.t["silver_arrow_qty"],
            "equipment.silver_arrow_quantity", 200, "int",
        )

        portions = self._attack_card(buy_left, self.t["buy_portion"])
        portions.pack(fill="x")
        self._check(
            portions, 0, self.t["restock"], "equipment.restock_potions", True,
        )
        self._row(
            portions, 1, self.t["hp_potion_buy_qty"],
            "equipment.buy_portion", 100, "int",
        )
        self._check(
            portions, 2, self.t["buy_depoison"], "equipment.buy_depoison", False,
        )
        self._row(
            portions, 3, self.t["depoison_qty"],
            "equipment.depoison_quantity", 1, "int",
        )
        self._npc_field(
            portions, 4, "equipment.hp_potion_npc", "shop", self.t["return_potion_npc"],
        )
        # Keep legacy hunt key in sync so older schedules still load/save cleanly.
        self._var("hunt.return_potion_npc", "")

        def _apply_arrow_choice(*_args: object) -> None:
            selected = str(self._arrow_kind.get())
            self.vars["equipment.buy_normal_arrows"].set(selected != "silver")
            self.vars["equipment.buy_silver_arrows"].set(selected == "silver")
            buying = bool(buy_arrows.get())
            self._set_inputs(("equipment.arrow_kind",), buying)
            self._set_inputs(("equipment.arrow_quantity",), buying and selected != "silver")
            self._set_inputs(
                ("equipment.silver_arrow_quantity",), buying and selected == "silver",
            )
            self._refresh_buy_summary()

        def _sync_potion_npc(*_args: object) -> None:
            if "equipment.hp_potion_npc" in self.vars and "hunt.return_potion_npc" in self.vars:
                self.vars["hunt.return_potion_npc"].set(
                    self.vars["equipment.hp_potion_npc"].get()
                )
            self._refresh_buy_summary()

        def _apply_potion_buy(*_args: object) -> None:
            restock = bool(self.vars["equipment.restock_potions"].get())
            depoison = bool(self.vars["equipment.buy_depoison"].get())
            self._set_inputs(("equipment.buy_portion",), restock)
            self._set_inputs(("equipment.depoison_quantity",), depoison)
            self._set_inputs(("equipment.hp_potion_npc",), restock or depoison)
            self._refresh_buy_summary()

        self._apply_arrow_choice = _apply_arrow_choice
        self._arrow_kind.trace_add("write", _apply_arrow_choice)
        buy_arrows.trace_add("write", _apply_arrow_choice)
        self.vars["equipment.hp_potion_npc"].trace_add("write", _sync_potion_npc)
        self.vars["equipment.restock_potions"].trace_add("write", _apply_potion_buy)
        self.vars["equipment.buy_depoison"].trace_add("write", _apply_potion_buy)
        for name in (
            "equipment.arrow_quantity",
            "equipment.silver_arrow_quantity",
            "equipment.buy_portion",
            "equipment.depoison_quantity",
        ):
            if name in self.vars:
                self.vars[name].trace_add("write", self._refresh_buy_summary)

        buy_summary = self._attack_card(buy_right, self.t["settings_summary"])
        buy_summary.pack(fill="both", expand=True)
        self.buy_summary = tk.Text(
            buy_summary, wrap="word", width=1, height=1, relief="flat", borderwidth=0,
            highlightthickness=0, background="#ffffff", foreground="#1f2328",
            font=FONT_BODY, padx=4, pady=4, cursor="arrow",
        )
        self.buy_summary.pack(fill="both", expand=True)
        _configure_summary_text(self.buy_summary)
        self.buy_summary.configure(state="disabled")

        _apply_arrow_choice()
        _apply_potion_buy()
        _sync_potion_npc()
        self._refresh_buy_summary()

        sell_page = pages["sell"]
        sell_page.rowconfigure(0, weight=1)
        sell_page.columnconfigure(0, weight=1)
        background = ttk.Style(sell_page).lookup("TFrame", "background") or "#f0f0f0"
        sell_canvas = tk.Canvas(
            sell_page, highlightthickness=0, borderwidth=0, background=background, height=1,
        )
        sell_scroll = ttk.Scrollbar(sell_page, orient="vertical", command=sell_canvas.yview)
        sell_canvas.configure(yscrollcommand=sell_scroll.set)
        sell_canvas.grid(row=0, column=0, sticky="nsew")
        sell_scroll.grid(row=0, column=1, sticky="ns")
        sell_inner = ttk.Frame(sell_canvas)
        sell_window = sell_canvas.create_window((0, 0), window=sell_inner, anchor="nw")

        def _fit_sell(_event=None) -> None:
            bbox = sell_canvas.bbox("all")
            if bbox:
                sell_canvas.configure(scrollregion=bbox)

        def _fit_sell_width(event) -> None:
            if int(sell_canvas.itemcget(sell_window, "width") or 0) != event.width:
                sell_canvas.itemconfigure(sell_window, width=event.width)

        def _sell_wheel(event) -> str | None:
            widget = event.widget
            while widget is not None:
                if widget.winfo_class() == "Treeview":
                    return None
                if widget in (sell_canvas, sell_inner, sell_page):
                    sell_canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
                widget = getattr(widget, "master", None)
            return None

        sell_inner.bind("<Configure>", _fit_sell)
        sell_canvas.bind("<Configure>", _fit_sell_width)

        settings = group(sell_inner, self.t["sell_settings"])
        settings.pack(fill="x", pady=(0, 6))
        mode = self._var("equipment.sell_mode", "sell_except_keep")
        mode.set("sell_except_keep")
        ttk.Label(settings, text=self.t["sell_except_keep"]).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=2
        )
        self._check(
            settings, 1, self.t["store_after_sell"], "equipment.store_after_sell", False,
        )

        items = group(sell_inner, self.t["sell_items"])
        items.pack(fill="both", expand=True)
        self.sell_filter_panel = SellFilterPanel(
            items, self.t, language=self.app.language,
        )
        self.sell_filter_panel.pack(fill="both", expand=True)

        def _bind_sell_wheel(widget: tk.Misc) -> None:
            if widget.winfo_class() == "Treeview":
                return
            widget.bind("<MouseWheel>", _sell_wheel, add="+")
            for child in widget.winfo_children():
                _bind_sell_wheel(child)

        _bind_sell_wheel(sell_inner)
        sell_canvas.bind("<MouseWheel>", _sell_wheel, add="+")

        self._build_routing(pages["routing"])

    def _refresh_buy_summary(self, *_args: object) -> None:
        if not hasattr(self, "buy_summary"):
            return

        def state(name: str) -> str:
            return self.t["summary_on"] if self._summary_on(name) else self.t["summary_off"]

        lines: list[str] = []
        buying = self._summary_on("equipment.buy_arrows")
        lines.append(f"{self.t['buy_arrows']}: {state('equipment.buy_arrows')}")
        if buying:
            kind = "silver" if getattr(self, "_arrow_kind", None) is not None and str(
                self._arrow_kind.get()
            ) == "silver" else "normal"
            if kind == "silver":
                qty = self._summary_number("equipment.silver_arrow_quantity", 200)
                lines.append(f"{self.t['buy_silver_arrows']}: {qty}")
            else:
                qty = self._summary_number("equipment.arrow_quantity", 200)
                lines.append(f"{self.t['buy_normal_arrows']}: {qty}")

        lines.append(f"{self.t['restock']}: {state('equipment.restock_potions')}")
        if self._summary_on("equipment.restock_potions"):
            lines.append(
                f"{self.t['hp_potion_buy_qty']}: "
                f"{self._summary_number('equipment.buy_portion', 100)}"
            )
        lines.append(f"{self.t['buy_depoison']}: {state('equipment.buy_depoison')}")
        if self._summary_on("equipment.buy_depoison"):
            lines.append(
                f"{self.t['depoison_qty']}: "
                f"{self._summary_number('equipment.depoison_quantity', 1)}"
            )
        npc = ""
        var = self.vars.get("equipment.hp_potion_npc")
        if var is not None:
            try:
                npc = str(var.get() or "").strip()
            except tk.TclError:
                npc = ""
        if npc:
            lines.append(f"{self.t['return_potion_npc']}: {npc}")
        elif self._summary_on("equipment.restock_potions") or self._summary_on(
            "equipment.buy_depoison"
        ):
            lines.append(f"{self.t['return_potion_npc']}: —")

        box = self.buy_summary
        box.configure(state="normal", height=max(len(lines), 1))
        box.delete("1.0", "end")
        for line in lines:
            _insert_summary_bullet(box, line)
        box.configure(state="disabled")

    def _npc_field(
        self, parent: ttk.Frame, row: int, name: str, role: str, label: str | None = None,
    ) -> None:
        field = ttk.Frame(parent)
        field.grid(row=row, column=0, columnspan=8, sticky="w", pady=2)
        ttk.Label(field, text=label or self.t["npc"]).pack(side="left", padx=(0, 6))
        variable = self._var(name, "")
        entry = ttk.Entry(field, textvariable=variable, width=28)
        entry.pack(side="left")
        button = ttk.Button(
            field, text="...", width=3, command=lambda: self._pick_npc(variable, role),
        )
        button.pack(side="left", padx=(4, 0))
        self._remember(name, entry)
        self._remember(name, button)

    def _npc_choices(self, role: str) -> list[str]:
        try:
            root = manmabot_root()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from app._04_decision.talking_scroll import ROWS
        except Exception:
            return []
        language = self.app.language
        region = ""
        choices: list[str] = []
        for spot in ROWS:
            kind = spot.get("kind")
            if kind == "header" and spot.get("region") not in ("title", "favorites"):
                region = scroll_label_display(str(spot.get("label") or ""), language)
                continue
            if kind != "spot" or role not in (spot.get("roles") or ()):
                continue
            label = scroll_label_display(str(spot.get("label") or ""), language)
            choices.append(f"{region} / {label}" if region else label)
        return choices

    def _pick_npc(self, variable: tk.Variable, role: str) -> None:
        choices = self._npc_choices(role)
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title(self.t["pick_npc"])
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        listing = tk.Listbox(dialog, height=12, width=36, activestyle="dotbox")
        listing.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        for item in choices:
            listing.insert("end", item)
        current = str(variable.get())
        if current in choices:
            index = choices.index(current)
            listing.selection_set(index)
            listing.see(index)

        def choose(_event: object = None) -> None:
            selected = listing.curselection()
            if not selected:
                return
            variable.set(listing.get(selected[0]))
            dialog.destroy()

        listing.bind("<Double-1>", choose)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text=self.t["cancel"], command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text=self.t["ok"], command=choose, style="Accent.TButton").pack(side="right", padx=(0, 4))
        _center_dialog(dialog, self.winfo_toplevel())
        dialog.deiconify()
        dialog.grab_set()

    def _build_routing(self, page: ttk.Frame) -> None:
        box = group(page, self.t["routing"])
        box.pack(fill="x")
        self.loot_var = self._var("other.loot_mode", "all_items")
        ttk.Radiobutton(
            box, text=self.t["loot_all_adena"], value="all_items", variable=self.loot_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(box, text=self.t["adena_weight"]).grid(
            row=1, column=0, sticky="w", padx=(22, 5), pady=2,
        )
        weight_frame = ttk.Frame(box)
        weight_frame.grid(row=1, column=1, sticky="w", pady=2)
        self._adena_weight_entry = ttk.Entry(
            weight_frame,
            textvariable=self._var("other.loot_adena_weight_pct", 30, "int"),
            width=13,
        )
        self._adena_weight_entry.pack(side="left")
        ttk.Label(weight_frame, text="%").pack(side="left", padx=(3, 0))
        ttk.Radiobutton(
            box, text=self.t["loot_adena_only_pick"], value="adena_only",
            variable=self.loot_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
        self._check(
            box, 3, self.t["use_potion_on_pickup"],
            "equipment.use_potion_on_pickup", True,
        )
        self._check(
            box, 4, self.t["minimize_combat_loot"],
            "equipment.minimize_combat_during_loot", True,
        )

        def _sync_loot_controls(*_args: object) -> None:
            adena_only = str(self.loot_var.get()) == "adena_only"
            self._adena_weight_entry.configure(state="disabled" if adena_only else "normal")

        self.loot_var.trace_add("write", _sync_loot_controls)
        _sync_loot_controls()

    def _build_other(self) -> None:
        self._retain_general_fields()
        pages = self._nested(self.pages["other"], (
            "game_f_keys", "diagnostics", "copy_import", "hotkeys",
        ))
        self._build_game_f_keys(pages["game_f_keys"])
        self._build_diagnostics(pages["diagnostics"])
        self._build_copy_import(pages["copy_import"])
        self._build_hotkey_page(pages["hotkeys"])

    def _retain_general_fields(self) -> None:
        """Keep game language, humanize, and notes in the save path without a tab."""
        holder = ttk.Frame(self)
        self._game_language_ids = {
            self.t["game_korean"]: "ko",
            self.t["game_chinese"]: "zh",
        }
        self.game_language_var = self._var(
            "other.game_language", self.t["game_korean"]
        )
        self.game_language_combo = ttk.Combobox(
            holder, state="readonly", width=12, values=list(self._game_language_ids),
            textvariable=self.game_language_var,
        )
        show_combobox_value(
            self.game_language_combo,
            self.game_language_var.get(),
            list(self._game_language_ids),
        )
        self._check(holder, 1, self.t["humanize"], "other.humanize", True)
        self.notes = tk.Text(holder, width=42, height=4)
        style_text(self.notes)

    def _surface_card(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            background=SURFACE,
            highlightbackground=BUTTON_EDGE,
            highlightcolor=BUTTON_EDGE,
            highlightthickness=1,
        )

    def _build_diagnostics(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(1, weight=1)
        status = self._attack_card(page, self.t["diag_status"])
        status.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        row = ttk.Frame(status)
        row.pack(fill="x")
        self._status_states = {}
        self._status_values = {}
        cards = (
            ("game", self.t["diag_game"]),
            ("memory", self.t["diag_memory"]),
            ("map", self.t["diag_map"]),
            ("bot", self.t["diag_bot"]),
            ("hotbar", self.t["diag_hotbar"]),
        )
        for index, (key, title) in enumerate(cards):
            row.columnconfigure(index, weight=1, uniform="diag")
            card = self._surface_card(row)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0))
            tk.Label(
                card, text=title, background=SURFACE, foreground=ACCENT,
                font=FONT_BODY, anchor="w",
            ).pack(fill="x", padx=8, pady=(6, 0))
            state = tk.Label(
                card, text=self.t["status_wait"], background=SURFACE,
                foreground=ACCENT, font=FONT_SECTION, anchor="w",
            )
            state.pack(fill="x", padx=8, pady=(2, 0))
            detail = tk.Label(
                card, text="", background=SURFACE, foreground=TEXT_MUTED,
                font=FONT_BODY, anchor="w", justify="left", wraplength=150,
            )
            detail.pack(fill="x", padx=8, pady=(0, 6))
            self._status_states[key] = state
            self._status_values[key] = detail

        log_card = self._attack_card(page, self.t["exec_log"])
        log_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        toolbar = ttk.Frame(log_card)
        toolbar.pack(fill="x", pady=(0, 4))
        self._log_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar, text=self.t["auto_scroll"], variable=self._log_autoscroll,
        ).pack(side="right")
        table = ttk.Frame(log_card)
        table.pack(fill="both", expand=True)
        self.log_tree = ttk.Treeview(
            table, columns=("time", "message"), show="headings", selectmode="browse",
        )
        self.log_tree.heading("time", text=self.t["log_time"])
        self.log_tree.heading("message", text=self.t["log_message"])
        self.log_tree.column("time", width=88, stretch=False, anchor="w")
        # Wide min so long decision/combat lines are not clipped in the cell.
        self.log_tree.column("message", width=520, minwidth=400, stretch=True, anchor="w")
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.log_tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.log_tree.xview)
        self.log_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.log_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        detail_frame = ttk.Frame(log_card)
        detail_frame.pack(fill="both", expand=False, pady=(6, 0))
        ttk.Label(detail_frame, text=self.t.get("log_full_line", "Full line")).pack(
            anchor="w"
        )
        self.log_detail = tk.Text(
            detail_frame,
            height=4,
            wrap="word",
            state="disabled",
            font=FONT_BODY,
        )
        style_text(self.log_detail)
        self.log_detail.pack(fill="both", expand=True)
        self.log_tree.bind("<<TreeviewSelect>>", self._on_log_select)
        self.log_box = tk.Text(page, height=1, state="disabled")
        style_text(self.log_box)
        self.app.log_widget = self.log_box
        self._replay_logs()

        side = ttk.Frame(page)
        side.grid(row=1, column=1, sticky="nsew")
        side.rowconfigure(1, weight=1)
        side.columnconfigure(0, weight=1)
        tools = self._attack_card(side, self.t["diag_tools"])
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for title, hint, command in (
            (self.t["copy_diagnostics"], self.t["copy_diag_hint"], self.app.copy_diagnostics),
            (self.t["open_logs"], self.t["open_logs_hint"], self.app.open_logs),
            (self.t["clear_log"], self.t["clear_log_hint"], self._clear_log_view),
        ):
            self._action_row(tools, title, hint, command).pack(fill="x", pady=3)
        alerts = self._attack_card(side, self.t["recent_alerts"])
        alerts.grid(row=1, column=0, sticky="nsew")
        self.alert_title = tk.Label(
            alerts, text=self.t["no_alerts"], background=SURFACE, foreground=TEXT,
            font=FONT_SECTION, anchor="w", justify="left", wraplength=240,
        )
        self.alert_title.pack(fill="x", padx=4, pady=(2, 0))
        self.alert_body = tk.Label(
            alerts, text="", background=SURFACE, foreground=TEXT_MUTED,
            font=FONT_BODY, anchor="nw", justify="left", wraplength=240,
        )
        self.alert_body.pack(fill="both", expand=True, padx=4, pady=(2, 4))

    def _action_row(self, parent: tk.Misc, title: str, hint: str, command) -> tk.Frame:
        row = self._surface_card(parent)
        tk.Label(
            row, text=title, background=SURFACE, foreground=TEXT,
            font=FONT_SECTION, anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(
            row, text=hint, background=SURFACE, foreground=TEXT_MUTED,
            font=FONT_BODY, anchor="w", justify="left", wraplength=260,
        ).pack(fill="x", padx=10, pady=(0, 6))

        def invoke(_event: object = None) -> None:
            command()

        row.bind("<Button-1>", invoke)
        for child in row.winfo_children():
            child.bind("<Button-1>", invoke)
        row.configure(cursor="hand2")
        return row

    def _lamp_caption(self, lamp: Lamp) -> tuple[str, str]:
        if lamp == Lamp.GREEN:
            return self.t["status_ok"], "#16a34a"
        if lamp in (Lamp.YELLOW, Lamp.RED):
            return self.t["status_warn"], "#d97706"
        return self.t["status_wait"], ACCENT

    def _show_status(self, game, memory, map_probe) -> None:
        if not getattr(self, "_status_states", None):
            return
        pairs = (
            ("game", game.lamp, game.detail),
            ("memory", memory.lamp, memory.detail),
            ("map", map_probe.lamp, map_probe.detail),
        )
        for key, lamp, detail in pairs:
            caption, color = self._lamp_caption(lamp)
            self._status_states[key].configure(text=caption, foreground=color)
            self._status_values[key].configure(
                text=localize_probe_detail(str(detail or ""), self.app.language)
            )
        state = self.app.coordinator.controller.state
        if state == RunState.RUNNING:
            caption, color = self.t["status_ok"], "#16a34a"
        elif state == RunState.PAUSED:
            caption, color = self.t["status_warn"], "#d97706"
        else:
            caption, color = self.t["status_wait"], ACCENT
        self._status_states["bot"].configure(
            text=caption, foreground=color,
        )
        self._status_values["bot"].configure(
            text=self.t.get(state.value, state.value),
        )
        slots = getattr(self.app.profile, "spell_slots", {}) or {}
        count = sum(
            1 for slot in slots.values()
            if isinstance(slot, dict) and str(slot.get("key") or "").strip()
        )
        self._status_states["hotbar"].configure(
            text=self.t["status_ok"] if count else self.t["status_wait"],
            foreground="#16a34a" if count else ACCENT,
        )
        self._status_values["hotbar"].configure(
            text=self.t["hotbar_ready"].format(count=count),
        )

    def _append_log_row(self, stamp: str, message: str) -> None:
        tree = getattr(self, "log_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        tree.insert("", "end", values=(stamp, message))
        children = tree.get_children()
        if len(children) > 500:
            tree.delete(children[0])
        follow = getattr(self, "_log_autoscroll", None)
        if follow is None or bool(follow.get()):
            last = tree.get_children()[-1]
            tree.see(last)
            tree.selection_set(last)
            self._show_log_detail(stamp, message)
        title = getattr(self, "alert_title", None)
        if title is not None and title.winfo_exists():
            title.configure(text=message)
            body = self.alert_body
            body.configure(text=stamp)

    def _on_log_select(self, _event: object = None) -> None:
        tree = getattr(self, "log_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            return
        values = tree.item(sel[0], "values")
        if not values or len(values) < 2:
            return
        self._show_log_detail(str(values[0]), str(values[1]))

    def _show_log_detail(self, stamp: str, message: str) -> None:
        detail = getattr(self, "log_detail", None)
        if detail is None or not detail.winfo_exists():
            return
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        detail.insert("1.0", f"{stamp}  {message}")
        detail.configure(state="disabled")

    def _replay_logs(self) -> None:
        for line in getattr(self.app, "_log_lines", []):
            stamp, _, message = str(line).partition("  ")
            self._append_log_row(stamp or str(line), message)

    def _clear_log_view(self) -> None:
        tree = getattr(self, "log_tree", None)
        if tree is not None and tree.winfo_exists():
            tree.delete(*tree.get_children())
        widget = getattr(self.app, "log_widget", None)
        if widget is not None and widget.winfo_exists():
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
        self.app._log_lines = []
        if getattr(self, "alert_title", None) is not None:
            self.alert_title.configure(text=self.t["no_alerts"])
            self.alert_body.configure(text="")

    def _build_copy_import(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)
        save_card = self._attack_card(page, self.t["save_current"])
        save_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        ttk.Label(save_card, text=self.t["save_current_hint"], wraplength=360).pack(anchor="w")
        form = ttk.Frame(save_card)
        form.pack(fill="x", pady=(8, 0))
        ttk.Label(form, text=self.t["profile_name"]).pack(anchor="w")
        line = ttk.Frame(form)
        line.pack(fill="x", pady=(4, 0))
        self.profile_name_var = tk.StringVar()
        ttk.Entry(line, textvariable=self.profile_name_var).pack(
            side="left", fill="x", expand=True, padx=(0, 6),
        )
        ttk.Button(
            line, text=self.t["save_as_name"], style="Accent.TButton",
            command=self._save_profile_from_entry,
        ).pack(side="left")

        load_card = self._attack_card(page, self.t["load_settings"])
        load_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(load_card, text=self.t["load_settings_hint"], wraplength=360).pack(anchor="w")
        # Pack actions first (bottom) so the expanding list cannot hide the buttons.
        actions = ttk.Frame(load_card)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(
            actions, text=self.t["load_profile"], command=self._load_selected_profile,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            actions, text=self.t["delete_profile"], command=self._delete_selected_profile,
        ).pack(side="left")
        listing = ttk.Frame(load_card)
        listing.pack(fill="both", expand=True, pady=(6, 0))
        self.profile_tree = ttk.Treeview(
            listing, columns=("name", "class", "date"), show="headings",
            selectmode="browse", height=6,
        )
        for column, heading, width in (
            ("name", self.t["col_name"], 120),
            ("class", self.t["profile_class"], 80),
            ("date", self.t["profile_date"], 130),
        ):
            self.profile_tree.heading(column, text=heading)
            self.profile_tree.column(column, width=width, anchor="w")
        profile_scroll = ttk.Scrollbar(listing, orient="vertical", command=self.profile_tree.yview)
        self.profile_tree.configure(yscrollcommand=profile_scroll.set)
        self.profile_tree.pack(side="left", fill="both", expand=True)
        profile_scroll.pack(side="right", fill="y")
        self.profile_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_profile())

        backup = self._attack_card(page, self.t["backup_exchange"])
        backup.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        ttk.Label(backup, text=self.t["backup_hint"], wraplength=360).pack(anchor="w", pady=(0, 6))
        self._action_row(
            backup, self.t["export_file"], self.t["export_file_hint"],
            self._export_selected_profile,
        ).pack(fill="x", pady=3)
        self._action_row(
            backup, self.t["import_file"], self.t["import_file_hint"],
            self._import_profile_file,
        ).pack(fill="x", pady=3)

        info = self._attack_card(page, self.t["selected_profile"])
        info.grid(row=1, column=1, sticky="nsew")
        self.profile_info = {}
        for key, label in (
            ("name", self.t["col_name"]),
            ("class", self.t["profile_class"]),
            ("created", self.t["profile_created"]),
        ):
            line = ttk.Frame(info)
            line.pack(fill="x", pady=1)
            ttk.Label(line, text=label, width=12).pack(side="left")
            value = ttk.Label(line, text="-")
            value.pack(side="left", fill="x", expand=True)
            self.profile_info[key] = value
        ttk.Label(info, text=self.t["profile_details"]).pack(anchor="w", pady=(6, 2))
        self.profile_desc = tk.Text(info, height=4, wrap="word", state="disabled")
        style_text(self.profile_desc)
        self.profile_desc.pack(fill="both", expand=True)
        self._reload_profile_table()

    def _profile_class_label(self, character: str) -> str:
        key = "royal" if character == "prince" else character
        return self.t.get(key, character)

    def _reload_profile_table(self) -> None:
        tree = getattr(self, "profile_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        tree.delete(*tree.get_children())
        for name in list_profile_names():
            path = named_profile_path(name)
            character = ""
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    character = str(data.get("character") or "")
            except (OSError, json.JSONDecodeError):
                data = None
            stamp = ""
            try:
                stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                pass
            tree.insert(
                "", "end", iid=name,
                values=(name, self._profile_class_label(character), stamp),
            )
        self._show_selected_profile()

    def _selected_profile_name(self) -> str:
        tree = getattr(self, "profile_tree", None)
        if tree is None:
            return ""
        selected = tree.selection()
        return str(selected[0]) if selected else ""

    def _show_selected_profile(self) -> None:
        name = self._selected_profile_name()
        info = getattr(self, "profile_info", None)
        desc = getattr(self, "profile_desc", None)
        if not info or desc is None:
            return
        if not name:
            for value in info.values():
                value.configure(text="-")
            desc.configure(state="normal")
            desc.delete("1.0", "end")
            desc.insert("1.0", self.t["no_profile"])
            desc.configure(state="disabled")
            return
        path = named_profile_path(name)
        character = ""
        language = ""
        active_map = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                character = str(data.get("character") or "")
                language = str(data.get("language") or "")
                active_map = str(data.get("active_map") or "")
        except (OSError, json.JSONDecodeError):
            pass
        created = ""
        try:
            created = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            pass
        info["name"].configure(text=name)
        info["class"].configure(text=self._profile_class_label(character))
        info["created"].configure(text=created or "-")
        lines = [
            part
            for part in (
                language_display_name(language, self.app.language) if language else "",
                map_display_name(active_map, self.app.language) if active_map else "",
            )
            if part
        ]
        desc.configure(state="normal")
        desc.delete("1.0", "end")
        desc.insert("1.0", "\n".join(lines) if lines else self.t["no_profile"])
        desc.configure(state="disabled")

    def _save_profile_from_entry(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            self.app.save_named()
        else:
            try:
                save_named_profile(name, self.app.profile)
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=self)
                return
        self._reload_profile_table()

    def _load_selected_profile(self) -> None:
        self.app.load_named(self._selected_profile_name() or None)

    def _delete_selected_profile(self) -> None:
        self.app.delete_named(self._selected_profile_name() or None)
        self._reload_profile_table()

    def _export_selected_profile(self) -> None:
        self.app.export_named(self._selected_profile_name() or None)

    def _import_profile_file(self) -> None:
        self.app.import_named()
        self._reload_profile_table()

    def _build_hotkey_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(0, weight=1)
        settings = self._attack_card(page, self.t["hotkey_settings"])
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        header = ttk.Frame(settings)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text=self.t["hotkey_action"], width=28).pack(side="left")
        ttk.Label(header, text=self.t["hotkey_key"], width=16).pack(side="left")
        ttk.Label(header, text=self.t["hotkey_enabled"]).pack(side="left")
        self._hotkey_vars: dict[str, tk.StringVar] = {}
        self._hotkey_labels: dict[str, ttk.Label] = {}
        self._hotkey_enabled: dict[str, tk.BooleanVar] = {}
        for key, label in (
            ("pause_resume", self.t["pause_hotkey"]),
            ("stop", self.t["stop_hotkey"]),
        ):
            row = ttk.Frame(settings)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, width=28).pack(side="left")
            variable = tk.StringVar()
            self._hotkey_vars[key] = variable
            key_label = ttk.Label(row, textvariable=variable, width=16, anchor="w")
            key_label.pack(side="left", padx=(0, 8))
            self._hotkey_labels[key] = key_label
            enabled = tk.BooleanVar(value=True)
            self._hotkey_enabled[key] = enabled
            ttk.Checkbutton(row, variable=enabled).pack(side="left")
        self._load_hotkey_fields()

        side = ttk.Frame(page)
        side.grid(row=0, column=1, sticky="nsew")
        side.rowconfigure(1, weight=1)
        side.columnconfigure(0, weight=1)
        options = self._attack_card(side, self.t["hotkey_options"])
        options.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(options, text=self.t["hotkey_global_note"], wraplength=280).pack(anchor="w", pady=2)
        ttk.Label(options, text=self.t["hotkey_duplicate_note"], wraplength=280).pack(anchor="w", pady=2)
        buttons = ttk.Frame(options)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(
            buttons, text=self.t["save_hotkeys"], command=self._edit_hotkeys_from_page,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            buttons, text=self.t["reset_hotkeys"], command=self._reset_hotkeys_from_page,
        ).pack(side="left")
        ttk.Button(
            options, text=self.t["hotkey_apply"], command=self._apply_hotkey_fields,
        ).pack(fill="x", pady=(8, 0))
        howto = self._attack_card(side, self.t["hotkey_howto"])
        howto.grid(row=1, column=0, sticky="nsew")
        ttk.Label(
            howto, text=self.t["hotkey_howto_body"], justify="left", wraplength=280,
        ).pack(anchor="w", fill="x")

    def _load_hotkey_fields(self) -> None:
        current = dict(getattr(self.app.profile, "hotkeys", {}) or {})
        for key, variable in getattr(self, "_hotkey_vars", {}).items():
            bound = str(current.get(key) or "").strip()
            display = bound or str(DEFAULT_HOTKEYS.get(key, ""))
            variable.set(display)
            enabled = self._hotkey_enabled.get(key)
            if enabled is not None:
                enabled.set(bool(bound))

    def _edit_hotkeys_from_page(self) -> None:
        self.app.edit_hotkeys()
        self._load_hotkey_fields()

    def _reset_hotkeys_from_page(self) -> None:
        self.app.reset_hotkeys()
        self._load_hotkey_fields()

    def _apply_hotkey_fields(self) -> None:
        if not self.app._settings_unlocked():
            return
        candidate = {}
        for key, variable in self._hotkey_vars.items():
            enabled = bool(self._hotkey_enabled[key].get())
            combo = variable.get().strip().lower()
            if not combo:
                combo = str(DEFAULT_HOTKEYS.get(key, "")).lower()
            candidate[key] = combo if enabled else ""
        previous = dict(self.app.profile.hotkeys)
        self.app.profile.hotkeys = candidate
        error = self.app.coordinator.rebind_hotkeys()
        if error:
            self.app.profile.hotkeys = previous
            self.app.coordinator.rebind_hotkeys()
            messagebox.showerror(self.t["hotkeys"], error, parent=self)
            self._load_hotkey_fields()
            return
        save_profile(self.app.profile)
        self._load_hotkey_fields()

    def _hunt_photo(
        self,
        path: Path | None,
        key: str,
        allowed: bool,
        *,
        pil_image: object | None = None,
    ) -> tk.PhotoImage:
        from PIL import ImageTk

        cache = getattr(self, "_hunt_photos", None)
        if cache is None:
            self._hunt_photos = {}
            cache = self._hunt_photos
        cache_key = hunt_icon_cache_key(key, allowed=allowed, size=_hunt_icon_box())
        photo = cache.get(cache_key)
        if photo is None:
            image = pil_image if pil_image is not None else _filled_icon(
                path, _hunt_icon_box(), enabled=allowed,
            )
            photo = ImageTk.PhotoImage(image, master=self)
            cache[cache_key] = photo
        return photo

    def _bump_icon_warmup_token(self) -> int:
        token = int(getattr(self, "_icon_warmup_token", 0) or 0) + 1
        self._icon_warmup_token = token
        return token

    def _ensure_icon_warmup_queue(self) -> None:
        q = getattr(self, "_icon_warmup_q", None)
        if q is None:
            import queue

            self._icon_warmup_q = queue.Queue()
            self._icon_warmup_pumping = False

    def _pump_icon_warmup(self) -> None:
        """Apply background-prepared icons on the UI thread."""
        self._ensure_icon_warmup_queue()
        import queue

        consumed = 0
        try:
            while True:
                kind, token, prepared = self._icon_warmup_q.get_nowait()
                consumed += 1
                self._apply_hunt_icon_batch(kind, token, prepared, 0)
        except queue.Empty:
            pass
        if consumed:
            self._icon_warmup_pending = max(
                0, int(getattr(self, "_icon_warmup_pending", 0) or 0) - consumed
            )
        if int(getattr(self, "_icon_warmup_pending", 0) or 0) > 0:
            self._icon_warmup_pumping = True
            try:
                self.after(40, self._pump_icon_warmup)
            except tk.TclError:
                self._icon_warmup_pending = 0
                self._icon_warmup_pumping = False
        else:
            self._icon_warmup_pumping = False

    def _start_hunt_icon_warmup(self, kind: str) -> None:
        """Decode Hunt icons off the UI thread, then attach PhotoImages in batches."""
        if kind == "species":
            order = list(getattr(self, "_species_order", []) or [])
            icons = getattr(self, "_species_icons", {}) or {}
            allowed_map = getattr(self, "_species_allowed", {}) or {}
        elif kind == "items":
            order = list(getattr(self, "_item_order", []) or [])
            icons = getattr(self, "_item_icons", {}) or {}
            allowed_map = getattr(self, "_item_allowed", {}) or {}
        else:
            return
        if not order:
            return
        self._ensure_icon_warmup_queue()
        token = self._bump_icon_warmup_token()
        self._icon_warmup_pending = int(getattr(self, "_icon_warmup_pending", 0) or 0) + 1
        jobs = [
            (key, icons.get(key), bool(allowed_map.get(key, True)))
            for key in order
        ]
        if not getattr(self, "_icon_warmup_pumping", False):
            self._icon_warmup_pumping = True
            try:
                self.after(0, self._pump_icon_warmup)
            except tk.TclError:
                self._icon_warmup_pending = max(
                    0, int(getattr(self, "_icon_warmup_pending", 0) or 0) - 1
                )
                self._icon_warmup_pumping = False
                return

        def worker() -> None:
            try:
                prepared = prepare_hunt_icons(
                    jobs, size=_hunt_icon_box(), filled_icon=_filled_icon,
                )
                self._icon_warmup_q.put((kind, token, prepared))
            except Exception:
                # Drop the pending slot so the pump can stop.
                self._icon_warmup_pending = max(
                    0, int(getattr(self, "_icon_warmup_pending", 0) or 0) - 1
                )

        threading.Thread(
            target=worker, name=f"hunt-icon-warmup-{kind}", daemon=True,
        ).start()

    def _apply_hunt_icon_batch(
        self,
        kind: str,
        token: int,
        prepared: dict[str, object],
        start: int,
    ) -> None:
        if token != int(getattr(self, "_icon_warmup_token", 0) or 0):
            return
        if kind == "species":
            tree = getattr(self, "species_tree", None)
            order = list(getattr(self, "_species_order", []) or [])
            icons = getattr(self, "_species_icons", {}) or {}
            allowed_map = getattr(self, "_species_allowed", {}) or {}
        else:
            tree = getattr(self, "item_tree", None)
            order = list(getattr(self, "_item_order", []) or [])
            icons = getattr(self, "_item_icons", {}) or {}
            allowed_map = getattr(self, "_item_allowed", {}) or {}
        if tree is None:
            return
        batch = 40
        end = min(start + batch, len(order))
        for key in order[start:end]:
            try:
                if not tree.exists(key):
                    continue
            except tk.TclError:
                return
            allowed = bool(allowed_map.get(key, True))
            cache_key = hunt_icon_cache_key(key, allowed=allowed, size=_hunt_icon_box())
            pil_image = prepared.get(cache_key)
            try:
                photo = self._hunt_photo(
                    icons.get(key), key, allowed, pil_image=pil_image,
                )
                tree.item(key, image=photo)
            except tk.TclError:
                return
        if end < len(order):
            try:
                self.after(
                    1,
                    lambda: self._apply_hunt_icon_batch(kind, token, prepared, end),
                )
            except tk.TclError:
                return

    def _toggle_items(self) -> None:
        for iid in self.item_tree.selection():
            allowed = not bool(self._item_allowed.get(iid, True))
            self._item_allowed[iid] = allowed
            if self.item_tree.exists(iid):
                _set_tree_column_value(
                    self.item_tree,
                    iid,
                    "allow",
                    self.t["yes"] if allowed else self.t["no"],
                )
                self.item_tree.item(
                    iid,
                    tags=() if allowed else ("denied",),
                    image=self._hunt_photo(self._item_icons.get(iid), iid, allowed),
                )
        self._refresh_items_summary()

    def _toggle_item_cell(self, event: tk.Event) -> str | None:
        if self.item_tree.identify_region(event.x, event.y) != "cell":
            return None
        if _tree_data_column(self.item_tree, event.x) != "allow":
            return None
        iid = self.item_tree.identify_row(event.y)
        if not iid:
            return None
        if iid not in self.item_tree.selection():
            self.item_tree.selection_set(iid)
        self._toggle_items()
        return "break"

    def _start_item_drag(self, event: tk.Event) -> None:
        self._item_drag_anchor = _tree_row(self.item_tree, event.x, event.y)

    def _drag_item_selection(self, event: tk.Event) -> None:
        current = self.item_tree.identify_row(event.y)
        anchor = getattr(self, "_item_drag_anchor", "")
        if not current or not anchor:
            return
        rows = list(self.item_tree.get_children())
        if current not in rows or anchor not in rows:
            return
        first, last = sorted((rows.index(anchor), rows.index(current)))
        self.item_tree.selection_set(rows[first:last + 1])
        self.item_tree.focus(current)
        self.item_tree.see(current)

    def _default_item_category_label(
        self,
        categories: list[str] | None = None,
        language: str | None = None,
    ) -> str:
        """Initial 분류 value: armor (갑옷), in the label the item rows use."""
        language = language or self._catalog_language()
        label = item_category_display_name("갑옷", language) or "갑옷"
        if categories is not None and label not in categories:
            return self.t["filter_all"]
        return label

    def _load_item_names(self) -> None:
        if not hasattr(self, "item_tree"):
            return
        raw = self._value("other", "item_pickup_names", [])
        selected = {str(item).strip() for item in raw} if isinstance(raw, list) else set()
        selected.discard("")
        if hasattr(self, "item_mode_var"):
            mode = str(self.item_mode_var.get() or "blacklist").strip().lower()
        else:
            mode = str(self._value("other", "item_pickup_mode", "blacklist")).strip().lower()
        if mode == "all":
            selected = set()
            mode = "blacklist"
        elif mode not in ("blacklist", "whitelist"):
            mode = "blacklist"
        if hasattr(self, "item_mode_var"):
            self.item_mode_var.set(mode)
        from app._03_world.game_catalog import (
            item_category_labels,
            list_item_rows,
            resolve_item_key,
        )

        language = self._catalog_language()
        selected_keys = {resolve_item_key(name) or name for name in selected}
        entries = list(list_item_rows())
        entries.sort(
            key=lambda entry: (
                item_catalog_display_name(entry.name_ko, language) or entry.name_ko
            ).lower()
        )
        categories = [
            self.t["filter_all"],
            *sorted(
                {
                    item_category_display_name(name, language)
                    for name in item_category_labels(language)
                    if name
                }
            ),
        ]
        if hasattr(self, "item_category_combo"):
            default_category = self._default_item_category_label(categories, language)
            current = str(self.item_category_var.get() or default_category)
            _size_readonly_combo(self.item_category_combo, categories, fit=False)
            if current not in categories:
                current = (
                    default_category
                    if default_category in categories
                    else self.t["filter_all"]
                )
            self.item_category_var.set(current)
        self._item_order = []
        self._item_allowed = {}
        self._item_labels = {}
        self._item_search = {}
        self._item_categories = {}
        self._item_icons = {}
        for entry in entries:
            if mode == "whitelist":
                allowed = entry.key in selected_keys
            elif mode == "blacklist":
                allowed = entry.key not in selected_keys
            else:
                allowed = True
            self._item_order.append(entry.key)
            self._item_allowed[entry.key] = allowed
            self._item_labels[entry.key] = item_catalog_display_name(
                entry.name_ko, language
            ) or entry.display_name(language)
            self._item_search[entry.key] = " ".join(
                item_search_names(entry.name_ko, row=entry)
            ).lower()
            self._item_categories[entry.key] = (
                item_category_display_name(entry.category_ko, language)
                or entry.display_category(language)
            )
            self._item_icons[entry.key] = entry.image_path()
        self._items_view_loaded = True
        self._refresh_item_rows(fit=True, with_icons=False)
        self._refresh_items_summary()
        self._start_hunt_icon_warmup("items")

    def _refresh_item_rows(self, *, fit: bool = False, with_icons: bool = True) -> None:
        if not hasattr(self, "item_tree"):
            return
        show = "all"
        if hasattr(self, "item_show_var") and hasattr(self, "_item_show_ids"):
            show = self._item_show_ids.get(self.item_show_var.get().strip(), "all")
        category = self.t["filter_all"]
        if hasattr(self, "item_category_var"):
            category = str(self.item_category_var.get() or self.t["filter_all"]).strip()
        needle = ""
        if hasattr(self, "item_search_var"):
            needle = str(self.item_search_var.get() or "")
        self.item_tree.delete(*self.item_tree.get_children())
        for key in self._item_order:
            allowed = bool(self._item_allowed.get(key, True))
            if show == "allowed" and not allowed:
                continue
            if show == "unallowed" and allowed:
                continue
            item_cat = self._item_categories.get(key, "")
            if category and category != self.t["filter_all"] and item_cat != category:
                continue
            label = self._item_labels.get(key, key)
            haystack = self._item_search.get(key) or " ".join((key, label, item_cat))
            if not table_name_matches(needle, haystack):
                continue
            row_kw: dict[str, Any] = {
                "iid": key,
                "text": "",
                "tags": () if allowed else ("denied",),
                "values": (
                    label,
                    item_cat,
                    self.t["yes"] if allowed else self.t["no"],
                ),
            }
            if with_icons:
                row_kw["image"] = self._hunt_photo(
                    self._item_icons.get(key), key, allowed,
                )
            self.item_tree.insert("", "end", **row_kw)
        if fit:
            _fit_tree_columns(self.item_tree, include_tree=True, stretch_last=False)
            self.item_tree.column("name", stretch=True)
            self.item_tree.column("allow", stretch=False, anchor="center")
            _configure_hunt_icon_column(self.item_tree, heading=self.t["species_image"])
        _refresh_cell_grid(self.item_tree)

    def load(self, task: ScheduleTask) -> None:
        self._suppress_delay_warn = True
        try:
            self._load_task(task)
        finally:
            self._suppress_delay_warn = False
            pair = self._target_delay_pair()
            if pair is not None and pair[0] > pair[1]:
                self.vars["hunt.target_delay_min_ms"].set(pair[1])
                self.vars["hunt.target_delay_max_ms"].set(max(pair[0], pair[1]))
            self._remember_target_delay()

    def _load_task(self, task: ScheduleTask) -> None:
        self.task = _clone(task)
        skip_vars = {
            "task.character",
            "task.account_id",
            "move.map_id",
            "other.game_language",
            "hunt.species_sort",
        }
        self._repeat_guard = True
        for name, var in self.vars.items():
            if name in skip_vars:
                continue
            if name.startswith("task."):
                raw = getattr(self.task, name.split(".", 1)[1])
            else:
                section, key = name.split(".", 1)
                raw = self._value(section, key, var.get())
            if isinstance(var, tk.BooleanVar):
                raw = _as_bool(raw)
            elif isinstance(var, tk.IntVar):
                try:
                    raw = int(raw)
                except (TypeError, ValueError):
                    raw = var.get()
                if name in _JITTER_VAR_NAMES:
                    raw = clamp_jitter_ms(raw)
            var.set(raw)
        self._load_hp_actions()
        if hasattr(self, "_arrow_kind"):
            silver = bool(self.vars["equipment.buy_silver_arrows"].get())
            self._arrow_kind.set("silver" if silver else "normal")
            self._apply_arrow_choice()
        if "equipment.hp_potion_npc" in self.vars:
            npc = str(self.vars["equipment.hp_potion_npc"].get() or "").strip()
            if not npc:
                npc = str(self._value("hunt", "return_potion_npc", "") or "").strip()
            shown = shop_npc_display(npc, self.app.language)
            if shown:
                self.vars["equipment.hp_potion_npc"].set(shown)
            if "hunt.return_potion_npc" in self.vars:
                self.vars["hunt.return_potion_npc"].set(
                    self.vars["equipment.hp_potion_npc"].get()
                )
        if hasattr(self, "vars") and "equipment.restock_potions" in self.vars:
            restock = bool(self.vars["equipment.restock_potions"].get())
            depoison_var = self.vars.get("equipment.buy_depoison")
            depoison = bool(depoison_var.get()) if depoison_var is not None else False
            self._set_inputs(("equipment.buy_portion",), restock)
            if "equipment.depoison_quantity" in self.vars:
                self._set_inputs(("equipment.depoison_quantity",), depoison)
            if "equipment.hp_potion_npc" in self.vars:
                self._set_inputs(("equipment.hp_potion_npc",), restock or depoison)
        loot_mode = str(self._value("other", "loot_mode", "all_items"))
        if loot_mode not in ("all_items", "adena_only"):
            loot_mode = "all_items"
        if hasattr(self, "loot_var"):
            self.loot_var.set(loot_mode)
        # Heavy Hunt/Magic icon tables load when those tabs are opened.
        self._species_view_loaded = False
        self._items_view_loaded = False
        self._magic_skills_shown = False
        self._species_order = []
        self._species_allowed = {}
        self._item_order = []
        self._item_allowed = {}
        if hasattr(self, "species_tree"):
            try:
                self.species_tree.delete(*self.species_tree.get_children())
            except tk.TclError:
                pass
        if hasattr(self, "item_tree"):
            try:
                self.item_tree.delete(*self.item_tree.get_children())
            except tk.TclError:
                pass
        species_sort = str(self._value("hunt", "species_sort", "name"))
        show_combobox_value(
            self.species_sort_combo,
            next(
                (
                    label for label, sort_id in self._sort_ids.items()
                    if sort_id == species_sort
                ),
                self.t["sort_name"],
            ),
            list(self._sort_ids),
        )
        game_language = str(self._value("other", "game_language", "ko"))
        show_combobox_value(
            self.game_language_combo,
            next(
                (
                    label for label, language_id in self._game_language_ids.items()
                    if language_id == game_language
                ),
                self.t["game_korean"],
            ),
            list(self._game_language_ids),
        )
        for day, variable in enumerate(self.weekday_vars):
            variable.set(day in self.task.weekdays)
        self._repeat_guard = False
        self._align_repeat_daily_checkbox()
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", str(self._value("other", "notes", "")))
        self._load_accounts()
        self._show_account_details()
        self._sync_timing_inputs()
        style = normalize_map_style(self._value("move", "map_style", ""))
        saved_map = str(self._value("move", "map_id", self.app.profile.active_map))
        if not str(self._value("move", "map_style", "")).strip():
            style = "normal" if saved_map in _FARM_MAP_IDS else "dungeon"
        if "move.map_style" in self.vars:
            self.vars["move.map_style"].set(style)
        self._load_maps(prefer=saved_map)
        self._sync_map_areas_ui()
        self._load_move_areas()
        self._load_slots()
        self._sync_magic_class(show_skills=False)
        if hasattr(self, "magic_summary"):
            self._refresh_magic_summary()
        if hasattr(self, "attack_summary"):
            self._refresh_attack_summary()
        if hasattr(self, "monsters_summary"):
            self._refresh_monsters_summary()
        if hasattr(self, "items_summary"):
            self._refresh_items_summary()
        if hasattr(self, "form_summary"):
            self._refresh_form_summary()
        if hasattr(self, "buy_summary"):
            self._refresh_buy_summary()
        self.mark_form_clean()
        # If the user already sits on a heavy tab, fill it now.
        self._maybe_load_deferred_views()

    def _fp_cell(self, value: object) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    def _form_fingerprint(self) -> tuple[str, ...]:
        """Stable snapshot of the form, used to skip leave prompts when unchanged."""
        cells: list[str] = []
        for name in sorted(self.vars):
            try:
                cells.append(f"{name}={self._fp_cell(self.vars[name].get())}")
            except (tk.TclError, TypeError, ValueError):
                cells.append(f"{name}=")
        if hasattr(self, "weekday_vars"):
            cells.append(
                "weekdays="
                + ",".join("1" if var.get() else "0" for var in self.weekday_vars)
            )
        if hasattr(self, "notes"):
            try:
                cells.append("notes=" + self.notes.get("1.0", "end-1c"))
            except tk.TclError:
                cells.append("notes=")
        if hasattr(self, "farm_tree"):
            try:
                cells.append("farms=" + ",".join(self._selected_farm_names()))
                stays = []
                for name in self._selected_farm_names():
                    seconds = stay_seconds_for(
                        name, getattr(self, "_farm_stays_s", {}), self._default_farm_stay_s()
                    )
                    stays.append(f"{name}:{stay_minutes_from_s(seconds)}")
                cells.append("farm_stays=" + ",".join(stays))
            except tk.TclError:
                cells.append("farms=")
        if hasattr(self, "order_display"):
            cells.append("order=" + self._fp_cell(self.order_display.get()))
        if hasattr(self, "type_display"):
            cells.append("type=" + self._fp_cell(self.type_display.get()))
        if hasattr(self, "server_display"):
            cells.append("server=" + self._fp_cell(self.server_display.get()))
        if hasattr(self, "character_var"):
            cells.append("character=" + self._fp_cell(self.character_var.get()))
        if hasattr(self, "species_mode_var"):
            cells.append("species_mode=" + self._fp_cell(self.species_mode_var.get()))
        allowed = getattr(self, "_species_allowed", {})
        cells.append(
            "species="
            + json.dumps(
                [(key, bool(allowed.get(key, True))) for key in sorted(allowed)],
                ensure_ascii=True,
            )
        )
        if hasattr(self, "item_mode_var"):
            cells.append("item_mode=" + self._fp_cell(self.item_mode_var.get()))
        items = getattr(self, "_item_allowed", {})
        cells.append(
            "items="
            + json.dumps(
                [(key, bool(items.get(key, True))) for key in sorted(items)],
                ensure_ascii=True,
            )
        )
        try:
            self._snapshot_hp_actions_from_rows()
        except Exception:
            pass
        cells.append(
            "hp_actions="
            + json.dumps(getattr(self, "_hp_actions", []), ensure_ascii=True, sort_keys=True, default=str)
        )
        if hasattr(self, "slot_tree"):
            try:
                slots = [
                    (iid, tuple(self.slot_tree.item(iid, "values")))
                    for iid in self.slot_tree.get_children()
                ]
                cells.append("slots=" + json.dumps(slots, ensure_ascii=True, default=str))
            except tk.TclError:
                cells.append("slots=")
        return tuple(cells)

    def mark_form_clean(self) -> None:
        """Remember the current form as the unchanged baseline."""
        self._clean_fingerprint = self._form_fingerprint()

    def form_is_dirty(self) -> bool:
        """True when the operator changed the form since it was last loaded."""
        baseline = getattr(self, "_clean_fingerprint", None)
        if baseline is None:
            return False
        return self._form_fingerprint() != baseline

    def _load_accounts(self) -> None:
        try:
            accounts = AccountStore().load()
        except Exception:
            accounts = []
        self._accounts_by_name = {
            account.display_name or account.username: account for account in accounts
        }
        self._account_ids = {a.display_name or a.username: a.account_id for a in accounts}
        values = [name for name in self._account_ids if str(name).strip()]
        current = self.task.account_id if self.task else None
        current_name = next(
            (n for n, i in self._account_ids.items() if i == current), ""
        )
        show_combobox_value(self.account_combo, current_name, values)
        schedule_combo = getattr(self, "schedule_account_combo", None)
        if schedule_combo is not None:
            show_combobox_value(schedule_combo, current_name, values)
        self._show_account_details()

    def _account_changed(self, _event=None) -> None:
        self._show_account_details()

    def _show_account_details(self) -> None:
        empty = self.t["value_empty"]
        account = self._accounts_by_name.get(str(self.vars["task.account_id"].get()))
        if account is None:
            self.order_display.set(empty)
            self.type_display.set(empty)
            self.server_display.set(empty)
            self.vars["task.server"].set("")
            character = self.task.character if self.task is not None else "mage"
            self.character_var.set(_label_for(self._character_ids, character))
            return
        self.order_display.set(str(account.character_number))
        self.type_display.set(_label_for(self._character_ids, account.character_type))
        self.server_display.set(account.server or empty)
        self.vars["task.server"].set(account.server)
        self.vars["task.character_slot"].set(int(account.character_number))
        self.character_var.set(_label_for(self._character_ids, account.character_type))

    def _sync_timing_inputs(self) -> None:
        window_mode = str(self.vars["task.time_mode"].get()) != "duration"
        self.start_time.set_enabled(window_mode)
        self.end_time.set_enabled(window_mode)
        self.duration_spin.configure(state="disabled" if window_mode else "normal")

    def _load_maps(self, prefer: str | None = None) -> None:
        choices = list_map_choices(self.app.language)
        dungeon = self._is_dungeon_style() if hasattr(self, "map_style_var") else False
        shown = [
            (map_id, label)
            for map_id, label, _dungeon in choices
            if (map_id in _FARM_MAP_IDS) != dungeon
        ]
        self._map_ids = {label: map_id for map_id, label in shown}
        want = str(prefer or self._map_id() or "")
        current = next(
            (label for label, mid in self._map_ids.items() if mid == want),
            "",
        )
        if not current and shown:
            current = shown[0][1]
        show_combobox_value(self.map_combo, current, list(self._map_ids))
        if current:
            self.map_var.set(current)
        self._sync_species_region_to_map()

    def _map_id(self) -> str:
        return self._map_ids.get(str(self.map_var.get()), str(self.map_var.get()))

    def _is_dungeon_style(self) -> bool:
        return normalize_map_style(self.map_style_var.get()) == "dungeon"

    def _on_map_combo(self) -> None:
        self._sync_map_areas_ui()
        self._load_move_areas()
        self._sync_species_region_to_map()

    def _on_species_region_selected(self, _event: object = None) -> None:
        self._species_region_user_set = True
        self._refresh_species_rows()
        self._refresh_monsters_summary()

    def _matching_map_region(self, region_values: list[str] | tuple[str, ...]) -> str:
        """Catalog region for the map selected on the Map tab, if one exists."""
        selected = str(self.map_var.get() or "").strip() if hasattr(self, "map_var") else ""
        map_id = ""
        if hasattr(self, "_map_ids") and selected:
            map_id = str(self._map_ids.get(selected, "") or "")
        known = {str(value) for value in region_values}
        all_label = self.t["filter_all"]
        for name in monster_region_candidates(map_id, self._catalog_language()):
            if name in known and name != all_label:
                return name
        if selected in known and selected != all_label:
            return selected
        return ""

    def _species_region_choice(self, region_values: list[str]) -> str:
        label = self._matching_map_region(region_values)
        if not getattr(self, "_species_region_user_set", False) and label:
            return label
        current = str(self.species_region_var.get() or "").strip()
        if current in region_values:
            return current
        if label:
            return label
        return self.t["filter_all"]

    def _sync_species_region_to_map(self) -> None:
        """Point the monster region filter at the map chosen on the Map tab."""
        if not hasattr(self, "species_region_var") or not hasattr(self, "species_region_combo"):
            return
        self._species_region_user_set = False
        try:
            values = [str(value) for value in (self.species_region_combo.cget("values") or [])]
        except tk.TclError:
            return
        if len(values) <= 1:
            return
        label = self._matching_map_region(values)
        chosen = label or self.t["filter_all"]
        if str(self.species_region_var.get() or "") != chosen:
            self.species_region_var.set(chosen)
        if getattr(self, "_species_view_loaded", False):
            self._refresh_species_rows()
            self._refresh_monsters_summary()

    def _on_map_style_changed(self) -> None:
        if not hasattr(self, "farm_tree"):
            return
        self._load_maps()
        self._sync_map_areas_ui()
        self._load_move_areas()

    def _sync_map_areas_ui(self) -> None:
        dungeon = self._is_dungeon_style()
        if hasattr(self, "map_hint"):
            self.map_hint.configure(
                text=self.t["map_setup_hint_dungeon"] if dungeon else self.t["map_setup_hint"]
            )
        if hasattr(self, "btn_edit_map"):
            self.btn_edit_map.configure(
                text=self.t["edit_patrol"] if dungeon else self.t["edit"]
            )
        if hasattr(self, "areas_group"):
            try:
                self.areas_group.configure(
                    text=self.t["patrol_points"] if dungeon else self.t["farms"]
                )
            except tk.TclError:
                pass
        if hasattr(self, "btn_select_all_farms"):
            state = "disabled" if dungeon else "normal"
            self.btn_select_all_farms.configure(state=state)
            self.btn_deselect_all_farms.configure(state=state)
        if hasattr(self, "btn_farm_up"):
            state = "disabled" if dungeon else "normal"
            self.btn_farm_up.configure(state=state)
            self.btn_farm_down.configure(state=state)
        if hasattr(self, "farm_tree"):
            if dungeon:
                self.farm_tree.heading("#0", text="#")
                self.farm_tree.heading("name", text=self.t["patrol_name"])
                self.farm_tree.heading("order", text="")
                self.farm_tree.heading("stay", text="")
                self.farm_tree.heading("memo", text=self.t["patrol_coords"])
                self.farm_tree.column("order", width=1, minwidth=0, stretch=False)
                self.farm_tree.column("stay", width=1, minwidth=0, stretch=False)
            else:
                self.farm_tree.heading("#0", text=self.t["area_use"])
                self.farm_tree.heading("name", text=self.t["area_name"])
                self.farm_tree.heading("order", text=self.t["farm_order"])
                self.farm_tree.heading("stay", text=self.t["farm_stay"])
                self.farm_tree.heading("memo", text=self.t["notes"])
                self.farm_tree.column("order", width=56, minwidth=48, stretch=False)
                self.farm_tree.column("stay", width=80, minwidth=64, stretch=False)

    def _load_move_areas(self) -> None:
        if self._is_dungeon_style():
            self._load_patrol()
        else:
            self._load_farms()

    def _default_farm_stay_s(self) -> float:
        return stay_s_from_minutes(
            stay_minutes_from_s(
                float(self._value("move", "farm_rotate_s", DEFAULT_FARM_STAY_S) or DEFAULT_FARM_STAY_S)
            )
        )

    def _load_farms(self) -> None:
        rows, _error = list_farm_details(self._map_id())
        selected = [str(name) for name in self._value("move", "selected_farms", [])]
        yaml_names = [name for name, _memo in rows]
        yaml_set = set(yaml_names)
        ordered = [name for name in selected if name in yaml_set]
        ordered.extend(name for name in yaml_names if name not in set(ordered))
        memo_by_name = {name: memo for name, memo in rows}
        self._farm_schedule_loading = True
        try:
            self._farm_stays_s = normalize_farm_stays_s(self._value("move", "farm_stays_s", {}))
            default_s = self._default_farm_stay_s()
            self.farm_tree.delete(*self.farm_tree.get_children())
            for name in ordered:
                checked = name in set(selected)
                if name not in self._farm_stays_s:
                    self._farm_stays_s[name] = default_s
                self.farm_tree.insert(
                    "", "end", iid=name, text="",
                    image=self._farm_check_on if checked else self._farm_check_off,
                    tags=("on",) if checked else ("off",),
                    values=(
                        route_point_display_name(name, self.app.language),
                        "",
                        "",
                        memo_by_name.get(name, ""),
                    ),
                )
        finally:
            self._farm_schedule_loading = False
        self._refresh_farm_schedule_columns()
        _fit_tree_columns(self.farm_tree, include_tree=True, stretch_last=True)
        _refresh_cell_grid(self.farm_tree)
        self._refresh_map_summary()

    def _load_patrol(self) -> None:
        entries = list_patrol_entries(self._map_id())
        self.farm_tree.delete(*self.farm_tree.get_children())
        for i, (x, y, name) in enumerate(entries):
            iid = f"patrol:{i}:{name}"
            self.farm_tree.insert(
                "",
                "end",
                iid=iid,
                text=str(i + 1),
                image="",
                tags=("patrol",),
                values=(
                    route_point_display_name(name, self.app.language),
                    "",
                    "",
                    f"({x}, {y})",
                ),
            )
        _fit_tree_columns(self.farm_tree, include_tree=True, stretch_last=True)
        _refresh_cell_grid(self.farm_tree)
        self._refresh_map_summary()

    def _set_farm_checked(self, iid: str, checked: bool) -> None:
        if checked and iid not in self._farm_stays_s:
            self._farm_stays_s[iid] = self._default_farm_stay_s()
        self.farm_tree.item(
            iid,
            image=self._farm_check_on if checked else self._farm_check_off,
            tags=("on",) if checked else ("off",),
        )

    def _refresh_farm_schedule_columns(self) -> None:
        if not hasattr(self, "farm_tree") or self._is_dungeon_style():
            return
        order_n = 0
        for iid in self.farm_tree.get_children():
            values = list(self.farm_tree.item(iid, "values"))
            while len(values) < 4:
                values.append("")
            checked = "on" in self.farm_tree.item(iid, "tags")
            if checked:
                order_n += 1
                values[1] = str(order_n)
                values[2] = str(
                    stay_minutes_from_s(
                        stay_seconds_for(iid, self._farm_stays_s, self._default_farm_stay_s())
                    )
                )
            else:
                values[1] = ""
                values[2] = ""
            self.farm_tree.item(iid, values=values)

    def _on_farm_tree_click(self, event: tk.Event) -> str | None:
        if self._is_dungeon_style():
            return None
        region = self.farm_tree.identify_region(event.x, event.y)
        if region not in ("tree", "cell"):
            return None
        iid = self.farm_tree.identify_row(event.y)
        if not iid:
            return None
        column = self.farm_tree.identify_column(event.x)
        if column == "#0":
            self._set_farm_checked(iid, "on" not in self.farm_tree.item(iid, "tags"))
            self._refresh_farm_schedule_columns()
            self._refresh_map_summary()
            return "break"
        if column == "#3":
            self.farm_tree.selection_set(iid)
            self._edit_farm_stay(iid)
            return "break"
        return None

    def _edit_farm_stay(self, iid: str) -> None:
        if self._is_dungeon_style() or not iid:
            return
        initial = stay_minutes_from_s(
            stay_seconds_for(iid, self._farm_stays_s, self._default_farm_stay_s())
        )
        value = simpledialog.askinteger(
            self.t["farm_stay"],
            self.t["farm_stay_prompt"],
            initialvalue=initial,
            minvalue=MIN_FARM_STAY_MIN,
            maxvalue=MAX_FARM_STAY_MIN,
            parent=self,
        )
        if value is None:
            return
        self._farm_stays_s[iid] = stay_s_from_minutes(value)
        if "on" not in self.farm_tree.item(iid, "tags"):
            self._set_farm_checked(iid, True)
        self._refresh_farm_schedule_columns()
        self._refresh_map_summary()

    def _move_farm_row(self, delta: int) -> None:
        if self._is_dungeon_style():
            return
        selection = self.farm_tree.selection()
        if not selection:
            return
        iid = selection[0]
        rows = list(self.farm_tree.get_children())
        try:
            index = rows.index(iid)
        except ValueError:
            return
        target = index + int(delta)
        if target < 0 or target >= len(rows):
            return
        self.farm_tree.move(iid, "", target)
        self.farm_tree.selection_set(iid)
        self.farm_tree.see(iid)
        self._refresh_farm_schedule_columns()
        self._refresh_map_summary()

    def _select_all_farms(self) -> None:
        if self._is_dungeon_style():
            return
        for iid in self.farm_tree.get_children():
            self._set_farm_checked(iid, True)
        self._refresh_farm_schedule_columns()
        self._refresh_map_summary()

    def _clear_farms(self) -> None:
        if self._is_dungeon_style():
            return
        for iid in self.farm_tree.get_children():
            self._set_farm_checked(iid, False)
        self._refresh_farm_schedule_columns()
        self._refresh_map_summary()

    def _refresh_map_summary(self) -> None:
        name = str(self.map_var.get()).strip() or self.t["value_empty"]
        rows = self.farm_tree.get_children()
        self.map_selected_label.configure(
            text=self.t["map_selected_line"].format(name=name),
        )
        if self._is_dungeon_style():
            self.map_registered_label.configure(
                text=self.t["map_registered_patrol_line"].format(n=len(rows)),
            )
            self.map_checked_label.configure(
                text=self.t["map_style_line"].format(
                    style=self.t["map_style_dungeon"]
                ),
            )
            if hasattr(self, "map_schedule_label"):
                self.map_schedule_label.configure(text="")
            return
        checked = [
            iid for iid in rows if "on" in self.farm_tree.item(iid, "tags")
        ]
        self.map_registered_label.configure(
            text=self.t["map_registered_line"].format(n=len(rows)),
        )
        self.map_checked_label.configure(
            text=self.t["map_checked_line"].format(n=len(checked)),
        )
        if hasattr(self, "map_schedule_label"):
            if not checked:
                self.map_schedule_label.configure(text=self.t["map_schedule_empty"])
            else:
                parts = []
                for index, iid in enumerate(checked, start=1):
                    label = route_point_display_name(iid, self.app.language)
                    minutes = stay_minutes_from_s(
                        stay_seconds_for(iid, self._farm_stays_s, self._default_farm_stay_s())
                    )
                    parts.append(f"{index}. {label} ({minutes}{self.t['minutes']})")
                self.map_schedule_label.configure(
                    text=self.t["map_schedule_line"].format(order=" → ".join(parts)),
                )

    def _selected_farm_names(self) -> list[str]:
        if self._is_dungeon_style():
            return []
        return [
            str(iid)
            for iid in self.farm_tree.get_children()
            if "on" in self.farm_tree.item(iid, "tags")
        ]

    def _load_species(self) -> None:
        levels = self._value("hunt", "species_levels", {})
        blocked = set(self._value("hunt", "species_blacklist", []))
        wanted = set(self._value("hunt", "species_whitelist", []))
        if hasattr(self, "species_mode_var"):
            mode = str(self.species_mode_var.get() or "blacklist").strip().lower()
        else:
            mode = str(self._value("hunt", "species_filter_mode", "blacklist")).strip().lower()
        if mode not in ("blacklist", "whitelist"):
            mode = "blacklist"
        if hasattr(self, "species_mode_var"):
            self.species_mode_var.set(mode)
        try:
            root = manmabot_root()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from app._03_world.constants import list_species_catalog
            from app._03_world.game_catalog import (
                is_mainland_region,
                list_monster_rows,
                mainland_filter_label,
                monster_region_labels,
            )

            rows = list_species_catalog()
            catalog = {item.key: item for item in list_monster_rows()}
            language = self._catalog_language()
            mainland_label = mainland_filter_label(language)
            self._species_mainland_label = mainland_label
            region_names = [
                name for name in monster_region_labels(language)
                if name != mainland_label
            ]
            region_values = [self.t["filter_all"], mainland_label, *region_names]
            if hasattr(self, "species_region_combo"):
                chosen = self._species_region_choice(region_values)
                _size_readonly_combo(self.species_region_combo, region_values, fit=False)
                self.species_region_var.set(chosen)
        except Exception:
            rows = sorted((key, value) for key, value in levels.items())
            catalog = {}
        language = self._catalog_language()
        if self._sort_ids.get(str(self.species_sort_var.get())) == "level":
            rows = sorted(rows, key=lambda item: (item[1], item[0]))
        else:
            rows = sorted(
                rows,
                key=lambda item: (
                    catalog[item[0]].display_name(language).lower()
                    if item[0] in catalog
                    else item[0]
                ),
            )
        self._species_defaults = dict(rows)
        self._species_order = []
        self._species_allowed = {}
        self._species_level = {}
        self._species_labels = {}
        self._species_search = {}
        self._species_region_text = {}
        self._species_region_values = {}
        self._species_on_mainland = {}
        self._species_icons = {}
        for key, default in rows:
            allowed = key in wanted if mode == "whitelist" else key not in blocked
            self._species_order.append(key)
            self._species_allowed[key] = allowed
            self._species_level[key] = int(default)
            row = catalog.get(key)
            self._species_labels[key] = species_display_name_ui(key, language)
            self._species_search[key] = " ".join(
                species_search_names(key, row=row)
            ).lower()
            if row is not None:
                regions = row.display_regions(language)
                self._species_region_text[key] = row.region_text(language)
                self._species_region_values[key] = regions
                self._species_on_mainland[key] = any(
                    is_mainland_region(name) for name in regions
                )
                self._species_icons[key] = row.image_path()
            else:
                self._species_region_text[key] = ""
                self._species_region_values[key] = ()
                self._species_on_mainland[key] = False
                self._species_icons[key] = None
        self._species_view_loaded = True
        self._refresh_species_rows(fit=True, with_icons=False)
        self._refresh_monsters_summary()
        self._start_hunt_icon_warmup("species")

    def _refresh_species_rows(self, *, fit: bool = False, with_icons: bool = True) -> None:
        if not hasattr(self, "species_tree"):
            return
        show = "all"
        if hasattr(self, "species_show_var") and hasattr(self, "_species_show_ids"):
            show = self._species_show_ids.get(self.species_show_var.get().strip(), "all")
        region = self.t["filter_all"]
        if hasattr(self, "species_region_var"):
            region = str(self.species_region_var.get() or self.t["filter_all"]).strip()
        mainland = str(getattr(self, "_species_mainland_label", "") or "")
        needle = ""
        if hasattr(self, "species_search_var"):
            needle = str(self.species_search_var.get() or "")
        self.species_tree.delete(*self.species_tree.get_children())
        for key in self._species_order:
            allowed = bool(self._species_allowed.get(key, True))
            if show == "allowed" and not allowed:
                continue
            if show == "unallowed" and allowed:
                continue
            if region and region != self.t["filter_all"]:
                if region == mainland:
                    if not self._species_on_mainland.get(key, False):
                        continue
                elif region not in (self._species_region_values.get(key) or ()):
                    continue
            label = self._species_labels.get(
                key, species_display_name_ui(key, self._catalog_language())
            )
            haystack = self._species_search.get(key) or " ".join(
                (key, label, self._species_region_text.get(key, ""))
            )
            if not table_name_matches(needle, haystack):
                continue
            level = self._species_defaults.get(key, self._species_level.get(key, 1))
            row_kw: dict[str, Any] = {
                "iid": key,
                "text": "",
                "tags": () if allowed else ("denied",),
                "values": (
                    label,
                    level,
                    self.t["yes"] if allowed else self.t["no"],
                    self._species_region_text.get(key, ""),
                ),
            }
            if with_icons:
                row_kw["image"] = self._hunt_photo(
                    self._species_icons.get(key), key, allowed,
                )
            self.species_tree.insert("", "end", **row_kw)
        if fit:
            _fit_tree_columns(self.species_tree, include_tree=True, stretch_last=True)
            self.species_tree.column("allow", stretch=False, anchor="center")
            self.species_tree.column("level", stretch=False, anchor="center")
            self.species_tree.column("region", stretch=True)
            _narrow_species_columns(self.species_tree)
            _lock_hunt_icon_column(self.species_tree)
        _refresh_cell_grid(self.species_tree)

    def _toggle_species(self) -> None:
        for iid in self.species_tree.selection():
            allowed = not bool(self._species_allowed.get(iid, True))
            self._species_allowed[iid] = allowed
            if self.species_tree.exists(iid):
                _set_tree_column_value(
                    self.species_tree,
                    iid,
                    "allow",
                    self.t["yes"] if allowed else self.t["no"],
                )
                self.species_tree.item(
                    iid,
                    tags=() if allowed else ("denied",),
                    image=self._hunt_photo(self._species_icons.get(iid), iid, allowed),
                )
        self._refresh_monsters_summary()

    def _edit_species_cell(self, event: tk.Event) -> str | None:
        if self.species_tree.identify_region(event.x, event.y) != "cell":
            return None
        iid = self.species_tree.identify_row(event.y)
        if not iid:
            return None
        if iid not in self.species_tree.selection():
            self.species_tree.selection_set(iid)
        if _tree_data_column(self.species_tree, event.x) == "allow":
            self._toggle_species()
        return "break"

    def _start_species_drag(self, event: tk.Event) -> None:
        self._species_drag_anchor = _tree_row(self.species_tree, event.x, event.y)

    def _drag_species_selection(self, event: tk.Event) -> str | None:
        current = self.species_tree.identify_row(event.y)
        if not self._species_drag_anchor or not current:
            return None
        rows = list(self.species_tree.get_children())
        try:
            first = rows.index(self._species_drag_anchor)
            last = rows.index(current)
        except ValueError:
            return None
        if first > last:
            first, last = last, first
        self.species_tree.selection_set(rows[first:last + 1])
        self.species_tree.focus(current)
        self.species_tree.see(current)
        return "break"

    def _load_slots(self) -> None:
        if hasattr(self, "slot_tree") and self.slot_tree.winfo_exists():
            self.slot_tree.delete(*self.slot_tree.get_children())
            slots = self._value("magic", "spell_slots", {})
            for spell, spec in sorted(slots.items()):
                self.slot_tree.insert(
                    "", "end", iid=spell,
                    values=(
                        self.s.spell_titles.get(spell, spell),
                        self.t["yes"] if spec.get("enabled") else self.t["no"],
                        spec.get("box", ""),
                        spec.get("key", ""),
                    ),
                )
            _refresh_cell_grid(self.slot_tree)
        self._refresh_hotbar_view()

    def collect(self) -> ScheduleTask | None:
        if self.task is None:
            return None
        result = _clone(self.task)
        try:
            for name, var in self.vars.items():
                value = var.get()
                if isinstance(var, tk.BooleanVar):
                    value = _as_bool(value)
                if name in _JITTER_VAR_NAMES:
                    value = clamp_jitter_ms(value)
                if name == "task.account_id":
                    value = self._account_ids.get(str(value)) or None
                if name == "task.character":
                    value = self._character_ids.get(str(value), str(value))
                if name == "move.map_id":
                    value = self._map_id()
                if name == "other.loot_mode":
                    value = str(value)
                    if value not in ("all_items", "adena_only"):
                        value = "all_items"
                if name == "other.item_pickup_mode":
                    value = str(value).strip().lower()
                    if value not in ("all", "blacklist", "whitelist"):
                        value = "all"
                if name == "hunt.species_sort":
                    value = self._sort_ids.get(str(value), str(value))
                if name == "other.game_language":
                    value = self._game_language_ids.get(str(value), str(value))
                if name.startswith("task."):
                    setattr(result, name.split(".", 1)[1], value)
                else:
                    section, key = name.split(".", 1)
                    result.settings.setdefault(section, {})[key] = value
            hunt = result.settings.setdefault("hunt", {})
            delay_min = clamp_jitter_ms(hunt.get("target_delay_min_ms"), 20)
            delay_max = clamp_jitter_ms(hunt.get("target_delay_max_ms"), 50)
            if delay_min > delay_max:
                messagebox.showwarning(
                    self.t["target_delay"],
                    self.t["target_delay_order"],
                    parent=self.winfo_toplevel(),
                )
                delay_min, delay_max = self._target_delay_ok
                self.vars["hunt.target_delay_min_ms"].set(delay_min)
                self.vars["hunt.target_delay_max_ms"].set(delay_max)
            hunt["target_delay_min_ms"] = delay_min
            hunt["target_delay_max_ms"] = delay_max
            hunt["attack_jitter_ms"] = clamp_jitter_ms(hunt.get("attack_jitter_ms"), 35)
            result.settings["move"]["selected_farms"] = self._selected_farm_names()
            result.settings["move"]["map_style"] = (
                "dungeon" if self._is_dungeon_style() else "normal"
            )
            result.settings["move"]["farm_rotate_s"] = self._default_farm_stay_s()
            selected = list(result.settings["move"]["selected_farms"])
            result.settings["move"]["farm_stays_s"] = {
                name: stay_seconds_for(name, self._farm_stays_s, self._default_farm_stay_s())
                for name in selected
            }
            if result.settings["move"]["map_style"] == "dungeon":
                result.settings["move"]["selected_farms"] = []
                result.settings["move"]["farm_stays_s"] = {}
            equipment = result.settings.setdefault("equipment", {})
            npc_shown = shop_npc_display(
                str(equipment.get("hp_potion_npc") or ""),
                self.app.language,
            )
            if npc_shown:
                equipment["hp_potion_npc"] = npc_shown
                result.settings.setdefault("hunt", {})["return_potion_npc"] = npc_shown
            # Only rewrite species/item lists from UI maps after those views loaded;
            # otherwise keep the cloned task settings (Start/Save must not wipe them).
            if getattr(self, "_species_view_loaded", False):
                blocked, wanted = [], []
                for iid in getattr(self, "_species_order", []) or []:
                    if bool(self._species_allowed.get(iid, True)):
                        wanted.append(iid)
                    else:
                        blocked.append(iid)
                hunt = result.settings.setdefault("hunt", {})
                hunt["species_levels"] = {}
                species_mode = str(self.species_mode_var.get()).strip().lower()
                if species_mode not in ("blacklist", "whitelist"):
                    species_mode = "blacklist"
                hunt["species_filter_mode"] = species_mode
                if species_mode == "whitelist":
                    hunt["species_whitelist"] = wanted
                    hunt["species_blacklist"] = []
                else:
                    hunt["species_blacklist"] = blocked
                    hunt["species_whitelist"] = []
            if getattr(self, "_items_view_loaded", False) and hasattr(self, "item_tree"):
                other = result.settings.setdefault("other", {})
                item_mode = str(self.item_mode_var.get()).strip().lower()
                if item_mode not in ("blacklist", "whitelist"):
                    item_mode = "blacklist"
                names = [
                    str(iid)
                    for iid in getattr(self, "_item_order", []) or []
                    if (
                        bool(self._item_allowed.get(iid, True))
                        if item_mode == "whitelist"
                        else not bool(self._item_allowed.get(iid, True))
                    )
                ]
                other["item_pickup_mode"] = item_mode
                other["item_pickup_names"] = names
            slots = copy.deepcopy(result.settings["magic"].get("spell_slots", {}))
            if hasattr(self, "slot_tree") and self.slot_tree.winfo_exists():
                for iid in self.slot_tree.get_children():
                    _spell, enabled, box, key = self.slot_tree.item(iid, "values")
                    spec = slots.setdefault(iid, {})
                    spec.update(
                        enabled=enabled == self.t["yes"],
                        box=int(box or 0),
                        key=str(key),
                    )
            result.settings["magic"]["spell_slots"] = slots
            result.settings["other"]["notes"] = self.notes.get("1.0", "end-1c")
            result.weekdays = [
                day for day, variable in enumerate(self.weekday_vars) if variable.get()
            ]
            result.settings.setdefault("recovery", {})["recovery_enabled"] = True
            self._snapshot_hp_actions_from_rows()
            recovery = result.settings.setdefault("recovery", {})
            recovery["hp_actions"] = self._normalize_hp_actions_for_ui(self._hp_actions)
            legacy = sync_legacy_from_actions(recovery["hp_actions"])
            recovery["hp_recover_enabled"] = True
            recovery["use_heal"] = bool(legacy["use_heal"])
            recovery["use_hp_potion"] = bool(legacy["use_hp_potion"])
            recovery["hp_potion_below"] = int(legacy["hp_potion_below"])
            recovery["escape_hp_below"] = int(legacy["escape_hp_below"])
            hunt = result.settings.setdefault("hunt", {})
            hunt["return_hp_enabled"] = False
            hunt["return_enabled"] = True
            account_label = str(self.vars["task.account_id"].get()).strip()
            if account_label:
                result.name = account_label[:80]
            # Enabled lives on the schedule-list checkbox, not the form. Keep the
            # live list value so Update / Start commit cannot wipe it back off.
            editing_id = getattr(self.app, "_editing_id", None)
            if editing_id:
                live = next(
                    (task for task in self.app.tasks if task.id == editing_id),
                    None,
                )
                if live is not None:
                    result.enabled = bool(live.enabled)
            self.task.enabled = bool(result.enabled)
            return ScheduleTask.from_dict(result.to_dict())
        except (tk.TclError, TypeError, ValueError):
            messagebox.showwarning(
                self.t["title"], self.t["invalid_value"], parent=self.app
            )
            return None

    def set_commit_mode(self, editing: bool) -> None:
        self.identity_box.configure(
            text=self.t["edit_schedule"] if editing else self.t["task_details"]
        )
        self.commit_button.configure(
            text=self.t["update_schedule"] if editing else self.t["add_schedule"]
        )

    def begin_new(self) -> None:
        """Clear the form so the next commit creates a schedule."""
        self.app._editing_id = None
        self.app._creating_new = True
        task = self.app.store.create(self.app.profile)
        task.name = ""
        task.account_id = None
        task.server = ""
        self.load(task)
        self.set_commit_mode(False)
        self.app._begin_ignore_schedule_select()
        self.app._nav_lock += 1
        try:
            selected = self.app.tree.selection()
            if selected:
                self.app.tree.selection_remove(selected)
        except tk.TclError:
            pass
        finally:
            self.app._nav_lock -= 1
        try:
            self.account_combo.focus_set()
        except tk.TclError:
            pass

    def _blank(self, value: object) -> bool:
        text = str(value or "").strip()
        return not text or text == self.t["value_empty"]

    def missing_required_fields(self) -> list[str]:
        """Labels of New schedule fields that are still empty."""
        missing: list[str] = []
        if self._blank(self.vars["task.account_id"].get()):
            missing.append(self.t["account"])
        if self._blank(self.order_display.get()):
            missing.append(self.t["character_order"])
        if self._blank(self.type_display.get()):
            missing.append(self.t["character_type"])
        if self._blank(self.server_display.get()):
            missing.append(self.t["server"])
        if str(self.vars["task.time_mode"].get()) == "duration":
            try:
                if int(self.vars["task.duration_minutes"].get()) < 1:
                    missing.append(self.t["duration_choice"])
            except (tk.TclError, TypeError, ValueError):
                missing.append(self.t["duration_choice"])
        else:
            if self._blank(self.vars["task.start_time"].get()):
                missing.append(self.t["start_time"])
            if self._blank(self.vars["task.end_time"].get()):
                missing.append(self.t["end_time"])
        if not any(variable.get() for variable in self.weekday_vars):
            missing.append(self.t["weekdays"])
        return missing

    def warn_required_fields(self, missing: list[str] | None = None) -> list[str]:
        """Show the required-fields box. Returns the missing labels (empty if complete)."""
        fields = list(missing) if missing is not None else self.missing_required_fields()
        if not fields:
            return []
        messagebox.showwarning(
            self.t["title"],
            self.t["required_fields"].format(fields="\n".join(fields)),
            parent=self.app,
        )
        try:
            self.account_combo.focus_set()
        except tk.TclError:
            pass
        return fields

    def commit(self, *, confirm_create: bool = True, confirm_update: bool = True, restart_new: bool = True) -> bool:
        """Add the form as a new list row, or save the schedule being edited."""
        editing = self.app._editing_id
        if not editing:
            if self.warn_required_fields():
                return False
            if confirm_create and not self.app._ask_yes_no(self.t["confirm_create_schedule"]):
                return False
        elif confirm_update and not self.app._ask_yes_no(self.t["confirm_update_schedule"]):
            return False
        task = self.collect()
        if task is None:
            return False
        editing = self.app._editing_id
        if editing:
            task.id = editing
            index = next(
                (i for i, item in enumerate(self.app.tasks) if item.id == editing),
                None,
            )
            if index is None:
                self.app.tasks.append(task)
                index = len(self.app.tasks) - 1
            else:
                self.app.tasks[index] = task
            self.app._persist(index)
            self.app.footer_status.configure(text=self.t["saved"])
            return True
        # Persist selects the new row; ignore that so Add does not also open
        # the leave-new dialog (a second, similar confirmation).
        self.app._begin_ignore_schedule_select()
        self.app.tasks.append(task)
        self.app._persist(len(self.app.tasks) - 1)
        self.app.footer_status.configure(text=self.t["schedule_added"])
        if restart_new:
            self.begin_new()
        else:
            self.app._creating_new = False
        return True

    def save(self) -> None:
        self.commit()


# Header status strip. Inactive stays gray; a live probe or a running bot is green.
# Pause keeps a warm tone so it does not read as stopped.
_STRIP_OFF = ("#e6e9ee", "#5c6570")
_STRIP_ON = ("#128a43", "#ffffff")
_STRIP_HOLD = ("#f4e4c4", "#8a5a00")


def _strip_colors(mode: str) -> tuple[str, str]:
    if mode == "on":
        return _STRIP_ON
    if mode == "hold":
        return _STRIP_HOLD
    return _STRIP_OFF


def _game_chip_text(detail: str, lamp: Lamp, texts: dict[str, str]) -> str:
    if lamp == Lamp.GREEN:
        return texts["chip_game_on"]
    text = str(detail or "")
    if text == "Game window is minimized":
        return texts["chip_game_min"]
    if text == "Game is not in focus":
        return texts["chip_game_focus"]
    if text == "Cursor is outside the game window":
        return texts["chip_game_cursor"]
    if text.startswith("Game probe failed"):
        return texts["chip_game_error"]
    return texts["chip_game_off"]


def _memory_chip_text(detail: str, lamp: Lamp, texts: dict[str, str]) -> str:
    if lamp == Lamp.GREEN:
        return texts["chip_mem_on"]
    if "waiting for player" in str(detail or ""):
        return texts["chip_mem_wait"]
    return texts["chip_mem_off"]


def _map_chip_text(map_probe, texts: dict[str, str], selected_farms: list[str]) -> str:
    if map_probe.lamp == Lamp.GREEN:
        if map_probe.dungeon:
            count = int(map_probe.patrol_count or 0)
        else:
            names = set(map_probe.farm_names or [])
            count = len([name for name in selected_farms if name in names])
        title = str(map_probe.map_name or "").strip() or texts["chip_map_on"]
        return texts["chip_place"].format(title=title, n=count)
    if map_probe.dungeon:
        return texts["chip_patrol_off"]
    if not str(map_probe.map_name or "").strip():
        return texts["chip_map_off"]
    return texts["chip_farm_off"]


class ScheduleWindow(tk.Tk):
    """Exactly one application root containing schedule and operator controls."""

    def __init__(self, profile: Profile | None = None, store: ScheduleStore | None = None) -> None:
        super().__init__()
        # Hide until final geometry sticks. Otherwise Windows briefly maps the
        # default ~200x200 Tk window, then jumps to 1187x806 (small→large flash).
        try:
            self.withdraw()
        except tk.TclError:
            pass
        self._window_revealed = False
        ensure_userdata()
        self.profile = profile or load_profile()
        self.store = store or ScheduleStore()
        self.language = ui_language(self.profile.language)
        self.profile.language = self.language
        load_bundled_fonts(self.language)
        self.t = tr(self.language)
        self.tasks = self.store.load()
        self._editing_id: str | None = None
        self._creating_new = False
        self._nav_lock = 0
        self._prompting = False
        self._ignore_schedule_select = False
        self._tree_user_click = False
        self._session = ScheduleSession()
        self._power_buttons: dict[str, ttk.Button] = {}
        self._power_layout_token = 0
        self._login_not_before = 0.0
        self._schedule_ready = False
        self._notice_tip: tk.Toplevel | None = None
        self.log_widget: tk.Text | None = None
        self._log_lines: list[str] = []
        self._closing = False
        self._debug_win = None
        apply_classic_style(self, self.language)
        self._sync_font_aliases()
        self.title(self.t["console_title"])
        self._apply_brand_icon()
        self.configure(background=BG)
        self.resizable(True, True)
        _disable_window_maximize(self)
        self._place_window()
        self._ui_scale = ui_theme.UI_SCALE
        self._scale_job = ""
        self.bind("<Configure>", self._on_window_configure)
        self.bind("<Map>", self._on_window_map, add="+")
        self.attributes("-topmost", bool(self.profile.always_on_top))
        self.coordinator = self._open_coordinator()
        self._build()
        self._refresh()
        # Sensitive data (profile + tasks) is already in memory. Fill the first
        # schedule form while still withdrawn so the first visible frame has
        # layout groups and fields — not an empty shell that populates later.
        # Heavy Hunt/Magic icons stay lazy (tab open + background warmup).
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(250, self._poll)
        self._bootstrap_initial_editor()
        self._reveal_window()

    def _reveal_window(self) -> None:
        """Show only after size + initial form are ready (no empty/flashy first paint)."""
        self._place_window()
        try:
            self.update_idletasks()
            self._place_window()
        except tk.TclError:
            pass
        try:
            self.deiconify()
            self.lift()
        except tk.TclError:
            pass
        _disable_window_maximize(self)
        self._window_revealed = True

    @staticmethod
    def _sync_font_aliases() -> None:
        """Refresh explicit Tk label fonts after changing the UI language."""
        global FONT_BODY, FONT_SECTION
        FONT_BODY = ui_theme.FONT_BODY
        FONT_SECTION = ui_theme.FONT_SECTION

    def _on_window_map(self, _event: tk.Event | None = None) -> None:
        _disable_window_maximize(self)

    def _undo_maximize(self) -> bool:
        """Return True when the window was maximized and has been restored."""
        try:
            zoomed = str(self.state()) == "zoomed"
        except tk.TclError:
            return False
        if not zoomed:
            return False
        if getattr(self, "_undoing_maximize", False):
            return True
        self._undoing_maximize = True
        try:
            self.state("normal")
        except tk.TclError:
            pass
        finally:
            self._undoing_maximize = False
        _disable_window_maximize(self)
        return True

    def _place_window(self) -> None:
        """Open at 1187×806, centered. Drag-resize stays on; maximize does not."""
        width = ui_theme.DEFAULT_WIDTH
        height = ui_theme.DEFAULT_HEIGHT
        work_w = self.winfo_screenwidth()
        work_h = self.winfo_screenheight()
        try:
            from ctypes import wintypes

            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
            work_w = max(width, rect.right - rect.left)
            work_h = max(height, rect.bottom - rect.top)
        except (AttributeError, OSError):
            pass
        self.minsize(ui_theme.MIN_WIDTH, ui_theme.MIN_HEIGHT)
        x = max(0, (work_w - width) // 2)
        y = max(0, (work_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        ui_theme.refresh_ui_scale(
            self, self.language, ui_theme.compute_ui_scale(width, height)
        )
        self._sync_font_aliases()

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._undo_maximize():
            return
        # Ignore size events while hidden / before reveal (stale 200x200 configs).
        if not getattr(self, "_window_revealed", False):
            return
        try:
            if int(event.width) < ui_theme.MIN_WIDTH or int(event.height) < ui_theme.MIN_HEIGHT:
                return
        except (TypeError, ValueError):
            return
        job = getattr(self, "_scale_job", "")
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._scale_job = self.after(80, self._apply_window_scale)

    def _apply_window_scale(self) -> None:
        self._scale_job = ""
        try:
            width = max(1, int(self.winfo_width()))
            height = max(1, int(self.winfo_height()))
        except tk.TclError:
            return
        scale = ui_theme.compute_ui_scale(width, height)
        previous = float(getattr(self, "_ui_scale", 0.0) or 0.0)
        if abs(scale - previous) < 0.02:
            self._fit_panes(width)
            return
        self._ui_scale = scale
        ui_theme.refresh_ui_scale(self, self.language, scale)
        self._sync_font_aliases()
        self._apply_scaled_metrics()
        self._fit_panes(width)

    def _apply_scaled_metrics(self) -> None:
        """Keep tables, summaries, and row heights in step with the window."""
        style = ttk.Style(self)
        style.configure(
            "Hunt.Treeview", rowheight=_hunt_row_height(), font=ui_theme.FONT_BODY,
        )
        style.configure("Map.Treeview", rowheight=ui_theme.scaled(30, 18), indent=0)
        style.configure(
            "Accounts.Treeview",
            rowheight=ui_theme.scaled(30, 18),
            font=ui_theme.FONT_BODY,
        )
        style.configure(
            "Accounts.Treeview.Heading",
            padding=(ui_theme.scaled(8), ui_theme.scaled(4)),
            font=ui_theme.FONT_SECTION,
        )
        body = ui_theme.FONT_BODY
        owner = getattr(self, "editor", self)
        for name in (
            "attack_summary",
            "monsters_summary",
            "items_summary",
            "fix_summary",
            "magic_summary",
            "magic_pick_summary",
            "buy_summary",
        ):
            widget = getattr(owner, name, None)
            if widget is None:
                continue
            try:
                widget.configure(font=body)
                _configure_summary_text(widget)
            except tk.TclError:
                pass
        for name in ("state_label", "game_lamp", "memory_lamp", "map_lamp"):
            widget = getattr(self, name, None)
            if widget is None:
                continue
            try:
                widget.configure(font=body)
            except tk.TclError:
                pass

    def _fit_panes(self, total: int | None = None) -> None:
        if not hasattr(self, "paned"):
            return
        try:
            width = int(total or self.paned.winfo_width())
        except tk.TclError:
            return
        if width < 80:
            return
        left_min = max(520, ui_theme.scaled(720, 520))
        right_min = max(240, width - left_min)
        try:
            self.paned.paneconfigure(self.paned.panes()[0], minsize=left_min)
            self.paned.paneconfigure(self.paned.panes()[1], minsize=min(right_min, width - left_min))
        except (tk.TclError, IndexError):
            pass

    def _apply_brand_icon(self) -> None:
        """Use the original Manmabot icon for title bar and taskbar."""
        source = brand_icon_path()
        if source is None:
            return
        icon_path = source
        try:
            from PIL import Image

            if source.suffix.lower() != ".ico":
                icon_path = USERDATA / "window_icon.ico"
                image = Image.open(source).convert("RGBA")
                image.save(
                    icon_path,
                    format="ICO",
                    sizes=((16, 16), (32, 32), (48, 48), (256, 256)),
                )
            self.iconbitmap(default=str(icon_path))
            self.iconbitmap(str(icon_path))
        except Exception:
            pass
        try:
            from PIL import Image, ImageTk

            image = Image.open(source).convert("RGBA")
            self._brand_icon_photo = ImageTk.PhotoImage(image)
            self.iconphoto(True, self._brand_icon_photo)
        except Exception:
            pass

    def _status_segment(self, parent: tk.Misc, *, last: bool = False) -> tk.Label:
        """One flat cell in the header status strip."""
        label = tk.Label(
            parent,
            text="",
            background=_STRIP_OFF[0],
            foreground=_STRIP_OFF[1],
            font=FONT_BODY,
            padx=10,
            pady=3,
            anchor="center",
            borderwidth=0,
            highlightthickness=0,
        )
        label.pack(side="left", padx=(1, 1 if last else 0), pady=1)
        return label

    def _paint_status_chip(self, label: tk.Label, text: str, mode: str) -> None:
        background, foreground = _strip_colors(mode)
        try:
            label.configure(text=text, background=background, foreground=foreground)
        except tk.TclError:
            pass

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")
        status_strip = tk.Frame(header, background=BORDER, highlightthickness=0)
        status_strip.pack(side="left", padx=(2, 14), pady=1)
        self.state_label = self._status_segment(status_strip)
        self.game_lamp = self._status_segment(status_strip)
        self.memory_lamp = self._status_segment(status_strip)
        self.map_lamp = self._status_segment(status_strip, last=True)
        self.power_btn = ttk.Button(
            header, text=self.t["start"], image=self._run_glyph("start"),
            compound="left", command=self._toggle_run,
        )
        self.stop_btn = ttk.Button(
            header, text=self.t["stop"], image=self._run_glyph("stop"),
            compound="left", command=self.coordinator.stop,
        )
        header_buttons = [self.stop_btn, self.power_btn]
        self.debug_btn = None
        if not is_portable():
            self.debug_btn = ttk.Button(header, text=self.t["debug"], command=self.open_debug)
            header_buttons.append(self.debug_btn)
        for button in header_buttons:
            button.pack(side="right", padx=2)
        self.topmost_var = tk.BooleanVar(self, value=self.profile.always_on_top)
        ttk.Checkbutton(
            header,
            text=self.t["always_on_top"],
            variable=self.topmost_var,
            command=self._toggle_topmost,
            style="Chrome.TCheckbutton",
        ).pack(side="right", padx=6)
        language = ttk.Combobox(header, state="readonly", width=11, values=list(LANGUAGES))
        language.pack(side="right", padx=8)
        show_combobox_value(language, LANGUAGE_NAMES[self.language], list(LANGUAGES))
        language.bind("<<ComboboxSelected>>", lambda _e: self._set_language(LANGUAGES[language.get()]))
        ttk.Button(
            header,
            text=self.t["manage_accounts"],
            command=self.open_accounts,
        ).pack(side="right", padx=4)

        paned = ttk.Panedwindow(self, orient="horizontal")
        self.paned = paned
        paned.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        left = ttk.Frame(paned, padding=(0, 4, 0, 4))
        right = ttk.Frame(paned, padding=(0, 4, 0, 4))
        paned.add(left, weight=2)
        paned.add(right, weight=5)
        try:
            paned.paneconfigure(left, minsize=140)
            paned.paneconfigure(right, minsize=240)
        except tk.TclError:
            pass
        self._build_schedule(left)
        self.editor = UnifiedTaskEditor(right, self)
        self.editor.pack(fill="both", expand=True)
        self._panes_balanced = False
        self.after_idle(self._balance_panes)
        self.after_idle(self._apply_window_scale)

        bottom = ttk.Frame(self, padding=5, style="Chrome.TFrame")
        bottom.pack(fill="x")
        self.footer_status = ttk.Label(
            bottom, text="", foreground=TEXT_MUTED,
            style="Chrome.TLabel",
        )
        self.footer_status.pack(side="left")

    def _balance_panes(self) -> None:
        """Keep the schedule list and the New schedule form on screen together."""
        if self._panes_balanced:
            return
        try:
            total = self.paned.winfo_width()
        except tk.TclError:
            return
        if total < 80:
            self.after(50, self._balance_panes)
            return
        # Room for the time controls and the account form side by side.
        left_min = max(520, ui_theme.scaled(720, 520))
        left_width = int(round(total * 0.52))
        left_width = min(max(left_width, left_min), max(left_min, total - 240))
        self.paned.sashpos(0, left_width)
        self._panes_balanced = True
        self._fit_panes(total)

    def _flow_buttons(
        self,
        parent: ttk.Frame,
        items: tuple[tuple[str, object], ...],
        *,
        columns: int | None = None,
    ) -> None:
        """Keep every toolbar button fully visible, wrapping onto extra rows."""
        buttons = []
        for text, command in items:
            button = ttk.Button(parent, text=text, command=command, padding=(6, 2))
            buttons.append(button)

        forced = max(1, int(columns)) if columns else None
        if forced is not None:
            for column in range(forced):
                parent.columnconfigure(column, weight=1, uniform="schedflow")

        def reflow(event: tk.Event | None = None) -> None:
            width = parent.winfo_width() if event is None else int(event.width)
            if width <= 1 and forced is None:
                return
            if forced is not None:
                for index, button in enumerate(buttons):
                    button.grid(
                        row=index // forced,
                        column=index % forced,
                        padx=(0, 3),
                        pady=2,
                        sticky="ew",
                    )
                return
            x = 0
            row = 0
            column = 0
            for button in buttons:
                need = button.winfo_reqwidth() + 6
                if column and x + need > width:
                    row += 1
                    column = 0
                    x = 0
                button.grid(row=row, column=column, padx=(0, 4), pady=2, sticky="w")
                column += 1
                x += need

        parent.bind("<Configure>", reflow)
        parent.after_idle(reflow)

    def _build_schedule(self, parent) -> None:
        box = group(parent, self.t["master_schedules"])
        box.pack(fill="both", expand=True)
        self.schedule_timing_host = ttk.Frame(box)
        self.schedule_timing_host.pack(fill="x", padx=2, pady=(2, 0))
        ttk.Separator(box, orient="horizontal").pack(fill="x", pady=(4, 6))
        table = ttk.Frame(box)
        table.pack(fill="both", expand=True)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        column_ids = tuple(item[0] for item in _SCHEDULE_COLUMNS)
        self.tree = ttk.Treeview(
            table,
            columns=column_ids,
            show="headings",
            selectmode="browse",
            style="Grid.Treeview",
        )
        for col, heading, width in _SCHEDULE_COLUMNS:
            self.tree.heading(col, text=self.t.get(heading, heading), anchor="center")
            anchor = "center" if col == "enabled" else "w"
            self.tree.column(col, width=width, minwidth=48 if col == "enabled" else 56, stretch=False, anchor=anchor)
        y_scroll = ttk.Scrollbar(table, orient="vertical")
        x_scroll = ttk.Scrollbar(table, orient="horizontal")

        def yset(*args: str) -> None:
            y_scroll.set(*args)
            _refresh_cell_grid(self.tree)
            self._layout_power_buttons()

        def xset(*args: str) -> None:
            x_scroll.set(*args)
            _refresh_cell_grid(self.tree)
            self._layout_power_buttons()

        y_scroll.configure(command=self.tree.yview)
        x_scroll.configure(command=self.tree.xview)
        self.tree.configure(yscrollcommand=yset, xscrollcommand=xset)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        _enable_bbox_grid(self.tree)
        self._schedule_check_on = checkbox_image(self.tree, True)
        self._schedule_check_off = checkbox_image(self.tree, False)
        self.tree.bind("<Double-1>", self._edit_schedule_row)
        self.tree.bind("<ButtonPress-1>", self._mark_schedule_user_click, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._on_schedule_select)
        self.tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._layout_power_buttons(), add="+",
        )
        _fit_tree_columns(self.tree)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 3))
        self._flow_buttons(
            row,
            (
                ("▲", lambda: self._move(-1)),
                ("▼", lambda: self._move(1)),
                (self.t["new"], self._new),
                (self.t["edit"], self.edit_selected_task),
                (self.t["duplicate"], self._duplicate),
                (self.t["delete"], self._delete),
            ),
            columns=3,
        )
        clock = ttk.Frame(box)
        clock.pack(fill="x", pady=(1, 3))
        ttk.Label(clock, text=self.t["current_time"]).pack(side="left")
        self.current_time_var = tk.StringVar(self, value=datetime.now().strftime("%H:%M:%S"))
        ttk.Label(
            clock,
            textvariable=self.current_time_var,
            width=8,
            font=FONT_BODY,
        ).pack(side="left", padx=3)
        self._start_clock()
        self.randomize_var = tk.BooleanVar(self, value=bool(self.store.randomize_enabled))
        ttk.Checkbutton(
            clock, text=self.t["randomize"], variable=self.randomize_var
        ).pack(side="left", padx=(5, 1))
        self.random_minutes_var = tk.IntVar(self, value=int(self.store.randomize_minutes or 0))
        ttk.Spinbox(
            clock, from_=0, to=120, width=4, textvariable=self.random_minutes_var
        ).pack(side="left")
        self.randomize_var.trace_add("write", self._save_randomize)
        self.random_minutes_var.trace_add("write", self._save_randomize)

    def _start_clock(self) -> None:
        """Refresh the local clock. A new build cancels the previous timer."""
        self._clock_token = getattr(self, "_clock_token", 0) + 1
        token = self._clock_token

        def tick() -> None:
            if self._closing or token != self._clock_token:
                return
            try:
                self.current_time_var.set(datetime.now().strftime("%H:%M:%S"))
            except tk.TclError:
                return
            self.after(200, tick)

        tick()

    def _selected(self) -> int | None:
        selection = self.tree.selection()
        iid = selection[0] if selection else self.tree.focus()
        try:
            index = int(iid)
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(self.tasks):
            return index
        return None

    def _refresh(self, select: int | None = None) -> None:
        self._clear_power_buttons()
        self.tree.delete(*self.tree.get_children())
        self._map_labels = {
            map_id: label for map_id, label, _dungeon in list_map_choices(self.language)
        }
        try:
            accounts = AccountStore().load()
        except Exception:
            accounts = []
        self._accounts_by_id = {account.account_id: account for account in accounts}
        for index, task in enumerate(self.tasks):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=tuple(
                    self._schedule_cell(task, column)
                    for column, _heading, _width in _SCHEDULE_COLUMNS
                ),
            )
        if self.tasks:
            index = select if select is not None and 0 <= select < len(self.tasks) else 0
            self._nav_lock += 1
            try:
                self.tree.selection_set(str(index))
                self.tree.focus(str(index))
                self.tree.see(str(index))
            finally:
                self._nav_lock -= 1
        _refresh_cell_grid(self.tree)
        _fit_tree_columns(self.tree)
        self._layout_power_buttons()
        self._refresh_operator()

    def _as_cell(self, value: Any) -> str:
        if isinstance(value, bool):
            return self.t["yes"] if value else self.t["no"]
        if isinstance(value, list):
            return ", ".join(self._as_cell(item) for item in value)
        if isinstance(value, dict):
            return ", ".join(f"{key}={self._as_cell(item)}" for key, item in value.items())
        return str(value if value is not None else "").replace("\n", " ")

    def _schedule_cell(self, task: ScheduleTask, column: str) -> str:
        if column == "name":
            return task.name
        if column == "account":
            account = self._accounts_by_id.get(task.account_id or "")
            if account is None:
                return self.t["value_empty"]
            return account.display_name or account.username
        if column == "enabled":
            return ""
        if column == "when":
            if task.time_mode == "duration":
                return f"{task.duration_minutes} {self.t['minutes']}"
            return f"{task.start_time}~{task.end_time}"
        if column == "character":
            return self.t.get(task.character, task.character)
        if column == "time_mode":
            return self.t["time_choice"] if task.time_mode == "window" else self.t["duration_choice"]
        if column == "weekdays":
            names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            return " ".join(self.t[names[day]] for day in task.weekdays if 0 <= day < len(names))
        if column in {"repeat_daily"}:
            return self.t["yes"] if getattr(task, column) else self.t["no"]
        if column in {"server", "start_time", "end_time", "duration_minutes", "character_slot", "role"}:
            return self._as_cell(getattr(task, column))
        if "." not in column:
            return self._as_cell(getattr(task, column, ""))
        section, key = column.split(".", 1)
        value = task.settings.get(section, {}).get(key, "")
        if column == "move.map_id":
            return self._map_labels.get(str(value), self._as_cell(value))
        if column == "hunt.attack_mode":
            labels = {"ranged": "ranged", "magic": "magic_attack", "melee": "melee"}
            return self.t.get(labels.get(str(value), ""), self._as_cell(value))
        if column == "hunt.species_sort":
            return self.t["sort_level"] if value == "level" else self.t["sort_name"]
        if column == "hunt.species_blacklist":
            names = value if isinstance(value, list) else []
            return ", ".join(species_display_name_ui(str(item), self.language) for item in names)
        if column == "hunt.species_levels":
            levels = value if isinstance(value, dict) else {}
            return ", ".join(
                f"{species_display_name_ui(str(key), self.language)}={level}"
                for key, level in levels.items()
            )
        if column == "other.loot_mode":
            return self.t.get(str(value), self._as_cell(value))
        if column == "other.game_language":
            if value == "zh":
                return self.t["game_chinese"]
            if value == "ko":
                return self.t["game_korean"]
            return self._as_cell(value)
        return self._as_cell(value)

    def _persist(self, select: int | None = None) -> None:
        self.store.save(self.tasks)
        self._refresh(select)

    def reload_selected(self) -> None:
        index = self._selected()
        if index is not None:
            self.editor.load(self.tasks[index])

    def edit_selected_task(self) -> None:
        """Load the selected schedule into the form so it can be changed."""
        index = self._selected()
        if index is None:
            messagebox.showinfo(
                self.t["title"], self.t["select_schedule"], parent=self,
            )
            return
        self._request_open(index)

    def _open_initial_editor(self) -> None:
        if self.tasks:
            self._open_edit_index(0)
        else:
            self.editor.begin_new()

    def _bootstrap_initial_editor(self) -> None:
        """Fill the first schedule form before the window is shown (UI-only timing)."""
        if self._closing or self._schedule_ready:
            return
        try:
            self._open_initial_editor()
        finally:
            self._schedule_ready = True
            self._refresh_operator()

    def _open_edit_id(self, task_id: str) -> None:
        index = next((i for i, item in enumerate(self.tasks) if item.id == task_id), None)
        if index is not None:
            self._open_edit_index(index)

    def _open_edit_index(self, index: int) -> None:
        task = self.tasks[index]
        self._creating_new = False
        self._editing_id = task.id
        self._nav_lock += 1
        try:
            self.tree.selection_set(str(index))
            self.tree.focus(str(index))
            self.tree.see(str(index))
        except tk.TclError:
            pass
        finally:
            self._nav_lock -= 1
        self.editor.load(task)
        self.editor.set_commit_mode(True)
        try:
            self.editor.account_combo.focus_set()
        except tk.TclError:
            pass

    def _restore_list_highlight(self) -> None:
        self._nav_lock += 1
        try:
            if self._editing_id and not self._creating_new:
                index = next(
                    (i for i, item in enumerate(self.tasks) if item.id == self._editing_id),
                    None,
                )
                if index is not None:
                    self.tree.selection_set(str(index))
                    self.tree.focus(str(index))
                    return
            selected = self.tree.selection()
            if selected:
                self.tree.selection_remove(selected)
        except tk.TclError:
            pass
        finally:
            self._nav_lock -= 1

    def _choice_dialog(self, message: str, choices: tuple[tuple[str, str], ...]) -> str:
        """One modal question, centered on this window and kept in front of it."""
        if self._prompting:
            return choices[-1][0]
        self._prompting = True
        try:
            dialog = tk.Toplevel(self)
            dialog.withdraw()
            dialog.title(self.t["title"])
            dialog.transient(self)
            dialog.resizable(False, False)
            body = ttk.Frame(dialog, padding=(18, 16, 18, 14))
            body.pack(fill="both", expand=True)
            ttk.Label(
                body, text=message, wraplength=420, justify="left",
            ).pack(anchor="w")
            row = ttk.Frame(body)
            row.pack(anchor="e", pady=(16, 0))
            result = {"value": choices[-1][0]}

            def pick(value: str) -> None:
                result["value"] = value
                dialog.destroy()

            for choice_id, label in choices:
                ttk.Button(
                    row,
                    text=label,
                    width=max(10, len(label) + 2),
                    command=lambda value=choice_id: pick(value),
                ).pack(side="left", padx=(0, 6))
            dialog.protocol("WM_DELETE_WINDOW", lambda: pick(choices[-1][0]))
            dialog.bind("<Escape>", lambda _event: pick(choices[-1][0]))
            dialog.bind("<Return>", lambda _event: pick(choices[0][0]))
            dialog.update_idletasks()
            width = max(dialog.winfo_reqwidth(), 420)
            height = max(dialog.winfo_reqheight(), 1)
            x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
            y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
            dialog.geometry(f"{width}x{height}+{x}+{y}")
            dialog.deiconify()
            dialog.lift()
            try:
                dialog.attributes("-topmost", True)
            except tk.TclError:
                pass
            dialog.grab_set()
            dialog.focus_set()
            self.wait_window(dialog)
            try:
                self.lift()
            except tk.TclError:
                pass
            return result["value"]
        finally:
            self._prompting = False

    def _ask_yes_no(self, message: str) -> bool:
        choice = self._choice_dialog(
            message,
            (("yes", self.t["choice_yes"]), ("no", self.t["choice_no"])),
        )
        return choice == "yes"

    def _begin_ignore_schedule_select(self) -> None:
        """Ignore TreeviewSelect until idle so leave/save cannot re-prompt."""
        self._ignore_schedule_select = True
        self._nav_lock += 1

        def release() -> None:
            if self._nav_lock > 0:
                self._nav_lock -= 1
            self._ignore_schedule_select = False

        self.after_idle(release)

    def _confirm_leave(self, proceed) -> bool:
        """Ask before leaving a new draft or an open edit. ``proceed`` runs on Save/Add or Discard."""
        creating = self._creating_new
        if not creating and not self._editing_id:
            proceed()
            return True
        if not self.editor.form_is_dirty():
            self._begin_ignore_schedule_select()
            proceed()
            return True
        if creating:
            missing = self.editor.missing_required_fields()
            if missing:
                choice = self._choice_dialog(
                    self.t["required_fields_leave"].format(fields="\n".join(missing)),
                    (
                        ("discard", self.t["choice_discard"]),
                        ("cancel", self.t["choice_cancel"]),
                    ),
                )
                if choice != "discard":
                    try:
                        self.editor.account_combo.focus_set()
                    except tk.TclError:
                        pass
                    return False
                self._begin_ignore_schedule_select()
                self._creating_new = False
                proceed()
                return True
            message = self.t["confirm_leave_new"]
            keep = ("save", self.t["choice_add"])
        elif self._editing_id:
            message = self.t["confirm_leave_edit"]
            keep = ("save", self.t["choice_save"])
        else:
            proceed()
            return True
        choice = self._choice_dialog(
            message,
            (
                keep,
                ("discard", self.t["choice_discard"]),
                ("cancel", self.t["choice_cancel"]),
            ),
        )
        if choice == "cancel":
            return False

        # Hold nav lock through save + navigate so a deferred TreeviewSelect
        # from persist/refresh cannot open a second leave prompt.
        self._begin_ignore_schedule_select()
        if choice == "save":
            if not self.editor.commit(
                confirm_create=False, confirm_update=False, restart_new=False,
            ):
                return False
        else:
            self._creating_new = False
        proceed()
        return True

    def _request_open(self, index: int) -> None:
        if self._prompting or self._ignore_schedule_select:
            return
        if not 0 <= index < len(self.tasks):
            return
        target_id = self.tasks[index].id
        if not self._creating_new and self._editing_id == target_id:
            return

        def go() -> None:
            self._open_edit_id(target_id)

        if self._creating_new or (self._editing_id and self._editing_id != target_id):
            if not self._confirm_leave(go):
                self._restore_list_highlight()
            return
        go()

    def _mark_schedule_user_click(self, _event: object = None) -> None:
        self._tree_user_click = True

    def _on_schedule_select(self, _event: object = None) -> None:
        user_click = self._tree_user_click
        self._tree_user_click = False
        if (
            self._nav_lock
            or self._prompting
            or self._ignore_schedule_select
            or not self._schedule_ready
        ):
            return
        # After leaving an edit to start a new draft, persist/highlight can
        # fire TreeviewSelect. That is not "edit another schedule".
        if self._creating_new and not user_click:
            self._restore_list_highlight()
            return
        index = self._selected()
        if index is None:
            return
        self._request_open(index)

    def _edit_schedule_row(self, event: tk.Event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        column = self.tree.identify_column(event.x)
        enabled_index = list(self.tree["columns"]).index("enabled") + 1
        if column == f"#{enabled_index}":
            return "break"
        return "break"

    def _new(self) -> None:
        if self._creating_new or self._prompting or self._ignore_schedule_select:
            return

        def go() -> None:
            self.editor.begin_new()

        if self._editing_id:
            if not self._confirm_leave(go):
                self._restore_list_highlight()
            return
        go()

    def _duplicate(self) -> None:
        index = self._selected()
        if index is not None:
            self.tasks.insert(index + 1, self.store.duplicate(self.tasks[index]))
            self._persist(index + 1)

    def _delete(self) -> None:
        index = self._selected()
        if index is None or not messagebox.askyesno(self.t["title"], self.t["confirm_delete"], parent=self):
            return
        removed = self.tasks[index].id
        was_editing = self._editing_id == removed
        del self.tasks[index]
        if was_editing:
            self._editing_id = None
        self._persist(min(index, len(self.tasks) - 1) if self.tasks else None)
        if was_editing:
            self.editor.begin_new()

    def _move(self, direction: int) -> None:
        index = self._selected()
        target = index + direction if index is not None else -1
        if index is not None and 0 <= target < len(self.tasks):
            self.tasks[index], self.tasks[target] = self.tasks[target], self.tasks[index]
            self._persist(target)

    def apply_task(self, task: ScheduleTask, *, interactive: bool = True) -> bool:
        if (
            self.coordinator.arming
            or self.coordinator.controller.state != RunState.STOPPED
        ):
            if interactive:
                messagebox.showwarning(
                    self.t["title"], self.t["stop_to_apply"], parent=self
                )
            return False
        count = len(apply_runtime_settings(task, self.profile))
        try:
            valid_account = (
                task.account_id
                if task.account_id and AccountStore().get(task.account_id) is not None
                else None
            )
        except Exception:
            valid_account = None
        if valid_account and self.profile.selected_account_id != valid_account:
            self.profile.selected_account_id = valid_account
            count += 1
        save_profile(self.profile)
        self.coordinator.invalidate_map_probe()
        self.footer_status.configure(text=self.t["applied"].format(count=count))
        self._refresh_operator()
        return True

    def _run_glyph(self, kind: str) -> tk.PhotoImage:
        icons = getattr(self, "_run_icons", None)
        if icons is None:
            self._run_icons = {}
            icons = self._run_icons
        image = icons.get(kind)
        if image is not None:
            return image
        image = tk.PhotoImage(master=self, width=16, height=16)
        image.blank()
        color = ACCENT

        def triangle(x0: int) -> None:
            for y in range(3, 13):
                reach = 5 - abs(y - 7)
                if reach > 0:
                    image.put(color, to=(x0, y, x0 + reach, y + 1))

        if kind == "pause":
            image.put(color, to=(3, 3, 6, 13))
            image.put(color, to=(10, 3, 13, 13))
        elif kind == "resume":
            image.put(color, to=(2, 3, 5, 13))
            triangle(7)
        elif kind == "stop":
            image.put(color, to=(3, 3, 13, 13))
        else:
            triangle(5)
        icons[kind] = image
        return image

    def _toggle_run(self) -> None:
        state = self.coordinator.controller.state
        if state == RunState.RUNNING:
            self.coordinator.controller.pause_user()
            self._refresh_operator()
        elif state == RunState.PAUSED:
            self.coordinator.resume()
        else:
            self._start()

    def _game_is_up(self) -> bool:
        try:
            return probe_game().lamp != Lamp.RED
        except Exception:
            return False

    def _start_error_text(self, error: str) -> str:
        key = str(error or "").strip()
        if not key:
            return ""
        return self.t.get(key) or START_FAIL.get(key) or key

    def _report_start_error(self, error: str) -> None:
        text = self._start_error_text(error)
        self.append_log(text)
        if hasattr(self, "footer_status"):
            self.footer_status.configure(text=text)

    def _start(self) -> None:
        if self._editing_id:
            self.editor.commit(confirm_update=False)
        game_up = self._game_is_up()
        has_schedule = any(task.enabled for task in self.tasks)
        if not has_schedule and not game_up:
            messagebox.showwarning(
                self.t["title"], self.t["no_enabled_schedule"], parent=self
            )
            return
        if (
            has_schedule
            and self.coordinator.controller.state == RunState.STOPPED
            and not self.coordinator.arming
        ):
            self._session.arm()
            self._login_not_before = 0.0
            self._drive_schedule()
        if (
            game_up
            and self.coordinator.controller.state == RunState.STOPPED
            and not self.coordinator.arming
        ):
            error = self.coordinator.start(unattended=True)
            if error:
                self._report_start_error(error)
        self._refresh_operator()

    def _open_coordinator(self) -> OperatorCoordinator:
        coordinator = OperatorCoordinator(
            self.profile, dispatch=lambda fn: self.after(0, fn),
            on_change=self._refresh_operator, on_log=self.append_log,
            on_hotbar=self._on_hotbar,
        )
        coordinator.on_user_stop = self._disarm_schedule
        return coordinator

    def _disarm_schedule(self) -> None:
        self._session.disarm()
        self.coordinator.hold_recovery = False

    def _randomize_minutes(self) -> int:
        try:
            if not bool(self.randomize_var.get()):
                return 0
            return max(0, min(120, int(self.random_minutes_var.get())))
        except (tk.TclError, ValueError):
            return 0

    def _save_randomize(self, *_args: object) -> None:
        if not self._schedule_ready:
            return
        try:
            minutes = max(0, min(120, int(self.random_minutes_var.get())))
        except (tk.TclError, ValueError):
            return
        self.store.randomize_enabled = bool(self.randomize_var.get())
        self.store.randomize_minutes = minutes
        self.store.save(self.tasks)

    def _account_label(self, task: ScheduleTask | None) -> str:
        if task is None:
            return self.t["value_empty"]
        account = self._accounts_by_id.get(task.account_id or "")
        if account is None:
            try:
                account = AccountStore().get(task.account_id) if task.account_id else None
            except Exception:
                account = None
        if account is None:
            return self.t["value_empty"]
        return account.display_name or account.username or self.t["value_empty"]

    def _task_by_id(self, task_id: str | None) -> ScheduleTask | None:
        if not task_id:
            return None
        return next((task for task in self.tasks if task.id == task_id), None)

    def _show_schedule_status(self) -> None:
        if not hasattr(self, "footer_status"):
            return
        if not self._session.armed:
            return
        if self._session.active_id and self._session.switch_at:
            task = self._task_by_id(self._session.active_id)
            text = self.t["schedule_active"].format(
                account=self._account_label(task),
                time=self._session.switch_at.strftime("%H:%M:%S"),
            )
        else:
            text = self.t["schedule_waiting"]
        self.footer_status.configure(text=text)

    def _show_switch_notice(self, decision_time: datetime, task_id: str | None) -> None:
        when = decision_time.strftime("%H:%M:%S")
        nxt = self._task_by_id(task_id)
        if nxt is None:
            text = self.t["switch_notice_end"].format(time=when)
        else:
            text = self.t["switch_notice"].format(
                account=self._account_label(nxt), time=when
            )
        self.append_log(text)
        previous = self._notice_tip
        if previous is not None:
            try:
                if previous.winfo_exists():
                    previous.destroy()
            except tk.TclError:
                pass
        tip = tk.Toplevel(self)
        self._notice_tip = tip
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(background="#1e293b")
        tk.Label(
            tip,
            text=text,
            background="#1e293b",
            foreground="#f8fafc",
            padx=14,
            pady=10,
            font=FONT_BODY,
            justify="left",
        ).pack()
        tip.update_idletasks()
        x = self.winfo_rootx() + 24
        y = max(0, self.winfo_rooty() + self.winfo_height() - tip.winfo_reqheight() - 56)
        tip.geometry(f"+{max(0, x)}+{y}")
        _no_activate(tip)
        tip.after(20000, tip.destroy)

    def _drive_schedule(self) -> None:
        if not self._session.armed or self._closing or self._session.switching:
            return
        for _ in range(max(2, len(self.tasks) + 2)):
            decision = self._session.tick(
                datetime.now(),
                self.tasks,
                randomize_minutes=self._randomize_minutes(),
            )
            if decision.kind == "notify":
                upcoming = self._session.next_task_id(self.tasks)
                self._show_switch_notice(decision.switch_at or datetime.now(), upcoming)
                self._show_schedule_status()
                return
            if decision.kind == "begin":
                if self._login_scheduled(decision.task_id) == "retry":
                    continue
                self._show_schedule_status()
                return
            if decision.kind == "handover":
                self._begin_handover(decision.task_id)
                return
            if (
                self._session.active_id
                and self.coordinator.controller.state == RunState.STOPPED
                and not self.coordinator.arming
            ):
                self._login_scheduled(self._session.active_id)
            self._show_schedule_status()
            return

    def _login_scheduled(self, task_id: str | None) -> str:
        if not self._session.armed or not task_id:
            return "done"
        if self.coordinator.arming or self.coordinator.controller.state != RunState.STOPPED:
            return "done"
        now = time.monotonic()
        if now < self._login_not_before:
            return "done"
        task = self._task_by_id(task_id)
        if task is None:
            self._session.skip_current()
            return "retry"
        try:
            account = AccountStore().get(task.account_id) if task.account_id else None
        except Exception:
            account = None
        game_up = self._game_is_up()
        if account is None and not game_up:
            self.append_log(self.t["schedule_missing_account"])
            self._session.skip_current()
            return "retry"
        if account is None:
            self.append_log(self.t["start_without_login"])
        self._login_not_before = now + 15.0
        if not self.apply_task(task, interactive=False):
            return "done"
        error = self.coordinator.start(unattended=True)
        if error:
            self._report_start_error(error)
        return "done"

    def _begin_handover(self, task_id: str | None) -> None:
        self._session.switching = True
        self.coordinator.halt_for_switch()

        def work() -> None:
            try:
                self.coordinator.controller.wait_stopped(timeout=5.0)
            except Exception:
                pass
            try:
                close_game_client()
            except Exception as exc:
                detail = str(exc)
                self.after(0, lambda: self.append_log(detail))
            self.after(0, lambda: self._finish_handover(task_id))

        threading.Thread(target=work, name="schedule-switch", daemon=True).start()

    def _finish_handover(self, task_id: str | None) -> None:
        self._session.switching = False
        self.coordinator.hold_recovery = False
        if self._closing or not self._session.armed:
            return
        if task_id:
            if self._login_scheduled(task_id) == "retry":
                self._drive_schedule()
        else:
            self.append_log(self.t["schedule_waiting"])
        self._show_schedule_status()
        self._refresh_operator()

    def _clear_power_buttons(self) -> None:
        for button in self._power_buttons.values():
            try:
                button.destroy()
            except tk.TclError:
                pass
        self._power_buttons.clear()

    def _toggle_schedule_enabled(self, index: int) -> None:
        if not 0 <= index < len(self.tasks):
            return
        self._toggle_enabled(index, not self.tasks[index].enabled)
        self._place_power_buttons()

    def _toggle_enabled(self, index: int, enabled: bool) -> None:
        if not 0 <= index < len(self.tasks):
            return
        if self.tasks[index].enabled == enabled:
            return
        self.tasks[index].enabled = enabled
        # Keep the open editor clone in sync so Update/Start commit cannot
        # rewrite the checkbox state from a stale form snapshot.
        editor = getattr(self, "editor", None)
        task = getattr(editor, "task", None) if editor is not None else None
        if task is not None and task.id == self.tasks[index].id:
            task.enabled = enabled
        self.after_idle(lambda: self._persist(index))

    def _layout_power_buttons(self, retries: int = 6) -> None:
        self._power_layout_token += 1
        token = self._power_layout_token

        def run(left: int) -> None:
            if token != self._power_layout_token or self._closing:
                return
            if not self._place_power_buttons() and left > 0 and self.tree.get_children():
                self.after(50, lambda: run(left - 1))

        run(retries)

    def _place_power_buttons(self) -> bool:
        if not hasattr(self, "tree"):
            return False
        try:
            children = list(self.tree.get_children())
        except tk.TclError:
            return False
        wanted: list[tuple[str, tuple[int, int, int, int]]] = []
        for iid in children:
            box = self.tree.bbox(iid, "enabled")
            if box:
                wanted.append((iid, box))
        live = {iid for iid, _box in wanted}
        for iid, button in list(self._power_buttons.items()):
            if iid not in live:
                try:
                    button.destroy()
                except tk.TclError:
                    pass
                self._power_buttons.pop(iid, None)
        for iid, (x, y, width, height) in wanted:
            try:
                index = int(iid)
            except ValueError:
                continue
            if not 0 <= index < len(self.tasks):
                continue
            task = self.tasks[index]
            selected = iid in set(self.tree.selection())
            check = self._power_buttons.get(iid)
            if check is None or not check.winfo_exists():
                check = tk.Label(
                    self.tree,
                    bd=0,
                    highlightthickness=0,
                    cursor="hand2",
                )
                check.bind(
                    "<Button-1>",
                    lambda _event, i=index: self._toggle_schedule_enabled(i),
                )
                self._power_buttons[iid] = check
            check.configure(
                image=self._schedule_check_on if task.enabled else self._schedule_check_off,
                bg=ACCENT if selected else SURFACE,
            )
            box = 16
            check.place(
                x=x + max(0, (width - box) // 2),
                y=y + max(0, (height - box) // 2),
                width=box,
                height=box,
            )
            check.lift()
        self.after_idle(self._lift_enabled_checks)
        return bool(wanted) or not children

    def _lift_enabled_checks(self) -> None:
        for check in self._power_buttons.values():
            try:
                if check.winfo_exists():
                    check.lift()
            except tk.TclError:
                pass

    def open_debug(self) -> None:
        win = self._debug_win
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return
        from manmabot_v1.ui.debug_ui import DebugWindow

        self._debug_win = DebugWindow(
            self,
            controller=self.coordinator.controller,
            get_logs=lambda: list(self._log_lines),
            t=self.t,
            get_arming=lambda: self.coordinator.arming,
            on_close=lambda: setattr(self, "_debug_win", None),
        )

    def _close_debug(self) -> None:
        win = self._debug_win
        self._debug_win = None
        if win is None:
            return
        try:
            if win.winfo_exists():
                win._close()
                return
        except tk.TclError:
            pass
        try:
            self.coordinator.controller.remove_debug_watcher()
        except Exception:
            pass

    def _toggle_topmost(self) -> None:
        self.profile.always_on_top = bool(self.topmost_var.get())
        save_profile(self.profile)
        self.attributes("-topmost", self.profile.always_on_top)

    def _refresh_operator(self) -> None:
        self._paint_run_status()
        state = self.coordinator.controller.state
        scheduled = self._session.armed or self._session.switching
        try:
            game, memory, map_probe = self.coordinator.probes()
            key = (
                state,
                self.coordinator.arming,
                scheduled,
                getattr(self.coordinator.controller, "reason", ""),
                game.lamp,
                game.detail,
                memory.lamp,
                memory.detail,
                map_probe.lamp,
                map_probe.detail,
            )
            if key == getattr(self, "_operator_key", None):
                return
            self._operator_key = key
            editor = getattr(self, "editor", None)
            if editor is not None and hasattr(editor, "_show_status"):
                editor._show_status(game, memory, map_probe)
            selected = [str(name) for name in (self.profile.selected_farms or [])]
            self._paint_status_chip(
                self.game_lamp,
                _game_chip_text(game.detail, game.lamp, self.t),
                "on" if game.lamp == Lamp.GREEN else "off",
            )
            self._paint_status_chip(
                self.memory_lamp,
                _memory_chip_text(memory.detail, memory.lamp, self.t),
                "on" if memory.lamp == Lamp.GREEN else "off",
            )
            self._paint_status_chip(
                self.map_lamp,
                _map_chip_text(map_probe, self.t, selected),
                "on" if map_probe.lamp == Lamp.GREEN else "off",
            )
        except Exception:
            pass

    def _paint_run_status(self) -> None:
        """Header status strip. Always follows the controller, including hotkeys."""
        if not hasattr(self, "state_label"):
            return
        state = self.coordinator.controller.state
        scheduled = self._session.armed or self._session.switching
        reason = str(getattr(self.coordinator.controller, "reason", "") or "").strip()
        state_text = self.t.get(state.value, state.value)
        if state == RunState.STOPPED and reason and reason != "cancelled":
            pretty = self._start_error_text(reason)
            if pretty and pretty != getattr(self, "_shown_start_reason", ""):
                self._shown_start_reason = pretty
                self.append_log(pretty)
                if hasattr(self, "footer_status"):
                    self.footer_status.configure(text=pretty)
        elif state != RunState.STOPPED:
            self._shown_start_reason = ""
        if state == RunState.RUNNING:
            mode = "on"
        elif state == RunState.PAUSED:
            mode = "hold"
        else:
            mode = "off"
        self._paint_status_chip(self.state_label, state_text, mode)
        if state == RunState.RUNNING:
            label, glyph, enabled = self.t["pause"], "pause", True
        elif state == RunState.PAUSED:
            label, glyph, enabled = self.t["resume"], "resume", True
        else:
            label, glyph = self.t["start"], "start"
            enabled = not self.coordinator.arming
        self.power_btn.configure(
            text=label,
            image=self._run_glyph(glyph),
            state="normal" if enabled else "disabled",
        )
        self.stop_btn.configure(
            state="normal"
            if state != RunState.STOPPED or self.coordinator.arming or scheduled
            else "disabled"
        )

    def _poll(self) -> None:
        if self._closing:
            return
        self._drive_schedule()
        self.coordinator.poll()
        self._refresh_operator()
        editor = getattr(self, "editor", None)
        if editor is not None and hasattr(editor, "_refresh_fix_inventory"):
            try:
                editor._refresh_fix_inventory()
            except tk.TclError:
                pass
        if editor is not None and hasattr(editor, "_refresh_hp_action_hotbar_keys"):
            try:
                editor._refresh_hp_action_hotbar_keys()
            except tk.TclError:
                pass
        self.after(250, self._poll)

    def _on_hotbar(self, layout: dict, slots: dict) -> None:
        stamped = dict(layout) if isinstance(layout, dict) else {}
        stamped["updated_at"] = f"{datetime.now():%H:%M:%S}"
        self.profile.hotbar_layout = stamped
        self.profile.spell_slots = copy.deepcopy(slots)
        save_profile(self.profile)
        index = self._selected()
        editor = getattr(self, "editor", None)
        if index is not None:
            magic = self.tasks[index].settings.setdefault("magic", {})
            magic["hotbar_layout"] = copy.deepcopy(stamped)
            magic["spell_slots"] = copy.deepcopy(slots)
            self.store.save(self.tasks)
            if (
                editor is not None
                and getattr(editor, "task", None) is not None
                and editor.task.id == self.tasks[index].id
            ):
                editor.task.settings.setdefault("magic", {})["hotbar_layout"] = copy.deepcopy(stamped)
                editor.task.settings.setdefault("magic", {})["spell_slots"] = copy.deepcopy(slots)

        def update() -> None:
            if editor is not None and hasattr(editor, "_refresh_hotbar_view"):
                try:
                    editor._refresh_hotbar_view()
                except tk.TclError:
                    pass

        self.after(0, update)

    def append_log(self, message: str) -> None:
        stamp = f"{datetime.now():%H:%M:%S}"
        line = f"{stamp}  {message}"
        self._log_lines = (self._log_lines + [line])[-500:]
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with (LOG_DIR / "v1.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass
        def update():
            editor = getattr(self, "editor", None)
            if editor is not None and hasattr(editor, "_append_log_row"):
                try:
                    editor._append_log_row(stamp, message)
                except tk.TclError:
                    pass
            if self.log_widget and self.log_widget.winfo_exists():
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", line + "\n")
                follow = getattr(editor, "_log_autoscroll", None) if editor is not None else None
                if follow is None or bool(follow.get()):
                    self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
        try:
            self.after(0, update)
        except tk.TclError:
            pass

    def _settings_unlocked(self) -> bool:
        allowed = (
            not self.coordinator.arming
            and self.coordinator.controller.state == RunState.STOPPED
        )
        if not allowed:
            messagebox.showwarning(
                self.t["title"], self.t["stop_to_apply"], parent=self
            )
        return allowed

    def _raise_child_window(self, top: tk.Misc) -> None:
        """Keep a child editor above the schedule window."""
        try:
            top.transient(self)
            top.deiconify()
            top.lift()
            top.focus_force()
            top.attributes("-topmost", True)
            top.after(250, lambda: top.attributes("-topmost", False))
        except tk.TclError:
            pass

    def open_map_editor(self) -> None:
        try:
            import customtkinter as ctk
            from manmabot_v1.ui.map_editor import MapEditor
            ctk.set_appearance_mode("light")
            top = ctk.CTkToplevel(self)
            dungeon = self.editor._is_dungeon_style()
            top.title(self.t["edit_patrol"] if dungeon else self.t["edit_map"])
            top.geometry("1000x700")
            top.configure(fg_color="#f3f4f6")
            editor = MapEditor(
                top,
                strings=ui_strings(self.language),
                language=self.language,
                can_edit=lambda: self.coordinator.controller.state == RunState.STOPPED,
                on_changed=self.editor._load_move_areas,
                on_done=top.destroy,
            )
            editor.pack(fill="both", expand=True)
            editor.load_map(self.editor._map_id(), dungeon=dungeon)
            self._raise_child_window(top)
            top.after(80, lambda: self._raise_child_window(top))
        except Exception as exc:
            messagebox.showerror(self.t["title"], str(exc), parent=self)

    def open_accounts(self) -> None:
        if not self._settings_unlocked():
            return
        top = tk.Toplevel(self)
        top.title(self.t["manage_accounts"])
        top.transient(self)
        top.geometry("1180x460")
        top.minsize(920, 320)
        table = ttk.Frame(top)
        table.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        style = ttk.Style(top)
        style.configure(
            "Accounts.Treeview",
            rowheight=30,
            font=FONT_BODY,
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            "Accounts.Treeview.Heading",
            padding=(8, 6),
            font=FONT_SECTION,
            background=TABLE_HEADER,
            foreground=TEXT,
            bordercolor=BORDER,
            relief="flat",
        )
        style.map(
            "Accounts.Treeview",
            background=[("selected", SELECTED)],
            foreground=[("selected", "#ffffff")],
        )
        column_ids = tuple(item[0] for item in _ACCOUNT_COLUMNS)
        tree = ttk.Treeview(
            table,
            columns=column_ids,
            show="headings",
            height=8,
            selectmode="browse",
            style="Accounts.Treeview",
        )
        for col, heading, width, _stretch, anchor in _ACCOUNT_COLUMNS:
            tree.heading(col, text=self.t.get(heading, heading), anchor="center")
            tree.column(
                col,
                width=width,
                minwidth=40,
                stretch=False,
                anchor=anchor,
            )
        y_scroll = ttk.Scrollbar(table, orient="vertical")

        def yset(*args: str) -> None:
            y_scroll.set(*args)
            _refresh_cell_grid(tree)

        y_scroll.configure(command=tree.yview)
        tree.configure(yscrollcommand=yset)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        _enable_bbox_grid(tree)
        store = AccountStore()
        recovery_prompted = False
        region_ids = {
            self.t["region_korea"]: "Korea",
            self.t["region_china"]: "China",
        }
        locale_ids = {
            self.t["locale_korean"]: "ko",
            self.t["locale_simplified_chinese"]: "zh-CN",
        }
        character_ids = {
            self.t["royal"]: "royal",
            self.t["knight"]: "knight",
            self.t["elf"]: "elf",
            self.t["mage"]: "mage",
        }
        full_paths: dict[str, tuple[str, str]] = {}
        layout_state = {"pending": None, "busy": False, "width": -1}

        def account_viewport() -> int:
            top.update_idletasks()
            window = top.winfo_width()
            if window < 80:
                return 0
            bar = y_scroll.winfo_width()
            if bar < 8:
                bar = 18
            return max(80, window - 16 - bar - 4)

        def layout_accounts() -> None:
            if not tree.winfo_exists():
                return
            _fit_account_columns(tree, full_paths, account_viewport())
            _refresh_cell_grid(tree)

        def run_layout() -> None:
            layout_state["pending"] = None
            if layout_state["busy"] or not top.winfo_exists():
                return
            width = top.winfo_width()
            if width < 80 or width == layout_state["width"]:
                return
            layout_state["busy"] = True
            layout_state["width"] = width
            try:
                layout_accounts()
            finally:
                layout_state["busy"] = False

        def schedule_layout(_event=None) -> None:
            if layout_state["busy"]:
                return
            pending = layout_state["pending"]
            if pending is not None:
                try:
                    tree.after_cancel(pending)
                except tk.TclError:
                    pass
            try:
                layout_state["pending"] = tree.after_idle(run_layout)
            except tk.TclError:
                layout_state["pending"] = None

        def account_row(account: Account) -> tuple:
            return (
                account.display_name or account.username,
                account.server,
                account.character_number,
                account.username,
                "••••••" if account.password else "",
                _label_for(region_ids, account.region),
                _label_for(locale_ids, account.locale),
                _label_for(character_ids, account.character_type),
                account.purple_launcher_path,
                account.game_path,
            )

        def reload():
            nonlocal recovery_prompted
            tree.delete(*tree.get_children())
            full_paths.clear()
            try:
                for account in store.load():
                    full_paths[account.account_id] = (
                        account.purple_launcher_path or "",
                        account.game_path or "",
                    )
                    tree.insert(
                        "",
                        "end",
                        iid=account.account_id,
                        values=account_row(account),
                    )
            except AccountStoreError:
                if recovery_prompted:
                    return
                recovery_prompted = True
                if not messagebox.askyesno(
                    self.t["account_unlock_title"],
                    self.t["account_unlock_reset"],
                    parent=top,
                ):
                    return
                try:
                    backup = store.backup_and_reset_inaccessible()
                    self.profile.selected_account_id = None
                    save_profile(self.profile)
                    self.editor._load_accounts()
                    messagebox.showinfo(
                        self.t["account_unlock_title"],
                        self.t["account_unlock_reset_done"].format(
                            path=str(backup) if backup else ""
                        ),
                        parent=top,
                    )
                except Exception as exc:
                    messagebox.showerror(self.t["title"], str(exc), parent=top)
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=top)
            if tree.get_children() and not tree.selection():
                tree.selection_set(tree.get_children()[0])
            layout_accounts()

        def edit_account(account: Account | None = None) -> None:
            form = tk.Toplevel(top)
            form.title(self.t["account"])
            form.transient(top)
            form.grab_set()
            form.focus_force()
            if account and account.locale in ("ko", "zh-CN"):
                default_locale = account.locale
            else:
                default_locale = "zh-CN" if self.language == "zh" else "ko"
            default_region = "China" if default_locale == "zh-CN" else "Korea"
            raw_slot = int(account.character_number) if account else 1
            if raw_slot not in (1, 2, 3):
                raw_slot = 1
            character_type = (
                account.character_type
                if account and account.character_type in character_ids.values()
                else "royal"
            )
            purple_path = (
                account.purple_launcher_path
                if account and account.purple_launcher_path
                else _DEFAULT_PURPLE_PATH
            )
            game_path = (
                account.game_path if account and account.game_path else _DEFAULT_GAME_PATH
            )
            fields = (
                ("display_name", self.t["display_name"], account.display_name if account else ""),
                ("username", self.t["username"], account.username if account else ""),
                ("password", self.t["password"], account.password if account else ""),
                ("region", self.t["region"], default_region),
                ("locale", self.t["server_language"], default_locale),
                ("server", self.t["server"], account.server if account else ""),
                ("character_number", self.t["character_order"], raw_slot),
                ("character_type", self.t["character_type"], character_type),
                ("purple_launcher_path", self.t["purple_path"], purple_path),
                ("game_path", self.t["game_path"], game_path),
            )
            variables: dict[str, tk.Variable] = {}
            combo_ids: dict[str, dict[str, str]] = {}
            combo_widgets: dict[str, ttk.Combobox] = {}
            choice_ids = {
                "region": region_ids,
                "locale": locale_ids,
                "character_type": character_ids,
            }
            for row_index, (key, label, value) in enumerate(fields):
                ttk.Label(form, text=label).grid(
                    row=row_index, column=0, sticky="w", padx=7, pady=3
                )
                variable: tk.Variable
                if key == "character_number":
                    variable = tk.IntVar(form, value=int(value))
                    widget = ttk.Frame(form)
                    for slot in (1, 2, 3):
                        ttk.Radiobutton(
                            widget,
                            text=str(slot),
                            value=slot,
                            variable=variable,
                        ).pack(side="left", padx=(0, 10))
                elif key == "password":
                    variable = tk.StringVar(form, value=str(value))
                    widget = ttk.Frame(form)
                    entry = ttk.Entry(
                        widget, width=30, textvariable=variable, show="*"
                    )
                    entry.pack(side="left", fill="x", expand=True)
                    revealed = {"on": False}

                    def toggle_password(
                        entry=entry, revealed=revealed
                    ) -> None:
                        revealed["on"] = not revealed["on"]
                        entry.configure(show="" if revealed["on"] else "*")
                        eye.configure(
                            bg=ACCENT_SOFT if revealed["on"] else SURFACE,
                            highlightbackground=ACCENT if revealed["on"] else BORDER,
                        )

                    eye = tk.Button(
                        widget,
                        text="\U0001F441",
                        font=("Segoe UI Emoji", 11),
                        relief="flat",
                        bd=0,
                        bg=SURFACE,
                        fg=TEXT,
                        activebackground=ACCENT_SOFT,
                        activeforeground=TEXT,
                        highlightthickness=1,
                        highlightbackground=BORDER,
                        highlightcolor=ACCENT,
                        width=3,
                        cursor="hand2",
                        command=toggle_password,
                    )
                    eye.pack(side="left", padx=(4, 0))
                elif key == "server":
                    servers = server_names_list(default_locale)
                    current_server = str(value)
                    if current_server and current_server not in servers:
                        servers.insert(0, current_server)
                    variable = tk.StringVar(
                        form,
                        value=current_server or (servers[0] if servers else ""),
                    )
                    widget = ttk.Combobox(
                        form,
                        state="readonly",
                        values=servers,
                        width=31,
                        textvariable=variable,
                    )
                    combo_widgets[key] = widget
                    show_combobox_value(widget, variable.get(), servers)
                elif key in choice_ids:
                    ids = choice_ids[key]
                    combo_ids[key] = ids
                    display_value = next(
                        (text for text, item_id in ids.items() if item_id == str(value)),
                        next(iter(ids)),
                    )
                    variable = tk.StringVar(form, value=display_value)
                    widget = ttk.Combobox(
                        form, state="readonly", values=list(ids),
                        width=31, textvariable=variable,
                    )
                    combo_widgets[key] = widget
                    show_combobox_value(widget, display_value, list(ids))
                elif key in ("purple_launcher_path", "game_path"):
                    variable = tk.StringVar(form, value=str(value))
                    widget = ttk.Frame(form)
                    entry = ttk.Entry(widget, width=34, textvariable=variable)
                    entry.pack(side="left", fill="x", expand=True)

                    def browse_path(
                        var: tk.StringVar = variable,
                        title: str = label,
                    ) -> None:
                        current = Path(str(var.get() or "")).expanduser()
                        initial_dir = (
                            current.parent
                            if current.parent.exists()
                            else Path.home()
                        )
                        selected = filedialog.askopenfilename(
                            parent=form,
                            title=title,
                            initialdir=str(initial_dir),
                            filetypes=[
                                (self.t["executables"], "*.exe"),
                                (self.t["all_files"], "*.*"),
                            ],
                        )
                        if selected:
                            var.set(selected)

                    ttk.Button(
                        widget, text=self.t["browse"], command=browse_path,
                    ).pack(side="left", padx=(4, 0))
                else:
                    variable = tk.StringVar(form, value=str(value))
                    widget = ttk.Entry(form, width=34, textvariable=variable)
                variables[key] = variable
                widget.grid(row=row_index, column=1, sticky="ew", padx=7, pady=3)
            form.columnconfigure(1, weight=1)

            def refresh_servers(_event=None) -> None:
                locale_label = str(variables["locale"].get())
                locale = combo_ids["locale"].get(locale_label, locale_label)
                servers = server_names_list(locale)
                current = str(variables["server"].get())
                if current not in servers and servers:
                    current = servers[0]
                show_combobox_value(combo_widgets["server"], current, servers)

            def show_paired(kind: str, code: str) -> None:
                ids = combo_ids[kind]
                show_combobox_value(
                    combo_widgets[kind],
                    next(
                        (label for label, item_id in ids.items() if item_id == code),
                        next(iter(ids)),
                    ),
                    list(ids),
                )

            def region_changed(_event=None) -> None:
                region_label = str(variables["region"].get())
                region = combo_ids["region"].get(region_label, region_label)
                show_paired("locale", "zh-CN" if region == "China" else "ko")
                refresh_servers()

            def locale_changed(_event=None) -> None:
                locale_label = str(variables["locale"].get())
                locale = combo_ids["locale"].get(locale_label, locale_label)
                show_paired("region", "China" if locale == "zh-CN" else "Korea")
                refresh_servers()

            combo_widgets["region"].bind("<<ComboboxSelected>>", region_changed)
            combo_widgets["locale"].bind("<<ComboboxSelected>>", locale_changed)

            def save_account() -> None:
                try:
                    values = {key: variable.get() for key, variable in variables.items()}
                    for key, ids in combo_ids.items():
                        values[key] = ids.get(str(values[key]), str(values[key]))
                    if account is None:
                        saved = Account.create(**values)
                        store.add(saved)
                    else:
                        saved = Account(
                            account_id=account.account_id,
                            click_mode=account.click_mode,
                            **values,
                        )
                        store.update(saved)
                    if self.profile.selected_account_id is None:
                        self.profile.selected_account_id = saved.account_id
                        save_profile(self.profile)
                    form.destroy()
                    reload()
                    self.editor._load_accounts()
                except Exception as exc:
                    messagebox.showerror(self.t["title"], str(exc), parent=form)

            buttons = ttk.Frame(form)
            buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", padx=7, pady=7)
            action_label = self.t["account_add"] if account is None else self.t["save"]
            ttk.Button(
                buttons, text=action_label, command=save_account, style="Accent.TButton",
            ).pack(
                side="left", padx=2
            )
            ttk.Button(buttons, text=self.t["cancel"], command=form.destroy).pack(
                side="left", padx=2
            )
            _center_dialog(form, self)
            form.wait_window()
            try:
                if top.winfo_exists():
                    top.grab_set()
                    top.focus_force()
            except tk.TclError:
                pass

        def edit_selected() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo(
                    self.t["title"], self.t["select_account"], parent=top,
                )
                return
            try:
                account = store.get(selected[0])
                if account is not None:
                    edit_account(account)
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=top)

        def delete_selected():
            try:
                for iid in tree.selection():
                    store.delete(iid)
                    if self.profile.selected_account_id == iid:
                        self.profile.selected_account_id = None
                        save_profile(self.profile)
                reload()
                self.editor._load_accounts()
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=top)

        def close_accounts() -> None:
            try:
                top.grab_release()
            except tk.TclError:
                pass
            if top.winfo_exists():
                top.destroy()

        row = ttk.Frame(top)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text=self.t["new"], command=edit_account).pack(side="left")
        ttk.Button(row, text=self.t["edit_account"], command=edit_selected).pack(
            side="left", padx=3
        )
        ttk.Button(row, text=self.t["delete"], command=delete_selected).pack(side="left", padx=3)

        def save_accounts() -> None:
            try:
                store.save(store.load())
                self.editor._load_accounts()
                close_accounts()
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=top)

        ttk.Button(
            row, text=self.t["save"], command=save_accounts, style="Accent.TButton",
        ).pack(side="right")

        def open_selected(_event=None) -> str | None:
            if _event is not None and tree.identify_region(_event.x, _event.y) != "cell":
                return None
            edit_selected()
            return "break"

        tree.bind("<Double-1>", open_selected)
        tree.bind("<Return>", lambda _event: edit_selected())
        top.bind("<Configure>", schedule_layout, add="+")
        reload()
        top.geometry("1180x460")
        top.update_idletasks()
        layout_accounts()
        _center_dialog(top, self)
        top.protocol("WM_DELETE_WINDOW", close_accounts)
        top.grab_set()
        top.focus_force()
        self.wait_window(top)

    def save_named(self) -> None:
        name = simpledialog.askstring(self.t["profiles"], self.t["profile_name"], parent=self)
        if name:
            try:
                save_named_profile(name, self.profile)
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=self)

    def load_named(self, name: str | None = None) -> None:
        if not self._settings_unlocked():
            return
        if not name:
            names = list_profile_names()
            name = simpledialog.askstring(self.t["profiles"],
                                          self.t["available_profiles"].format(names=", ".join(names)),
                                          parent=self)
        if name:
            try:
                loaded = load_named_profile(name)
                self.profile.__dict__.update(loaded.__dict__)
                save_profile(self.profile)
                self.coordinator.profile = self.profile
                self._refresh()
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=self)

    def delete_named(self, name: str | None = None) -> None:
        if not name:
            names = list_profile_names()
            name = simpledialog.askstring(
                self.t["profiles"],
                self.t["available_profiles"].format(names=", ".join(names)),
                parent=self,
            )
        if name:
            try:
                delete_named_profile(name)
            except Exception as exc:
                messagebox.showerror(self.t["title"], str(exc), parent=self)

    def export_named(self, name: str | None = None) -> None:
        if not name:
            names = list_profile_names()
            name = simpledialog.askstring(
                self.t["profiles"],
                self.t["available_profiles"].format(names=", ".join(names)),
                parent=self,
            )
        if not name:
            return
        try:
            source = named_profile_path(name)
            if not source.is_file():
                raise FileNotFoundError(self.t["profile_not_found"])
            destination = filedialog.asksaveasfilename(
                parent=self,
                title=self.t["export_profile"],
                defaultextension=".json",
                initialfile=source.name,
                filetypes=((self.t["profile_files"], "*.json"),),
            )
            if destination:
                shutil.copy2(source, destination)
                messagebox.showinfo(
                    self.t["profiles"], self.t["profile_exported"], parent=self
                )
        except Exception as exc:
            messagebox.showerror(self.t["title"], str(exc), parent=self)

    def import_named(self) -> None:
        source = filedialog.askopenfilename(
            parent=self,
            title=self.t["import_profile"],
            filetypes=((self.t["profile_files"], "*.json"),),
        )
        if not source:
            return
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(self.t["invalid_profile_file"])
            imported = Profile.from_dict(data)
            suggested = Path(source).stem
            name = simpledialog.askstring(
                self.t["profiles"],
                self.t["profile_name"],
                initialvalue=suggested,
                parent=self,
            )
            if name:
                save_named_profile(name, imported)
                messagebox.showinfo(
                    self.t["profiles"], self.t["profile_imported"], parent=self
                )
        except Exception as exc:
            messagebox.showerror(self.t["title"], str(exc), parent=self)

    def apply_profile(self, profile: Profile) -> None:
        """Compatibility callback used by the existing setup wizard."""
        language = ui_language(profile.language)
        self.profile.__dict__.update(profile.__dict__)
        save_profile(self.profile)
        self.coordinator.profile = self.profile
        if language != self.language:
            self._set_language(language)
        else:
            self._refresh()

    def edit_hotkeys(self) -> None:
        if not self._settings_unlocked():
            return
        self._show_hotkey_editor(dict(self.profile.hotkeys))

    def _show_hotkey_editor(self, initial: dict[str, str]) -> None:
        previous_hotkeys = dict(self.profile.hotkeys)
        # Registered global shortcuts can consume Alt combinations before the
        # focused Tk capture window receives them.
        self.coordinator.hotkeys.clear()
        dialog = tk.Toplevel(self)
        dialog.title(self.t["hotkeys"])
        dialog.transient(self)
        dialog.resizable(False, False)
        values = {
            "pause_resume": tk.StringVar(
                dialog,
                value=initial.get("pause_resume", DEFAULT_HOTKEYS["pause_resume"]),
            ),
            "stop": tk.StringVar(
                dialog, value=initial.get("stop", DEFAULT_HOTKEYS["stop"])
            ),
        }
        for row, (key, label) in enumerate((
            ("pause_resume", self.t["pause_hotkey"]),
            ("stop", self.t["stop_hotkey"]),
        )):
            ttk.Label(dialog, text=label).grid(
                row=row, column=0, sticky="w", padx=8, pady=5
            )
            ttk.Label(
                dialog,
                textvariable=values[key],
                width=16,
                style="Field.TLabel",
                anchor="center",
            ).grid(row=row, column=1, padx=4, pady=5)
            ttk.Button(
                dialog,
                text=self.t["capture_key"],
                command=lambda action=key: self._capture_hotkey(
                    dialog, action, values
                ),
            ).grid(row=row, column=2, padx=8, pady=5)

        def save() -> None:
            candidate = {
                "pause_resume": values["pause_resume"].get().lower(),
                "stop": values["stop"].get().lower(),
            }
            self.profile.hotkeys = candidate
            error = self.coordinator.rebind_hotkeys()
            if error:
                self.profile.hotkeys = previous_hotkeys
                messagebox.showerror(self.t["hotkeys"], error, parent=dialog)
            else:
                save_profile(self.profile)
                dialog.destroy()

        def cancel() -> None:
            self.profile.hotkeys = previous_hotkeys
            self.coordinator.rebind_hotkeys()
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, columnspan=3, sticky="e", padx=8, pady=8)
        ttk.Button(
            buttons, text=self.t["save"], command=save, style="Accent.TButton",
        ).pack(
            side="left", padx=2
        )
        ttk.Button(buttons, text=self.t["cancel"], command=cancel).pack(
            side="left", padx=2
        )
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        _center_dialog(dialog, self)
        dialog.grab_set()

    def _capture_hotkey(
        self,
        owner: tk.Toplevel,
        action: str,
        values: dict[str, tk.StringVar],
    ) -> None:
        capture = tk.Toplevel(owner)
        capture.title(self.t["capture_key"])
        capture.transient(owner)
        capture.resizable(False, False)
        ttk.Label(
            capture, text=self.t["hotkey_capture_prompt"], padding=(18, 14)
        ).pack()
        keyboard_hook = None
        finished = False
        rejected_combo: str | None = None
        pressed_modifiers: set[str] = set()

        def cleanup() -> None:
            nonlocal keyboard_hook
            if keyboard_hook is not None:
                try:
                    keyboard.unhook(keyboard_hook)
                except Exception:
                    pass
                keyboard_hook = None

        def close() -> None:
            cleanup()
            if capture.winfo_exists():
                capture.destroy()

        def commit(combo: str) -> None:
            nonlocal finished, rejected_combo
            if finished or not capture.winfo_exists():
                return
            combo = combo.strip().lower()
            used = {
                variable.get().strip().lower()
                for name, variable in values.items()
                if name != action
            }
            if combo in used:
                if combo == rejected_combo:
                    return
                rejected_combo = combo
                messagebox.showwarning(
                    self.t["hotkeys"],
                    self.t["hotkey_in_use"].format(key=combo),
                    parent=capture,
                )
                capture.focus_force()
                return
            rejected_combo = None
            finished = True
            values[action].set(combo)
            close()

        def on_key(event: tk.Event, force_alt: bool = False) -> str:
            if event.keysym == "Escape":
                close()
                return "break"
            if event.keysym in {
                "Shift_L", "Shift_R", "Control_L", "Control_R",
                "Alt_L", "Alt_R", "Meta_L", "Meta_R",
            }:
                return "break"
            modifiers = []
            if event.state & 0x0004:
                modifiers.append("ctrl")
            if event.state & 0x0001:
                modifiers.append("shift")
            # Tk reports Alt as Mod1 (0x0008) on some Windows builds and as
            # the Win32 extended-context flag (0x20000) on others.
            alt_down = bool(force_alt or event.state & (0x0008 | 0x20000))
            if sys.platform == "win32":
                try:
                    alt_down = alt_down or bool(
                        ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000
                    )
                except Exception:
                    pass
            if alt_down:
                modifiers.append("alt")
            combo = "+".join([*dict.fromkeys(modifiers), str(event.keysym).lower()])
            commit(combo)
            return "break"

        modifier_names = {
            "alt": "alt", "left alt": "alt", "right alt": "alt",
            "ctrl": "ctrl", "left ctrl": "ctrl", "right ctrl": "ctrl",
            "control": "ctrl",
            "shift": "shift", "left shift": "shift", "right shift": "shift",
        }

        def low_level_key(event) -> None:
            name = str(getattr(event, "name", "") or "").strip().lower()
            event_type = str(getattr(event, "event_type", "") or "").lower()
            modifier = modifier_names.get(name)
            if modifier:
                if event_type == "down":
                    pressed_modifiers.add(modifier)
                elif event_type == "up":
                    pressed_modifiers.discard(modifier)
                return
            if event_type != "down" or not name:
                return
            if name == "esc":
                capture.after(0, close)
                return
            ordered = [
                modifier for modifier in ("ctrl", "shift", "alt")
                if modifier in pressed_modifiers
            ]
            combo = "+".join([*ordered, name])
            capture.after(0, lambda value=combo: commit(value))

        capture.bind("<KeyPress>", on_key)
        capture.bind("<Alt-KeyPress>", lambda event: on_key(event, True))
        capture.protocol("WM_DELETE_WINDOW", close)
        _center_dialog(capture, owner)
        capture.grab_set()
        capture.after_idle(capture.focus_force)
        try:
            keyboard_hook = keyboard.hook(low_level_key, suppress=False)
        except Exception:
            keyboard_hook = None

    def reset_hotkeys(self) -> None:
        if not self._settings_unlocked():
            return
        previous = dict(self.profile.hotkeys)
        self.profile.hotkeys = dict(DEFAULT_HOTKEYS)
        error = self.coordinator.rebind_hotkeys()
        if error:
            self.profile.hotkeys = previous
            self.coordinator.rebind_hotkeys()
            messagebox.showerror(self.t["hotkeys"], error, parent=self)
            return
        save_profile(self.profile)
        messagebox.showinfo(
            self.t["hotkeys"], self.t["hotkeys_reset_done"], parent=self
        )

    def reset_all(self) -> None:
        if not self._settings_unlocked():
            return
        if not messagebox.askyesno(
            self.t["title"], self.t["reset_confirm"], parent=self
        ):
            return
        self.coordinator.stop()
        self.apply_profile(reset_profile())

    def run_setup(self) -> None:
        if not self._settings_unlocked():
            return
        try:
            from manmabot_v1.ui.wizard import SetupWizard
            SetupWizard(self)
        except Exception as exc:
            messagebox.showerror(self.t["setup"], str(exc), parent=self)

    def start_driver(self) -> None:
        from manmabot_v1.monitor_launch import try_start_driver
        ok, detail = try_start_driver(log=self.append_log)
        (messagebox.showinfo if ok else messagebox.showwarning)(
            self.t["start_driver"], detail, parent=self
        )

    def copy_diagnostics(self) -> None:
        game, memory, map_probe = self.coordinator.probes()
        text = (f"Manmabot v1\ngame={game.detail}\nmemory={memory.detail}\nmap={map_probe.detail}\n"
                f"active_map={self.profile.active_map}\ncharacter={self.profile.character}\n"
                f"language={self.profile.language}\ngame_language={self.profile.game_language}\n")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.footer_status.configure(text=self.t["diagnostics_copied"])

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))

    def _set_language(self, language: str) -> None:
        language = ui_language(language)
        if language == self.language:
            return
        self._close_debug()
        self.profile.language = language
        save_profile(self.profile)
        self._session.disarm()
        self._clear_power_buttons()
        self.coordinator.close()
        # Rebuild while withdrawn so the user never sees a blank/torn layout
        # between destroy() and the restored editor form.
        self._window_revealed = False
        try:
            self.withdraw()
        except tk.TclError:
            pass
        for child in self.winfo_children():
            child.destroy()
        self.language = language
        self.t = tr(language)
        apply_classic_style(self, language)
        self._sync_font_aliases()
        self.title(self.t["console_title"])
        self.resizable(True, True)
        _disable_window_maximize(self)
        self.minsize(ui_theme.MIN_WIDTH, ui_theme.MIN_HEIGHT)
        self.coordinator = self._open_coordinator()
        self._build()
        self._apply_window_scale()
        self._nav_lock += 1
        try:
            self._refresh()
            self._restore_editor()
        finally:
            self._nav_lock -= 1
        self._reveal_window()

    def _restore_editor(self) -> None:
        editing = self._editing_id
        task = next(
            (item for item in self.tasks if item.id == editing), None
        ) if editing else None
        if task is None:
            self._editing_id = None
            self.editor.begin_new()
        else:
            self.editor.load(task)
            self.editor.set_commit_mode(True)

    def _on_close(self) -> None:
        self._closing = True
        self._session.disarm()
        self._close_debug()
        self.coordinator.close()
        self.destroy()


def run_schedule_app() -> int:
    app = ScheduleWindow()
    app.mainloop()
    return 0
