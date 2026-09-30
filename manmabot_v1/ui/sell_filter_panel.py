"""Sell keep-list panel for the schedule Equipment tab.

Shows currently owned bag items (category Own) at the top, then the full
official catalog with owned duplicates skipped. Save = keep (do not sell).
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Mapping, Optional

from PIL import Image, ImageTk

from manmabot_v1.paths import manmabot_root

_engine = str(manmabot_root())
if _engine not in sys.path:
    sys.path.insert(0, _engine)

from app._03_world.game_catalog import (
    ItemCatalogRow,
    item_by_key,
    list_item_rows,
    resolve_item_key,
)
from app._03_world.memory_inventory import ADENA_IDS, ADENA_NAMES
from manmabot_v1.localized_names import (
    item_catalog_display_name,
    item_category_display_name,
    memory_name_for_ui,
)
from manmabot_v1.map_previews import placeholder_thumb
from manmabot_v1.shopping.behaviors import (
    ShoppingSellFilters,
    load_behaviors,
    load_sell_filters,
    save_behaviors,
)
from manmabot_v1.ui.design_system import TEXT_MUTED, FitLabel

_NONE = ""
_KEEP = "keep"
_CYCLE = (_NONE, _KEEP)

# Same square as the hunt monster table: 32px sprite plus 4px on every side.
_ICON_PAD = 4
_ICON_BOX = 40


@dataclass(frozen=True)
class _SellListRow:
    key: str
    name: str
    category: str
    is_own: bool
    icon: Path | None = None
    source_category: str = ""  # catalog category for filtering when is_own


def _thumb(path: Path | None, size: int = _ICON_BOX):
    """Fit an item sprite the same way hunt monster icons are fitted."""
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
    bounds = image.getbbox()
    if bounds:
        image = image.crop(bounds)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, size - _ICON_PAD * 2)
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


def _catalog_by_id(catalog: list[ItemCatalogRow]) -> dict[int, ItemCatalogRow]:
    out: dict[int, ItemCatalogRow] = {}
    for row in catalog:
        for sid in row.ids:
            try:
                out[int(sid)] = row
            except (TypeError, ValueError):
                continue
    return out


def _is_adena(*, item_id: int, name: str, key: str = "") -> bool:
    if int(item_id or 0) in ADENA_IDS:
        return True
    tokens = {
        str(name or "").strip().lower(),
        str(key or "").strip().lower(),
    }
    tokens.discard("")
    adena = {str(n).strip().lower() for n in ADENA_NAMES if str(n).strip()}
    adena.add("아데나")
    return bool(tokens & adena)


def _owned_from_snapshot(
    snap: Optional[dict],
    *,
    catalog: list[ItemCatalogRow],
    language: str,
    own_label: str,
) -> list[_SellListRow]:
    raw = snap.get("items") if isinstance(snap, dict) else None
    if not isinstance(raw, list):
        return []
    by_id = _catalog_by_id(catalog)
    rows: list[_SellListRow] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        name = str(
            item.get("name")
            or item.get("name_tw")
            or item.get("name_cn")
            or item.get("name_en")
            or ""
        ).strip()
        if _is_adena(item_id=item_id, name=name):
            continue
        # Prefer name→catalog; game memory ids often differ from official item.json ids.
        key = resolve_item_key(name) or ""
        entry = item_by_key(key) if key else None
        if entry is None and item_id:
            entry = by_id.get(item_id)
            if entry is not None:
                key = entry.key
        if not key:
            key = name or (f"id:{item_id}" if item_id else "")
        if not key or key in seen:
            continue
        if _is_adena(item_id=item_id, name=name, key=key):
            continue
        if entry is not None and _is_adena(
            item_id=item_id, name=entry.name_ko, key=entry.key
        ):
            continue
        seen.add(key)
        source_cat = ""
        if entry is not None:
            shown = item_catalog_display_name(entry.name_ko, language) or entry.name_ko
            icon = entry.image_path()
            source_cat = (
                item_category_display_name(
                    entry.display_category(language), language
                )
                or entry.display_category(language)
                or ""
            )
        else:
            shown = memory_name_for_ui(name or key, language) or key
            icon = None
        rows.append(
            _SellListRow(
                key=key,
                name=shown,
                category=own_label,
                is_own=True,
                icon=icon,
                source_category=source_cat,
            )
        )
    rows.sort(key=lambda r: r.name.lower())
    return rows


class SellFilterPanel(ttk.Frame):
    """Full catalog + live bag Own rows; Save marks keep-from-sell."""

    def __init__(
        self,
        master: tk.Misc,
        t: Mapping[str, str],
        *,
        language: str = "ko",
        actions_parent: tk.Misc | None = None,
    ) -> None:
        super().__init__(master)
        self._t = t
        self._language = language
        self._actions_parent = actions_parent
        self._catalog: list[ItemCatalogRow] = []
        self._owned: list[_SellListRow] = []
        self._owned_keys: set[str] = set()
        self._marks: dict[str, str] = {}
        self._iid_to_name: dict[str, str] = {}
        self._icon_paths: dict[str, Path | None] = {}
        self._photo_cache: dict[str, tk.PhotoImage] = {}
        self._scanning = False
        own_label = str(t.get("filter_own", "Own"))
        self._show_ids = {
            t["filter_all"]: "all",
            own_label: "own",
            t.get("filter_save", t["filter_keep"]): "keep",
            t["filter_unmarked"]: "unmarked",
        }
        self._mark_labels = {
            _NONE: "—",
            _KEEP: t.get("filter_save", t["filter_keep"]),
        }
        self.search_var = tk.StringVar(self, value="")
        self.category_var = tk.StringVar(self, value=t["filter_all"])
        self.show_var = tk.StringVar(self, value=t["filter_all"])
        self.count_var = tk.StringVar(self, value="")
        self.status_var = tk.StringVar(self, value="")
        # Catalog/marks load on first ensure_loaded(); icon PIL may already be
        # warm from ScheduleWindow startup background prep.
        self._loaded = False
        self._warm_pil: dict[str, object] = {}
        self._build()

    @property
    def _own_label(self) -> str:
        return str(self._t.get("filter_own", "Own"))

    def ensure_loaded(self) -> None:
        """Load keep filters + item icons once when the Sell UI is shown."""
        if self._loaded:
            return
        self._loaded = True
        self.reload()

    def _build(self) -> None:
        hint = str(self._t.get("sell_logic_hint") or self._t.get("sell_filter_hint") or "")
        if hint:
            FitLabel(
                self,
                text=hint,
                foreground=TEXT_MUTED,
                wraplength=640,
                justify="left",
            ).pack(fill="x", pady=(0, 6))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        FitLabel(bar, text=self._t["filter_search"]).pack(side="left")
        search = ttk.Entry(bar, textvariable=self.search_var, width=18)
        search.pack(side="left", padx=(4, 10))
        search.bind("<KeyRelease>", lambda _event: self._refresh())
        FitLabel(bar, text=self._t["filter_category"]).pack(side="left")
        self._category = ttk.Combobox(
            bar,
            textvariable=self.category_var,
            state="readonly",
            width=14,
            values=(self._t["filter_all"], self._own_label),
        )
        self._category.pack(side="left", padx=(4, 10))
        self._category.bind("<<ComboboxSelected>>", lambda _event: self._refresh())
        FitLabel(bar, text=self._t["filter_show"]).pack(side="left")
        show = ttk.Combobox(
            bar,
            textvariable=self.show_var,
            state="readonly",
            width=12,
            values=tuple(self._show_ids),
        )
        show.pack(side="left", padx=(4, 10))
        show.bind("<<ComboboxSelected>>", lambda _event: self._refresh())
        self._reload_btn = ttk.Button(
            bar,
            text=self._t.get("sell_reload_inventory", self._t.get("inventory_refresh", "Reload")),
            command=self.reload_owned,
        )
        self._reload_btn.pack(side="left", padx=(10, 0))
        FitLabel(bar, textvariable=self.count_var, foreground=TEXT_MUTED).pack(
            side="left", padx=(10, 0)
        )

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        # Hunt style is defined in schedule_ui. Import here so this module can
        # still be imported from schedule_ui without a cycle.
        from manmabot_v1.ui.schedule_ui import (
            _configure_hunt_icon_column,
            _configure_hunt_tree,
            _enable_bbox_grid,
            _mount_vertical_scroll,
        )

        _configure_hunt_tree(self)
        self._tree = ttk.Treeview(
            table,
            columns=("save", "category", "name"),
            show="tree headings",
            selectmode="extended",
            height=8,
            style="Hunt.Treeview",
        )
        _configure_hunt_icon_column(self._tree, heading="")
        save_heading = self._t.get("filter_save", self._t["filter_mark"])
        self._tree.heading("save", text=save_heading, anchor="center")
        self._tree.heading("category", text=self._t["filter_category"], anchor="center")
        self._tree.heading("name", text=self._t["filter_item"], anchor="center")
        self._tree.column("save", width=88, minwidth=72, anchor="center", stretch=False)
        self._tree.column("category", width=110, minwidth=80, anchor="center", stretch=False)
        self._tree.column("name", width=280, minwidth=120, anchor="w", stretch=True)
        _mount_vertical_scroll(table, self._tree)
        _enable_bbox_grid(self._tree)
        self._tree.tag_configure("keep", foreground="#0f766e")
        self._tree.tag_configure("own", foreground="#1d4ed8")
        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<space>", self._on_space)

        actions = ttk.Frame(self._actions_parent or self)
        actions.pack(
            fill="x",
            pady=(0, 0) if self._actions_parent is not None else (6, 0),
        )
        ttk.Button(
            actions,
            text=self._t.get("mark_save", self._t["mark_keep"]),
            command=lambda: self._mark_selected(_KEEP),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            actions,
            text=self._t.get("mark_clear_save", self._t["mark_clear"]),
            command=lambda: self._mark_selected(_NONE),
        ).pack(side="left")
        FitLabel(actions, textvariable=self.status_var, foreground=TEXT_MUTED).pack(
            side="right"
        )

    def accept_warm_thumbs(self, thumbs: dict[str, object]) -> None:
        """Store background-prepared PIL thumbs for instant PhotoImage create."""
        if not thumbs:
            return
        self._warm_pil.update(thumbs)

    def _photo_for(self, key: str) -> tk.PhotoImage:
        cached = self._photo_cache.get(key)
        if cached is not None:
            return cached
        image = (getattr(self, "_warm_pil", None) or {}).get(key)
        if image is None:
            path = self._icon_paths.get(key)
            image = _thumb(path)
        photo = ImageTk.PhotoImage(image, master=self)
        self._photo_cache[key] = photo
        return photo

    def _load_filters_and_catalog(self) -> None:
        try:
            self._catalog = list(list_item_rows())
            filters = load_sell_filters()
        except Exception as exc:
            self._catalog = []
            filters = ShoppingSellFilters()
            self.status_var.set(str(exc))
            return
        self._marks = {}
        for name in filters.keep_list:
            cleaned = str(name).strip()
            if cleaned:
                self._marks[cleaned] = _KEEP

    def _rebuild_icons_and_categories(self, *, clear_photos: bool = False) -> None:
        if clear_photos:
            self._photo_cache.clear()
        self._icon_paths = {}
        for entry in self._catalog:
            self._icon_paths[entry.key] = entry.image_path()
        for row in self._owned:
            if row.icon is not None:
                self._icon_paths[row.key] = row.icon
        own = self._own_label
        categories = [self._t["filter_all"], own]
        seen: set[str] = {own}
        for entry in self._catalog:
            label = (
                item_category_display_name(
                    entry.display_category(self._language), self._language
                )
                or entry.display_category(self._language)
            )
            if label and label not in seen:
                seen.add(label)
                categories.append(label)
        categories = [categories[0], own] + sorted(
            [c for c in categories[2:]], key=str.lower
        )
        self._category.configure(values=categories)
        if self.category_var.get() not in categories:
            self.category_var.set(self._t["filter_all"])

    def _apply_owned_snapshot(self, snap: object, error: str) -> None:
        """Update Own rows from an inventory_listen snapshot."""
        items = snap.get("items") if isinstance(snap, dict) else None
        if error or not isinstance(snap, dict) or not isinstance(items, list):
            msg = self._t.get(
                "inventory_refresh_failed",
                "Could not read inventory. {error}",
            )
            try:
                self.status_var.set(msg.format(error=error or "no snapshot"))
            except (KeyError, ValueError, IndexError):
                self.status_var.set(str(error or "no snapshot"))
            self._owned = []
            self._owned_keys = set()
            self._rebuild_icons_and_categories()
            self._refresh()
            return
        self._owned = _owned_from_snapshot(
            snap,
            catalog=self._catalog,
            language=self._language,
            own_label=self._own_label,
        )
        self._owned_keys = {row.key for row in self._owned}
        self._rebuild_icons_and_categories()
        if self.category_var.get() not in (self._t["filter_all"], self._own_label):
            self.category_var.set(self._t["filter_all"])
        self._refresh()
        try:
            self._tree.yview_moveto(0)
        except tk.TclError:
            pass
        self.status_var.set(
            self._t.get("sell_own_reloaded", "Loaded {n} owned items.").format(
                n=len(self._owned)
            )
        )

    def _snapshot_inventory(self) -> tuple[object, str]:
        snap = None
        error = ""
        try:
            from app._03_world.inventory_listen_reader import shared_inventory

            reader = shared_inventory()
            if not reader.dll_loaded:
                error = "inventory_listen.dll missing"
            else:
                snap = reader.snapshot()
                if snap is None:
                    error = "empty snapshot (is LC.exe running?)"
        except Exception as exc:
            error = str(exc)
        return snap, error

    def reload(self) -> None:
        """Load keep filters + catalog, then pull live bag synchronously."""
        self._loaded = True
        self._load_filters_and_catalog()
        self._rebuild_icons_and_categories(clear_photos=True)
        snap, error = self._snapshot_inventory()
        self._apply_owned_snapshot(snap, error)

    def reload_owned(self) -> None:
        """Pull current character bag via inventory_listen and refresh Own rows."""
        if self._scanning:
            return
        self._scanning = True
        try:
            self._reload_btn.configure(state="disabled")
        except tk.TclError:
            pass
        self.status_var.set(
            self._t.get("inventory_refreshing", "Reading the current bag…")
        )

        def work() -> None:
            snap, error = self._snapshot_inventory()
            try:
                self.after(
                    0,
                    lambda s=snap, e=error: self._finish_owned_reload(s, e),
                )
            except tk.TclError:
                self._scanning = False

        threading.Thread(target=work, name="sell-own-reload", daemon=True).start()

    def _finish_owned_reload(self, snap: object, error: str) -> None:
        self._scanning = False
        try:
            self._reload_btn.configure(state="normal")
        except tk.TclError:
            pass
        self._apply_owned_snapshot(snap, error)

    def _visible(self) -> list[_SellListRow]:
        needle = self.search_var.get().strip().lower()
        category = self.category_var.get().strip()
        show = self._show_ids.get(self.show_var.get().strip(), "all")
        all_label = self._t["filter_all"]
        own_label = self._own_label

        def wanted(key: str, *, is_own: bool) -> bool:
            mark = self._marks.get(key, _NONE)
            if show == "own":
                return is_own
            if show == "keep":
                return mark == _KEEP
            if show == "unmarked":
                return mark == _NONE
            return True

        def name_ok(text: str, *extra: str) -> bool:
            if not needle:
                return True
            return needle in " ".join((text, *extra)).lower()

        def own_in_category(row: _SellListRow) -> bool:
            if category in ("", all_label, own_label):
                return True
            return bool(row.source_category) and row.source_category == category

        rows: list[_SellListRow] = []
        for row in self._owned:
            if not own_in_category(row):
                continue
            if wanted(row.key, is_own=True) and name_ok(row.name, row.key):
                rows.append(row)

        if category == own_label or show == "own":
            return rows

        for entry in self._catalog:
            if entry.key in self._owned_keys:
                continue
            cat = (
                item_category_display_name(
                    entry.display_category(self._language), self._language
                )
                or entry.display_category(self._language)
            )
            if category not in ("", all_label) and cat != category:
                continue
            shown = (
                item_catalog_display_name(entry.name_ko, self._language) or entry.name_ko
            )
            if not wanted(entry.key, is_own=False):
                continue
            if not name_ok(
                shown,
                entry.name_ko,
                entry.name_zh,
                entry.name_zh_cn,
                cat,
                *map(str, entry.ids),
            ):
                continue
            rows.append(
                _SellListRow(
                    key=entry.key,
                    name=shown,
                    category=cat,
                    is_own=False,
                    icon=entry.image_path(),
                    source_category=cat,
                )
            )

        known = self._owned_keys | {e.key for e in self._catalog}
        for name in sorted(self._marks):
            if name in known or not self._marks.get(name):
                continue
            if category not in ("", all_label) and category != self._t.get(
                "filter_extra", "Extra"
            ):
                continue
            if not wanted(name, is_own=False):
                continue
            shown = memory_name_for_ui(name, self._language)
            if not name_ok(shown, name):
                continue
            rows.append(
                _SellListRow(
                    key=name,
                    name=shown,
                    category=str(self._t.get("filter_extra", "Extra")),
                    is_own=False,
                    icon=None,
                )
            )
        return rows

    def _refresh(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._iid_to_name.clear()
        rows = self._visible()
        for index, row in enumerate(rows):
            if row.icon is not None:
                self._icon_paths[row.key] = row.icon
            mark = self._marks.get(row.key, _NONE)
            iid = str(index)
            self._iid_to_name[iid] = row.key
            tags: list[str] = []
            if mark:
                tags.append(mark)
            if row.is_own:
                tags.append("own")
            try:
                photo = self._photo_for(row.key)
            except Exception:
                self._icon_paths[row.key] = None
                self._photo_cache.pop(row.key, None)
                photo = self._photo_for(row.key)
            self._tree.insert(
                "",
                "end",
                iid=iid,
                image=photo,
                values=(
                    self._mark_labels.get(mark, "—"),
                    row.category,
                    row.name,
                ),
                tags=tuple(tags),
            )
        keep = sum(1 for mark in self._marks.values() if mark == _KEEP)
        fmt = self._t.get(
            "filter_count_keep",
            self._t.get("filter_count", "{shown} shown · keep {keep}"),
        )
        try:
            self.count_var.set(
                fmt.format(shown=len(rows), keep=keep, garbage=0, own=len(self._owned))
            )
        except (KeyError, ValueError, IndexError):
            self.count_var.set(f"{len(rows)} / save {keep} / own {len(self._owned)}")
        if not self._catalog and not self._owned and not self.status_var.get():
            self.status_var.set(self._t["filter_empty"])
        from manmabot_v1.ui.schedule_ui import _refresh_cell_grid

        _refresh_cell_grid(self._tree)

    def _names(self, iids: tuple[str, ...] | list[str]) -> list[str]:
        return [self._iid_to_name[iid] for iid in iids if iid in self._iid_to_name]

    def _on_double_click(self, event: tk.Event) -> str:
        row = self._tree.identify_row(event.y)
        if not row:
            return "break"
        self._cycle(self._names((row,)))
        return "break"

    def _on_space(self, _event: tk.Event) -> str:
        self._cycle(self._names(self._tree.selection()))
        return "break"

    def _mark_selected(self, mark: str) -> None:
        names = self._names(self._tree.selection())
        if not names:
            return
        for name in names:
            if mark == _NONE:
                self._marks.pop(name, None)
            else:
                self._marks[name] = mark
        self._persist()
        self._refresh()

    def _cycle(self, names: list[str]) -> None:
        if not names:
            return
        for name in names:
            current = self._marks.get(name, _NONE)
            nxt = (
                _CYCLE[(_CYCLE.index(current) + 1) % len(_CYCLE)]
                if current in _CYCLE
                else _KEEP
            )
            if nxt == _NONE:
                self._marks.pop(name, None)
            else:
                self._marks[name] = nxt
        self._persist()
        self._refresh()

    def _persist(self) -> None:
        filters = ShoppingSellFilters(
            garbage_list=(),
            keep_list=tuple(
                sorted(n for n, mark in self._marks.items() if mark == _KEEP)
            ),
        )
        try:
            save_behaviors(load_behaviors(), sell_filters=filters)
        except Exception as exc:
            self.status_var.set(str(exc))
            return
        self.status_var.set(self._t["filter_saved"])
