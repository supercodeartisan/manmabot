"""Browse shop-sell (or hotbar) item templates — replace existing or save as new."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Optional

from manmabot_v1.hotbar.item_catalog import (
    ItemTemplateEntry,
    PackName,
    list_item_categories,
    list_item_templates,
    new_item_template_rel,
)
from manmabot_v1.ui.design_system import TEXT_MUTED


@dataclass(frozen=True)
class TemplateBrowseResult:
    """Existing catalog entry, or a new items/<category>/<name>.png target."""

    entry: ItemTemplateEntry
    is_new: bool = False


class TemplateBrowseDialog(tk.Toplevel):
    """Modal catalog picker — replace selected, or save as a new template file."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str = "Save slot crop to template",
        initial_search: str = "",
        prefer_garbage: bool = False,
        default_category: str = "other",
        pack: PackName = "sell",
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.resizable(True, True)
        self.geometry("620x560")
        self.result: Optional[TemplateBrowseResult] = None
        self._pack: PackName = pack

        self._catalog = list(list_item_templates(pack=pack))
        self._iid_to_entry: dict[str, ItemTemplateEntry] = {}
        cats = list_item_categories(pack=pack)
        if default_category and default_category not in cats:
            cats = [default_category] + cats
        self.search_var = tk.StringVar(self, value=initial_search)
        self.category_var = tk.StringVar(self, value="(all)")
        self.show_var = tk.StringVar(
            self, value="garbage" if prefer_garbage else "all"
        )
        self.new_category_var = tk.StringVar(
            self,
            value=(
                default_category
                if default_category in (cats or [default_category])
                else (cats[0] if cats else "other")
            ),
        )
        self.new_name_var = tk.StringVar(self, value=initial_search)

        pack_label = "shopping_slots" if pack == "sell" else "icons_unique"

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)

        filters = ttk.Frame(body)
        filters.pack(fill="x", pady=(0, 6))
        ttk.Label(filters, text="Search").pack(side="left", padx=(0, 4))
        search = ttk.Entry(filters, textvariable=self.search_var, width=22)
        search.pack(side="left", padx=(0, 8))
        search.bind("<KeyRelease>", lambda _e: self._refresh())
        ttk.Label(filters, text="Category").pack(side="left", padx=(0, 4))
        self._cat_combo = ttk.Combobox(
            filters,
            textvariable=self.category_var,
            values=["(all)"] + cats,
            state="readonly",
            width=14,
        )
        self._cat_combo.pack(side="left", padx=(0, 8))
        self._cat_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        ttk.Label(filters, text="Show").pack(side="left", padx=(0, 4))
        show = ttk.Combobox(
            filters,
            textvariable=self.show_var,
            values=("all", "garbage", "keep"),
            state="readonly",
            width=10,
        )
        show.pack(side="left")
        show.bind("<<ComboboxSelected>>", lambda _e: self._refresh())

        ttk.Label(
            body,
            text=(
                f"Pack: {pack_label}/items · Replace: select a row · "
                "New: fill category + name below."
            ),
            foreground=TEXT_MUTED,
        ).pack(anchor="w")

        tree_frame = ttk.Frame(body)
        tree_frame.pack(fill="both", expand=True, pady=6)
        cols = ("category", "name", "zh", "path")
        self.tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="browse", height=14
        )
        self.tree.heading("category", text="Category")
        self.tree.heading("name", text="Item (KR)")
        self.tree.heading("zh", text="ZH")
        self.tree.heading("path", text="Template")
        self.tree.column("category", width=90, stretch=False)
        self.tree.column("name", width=160)
        self.tree.column("zh", width=120)
        self.tree.column("path", width=200)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._accept_replace())
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        new_box = ttk.LabelFrame(body, text="Save as new template", padding=(8, 4))
        new_box.pack(fill="x", pady=(4, 0))
        row = ttk.Frame(new_box)
        row.pack(fill="x")
        ttk.Label(row, text="Category").pack(side="left", padx=(0, 4))
        self._new_cat_combo = ttk.Combobox(
            row,
            textvariable=self.new_category_var,
            values=cats or ["other"],
            width=14,
        )
        self._new_cat_combo.pack(side="left", padx=(0, 8))
        ttk.Label(row, text="Item name (KR)").pack(side="left", padx=(0, 4))
        self._new_name_entry = ttk.Entry(row, textvariable=self.new_name_var, width=28)
        self._new_name_entry.pack(side="left", padx=(0, 8))
        ttk.Label(
            new_box,
            text=f"Creates {pack_label}/items/<category>/<name>.png  (weapon · armor · supply · book · other)",
            foreground=TEXT_MUTED,
        ).pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=self._cancel).pack(side="right", padx=2)
        ttk.Button(bar, text="Replace selected", command=self._accept_replace).pack(
            side="right", padx=2
        )
        # Default action: Save as new (Enter / focused name field).
        self._btn_save_new = ttk.Button(bar, text="Save as new", command=self._accept_new)
        self._btn_save_new.pack(side="right", padx=2)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._accept_new())
        self._refresh()
        self._new_name_entry.focus_set()
        self.wait_window(self)

    def _filter_names(self) -> set[str] | None:
        """None = all; else allowlist from sell filters."""
        show = self.show_var.get().strip().lower()
        if show == "all":
            return None
        try:
            from manmabot_v1.shopping.behaviors import load_sell_filters

            filters = load_sell_filters()
        except Exception:
            return set()
        if show == "garbage":
            return {str(n).strip() for n in filters.garbage_list if str(n).strip()}
        if show == "keep":
            return {str(n).strip() for n in filters.keep_list if str(n).strip()}
        return None

    def _refresh(self) -> None:
        needle = self.search_var.get().strip().lower()
        cat = self.category_var.get().strip()
        allow = self._filter_names()
        self.tree.delete(*self.tree.get_children())
        self._iid_to_entry.clear()
        for i, entry in enumerate(self._catalog):
            if allow is not None and entry.kr_name not in allow:
                continue
            if cat not in ("", "(all)") and entry.category != cat:
                continue
            if needle:
                blob = (
                    f"{entry.kr_name} {entry.zh_name} {entry.category} {entry.template}"
                ).lower()
                if needle not in blob:
                    continue
            iid = str(i)
            self._iid_to_entry[iid] = entry
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(entry.category, entry.kr_name, entry.zh_name, entry.template),
            )

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        entry = self._iid_to_entry.get(sel[0])
        if entry is None:
            return
        self.new_category_var.set(entry.category or self.new_category_var.get())
        self.new_name_var.set(entry.kr_name)

    def _accept_replace(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(
                "Template",
                "Select an existing template row, or use Save as new.",
                parent=self,
            )
            return
        entry = self._iid_to_entry.get(sel[0])
        if entry is None:
            return
        self.result = TemplateBrowseResult(entry=entry, is_new=False)
        self.destroy()

    def _accept_new(self) -> None:
        cat = self.new_category_var.get().strip()
        name = self.new_name_var.get().strip()
        try:
            rel = new_item_template_rel(cat, name, pack=self._pack)
        except ValueError as exc:
            messagebox.showwarning("Template", str(exc), parent=self)
            return
        existing = next((e for e in self._catalog if e.kr_name == name), None)
        if existing is not None:
            if not messagebox.askyesno(
                "Template",
                f"{name!r} already exists as:\n{existing.template}\n\n"
                "Save as new will fail unless you change the name, "
                "or use Replace selected on that row instead.\n\n"
                "Continue anyway?",
                parent=self,
            ):
                return
        entry = ItemTemplateEntry(
            kr_name=name,
            category=cat,
            template=rel,
            zh_name="",
        )
        self.result = TemplateBrowseResult(entry=entry, is_new=True)
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
