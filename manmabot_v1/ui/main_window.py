"""Main operator window for Version 1."""
from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from manmabot_v1.accounts import (
    Account,
    AccountStore,
    AccountStoreError,
    SERVER_LANGUAGE_CODES,
    normalize_server_language,
    region_for_locale,
)
from manmabot_v1.autologin_service import (
    AutoLoginRequest,
    AutoLoginService,
)
from manmabot_v1.server_list import server_names_list
from manmabot_v1.bot_controller import BotController, RunState
from manmabot_v1.hotkeys import HotkeyManager, install_alt_menu_guard
from manmabot_v1.localized_names import route_point_display_name
from manmabot_v1.map_previews import brand_icon_path, character_portrait_path, map_preview_path
from manmabot_v1.paths import LOG_DIR, USERDATA, ensure_userdata, manmabot_root
from manmabot_v1.probes import (
    Lamp,
    bring_game_to_front,
    is_dungeon_map_id,
    list_farms_for_map,
    list_map_choices,
    localize_probe_detail,
    probe_game,
    probe_map,
    probe_memory,
)
from manmabot_v1.profile import (
    Profile,
    delete_named_profile,
    list_profile_names,
    load_named_profile,
    normalize_profile_name,
    reset_profile,
    save_named_profile,
    save_profile,
)
from manmabot_v1.recovery import RecoveryBudget, prepare_session
from manmabot_v1.spell_defaults import (
    SKILL_GRID,
    SKILL_KEYS,
    SLOT_IDS,
)
from manmabot_v1.strings import (
    DEFAULT_HOTKEYS,
    LANGUAGE_CHOICES,
    normalize_game_language,
    normalize_language,
    ui_strings,
)
from manmabot_v1.ui.character_picker import pack_character_choices
from manmabot_v1.ui.controls import disable_slider_mousewheel
from manmabot_v1.ui.farm_overview import render_farm_overview
from manmabot_v1.ui.loot_picker import pack_loot_choices
from manmabot_v1.ui.map_editor import MapEditor
from manmabot_v1.ui.species_panel import SpeciesPanel


_LAMP_COLOR = {
    Lamp.GRAY: "#6b7280",
    Lamp.GREEN: "#22c55e",
    Lamp.YELLOW: "#eab308",
    Lamp.RED: "#ef4444",
}
_UI_SCALE_MIN = 0.7
_UI_SCALE_MAX = 2.0
_UI_SCALE_STEP = 1.1
_ARROW_QTY_MIN = 1
_ARROW_QTY_MAX = 999
_DEFAULT_PURPLE_LAUNCHER = (
    r"C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe"
)
_DEFAULT_PURPLE_EXE = (
    r"C:\Program Files (x86)\NC\Purple\2.26.907.25\Purple.exe"
)
_DEFAULT_GAME_EXECUTABLE = (
    r"C:\Program Files (x86)\NC\Lineage Classic\LC.exe"
)


def _default_purple_launcher_path() -> str:
    """Prefer the launcher, then the versioned Purple.exe if present."""
    for candidate in (_DEFAULT_PURPLE_LAUNCHER, _DEFAULT_PURPLE_EXE):
        if Path(candidate).is_file():
            return candidate
    return _DEFAULT_PURPLE_LAUNCHER


class _PctBar:
    """CTkSlider plus its caption. ``set`` moves the bar, not only the variable."""

    def __init__(self, var, slider, label, render) -> None:
        self.var = var
        self.slider = slider
        self.label = label
        self._render = render

    def get(self) -> float:
        return float(self.var.get())

    def set(self, value: float) -> None:
        value = float(value)
        self.var.set(value)
        try:
            self.slider.set(value)
        except Exception:
            pass
        try:
            self.label.configure(text=self._render(value))
        except Exception:
            pass


class MainWindow(ctk.CTk):
    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self.profile = profile
        self.s = ui_strings(profile.language)
        self.title(self.s.window_title)
        self._ctrl_w, self._ctrl_h = 1000, 780
        self._left_w = 440
        self._edit_w, self._edit_h = 1120, 760
        self._edit_open = False
        self.geometry(f"{self._ctrl_w}x{self._ctrl_h}")
        self.minsize(880, 640)

        self._log_lines: list[str] = []
        self._arming = False
        self._arming_token = 0
        self._arming_cancel = threading.Event()
        self._arming_thread: Optional[threading.Thread] = None
        self._closing = False
        self._recovery_budget = RecoveryBudget(max_attempts=3, window_s=600.0)
        self._sync_recovery_budget()
        self.controller = BotController(
            on_log=self.append_log,
            on_state=self._on_bot_state,
            on_hotbar=self._on_hotbar_from_bot,
        )
        self.hotkeys = HotkeyManager()

        self._build()
        self._apply_brand_icon()
        self.after(400, self._apply_brand_icon)
        install_alt_menu_guard(self)
        self._bind_ctrl_wheel_zoom()
        self._apply_always_on_top()
        self._refresh_lamps()
        self._refresh_buttons()
        self._rebind_hotkeys()
        self.controller.set_preview_enabled(False)
        self.after(250, self._poll)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_brand_icon(self) -> None:
        """Title-bar / taskbar icon from ``images/icon.png`` (not drawn in the UI)."""
        path = brand_icon_path()
        if path is None:
            return
        ico = self._brand_ico_path(path)
        try:
            if ico is not None:
                self.iconbitmap(default=str(ico))
                self.iconbitmap(str(ico))
        except Exception:
            pass
        try:
            from PIL import Image, ImageTk

            im = Image.open(path)
            im.load()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            photo = ImageTk.PhotoImage(im)
            self._brand_icon_photo = photo
            self.iconphoto(True, photo)
        except Exception:
            pass
        if ico is not None:
            self._set_win32_icon(ico)

    def _brand_ico_path(self, source: Path) -> Optional[str]:
        if source.suffix.lower() == ".ico":
            return str(source)
        try:
            from PIL import Image

            im = Image.open(source)
            im.load()
            im = im.convert("RGBA")
            ensure_userdata()
            dest = USERDATA / "window_icon.ico"
            im.save(
                dest,
                format="ICO",
                sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
            )
            return str(dest)
        except Exception:
            return None

    def _set_win32_icon(self, ico_path: str) -> None:
        if sys.platform != "win32":
            return
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SendMessageW.restype = wintypes.LPARAM
            user32.SendMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                ctypes.c_void_p,
            ]
            hwnd = int(user32.GetAncestor(int(self.winfo_id()), 2) or 0)
            if not hwnd:
                hwnd = int(user32.GetParent(int(self.winfo_id())) or 0)
            if not hwnd:
                return
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if small:
                user32.SendMessageW(hwnd, WM_SETICON, 0, small)
                self._hicon_small = small
            if big:
                user32.SendMessageW(hwnd, WM_SETICON, 1, big)
                self._hicon_big = big
        except Exception:
            pass

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        self.left = ctk.CTkFrame(self.body, fg_color="transparent", width=self._ctrl_w)
        self.left.pack(side="left", fill="both", expand=True)
        self.left.pack_propagate(True)

        self.editor_host = ctk.CTkFrame(self.body, fg_color="transparent")
        self._edit_open = False

        ctk.CTkLabel(
            self.left, text=self.s.brand, font=ctk.CTkFont(size=20, weight="bold")
        ).pack(anchor="w", **pad)
        ctk.CTkLabel(
            self.left, text=self.s.brand_sub, text_color="gray"
        ).pack(anchor="w", padx=12)

        # Status
        status = ctk.CTkFrame(self.left)
        status.pack(fill="x", padx=12, pady=8)
        lamps = ctk.CTkFrame(status, fg_color="transparent")
        lamps.pack(fill="x", padx=8, pady=6)
        self.lamp_game = self._make_lamp(lamps, self.s.lamp_game, self._click_game)
        self.lamp_mem = self._make_lamp(lamps, self.s.lamp_memory, self._ensure_memory)
        self.lamp_map = self._make_lamp(lamps, self.s.lamp_map, self._click_map)

        self.headline = ctk.CTkLabel(
            status, text=self.s.headline_stopped, font=ctk.CTkFont(size=16, weight="bold")
        )
        self.headline.pack(anchor="w", padx=8)
        self.reason_label = ctk.CTkLabel(
            status, text=self.s.ready_to_start, wraplength=860, justify="left"
        )
        self.reason_label.pack(anchor="w", padx=8, pady=(0, 8))

        # Controls
        row = ctk.CTkFrame(self.left, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        self.btn_start = ctk.CTkButton(
            row, text=self.s.btn_start, width=120, command=self._on_start
        )
        self.btn_start.pack(side="left", padx=4)
        self.btn_resume = ctk.CTkButton(
            row, text=self.s.btn_resume, width=120, command=self._on_resume
        )
        self.btn_resume.pack(side="left", padx=4)
        self.btn_stop = ctk.CTkButton(
            row, text=self.s.btn_stop, width=120, fg_color="#b91c1c", command=self._on_stop
        )
        self.btn_stop.pack(side="left", padx=4)

        # Tabs
        try:
            self.tabs = ctk.CTkTabview(self.left, command=self._on_tab_changed)
        except TypeError:
            self.tabs = ctk.CTkTabview(self.left)
            try:
                self.tabs._segmented_button.configure(command=self._on_tab_changed)
            except Exception:
                pass
        self.tabs.pack(fill="both", expand=True, padx=12, pady=8)
        self.tab_names = {
            "setup": self.s.tab_setup,
            "farms": self.s.tab_farms,
            "species": self.s.tab_species,
            "spells": self.s.tab_spells,
            "advanced": self.s.tab_advanced,
            "log": self.s.tab_log,
        }
        self.tab_setup = self.tabs.add(self.tab_names["setup"])
        self.tab_farms = self.tabs.add(self.tab_names["farms"])
        self.tab_species = self.tabs.add(self.tab_names["species"])
        self.tab_spells = self.tabs.add(self.tab_names["spells"])
        self.tab_advanced = self.tabs.add(self.tab_names["advanced"])
        self.tab_log = self.tabs.add(self.tab_names["log"])

        self._build_setup()
        self._build_farms()
        self._build_species()
        self._build_spells()
        self._build_advanced()
        self._build_log()
        self._build_map_editor()

    def _bind_ctrl_wheel_zoom(self) -> None:
        if getattr(self, "_ctrl_wheel_bound", False):
            return
        self.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.bind_all("<Control-Button-4>", self._on_ctrl_wheel)
        self.bind_all("<Control-Button-5>", self._on_ctrl_wheel)
        self._ctrl_wheel_bound = True

    def _wheel_delta(self, event) -> int:
        num = getattr(event, "num", None)
        if num == 4:
            return 120
        if num == 5:
            return -120
        return int(getattr(event, "delta", 0) or 0)

    def _map_canvas_under_widget(self, widget):
        canvases = []
        if getattr(self, "_edit_open", False):
            canvas = getattr(getattr(self, "map_editor", None), "canvas", None)
            if canvas is not None:
                canvases.append(("farms", canvas))
        current = widget
        for _ in range(16):
            if current is None:
                return None
            for kind, canvas in canvases:
                if current == canvas:
                    return kind
            current = getattr(current, "master", None)
        return None

    def _on_ctrl_wheel(self, event):
        delta = self._wheel_delta(event)
        if delta == 0:
            return "break"
        kind = self._map_canvas_under_widget(getattr(event, "widget", None))
        if kind == "farms":
            event.delta = delta
            self.map_editor._on_wheel(event)
            return "break"
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        cur = float(ScalingTracker.widget_scaling)
        nxt = cur * _UI_SCALE_STEP if delta > 0 else cur / _UI_SCALE_STEP
        nxt = max(_UI_SCALE_MIN, min(_UI_SCALE_MAX, nxt))
        if abs(nxt - cur) < 1e-4:
            return "break"
        ctk.set_widget_scaling(nxt)
        return "break"

    def _make_lamp(self, parent, name: str, cmd) -> dict:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", padx=8)
        dot = ctk.CTkLabel(f, text="●", text_color=_LAMP_COLOR[Lamp.GRAY], width=16)
        dot.pack(side="left")
        btn = ctk.CTkButton(f, text=name, width=70, height=24, command=cmd)
        btn.pack(side="left", padx=2)
        tip = ctk.CTkLabel(f, text="", text_color="gray", font=ctk.CTkFont(size=10))
        return {"dot": dot, "btn": btn, "tip": tip, "detail": ""}

    # ── Setup tab ─────────────────────────────────────────────────────────

    def _settings_group(
        self,
        parent,
        title: str = "",
        *,
        pack: bool = True,
        fill: str = "x",
        expand: bool = False,
    ) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, border_width=1, corner_radius=0)
        if pack:
            box.pack(fill=fill, expand=expand, padx=6, pady=4)
        if title:
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(weight="bold")).pack(
                anchor="w", padx=10, pady=(7, 3)
            )
        return box

    def _build_setup(self) -> None:
        t = self.tab_setup
        t.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(t)
        scroll.pack(fill="both", expand=True)
        wrap = 820

        map_group = self._settings_group(scroll)
        visual = ctk.CTkFrame(map_group, fg_color="transparent")
        visual.pack(fill="x", padx=4, pady=(4, 8))
        visual.grid_columnconfigure(0, weight=1, uniform="setup_vis")
        visual.grid_columnconfigure(1, weight=1, uniform="setup_vis")
        visual.grid_rowconfigure(2, minsize=120)
        self._setup_visual = visual
        self._setup_preview_h = 320
        self._setup_fit_w = 0

        map_title = ctk.CTkLabel(
            visual, text=self.s.map_select, font=ctk.CTkFont(weight="bold")
        )
        map_title.grid(row=0, column=0, sticky="w", padx=(4, 8))
        char_title = ctk.CTkLabel(
            visual, text=self.s.character, font=ctk.CTkFont(weight="bold")
        )
        char_title.grid(row=0, column=1, sticky="w", padx=(8, 4))

        self._map_choices = list_map_choices(self.profile.language)
        labels = [name for _mid, name, _d in self._map_choices]
        ids = [mid for mid, _n, _d in self._map_choices]
        current = self.profile.active_map
        if current not in ids and ids:
            current = ids[0]
            self.profile.active_map = current
        display = labels[ids.index(current)] if current in ids else (labels[0] if labels else "")
        self.map_var = tk.StringVar(value=display)
        self._map_combo = ctk.CTkComboBox(
            visual,
            values=labels or [""],
            variable=self.map_var,
            command=self._on_map_chosen,
        )
        self._map_combo.grid(row=1, column=0, sticky="ew", padx=(4, 8), pady=4)

        self._map_preview_w, self._map_preview_h = 420, self._setup_preview_h
        self._map_preview_host = ctk.CTkFrame(
            visual, height=1, fg_color="transparent"
        )
        self._map_preview_host.pack_propagate(False)
        self._map_preview_label = ctk.CTkLabel(
            self._map_preview_host, text="", fg_color="transparent"
        )
        self._map_preview_label.pack(expand=True, fill="both")
        self._map_preview_ctk = None

        char_row = ctk.CTkFrame(visual, fg_color="transparent")
        char_row.grid(row=2, column=1, sticky="nsew", padx=(8, 4), pady=6)
        char_row.grid_columnconfigure(0, weight=0)
        char_row.grid_columnconfigure(1, weight=1)
        char_row.grid_rowconfigure(0, weight=1)
        self._setup_char_row = char_row
        self._char_preview_w, self._char_preview_h = 320, self._setup_preview_h
        self._char_preview_host = ctk.CTkFrame(
            char_row,
            width=self._char_preview_w,
            height=self._char_preview_h,
            fg_color="#1a1a1e",
            corner_radius=0,
            border_width=0,
        )
        self._char_preview_host.grid_propagate(False)
        self._char_preview_label = ctk.CTkLabel(
            self._char_preview_host, text="", fg_color="transparent"
        )
        self._char_preview_label.pack(expand=True, fill="both")
        self._char_preview_ctk = None
        self.char_var = tk.StringVar(value=self.profile.character)
        list_host = ctk.CTkFrame(char_row, fg_color="transparent")
        list_host.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0)
        self._char_list_host = list_host
        self._char_portrait_refs = pack_character_choices(
            list_host,
            variable=self.char_var,
            strings=self.s,
            command=self._on_character_chosen,
            show_portraits=False,
            show_blurbs=False,
            expand_rows=True,
            padx=0,
            wraplength=200,
        )
        ctk.CTkLabel(
            visual, text=self.s.map_hint, text_color="gray", wraplength=400, justify="left"
        ).grid(row=3, column=0, sticky="w", padx=(4, 8))

        lang = self._settings_group(scroll, self.s.game_language)
        self.game_lang_var = tk.StringVar(
            value=normalize_game_language(self.profile.game_language)
        )
        for code, label in (
            ("ko", self.s.game_lang_ko),
            ("zh", self.s.game_lang_zh),
        ):
            ctk.CTkRadioButton(
                lang,
                text=label,
                variable=self.game_lang_var,
                value=code,
                command=self._save_setup_fields,
            ).pack(anchor="w", padx=12, pady=2)
        ctk.CTkLabel(
            lang,
            text=self.s.game_language_hint,
            text_color="gray",
            wraplength=wrap,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        loot = self._settings_group(scroll, self.s.loot)
        self.loot_var = tk.StringVar(value=self.profile.loot_mode)
        self._loot_icon_refs = pack_loot_choices(
            loot,
            variable=self.loot_var,
            strings=self.s,
            command=self._save_setup_fields,
            icon_box=(128, 128),
            wraplength=220,
        )
        self.adena_weight = self._slider(
            loot,
            self.s.loot_adena_weight,
            self.profile.loot_adena_weight_ratio,
        )
        self.loot_weight_lab = ctk.CTkLabel(
            loot,
            text=self.s.loot_weight_note.format(
                pct=int(round(self.profile.loot_adena_weight_ratio * 100))
            ),
            text_color="gray",
            wraplength=wrap,
            justify="left",
        )
        self.loot_weight_lab.pack(anchor="w", padx=12, pady=(0, 10))

        surv = self._settings_group(scroll, self.s.survival)
        self.hp_pot = self._slider(
            surv, self.s.drink_hp, self.profile.hp_potion_ratio
        )
        self.hp_esc = self._slider(
            surv, self.s.escape_hp, self.profile.hp_escape_ratio
        )
        ctk.CTkButton(
            surv, text=self.s.reset_survival, command=self._reset_survival
        ).pack(anchor="w", padx=12, pady=(4, 10))

        arrows = self._settings_group(scroll, self.s.buy_arrows)
        type_row = ctk.CTkFrame(arrows, fg_color="transparent")
        type_row.pack(anchor="w", padx=12, pady=(4, 0))
        self.arrow_type_var = tk.StringVar(
            value=(
                "silver"
                if getattr(self.profile, "buy_silver_arrows", False)
                else "normal"
            )
        )
        ctk.CTkRadioButton(
            type_row,
            text=self.s.buy_normal_arrows,
            variable=self.arrow_type_var,
            value="normal",
            command=self._on_arrow_type_change,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(
            type_row,
            text=self.s.buy_silver_arrows,
            variable=self.arrow_type_var,
            value="silver",
            command=self._on_arrow_type_change,
        ).pack(side="left")

        self.arrow_qty_var = tk.StringVar(value=str(int(self.profile.arrow_buy_qty)))
        self.silver_arrow_qty_var = tk.StringVar(
            value=str(int(getattr(self.profile, "silver_arrow_buy_qty", 200)))
        )
        arrow_row = ctk.CTkFrame(arrows, fg_color="transparent")
        arrow_row.pack(anchor="w", padx=12, pady=4)
        ctk.CTkLabel(arrow_row, text=self.s.buy_arrows).pack(side="left", padx=(0, 6))
        self.arrow_qty_entry = ctk.CTkEntry(
            arrow_row, width=80, textvariable=self.arrow_qty_var
        )
        self.arrow_qty_entry.pack(side="left")
        self._bind_arrow_qty_entry()
        self.arrow_qty_entry.bind("<FocusOut>", lambda _e: self._commit_arrow_qty())
        self.arrow_qty_entry.bind("<Return>", lambda _e: self._commit_arrow_qty())

        silver_row = ctk.CTkFrame(arrows, fg_color="transparent")
        silver_row.pack(anchor="w", padx=12, pady=4)
        ctk.CTkLabel(silver_row, text=self.s.silver_arrow_qty).pack(
            side="left", padx=(0, 6)
        )
        self.silver_arrow_qty_entry = ctk.CTkEntry(
            silver_row, width=80, textvariable=self.silver_arrow_qty_var
        )
        self.silver_arrow_qty_entry.pack(side="left")
        self.silver_arrow_qty_entry.bind(
            "<FocusOut>", lambda _e: self._commit_silver_arrow_qty()
        )
        self.silver_arrow_qty_entry.bind(
            "<Return>", lambda _e: self._commit_silver_arrow_qty()
        )

        restock_row = ctk.CTkFrame(arrows, fg_color="transparent")
        restock_row.pack(anchor="w", padx=12, pady=(4, 0))
        self.restock_potions_var = tk.BooleanVar(
            value=bool(getattr(self.profile, "restock_potions", True))
        )
        ctk.CTkCheckBox(
            restock_row,
            text=self.s.restock_potions,
            variable=self.restock_potions_var,
            command=self._save_setup_fields,
        ).pack(side="left")
        ctk.CTkLabel(
            arrows,
            text=self.s.buy_arrows_hint,
            text_color="gray",
            wraplength=wrap,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 2))
        ctk.CTkLabel(
            arrows,
            text=self.s.restock_potions_hint,
            text_color="gray",
            wraplength=wrap,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def _slider(self, parent, label: str, value: float):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=8, pady=4)
        lab = ctk.CTkLabel(frame, text=f"{label}: {int(value * 100)}%")
        lab.pack(anchor="w")
        var = tk.DoubleVar(value=value * 100)

        def render(pct: float) -> str:
            return f"{label}: {int(pct)}%"

        def on_change(_=None):
            lab.configure(text=render(var.get()))
            if not getattr(self, "_setup_syncing", False):
                self._save_setup_fields()

        s = ctk.CTkSlider(frame, from_=5, to=95, variable=var, command=on_change)
        s.pack(fill="x")
        disable_slider_mousewheel(s)
        return _PctBar(var, s, lab, render)

    def _arrow_qty_ok(self, proposed: str) -> bool:
        if proposed == "":
            return True
        if not proposed.isdigit() or len(proposed) > 3:
            return False
        n = int(proposed)
        return _ARROW_QTY_MIN <= n <= _ARROW_QTY_MAX

    def _bind_arrow_qty_entry(self) -> None:
        inner = getattr(self.arrow_qty_entry, "_entry", None)
        widget = inner if inner is not None else self.arrow_qty_entry
        vcmd = (self.register(self._arrow_qty_ok), "%P")
        try:
            widget.configure(validate="all", validatecommand=vcmd)
        except Exception:
            pass
        self._arrow_qty_guard = False
        self.arrow_qty_var.trace_add("write", self._on_arrow_qty_write)

    def _on_arrow_qty_write(self, *_args) -> None:
        if getattr(self, "_arrow_qty_guard", False):
            return
        raw = self.arrow_qty_var.get()
        if self._arrow_qty_ok(raw):
            return
        digits = "".join(c for c in raw if c.isdigit())[:3]
        cleaned = digits if self._arrow_qty_ok(digits) else ""
        self._arrow_qty_guard = True
        try:
            self.arrow_qty_var.set(cleaned)
        finally:
            self._arrow_qty_guard = False

    def _commit_arrow_qty(self) -> None:
        raw = str(self.arrow_qty_var.get() or "").strip()
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = int(self.profile.arrow_buy_qty)
        n = max(_ARROW_QTY_MIN, min(_ARROW_QTY_MAX, n))
        self._arrow_qty_guard = True
        try:
            self.arrow_qty_var.set(str(n))
        finally:
            self._arrow_qty_guard = False
        self._save_setup_fields()

    def _commit_silver_arrow_qty(self) -> None:
        raw = str(self.silver_arrow_qty_var.get() or "").strip()
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = int(getattr(self.profile, "silver_arrow_buy_qty", 200))
        n = max(_ARROW_QTY_MIN, min(_ARROW_QTY_MAX, n))
        self.silver_arrow_qty_var.set(str(n))
        self._save_setup_fields()

    def _on_arrow_type_change(self) -> None:
        self._save_setup_fields()

    # ── Farms tab ─────────────────────────────────────────────────────────

    def _build_farms(self) -> None:
        t = self.tab_farms
        scroll = ctk.CTkScrollableFrame(t)
        scroll.pack(fill="both", expand=True)
        self.farms_scroll = scroll

        self.farms_select_group = self._settings_group(scroll)
        self.farms_head = ctk.CTkFrame(self.farms_select_group, fg_color="transparent")
        self.farms_heading = ctk.CTkLabel(
            self.farms_head, text=self.s.farms_heading, font=ctk.CTkFont(weight="bold")
        )
        self.farms_heading.pack(anchor="w")
        self.farms_banner = ctk.CTkLabel(
            self.farms_head, text="", wraplength=360, justify="left"
        )
        self.farms_banner.pack(anchor="w", pady=(4, 0))

        self.farms_body = ctk.CTkFrame(self.farms_select_group, fg_color="transparent")
        self.farms_list_col = ctk.CTkFrame(self.farms_body, fg_color="transparent")
        self.farms_map_col = ctk.CTkFrame(self.farms_body, fg_color="transparent")

        self.farms_minimap_host = ctk.CTkFrame(
            self.farms_map_col, width=360, height=360, fg_color="#111111"
        )
        self.farms_minimap_host.pack_propagate(False)
        self.farms_minimap_label = None
        self._farm_map_box = (348, 348)
        self.farms_minimap_host.bind("<Configure>", self._on_farm_minimap_configure)

        self.farms_island_tools = ctk.CTkFrame(self.farms_list_col, fg_color="transparent")
        ctk.CTkButton(
            self.farms_island_tools, text=self.s.select_all, width=100, command=self._farms_all
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            self.farms_island_tools, text=self.s.clear, width=80, command=self._farms_clear
        ).pack(side="left", padx=2)

        self.farms_frame = ctk.CTkFrame(self.farms_list_col, fg_color="transparent")
        self.farm_vars: dict[str, tk.BooleanVar] = {}

        self.farms_edit_group = self._settings_group(scroll, pack=False)
        self.farms_edit_row = ctk.CTkFrame(self.farms_edit_group, fg_color="transparent")
        self.btn_edit_map = ctk.CTkButton(
            self.farms_edit_row, text=self.s.edit_patrol, width=140, command=self._open_map_editor
        )
        self.btn_edit_map.pack(anchor="w")

        self.farms_rotate_group = self._settings_group(scroll)
        self.farms_rotate = ctk.CTkFrame(self.farms_rotate_group, fg_color="transparent")
        self.rotate_var = tk.DoubleVar(value=self.profile.farm_rotate_s / 60.0)
        ctk.CTkLabel(self.farms_rotate, text=self.s.rotate_farms).pack(anchor="w")
        self.farms_rotate_slider = ctk.CTkSlider(
            self.farms_rotate,
            from_=1,
            to=30,
            variable=self.rotate_var,
            command=lambda _=None: self._save_farms(),
        )
        self.farms_rotate_slider.pack(fill="x", pady=4)
        disable_slider_mousewheel(self.farms_rotate_slider)

        self._reload_farm_checks()

    def _build_map_editor(self) -> None:
        self.editor_bar = ctk.CTkFrame(self.editor_host, fg_color="transparent")
        self.editor_bar_title = ctk.CTkLabel(
            self.editor_bar,
            text=self.s.edit_patrol,
            font=ctk.CTkFont(weight="bold"),
        )
        self.editor_bar_title.pack(side="left", padx=4)
        self.btn_editor_close = ctk.CTkButton(
            self.editor_bar,
            text=self.s.editor_close,
            width=90,
            command=self._on_editor_close,
        )
        self.btn_editor_close.pack(side="right", padx=4)
        self.map_editor = MapEditor(
            self.editor_host,
            strings=self.s,
            language=self.profile.language,
            can_edit=self._can_edit_map_silent,
            on_changed=self._on_map_edited,
            on_done=self._close_map_editor,
        )

    def _on_editor_close(self) -> None:
        if hasattr(self, "map_editor"):
            self.map_editor.dismiss()
        else:
            self._close_map_editor()

    def _can_edit_map_silent(self) -> bool:
        return self.controller.state != RunState.RUNNING

    def _open_map_editor(self) -> None:
        if not is_dungeon_map_id(self.profile.active_map):
            return
        if not self._can_edit_map():
            return
        self._edit_open = True
        self.tabs.set(self.tab_names["farms"])
        self._sync_side_panel()

    def _close_map_editor(self) -> None:
        if not self._edit_open:
            return
        self._edit_open = False
        self._sync_side_panel()
        self._reload_farm_checks()
        self._refresh_lamps()
        self._refresh_buttons()

    def _ensure_side_host(self) -> None:
        if str(self.editor_host.winfo_manager()):
            return
        self.left.pack_propagate(False)
        self.left.configure(width=self._left_w)
        self.left.pack_configure(expand=False, fill="both")
        self.editor_host.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=8)
        self._expand_for_edit()

    def _show_farms_editor_panel(self) -> None:
        self._ensure_side_host()
        if hasattr(self, "editor_bar_title"):
            self.editor_bar_title.configure(text=self.s.edit_patrol)
        if hasattr(self, "editor_bar") and not str(self.editor_bar.winfo_manager()):
            self.editor_bar.pack(fill="x", pady=(0, 4))
        if not str(self.map_editor.winfo_manager()):
            self.map_editor.pack(fill="both", expand=True)
        self.map_editor.load_map(self.profile.active_map)

    def _hide_side_panel(self) -> None:
        if hasattr(self, "map_editor"):
            self.map_editor.pack_forget()
        if hasattr(self, "editor_bar"):
            self.editor_bar.pack_forget()
        if not str(self.editor_host.winfo_manager()):
            return
        self.editor_host.pack_forget()
        self.left.pack_propagate(True)
        self.left.pack_configure(expand=True, fill="both")
        self._restore_compact_window()

    def _sync_side_panel(self, name: str = "") -> None:
        if not hasattr(self, "map_editor"):
            return
        current = name or ""
        try:
            if not current:
                current = self.tabs.get()
        except Exception:
            current = ""
        if self._edit_open and current == self.tab_names["farms"]:
            self._show_farms_editor_panel()
        else:
            self._hide_side_panel()

    def _on_tab_changed(self, name: str = "") -> None:
        self._sync_side_panel(name)

    def _expand_for_edit(self) -> None:
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(self._edit_w, max(900, sw - 40))
        h = min(self._edit_h, max(640, sh - 80))
        x, y = self.winfo_x(), self.winfo_y()
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.minsize(900, 640)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _restore_compact_window(self) -> None:
        self.update_idletasks()
        x, y = self.winfo_x(), self.winfo_y()
        self.minsize(880, 640)
        self.geometry(f"{self._ctrl_w}x{self._ctrl_h}+{x}+{y}")

    def _pack_farms_layout(self, dungeon: bool) -> None:
        for w in (
            self.farms_head,
            self.farms_body,
            self.farms_list_col,
            self.farms_map_col,
            self.farms_minimap_host,
            self.farms_island_tools,
            self.farms_frame,
            self.farms_edit_group,
            self.farms_edit_row,
            self.farms_rotate,
            self.farms_rotate_group,
        ):
            w.pack_forget()
        self.farms_head.pack(fill="x", padx=12, pady=(8, 0))
        self.farms_body.pack(fill="x", padx=8, pady=8)
        if dungeon:
            self.farms_map_col.pack(fill="x")
            self.farms_minimap_host.pack(anchor="n")
        else:
            self.farms_list_col.pack(side="left", anchor="n")
            self.farms_island_tools.pack(fill="x", pady=(0, 4))
            self.farms_frame.pack(fill="x")
            self.farms_map_col.pack(side="left", fill="both", expand=True)
            self.farms_minimap_host.pack(anchor="n")
        if dungeon:
            self.btn_edit_map.configure(text=self.s.edit_patrol)
            self.farms_edit_group.pack(fill="x", padx=8, pady=6)
            self.farms_edit_row.pack(fill="x", padx=12, pady=8)
        if not dungeon:
            self.farms_rotate_group.pack(fill="x", padx=8, pady=6)
            self.farms_rotate.pack(fill="x", padx=12, pady=(4, 10))

    def _on_map_chosen(self, _value: str | None = None) -> None:
        if self.controller.state == RunState.RUNNING:
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            self._sync_map_combo()
            return
        labels = [name for _mid, name, _d in self._map_choices]
        ids = [mid for mid, _n, _d in self._map_choices]
        display = self.map_var.get()
        if display not in labels:
            return
        new_id = ids[labels.index(display)]
        if new_id == self.profile.active_map:
            self._refresh_map_preview()
            return
        self.profile.active_map = new_id
        self.profile.selected_farms = []
        save_profile(self.profile)
        self._refresh_map_preview()
        if hasattr(self, "farms_frame"):
            self._reload_farm_checks()
        if getattr(self, "_edit_open", False):
            if is_dungeon_map_id(new_id):
                self.map_editor.load_map(new_id)
            else:
                self._close_map_editor()
        self._refresh_lamps()
        self._refresh_buttons()

    def _sync_map_combo(self) -> None:
        labels = [name for _mid, name, _d in self._map_choices]
        ids = [mid for mid, _n, _d in self._map_choices]
        if self.profile.active_map in ids:
            self.map_var.set(labels[ids.index(self.profile.active_map)])
        self._refresh_map_preview()

    def _on_setup_visual_configure(self, event) -> None:
        """Keep map/character previews inside equal columns so they never overlap."""
        if getattr(event, "widget", None) is not getattr(self, "_setup_visual", None):
            return
        w = int(getattr(event, "width", 0) or 0)
        if w < 80:
            return
        col = max(160, (w // 2) - 16)
        if abs(col - int(getattr(self, "_setup_fit_w", 0) or 0)) < 8:
            return
        self._setup_fit_w = col
        self._map_preview_w = col
        self._map_preview_h = self._setup_preview_h
        radio_reserve = 54 + 110
        self._char_preview_w = max(120, min(320, col - radio_reserve))
        self._char_preview_h = self._setup_preview_h
        try:
            self._map_preview_host.configure(height=self._map_preview_h)
            self._char_preview_host.configure(
                width=self._char_preview_w, height=self._char_preview_h
            )
        except Exception:
            pass
        self._refresh_map_preview()
        self._refresh_character_preview()

    def _paint_still_preview(
        self,
        host,
        label_attr: str,
        ctk_attr: str,
        pil_attr: str,
        path,
        box: tuple[int, int],
        missing_text: str,
        *,
        cover: bool = False,
    ) -> None:
        """Fit ``path`` into a fixed host; rebuild the label so CTkImage updates."""
        old = getattr(self, label_attr, None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass

        from PIL import Image

        max_w, max_h = max(1, int(box[0])), max(1, int(box[1]))
        text = ""
        try:
            if path is not None:
                im = Image.open(path)
                im.load()
            else:
                im = Image.new("RGB", (max_w, max_h), (28, 28, 28))
                text = missing_text
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            w, h = im.size
            if cover:
                # Fill height; keep the full width (no side crop). Shrink only
                # if the column is too narrow.
                scale = max_h / max(h, 1)
                nw = max(1, int(round(w * scale)))
                nh = max_h
                if nw > max_w:
                    scale = max_w / max(w, 1)
                    nw = max(1, int(round(w * scale)))
                    nh = max(1, int(round(h * scale)))
                im = im.resize((nw, nh), Image.Resampling.LANCZOS)
                try:
                    host.configure(width=nw, height=max_h)
                except Exception:
                    pass
                ctk_img = ctk.CTkImage(light_image=im, dark_image=im, size=(nw, nh))
            else:
                scale = min(max_w / max(w, 1), max_h / max(h, 1))
                nw = max(1, int(w * scale))
                nh = max(1, int(h * scale))
                ctk_img = ctk.CTkImage(light_image=im, dark_image=im, size=(nw, nh))
        except Exception:
            im = Image.new("RGB", (max_w, max_h), (28, 28, 28))
            text = missing_text
            nw, nh = max_w, max_h
            ctk_img = ctk.CTkImage(light_image=im, dark_image=im, size=(max_w, max_h))
        setattr(self, pil_attr, im)
        setattr(self, ctk_attr, ctk_img)
        label = ctk.CTkLabel(
            host,
            text=text,
            image=ctk_img,
            compound="center",
            text_color="gray",
            fg_color="transparent",
            width=nw,
            height=nh,
        )
        label.pack(expand=True, fill="both" if not cover else "none")
        inner = getattr(label, "_label", None)
        if inner is not None:
            try:
                inner.configure(bd=0, padx=0, pady=0, highlightthickness=0)
            except Exception:
                pass
        setattr(self, label_attr, label)

    def _refresh_map_preview(self) -> None:
        """Decorative setup previews are disabled in the classic UI."""
        return

    def _refresh_character_preview(self) -> None:
        """Decorative setup portraits are disabled in the classic UI."""
        return

    def _on_character_chosen(self) -> None:
        self._save_setup_fields()
        self._refresh_character_preview()

    def _on_map_edited(self) -> None:
        self._reload_farm_checks()
        self._refresh_lamps()
        self._refresh_buttons()

    def _on_farm_minimap_configure(self, event) -> None:
        if getattr(event, "widget", None) is not getattr(self, "farms_minimap_host", None):
            return
        w = max(80, int(getattr(event, "width", 0) or 0) - 12)
        h = max(80, min(360, int(getattr(event, "height", 0) or 0) - 8))
        prev = getattr(self, "_farm_map_box", (0, 0))
        if abs(w - prev[0]) < 8 and abs(h - prev[1]) < 8:
            return
        self._farm_map_box = (w, h)
        self._refresh_farm_minimap()

    def _refresh_farm_minimap(self) -> None:
        if not hasattr(self, "farms_minimap_host"):
            return
        box = getattr(self, "_farm_map_box", (348, 348))
        if is_dungeon_map_id(self.profile.active_map):
            selected: list[str] = []
        elif self.farm_vars:
            selected = [n for n, v in self.farm_vars.items() if v.get()]
        else:
            selected = list(self.profile.selected_farms)
        im, missing = render_farm_overview(
            self.profile.active_map, selected, box[0], box[1]
        )
        text = self.s.map_missing_short if missing else ""
        nw, nh = im.size
        ctk_img = ctk.CTkImage(light_image=im, dark_image=im, size=(nw, nh))
        self._farm_minimap_pil = im
        self._farm_minimap_ctk = ctk_img
        label = getattr(self, "farms_minimap_label", None)
        if label is None or not label.winfo_exists():
            label = ctk.CTkLabel(
                self.farms_minimap_host,
                text=text,
                image=ctk_img,
                compound="center",
                text_color="gray",
                fg_color="transparent",
                width=nw,
                height=nh,
            )
            label.pack(expand=True)
            inner = getattr(label, "_label", None)
            if inner is not None:
                try:
                    inner.configure(bd=0, padx=0, pady=0, highlightthickness=0)
                except Exception:
                    pass
            self.farms_minimap_label = label
        else:
            label.configure(image=ctk_img, text=text, width=nw, height=nh)

    def _update_farms_banner(self, names: list[str] | None = None, err: str | None = None) -> None:
        dungeon = is_dungeon_map_id(self.profile.active_map)
        pack_name = next(
            (n for mid, n, _d in getattr(self, "_map_choices", []) if mid == self.profile.active_map),
            self.profile.active_map,
        )
        self.farms_heading.configure(text=pack_name)
        if dungeon:
            self.farms_banner.configure(text=self.s.farms_unsupported_dungeon)
            return
        if names is None:
            names, err = list_farms_for_map(self.profile.active_map)
        if err and not names:
            self.farms_banner.configure(text=err)
        elif not self.profile.selected_farms:
            self.farms_banner.configure(text=self.s.farms_hint_empty)
        else:
            n = len([x for x in self.profile.selected_farms if x in names])
            self.farms_banner.configure(
                text=self.s.farms_banner.format(
                    n=n,
                    total=len(names),
                    minutes=self.profile.farm_rotate_s / 60,
                )
            )

    def _reload_farm_checks(self) -> None:
        for w in self.farms_frame.winfo_children():
            w.destroy()
        self.farm_vars.clear()
        dungeon = is_dungeon_map_id(self.profile.active_map)
        self._pack_farms_layout(dungeon)
        if dungeon:
            self._update_farms_banner()
            self._refresh_farm_minimap()
            return
        names, err = list_farms_for_map(self.profile.active_map)
        self._update_farms_banner(names, err)
        for name in names:
            var = tk.BooleanVar(value=name in self.profile.selected_farms)
            self.farm_vars[name] = var
            ctk.CTkCheckBox(
                self.farms_frame,
                text=route_point_display_name(name, self.profile.language),
                variable=var,
                command=self._save_farms,
            ).pack(anchor="w", padx=4, pady=2)
        self._refresh_farm_minimap()

    def _farms_all(self) -> None:
        for v in self.farm_vars.values():
            v.set(True)
        self._save_farms()

    def _farms_clear(self) -> None:
        for v in self.farm_vars.values():
            v.set(False)
        self._save_farms()

    def _save_farms(self) -> None:
        if self.controller.state == RunState.RUNNING:
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            self._reload_farm_checks()
            return
        if is_dungeon_map_id(self.profile.active_map):
            return
        self.profile.selected_farms = [n for n, v in self.farm_vars.items() if v.get()]
        self.profile.farm_rotate_s = float(self.rotate_var.get()) * 60.0
        save_profile(self.profile)
        self._update_farms_banner()
        self._refresh_farm_minimap()
        self._refresh_lamps()
        self._refresh_buttons()

    def _can_edit_map(self) -> bool:
        if self.controller.state == RunState.RUNNING:
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            return False
        return True

    # ── Species tab ───────────────────────────────────────────────────────

    def _build_species(self) -> None:
        self.species_panel = SpeciesPanel(self.tab_species, self)

    def _reload_species(self) -> None:
        if hasattr(self, "species_panel"):
            self.species_panel.reload()

    # ── Spells tab ────────────────────────────────────────────────────────

    def _build_spells(self) -> None:
        t = self.tab_spells
        scroll = ctk.CTkScrollableFrame(t)
        scroll.pack(fill="both", expand=True)
        self._spells_syncing = True
        self._spell_view_box = 1

        intro = self._settings_group(scroll, self.s.spells_heading)
        ctk.CTkLabel(
            intro,
            text=self.s.spells_hint,
            wraplength=380,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=4)
        ctk.CTkLabel(
            intro,
            text=self.s.spell_gcd_note,
            wraplength=380,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        usage = self._settings_group(scroll, self.s.spells_usage_heading)
        self.heal_until_var = self._range_slider(
            usage,
            self.s.spell_heal_until,
            self.profile.heal_until_hp_ratio,
            10,
            95,
            suffix="%",
            as_percent=True,
        )
        self.spell_reserve_var = self._range_slider(
            usage,
            self.s.spell_mana_reserve,
            self.profile.spell_reserve_ratio,
            5,
            50,
            suffix="%",
            as_percent=True,
        )

        detected = self._settings_group(scroll, self.s.spells_detected_heading)
        box_row = ctk.CTkFrame(detected, fg_color="transparent")
        box_row.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(box_row, text=self.s.spells_box).pack(side="left")
        self.spell_box_seg = ctk.CTkSegmentedButton(
            box_row,
            values=[self.s.spells_box_n.format(n=i) for i in (1, 2, 3)],
            command=self._on_spell_box,
        )
        self.spell_box_seg.pack(side="left", padx=(8, 0), fill="x", expand=True)
        self.spell_box_seg.set(self.s.spells_box_n.format(n=1))

        ctk.CTkLabel(
            detected,
            text=self.s.spells_cell_hint,
            wraplength=380,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        self.spell_waiting_lab = ctk.CTkLabel(
            detected,
            text=self.s.spells_waiting_scan,
            wraplength=380,
            justify="left",
            text_color="gray",
        )
        self.spell_waiting_lab.pack(anchor="w", padx=12, pady=(0, 6))

        grid = ctk.CTkFrame(detected)
        grid.pack(fill="x", padx=12, pady=(0, 10))
        for col in range(4):
            grid.grid_columnconfigure(col, weight=1)
        self.spell_cell_labels: dict[str, ctk.CTkLabel] = {}
        for row_i, row_keys in enumerate(SKILL_GRID):
            for col_i, key in enumerate(row_keys):
                cell = ctk.CTkFrame(grid, fg_color="#2a2a32", corner_radius=6)
                cell.grid(row=row_i, column=col_i, sticky="nsew", padx=2, pady=2)
                lab = ctk.CTkLabel(
                    cell,
                    text=f"{key.upper()}\n—",
                    justify="center",
                    wraplength=90,
                    height=64,
                )
                lab.pack(fill="both", expand=True, padx=4, pady=4)
                self.spell_cell_labels[key] = lab

        active = self._settings_group(scroll, self.s.spells_active_heading)
        self.spell_active_lab = ctk.CTkLabel(
            active,
            text="",
            wraplength=380,
            justify="left",
        )
        self.spell_active_lab.pack(anchor="w", padx=12, pady=(4, 10))

        self._spells_syncing = False
        self._refresh_spell_detection_view()

    def _range_slider(
        self,
        parent,
        label: str,
        value: float,
        lo: float,
        hi: float,
        *,
        suffix: str,
        as_percent: bool,
    ):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=8, pady=4)
        shown = int(value * 100) if as_percent else int(value)
        lab = ctk.CTkLabel(frame, text=f"{label}: {shown}{suffix}")
        lab.pack(anchor="w")
        var = tk.DoubleVar(value=value * 100 if as_percent else value)

        def render(raw: float) -> str:
            return f"{label}: {int(raw)}{suffix}"

        def on_change(_=None):
            lab.configure(text=render(float(var.get())))
            if not getattr(self, "_spells_syncing", False):
                self._save_spells()

        s = ctk.CTkSlider(frame, from_=lo, to=hi, variable=var, command=on_change)
        s.pack(fill="x")
        disable_slider_mousewheel(s)
        return _PctBar(var, s, lab, render)

    def _on_spell_box(self, value: str) -> None:
        if self._spells_syncing:
            return
        for n in (1, 2, 3):
            if value == self.s.spells_box_n.format(n=n):
                self._spell_view_box = n
                break
        self._refresh_spell_detection_view()

    def _on_hotbar_from_bot(self, layout: dict, slots: dict) -> None:
        def apply() -> None:
            if isinstance(layout, dict):
                self.profile.hotbar_layout = dict(layout)
            if isinstance(slots, dict):
                self.profile.spell_slots = dict(slots)
            self._refresh_spell_detection_view()

        try:
            self.after(0, apply)
        except Exception:
            apply()

    def _refresh_spell_detection_view(self) -> None:
        if not hasattr(self, "spell_cell_labels"):
            return
        layout = self.profile.hotbar_layout if isinstance(
            self.profile.hotbar_layout, dict
        ) else {}
        boxes = layout.get("boxes") if isinstance(layout.get("boxes"), dict) else {}
        has_scan = bool(boxes)
        if hasattr(self, "spell_waiting_lab"):
            if has_scan:
                self.spell_waiting_lab.pack_forget()
            else:
                self.spell_waiting_lab.configure(text=self.s.spells_waiting_scan)
                if not self.spell_waiting_lab.winfo_ismapped():
                    self.spell_waiting_lab.pack(anchor="w", padx=12, pady=(0, 6))

        box_key = str(self._spell_view_box)
        box_cells = boxes.get(box_key) if isinstance(boxes.get(box_key), dict) else {}
        for key in SKILL_KEYS:
            lab = self.spell_cell_labels.get(key)
            if lab is None:
                continue
            cell = box_cells.get(key) if isinstance(box_cells.get(key), dict) else {}
            kr = str(cell.get("kr_name") or "").strip()
            zh = str(cell.get("zh_name") or "").strip()
            role = str(cell.get("role") or "").strip()
            bound = bool(cell.get("bound"))
            from manmabot_v1.localized_names import memory_name_for_ui

            name = memory_name_for_ui(kr or zh, self.profile.language) or self.s.spell_empty
            kind = str(cell.get("kind") or "").upper()
            count = cell.get("count")
            if count in (None, "") and (kr or zh):
                from manmabot_v1.hotbar.inspect import count_from_hotbar_label

                count = count_from_hotbar_label(kr or zh)
            if kind == "ITEM" and count not in (None, "", 0):
                name = f"{name} ×{count}"
            if role and bound:
                role_title = self.s.spell_titles.get(role, role)
                text = f"{key.upper()}\n{name}\n→ {role_title}"
                color = "white"
            elif role:
                role_title = self.s.spell_titles.get(role, role)
                text = f"{key.upper()}\n{name}\n{role_title} ({self.s.spells_ignored})"
                color = "gray"
            elif kr or zh:
                text = f"{key.upper()}\n{name}\n{self.s.spells_unmapped}"
                color = "gray"
            else:
                text = f"{key.upper()}\n—"
                color = "gray"
            lab.configure(text=text, text_color=color)

        if hasattr(self, "spell_box_seg"):
            self.spell_box_seg.set(
                self.s.spells_box_n.format(n=self._spell_view_box)
            )

        lines: list[str] = []
        for sid in SLOT_IDS:
            spec = self.profile.spell_slots.get(sid) or {}
            enabled = bool(spec.get("enabled"))
            box = int(spec.get("box") or 0)
            key = str(spec.get("key") or "")
            title = self.s.spell_titles.get(sid, sid)
            if enabled and box in (1, 2, 3) and key:
                lines.append(
                    f"• {title}: {self.s.spells_box_n.format(n=box)} / {key.upper()}"
                )
            else:
                lines.append(f"• {title}: {self.s.spell_off}")
        if hasattr(self, "spell_active_lab"):
            self.spell_active_lab.configure(
                text="\n".join(lines) if lines else self.s.spells_waiting_scan
            )

        if hasattr(self, "heal_until_var"):
            self._spells_syncing = True
            try:
                self.heal_until_var.set(self.profile.heal_until_hp_ratio * 100)
                self.spell_reserve_var.set(self.profile.spell_reserve_ratio * 100)
            finally:
                self._spells_syncing = False

    def _sync_spells_ui(self) -> None:
        self._refresh_spell_detection_view()

    def _save_spells(self) -> None:
        if self._spells_syncing:
            return
        if self.controller.state == RunState.RUNNING:
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            self._sync_spells_ui()
            return
        self.profile.heal_until_hp_ratio = float(self.heal_until_var.get()) / 100.0
        self.profile.spell_reserve_ratio = float(self.spell_reserve_var.get()) / 100.0
        save_profile(self.profile)

    # ── Hotkeys (Advanced section) ────────────────────────────────────────

    def _build_hotkeys(self, parent) -> None:
        ctk.CTkLabel(
            parent,
            text=self.s.hotkeys_intro,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))
        self.hotkey_labels: dict[str, ctk.CTkLabel] = {}
        for key, title in self.s.hotkey_labels.items():
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(row, text=title, width=140, anchor="w").pack(side="left")
            lab = ctk.CTkLabel(
                row, text=self.profile.hotkeys.get(key, ""), width=100
            )
            lab.pack(side="left", padx=8)
            self.hotkey_labels[key] = lab
            ctk.CTkButton(
                row,
                text=self.s.change,
                width=80,
                command=lambda k=key: self._change_hotkey(k),
            ).pack(side="right", padx=4)
        ctk.CTkButton(
            parent, text=self.s.reset_hotkeys, command=self._reset_hotkeys, width=160
        ).pack(anchor="w", padx=12, pady=8)
        ctk.CTkLabel(
            parent,
            text=self.s.hotkeys_tip,
            wraplength=380,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def _change_hotkey(self, action: str) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title(self.s.change_shortcut_title)
        dlg.geometry("320x120")
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(
            dlg,
            text=self.s.press_new_shortcut.format(
                action=self.s.hotkey_labels[action]
            ),
        ).pack(pady=16)
        status = ctk.CTkLabel(dlg, text=self.s.waiting)
        status.pack()

        def on_key(event):
            mods = []
            if event.state & 0x4:
                mods.append("ctrl")
            if event.state & 0x20000 or event.state & 0x8:
                mods.append("alt")
            if event.state & 0x1:
                mods.append("shift")
            key = event.keysym.lower()
            if key in ("control_l", "control_r", "alt_l", "alt_r", "shift_l", "shift_r"):
                return
            if key == "escape":
                dlg.destroy()
                return
            combo = "+".join(mods + [key]) if mods else key
            if not mods:
                messagebox.showwarning(
                    self.s.tab_hotkeys, self.s.hotkey_need_modifier
                )
                return
            # conflict
            for a, c in self.profile.hotkeys.items():
                if a != action and c == combo:
                    messagebox.showerror(
                        self.s.tab_hotkeys,
                        self.s.hotkey_conflict.format(
                            action=self.s.hotkey_labels.get(a, a)
                        ),
                    )
                    return
            self.profile.hotkeys[action] = combo
            save_profile(self.profile)
            self.hotkey_labels[action].configure(text=combo)
            err = self._rebind_hotkeys()
            if err:
                messagebox.showerror(self.s.tab_hotkeys, err)
            dlg.destroy()

        dlg.bind("<KeyPress>", on_key)
        dlg.focus_force()

    def _reset_hotkeys(self) -> None:
        if not messagebox.askyesno(self.s.tab_hotkeys, self.s.restore_hotkeys_q):
            return

        self.profile.hotkeys = dict(DEFAULT_HOTKEYS)
        save_profile(self.profile)
        for k, lab in self.hotkey_labels.items():
            lab.configure(text=self.profile.hotkeys[k])
        self._rebind_hotkeys()

    # ── Advanced tab ──────────────────────────────────────────────────────

    def _build_advanced(self) -> None:
        t = self.tab_advanced
        scroll = ctk.CTkScrollableFrame(t)
        scroll.pack(fill="both", expand=True)
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=4, pady=4)
        row.grid_columnconfigure(0, weight=1, uniform="advanced")
        row.grid_columnconfigure(1, weight=1, uniform="advanced")
        row.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(row, fg_color="transparent")
        right = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        general = self._settings_group(left)
        self.var_aot = tk.BooleanVar(value=self.profile.always_on_top)
        ctk.CTkCheckBox(
            general,
            text=self.s.always_on_top,
            variable=self.var_aot,
            command=self._save_advanced,
        ).pack(anchor="w", padx=12, pady=(10, 8))

        ctk.CTkLabel(general, text=self.s.language).pack(
            anchor="w", padx=12, pady=(4, 2)
        )
        self._language_display_to_code = {
            display: code for code, display in LANGUAGE_CHOICES
        }
        self._language_code_to_display = {
            code: display for code, display in LANGUAGE_CHOICES
        }
        self.language_menu = ctk.CTkOptionMenu(
            general,
            values=[display for _, display in LANGUAGE_CHOICES],
            command=self._change_language,
        )
        self.language_menu.set(
            self._language_code_to_display[normalize_language(self.profile.language)]
        )
        self.language_menu.pack(anchor="w", padx=12, pady=2)
        ctk.CTkLabel(general, text=self.s.language_hint, text_color="gray").pack(
            anchor="w", padx=12, pady=(0, 10)
        )

        profiles = self._settings_group(left, self.s.profiles_section)
        ctk.CTkLabel(profiles, text=self.s.profile_save_as).pack(
            anchor="w", padx=12, pady=(2, 2)
        )
        self.profile_name_var = tk.StringVar()
        self.profile_name_entry = ctk.CTkEntry(
            profiles,
            textvariable=self.profile_name_var,
            placeholder_text=self.s.profile_name,
        )
        self.profile_name_entry.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(
            profiles,
            text=self.s.profile_save,
            width=100,
            command=self._save_named_profile,
        ).pack(anchor="w", padx=12, pady=(0, 10))
        ctk.CTkLabel(profiles, text=self.s.profile_saved_profiles).pack(
            anchor="w", padx=12, pady=(0, 2)
        )
        self.profile_selected_var = tk.StringVar(value=self.s.profile_select)
        self.profile_menu = ctk.CTkOptionMenu(
            profiles,
            values=[self.s.profile_select],
            variable=self.profile_selected_var,
        )
        self.profile_menu.pack(fill="x", padx=12, pady=2)
        profile_buttons = ctk.CTkFrame(profiles, fg_color="transparent")
        profile_buttons.pack(fill="x", padx=12, pady=(6, 10))
        ctk.CTkButton(
            profile_buttons,
            text=self.s.profile_load,
            width=100,
            command=self._load_named_profile,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            profile_buttons,
            text=self.s.profile_delete,
            width=100,
            fg_color="#b91c1c",
            command=self._delete_named_profile,
        ).pack(side="left")
        self._refresh_profile_menu()

        accounts = self._settings_group(right, self.s.accounts_section)
        ctk.CTkLabel(
            accounts,
            text=self.s.account_secure_hint,
            wraplength=360,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(2, 6))
        self.account_selected_var = tk.StringVar(value=self.s.account_none)
        self.account_menu = ctk.CTkOptionMenu(
            accounts,
            values=[self.s.account_none],
            variable=self.account_selected_var,
            command=self._select_account,
        )
        self.account_menu.pack(fill="x", padx=12, pady=2)
        account_buttons = ctk.CTkFrame(accounts, fg_color="transparent")
        account_buttons.pack(fill="x", padx=12, pady=(6, 10))
        ctk.CTkButton(
            account_buttons,
            text=self.s.account_add,
            width=80,
            command=lambda: self._open_account_dialog(None),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            account_buttons,
            text=self.s.account_update,
            width=80,
            command=self._update_selected_account,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            account_buttons,
            text=self.s.account_delete,
            width=80,
            fg_color="#b91c1c",
            command=self._delete_account,
        ).pack(side="left", padx=4)
        self._refresh_account_menu()

        hotkeys = self._settings_group(right, self.s.tab_hotkeys)
        self._build_hotkeys(hotkeys)

        setup = self._settings_group(left, self.s.setup_section)
        ctk.CTkButton(
            setup, text=self.s.run_wizard, width=160, command=self._open_wizard
        ).pack(anchor="w", padx=12, pady=(4, 10))

        logs = self._settings_group(right, self.s.logs_support)
        log_row = ctk.CTkFrame(logs, fg_color="transparent")
        log_row.pack(anchor="w", padx=12, pady=(0, 10))
        ctk.CTkButton(
            log_row, text=self.s.open_log_folder, width=130, command=self._open_logs
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            log_row, text=self.s.copy_diagnostics, width=130, command=self._copy_diag
        ).pack(side="left", padx=2)

        danger = self._settings_group(right, self.s.danger_zone)
        ctk.CTkButton(
            danger,
            text=self.s.reset_all,
            fg_color="#b91c1c",
            command=self._reset_all,
        ).pack(anchor="w", padx=12, pady=(4, 10))

    # ── Log tab ───────────────────────────────────────────────────────────

    def _build_log(self) -> None:
        box = self._settings_group(self.tab_log, fill="both", expand=True)
        self.log_box = ctk.CTkTextbox(box, state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)

    # ── persistence helpers ───────────────────────────────────────────────

    def _refresh_account_menu(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "account_menu"):
            return
        try:
            self._accounts = AccountStore().load()
        except AccountStoreError:
            self._accounts = []
        self._account_display_to_id = {
            f"{account.display_name} — {account.username}": account.account_id
            for account in self._accounts
        }
        values = [self.s.account_none, *self._account_display_to_id]
        wanted = selected_id if selected_id is not None else self.profile.selected_account_id
        chosen = next(
            (
                f"{account.display_name} — {account.username}"
                for account in self._accounts
                if account.account_id == wanted
            ),
            self.s.account_none,
        )
        self.account_menu.configure(values=values)
        self.account_selected_var.set(chosen)
        self.account_menu.set(chosen)

    def _selected_account(self) -> Account | None:
        selected_id = getattr(self, "_account_display_to_id", {}).get(
            self.account_selected_var.get()
        )
        return next(
            (
                account
                for account in getattr(self, "_accounts", [])
                if account.account_id == selected_id
            ),
            None,
        )

    def _select_account(self, display: str) -> None:
        if self._arming:
            self._refresh_account_menu(self.profile.selected_account_id)
            return
        selected_id = getattr(self, "_account_display_to_id", {}).get(display)
        self.profile.selected_account_id = selected_id
        save_profile(self.profile)

    def _update_selected_account(self) -> None:
        if self._arming:
            return
        account = self._selected_account()
        if account is None:
            messagebox.showwarning(
                self.s.account_error_title, self.s.account_none, parent=self
            )
            return
        self._open_account_dialog(account)

    def _open_account_dialog(self, account: Account | None) -> None:
        if self._arming:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(
            self.s.account_update if account is not None else self.s.account_add
        )
        dialog.geometry("700x540")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        display_name = tk.StringVar(value=account.display_name if account else "")
        username = tk.StringVar(value=account.username if account else "")
        password = tk.StringVar(value=account.password if account else "")
        language_labels = {
            "ko": self.s.account_server_language_ko,
            "zh-CN": self.s.account_server_language_zh_cn,
            "zh-TW": self.s.account_server_language_zh_tw,
            "ja": self.s.account_server_language_ja,
        }
        label_to_locale = {label: code for code, label in language_labels.items()}
        initial_locale = normalize_server_language(
            account.locale if account else "ko",
            account.region if account else "Korea",
        )
        if initial_locale not in language_labels:
            initial_locale = "ko"
        server_language = tk.StringVar(value=language_labels[initial_locale])
        server = tk.StringVar(value=account.server if account else "")
        raw_character = int(account.character_number) if account else 1
        if not 1 <= raw_character <= 3:
            raw_character = 1
        character = tk.StringVar(value=str(raw_character))
        click_mode = tk.StringVar(value=account.click_mode if account else "dynamic")
        purple_path = tk.StringVar(
            value=(
                account.purple_launcher_path
                if account and account.purple_launcher_path
                else _default_purple_launcher_path()
            )
        )
        game_path = tk.StringVar(
            value=(
                account.game_path
                if account and account.game_path
                else _DEFAULT_GAME_EXECUTABLE
            )
        )
        fields = ctk.CTkFrame(dialog, fg_color="transparent")
        fields.pack(fill="both", expand=True, padx=16, pady=12)
        fields.grid_columnconfigure(1, weight=1)

        def browse_executable(variable: tk.StringVar, title: str) -> None:
            current = Path(variable.get()).expanduser()
            initial_dir = current.parent if str(current.parent) else Path.home()
            selected = filedialog.askopenfilename(
                parent=dialog,
                title=title,
                initialdir=str(initial_dir),
                filetypes=[
                    ("Executable files", "*.exe"),
                    ("All files", "*.*"),
                ],
            )
            if selected:
                variable.set(selected)

        def label(row: int, text: str) -> None:
            ctk.CTkLabel(fields, text=text, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=6
            )

        def selected_locale() -> str:
            return label_to_locale.get(server_language.get(), "ko")

        label(0, self.s.account_display_name)
        ctk.CTkEntry(fields, textvariable=display_name).grid(
            row=0, column=1, sticky="ew", pady=6
        )
        label(1, self.s.account_username)
        ctk.CTkEntry(fields, textvariable=username).grid(
            row=1, column=1, sticky="ew", pady=6
        )
        label(2, self.s.account_password)
        ctk.CTkEntry(fields, textvariable=password, show="•").grid(
            row=2, column=1, sticky="ew", pady=6
        )

        def refresh_servers(*_args) -> None:
            names = server_names_list(selected_locale())
            if not names:
                names = [""]
            current = server.get().strip()
            chosen = current if current in names else names[0]
            server.set(chosen)
            server_menu.configure(values=names)
            try:
                server_menu.set(chosen)
            except Exception:
                pass

        label(3, self.s.account_server_language)
        ctk.CTkOptionMenu(
            fields,
            variable=server_language,
            values=[language_labels[code] for code in SERVER_LANGUAGE_CODES],
            command=refresh_servers,
        ).grid(row=3, column=1, sticky="ew", pady=6)
        label(4, self.s.account_server)
        initial_servers = server_names_list(selected_locale()) or [""]
        if server.get().strip() not in initial_servers:
            server.set(initial_servers[0])
        server_menu = ctk.CTkOptionMenu(
            fields,
            variable=server,
            values=initial_servers,
        )
        server_menu.grid(row=4, column=1, sticky="ew", pady=6)
        label(5, self.s.account_character)
        ctk.CTkOptionMenu(
            fields,
            variable=character,
            values=[str(number) for number in range(1, 4)],
        ).grid(row=5, column=1, sticky="ew", pady=6)
        label(6, self.s.account_click_mode)
        ctk.CTkOptionMenu(
            fields,
            variable=click_mode,
            values=["dynamic", "fixed", "hybrid"],
        ).grid(row=6, column=1, sticky="ew", pady=6)
        label(7, self.s.account_purple_path)
        ctk.CTkEntry(fields, textvariable=purple_path).grid(
            row=7, column=1, sticky="ew", pady=6
        )
        ctk.CTkButton(
            fields,
            text=self.s.account_browse,
            width=90,
            command=lambda: browse_executable(
                purple_path, self.s.account_purple_path
            ),
        ).grid(row=7, column=2, padx=(8, 0), pady=6)
        label(8, self.s.account_game_path)
        ctk.CTkEntry(fields, textvariable=game_path).grid(
            row=8, column=1, sticky="ew", pady=6
        )
        ctk.CTkButton(
            fields,
            text=self.s.account_browse,
            width=90,
            command=lambda: browse_executable(
                game_path, self.s.account_game_path
            ),
        ).grid(row=8, column=2, padx=(8, 0), pady=6)

        def save_account() -> None:
            locale_code = selected_locale()
            region_name = region_for_locale(locale_code)
            try:
                candidate = (
                    Account(
                        account_id=account.account_id,
                        username=username.get(),
                        password=password.get(),
                        region=region_name,
                        server=server.get(),
                        character_number=character.get(),
                        click_mode=click_mode.get(),
                        display_name=display_name.get(),
                        locale=locale_code,
                        purple_launcher_path=purple_path.get(),
                        game_path=game_path.get(),
                    )
                    if account is not None
                    else Account.create(
                        username.get(),
                        password.get(),
                        region_name,
                        server.get(),
                        character_number=character.get(),
                        click_mode=click_mode.get(),
                        display_name=display_name.get(),
                        locale=locale_code,
                        purple_launcher_path=purple_path.get(),
                        game_path=game_path.get(),
                    )
                )
            except ValueError as exc:
                key = str(exc)
                errors = {
                    "invalid_username": self.s.account_invalid_username,
                    "invalid_password": self.s.account_invalid_password,
                    "invalid_display_name": self.s.account_invalid_display_name,
                    "invalid_server_language": self.s.account_invalid_server_language,
                    "invalid_region": self.s.account_invalid_server_language,
                    "invalid_locale": self.s.account_invalid_server_language,
                    "invalid_server": self.s.account_invalid_server,
                    "invalid_character": self.s.account_invalid_character,
                    "invalid_purple_path": self.s.account_invalid_purple_path,
                    "invalid_game_path": self.s.account_invalid_game_path,
                    "invalid_click_mode": self.s.account_click_mode,
                }
                messagebox.showwarning(
                    self.s.account_error_title,
                    errors.get(key, self.s.account_storage_error),
                    parent=dialog,
                )
                return
            if not candidate.purple_launcher_path or not Path(
                candidate.purple_launcher_path
            ).is_file():
                messagebox.showwarning(
                    self.s.account_error_title,
                    self.s.account_invalid_purple_path,
                    parent=dialog,
                )
                return
            if not candidate.game_path or not Path(candidate.game_path).is_file():
                messagebox.showwarning(
                    self.s.account_error_title,
                    self.s.account_invalid_game_path,
                    parent=dialog,
                )
                return
            duplicate = next(
                (
                    current
                    for current in getattr(self, "_accounts", [])
                    if current.username.casefold() == candidate.username.casefold()
                    and current.account_id != candidate.account_id
                ),
                None,
            )
            if duplicate is not None:
                messagebox.showwarning(
                    self.s.account_error_title,
                    self.s.account_duplicate,
                    parent=dialog,
                )
                return
            try:
                store = AccountStore()
                store.update(candidate) if account is not None else store.add(candidate)
            except (AccountStoreError, KeyError, ValueError):
                messagebox.showerror(
                    self.s.account_error_title,
                    self.s.account_storage_error,
                    parent=dialog,
                )
                return
            self.profile.selected_account_id = candidate.account_id
            save_profile(self.profile)
            self._refresh_account_menu(candidate.account_id)
            dialog.destroy()
            messagebox.showinfo(
                self.s.account_error_title, self.s.account_saved, parent=self
            )

        ctk.CTkButton(
            fields,
            text=self.s.account_update if account is not None else self.s.account_add,
            command=save_account,
        ).grid(row=10, column=1, sticky="e", pady=(14, 4))
        dialog.after(50, dialog.focus_force)

    def _delete_account(self) -> None:
        if self._arming:
            return
        account = self._selected_account()
        if account is None:
            messagebox.showwarning(
                self.s.account_error_title, self.s.account_none, parent=self
            )
            return
        if not messagebox.askyesno(
            self.s.account_error_title,
            self.s.account_delete_q.format(name=account.display_name),
            parent=self,
        ):
            return
        try:
            AccountStore().delete(account.account_id)
        except (AccountStoreError, KeyError):
            messagebox.showerror(
                self.s.account_error_title, self.s.account_storage_error, parent=self
            )
            return
        self.profile.selected_account_id = None
        save_profile(self.profile)
        self._refresh_account_menu()
        messagebox.showinfo(
            self.s.account_error_title, self.s.account_deleted, parent=self
        )

    def _refresh_profile_menu(self, selected: str | None = None) -> None:
        if not hasattr(self, "profile_menu"):
            return
        names = list_profile_names()
        values = names or [self.s.profile_select]
        self.profile_menu.configure(values=values)
        chosen = selected if selected in names else values[0]
        self.profile_selected_var.set(chosen)
        self.profile_menu.set(chosen)

    def _selected_profile_name(self) -> str:
        selected = self.profile_selected_var.get().strip()
        if selected == self.s.profile_select:
            raise ValueError("No settings profile selected")
        return normalize_profile_name(selected)

    def _save_named_profile(self) -> None:
        if self._arming:
            return
        try:
            name = normalize_profile_name(self.profile_name_var.get())
        except ValueError:
            messagebox.showwarning(
                self.s.profiles_section, self.s.profile_name_invalid, parent=self
            )
            return
        existing = next(
            (
                saved
                for saved in list_profile_names()
                if saved.casefold() == name.casefold()
            ),
            None,
        )
        if existing is not None:
            name = existing
            if not messagebox.askyesno(
                self.s.profiles_section,
                self.s.profile_overwrite_q.format(name=name),
                parent=self,
            ):
                return
        save_named_profile(name, self.profile)
        self._refresh_profile_menu(name)
        messagebox.showinfo(
            self.s.profiles_section,
            self.s.profile_saved.format(name=name),
            parent=self,
        )

    def _load_named_profile(self) -> None:
        if self._arming:
            return
        if self.controller.state != RunState.STOPPED:
            messagebox.showinfo(
                self.s.profiles_section, self.s.stop_to_change_setup, parent=self
            )
            return
        try:
            name = self._selected_profile_name()
            profile = load_named_profile(name)
        except (ValueError, FileNotFoundError):
            messagebox.showwarning(
                self.s.profiles_section, self.s.profile_name_invalid, parent=self
            )
            return
        profile.wizard_completed = True
        save_profile(profile)
        self.apply_profile(profile)
        messagebox.showinfo(
            self.s.profiles_section,
            self.s.profile_loaded.format(name=name),
            parent=self,
        )

    def _delete_named_profile(self) -> None:
        if self._arming:
            return
        try:
            name = self._selected_profile_name()
        except ValueError:
            messagebox.showwarning(
                self.s.profiles_section, self.s.profile_select, parent=self
            )
            return
        if not messagebox.askyesno(
            self.s.profiles_section,
            self.s.profile_delete_q.format(name=name),
            parent=self,
        ):
            return
        try:
            delete_named_profile(name)
        except FileNotFoundError:
            self._refresh_profile_menu()
            return
        self._refresh_profile_menu()
        messagebox.showinfo(
            self.s.profiles_section,
            self.s.profile_deleted.format(name=name),
            parent=self,
        )

    def _change_language(self, display_name: str) -> None:
        code = normalize_language(self._language_display_to_code.get(display_name))
        if code == normalize_language(self.profile.language):
            return
        self.profile.language = code
        save_profile(self.profile)
        self.controller._profile.language = code
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Recreate localized widgets without starting another poll loop."""
        self._edit_open = False
        log_lines = list(self._log_lines)
        log_scroll = self.log_box.yview()[0] if hasattr(self, "log_box") else 1.0
        if hasattr(self, "body") and self.body.winfo_exists():
            self.body.destroy()
        self.s = ui_strings(self.profile.language)
        self.title(self.s.window_title)
        self._build()
        self._apply_brand_icon()
        self.minsize(880, 640)
        self.geometry(f"{self._ctrl_w}x{self._ctrl_h}")
        self._apply_always_on_top()
        self._refresh_lamps()
        self._refresh_buttons()
        self._rebind_hotkeys()
        self.log_box.configure(state="normal")
        if log_lines:
            self.log_box.insert("end", "\n".join(log_lines) + "\n")
        self.log_box.configure(state="disabled")
        self.log_box.yview_moveto(log_scroll)

    def _save_setup_fields(self) -> None:
        if self.controller.state == RunState.RUNNING:
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            return
        self.profile.character = self.char_var.get()
        self.profile.game_language = normalize_game_language(self.game_lang_var.get())
        self.profile.loot_mode = self.loot_var.get()
        self.profile.loot_adena_weight_ratio = float(self.adena_weight.get()) / 100.0
        self.profile.hp_potion_ratio = float(self.hp_pot.get()) / 100.0
        self.profile.hp_escape_ratio = float(self.hp_esc.get()) / 100.0
        self.profile.mp_escape_enabled = False
        try:
            self.profile.arrow_buy_qty = max(
                _ARROW_QTY_MIN,
                min(_ARROW_QTY_MAX, int(self.arrow_qty_var.get().strip())),
            )
            if str(self.arrow_qty_var.get()) != str(self.profile.arrow_buy_qty):
                self._arrow_qty_guard = True
                try:
                    self.arrow_qty_var.set(str(int(self.profile.arrow_buy_qty)))
                finally:
                    self._arrow_qty_guard = False
        except (TypeError, ValueError):
            self._arrow_qty_guard = True
            try:
                self.arrow_qty_var.set(str(int(self.profile.arrow_buy_qty)))
            finally:
                self._arrow_qty_guard = False
        try:
            self.profile.silver_arrow_buy_qty = max(
                _ARROW_QTY_MIN,
                min(_ARROW_QTY_MAX, int(self.silver_arrow_qty_var.get().strip())),
            )
            self.silver_arrow_qty_var.set(str(int(self.profile.silver_arrow_buy_qty)))
        except (TypeError, ValueError):
            self.silver_arrow_qty_var.set(
                str(int(getattr(self.profile, "silver_arrow_buy_qty", 200)))
            )
        arrow_type = str(getattr(self, "arrow_type_var", tk.StringVar(value="normal")).get())
        self.profile.buy_normal_arrows = arrow_type != "silver"
        self.profile.buy_silver_arrows = arrow_type == "silver"
        if hasattr(self, "restock_potions_var"):
            self.profile.restock_potions = bool(self.restock_potions_var.get())
        save_profile(self.profile)
        self._refresh_loot_weight_note()
        self._refresh_buttons()

    def _refresh_loot_weight_note(self) -> None:
        lab = getattr(self, "loot_weight_lab", None)
        if lab is None:
            return
        pct = int(round(float(self.profile.loot_adena_weight_ratio) * 100))
        lab.configure(text=self.s.loot_weight_note.format(pct=pct))

    def _reset_survival(self) -> None:
        self._setup_syncing = True
        try:
            self.hp_pot.set(55)
            self.hp_esc.set(30)
            if hasattr(self, "adena_weight"):
                self.adena_weight.set(30)
        finally:
            self._setup_syncing = False
        self._save_setup_fields()

    def _save_advanced(self) -> None:
        self.profile.always_on_top = bool(self.var_aot.get())
        save_profile(self.profile)
        self._apply_always_on_top()

    def _apply_always_on_top(self) -> None:
        top = bool(self.profile.always_on_top)
        self.attributes("-topmost", top)

    # ── lamps / buttons ───────────────────────────────────────────────────

    def _set_lamp(self, lamp: dict, probe_lamp: Lamp, detail: str) -> None:
        lamp["dot"].configure(text_color=_LAMP_COLOR[probe_lamp])
        lamp["detail"] = detail

    def _refresh_lamps(self) -> None:
        g = probe_game()
        self._set_lamp(
            self.lamp_game,
            g.lamp,
            localize_probe_detail(g.detail, self.profile.language),
        )

        # While the bot worker holds the memory pipe, a second probe looks
        # "disconnected". Treat armed sessions as memory OK for the lamp.
        armed = self.controller.state in (RunState.RUNNING, RunState.PAUSED)
        if armed:
            m_lamp, m_detail = Lamp.GREEN, self.s.memory_connected_session
        else:
            m = probe_memory()
            m_lamp, m_detail = m.lamp, localize_probe_detail(
                m.detail, self.profile.language
            )
        self._set_lamp(self.lamp_mem, m_lamp, m_detail)

        mp = probe_map(
            self.profile.selected_farms,
            map_id=self.profile.active_map,
            language=self.profile.language,
            map_style=getattr(self.profile, "map_style", None),
        )
        self._set_lamp(self.lamp_map, mp.lamp, mp.detail)

    def _refresh_buttons(self) -> None:
        st = self.controller.state
        gate = self.controller.start_gates_ok(self.profile)
        if st == RunState.STOPPED:
            # Keep Start clickable so we can auto-connect memory and send
            # the operator to Farms when no area is selected.
            self.btn_start.configure(
                state="disabled" if self._arming else "normal"
            )
            self.btn_resume.configure(state="disabled")
            self.btn_stop.configure(state="normal" if self._arming else "disabled")
            self.headline.configure(text=self.s.headline_stopped)
            if self._arming:
                return
            if gate and gate != "start_no_memory":
                self.reason_label.configure(text=self.s.start_fail[gate])
            elif self.controller.reason:
                self.reason_label.configure(text=self.controller.reason)
            else:
                self.reason_label.configure(text=self.s.ready_to_start)
        elif st == RunState.PAUSED:
            self.btn_start.configure(state="disabled")
            self.btn_resume.configure(state="normal")
            self.btn_stop.configure(state="normal")
            self.headline.configure(text=self.s.headline_paused)
            self.reason_label.configure(text=self.controller.reason or "")
        else:
            self.btn_start.configure(state="disabled")
            self.btn_resume.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.headline.configure(text=self.s.headline_running)
            self.reason_label.configure(text="")

    def _on_bot_state(self, state: RunState, reason: str) -> None:
        def _ui() -> None:
            try:
                if not self.winfo_exists():
                    return
            except Exception:
                return
            self._refresh_buttons()
            if state == RunState.STOPPED and not self._arming:
                self._close_memory_monitor()
                self._refresh_lamps()

        self.after(0, _ui)

    # ── actions ───────────────────────────────────────────────────────────

    def _require_account_or_warn(self) -> Account | None:
        """Require a selected account; otherwise warn and open Advanced."""
        account = self._selected_account()
        if account is not None:
            return account
        messagebox.showwarning(
            self.s.account_error_title,
            self.s.autologin_account_required,
            parent=self,
        )
        try:
            self.tabs.set(self.tab_names["advanced"])
        except Exception:
            pass
        self._refresh_buttons()
        return None

    def _on_start(self) -> None:
        self._save_setup_fields()
        if self.controller.state != RunState.STOPPED or self._arming:
            return
        self._recovery_budget.reset()
        if self._require_account_or_warn() is None:
            return

        mp = probe_map(
            self.profile.selected_farms,
            map_id=self.profile.active_map,
            language=self.profile.language,
            map_style=getattr(self.profile, "map_style", None),
        )
        if mp.lamp != Lamp.GREEN:
            key = (
                "start_no_patrol"
                if mp.dungeon
                else (
                    "map_missing"
                    if mp.lamp == Lamp.RED and not mp.farm_names
                    else "start_no_farms"
                )
            )
            messagebox.showerror(self.s.cannot_start, self.s.start_fail[key])
            self._click_map()
            self._refresh_lamps()
            self._refresh_buttons()
            return

        from manmabot_v1.driver_setup import interception_ready
        from manmabot_v1.ui.driver_setup import show_driver_setup

        input_ready, input_detail = interception_ready()
        if not input_ready:
            show_driver_setup(self, require_ready=False)
            input_ready, input_detail = interception_ready()
        if not input_ready:
            messagebox.showerror(self.s.cannot_start, input_detail, parent=self)
            self._refresh_lamps()
            return

        self._begin_arming(recovery=False)

    def _sync_recovery_budget(self) -> None:
        try:
            attempts = max(1, min(20, int(getattr(self.profile, "max_retries", 3))))
        except (TypeError, ValueError):
            attempts = 3
        self._recovery_budget.max_attempts = attempts

    def _begin_arming(self, *, recovery: bool) -> None:
        if self._arming or self._closing:
            return
        account = self._selected_account()
        if account is None:
            messagebox.showwarning(
                self.s.account_error_title,
                self.s.autologin_account_required,
                parent=self,
            )
            try:
                self.tabs.set(self.tab_names["advanced"])
            except Exception:
                pass
            return
        self._sync_recovery_budget()
        if recovery and not self._recovery_budget.claim():
            self.controller.reason = self.s.recovery_limit
            self.append_log(self.s.recovery_limit)
            self._refresh_buttons()
            return

        self._arming = True
        self._arming_token += 1
        token = self._arming_token
        self._arming_cancel = threading.Event()
        self.reason_label.configure(
            text=self.s.recovery_starting if recovery else self.s.autologin_starting
        )
        self.append_log(
            self.s.recovery_starting if recovery else self.s.autologin_starting
        )
        self._refresh_buttons()

        # Closing the pipe process also unblocks a worker that was stuck in an
        # RPC when the game vanished. A new monitor is created after login.
        if recovery:
            self._close_memory_monitor()

        def runner() -> None:
            outcome = {
                "ok": False,
                "cancelled": False,
                "detail": "",
            }
            try:
                deadline = time.monotonic() + 12.0
                while not self.controller.worker_stopped():
                    if self._arming_cancel.is_set():
                        outcome["cancelled"] = True
                        outcome["detail"] = self.s.autologin_cancelled
                        break
                    if time.monotonic() >= deadline:
                        outcome["detail"] = "The previous bot worker did not stop safely."
                        break
                    time.sleep(0.1)
                else:
                    def run_login(selected: object, cancel_event: threading.Event):
                        selected_account = selected
                        request = AutoLoginRequest(
                            user_id=selected_account.username,
                            password=selected_account.password,
                            server=selected_account.server,
                            character_number=selected_account.character_number,
                            language=selected_account.locale,
                            purple_launcher_path=selected_account.purple_launcher_path,
                            game_path=selected_account.game_path,
                            click_mode=selected_account.click_mode,
                        )
                        return AutoLoginService().run(
                            request,
                            cancel_event=cancel_event,
                            on_status=lambda status: self.after(
                                0,
                                lambda text=status: self._show_arming_status(
                                    token, text
                                ),
                            ),
                        )

                    def ensure_memory():
                        from manmabot_v1.monitor_launch import ensure_monitor_connected

                        return ensure_monitor_connected(
                            elevate=True,
                            start_driver=True,
                            timeout_s=20.0,
                            log=self.append_log,
                        )

                    prepared = prepare_session(
                        account=account,
                        cancel_event=self._arming_cancel,
                        game_ready=lambda: probe_game().lamp != Lamp.RED,
                        run_login=run_login,
                        ensure_memory=ensure_memory,
                    )
                    outcome["ok"] = prepared.ok
                    outcome["cancelled"] = prepared.cancelled
                    outcome["detail"] = {
                        "account_required": self.s.autologin_account_required,
                        "cancelled": self.s.autologin_cancelled,
                    }.get(prepared.detail, prepared.detail)
            except Exception as exc:
                outcome["detail"] = str(exc)

            try:
                self.after(
                    0,
                    lambda result=outcome: self._finish_arming(
                        token, result, recovery=recovery
                    ),
                )
            except Exception:
                pass

        self._arming_thread = threading.Thread(
            target=runner,
            name="manmabot-v1-arming",
            daemon=True,
        )
        self._arming_thread.start()

    def _show_arming_status(self, token: int, status: str) -> None:
        if token != self._arming_token or not self._arming or self._closing:
            return
        text = self.s.autologin_status.format(status=status)
        self.reason_label.configure(text=text)
        self.append_log(text)

    def _finish_arming(
        self, token: int, outcome: dict, *, recovery: bool
    ) -> None:
        if token != self._arming_token or self._closing:
            return
        self._arming = False
        self._arming_thread = None
        detail = str(outcome.get("detail") or "")
        if outcome.get("cancelled"):
            self.controller.reason = self.s.autologin_cancelled
            self.append_log(self.s.autologin_cancelled)
        elif not outcome.get("ok"):
            rendered = self.s.autologin_failed.format(detail=detail)
            self.controller.reason = rendered
            self.append_log(rendered)
            messagebox.showwarning(
                self.s.cannot_start, rendered, parent=self
            )
            self._close_memory_monitor()
        else:
            err = self.controller.start(self.profile)
            if err:
                rendered = self.s.start_fail.get(err, err)
                self.controller.reason = rendered
                messagebox.showwarning(
                    self.s.cannot_start, rendered, parent=self
                )
                self._close_memory_monitor()
            elif recovery:
                self.append_log(self.s.recovery_completed)
        self._refresh_lamps()
        self._refresh_buttons()

    def _on_resume(self) -> None:
        self.controller.resume()
        self._refresh_buttons()

    def _on_stop(self) -> None:
        if self._arming:
            self._arming_cancel.set()
            self.reason_label.configure(text=self.s.autologin_cancelled)
            self._refresh_buttons()
            return
        armed = self.controller.state in (RunState.RUNNING, RunState.PAUSED)
        self.controller.stop()
        if armed:
            self._close_memory_monitor()
        self._refresh_buttons()
        self._refresh_lamps()

    def _click_game(self) -> None:
        g = probe_game()
        if g.hwnd:
            bring_game_to_front(g.hwnd)
        self._refresh_lamps()
        self.append_log(f"{self.s.lamp_game}: {g.detail}")
        self._refresh_buttons()

    def _click_memory(self) -> None:
        m = probe_memory()
        self._refresh_lamps()
        self.append_log(f"{self.s.lamp_memory}: {m.detail}")
        self._refresh_buttons()

    def _wait_monitor_connect(self, *, start_driver: bool = True):
        """Attach the in-process player monitor and wait for a snapshot."""
        from manmabot_v1.monitor_launch import ensure_monitor_connected

        self.append_log(self.s.wizard_starting_monitor)
        self.update_idletasks()
        import threading

        box: list = []

        def runner():
            box.append(
                ensure_monitor_connected(
                    elevate=True,
                    start_driver=start_driver,
                    timeout_s=20.0,
                    log=lambda msg: self.after(0, lambda m=msg: self.append_log(m)),
                )
            )

        th = threading.Thread(target=runner, daemon=True)
        th.start()
        while th.is_alive():
            self.update()
            th.join(0.05)
        return box[0] if box else None

    def _close_memory_monitor(self) -> None:
        """Release the in-process reader and close a leftover monitor console."""
        from manmabot_v1.monitor_launch import (
            is_monitor_process_running,
            stop_monitor_process,
        )
        from manmabot_v1.player_monitor import shutdown_shared_monitor

        shutdown_shared_monitor()
        if not is_monitor_process_running():
            return
        self.append_log(self.s.monitor_closing)
        ok, detail = stop_monitor_process(
            log=lambda msg: self.append_log(msg),
        )
        if ok:
            self.append_log(self.s.monitor_closed)
        else:
            self.append_log(self.s.monitor_close_failed.format(detail=detail))

    def _ensure_memory(self) -> None:
        """Attach the in-process player monitor and wait for a snapshot."""
        result = self._wait_monitor_connect()
        if result is None:
            messagebox.showerror(
                self.s.memory_title, self.s.memory_failed_detail
            )
            return
        self._refresh_lamps()
        self._refresh_buttons()
        if result.ok:
            self.append_log(
                self.s.memory_connected.format(detail=result.detail)
            )
            messagebox.showinfo(
                self.s.memory_title,
                self.s.memory_connected.format(detail=result.detail),
            )
        else:
            self.append_log(self.s.memory_failed.format(detail=result.detail))
            messagebox.showwarning(
                self.s.memory_title,
                self.s.memory_failed.format(detail=result.detail),
            )

    def _start_driver(self) -> None:
        from manmabot_v1.monitor_launch import try_start_driver

        ok, msg = try_start_driver(log=self.append_log)
        if ok:
            messagebox.showinfo(
                self.s.driver_title,
                self.s.driver_ok.format(msg=msg),
            )
        else:
            messagebox.showwarning(
                self.s.driver_title, self.s.driver_fail_prefix.format(msg=msg)
            )

    def _click_map(self) -> None:
        self.tabs.set(self.tab_names["farms"])
        self._reload_farm_checks()

    def _open_wizard(self) -> None:
        if self.controller.state != RunState.STOPPED:
            if not messagebox.askyesno(self.s.setup, self.s.stop_open_setup_q):
                return
            self.controller.stop()
        from manmabot_v1.ui.wizard import SetupWizard

        SetupWizard(self)

    def _open_logs(self) -> None:
        import os

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    def _copy_diag(self) -> None:
        g, m, mp = probe_game(), probe_memory(), probe_map(
            self.profile.selected_farms,
            map_id=self.profile.active_map,
            language=self.profile.language,
            map_style=getattr(self.profile, "map_style", None),
        )
        text = (
            f"Manmabot v1\n"
            f"manmabot={manmabot_root()}\n"
            f"game={g.detail}\n"
            f"memory={m.detail}\n"
            f"map={mp.detail}\n"
            f"active_map={self.profile.active_map}\n"
            f"character={self.profile.character}\n"
            f"language={self.profile.language}\n"
            f"game_language={self.profile.game_language}\n"
            f"loot={self.profile.loot_mode}\n"
            f"farms={self.profile.selected_farms}\n"
            f"wizard_completed={self.profile.wizard_completed}\n"
        )
        self.clipboard_clear()
        self.clipboard_append(text)
        self.append_log(self.s.diagnostics_copied)

    def _reset_all(self) -> None:
        if not messagebox.askyesno(
            self.s.reset_title, self.s.reset_confirm
        ):
            return
        if self.controller.state != RunState.STOPPED:
            self.controller.stop()
        self.profile = reset_profile()
        self.apply_profile(self.profile)
        self.append_log(self.s.settings_reset_log)
        from manmabot_v1.ui.wizard import SetupWizard

        SetupWizard(self)

    def _rebind_hotkeys(self) -> Optional[str]:
        return self.hotkeys.bind(
            self.profile.hotkeys,
            on_pause_resume=lambda: self.after(0, self.controller.toggle_pause_hotkey),
            on_stop=lambda: self.after(0, self._on_stop),
        )

    def append_log(self, msg: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-500:]

        def _ui():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
            try:
                log_file = LOG_DIR / "v1.log"
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

        try:
            self.after(0, _ui)
        except Exception:
            pass

    def _poll(self) -> None:
        self._refresh_lamps()
        if self.controller.state in (RunState.RUNNING, RunState.PAUSED):
            event = self.controller.auto_pause_tick()
            if event == "game_closed":
                if bool(getattr(self.profile, "resume_after_relogin", True)):
                    self._begin_arming(recovery=True)
                else:
                    self.controller.reason = "Game closed; resume after relogin is off."
                    self.append_log(self.controller.reason)
        self._refresh_buttons()
        self.after(250, self._poll)

    def apply_profile(self, profile: Profile) -> None:
        """Called by wizard on finish."""
        language_changed = normalize_language(profile.language) != normalize_language(
            self.profile.language
        )
        self.profile = profile
        self.s = ui_strings(profile.language)
        if language_changed:
            self._rebuild_ui()
            self.append_log(self.s.wizard_done_log)
            return
        self.char_var.set(profile.character)
        if hasattr(self, "game_lang_var"):
            self.game_lang_var.set(normalize_game_language(profile.game_language))
        self._refresh_character_preview()
        self.loot_var.set(profile.loot_mode)
        if hasattr(self, "adena_weight"):
            self.adena_weight.set(profile.loot_adena_weight_ratio * 100)
        self._refresh_loot_weight_note()
        self.hp_pot.set(profile.hp_potion_ratio * 100)
        self.hp_esc.set(profile.hp_escape_ratio * 100)
        if hasattr(self, "arrow_qty_var"):
            self.arrow_qty_var.set(str(int(profile.arrow_buy_qty)))
        if hasattr(self, "silver_arrow_qty_var"):
            self.silver_arrow_qty_var.set(
                str(int(getattr(profile, "silver_arrow_buy_qty", 200)))
            )
        if hasattr(self, "arrow_type_var"):
            self.arrow_type_var.set(
                "silver" if getattr(profile, "buy_silver_arrows", False) else "normal"
            )
        if hasattr(self, "restock_potions_var"):
            self.restock_potions_var.set(bool(getattr(profile, "restock_potions", True)))
        self.var_aot.set(profile.always_on_top)
        self._refresh_account_menu(profile.selected_account_id)
        self.rotate_var.set(profile.farm_rotate_s / 60.0)
        if hasattr(self, "farms_rotate_slider"):
            try:
                self.farms_rotate_slider.set(profile.farm_rotate_s / 60.0)
            except Exception:
                pass
        for k, lab in self.hotkey_labels.items():
            lab.configure(text=profile.hotkeys.get(k, ""))
        self._sync_map_combo()
        self._reload_farm_checks()
        if getattr(self, "_edit_open", False):
            if is_dungeon_map_id(profile.active_map):
                self.map_editor.load_map(profile.active_map)
            else:
                self._close_map_editor()
        self._reload_species()
        self._sync_spells_ui()
        self._apply_always_on_top()
        self._rebind_hotkeys()
        self._refresh_lamps()
        self._refresh_buttons()
        self.append_log(self.s.wizard_done_log)

    def _on_close(self) -> None:
        self._closing = True
        self._arming_cancel.set()
        self.controller.stop()
        self._close_memory_monitor()
        thread = self._arming_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=6.0)
        self.hotkeys.clear()
        self.destroy()
