"""Debug inspector panel and standalone debug bot player."""
from __future__ import annotations

import io
import threading
import tkinter as tk
from datetime import datetime
from typing import Callable
from tkinter import messagebox, ttk

from session.bot_controller import BotController, RunState
from session.debug_snapshot import (
    STATUS_SECTIONS,
    columns_for_section,
    rows_for_section,
    section_text,
)
from settings.map_previews import brand_icon_path
from session.paths import LOG_DIR, USERDATA, ensure_userdata
from session.probes import Lamp, localize_probe_detail
from settings.profile import Profile, load_profile, save_profile
from ui.design_system import (
    BG,
    BORDER,
    CHROME,
    SELECTED,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    FONT_BODY,
    apply_classic_style,
)
from ui import design_system as ui_theme
from i18n.strings import ui_language
from ui.fonts import load_bundled_fonts
from ui.operator_coordinator import OperatorCoordinator
from ui.schedule_i18n import tr


def _fmt_cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


class DebugPanel(ttk.Frame):
    """Status-list inspector bound to one BotController."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: BotController,
        get_logs: Callable[[], list[str]],
        t: dict[str, str],
        get_arming: Callable[[], bool] | None = None,
        note_text: str = "",
    ) -> None:
        super().__init__(master)
        self.controller = controller
        self.get_logs = get_logs
        self.get_arming = get_arming or (lambda: False)
        self.t = t
        self._photo = None
        self._section = STATUS_SECTIONS[0]
        self._last_log_len = -1
        self._last_tree_stamp = None
        self._previewing = False
        self._preview_busy = False
        self._preview_seq = 0
        self._preview_lock = threading.Lock()
        self._pending_preview = None
        self._preview_fail = False
        self._note_text = note_text
        self._nav_photo = None
        self._nav_photo_key = None
        self._nav_source = None
        self._nav_source_stamp = None
        self._nav_zoom = 1.0
        self._nav_fit_done = False
        self._nav_show_seq = 0
        self._nav_show_lock = threading.Lock()
        self._pending_nav_show = None
        self._pending_nav_stamp = None
        self._nav_show_fail = False
        self._nav_show_busy = False
        self._last_nav_decision_stamp = None
        self._last_nav_map_stamp = None
        self._nav_blocked = False
        self._nav_configure_after = None
        self._nav_worker = None
        self._build()

    def _tr(self, key: str, fallback: str | None = None) -> str:
        return self.t.get(key, fallback or key)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")
        status_box = tk.Frame(header, background=CHROME)
        status_box.pack(side="left")
        self.state_dot = tk.Canvas(
            status_box, width=13, height=13, background=CHROME, highlightthickness=0
        )
        self.state_dot.pack(side="left", padx=(0, 4))
        self.state_dot_item = self.state_dot.create_oval(
            2, 2, 11, 11, fill="#dc2626", outline="#991b1b"
        )
        self.state_label = tk.Label(
            status_box,
            text="",
            background=CHROME,
            foreground=TEXT,
            font=(FONT_BODY[0], FONT_BODY[1], "bold"),
        )
        self.state_label.pack(side="left")
        self.note_label = tk.Label(
            header,
            text=self._note_text or self._tr("debug_same_run"),
            background=CHROME,
            foreground=TEXT_MUTED,
        )
        self.note_label.pack(side="left", padx=14)
        ttk.Button(header, text=self._tr("debug_copy"), command=self.copy).pack(
            side="right"
        )

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        left = ttk.Frame(paned, padding=4)
        right = ttk.Frame(paned, padding=4)
        paned.add(left, weight=1)
        paned.add(right, weight=4)

        list_box = ttk.LabelFrame(
            left, text=self._tr("debug_status_list"), padding=(6, 4)
        )
        list_box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            list_box,
            exportselection=False,
            activestyle="dotbox",
            background=SURFACE,
            foreground=TEXT,
            selectbackground=SELECTED,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightcolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        self.listbox.pack(fill="both", expand=True)
        for section in STATUS_SECTIONS:
            self.listbox.insert("end", self._tr(f"debug_{section}"))
        self.listbox.selection_set(0)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        details = ttk.LabelFrame(right, text=self._tr("debug_details"), padding=(6, 4))
        details.pack(fill="both", expand=True)
        details.grid_rowconfigure(0, weight=1)
        details.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(details, show="headings", style="Grid.Treeview")
        self.tree_scroll = ttk.Scrollbar(
            details, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll.grid(row=0, column=1, sticky="ns")

        self.log_widget = tk.Text(
            details,
            state="disabled",
            wrap="word",
            background=SURFACE,
            foreground=TEXT,
            font=("Consolas", 9),
            relief="solid",
            borderwidth=1,
        )
        self.preview_label = tk.Label(
            details,
            text=self._tr("debug_preview_waiting"),
            background="#111111",
            foreground="#d1d5db",
            anchor="center",
        )
        self.nav_show_frame = ttk.Frame(details)
        self.nav_show_frame.grid_rowconfigure(2, weight=1)
        self.nav_show_frame.grid_columnconfigure(0, weight=4)
        self.nav_show_frame.grid_columnconfigure(1, weight=1)
        nav_bar = ttk.Frame(self.nav_show_frame)
        nav_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        ttk.Button(nav_bar, text="−", width=3, command=lambda: self._nav_zoom_by(0.8)).pack(
            side="left", padx=(0, 2)
        )
        ttk.Button(nav_bar, text="+", width=3, command=lambda: self._nav_zoom_by(1.25)).pack(
            side="left", padx=(0, 2)
        )
        ttk.Button(
            nav_bar,
            text=self._tr("debug_nav_show_reset", "Reset"),
            command=self._nav_reset_view,
        ).pack(side="left", padx=(0, 8))
        self.nav_zoom_label = tk.Label(
            nav_bar, text="100%", background=SURFACE, foreground=TEXT_MUTED
        )
        self.nav_zoom_label.pack(side="left")
        tk.Label(
            nav_bar,
            text=self._tr("debug_nav_show_hint", "Wheel: zoom · Drag: pan"),
            background=SURFACE,
            foreground=TEXT_MUTED,
        ).pack(side="right")
        self.nav_blocked_banner = tk.Label(
            self.nav_show_frame,
            text="",
            background="#7f1d1d",
            foreground="#fee2e2",
            font=(FONT_BODY[0], FONT_BODY[1], "bold"),
            anchor="w",
            padx=8,
            pady=2,
        )
        self.nav_gate_warn_banner = tk.Label(
            self.nav_show_frame,
            text="",
            background="#7f1d1d",
            foreground="#fef08a",
            font=(FONT_BODY[0], FONT_BODY[1], "bold"),
            anchor="w",
            padx=8,
            pady=2,
            wraplength=720,
            justify="left",
        )
        self.nav_show_canvas = tk.Canvas(
            self.nav_show_frame,
            background="#111111",
            highlightthickness=0,
            cursor="fleur",
        )
        self.nav_show_canvas.grid(row=2, column=0, sticky="nsew", padx=(0, 4))
        self.nav_show_canvas.bind("<MouseWheel>", self._nav_on_wheel)
        self.nav_show_canvas.bind("<Button-4>", self._nav_on_wheel_linux)
        self.nav_show_canvas.bind("<Button-5>", self._nav_on_wheel_linux)
        self.nav_show_canvas.bind("<ButtonPress-1>", self._nav_pan_start)
        self.nav_show_canvas.bind("<B1-Motion>", self._nav_pan_move)
        self.nav_show_canvas.bind("<ButtonPress-3>", self._nav_pan_start)
        self.nav_show_canvas.bind("<B3-Motion>", self._nav_pan_move)
        self.nav_show_canvas.bind("<Configure>", self._nav_on_configure)
        decision_box = ttk.LabelFrame(
            self.nav_show_frame,
            text=self._tr("debug_nav_show_decision", "Decision detail"),
            padding=(4, 2),
        )
        decision_box.grid(row=2, column=1, sticky="nsew")
        decision_box.grid_rowconfigure(0, weight=1)
        decision_box.grid_columnconfigure(0, weight=1)
        self.nav_decision_text = tk.Text(
            decision_box,
            state="disabled",
            wrap="word",
            width=36,
            background=SURFACE,
            foreground=TEXT,
            font=("Consolas", 9),
            relief="flat",
            borderwidth=0,
        )
        self.nav_decision_text.grid(row=0, column=0, sticky="nsew")
        self.nav_decision_text.tag_configure("warn", foreground="#ef4444")
        self.empty_label = tk.Label(
            details,
            text=self._tr("debug_idle"),
            background=SURFACE,
            foreground=TEXT_MUTED,
            wraplength=560,
            justify="left",
            anchor="nw",
        )
        self.tables_frame = ttk.Frame(details)
        for col in range(3):
            self.tables_frame.grid_columnconfigure(col, weight=1 if col == 0 else 3, uniform="mem")
        self.tables_frame.grid_rowconfigure(0, weight=3)
        self.tables_frame.grid_rowconfigure(1, weight=3)
        self.tables_frame.grid_rowconfigure(2, weight=2)
        self.tables_frame.grid_rowconfigure(3, weight=2)
        self._install_mem_tree_style()
        self.player_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_player"),
            0,
            0,
            (("field", "debug_field", 70), ("value", "debug_value", 110)),
        )
        self.entity_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_entities"),
            0,
            1,
            (
                ("class", "debug_class", 70),
                ("name", "debug_name", 90),
                ("species", "debug_species", 50),
                ("world", "debug_col_world", 80),
                ("screen", "debug_col_screen", 80),
                ("iscr", "debug_col_iscr", 80),
                ("src", "debug_src", 40),
                ("ent", "debug_ent", 90),
            ),
        )
        self.inventory_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_inventory"),
            0,
            2,
            (
                ("slot", "debug_slot", 36),
                ("id", "debug_id", 50),
                ("name", "debug_name", 90),
                ("tw", "debug_name_tw", 80),
                ("count", "debug_count", 40),
                ("kind", "debug_kind", 40),
                ("fmt", "debug_fmt", 70),
            ),
        )
        self.hotbar_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_hotbar"),
            1,
            0,
            (
                ("slot", "debug_slot", 36),
                ("box", "hotbar_box", 40),
                ("key", "hotbar_key", 40),
                ("type", "debug_type", 50),
                ("name", "debug_name", 120),
                ("count", "debug_count", 40),
                ("role", "debug_role", 70),
            ),
            columnspan=3,
        )
        self.buff_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_buffs"),
            2,
            0,
            (("id", "debug_id", 60), ("remain", "debug_remain", 50), ("stacks", "debug_stacks", 50)),
        )
        self.skill_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_skills"),
            2,
            1,
            (("id", "debug_id", 60), ("name", "debug_name", 110), ("level", "debug_level", 40)),
        )
        self.party_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_party"),
            2,
            2,
            (("name", "debug_name", 90), ("hp", "debug_hp", 50), ("class", "debug_class", 70)),
        )
        self.shop_sell_tree = self._make_table(
            self.tables_frame,
            self._tr("debug_table_shop_sell"),
            3,
            0,
            (
                ("idx", "debug_idx", 36),
                ("id", "debug_id", 50),
                ("name", "debug_name", 140),
                ("count", "debug_count", 40),
                ("unit", "debug_unit", 40),
                ("tmpl", "debug_tmpl", 50),
                ("action", "debug_sell_action", 50),
            ),
            columnspan=3,
        )
        self._show_tree()
        self._configure_tree(self._section)
        self.refresh(force=True)

    def _install_mem_tree_style(self) -> None:
        style = ttk.Style(self)
        family = FONT_BODY[0]
        style.configure(
            "Mem.Treeview",
            rowheight=16,
            font=(family, 8),
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Mem.Treeview.Heading",
            padding=(2, 1),
            font=(family, 8, "bold"),
            background=SURFACE,
            foreground=TEXT,
        )
        style.map(
            "Mem.Treeview",
            background=[("selected", SELECTED)],
            foreground=[("selected", "#ffffff")],
        )

    def _make_table(
        self,
        parent: ttk.Frame,
        title: str,
        row: int,
        column: int,
        columns: tuple[tuple[str, str, int], ...],
        columnspan: int = 1,
    ) -> ttk.Treeview:
        box = ttk.LabelFrame(parent, text=title, padding=(2, 1))
        box.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="nsew",
            padx=(0, 3),
            pady=(0, 3),
        )
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        ids = [column_spec[0] for column_spec in columns]
        tree = ttk.Treeview(box, show="headings", style="Mem.Treeview", columns=ids)
        scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        stretch = {"value", "name", "fmt", "screen", "iscr", "ent", "tw", "role", "action"}
        for column_id, label_key, width in columns:
            tree.heading(column_id, text=self._tr(label_key))
            tree.column(column_id, width=width, minwidth=28, stretch=column_id in stretch)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return tree

    def _hide_details(self) -> None:
        for widget in (
            self.tree,
            self.tree_scroll,
            self.log_widget,
            self.preview_label,
            self.nav_show_frame,
            self.empty_label,
            self.tables_frame,
        ):
            widget.grid_remove()

    def _show_tree(self) -> None:
        self._hide_details()
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll.grid(row=0, column=1, sticky="ns")

    def _show_logs(self) -> None:
        self._hide_details()
        self.log_widget.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def _set_previewing(self, on: bool) -> None:
        if on == self._previewing:
            return
        self._previewing = on
        if on:
            self.controller.add_preview_watcher()
        else:
            self.controller.remove_preview_watcher()

    def _show_preview(self) -> None:
        self._hide_details()
        self._set_previewing(True)
        self.preview_label.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def _ensure_nav_worker(self):
        if self._nav_worker is None:
            from session.nav_debug_view import NavShowRenderWorker

            self._nav_worker = NavShowRenderWorker()
        return self._nav_worker

    def _show_nav_show(self) -> None:
        self._hide_details()
        self._set_previewing(False)
        self._ensure_nav_worker()
        self.nav_show_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.after_idle(self._nav_redraw)

    def _show_tables(self) -> None:
        self._hide_details()
        self.tables_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def _show_empty(self, text: str) -> None:
        self._hide_details()
        self.empty_label.configure(text=text)
        self.empty_label.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def _on_select(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        section = STATUS_SECTIONS[int(selection[0])]
        if section == self._section:
            return
        self._section = section
        self._last_log_len = -1
        if section == "logs":
            self._set_previewing(False)
            self._show_logs()
        elif section == "preview":
            self._show_preview()
        elif section == "nav_show":
            self._show_nav_show()
        elif section == "tables":
            self._set_previewing(False)
            self._show_tables()
        else:
            self._set_previewing(False)
            self._configure_tree(section)
            self._show_tree()
        self.refresh(force=True)

    def _configure_tree(self, section: str) -> None:
        columns = columns_for_section(section)
        ids = [column[0] for column in columns]
        self.tree.configure(columns=ids)
        for column_id, label_key in columns:
            self.tree.heading(column_id, text=self._tr(label_key))
            width = 280 if column_id in {"value", "name", "spell", "position"} else 90
            if column_id == "field":
                width = 170
            self.tree.column(
                column_id,
                width=width,
                stretch=column_id in {"value", "name", "spell"},
            )

    def refresh(self, *, force: bool = False) -> None:
        snapshot = self.controller.debug_snapshot()
        overview = dict(snapshot.get("overview") or {})
        if self.get_arming():
            overview["arming"] = True
            snapshot = {**snapshot, "overview": overview}
        state_name = str(overview.get("state") or self.controller.state.value)
        try:
            state = RunState(state_name)
        except ValueError:
            state = self.controller.state
        colors = {
            RunState.STOPPED: ("#dc2626", "#991b1b"),
            RunState.RUNNING: ("#16a34a", "#166534"),
            RunState.PAUSED: ("#f59e0b", "#b45309"),
        }
        fill, outline = colors.get(state, ("#dc2626", "#991b1b"))
        self.state_dot.itemconfigure(self.state_dot_item, fill=fill, outline=outline)
        reason = str(overview.get("reason") or "")
        note = str(overview.get("note") or "")
        if overview.get("arming"):
            label = self._tr("debug_arming")
        else:
            label = self._tr(state_name, state_name)
        if reason:
            label = f"{label} — {reason}"
        elif note:
            label = f"{label} — {note}"
        self.state_label.configure(text=label)

        if self._section == "logs":
            self._refresh_logs(force=force)
            return
        if self._section == "preview":
            self._refresh_preview()
            return
        if self._section == "nav_show":
            self._refresh_nav_decision(snapshot)
            self._refresh_nav_show(snapshot)
            return
        if self._section == "tables":
            self._refresh_tables(snapshot, force=force)
            return

        stamp = (
            snapshot.get("updated_at"),
            overview.get("frame_id"),
            overview.get("note"),
            overview.get("state"),
            overview.get("reason"),
        )
        rows = rows_for_section(self._section, snapshot)
        if not rows:
            idle = not overview.get("worker_alive") and state is RunState.STOPPED
            self._show_empty(
                self._tr("debug_idle") if idle else self._tr("debug_no_data")
            )
            self._last_tree_stamp = stamp
            return
        if not force and stamp == self._last_tree_stamp:
            return
        self._last_tree_stamp = stamp
        if self.tree.winfo_manager() == "":
            self._show_tree()
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), values=row)

    def _fill_tree(self, tree: ttk.Treeview, rows: list[tuple[str, ...]]) -> None:
        tree.delete(*tree.get_children())
        for index, row in enumerate(rows):
            tree.insert("", "end", iid=str(index), values=row)

    def _refresh_tables(self, snapshot: dict, *, force: bool = False) -> None:
        tables = dict(snapshot.get("tables") or {})
        stamp = (
            snapshot.get("updated_at"),
            len(tables.get("entities") or []),
            len(tables.get("inventory") or []),
            len(tables.get("shop_sell") or []),
            tuple(
                (row.get("idx"), row.get("id"), row.get("action"), row.get("count"))
                for row in list(tables.get("shop_sell") or [])[:24]
                if isinstance(row, dict)
            ),
            len(tables.get("hotbar") or []),
            tuple(
                (row.get("name"), row.get("count"), row.get("type"))
                for row in list(tables.get("hotbar") or [])
                if isinstance(row, dict)
            ),
            len(tables.get("buffs") or []),
            len(tables.get("skills") or []),
            len(tables.get("party") or []),
            tuple(
                (row.get("field"), row.get("value"))
                for row in list(tables.get("player") or [])[:8]
                if isinstance(row, dict)
            ),
        )
        if not force and stamp == self._last_tree_stamp:
            return
        self._last_tree_stamp = stamp
        if self.tables_frame.winfo_manager() == "":
            self._show_tables()
        player_rows = [
            (_fmt_cell(row.get("field")), _fmt_cell(row.get("value")))
            for row in list(tables.get("player") or [])
            if isinstance(row, dict)
        ]
        entity_rows = [
            (
                _fmt_cell(row.get("class")),
                _fmt_cell(row.get("name")),
                _fmt_cell(row.get("species")),
                _fmt_cell(row.get("world")),
                _fmt_cell(row.get("screen")),
                _fmt_cell(row.get("iscr")),
                _fmt_cell(row.get("src")),
                _fmt_cell(row.get("ent")),
            )
            for row in list(tables.get("entities") or [])
            if isinstance(row, dict)
        ]
        inv_rows = [
            (
                _fmt_cell(row.get("slot")),
                _fmt_cell(row.get("id")),
                _fmt_cell(row.get("name")),
                _fmt_cell(row.get("tw")),
                _fmt_cell(row.get("count")),
                _fmt_cell(row.get("kind")),
                _fmt_cell(row.get("fmt")),
            )
            for row in list(tables.get("inventory") or [])
            if isinstance(row, dict)
        ]
        shop_sell_rows = [
            (
                _fmt_cell(row.get("idx")),
                _fmt_cell(row.get("id")),
                _fmt_cell(row.get("name")),
                _fmt_cell(row.get("count")),
                _fmt_cell(row.get("unit")),
                _fmt_cell(row.get("tmpl")),
                _fmt_cell(row.get("action")),
            )
            for row in list(tables.get("shop_sell") or [])
            if isinstance(row, dict)
        ]
        hotbar_rows = [
            (
                _fmt_cell(row.get("slot")),
                _fmt_cell(row.get("box")),
                _fmt_cell(row.get("key")),
                _fmt_cell(row.get("type")),
                _fmt_cell(row.get("name")),
                _fmt_cell(row.get("count")),
                _fmt_cell(row.get("role")),
            )
            for row in list(tables.get("hotbar") or [])
            if isinstance(row, dict)
        ]
        buff_rows = [
            (_fmt_cell(row.get("id")), _fmt_cell(row.get("remain")), _fmt_cell(row.get("stacks")))
            for row in list(tables.get("buffs") or [])
            if isinstance(row, dict)
        ]
        skill_rows = [
            (_fmt_cell(row.get("id")), _fmt_cell(row.get("name")), _fmt_cell(row.get("level")))
            for row in list(tables.get("skills") or [])
            if isinstance(row, dict)
        ]
        party_rows = [
            (_fmt_cell(row.get("name")), _fmt_cell(row.get("hp")), _fmt_cell(row.get("class")))
            for row in list(tables.get("party") or [])
            if isinstance(row, dict)
        ]
        self._fill_tree(self.player_tree, player_rows)
        self._fill_tree(self.entity_tree, entity_rows)
        self._fill_tree(self.inventory_tree, inv_rows)
        self._fill_tree(self.shop_sell_tree, shop_sell_rows)
        self._fill_tree(self.hotbar_tree, hotbar_rows)
        self._fill_tree(self.buff_tree, buff_rows)
        self._fill_tree(self.skill_tree, skill_rows)
        self._fill_tree(self.party_tree, party_rows)

    def _refresh_logs(self, *, force: bool = False) -> None:
        lines = self.get_logs()
        if not force and len(lines) == self._last_log_len:
            return
        self._last_log_len = len(lines)
        text = "\n".join(lines)
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        if text:
            self.log_widget.insert("end", text + "\n")
            self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _apply_pending_preview(self) -> None:
        with self._preview_lock:
            image = self._pending_preview
            failed = self._preview_fail
            self._pending_preview = None
            self._preview_fail = False
        if failed:
            self.preview_label.configure(
                image="", text=self._tr("debug_preview_waiting")
            )
            return
        if image is None:
            return
        try:
            from PIL import ImageTk

            photo = ImageTk.PhotoImage(image, master=self)
            self._photo = photo
            self.preview_label.configure(image=photo, text="")
        except Exception:
            self.preview_label.configure(
                image="", text=self._tr("debug_preview_waiting")
            )


    def _format_nav_decision(self, snapshot: dict) -> tuple[str, bool]:
        overview = dict(snapshot.get("overview") or {})
        decision = dict(snapshot.get("decision") or {})
        nav = dict(snapshot.get("navigation") or {})
        player = dict(snapshot.get("player") or {})
        map_id = str(
            nav.get("display_map")
            or nav.get("live_pack")
            or overview.get("map")
            or "talking_island"
        )
        origin = (
            nav.get("live_origin_xy")
            or nav.get("origin_xy")
            or nav.get("world_origin")
        )
        blocked = False
        try:
            from session.nav_debug_view import player_on_blocked_tile

            blocked = bool(player_on_blocked_tile(map_id, origin))
        except Exception:
            blocked = False

        def g(mapping: dict, key: str, default: str = "—") -> str:
            value = mapping.get(key)
            if value is None or value == "":
                return default
            return str(value)

        lines: list[str] = []
        if blocked:
            lines.append(f"WARNING  PLAYER ON BLOCKED TILE {origin}")
            lines.append("")
        lines.extend(
            [
                f"state     {g(overview, 'state')}",
                f"live_map  {g(nav, 'live_pack')}  id={g(nav, 'live_map_id')}",
                f"profile   {g(nav, 'profile_map') or g(overview, 'map')}",
                f"abs_xy    {g(nav, 'live_abs_xy')}",
                f"nav_xy    {g(nav, 'live_origin_xy') or g(nav, 'world_origin')}",
                f"mode      {g(decision, 'mode')}",
                f"goal      {g(decision, 'goal')}",
                f"action    {g(decision, 'action')}",
                f"reason    {g(decision, 'reason')}",
            ]
        )
        path_skips = [
            row
            for row in (decision.get("path_cap_skips") or [])
            if isinstance(row, dict)
        ]
        if path_skips:
            for row in path_skips[:4]:
                lines.append(
                    "path_cap  "
                    f"id={row.get('id')} {row.get('kind') or '?'} "
                    f"{row.get('reason') or 'path>30'}"
                )
        world_nav = nav.get("world_nav") if isinstance(nav.get("world_nav"), dict) else None
        if world_nav:
            lines.extend(
                [
                    f"wn_phase  {g(world_nav, 'phase')}",
                    f"wn_step   {int(world_nav.get('step_i') or 0) + 1}/"
                    f"{g(world_nav, 'steps_n')}  cost={g(world_nav, 'total_cost')}",
                    f"wn_reason {g(world_nav, 'reason')}",
                ]
            )
            for step in list(world_nav.get("steps") or [])[:8]:
                if not isinstance(step, dict):
                    continue
                mark = ">" if step.get("active") else ("*" if step.get("done") else " ")
                lines.append(
                    f"plan[{mark}]  {step.get('i')} {step.get('op')} "
                    f"{str(step.get('summary') or '')[:52]}"
                )
            if world_nav.get("error"):
                lines.append(f"wn_error  {world_nav.get('error')}")
        gate_warn = nav.get("gate_warn") if isinstance(nav.get("gate_warn"), dict) else None
        if gate_warn and gate_warn.get("message"):
            lines.append(
                f"GATE_WARN {gate_warn.get('from_map')}->{gate_warn.get('to_map')} "
                f"{gate_warn.get('message')}"
            )
        lines.extend(
            [
                f"purpose   {g(nav, 'travel_purpose')}",
                f"player    {g(nav, 'world_origin')}",
                f"blocked   {'YES' if blocked else 'no'}",
                f"hop       {g(nav, 'nav_waypoint')}",
                f"nav_goal  {g(nav, 'nav_goal')}",
                f"path_len  {g(nav, 'path_len')}",
                f"hop_on    {g(nav, 'travel_hop_active')}",
                f"unstick   {g(nav, 'travel_unstick_active')}",
                f"detour    {g(nav, 'enter_farm_detour')}",
                f"hp        {g(player, 'hp_text')}",
                f"mp        {g(player, 'mp_text')}",
            ]
        )
        return "\n".join(lines), blocked

    def _set_nav_blocked_banner(self, blocked: bool, origin: object = None) -> None:
        self._nav_blocked = bool(blocked)
        if blocked:
            text = self._tr(
                "debug_nav_blocked_warning",
                "WARNING: player is on a blocked (black) tile",
            )
            if origin is not None:
                text = f"{text}  @ {origin}"
            self.nav_blocked_banner.configure(text=text)
            self.nav_blocked_banner.grid(
                row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2)
            )
        else:
            self.nav_blocked_banner.grid_remove()

    def _set_nav_gate_warn_banner(self, gate_warn: object = None) -> None:
        warn = gate_warn if isinstance(gate_warn, dict) else None
        message = str((warn or {}).get("message") or "").strip()
        if not message:
            self.nav_gate_warn_banner.grid_remove()
            if self._nav_blocked:
                self.nav_blocked_banner.grid(
                    row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2)
                )
            return
        fm = warn.get("from_map")
        tm = warn.get("to_map")
        edge = str(warn.get("edge") or "").strip()
        prefix = self._tr(
            "debug_nav_gate_warning",
            "WARNING: gate transition failed (2 attempts)",
        )
        detail = message
        if fm is not None or tm is not None:
            detail = f"map {fm} → {tm}: {message}"
        if edge:
            detail = f"{detail}  [{edge}]"
        self.nav_gate_warn_banner.configure(text=f"{prefix} — {detail}")
        # Share row 1 with blocked banner: gate warning takes priority.
        self.nav_blocked_banner.grid_remove()
        self.nav_gate_warn_banner.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2)
        )

    def _refresh_nav_decision(self, snapshot: dict) -> None:
        decision = snapshot.get("decision") or {}
        nav = snapshot.get("navigation") or {}
        overview = snapshot.get("overview") or {}
        world_nav = nav.get("world_nav") if isinstance(nav.get("world_nav"), dict) else {}
        stamp = (
            snapshot.get("updated_at"),
            overview.get("state"),
            decision.get("mode"),
            decision.get("action"),
            decision.get("reason"),
            nav.get("live_map_id"),
            nav.get("live_origin_xy"),
            nav.get("origin_xy"),
            nav.get("nav_waypoint"),
            nav.get("nav_goal"),
            nav.get("path_len"),
            nav.get("travel_purpose"),
            world_nav.get("phase"),
            world_nav.get("step_i"),
            (nav.get("gate_warn") or {}).get("message")
            if isinstance(nav.get("gate_warn"), dict)
            else None,
        )
        if stamp == self._last_nav_decision_stamp:
            return
        self._last_nav_decision_stamp = stamp
        text, blocked = self._format_nav_decision(snapshot)
        self._set_nav_blocked_banner(
            blocked,
            nav.get("live_origin_xy") or nav.get("origin_xy") or nav.get("world_origin"),
        )
        self._set_nav_gate_warn_banner(nav.get("gate_warn"))
        widget = self.nav_decision_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        if blocked:
            widget.tag_add("warn", "1.0", "2.0")
        widget.configure(state="disabled")

    def _on_nav_render_done(self, seq: int, stamp: tuple, image, failed: bool) -> None:
        with self._nav_show_lock:
            if seq != self._nav_show_seq:
                return
            self._pending_nav_show = image
            self._pending_nav_stamp = stamp
            self._nav_show_fail = bool(failed)
            self._nav_show_busy = False
            if not failed:
                self._last_nav_map_stamp = stamp
        try:
            self.after(0, self._apply_pending_nav_show)
        except Exception:
            pass

    def _apply_pending_nav_show(self) -> None:
        with self._nav_show_lock:
            image = self._pending_nav_show
            failed = self._nav_show_fail
            stamp = self._pending_nav_stamp
            self._pending_nav_show = None
            self._nav_show_fail = False
            self._pending_nav_stamp = None
        if failed:
            self._nav_source = None
            self._nav_source_stamp = None
            self._nav_photo_key = None
            self.nav_show_canvas.delete("all")
            self.nav_show_canvas.create_text(
                max(8, self.nav_show_canvas.winfo_width() // 2),
                max(8, self.nav_show_canvas.winfo_height() // 2),
                text=self._tr("debug_nav_show_waiting"),
                fill="#d1d5db",
                anchor="center",
            )
            return
        if image is None:
            return
        self._nav_source = image
        self._nav_source_stamp = stamp
        if not self._nav_fit_done:
            self._nav_fit_to_view()
            self._nav_fit_done = True
        self._nav_redraw()

    def _nav_on_configure(self, _event: tk.Event | None = None) -> None:
        after_id = self._nav_configure_after
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        self._nav_configure_after = self.after(80, self._nav_redraw)

    def _nav_fit_to_view(self) -> None:
        src = self._nav_source
        if src is None:
            return
        cw = max(1, self.nav_show_canvas.winfo_width() or 640)
        ch = max(1, self.nav_show_canvas.winfo_height() or 400)
        sw, sh = src.size
        self._nav_zoom = max(0.05, min(cw / float(sw), ch / float(sh), 4.0))

    def _nav_reset_view(self) -> None:
        self._nav_fit_done = False
        self._nav_fit_to_view()
        self._nav_fit_done = True
        self._nav_redraw()
        try:
            self.nav_show_canvas.xview_moveto(0)
            self.nav_show_canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _nav_zoom_by(self, factor: float, *, anchor: tuple[int, int] | None = None) -> None:
        old = max(self._nav_zoom, 1e-6)
        new = min(8.0, max(0.1, old * float(factor)))
        if abs(new - old) < 1e-6:
            return
        canvas = self.nav_show_canvas
        src = self._nav_source
        if src is None:
            self._nav_zoom = new
            return
        if anchor is None:
            anchor = (
                max(1, canvas.winfo_width()) // 2,
                max(1, canvas.winfo_height()) // 2,
            )
        ax, ay = anchor
        wx = float(canvas.canvasx(ax)) / old
        wy = float(canvas.canvasy(ay)) / old
        self._nav_zoom = new
        self._nav_redraw()
        dw = max(1.0, src.size[0] * new)
        dh = max(1.0, src.size[1] * new)
        left = wx * new - ax
        top = wy * new - ay
        try:
            canvas.xview_moveto(max(0.0, min(1.0, left / dw)))
            canvas.yview_moveto(max(0.0, min(1.0, top / dh)))
        except tk.TclError:
            pass

    def _nav_on_wheel(self, event: tk.Event) -> None:
        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 0.8
        self._nav_zoom_by(factor, anchor=(int(event.x), int(event.y)))

    def _nav_on_wheel_linux(self, event: tk.Event) -> None:
        num = int(getattr(event, "num", 0) or 0)
        if num == 4:
            self._nav_zoom_by(1.25, anchor=(int(event.x), int(event.y)))
        elif num == 5:
            self._nav_zoom_by(0.8, anchor=(int(event.x), int(event.y)))

    def _nav_pan_start(self, event: tk.Event) -> None:
        self.nav_show_canvas.scan_mark(event.x, event.y)

    def _nav_pan_move(self, event: tk.Event) -> None:
        self.nav_show_canvas.scan_dragto(event.x, event.y, gain=1)

    def _nav_redraw(self) -> None:
        self._nav_configure_after = None
        canvas = self.nav_show_canvas
        src = self._nav_source
        if src is None:
            return
        try:
            from PIL import Image, ImageTk
        except Exception:
            return
        zoom = max(0.1, float(self._nav_zoom))
        sw, sh = src.size
        dw = max(1, int(round(sw * zoom)))
        dh = max(1, int(round(sh * zoom)))
        max_px = 4000
        if dw > max_px or dh > max_px:
            scale = min(max_px / float(dw), max_px / float(dh))
            dw = max(1, int(dw * scale))
            dh = max(1, int(dh * scale))
            zoom = dw / float(sw)
            self._nav_zoom = zoom
        key = (id(src), self._nav_source_stamp, dw, dh)
        if key == self._nav_photo_key and self._nav_photo is not None:
            self.nav_zoom_label.configure(text=f"{int(round(zoom * 100))}%")
            return
        try:
            resample = getattr(Image, "Resampling", Image).NEAREST
            shown = src if (dw, dh) == (sw, sh) else src.resize((dw, dh), resample)
            photo = ImageTk.PhotoImage(shown, master=self)
        except Exception:
            return
        self._nav_photo = photo
        self._nav_photo_key = key
        try:
            x_left = canvas.canvasx(0)
            y_top = canvas.canvasy(0)
        except tk.TclError:
            x_left, y_top = 0.0, 0.0
        canvas.delete("all")
        canvas.create_image(0, 0, image=photo, anchor="nw", tags=("map",))
        canvas.configure(scrollregion=(0, 0, dw, dh))
        try:
            if dw > 0:
                canvas.xview_moveto(max(0.0, min(1.0, float(x_left) / float(dw))))
            if dh > 0:
                canvas.yview_moveto(max(0.0, min(1.0, float(y_top) / float(dh))))
        except tk.TclError:
            pass
        self.nav_zoom_label.configure(text=f"{int(round(zoom * 100))}%")

    def _refresh_nav_show(self, snapshot: dict) -> None:
        self._apply_pending_nav_show()
        from session.nav_debug_view import nav_show_content_stamp

        stamp = nav_show_content_stamp(snapshot)
        map_id = str(stamp[0] if stamp else "")
        if (
            self._nav_source is not None
            and isinstance(self._last_nav_map_stamp, tuple)
            and self._last_nav_map_stamp
            and self._last_nav_map_stamp[0] != map_id
        ):
            # Live/profile map pack changed — drop stale canvas image immediately.
            self._nav_source = None
            self._nav_photo = None
            self._nav_photo_key = None
            self._nav_fit_done = False
            self._last_nav_map_stamp = None
        if stamp == self._last_nav_map_stamp and self._nav_source is not None:
            return
        if self._nav_show_busy:
            return
        self._nav_show_busy = True
        self._nav_show_seq += 1
        seq = self._nav_show_seq
        worker = self._ensure_nav_worker()
        worker.submit(
            seq=seq,
            snapshot=snapshot,
            stamp=stamp,
            on_done=self._on_nav_render_done,
        )

    def _refresh_preview(self) -> None:
        self._apply_pending_preview()
        if self._preview_busy:
            return
        data = self.controller.pop_preview_jpeg()
        if not data:
            return
        self._preview_busy = True
        self._preview_seq += 1
        seq = self._preview_seq
        max_w = max(320, self.preview_label.winfo_width() or 640)
        max_h = max(240, self.preview_label.winfo_height() or 400)

        def decode() -> None:
            image = None
            failed = False
            try:
                from PIL import Image

                decoded = Image.open(io.BytesIO(data)).convert("RGB")
                resample = getattr(Image, "Resampling", Image).BILINEAR
                decoded.thumbnail((max_w, max_h), resample)
                image = decoded
            except Exception:
                failed = True
            with self._preview_lock:
                if seq != self._preview_seq:
                    self._preview_busy = False
                    return
                self._pending_preview = image
                self._preview_fail = failed
                self._preview_busy = False
            # Paint as soon as decode finishes (nav_show already does this).
            try:
                self.after(0, self._apply_pending_preview)
            except tk.TclError:
                pass

        threading.Thread(target=decode, name="debug-preview-decode", daemon=True).start()

    def shutdown_nav_worker(self) -> None:
        worker = self._nav_worker
        self._nav_worker = None
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass

    def copy(self) -> None:
        snapshot = self.controller.debug_snapshot()
        text = section_text(self._section, snapshot, self.get_logs())
        if not text:
            text = self._tr("debug_no_data")
        self.winfo_toplevel().clipboard_clear()
        self.winfo_toplevel().clipboard_append(text)
        self.note_label.configure(text=self._tr("debug_copied"))


class DebugWindow(tk.Toplevel):
    """Companion panel on the schedule console — watches that console's bot run."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: BotController,
        get_logs: Callable[[], list[str]],
        t: dict[str, str],
        on_close: Callable[[], None] | None = None,
        get_arming: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(master)
        self.controller = controller
        self._on_close = on_close
        self._closing = False
        self.t = t
        self.title(t.get("debug_title", "Debug"))
        self.geometry("1180x700")
        self.minsize(900, 520)
        self.configure(background=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.controller.add_debug_watcher()
        top = ttk.Frame(self, padding=4, style="Chrome.TFrame")
        top.pack(fill="x")
        self.topmost_var = tk.BooleanVar(self, value=True)
        ttk.Checkbutton(
            top,
            text=t.get("always_on_top", "Always on top"),
            variable=self.topmost_var,
            command=lambda: self.attributes("-topmost", bool(self.topmost_var.get())),
        ).pack(side="right")
        self.panel = DebugPanel(
            self,
            controller=controller,
            get_logs=get_logs,
            t=t,
            get_arming=get_arming,
            note_text=t.get("debug_same_run", "Same live run as the operator console."),
        )
        self.panel.pack(fill="both", expand=True)
        self.attributes("-topmost", True)
        self._poll_after = self.after(50, self._poll)

    def _poll(self) -> None:
        if self._closing or not self.winfo_exists():
            return
        self.panel.refresh()
        delay = 50 if self.panel._section == "preview" else 200
        self._poll_after = self.after(delay, self._poll)

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        after_id = getattr(self, "_poll_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        try:
            self.panel.shutdown_nav_worker()
        except Exception:
            pass
        try:
            self.panel._set_previewing(False)
        except Exception:
            pass
        try:
            self.controller.remove_debug_watcher()
        except Exception:
            pass
        callback = self._on_close
        self.destroy()
        if callback is not None:
            callback()


class DebugPlayer(tk.Tk):
    """Independent bot player for debugging (separate from the schedule console)."""

    def __init__(self, profile: Profile | None = None) -> None:
        super().__init__()
        ensure_userdata()
        self.profile = profile or load_profile()
        self.language = ui_language(self.profile.language)
        self.profile.language = self.language
        load_bundled_fonts(self.language)
        self.t = tr(self.language)
        self._log_lines: list[str] = []
        self._closing = False
        apply_classic_style(self, self.language)
        global FONT_BODY
        FONT_BODY = ui_theme.FONT_BODY
        self.title(self.t.get("debug_player_title", "ZF"))
        self.geometry("1100x720")
        self.minsize(860, 540)
        self.configure(background=BG)
        self.attributes("-topmost", True)
        self._apply_brand_icon()
        self.coordinator = OperatorCoordinator(
            self.profile,
            dispatch=lambda fn: self.after(0, fn),
            on_change=self._on_operator_change,
            on_log=self.append_log,
            on_hotbar=self._on_hotbar,
        )
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self.coordinator.controller.add_debug_watcher()
        self._last_controls_t = 0.0
        self._refresh_controls()
        self._poll_after = self.after(50, self._poll)

    def _tr(self, key: str, fallback: str | None = None) -> str:
        return self.t.get(key, fallback or key)

    def _apply_brand_icon(self) -> None:
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

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")

        self.game_lamp = ttk.Label(header, style="Chrome.TLabel")
        self.memory_lamp = ttk.Label(header, style="Chrome.TLabel")
        self.map_lamp = ttk.Label(header, style="Chrome.TLabel")
        for widget in (self.game_lamp, self.memory_lamp, self.map_lamp):
            widget.pack(side="left", padx=(0, 12))

        self.start_btn = ttk.Button(header, text=self._tr("start"), command=self._start)
        self.resume_btn = ttk.Button(
            header, text=self._tr("resume"), command=self.coordinator.resume
        )
        self.stop_btn = ttk.Button(
            header, text=self._tr("stop"), command=self.coordinator.stop
        )
        for button in (self.stop_btn, self.resume_btn, self.start_btn):
            button.pack(side="right", padx=2)

        self.topmost_var = tk.BooleanVar(self, value=True)
        ttk.Checkbutton(
            header,
            text=self._tr("always_on_top"),
            variable=self.topmost_var,
            command=lambda: self.attributes("-topmost", bool(self.topmost_var.get())),
        ).pack(side="right", padx=6)

        self.panel = DebugPanel(
            self,
            controller=self.coordinator.controller,
            get_logs=lambda: list(self._log_lines),
            t=self.t,
            get_arming=lambda: self.coordinator.arming,
            note_text=self._tr("debug_player_hint"),
        )
        self.panel.pack(fill="both", expand=True)

    def _start(self) -> None:
        error = self.coordinator.start()
        if error:
            messagebox.showwarning(
                self._tr("cannot_start"),
                self.t.get(error, error),
                parent=self,
            )
        self._refresh_controls()

    def _on_hotbar(self, layout: dict, slots: dict) -> None:
        from settings.spell_defaults import spell_slot_bindings

        self.profile.hotbar_layout = dict(layout)
        self.profile.spell_slots = spell_slot_bindings(slots)
        try:
            save_profile(self.profile)
        except Exception:
            pass

    def append_log(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {message}"
        self._log_lines = (self._log_lines + [line])[-500:]

        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with (LOG_DIR / "v1-debug.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass

        def update() -> None:
            if self.panel._section == "logs":
                self.panel.refresh(force=True)

        try:
            self.after(0, update)
        except tk.TclError:
            pass

    def _on_operator_change(self) -> None:
        self._refresh_controls()
        self.panel.refresh(force=True)

    def _refresh_controls(self) -> None:
        try:
            game, memory, map_probe = self.coordinator.probes()

            def lamp(label, result) -> None:
                mark = (
                    "●"
                    if result.lamp == Lamp.GREEN
                    else ("◐" if result.lamp == Lamp.AMBER else "○")
                )
                label.configure(
                    text=f"{mark} {localize_probe_detail(result.detail, self.language)}"
                )

            lamp(self.game_lamp, game)
            lamp(self.memory_lamp, memory)
            lamp(self.map_lamp, map_probe)
        except Exception:
            pass
        state = self.coordinator.controller.state
        arming = self.coordinator.arming
        self.start_btn.configure(
            state="normal" if state == RunState.STOPPED and not arming else "disabled"
        )
        self.resume_btn.configure(
            state="normal" if state == RunState.PAUSED else "disabled"
        )
        self.stop_btn.configure(
            state="normal" if state != RunState.STOPPED or arming else "disabled"
        )

    def _poll(self) -> None:
        if self._closing:
            return
        import time

        now = time.monotonic()
        self.coordinator.poll()
        if now - self._last_controls_t >= 0.25:
            self._refresh_controls()
            self._last_controls_t = now
        self.panel.refresh()
        delay = 50 if self.panel._section == "preview" else 200
        self._poll_after = self.after(delay, self._poll)

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        after_id = getattr(self, "_poll_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        try:
            self.panel.shutdown_nav_worker()
        except Exception:
            pass
        try:
            self.panel._set_previewing(False)
        except Exception:
            pass
        try:
            self.coordinator.controller.remove_debug_watcher()
        except Exception:
            pass
        self.coordinator.close()
        self.destroy()


def run_debug_player() -> int:
    app = DebugPlayer()
    app.mainloop()
    return 0
