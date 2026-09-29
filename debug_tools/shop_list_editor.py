"""Shop list editor widget for Shopping Practice (writes maps/shops.yaml)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from manmabot_v1.ui.design_system import TEXT_MUTED


_ID_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


class ShopListEditor(ttk.Frame):
    """Edit the live bot shop catalog (``engine/maps/shops.yaml``)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_log: Optional[Callable[[str], None]] = None,
        on_saved: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, padding=4)
        self._on_log = on_log or (lambda _m: None)
        self._on_saved = on_saved or (lambda: None)
        self._shops: list = []
        self._selected_index: int | None = None
        self._suppress = False

        self.path_var = tk.StringVar(self, value="")
        self.id_var = tk.StringVar(self)
        self.name_var = tk.StringVar(self)
        self.label_var = tk.StringVar(self)
        self.map_var = tk.StringVar(self)
        self.scroll_var = tk.StringVar(self)
        self.world_x_var = tk.StringVar(self, value="0")
        self.world_y_var = tk.StringVar(self, value="0")
        self.roles_var = tk.StringVar(self, value="")
        self.status_var = tk.StringVar(self, value="")

        self._build()
        self.reload_from_disk()

    def _build(self) -> None:
        from app._04_decision.shops import (
            SHOP_ROLE_CHOICES,
            list_map_ids,
            list_scroll_spot_ids,
            shops_path,
        )

        top = ttk.Frame(self, style="Chrome.TFrame")
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top,
            text="Live bot catalog — saves to maps/shops.yaml",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left")
        self.path_var.set(str(shops_path()))
        ttk.Label(
            top, textvariable=self.path_var, style="Chrome.TLabel", foreground=TEXT_MUTED
        ).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=4)
        right = ttk.Frame(body, padding=4)
        body.add(left, weight=2)
        body.add(right, weight=3)

        list_box = ttk.LabelFrame(left, text="Shops", padding=(6, 4))
        list_box.pack(fill="both", expand=True)
        cols = ("id", "map", "scroll", "roles")
        self.tree = ttk.Treeview(
            list_box,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=14,
        )
        self.tree.heading("id", text="Id")
        self.tree.heading("map", text="Map")
        self.tree.heading("scroll", text="Scroll spot")
        self.tree.heading("roles", text="Roles")
        self.tree.column("id", width=120, anchor="w")
        self.tree.column("map", width=100, anchor="w")
        self.tree.column("scroll", width=140, anchor="w")
        self.tree.column("roles", width=100, anchor="w")
        scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_tree_select())

        btns = ttk.Frame(left, style="Chrome.TFrame")
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add", command=self.add_shop).pack(side="left", padx=2)
        ttk.Button(btns, text="Duplicate", command=self.duplicate_shop).pack(
            side="left", padx=2
        )
        ttk.Button(btns, text="Delete", command=self.delete_shop).pack(
            side="left", padx=2
        )
        ttk.Button(btns, text="Reload", command=self.reload_from_disk).pack(
            side="right", padx=2
        )
        ttk.Button(btns, text="Save to bot", command=self.save_to_disk).pack(
            side="right", padx=2
        )

        form = ttk.LabelFrame(right, text="Selected shop", padding=(8, 6))
        form.pack(fill="both", expand=True)

        def row(r: int, label: str, widget: tk.Misc) -> None:
            ttk.Label(form, text=label, style="Chrome.TLabel").grid(
                row=r, column=0, sticky="w", pady=3, padx=(0, 8)
            )
            widget.grid(row=r, column=1, sticky="ew", pady=3)

        form.columnconfigure(1, weight=1)
        row(0, "Id", ttk.Entry(form, textvariable=self.id_var, width=28))
        row(1, "Name", ttk.Entry(form, textvariable=self.name_var, width=28))
        row(2, "Label", ttk.Entry(form, textvariable=self.label_var, width=28))

        map_combo = ttk.Combobox(
            form,
            textvariable=self.map_var,
            values=list_map_ids(),
            width=26,
        )
        row(3, "Map", map_combo)

        scroll_combo = ttk.Combobox(
            form,
            textvariable=self.scroll_var,
            values=list_scroll_spot_ids(),
            width=26,
        )
        row(4, "Scroll spot", scroll_combo)

        world = ttk.Frame(form, style="Chrome.TFrame")
        ttk.Entry(world, textvariable=self.world_x_var, width=10).pack(
            side="left", padx=(0, 4)
        )
        ttk.Entry(world, textvariable=self.world_y_var, width=10).pack(side="left")
        ttk.Button(
            world, text="Fill from memory", command=self.fill_world_from_memory
        ).pack(side="left", padx=8)
        row(5, "World x,y", world)

        roles_row = ttk.Frame(form, style="Chrome.TFrame")
        ttk.Entry(roles_row, textvariable=self.roles_var, width=28).pack(
            side="left", fill="x", expand=True
        )
        row(6, "Roles", roles_row)
        ttk.Label(
            form,
            text="Comma-separated: " + ", ".join(SHOP_ROLE_CHOICES),
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).grid(row=7, column=1, sticky="w")

        apply_row = ttk.Frame(form, style="Chrome.TFrame")
        apply_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(
            apply_row, text="Apply to list", command=self.apply_form_to_selected
        ).pack(side="left")
        ttk.Label(
            apply_row,
            textvariable=self.status_var,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=10)

        ttk.Label(
            form,
            text=(
                "Tip: stand on the NPC tile, then Fill from memory. "
                "Tag potion sellers with role potions for buy HP potion later."
            ),
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
            wraplength=360,
            justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _log(self, message: str) -> None:
        self._on_log(message)
        self.status_var.set(message)

    def reload_from_disk(self) -> None:
        from app._04_decision.shops import reload_shops, shops_path

        try:
            self._shops = list(reload_shops())
        except Exception as exc:
            messagebox.showerror("Shop list", str(exc), parent=self)
            self._log(f"reload failed: {exc}")
            return
        self.path_var.set(str(shops_path()))
        self._refresh_tree(select_index=0 if self._shops else None)
        self._log(f"Loaded {len(self._shops)} shop(s) from {shops_path().name}")

    def save_to_disk(self) -> None:
        from app._04_decision.shops import save_shops, shops_path

        try:
            if self._selected_index is not None:
                if not self.apply_form_to_selected(silent=True):
                    return
            path = save_shops(list(self._shops))
            self._refresh_tree(select_index=self._selected_index)
            self._log(f"Saved {len(self._shops)} shop(s) to {path.name}")
            self._on_saved()
        except Exception as exc:
            import traceback

            detail = traceback.format_exc()
            try:
                from debug_tools import OUTPUT_DIR

                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                (OUTPUT_DIR / "shop_list_save_error.txt").write_text(
                    detail, encoding="utf-8"
                )
            except Exception:
                pass
            messagebox.showerror(
                "Shop list",
                f"Save failed:\n{exc}\n\nDetails: debug_tools/output/shop_list_save_error.txt",
                parent=self.winfo_toplevel(),
            )
            self._log(f"save failed: {exc}")

    def _refresh_tree(self, select_index: int | None = None) -> None:
        # Unbind while rebuilding — ttk selection events after delete() can
        # re-enter apply/save and crash the window (especially with pythonw).
        self.tree.unbind("<<TreeviewSelect>>")
        self._suppress = True
        try:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            for i, shop in enumerate(self._shops):
                roles = ",".join(shop.roles) if shop.roles else ""
                # Prefer ASCII-safe columns in the tree (label stays in the form).
                display = shop.id
                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(display, shop.map_id, shop.scroll_spot, roles),
                )
            if select_index is not None and 0 <= select_index < len(self._shops):
                iid = str(select_index)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
                self._selected_index = select_index
                self._load_form(self._shops[select_index])
            elif not self._shops:
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
        if index < 0 or index >= len(self._shops):
            return
        # Apply pending edits before switching rows (no nested refresh storm).
        if self._selected_index is not None and self._selected_index != index:
            prev = self._selected_index
            try:
                shop = self._parse_form()
            except Exception as exc:
                self._log(str(exc))
                self._suppress = True
                try:
                    self.tree.selection_set(str(prev))
                    self.tree.focus(str(prev))
                finally:
                    self._suppress = False
                return
            for i, other in enumerate(self._shops):
                if i != prev and other.id == shop.id:
                    self._log(f"Duplicate id {shop.id!r}")
                    self._suppress = True
                    try:
                        self.tree.selection_set(str(prev))
                        self.tree.focus(str(prev))
                    finally:
                        self._suppress = False
                    return
            self._shops[prev] = shop
            # Update the previous row text without full rebuild.
            roles = ",".join(shop.roles) if shop.roles else ""
            try:
                self.tree.item(
                    str(prev),
                    values=(shop.id, shop.map_id, shop.scroll_spot, roles),
                )
            except tk.TclError:
                pass
        self._selected_index = index
        self._load_form(self._shops[index])

    def _clear_form(self) -> None:
        self.id_var.set("")
        self.name_var.set("")
        self.label_var.set("")
        self.map_var.set("")
        self.scroll_var.set("")
        self.world_x_var.set("0")
        self.world_y_var.set("0")
        self.roles_var.set("")

    def _load_form(self, shop) -> None:
        self.id_var.set(shop.id)
        self.name_var.set(shop.name)
        self.label_var.set(shop.label)
        self.map_var.set(shop.map_id)
        self.scroll_var.set(shop.scroll_spot)
        self.world_x_var.set(str(int(shop.world_x)))
        self.world_y_var.set(str(int(shop.world_y)))
        self.roles_var.set(", ".join(shop.roles))

    def _parse_form(self):
        from app._04_decision.shops import Shop

        sid = self.id_var.get().strip()
        if not sid or not _ID_SAFE.match(sid):
            raise ValueError(
                "Id must start with a letter and use only letters, digits, _ or -"
            )
        try:
            wx = int(float(self.world_x_var.get().strip()))
            wy = int(float(self.world_y_var.get().strip()))
        except ValueError as exc:
            raise ValueError("World x,y must be integers") from exc
        roles = tuple(
            p.strip()
            for p in self.roles_var.get().replace(";", ",").split(",")
            if p.strip()
        )
        map_id = self.map_var.get().strip()
        scroll = self.scroll_var.get().strip()
        if not map_id:
            raise ValueError("Map is required")
        if not scroll:
            raise ValueError("Scroll spot is required")
        name = self.name_var.get().strip() or sid
        label = self.label_var.get().strip()
        return Shop(
            id=sid,
            name=name,
            label=label,
            map_id=map_id,
            scroll_spot=scroll,
            world_x=wx,
            world_y=wy,
            roles=roles,
        )

    def apply_form_to_selected(self, *, silent: bool = False) -> bool:
        if self._selected_index is None:
            if not silent:
                messagebox.showinfo("Shop list", "Select a shop first.", parent=self)
            return False
        try:
            shop = self._parse_form()
        except Exception as exc:
            if not silent:
                messagebox.showwarning("Shop list", str(exc), parent=self)
            self._log(str(exc))
            return False
        for i, other in enumerate(self._shops):
            if i != self._selected_index and other.id == shop.id:
                msg = f"Duplicate id {shop.id!r}"
                if not silent:
                    messagebox.showwarning("Shop list", msg, parent=self)
                self._log(msg)
                return False
        self._shops[self._selected_index] = shop
        self._refresh_tree(select_index=self._selected_index)
        if not silent:
            self._log(f"Updated list entry {shop.id}")
        return True

    def add_shop(self) -> None:
        from app._04_decision.shops import Shop, list_map_ids, list_scroll_spot_ids

        maps = list_map_ids()
        spots = list_scroll_spot_ids()
        base = "new_shop"
        n = 1
        existing = {s.id for s in self._shops}
        sid = base
        while sid in existing:
            n += 1
            sid = f"{base}_{n}"
        shop = Shop(
            id=sid,
            name="New shop",
            label="",
            map_id=maps[0] if maps else "talking_island",
            scroll_spot=spots[0] if spots else "ti_general_goods",
            world_x=0,
            world_y=0,
            roles=(),
        )
        self._shops.append(shop)
        self._refresh_tree(select_index=len(self._shops) - 1)
        self._log(f"Added {sid} (not saved yet)")

    def duplicate_shop(self) -> None:
        if self._selected_index is None:
            return
        from app._04_decision.shops import Shop

        src = self._shops[self._selected_index]
        existing = {s.id for s in self._shops}
        sid = f"{src.id}_copy"
        n = 2
        while sid in existing:
            sid = f"{src.id}_copy{n}"
            n += 1
        self._shops.append(
            Shop(
                id=sid,
                name=src.name,
                label=src.label,
                map_id=src.map_id,
                scroll_spot=src.scroll_spot,
                world_x=src.world_x,
                world_y=src.world_y,
                roles=src.roles,
            )
        )
        self._refresh_tree(select_index=len(self._shops) - 1)
        self._log(f"Duplicated → {sid}")

    def delete_shop(self) -> None:
        if self._selected_index is None:
            return
        shop = self._shops[self._selected_index]
        if not messagebox.askyesno(
            "Shop list",
            f"Delete shop {shop.id!r} from the list?\n(Save to bot to write disk.)",
            parent=self,
        ):
            return
        del self._shops[self._selected_index]
        next_i = min(self._selected_index, len(self._shops) - 1)
        self._selected_index = None
        self._refresh_tree(select_index=next_i if self._shops else None)
        self._log(f"Deleted {shop.id} (not saved yet)")

    def fill_world_from_memory(self) -> None:
        """Set world x,y from the memory monitor player position."""
        try:
            from tool.utils import load_config
            from app._03_world.memory_client import PIPE_NAME, LineageMonitor

            config = load_config()
            section = (config.get("memory") or {})
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
            raw = (snap or {}).get("player") or {}
            pos = raw.get("pos")
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                raise RuntimeError("no player position in memory snapshot")
            gx, gy = int(pos[0]), int(pos[1])
            if gx == 0 and gy == 0:
                raise RuntimeError("player position is unset (0,0)")
            self.world_x_var.set(str(gx))
            self.world_y_var.set(str(gy))
            self._log(f"World filled from memory: [{gx}, {gy}]")
            if self._selected_index is not None:
                self.apply_form_to_selected(silent=True)
        except Exception as exc:
            messagebox.showwarning("Shop list", str(exc), parent=self)
            self._log(f"Fill from memory failed: {exc}")
