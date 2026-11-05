"""NPC behavior editor — buy, sell, warehouse, teleporter. Form + capture UV calibrate."""
from __future__ import annotations

import re
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk
from typing import Callable, Optional

from shop.behaviors import (
    ACTION_BUY,
    ACTION_SELL,
    ACTION_STORE,
    ACTION_TELEPORTER,
    ACTIONS,
    ITEM_ROW_COUNT,
    SELL_MODE_ONLY_GARBAGE,
    SELL_MODES,
    TELEPORT_KIND_DUNGEON_GATE,
    TELEPORT_KIND_FIELD_LAND,
    TELEPORT_KINDS,
    ShoppingBehavior,
    ShoppingSellFilters,
    ShoppingUiClicks,
    behaviors_path,
    default_behavior,
    load_behaviors,
    save_behaviors,
)
from ui.design_system import TEXT_MUTED

_ID_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

# Marker keys drawn on the capture canvas.
_SHOP_MARKER_KEYS: tuple[str, ...] = (
    "buy_button",
    "sell_button",
    "confirm_button",
    "list_scroll_point",
    *(f"row_{i}" for i in range(ITEM_ROW_COUNT)),
)
_TELEPORTER_MARKER_KEYS: tuple[str, ...] = (
    "buy_button",
    "confirm_button",
)
_MARKER_KEYS: tuple[str, ...] = _SHOP_MARKER_KEYS

_MARKER_LABELS = {
    "buy_button": "Buy / option",
    "sell_button": "Sell button",
    "confirm_button": "Confirm",
    "list_scroll_point": "List scroll",
    **{f"row_{i}": f"Item row {i}" for i in range(ITEM_ROW_COUNT)},
}


def _uv_get(ui: ShoppingUiClicks, key: str) -> Optional[tuple[float, float]]:
    if key == "buy_button":
        return ui.buy_button
    if key == "sell_button":
        return ui.sell_button
    if key == "confirm_button":
        return ui.confirm_button
    if key == "list_scroll_point":
        return ui.list_scroll_point
    if key.startswith("row_"):
        idx = int(key.split("_", 1)[1])
        rows = ui.item_rows
        if 0 <= idx < len(rows):
            return rows[idx]
    return None


def _uv_set(ui: ShoppingUiClicks, key: str, pt: Optional[tuple[float, float]]) -> ShoppingUiClicks:
    rows = list(ui.item_rows)
    while len(rows) < ITEM_ROW_COUNT:
        rows.append(None)
    rows = rows[:ITEM_ROW_COUNT]
    buy, sell, conf, scroll = (
        ui.buy_button,
        ui.sell_button,
        ui.confirm_button,
        ui.list_scroll_point,
    )
    if key == "buy_button":
        buy = pt
    elif key == "sell_button":
        sell = pt
    elif key == "confirm_button":
        conf = pt
    elif key == "list_scroll_point":
        scroll = pt
    elif key.startswith("row_"):
        idx = int(key.split("_", 1)[1])
        if 0 <= idx < ITEM_ROW_COUNT:
            rows[idx] = pt
    return ShoppingUiClicks(
        buy_button=buy,
        sell_button=sell,
        confirm_button=conf,
        list_scroll_point=scroll,
        item_rows=tuple(rows),
    )


def _default_ui_layout(*, action: str = ACTION_BUY) -> ShoppingUiClicks:
    """Placeholder UVs so markers appear before first calibrate."""
    if action == ACTION_TELEPORTER:
        return ShoppingUiClicks(
            buy_button=(0.18, 0.40),
            confirm_button=(0.28, 0.72),
        )
    rows = []
    for i in range(ITEM_ROW_COUNT):
        rows.append((0.45, 0.28 + i * 0.06))
    return ShoppingUiClicks(
        buy_button=(0.18, 0.55),
        sell_button=(0.18, 0.62),
        list_scroll_point=(0.55, 0.45),
        confirm_button=(0.28, 0.72),
        item_rows=tuple(rows),
    )


class ShoppingBehaviorEditor(ttk.Frame):
    """Edit engine NPC behaviors (form + capture calibrate)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_log: Optional[Callable[[str], None]] = None,
        on_saved: Optional[Callable[[], None]] = None,
        get_sell_filters: Optional[Callable[[], ShoppingSellFilters]] = None,
    ) -> None:
        super().__init__(master, padding=4)
        self._on_log = on_log or (lambda _m: None)
        self._on_saved = on_saved or (lambda: None)
        self._get_sell_filters = get_sell_filters
        self._behaviors: list[ShoppingBehavior] = []
        self._selected_index: int | None = None
        self._suppress = False
        self._marker_key = "buy_button"

        self._frame = None  # BGR
        self._photo = None
        self._scale = 1.0
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._offset = (0.0, 0.0)
        self._img_size = (1, 1)
        self._drag = False
        self._drag_start = (0, 0)
        self._pan_drag = False
        self._pan0 = (0.0, 0.0)

        self.path_var = tk.StringVar(self, value="")
        self.id_var = tk.StringVar(self)
        self.name_var = tk.StringVar(self)
        self.action_var = tk.StringVar(self, value=ACTION_BUY)
        self.map_var = tk.StringVar(self)
        self.scroll_var = tk.StringVar(self)
        self.world_x_var = tk.StringVar(self, value="0")
        self.world_y_var = tk.StringVar(self, value="0")
        self.qty_var = tk.StringVar(self, value="200")
        self.item_index_var = tk.StringVar(self, value="0")
        self.adena_cost_var = tk.StringVar(self, value="0")
        self.teleport_kind_var = tk.StringVar(self, value=TELEPORT_KIND_DUNGEON_GATE)
        self.dest_dungeon_var = tk.StringVar(self, value="")
        self.land_map_var = tk.StringVar(self, value="")
        self.land_x_var = tk.StringVar(self, value="0")
        self.land_y_var = tk.StringVar(self, value="0")
        self.world_nav_var = tk.BooleanVar(self, value=False)
        self.sell_mode_var = tk.StringVar(self, value=SELL_MODE_ONLY_GARBAGE)
        self.status_var = tk.StringVar(self, value="")
        self.zoom_label_var = tk.StringVar(self, value="100%")
        self.marker_var = tk.StringVar(self, value=_MARKER_LABELS["buy_button"])
        self._dirty = False
        self._action_combo: ttk.Combobox | None = None
        self._map_combo: ttk.Combobox | None = None
        self._scroll_combo: ttk.Combobox | None = None
        self._sell_mode_combo: ttk.Combobox | None = None
        self._sell_frame: ttk.LabelFrame | None = None
        self._calib_frame: ttk.LabelFrame | None = None
        self._item_index_entry: ttk.Entry | None = None
        self._qty_entry: ttk.Entry | None = None
        self._adena_entry: ttk.Entry | None = None
        self._kind_combo: ttk.Combobox | None = None
        self._dest_combo: ttk.Combobox | None = None
        self._land_map_combo: ttk.Combobox | None = None
        self._land_x_entry: ttk.Entry | None = None
        self._land_y_entry: ttk.Entry | None = None
        self._land_fill_btn: ttk.Button | None = None
        self._dest_row: ttk.Frame | None = None
        self._land_row: ttk.Frame | None = None
        self._world_nav_check: ttk.Checkbutton | None = None
        self._dest_id_to_label: dict[int, str] = {}
        self._dest_label_to_id: dict[str, int] = {}
        self._land_id_to_label: dict[int, str] = {}
        self._land_label_to_id: dict[str, int] = {}
        self._scroll_label_to_id: dict[str, str] = {}
        self._scroll_id_to_label: dict[str, str] = {}
        self._active_marker_keys: tuple[str, ...] = _SHOP_MARKER_KEYS

        self._build()
        self.reload_from_disk()

    def _log(self, message: str) -> None:
        self._on_log(message)
        self.status_var.set(message)

    def _build(self) -> None:
        from app._04_decision.shops import (
            list_destination_dungeon_choices,
            list_land_map_choices,
            list_map_ids,
            list_scroll_spot_choices,
        )

        top = ttk.Frame(self, style="Chrome.TFrame")
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top,
            text="NPC behaviors (buy, sell, warehouse, teleporter) — dialog UVs",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left")
        self.path_var.set(str(behaviors_path()))
        ttk.Label(
            top, textvariable=self.path_var, style="Chrome.TLabel", foreground=TEXT_MUTED
        ).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=2)
        right = ttk.Frame(body, padding=2)
        body.add(left, weight=2)
        body.add(right, weight=5)

        list_box = ttk.LabelFrame(left, text="Behaviors", padding=(6, 4))
        list_box.pack(fill="both", expand=True)
        cols = ("id", "action", "map", "scroll")
        self.tree = ttk.Treeview(
            list_box, columns=cols, show="headings", selectmode="browse", height=16
        )
        for c, t, w in (
            ("id", "Id", 120),
            ("action", "Action", 50),
            ("map", "Map", 90),
            ("scroll", "Scroll", 110),
        ):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_tree_select())

        btns = ttk.Frame(left, style="Chrome.TFrame")
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add", command=self.add_behavior).pack(side="left", padx=2)
        ttk.Button(btns, text="Duplicate", command=self.duplicate_behavior).pack(
            side="left", padx=2
        )
        ttk.Button(btns, text="Delete", command=self.delete_behavior).pack(
            side="left", padx=2
        )
        ttk.Button(btns, text="Reload", command=self.reload_from_disk).pack(
            side="right", padx=2
        )
        ttk.Button(btns, text="Save", command=self.save_to_disk).pack(
            side="right", padx=2
        )

        form = ttk.LabelFrame(right, text="Identity / travel / qty", padding=(8, 4))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        def cell(r, c, label, widget, colspan=1):
            ttk.Label(form, text=label, style="Chrome.TLabel").grid(
                row=r, column=c, sticky="w", padx=(0, 4), pady=2
            )
            widget.grid(
                row=r, column=c + 1, columnspan=colspan, sticky="ew", padx=(0, 8), pady=2
            )

        cell(0, 0, "Id", ttk.Entry(form, textvariable=self.id_var, width=18))
        cell(0, 2, "Name", ttk.Entry(form, textvariable=self.name_var, width=22))
        self._action_combo = ttk.Combobox(
            form,
            textvariable=self.action_var,
            values=ACTIONS,
            state="readonly",
            width=10,
        )
        cell(1, 0, "Action", self._action_combo)
        self._map_combo = ttk.Combobox(
            form, textvariable=self.map_var, values=list_map_ids(), width=18
        )
        cell(1, 2, "Map", self._map_combo)
        choices = list_scroll_spot_choices()
        self._scroll_label_to_id = {label: sid for sid, label in choices}
        self._scroll_id_to_label = {sid: label for sid, label in choices}
        self._scroll_combo = ttk.Combobox(
            form,
            textvariable=self.scroll_var,
            values=[label for _sid, label in choices],
            width=42,
        )
        cell(2, 0, "Scroll spot", self._scroll_combo, colspan=3)
        world = ttk.Frame(form, style="Chrome.TFrame")
        ttk.Entry(world, textvariable=self.world_x_var, width=8).pack(side="left", padx=2)
        ttk.Entry(world, textvariable=self.world_y_var, width=8).pack(side="left", padx=2)
        ttk.Button(
            world, text="Fill NPC from memory", command=self.fill_world_from_memory
        ).pack(side="left", padx=6)
        cell(3, 0, "NPC world", world)
        self._adena_entry = ttk.Entry(form, textvariable=self.adena_cost_var, width=8)
        cell(3, 2, "Adena cost", self._adena_entry)
        self._item_index_entry = ttk.Entry(
            form, textvariable=self.item_index_var, width=8
        )
        cell(4, 0, "Item index", self._item_index_entry)
        self._qty_entry = ttk.Entry(form, textvariable=self.qty_var, width=8)
        cell(4, 2, "Default qty", self._qty_entry)
        self._kind_combo = ttk.Combobox(
            form,
            textvariable=self.teleport_kind_var,
            values=list(TELEPORT_KINDS),
            state="readonly",
            width=18,
        )
        self._kind_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_action_panel())
        cell(5, 0, "Teleport kind", self._kind_combo)
        dest_choices = list_destination_dungeon_choices()
        self._dest_id_to_label = {mid: label for mid, label in dest_choices}
        self._dest_label_to_id = {label: mid for mid, label in dest_choices}
        self._dest_row = ttk.Frame(form, style="Chrome.TFrame")
        self._dest_combo = ttk.Combobox(
            self._dest_row,
            textvariable=self.dest_dungeon_var,
            values=[label for _mid, label in dest_choices],
            width=42,
        )
        self._dest_combo.pack(side="left", fill="x", expand=True)
        cell(6, 0, "Dest dungeon", self._dest_row, colspan=3)
        land_choices = list_land_map_choices()
        self._land_id_to_label = {mid: label for mid, label in land_choices}
        self._land_label_to_id = {label: mid for mid, label in land_choices}
        self._land_row = ttk.Frame(form, style="Chrome.TFrame")
        self._land_map_combo = ttk.Combobox(
            self._land_row,
            textvariable=self.land_map_var,
            values=[label for _mid, label in land_choices],
            width=28,
        )
        self._land_map_combo.pack(side="left", padx=(0, 4))
        self._land_x_entry = ttk.Entry(
            self._land_row, textvariable=self.land_x_var, width=8
        )
        self._land_x_entry.pack(side="left", padx=2)
        self._land_y_entry = ttk.Entry(
            self._land_row, textvariable=self.land_y_var, width=8
        )
        self._land_y_entry.pack(side="left", padx=2)
        self._land_fill_btn = ttk.Button(
            self._land_row,
            text="Fill land from memory",
            command=self.fill_land_from_memory,
        )
        self._land_fill_btn.pack(side="left", padx=6)
        cell(7, 0, "Land map / xy", self._land_row, colspan=3)
        self._world_nav_check = ttk.Checkbutton(
            form,
            text="Use in world-nav (NPC teleporter shortcut)",
            variable=self.world_nav_var,
        )
        self._world_nav_check.grid(row=8, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(
            form,
            text="Edits stay in memory until Save (Engine/data/npc_behaviors.yaml). "
            "Scroll spot = talking-scroll hubs. Adena = fare. "
            "dungeon_gate → Dest dungeon (LC mapId). "
            "field_land → Land map/xy after Run Practice. "
            "World-nav checkbox writes world_nav (Korean id; zh uses _ch).",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(6, 2))
        ttk.Button(
            form, text="Save fields to engine data", command=self.save_to_disk
        ).grid(row=10, column=0, columnspan=4, sticky="w", pady=(2, 2))

        sell = ttk.LabelFrame(right, text="Sell mode (this behavior)", padding=(8, 4))
        self._sell_frame = sell
        mode_row = ttk.Frame(sell, style="Chrome.TFrame")
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Sell mode", style="Chrome.TLabel").pack(
            side="left", padx=(0, 6)
        )
        self._sell_mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.sell_mode_var,
            values=SELL_MODES,
            state="readonly",
            width=22,
        )
        self._sell_mode_combo.pack(side="left")
        ttk.Label(
            mode_row,
            text="Lists live on the Sell tab · "
            "sell_only_garbage / sell_except_keep",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=10)

        self._action_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_action_panel())
        self.action_var.trace_add("write", lambda *_a: self._sync_action_panel())

        calib = ttk.LabelFrame(right, text="Calibrate dialog UVs", padding=(6, 4))
        self._calib_frame = calib
        self._sync_action_panel()
        calib.pack(fill="both", expand=True, pady=(6, 0))
        bar = ttk.Frame(calib, style="Chrome.TFrame")
        bar.pack(fill="x")
        ttk.Button(bar, text="Recapture", command=self.recapture).pack(side="left", padx=2)
        ttk.Button(bar, text="Seed default markers", command=self.seed_markers).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Zoom -", command=lambda: self._zoom_by(1 / 1.25)).pack(
            side="left", padx=2
        )
        ttk.Label(bar, textvariable=self.zoom_label_var, width=5, style="Chrome.TLabel").pack(
            side="left"
        )
        ttk.Button(bar, text="Zoom +", command=lambda: self._zoom_by(1.25)).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Reset zoom", command=self._zoom_reset).pack(side="left", padx=2)
        ttk.Label(
            bar,
            text="Select marker · drag · arrows nudge · wheel zoom · middle pan",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="right", padx=4)

        mid = ttk.Panedwindow(calib, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=4)
        marker_box = ttk.Frame(mid, padding=2)
        canvas_box = ttk.Frame(mid, padding=2)
        mid.add(marker_box, weight=1)
        mid.add(canvas_box, weight=4)

        ttk.Label(marker_box, text="Markers", style="Chrome.TLabel").pack(anchor="w")
        self.marker_list = tk.Listbox(marker_box, height=14, exportselection=False)
        self.marker_list.pack(fill="both", expand=True)
        self._rebuild_marker_list()
        self.marker_list.bind("<<ListboxSelect>>", self._on_marker_select)

        self.canvas = tk.Canvas(canvas_box, background="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Left>", lambda e: self._nudge(-1, 0, e))
        self.canvas.bind("<Right>", lambda e: self._nudge(1, 0, e))
        self.canvas.bind("<Up>", lambda e: self._nudge(0, -1, e))
        self.canvas.bind("<Down>", lambda e: self._nudge(0, 1, e))
        self.canvas.focus_set()

        foot = ttk.Frame(self, style="Chrome.TFrame")
        foot.pack(fill="x", pady=(4, 0))
        ttk.Label(foot, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )
        ttk.Label(foot, textvariable=self.marker_var, style="Chrome.TLabel").pack(
            side="right"
        )

    # ------------------------------------------------------------------ data

    def reload_from_disk(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                "Behaviors",
                "You have unsaved form edits. Reload and discard them?",
                parent=self.winfo_toplevel(),
            ):
                return
        try:
            self._behaviors = list(load_behaviors())
        except Exception as exc:
            messagebox.showerror("Behaviors", str(exc), parent=self.winfo_toplevel())
            self._log(f"reload failed: {exc}")
            return
        self._dirty = False
        self.path_var.set(str(behaviors_path()))
        self._refresh_tree(select_index=0 if self._behaviors else None)
        self._log(f"Loaded {len(self._behaviors)} behavior(s) from {behaviors_path()}")

    def save_to_disk(self) -> None:
        try:
            # Force Combobox typed text into the StringVars before parse.
            self.update_idletasks()
            if self._selected_index is not None:
                if not self.apply_form_to_selected(silent=False, refresh=False):
                    return
                self._update_tree_row(self._selected_index)
            sell_filters = (
                self._get_sell_filters() if self._get_sell_filters is not None else None
            )
            path = save_behaviors(
                list(self._behaviors),
                sell_filters=sell_filters,
            )
            self._dirty = False
            self._refresh_tree(select_index=self._selected_index)
            self._log(
                f"Saved {len(self._behaviors)} behavior(s) → {path}"
            )
            self._on_saved()
        except Exception as exc:
            import traceback

            detail = traceback.format_exc()
            try:
                from common import OUTPUT_DIR

                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                (OUTPUT_DIR / "shopping_behavior_save_error.txt").write_text(
                    detail, encoding="utf-8"
                )
            except Exception:
                pass
            messagebox.showerror(
                "Behaviors",
                f"Save failed:\n{exc}",
                parent=self.winfo_toplevel(),
            )
            self._log(f"save failed: {exc}")

    def _refresh_tree(self, select_index: int | None = None) -> None:
        self.tree.unbind("<<TreeviewSelect>>")
        self._suppress = True
        try:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            for i, b in enumerate(self._behaviors):
                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(b.id, b.action, b.map_id, b.scroll_spot),
                )
            if select_index is not None and 0 <= select_index < len(self._behaviors):
                iid = str(select_index)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self._selected_index = select_index
                self._load_form(self._behaviors[select_index])
                self._redraw()
            elif not self._behaviors:
                self._selected_index = None
                self._clear_form()
        finally:
            self._suppress = False
            self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_tree_select())

    def _on_tree_select(self) -> None:
        if self._suppress:
            return
        sel = self.tree.selection()
        if not sel:
            return
        try:
            index = int(sel[0])
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(self._behaviors):
            return
        # Persist edits on the previous row without rebuilding the tree
        # (full refresh re-fires <<TreeviewSelect>> and can stack-overflow).
        if self._selected_index is not None and self._selected_index != index:
            prev = self._selected_index
            if not self.apply_form_to_selected(silent=True, refresh=False):
                self._suppress = True
                try:
                    self.tree.selection_set(str(prev))
                    self.tree.focus(str(prev))
                finally:
                    self._suppress = False
                return
            self._update_tree_row(prev)
        self._selected_index = index
        self._load_form(self._behaviors[index])
        self._redraw()

    def _update_tree_row(self, index: int) -> None:
        if index < 0 or index >= len(self._behaviors):
            return
        b = self._behaviors[index]
        try:
            self.tree.item(
                str(index),
                values=(b.id, b.action, b.map_id, b.scroll_spot),
            )
        except tk.TclError:
            pass

    def _rebuild_marker_list(self) -> None:
        action = self._combo_text(self._action_combo, self.action_var).lower()
        keys = (
            _TELEPORTER_MARKER_KEYS
            if action == ACTION_TELEPORTER
            else _SHOP_MARKER_KEYS
        )
        self._active_marker_keys = keys
        if not hasattr(self, "marker_list"):
            return
        prev = self._marker_key
        self.marker_list.delete(0, "end")
        for key in keys:
            label = _MARKER_LABELS[key]
            if action == ACTION_TELEPORTER and key == "buy_button":
                label = "Teleport option"
            self.marker_list.insert("end", label)
        if prev in keys:
            idx = keys.index(prev)
        else:
            idx = 0
            self._marker_key = keys[0] if keys else "buy_button"
        if keys:
            self.marker_list.selection_clear(0, "end")
            self.marker_list.selection_set(idx)
            self.marker_list.activate(idx)
            label = _MARKER_LABELS[self._marker_key]
            if action == ACTION_TELEPORTER and self._marker_key == "buy_button":
                label = "Teleport option"
            self.marker_var.set(label)

    def _sync_action_panel(self) -> None:
        """Show sell mode for sell/store; adena/dest for teleporter; refresh markers."""
        action = self._combo_text(self._action_combo, self.action_var).lower()
        kind = self._combo_text(self._kind_combo, self.teleport_kind_var).lower()
        if kind not in TELEPORT_KINDS:
            kind = TELEPORT_KIND_DUNGEON_GATE
        slot_state = (
            "disabled"
            if action in (ACTION_SELL, ACTION_STORE, ACTION_TELEPORTER)
            else "normal"
        )
        qty_state = "disabled" if action == ACTION_TELEPORTER else "normal"
        adena_state = "normal" if action == ACTION_TELEPORTER else "disabled"
        kind_state = "readonly" if action == ACTION_TELEPORTER else "disabled"
        world_nav_state = "normal" if action == ACTION_TELEPORTER else "disabled"
        is_dungeon = action == ACTION_TELEPORTER and kind == TELEPORT_KIND_DUNGEON_GATE
        is_field = action == ACTION_TELEPORTER and kind == TELEPORT_KIND_FIELD_LAND
        dest_state = "normal" if is_dungeon else "disabled"
        land_state = "normal" if is_field else "disabled"
        entry = self._item_index_entry
        if entry is not None:
            try:
                entry.configure(state=slot_state)
            except tk.TclError:
                pass
        qty = self._qty_entry
        if qty is not None:
            try:
                qty.configure(state=qty_state)
            except tk.TclError:
                pass
        adena = self._adena_entry
        if adena is not None:
            try:
                adena.configure(state=adena_state)
            except tk.TclError:
                pass
        kind_combo = getattr(self, "_kind_combo", None)
        if kind_combo is not None:
            try:
                kind_combo.configure(state=kind_state)
            except tk.TclError:
                pass
        dest = getattr(self, "_dest_combo", None)
        if dest is not None:
            try:
                dest.configure(state=dest_state)
            except tk.TclError:
                pass
        for w in (
            getattr(self, "_land_map_combo", None),
            getattr(self, "_land_x_entry", None),
            getattr(self, "_land_y_entry", None),
            getattr(self, "_land_fill_btn", None),
        ):
            if w is not None:
                try:
                    w.configure(state=land_state)
                except tk.TclError:
                    pass
        wn = getattr(self, "_world_nav_check", None)
        if wn is not None:
            try:
                wn.configure(state=world_nav_state)
            except tk.TclError:
                pass
        if action in (ACTION_SELL, ACTION_STORE):
            self.item_index_var.set("0")
            self.adena_cost_var.set("0")
            self.dest_dungeon_var.set("")
            self.land_map_var.set("")
            self.land_x_var.set("0")
            self.land_y_var.set("0")
            self.teleport_kind_var.set(TELEPORT_KIND_DUNGEON_GATE)
            self.world_nav_var.set(False)
        elif action == ACTION_TELEPORTER:
            self.item_index_var.set("0")
            self.qty_var.set("1")
            if is_dungeon:
                self.land_map_var.set("")
                self.land_x_var.set("0")
                self.land_y_var.set("0")
            else:
                self.dest_dungeon_var.set("")
        else:
            self.adena_cost_var.set("0")
            self.dest_dungeon_var.set("")
            self.land_map_var.set("")
            self.land_x_var.set("0")
            self.land_y_var.set("0")
            self.teleport_kind_var.set(TELEPORT_KIND_DUNGEON_GATE)
            self.world_nav_var.set(False)
        frame = self._sell_frame
        if frame is not None:
            if action in (ACTION_SELL, ACTION_STORE):
                kwargs = {"fill": "x", "pady": (6, 0)}
                calib = self._calib_frame
                if calib is not None:
                    try:
                        frame.pack(before=calib, **kwargs)
                    except tk.TclError:
                        frame.pack(**kwargs)
                else:
                    frame.pack(**kwargs)
            else:
                frame.pack_forget()
        self._rebuild_marker_list()
        try:
            self._redraw()
        except Exception:
            pass

    def _scroll_label_for_id(self, spot_id: str) -> str:
        sid = str(spot_id or "").strip()
        return self._scroll_id_to_label.get(sid, sid)

    def _scroll_id_from_form(self) -> str:
        raw = self._combo_text(self._scroll_combo, self.scroll_var)
        if not raw:
            return ""
        if raw in self._scroll_label_to_id:
            return self._scroll_label_to_id[raw]
        # Accept bare id (legacy / typed).
        if raw in self._scroll_id_to_label:
            return raw
        # Label prefix "id · …"
        head = raw.split(" · ", 1)[0].strip()
        if head in self._scroll_id_to_label:
            return head
        return raw

    def _dest_label_for_id(self, map_id: int) -> str:
        mid = int(map_id or 0)
        if mid <= 0:
            return ""
        return self._dest_id_to_label.get(mid, str(mid))

    def _dest_id_from_form(self) -> int:
        raw = self._combo_text(self._dest_combo, self.dest_dungeon_var)
        if not raw:
            return 0
        if raw in self._dest_label_to_id:
            return int(self._dest_label_to_id[raw])
        head = raw.split(" · ", 1)[0].strip()
        try:
            return max(0, int(float(head)))
        except ValueError:
            return 0

    def _land_label_for_id(self, map_id: int) -> str:
        mid = int(map_id or 0)
        if mid < 0:
            return ""
        if mid == 0 and mid not in self._land_id_to_label:
            return ""
        return self._land_id_to_label.get(mid, str(mid) if mid > 0 else "")

    def _land_id_from_form(self) -> int:
        raw = self._combo_text(self._land_map_combo, self.land_map_var)
        if not raw:
            return 0
        if raw in self._land_label_to_id:
            return int(self._land_label_to_id[raw])
        head = raw.split(" · ", 1)[0].strip()
        try:
            return max(0, int(float(head)))
        except ValueError:
            return 0

    def _clear_form(self) -> None:
        self.id_var.set("")
        self.name_var.set("")
        self.action_var.set(ACTION_BUY)
        self.map_var.set("")
        self.scroll_var.set("")
        self.world_x_var.set("0")
        self.world_y_var.set("0")
        self.qty_var.set("200")
        self.item_index_var.set("0")
        self.adena_cost_var.set("0")
        self.teleport_kind_var.set(TELEPORT_KIND_DUNGEON_GATE)
        self.dest_dungeon_var.set("")
        self.land_map_var.set("")
        self.land_x_var.set("0")
        self.land_y_var.set("0")
        self.world_nav_var.set(False)
        self.sell_mode_var.set(SELL_MODE_ONLY_GARBAGE)
        self._sync_action_panel()

    def _load_form(self, b: ShoppingBehavior) -> None:
        self.id_var.set(b.id)
        self.name_var.set(b.name)
        self.action_var.set(b.action)
        self.map_var.set(b.map_id)
        self.scroll_var.set(self._scroll_label_for_id(b.scroll_spot))
        self.world_x_var.set(str(int(b.npc_world_x)))
        self.world_y_var.set(str(int(b.npc_world_y)))
        self.qty_var.set(str(int(b.default_qty)))
        self.item_index_var.set(str(int(b.item_index)))
        self.adena_cost_var.set(str(int(b.adena_cost)))
        kind = str(getattr(b, "teleport_kind", "") or TELEPORT_KIND_DUNGEON_GATE)
        if kind not in TELEPORT_KINDS:
            kind = (
                TELEPORT_KIND_FIELD_LAND
                if int(getattr(b, "land_map_id", 0) or 0) > 0
                else TELEPORT_KIND_DUNGEON_GATE
            )
        self.teleport_kind_var.set(kind)
        self.dest_dungeon_var.set(
            self._dest_label_for_id(int(getattr(b, "destination_dungeon", 0) or 0))
        )
        self.land_map_var.set(
            self._land_label_for_id(int(getattr(b, "land_map_id", 0) or 0))
        )
        self.land_x_var.set(str(int(getattr(b, "land_world_x", 0) or 0)))
        self.land_y_var.set(str(int(getattr(b, "land_world_y", 0) or 0)))
        self.world_nav_var.set(bool(getattr(b, "world_nav", False)))
        mode = b.sell_mode if b.sell_mode in SELL_MODES else SELL_MODE_ONLY_GARBAGE
        self.sell_mode_var.set(mode)
        self._sync_action_panel()

    def _combo_text(self, combo: ttk.Combobox | None, var: tk.StringVar) -> str:
        """Read Combobox display text (typed value may lag the StringVar)."""
        if combo is not None:
            try:
                return str(combo.get()).strip()
            except tk.TclError:
                pass
        return str(var.get()).strip()

    def _parse_form(self) -> ShoppingBehavior:
        sid = self.id_var.get().strip()
        if not sid or not _ID_SAFE.match(sid):
            raise ValueError(
                "Id must start with a letter and use only letters, digits, _ or -"
            )
        action = self._combo_text(self._action_combo, self.action_var).lower()
        if action not in ACTIONS:
            raise ValueError("Action must be buy, sell, store, or teleporter")
        map_id = self._combo_text(self._map_combo, self.map_var)
        scroll = self._scroll_id_from_form()
        if not map_id or not scroll:
            raise ValueError("Map and scroll spot are required")
        try:
            wx = int(float(self.world_x_var.get().strip()))
            wy = int(float(self.world_y_var.get().strip()))
        except ValueError as exc:
            raise ValueError("NPC world must be integers") from exc
        try:
            qty = max(1, min(999, int(float(self.qty_var.get().strip() or "1"))))
        except ValueError as exc:
            raise ValueError("Default qty must be 1..999") from exc
        try:
            item_index = max(0, int(float(self.item_index_var.get().strip() or "0")))
        except ValueError as exc:
            raise ValueError("Item index must be an integer >= 0") from exc
        try:
            adena_cost = max(0, int(float(self.adena_cost_var.get().strip() or "0")))
        except ValueError as exc:
            raise ValueError("Adena cost must be an integer >= 0") from exc
        teleport_kind = self._combo_text(
            self._kind_combo, self.teleport_kind_var
        ).lower()
        if teleport_kind not in TELEPORT_KINDS:
            teleport_kind = TELEPORT_KIND_DUNGEON_GATE
        destination_dungeon = self._dest_id_from_form()
        land_map_id = self._land_id_from_form()
        try:
            land_world_x = int(float(self.land_x_var.get().strip() or "0"))
            land_world_y = int(float(self.land_y_var.get().strip() or "0"))
        except ValueError as exc:
            raise ValueError("Land world must be integers") from exc
        sell_mode = self._combo_text(self._sell_mode_combo, self.sell_mode_var)
        if sell_mode not in SELL_MODES:
            sell_mode = SELL_MODE_ONLY_GARBAGE
        if action not in (ACTION_SELL, ACTION_STORE):
            sell_mode = SELL_MODE_ONLY_GARBAGE
        if action in (ACTION_SELL, ACTION_STORE):
            item_index = 0
            adena_cost = 0
            destination_dungeon = 0
            land_map_id = 0
            land_world_x = 0
            land_world_y = 0
            teleport_kind = TELEPORT_KIND_DUNGEON_GATE
        world_nav = bool(self.world_nav_var.get())
        if action == ACTION_TELEPORTER:
            item_index = 0
            qty = 1
            if teleport_kind == TELEPORT_KIND_FIELD_LAND:
                destination_dungeon = 0
                if land_map_id <= 0:
                    raise ValueError("Land map is required for field_land teleporter")
            else:
                land_map_id = 0
                land_world_x = 0
                land_world_y = 0
                if destination_dungeon <= 0:
                    raise ValueError(
                        "Dest dungeon mapId is required for dungeon_gate teleporter"
                    )
        else:
            adena_cost = 0
            destination_dungeon = 0
            land_map_id = 0
            land_world_x = 0
            land_world_y = 0
            teleport_kind = TELEPORT_KIND_DUNGEON_GATE
            world_nav = False
        prev_ui = ShoppingUiClicks()
        prev_offset = None
        if self._selected_index is not None:
            prev = self._behaviors[self._selected_index]
            prev_ui = prev.ui
            prev_offset = prev.click_offset_uv
        if action == ACTION_TELEPORTER:
            prev_ui = ShoppingUiClicks(
                buy_button=prev_ui.buy_button,
                confirm_button=prev_ui.confirm_button,
            )
        return ShoppingBehavior(
            id=sid,
            name=self.name_var.get().strip() or sid,
            action=action,
            map_id=map_id,
            scroll_spot=scroll,
            npc_world_x=wx,
            npc_world_y=wy,
            default_qty=qty,
            item_index=item_index,
            adena_cost=adena_cost,
            teleport_kind=teleport_kind,
            destination_dungeon=destination_dungeon,
            land_map_id=land_map_id,
            land_world_x=land_world_x,
            land_world_y=land_world_y,
            world_nav=world_nav,
            sell_mode=sell_mode,
            click_offset_uv=prev_offset,
            ui=prev_ui,
        )

    def apply_form_to_selected(
        self, *, silent: bool = False, refresh: bool = True
    ) -> bool:
        if self._selected_index is None:
            if not silent:
                messagebox.showinfo(
                    "Behaviors", "Select a behavior first.", parent=self.winfo_toplevel()
                )
            return False
        try:
            b = self._parse_form()
        except Exception as exc:
            if not silent:
                messagebox.showwarning(
                    "Behaviors", str(exc), parent=self.winfo_toplevel()
                )
            self._log(str(exc))
            return False
        for i, other in enumerate(self._behaviors):
            if i != self._selected_index and other.id == b.id:
                msg = f"Duplicate id {b.id!r}"
                if not silent:
                    messagebox.showwarning(
                        "Behaviors", msg, parent=self.winfo_toplevel()
                    )
                self._log(msg)
                return False
        self._behaviors[self._selected_index] = b
        self._dirty = True
        if refresh:
            self._refresh_tree(select_index=self._selected_index)
        if not silent:
            self._log(
                f"Updated {b.id} in memory — click Save to write engine data"
            )
        return True

    def add_behavior(self) -> None:
        existing = {b.id for b in self._behaviors}
        sid = "new_behavior"
        n = 1
        while sid in existing:
            n += 1
            sid = f"new_behavior_{n}"
        self._behaviors.append(default_behavior(sid))
        self._dirty = True
        self._refresh_tree(select_index=len(self._behaviors) - 1)
        self._log(f"Added {sid} — click Save to write engine data")

    def duplicate_behavior(self) -> None:
        if self._selected_index is None:
            return
        src = self._behaviors[self._selected_index]
        existing = {b.id for b in self._behaviors}
        sid = f"{src.id}_copy"
        n = 2
        while sid in existing:
            sid = f"{src.id}_copy{n}"
            n += 1
        self._behaviors.append(replace(src, id=sid, name=f"{src.name} copy"))
        self._dirty = True
        self._refresh_tree(select_index=len(self._behaviors) - 1)
        self._log(f"Duplicated -> {sid} — click Save to write engine data")

    def delete_behavior(self) -> None:
        if self._selected_index is None:
            return
        b = self._behaviors[self._selected_index]
        if not messagebox.askyesno(
            "Behaviors",
            f"Delete {b.id!r}?\n(Save to write disk.)",
            parent=self.winfo_toplevel(),
        ):
            return
        del self._behaviors[self._selected_index]
        self._dirty = True
        next_i = min(self._selected_index, len(self._behaviors) - 1)
        self._selected_index = None
        self._refresh_tree(select_index=next_i if self._behaviors else None)
        self._log(f"Deleted {b.id} — click Save to write engine data")

    def flush_pending_form(self) -> bool:
        """Push the form into memory (does not write disk). Used before tab switch."""
        if self._selected_index is None:
            return True
        return self.apply_form_to_selected(silent=True, refresh=False)

    def current_behaviors(self) -> list[ShoppingBehavior]:
        """In-memory behaviors (form flushed). Used when Sell tab saves lists."""
        self.flush_pending_form()
        return list(self._behaviors)

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty)

    def fill_world_from_memory(self) -> None:
        try:
            from shopping.memory_fill import read_player_game_xy

            gx, gy = read_player_game_xy()
            self.world_x_var.set(str(gx))
            self.world_y_var.set(str(gy))
            self._log(f"NPC world from memory: [{gx}, {gy}]")
            if self._selected_index is not None:
                self.apply_form_to_selected(silent=True, refresh=False)
                self._dirty = True
        except Exception as exc:
            messagebox.showwarning(
                "Behaviors", str(exc), parent=self.winfo_toplevel()
            )
            self._log(f"Fill memory failed: {exc}")

    def fill_land_from_memory(self) -> None:
        """After Run Practice field TP: stamp land mapId + xy from live pose."""
        try:
            from shopping.memory_fill import read_player_game_xy, read_player_map_id

            mid = read_player_map_id()
            gx, gy = read_player_game_xy()
            self.teleport_kind_var.set(TELEPORT_KIND_FIELD_LAND)
            self.land_map_var.set(self._land_label_for_id(int(mid)))
            if not self.land_map_var.get().strip():
                self.land_map_var.set(str(int(mid)))
            self.land_x_var.set(str(gx))
            self.land_y_var.set(str(gy))
            self._sync_action_panel()
            self._log(f"Land from memory: map{mid} [{gx}, {gy}]")
            if self._selected_index is not None:
                self.apply_form_to_selected(silent=True, refresh=False)
                self._dirty = True
        except Exception as exc:
            messagebox.showwarning(
                "Behaviors", str(exc), parent=self.winfo_toplevel()
            )
            self._log(f"Fill land failed: {exc}")

    # ------------------------------------------------------------------ calibrate

    def _current(self) -> Optional[ShoppingBehavior]:
        if self._selected_index is None:
            return None
        if 0 <= self._selected_index < len(self._behaviors):
            return self._behaviors[self._selected_index]
        return None

    def _set_current_ui(self, ui: ShoppingUiClicks) -> None:
        b = self._current()
        if b is None or self._selected_index is None:
            return
        self._behaviors[self._selected_index] = replace(b, ui=ui)
        self._dirty = True

    def seed_markers(self) -> None:
        b = self._current()
        if b is None:
            messagebox.showinfo(
                "Behaviors", "Select a behavior first.", parent=self.winfo_toplevel()
            )
            return
        self._set_current_ui(_default_ui_layout(action=b.action))
        self._redraw()
        self._log("Seeded default marker layout (adjust on capture)")

    def recapture(self) -> None:
        try:
            from session.perception_capture import (
                grab_perception_frame,
                open_perception_capture,
            )

            capture = open_perception_capture()
            try:
                frame = grab_perception_frame(capture, retries=40, wait_s=0.05)
            finally:
                close = getattr(capture, "stop", None) or getattr(capture, "close", None)
                if callable(close):
                    close()
            if frame is None:
                raise RuntimeError("No game frame — make sure LC.exe is visible")
            self._frame = frame
            b = self._current()
            keys = self._active_marker_keys or _SHOP_MARKER_KEYS
            if b is not None and not any(
                _uv_get(b.ui, k) is not None for k in keys
            ):
                self._set_current_ui(_default_ui_layout(action=b.action))
            self._zoom = 1.0
            self._pan = (0.0, 0.0)
            self.zoom_label_var.set("100%")
            self._redraw()
            self._log(f"Captured frame {frame.shape[1]}x{frame.shape[0]}")
            self.canvas.focus_set()
        except Exception as exc:
            messagebox.showwarning(
                "Behaviors", str(exc), parent=self.winfo_toplevel()
            )
            self._log(f"Recapture failed: {exc}")

    def _on_marker_select(self, _event=None) -> None:
        sel = self.marker_list.curselection()
        if not sel:
            return
        keys = self._active_marker_keys or _SHOP_MARKER_KEYS
        idx = int(sel[0])
        if idx < 0 or idx >= len(keys):
            return
        self._marker_key = keys[idx]
        action = self._combo_text(self._action_combo, self.action_var).lower()
        label = _MARKER_LABELS[self._marker_key]
        if action == ACTION_TELEPORTER and self._marker_key == "buy_button":
            label = "Teleport option"
        self.marker_var.set(label)
        self._redraw()
        self.canvas.focus_set()

    def _zoom_by(self, factor: float) -> None:
        self._zoom = max(0.25, min(8.0, self._zoom * factor))
        self.zoom_label_var.set(f"{int(round(self._zoom * 100))}%")
        self._redraw()

    def _zoom_reset(self) -> None:
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.zoom_label_var.set("100%")
        self._redraw()

    def _on_wheel(self, event: tk.Event) -> None:
        if event.delta > 0:
            self._zoom_by(1.25)
        else:
            self._zoom_by(1 / 1.25)

    def _fit(self):
        import cv2
        from PIL import Image, ImageTk

        frame = self._frame
        assert frame is not None
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        fit = min(cw / image.width, ch / image.height)
        scale = fit * self._zoom
        dw = max(1, int(round(image.width * scale)))
        dh = max(1, int(round(image.height * scale)))
        image = image.resize((dw, dh), getattr(Image, "Resampling", Image).BILINEAR)
        photo = ImageTk.PhotoImage(image, master=self)
        ox = (cw - dw) / 2 + self._pan[0]
        oy = (ch - dh) / 2 + self._pan[1]
        return photo, scale, ox, oy, dw, dh

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self._frame is None:
            self.canvas.create_text(
                20,
                20,
                anchor="nw",
                fill="#aaaaaa",
                text="Recapture a shop dialog frame to place UV markers.",
            )
            return
        photo, scale, ox, oy, dw, dh = self._fit()
        self._photo = photo
        self._scale = scale
        self._offset = (ox, oy)
        self._img_size = (dw, dh)
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)
        b = self._current()
        if b is None:
            return
        h, w = self._frame.shape[:2]
        action = str(b.action or "").strip().lower()
        keys = (
            _TELEPORTER_MARKER_KEYS
            if action == ACTION_TELEPORTER
            else _SHOP_MARKER_KEYS
        )
        for key in keys:
            pt = _uv_get(b.ui, key)
            if pt is None:
                continue
            cx = ox + pt[0] * w * scale
            cy = oy + pt[1] * h * scale
            selected = key == self._marker_key
            color = "#22c55e" if selected else "#38bdf8"
            r = 7 if selected else 5
            self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r, outline=color, width=2, fill=""
            )
            label = _MARKER_LABELS[key]
            if action == ACTION_TELEPORTER and key == "buy_button":
                label = "Teleport option"
            self.canvas.create_text(
                cx + 10,
                cy - 10,
                anchor="sw",
                fill=color,
                text=label,
                font=("Segoe UI", 8),
            )

    def _canvas_to_uv(self, x: float, y: float) -> Optional[tuple[float, float]]:
        if self._frame is None:
            return None
        h, w = self._frame.shape[:2]
        ox, oy = self._offset
        scale = self._scale
        if scale <= 0:
            return None
        u = (x - ox) / (w * scale)
        v = (y - oy) / (h * scale)
        if u < 0 or v < 0 or u > 1 or v > 1:
            return None
        return (u, v)

    def _on_press(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        b = self._current()
        if b is None or self._frame is None:
            return
        uv = self._canvas_to_uv(event.x, event.y)
        if uv is None:
            return
        # Select nearest marker within a few px, else move selected marker here.
        h, w = self._frame.shape[:2]
        ox, oy = self._offset
        scale = self._scale
        best_key = None
        best_d = 18.0
        keys = self._active_marker_keys or _SHOP_MARKER_KEYS
        for key in keys:
            pt = _uv_get(b.ui, key)
            if pt is None:
                continue
            cx = ox + pt[0] * w * scale
            cy = oy + pt[1] * h * scale
            d = ((cx - event.x) ** 2 + (cy - event.y) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best_key = key
        if best_key is not None:
            self._marker_key = best_key
            idx = keys.index(best_key)
            self.marker_list.selection_clear(0, "end")
            self.marker_list.selection_set(idx)
            self.marker_list.see(idx)
            action = self._combo_text(self._action_combo, self.action_var).lower()
            label = _MARKER_LABELS[best_key]
            if action == ACTION_TELEPORTER and best_key == "buy_button":
                label = "Teleport option"
            self.marker_var.set(label)
        else:
            ui = _uv_set(b.ui, self._marker_key, uv)
            self._set_current_ui(ui)
        self._drag = True
        self._drag_start = (event.x, event.y)
        self._redraw()

    def _on_drag(self, event: tk.Event) -> None:
        if not self._drag:
            return
        b = self._current()
        if b is None:
            return
        uv = self._canvas_to_uv(event.x, event.y)
        if uv is None:
            return
        self._set_current_ui(_uv_set(b.ui, self._marker_key, uv))
        self._redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag = False

    def _on_pan_press(self, event: tk.Event) -> None:
        self._pan_drag = True
        self._drag_start = (event.x, event.y)
        self._pan0 = self._pan

    def _on_pan_drag(self, event: tk.Event) -> None:
        if not self._pan_drag:
            return
        self._pan = (
            self._pan0[0] + (event.x - self._drag_start[0]),
            self._pan0[1] + (event.y - self._drag_start[1]),
        )
        self._redraw()

    def _on_pan_release(self, _event: tk.Event) -> None:
        self._pan_drag = False

    def _nudge(self, dx: int, dy: int, event: tk.Event) -> str:
        b = self._current()
        if b is None or self._frame is None:
            return "break"
        pt = _uv_get(b.ui, self._marker_key)
        if pt is None:
            return "break"
        step = 5 if (getattr(event, "state", 0) & 0x0001) else 1
        h, w = self._frame.shape[:2]
        u = max(0.0, min(1.0, pt[0] + (dx * step) / max(w, 1)))
        v = max(0.0, min(1.0, pt[1] + (dy * step) / max(h, 1)))
        self._set_current_ui(_uv_set(b.ui, self._marker_key, (u, v)))
        self._redraw()
        return "break"
