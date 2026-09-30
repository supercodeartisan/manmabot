"""Debug inspector panel and standalone debug bot player."""
from __future__ import annotations

import io
import threading
import tkinter as tk
from datetime import datetime
from typing import Callable
from tkinter import messagebox, ttk

from manmabot_v1.bot_controller import BotController, RunState
from manmabot_v1.debug_snapshot import (
    STATUS_SECTIONS,
    columns_for_section,
    rows_for_section,
    section_text,
)
from manmabot_v1.map_previews import brand_icon_path
from manmabot_v1.paths import LOG_DIR, USERDATA, ensure_userdata
from manmabot_v1.probes import Lamp, localize_probe_detail
from manmabot_v1.profile import Profile, load_profile, save_profile
from manmabot_v1.ui.design_system import (
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
from manmabot_v1.ui import design_system as ui_theme
from manmabot_v1.ui.fonts import load_bundled_fonts
from manmabot_v1.ui.operator_coordinator import OperatorCoordinator
from manmabot_v1.ui.schedule_i18n import tr


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

        threading.Thread(target=decode, name="debug-preview-decode", daemon=True).start()

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
        self.title(t.get("debug_title", "Bot debug"))
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
        self.language = (
            self.profile.language if self.profile.language in ("en", "ko", "zh") else "en"
        )
        load_bundled_fonts(self.language)
        self.t = tr(self.language)
        self._log_lines: list[str] = []
        self._closing = False
        apply_classic_style(self, self.language)
        global FONT_BODY
        FONT_BODY = ui_theme.FONT_BODY
        self.title(self.t.get("debug_player_title", "Manmabot debug player"))
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
        self.profile.hotbar_layout = dict(layout)
        self.profile.spell_slots = dict(slots)
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
