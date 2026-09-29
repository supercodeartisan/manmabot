"""Shopping behavior editor — identity/travel form + capture UV calibrate."""
from __future__ import annotations

import re
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk
from typing import Callable, Optional

from manmabot_v1.shopping.behaviors import (
    ITEM_ROW_COUNT,
    SELL_MODE_ONLY_GARBAGE,
    SELL_MODES,
    ShoppingBehavior,
    ShoppingSellFilters,
    ShoppingUiClicks,
    behaviors_path,
    default_behavior,
    load_behaviors,
    save_behaviors,
)
from manmabot_v1.ui.design_system import TEXT_MUTED

_ID_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

# Marker keys drawn on the capture canvas.
_MARKER_KEYS: tuple[str, ...] = (
    "buy_button",
    "sell_button",
    "confirm_button",
    "list_scroll_point",
    *(f"row_{i}" for i in range(ITEM_ROW_COUNT)),
)

_MARKER_LABELS = {
    "buy_button": "Buy button",
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


def _default_ui_layout() -> ShoppingUiClicks:
    """Placeholder UVs so markers appear before first calibrate."""
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
    """Edit userdata shopping behaviors (form + capture calibrate)."""

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
        self.action_var = tk.StringVar(self, value="buy")
        self.map_var = tk.StringVar(self)
        self.scroll_var = tk.StringVar(self)
        self.world_x_var = tk.StringVar(self, value="0")
        self.world_y_var = tk.StringVar(self, value="0")
        self.qty_var = tk.StringVar(self, value="200")
        self.item_index_var = tk.StringVar(self, value="0")
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

        self._build()
        self.reload_from_disk()

    def _log(self, message: str) -> None:
        self._on_log(message)
        self.status_var.set(message)

    def _build(self) -> None:
        from app._04_decision.shops import list_map_ids, list_scroll_spot_ids

        top = ttk.Frame(self, style="Chrome.TFrame")
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top,
            text="Shopping behaviors (userdata) — capture-calibrated dialog UVs",
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
        cols = ("id", "action", "map", "item")
        self.tree = ttk.Treeview(
            list_box, columns=cols, show="headings", selectmode="browse", height=16
        )
        for c, t, w in (
            ("id", "Id", 120),
            ("action", "Action", 50),
            ("map", "Map", 90),
            ("item", "Item#", 50),
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
            values=("buy", "sell"),
            state="readonly",
            width=10,
        )
        cell(1, 0, "Action", self._action_combo)
        self._map_combo = ttk.Combobox(
            form, textvariable=self.map_var, values=list_map_ids(), width=18
        )
        cell(1, 2, "Map", self._map_combo)
        self._scroll_combo = ttk.Combobox(
            form,
            textvariable=self.scroll_var,
            values=list_scroll_spot_ids(),
            width=18,
        )
        cell(2, 0, "Scroll spot", self._scroll_combo, colspan=1)
        world = ttk.Frame(form, style="Chrome.TFrame")
        ttk.Entry(world, textvariable=self.world_x_var, width=8).pack(side="left", padx=2)
        ttk.Entry(world, textvariable=self.world_y_var, width=8).pack(side="left", padx=2)
        ttk.Button(
            world, text="Fill NPC from memory", command=self.fill_world_from_memory
        ).pack(side="left", padx=6)
        cell(2, 2, "NPC world", world)
        self._item_index_entry = ttk.Entry(
            form, textvariable=self.item_index_var, width=8
        )
        cell(3, 0, "Item index", self._item_index_entry)
        cell(3, 2, "Default qty", ttk.Entry(form, textvariable=self.qty_var, width=8))
        ttk.Label(
            form,
            text="Edits stay in memory until you click Save (writes userdata/shopping_behaviors.yaml).",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 2))
        ttk.Button(
            form, text="Save fields to userdata", command=self.save_to_disk
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(2, 2))

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

        self._action_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_sell_panel())
        self.action_var.trace_add("write", lambda *_a: self._sync_sell_panel())

        calib = ttk.LabelFrame(right, text="Calibrate dialog UVs", padding=(6, 4))
        self._calib_frame = calib
        self._sync_sell_panel()
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
        for key in _MARKER_KEYS:
            self.marker_list.insert("end", _MARKER_LABELS[key])
        self.marker_list.selection_set(0)
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
                from debug_tools import OUTPUT_DIR

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
                    values=(b.id, b.action, b.map_id, b.item_index),
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
                values=(b.id, b.action, b.map_id, b.item_index),
            )
        except tk.TclError:
            pass

    def _sync_sell_panel(self) -> None:
        """Show sell mode when Action is sell; freeze item index (unused for sell)."""
        action = self._combo_text(self._action_combo, self.action_var).lower()
        entry = self._item_index_entry
        if entry is not None:
            try:
                entry.configure(state="disabled" if action == "sell" else "normal")
            except tk.TclError:
                pass
        if action == "sell":
            self.item_index_var.set("0")
        frame = self._sell_frame
        if frame is None:
            return
        if action == "sell":
            kwargs = {"fill": "x", "pady": (6, 0)}
            calib = self._calib_frame
            if calib is not None:
                try:
                    frame.pack(before=calib, **kwargs)
                    return
                except tk.TclError:
                    pass
            frame.pack(**kwargs)
        else:
            frame.pack_forget()

    def _clear_form(self) -> None:
        self.id_var.set("")
        self.name_var.set("")
        self.action_var.set("buy")
        self.map_var.set("")
        self.scroll_var.set("")
        self.world_x_var.set("0")
        self.world_y_var.set("0")
        self.qty_var.set("200")
        self.item_index_var.set("0")
        self.sell_mode_var.set(SELL_MODE_ONLY_GARBAGE)
        self._sync_sell_panel()

    def _load_form(self, b: ShoppingBehavior) -> None:
        self.id_var.set(b.id)
        self.name_var.set(b.name)
        self.action_var.set(b.action)
        self.map_var.set(b.map_id)
        self.scroll_var.set(b.scroll_spot)
        self.world_x_var.set(str(int(b.npc_world_x)))
        self.world_y_var.set(str(int(b.npc_world_y)))
        self.qty_var.set(str(int(b.default_qty)))
        self.item_index_var.set(str(int(b.item_index)))
        mode = b.sell_mode if b.sell_mode in SELL_MODES else SELL_MODE_ONLY_GARBAGE
        self.sell_mode_var.set(mode)
        self._sync_sell_panel()

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
        if action not in ("buy", "sell"):
            raise ValueError("Action must be buy or sell")
        map_id = self._combo_text(self._map_combo, self.map_var)
        scroll = self._combo_text(self._scroll_combo, self.scroll_var)
        if not map_id or not scroll:
            raise ValueError("Map and scroll spot are required")
        try:
            wx = int(float(self.world_x_var.get().strip()))
            wy = int(float(self.world_y_var.get().strip()))
        except ValueError as exc:
            raise ValueError("NPC world must be integers") from exc
        try:
            qty = max(1, min(999, int(float(self.qty_var.get().strip()))))
        except ValueError as exc:
            raise ValueError("Default qty must be 1..999") from exc
        try:
            item_index = max(0, int(float(self.item_index_var.get().strip())))
        except ValueError as exc:
            raise ValueError("Item index must be an integer >= 0") from exc
        sell_mode = self._combo_text(self._sell_mode_combo, self.sell_mode_var)
        if sell_mode not in SELL_MODES:
            sell_mode = SELL_MODE_ONLY_GARBAGE
        if action != "sell":
            sell_mode = SELL_MODE_ONLY_GARBAGE
        else:
            item_index = 0
        prev_ui = ShoppingUiClicks()
        if self._selected_index is not None:
            prev_ui = self._behaviors[self._selected_index].ui
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
            sell_mode=sell_mode,
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
                f"Updated {b.id} in memory — click Save to write userdata"
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
        self._log(f"Added {sid} — click Save to write userdata")

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
        self._log(f"Duplicated -> {sid} — click Save to write userdata")

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
        self._log(f"Deleted {b.id} — click Save to write userdata")

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
            from tool.utils import load_config
            from app._03_world.memory_client import PIPE_NAME, LineageMonitor

            config = load_config()
            section = config.get("memory") or {}
            if not bool(section.get("enabled", False)):
                raise RuntimeError("memory.enabled is false")
            pipe = str(section.get("pipe") or PIPE_NAME)
            retries = max(5, int(section.get("connect_retries", 30)))
            delay = float(section.get("connect_delay", 0.2))
            mon = LineageMonitor(pipe=pipe, connect_retries=retries, connect_delay=delay)
            try:
                mon.connect()
                mon.ping()
                snap = mon.snapshot(fresh=True)
            finally:
                mon.close()
            pos = ((snap or {}).get("player") or {}).get("pos")
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                raise RuntimeError("no player position")
            gx, gy = int(pos[0]), int(pos[1])
            if gx == 0 and gy == 0:
                raise RuntimeError("player position unset (0,0)")
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
        self._set_current_ui(_default_ui_layout())
        self._redraw()
        self._log("Seeded default marker layout (adjust on capture)")

    def recapture(self) -> None:
        try:
            from manmabot_v1.perception_capture import (
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
            if b is not None and not any(
                _uv_get(b.ui, k) is not None for k in _MARKER_KEYS
            ):
                self._set_current_ui(_default_ui_layout())
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
        self._marker_key = _MARKER_KEYS[int(sel[0])]
        self.marker_var.set(_MARKER_LABELS[self._marker_key])
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
        for key in _MARKER_KEYS:
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
            self.canvas.create_text(
                cx + 10,
                cy - 10,
                anchor="sw",
                fill=color,
                text=_MARKER_LABELS[key],
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
        for key in _MARKER_KEYS:
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
            idx = _MARKER_KEYS.index(best_key)
            self.marker_list.selection_clear(0, "end")
            self.marker_list.selection_set(idx)
            self.marker_list.see(idx)
            self.marker_var.set(_MARKER_LABELS[best_key])
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
