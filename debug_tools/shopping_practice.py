"""GUI shopping practice panel — behaviors + live shop list editor."""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from debug_tools.bootstrap import bootstrap

bootstrap()

# Loads practice_calibrated_behavior used by shopping_catalog.run_practice.
import debug_tools.shopping_methods  # noqa: F401

from debug_tools.shopping_behavior_editor import ShoppingBehaviorEditor
from debug_tools.shopping_catalog import (
    PracticeEntry,
    run_practice,
    shopping_catalog,
)
from debug_tools.shopping_sell_editor import ShoppingSellEditor
from manmabot_v1.ui.design_system import TEXT_MUTED, apply_classic_style


def _is_elevated() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated() -> bool:
    """Relaunch this entry script with UAC. Returns True if launch was requested."""
    if os.name != "nt":
        return False
    try:
        from debug_tools.elevate_shopping_practice import main as elevate_main

        return elevate_main() == 0
    except Exception:
        try:
            import ctypes

            script = Path(__file__).resolve().parents[0] / "run_shopping_practice.py"
            py = Path(sys.executable).resolve()
            cwd = str(Path(__file__).resolve().parents[1])
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(py),
                f'"{script}"',
                cwd,
                1,
            )
            return int(rc) > 32
        except Exception:
            return False


class ShoppingPracticeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        elevated = _is_elevated()
        self.title(
            "Shopping Practice (Administrator)"
            if elevated
            else "Shopping Practice"
        )
        self.geometry("1100x720")
        self.minsize(900, 560)
        apply_classic_style(self)

        self._behaviors = shopping_catalog()
        self._by_iid: dict[str, PracticeEntry] = {}
        self._selected: PracticeEntry | None = None
        self._busy = False
        self._closing = False
        self._elevated = elevated

        self.status_var = tk.StringVar(self, value="Select a shopping behavior")
        self.title_var = tk.StringVar(self, value="")
        self.category_var = tk.StringVar(self, value="")
        self.status_badge_var = tk.StringVar(self, value="")
        self.desc_var = tk.StringVar(self, value="")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if not elevated:
            self.after(200, self._warn_elevation)
        if self._behaviors:
            first = self._behaviors[0].id
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._on_select()

    def _warn_elevation(self) -> None:
        self._append_log(
            "Not running as Administrator — memory pipe will return WinError 5 "
            "while realtime_monitor_full.exe is elevated. Use Relaunch as Admin."
        )
        self.status_var.set("Need Administrator to use memory pipe")

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Shopping Practice",
            style="Chrome.TLabel",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        elev_note = (
            "Admin · memory pipe OK"
            if self._elevated
            else "Not admin · memory pipe blocked (WinError 5)"
        )
        ttk.Label(
            header,
            text=elev_note,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=12)

        self.run_btn = ttk.Button(
            header, text="Run Practice", command=self.run_selected
        )
        self.run_btn.pack(side="right", padx=2)
        if not self._elevated:
            ttk.Button(
                header, text="Relaunch as Admin", command=self._on_relaunch_admin
            ).pack(side="right", padx=2)
        ttk.Button(header, text="Clear log", command=self._clear_log).pack(
            side="right", padx=2
        )

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        practice = ttk.Frame(self.notebook, padding=4)
        behaviors_tab = ttk.Frame(self.notebook, padding=4)
        sell_tab = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(practice, text="Practice")
        self.notebook.add(behaviors_tab, text="Behaviors")
        self.notebook.add(sell_tab, text="Sell")

        body = ttk.Panedwindow(practice, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=4)
        right = ttk.Frame(body, padding=4)
        body.add(left, weight=2)
        body.add(right, weight=3)

        catalog_box = ttk.LabelFrame(left, text="Behavior catalog", padding=(6, 4))
        catalog_box.pack(fill="both", expand=True)
        cols = ("title", "category", "status")
        self.tree = ttk.Treeview(
            catalog_box,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=16,
        )
        self.tree.heading("title", text="Behavior")
        self.tree.heading("category", text="Category")
        self.tree.heading("status", text="Status")
        self.tree.column("title", width=180, anchor="w")
        self.tree.column("category", width=70, anchor="center")
        self.tree.column("status", width=60, anchor="center")
        scroll = ttk.Scrollbar(
            catalog_box, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self.run_selected())

        for behavior in self._behaviors:
            self._by_iid[behavior.id] = behavior
            self.tree.insert(
                "",
                "end",
                iid=behavior.id,
                values=(behavior.title, behavior.category, behavior.status),
            )

        detail = ttk.LabelFrame(right, text="Detail", padding=(8, 6))
        detail.pack(fill="x")
        ttk.Label(
            detail,
            textvariable=self.title_var,
            style="Chrome.TLabel",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        meta = ttk.Frame(detail, style="Chrome.TFrame")
        meta.pack(fill="x", pady=(4, 6))
        ttk.Label(meta, text="Category:", style="Chrome.TLabel").pack(side="left")
        ttk.Label(meta, textvariable=self.category_var, style="Chrome.TLabel").pack(
            side="left", padx=(4, 16)
        )
        ttk.Label(meta, text="Status:", style="Chrome.TLabel").pack(side="left")
        ttk.Label(
            meta, textvariable=self.status_badge_var, style="Chrome.TLabel"
        ).pack(side="left", padx=4)
        ttk.Label(
            detail,
            textvariable=self.desc_var,
            style="Chrome.TLabel",
            wraplength=420,
            justify="left",
            foreground=TEXT_MUTED,
        ).pack(anchor="w", fill="x")

        log_box = ttk.LabelFrame(right, text="Log", padding=(6, 4))
        log_box.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(
            log_box,
            height=12,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
        )
        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.behavior_editor = ShoppingBehaviorEditor(
            behaviors_tab,
            on_log=self._append_log,
            on_saved=self._on_behaviors_saved,
            get_sell_filters=lambda: self.sell_editor.read_filters(),
        )
        self.behavior_editor.pack(fill="both", expand=True)

        self.sell_editor = ShoppingSellEditor(
            sell_tab,
            on_log=self._append_log,
            on_saved=self._on_sell_saved,
            get_behaviors=lambda: self.behavior_editor.current_behaviors(),
        )
        self.sell_editor.pack(fill="both", expand=True)

        footer = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )

    def _on_behaviors_saved(self) -> None:
        self._append_log("Behaviors saved to userdata/shopping_behaviors.yaml")
        self._reload_practice_catalog(keep_id=getattr(self._selected, "id", None))

    def _on_sell_saved(self) -> None:
        self._append_log("Sell lists saved to userdata/shopping_behaviors.yaml")
        self._reload_practice_catalog(keep_id=getattr(self._selected, "id", None))

    def _reload_practice_catalog(self, keep_id: str | None = None) -> None:
        """Refresh Practice list from userdata (after Behaviors save / tab switch)."""
        prev = keep_id
        self._behaviors = shopping_catalog()
        self._by_iid = {}
        self.tree.delete(*self.tree.get_children())
        for behavior in self._behaviors:
            self._by_iid[behavior.id] = behavior
            self.tree.insert(
                "",
                "end",
                iid=behavior.id,
                values=(behavior.title, behavior.category, behavior.status),
            )
        pick = prev if prev in self._by_iid else (
            self._behaviors[0].id if self._behaviors else None
        )
        if pick:
            self.tree.selection_set(pick)
            self.tree.focus(pick)
            self._on_select()
        else:
            self._selected = None
            self.run_btn.configure(state="disabled")

    def _on_tab_changed(self, _event=None) -> None:
        try:
            tab = self.notebook.tab(self.notebook.select(), "text")
        except Exception:
            return
        if tab == "Behaviors":
            self.run_btn.configure(state="disabled")
            self.status_var.set(
                "Behaviors · edit travel + capture-calibrate dialog UVs · Save to persist"
            )
            return
        if tab == "Sell":
            self.run_btn.configure(state="disabled")
            self.status_var.set(
                "Sell · Filters (garbage/keep) · Slot positions (template regions)"
            )
            return
        # Practice: flush editors; warn if still not on disk.
        editor = getattr(self, "behavior_editor", None)
        if editor is not None:
            editor.flush_pending_form()
            if editor.has_unsaved_changes():
                self._append_log(
                    "Behaviors have unsaved changes — open Behaviors and click Save"
                )
        sell = getattr(self, "sell_editor", None)
        if sell is not None and sell.has_unsaved_changes():
            self._append_log(
                "Sell lists have unsaved changes — open Sell and click Save"
            )
        self._reload_practice_catalog(
            keep_id=getattr(self._selected, "id", None)
        )
        if self._selected is not None and not self._busy:
            self.run_btn.configure(state="normal")
        self.status_var.set(
            f"Selected · {self._selected.id}"
            if self._selected
            else "Select a shopping behavior"
        )

    def _on_relaunch_admin(self) -> None:
        if _relaunch_elevated():
            self._append_log("Relaunching elevated — accept the UAC prompt")
            self.after(400, self.destroy)
        else:
            messagebox.showwarning(
                "Shopping Practice",
                "Could not request elevation. Use "
                "“Start Shopping Practice (Admin).bat”.",
                parent=self,
            )

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self._selected = None
            self.title_var.set("")
            self.category_var.set("")
            self.status_badge_var.set("")
            self.desc_var.set("")
            self.status_var.set("Select a shopping behavior")
            self.run_btn.configure(state="disabled")
            return
        behavior = self._by_iid.get(sel[0])
        self._selected = behavior
        if behavior is None:
            return
        self.title_var.set(behavior.title)
        self.category_var.set(behavior.category)
        self.status_badge_var.set(behavior.status)
        self.desc_var.set(behavior.description)
        self.status_var.set(f"Selected · {behavior.id}")
        if not self._busy:
            self.run_btn.configure(state="normal")
        self._append_log(f"selected {behavior.id}")

    def run_selected(self) -> None:
        if self._busy or self._selected is None or self._closing:
            return
        try:
            if self.notebook.tab(self.notebook.select(), "text") != "Practice":
                self.notebook.select(0)
        except Exception:
            pass
        behavior = self._selected
        self._busy = True
        self.run_btn.configure(state="disabled")
        self.status_var.set(f"Running practice · {behavior.id}")
        self._append_log(f"Run Practice · {behavior.id}")

        def worker() -> None:
            try:
                result = run_practice(behavior.id)
                message = result.message
                ok = result.ok
            except Exception as exc:
                message = f"practice {behavior.id} failed: {exc}"
                ok = False

            def done() -> None:
                self._busy = False
                if self._closing:
                    return
                self._append_log(message)
                self.status_var.set(message)
                if self._selected is not None:
                    self.run_btn.configure(state="normal")
                if ok:
                    self._append_log("done")

            self.after(0, done)

        threading.Thread(
            target=worker, name=f"shop-practice-{behavior.id}", daemon=True
        ).start()

    def _append_log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {line}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self._closing = True
        self.destroy()


def run_shopping_practice() -> int:
    app = ShoppingPracticeApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_shopping_practice())
