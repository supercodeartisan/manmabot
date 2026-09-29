"""Shared sell filters editor — mark template items as garbage or keep."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from debug_tools.shopping_sell_slot_calibrator import ShoppingSellSlotCalibrator
from manmabot_v1.hotbar.item_catalog import (
    ItemTemplateEntry,
    list_item_categories,
    list_item_templates,
)
from manmabot_v1.shopping.behaviors import (
    ShoppingSellFilters,
    behaviors_path,
    load_behaviors,
    load_sell_filters,
    save_behaviors,
)
from manmabot_v1.ui.design_system import TEXT_MUTED

_MARK_NONE = ""
_MARK_GARBAGE = "garbage"
_MARK_KEEP = "keep"
_MARK_CYCLE = (_MARK_NONE, _MARK_GARBAGE, _MARK_KEEP)

_MARK_LABEL = {
    _MARK_NONE: "—",
    _MARK_GARBAGE: "garbage",
    _MARK_KEEP: "keep",
}


class ShoppingSellEditor(ttk.Frame):
    """Sell tab: item garbage/keep marks + sell-list slot region calibrator."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_log: Optional[Callable[[str], None]] = None,
        on_saved: Optional[Callable[[], None]] = None,
        get_behaviors: Optional[Callable[[], list]] = None,
    ) -> None:
        super().__init__(master, padding=4)
        self._on_log = on_log or (lambda _m: None)
        self._on_saved = on_saved or (lambda: None)
        self._get_behaviors = get_behaviors
        self._dirty = False
        self._catalog: list[ItemTemplateEntry] = []
        self._marks: dict[str, str] = {}
        self._iid_to_name: dict[str, str] = {}
        self.path_var = tk.StringVar(self, value=str(behaviors_path()))
        self.status_var = tk.StringVar(self, value="")
        self.search_var = tk.StringVar(self, value="")
        self.category_var = tk.StringVar(self, value="(all)")
        self.show_var = tk.StringVar(self, value="all")
        self.count_var = tk.StringVar(self, value="")
        self._tree: ttk.Treeview | None = None
        self._filters_frame: ttk.Frame | None = None
        self.slot_calibrator: ShoppingSellSlotCalibrator | None = None
        self._build()
        self.reload_from_disk()

    def _log(self, message: str) -> None:
        self._on_log(message)
        self.status_var.set(message)

    def _build(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        filters = ttk.Frame(nb, padding=4)
        slots = ttk.Frame(nb, padding=4)
        nb.add(filters, text="Filters")
        nb.add(slots, text="Slot positions")
        self._filters_frame = filters

        self._build_filters(filters)

        self.slot_calibrator = ShoppingSellSlotCalibrator(slots, on_log=self._on_log)
        self.slot_calibrator.pack(fill="both", expand=True)

    def _build_filters(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Chrome.TFrame")
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top,
            text="Mark items from shopping_slots · shared by every sell behavior",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left")
        ttk.Label(
            top, textvariable=self.path_var, style="Chrome.TLabel", foreground=TEXT_MUTED
        ).pack(side="right")

        filter_bar = ttk.Frame(parent, style="Chrome.TFrame")
        filter_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_bar, text="Search", style="Chrome.TLabel").pack(
            side="left", padx=(0, 4)
        )
        search = ttk.Entry(filter_bar, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=(0, 10))
        search.bind("<KeyRelease>", lambda _e: self._refresh_tree())
        ttk.Label(filter_bar, text="Category", style="Chrome.TLabel").pack(
            side="left", padx=(0, 4)
        )
        self._category_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.category_var,
            values=["(all)"],
            state="readonly",
            width=16,
        )
        self._category_combo.pack(side="left", padx=(0, 10))
        self._category_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_tree()
        )
        ttk.Label(filter_bar, text="Show", style="Chrome.TLabel").pack(
            side="left", padx=(0, 4)
        )
        show = ttk.Combobox(
            filter_bar,
            textvariable=self.show_var,
            values=("all", "garbage", "keep", "unmarked"),
            state="readonly",
            width=10,
        )
        show.pack(side="left", padx=(0, 10))
        show.bind("<<ComboboxSelected>>", lambda _e: self._refresh_tree())
        ttk.Label(
            filter_bar,
            textvariable=self.count_var,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=6)

        body = ttk.LabelFrame(parent, text="shopping_slots templates", padding=(6, 4))
        body.pack(fill="both", expand=True)
        cols = ("mark", "category", "name", "zh")
        self._tree = ttk.Treeview(
            body,
            columns=cols,
            show="headings",
            selectmode="extended",
            height=18,
        )
        self._tree.heading("mark", text="Mark")
        self._tree.heading("category", text="Category")
        self._tree.heading("name", text="Item (KR)")
        self._tree.heading("zh", text="ZH")
        self._tree.column("mark", width=70, anchor="center", stretch=False)
        self._tree.column("category", width=100, anchor="w", stretch=False)
        self._tree.column("name", width=220, anchor="w")
        self._tree.column("zh", width=160, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<space>", self._on_space_cycle)
        self._tree.tag_configure("garbage", foreground="#a04000")
        self._tree.tag_configure("keep", foreground="#006060")

        actions = ttk.Frame(parent, style="Chrome.TFrame")
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(
            actions, text="Mark garbage", command=lambda: self._mark_selected(_MARK_GARBAGE)
        ).pack(side="left", padx=2)
        ttk.Button(
            actions, text="Mark keep", command=lambda: self._mark_selected(_MARK_KEEP)
        ).pack(side="left", padx=2)
        ttk.Button(
            actions, text="Clear mark", command=lambda: self._mark_selected(_MARK_NONE)
        ).pack(side="left", padx=2)
        ttk.Label(
            actions,
            text="Double-click or Space cycles — / garbage / keep",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=12)

        bar = ttk.Frame(parent, style="Chrome.TFrame")
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Reload", command=self.reload_from_disk).pack(
            side="right", padx=2
        )
        ttk.Button(bar, text="Save", command=self.save_to_disk).pack(
            side="right", padx=2
        )
        ttk.Label(bar, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )

    def _load_catalog(self) -> None:
        self._catalog = list(list_item_templates(pack="sell"))
        cats = ["(all)"] + list_item_categories(pack="sell")
        self._category_combo.configure(values=cats)
        if self.category_var.get() not in cats:
            self.category_var.set("(all)")

    def _visible_entries(self) -> list[ItemTemplateEntry | tuple[str, str]]:
        """Catalog rows plus orphan saved names as (category, kr_name) tuples."""
        needle = self.search_var.get().strip().lower()
        cat = self.category_var.get().strip()
        show = self.show_var.get().strip().lower()
        catalog_names = {e.kr_name for e in self._catalog}

        def mark_ok(name: str) -> bool:
            mark = self._marks.get(name, _MARK_NONE)
            if show == "garbage":
                return mark == _MARK_GARBAGE
            if show == "keep":
                return mark == _MARK_KEEP
            if show == "unmarked":
                return mark == _MARK_NONE
            return True

        def text_ok(name: str, zh: str, category: str) -> bool:
            if cat not in ("", "(all)") and category != cat:
                return False
            if not needle:
                return True
            blob = f"{name} {zh} {category}".lower()
            return needle in blob

        rows: list[ItemTemplateEntry | tuple[str, str]] = []
        for entry in self._catalog:
            if not mark_ok(entry.kr_name):
                continue
            if not text_ok(entry.kr_name, entry.zh_name, entry.category):
                continue
            rows.append(entry)

        # Names saved in yaml but missing from the icon pack.
        orphans = [
            n
            for n in sorted(self._marks)
            if n not in catalog_names and self._marks.get(n)
        ]
        for name in orphans:
            if not mark_ok(name):
                continue
            if cat not in ("", "(all)", "(saved)"):
                continue
            if not text_ok(name, "", "(saved)"):
                continue
            rows.append(("(saved)", name))
        return rows

    def _refresh_tree(self) -> None:
        tree = self._tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        self._iid_to_name.clear()
        for i, row in enumerate(self._visible_entries()):
            if isinstance(row, ItemTemplateEntry):
                name = row.kr_name
                category = row.category
                zh = row.zh_name
            else:
                category, name = row
                zh = ""
            mark = self._marks.get(name, _MARK_NONE)
            iid = str(i)
            self._iid_to_name[iid] = name
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(_MARK_LABEL.get(mark, "—"), category, name, zh),
                tags=(mark,) if mark else (),
            )
        g = sum(1 for m in self._marks.values() if m == _MARK_GARBAGE)
        k = sum(1 for m in self._marks.values() if m == _MARK_KEEP)
        self.count_var.set(
            f"showing {len(self._iid_to_name)} / {len(self._catalog)} · "
            f"garbage={g} · keep={k}"
        )

    def _selected_names(self) -> list[str]:
        tree = self._tree
        if tree is None:
            return []
        names: list[str] = []
        for iid in tree.selection():
            name = self._iid_to_name.get(iid)
            if name:
                names.append(name)
        return names

    def _mark_selected(self, mark: str) -> None:
        names = self._selected_names()
        if not names:
            return
        for name in names:
            if mark == _MARK_NONE:
                self._marks.pop(name, None)
            else:
                self._marks[name] = mark
        self._dirty = True
        self._refresh_tree()
        # Reselect by name after rebuild.
        tree = self._tree
        if tree is None:
            return
        want = set(names)
        pick = [iid for iid, n in self._iid_to_name.items() if n in want]
        if pick:
            tree.selection_set(pick)
            tree.focus(pick[0])
            tree.see(pick[0])

    def _cycle_names(self, names: list[str]) -> None:
        if not names:
            return
        for name in names:
            cur = self._marks.get(name, _MARK_NONE)
            try:
                idx = _MARK_CYCLE.index(cur)
            except ValueError:
                idx = 0
            nxt = _MARK_CYCLE[(idx + 1) % len(_MARK_CYCLE)]
            if nxt == _MARK_NONE:
                self._marks.pop(name, None)
            else:
                self._marks[name] = nxt
        self._dirty = True
        self._refresh_tree()
        tree = self._tree
        if tree is None:
            return
        want = set(names)
        pick = [iid for iid, n in self._iid_to_name.items() if n in want]
        if pick:
            tree.selection_set(pick)
            tree.focus(pick[0])

    def _on_double_click(self, _event=None) -> None:
        self._cycle_names(self._selected_names())

    def _on_space_cycle(self, _event=None) -> None:
        self._cycle_names(self._selected_names())
        return "break"

    def read_filters(self) -> ShoppingSellFilters:
        garbage = tuple(
            n for n, m in sorted(self._marks.items()) if m == _MARK_GARBAGE
        )
        keep = tuple(n for n, m in sorted(self._marks.items()) if m == _MARK_KEEP)
        return ShoppingSellFilters(garbage_list=garbage, keep_list=keep)

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty)

    def reload_from_disk(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                "Sell",
                "You have unsaved list edits. Reload and discard them?",
                parent=self.winfo_toplevel(),
            ):
                return
        try:
            filters = load_sell_filters()
            self._load_catalog()
        except Exception as exc:
            messagebox.showerror("Sell", str(exc), parent=self.winfo_toplevel())
            self._log(f"sell reload failed: {exc}")
            return
        self._marks = {}
        for name in filters.garbage_list:
            self._marks[str(name)] = _MARK_GARBAGE
        for name in filters.keep_list:
            # Keep wins if both somehow listed.
            self._marks[str(name)] = _MARK_KEEP
        self._dirty = False
        self.path_var.set(str(behaviors_path()))
        self._refresh_tree()
        self._log(
            f"Loaded {len(self._catalog)} shopping_slots templates · "
            f"garbage={len(filters.garbage_list)} · keep={len(filters.keep_list)}"
        )

    def save_to_disk(self) -> None:
        try:
            if self._get_behaviors is not None:
                behaviors = list(self._get_behaviors())
            else:
                behaviors = list(load_behaviors())
            filters = self.read_filters()
            path = save_behaviors(behaviors, sell_filters=filters)
            self._dirty = False
            self._log(
                f"Saved sell lists · garbage={len(filters.garbage_list)} · "
                f"keep={len(filters.keep_list)} → {path}"
            )
            self._on_saved()
        except Exception as exc:
            messagebox.showerror(
                "Sell",
                f"Save failed:\n{exc}",
                parent=self.winfo_toplevel(),
            )
            self._log(f"sell save failed: {exc}")
