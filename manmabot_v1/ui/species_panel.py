"""Compact Species tab with allow/deny switches and catalog levels."""
from __future__ import annotations

import sys
import textwrap
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from manmabot_v1.bot_controller import RunState
from manmabot_v1.localized_names import species_display_name_ui
from manmabot_v1.paths import manmabot_root
from manmabot_v1.profile import save_profile

if TYPE_CHECKING:
    from manmabot_v1.ui.main_window import MainWindow

CELL_W = 230
CARD_H = 78
BUTTON_W = 96
_ON_COLOR = ("gray75", "gray30")
_OFF_COLOR = ("#c4a4a4", "#5a3030")


class SpeciesPanel:
    """Own the compact monster cards inside the Species tab."""

    def __init__(self, tab, app: "MainWindow") -> None:
        self.app = app
        self.tab = tab
        self._defaults: dict[str, int] = {}
        self._order: list[str] = []
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._allow_vars: dict[str, tk.BooleanVar] = {}
        self._cols = 4
        self._syncing = False
        self._build()

    @property
    def s(self):
        return self.app.s

    def _build(self) -> None:
        self.tab.grid_rowconfigure(1, weight=1)
        self.tab.grid_columnconfigure(0, weight=1)

        head = self.app._settings_group(self.tab, pack=False)
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkLabel(
            head, text=self.s.species_heading, font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            head,
            text=self.s.species_hint,
            wraplength=620,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(4, 0))

        sort_row = ctk.CTkFrame(head, fg_color="transparent")
        sort_row.pack(fill="x", padx=12, pady=(6, 10))
        ctk.CTkLabel(sort_row, text=self.s.species_sort_by).pack(side="left")
        self.sort_var = tk.StringVar(
            value=self._sort_label(self.app.profile.species_sort)
        )
        self.sort_seg = ctk.CTkSegmentedButton(
            sort_row,
            values=[self.s.species_sort_name, self.s.species_sort_level],
            variable=self.sort_var,
            command=self._on_sort,
            width=220,
        )
        self.sort_seg.pack(side="left", padx=(8, 0))

        grid_box = self.app._settings_group(self.tab, pack=False)
        grid_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.grid_host = ctk.CTkScrollableFrame(grid_box)
        self.grid_host.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab.bind("<Configure>", self._on_resize)
        self.reload()

    def _sort_label(self, code: str) -> str:
        return (
            self.s.species_sort_level
            if code == "level"
            else self.s.species_sort_name
        )

    def _sort_code(self, label: str) -> str:
        return "level" if label == self.s.species_sort_level else "name"

    def _on_sort(self, value: str) -> None:
        self.app.profile.species_sort = self._sort_code(str(value))
        save_profile(self.app.profile)
        self._apply_sort()
        self._place_cards()

    def _on_resize(self, event) -> None:
        if event.widget is not self.tab:
            return
        cols = max(1, min(5, max(1, int(event.width) - 24) // CELL_W))
        if cols != self._cols:
            self._cols = cols
            self._place_cards()

    def reload(self) -> None:
        self.sort_var.set(self._sort_label(self.app.profile.species_sort))
        try:
            self.sort_seg.set(self.sort_var.get())
        except Exception:
            pass
        for child in self.grid_host.winfo_children():
            child.destroy()
        self._cards.clear()
        self._buttons.clear()
        self._allow_vars.clear()

        root = manmabot_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app._03_world.constants import list_species_catalog

        rows = list_species_catalog()
        self._defaults = {key: level for key, level in rows}
        for key, _default in rows:
            self._build_card(key)
        self._apply_sort()
        self._place_cards()

    def _build_card(self, key: str) -> None:
        card = ctk.CTkFrame(
            self.grid_host,
            width=CELL_W - 6,
            height=CARD_H,
        )
        card.pack_propagate(False)
        button = ctk.CTkButton(
            card,
            text="",
            width=BUTTON_W,
            height=CARD_H - 10,
            compound="top",
            anchor="center",
            font=ctk.CTkFont(size=10),
            command=lambda: self._flip_species(key),
        )
        button.pack(side="left", padx=(5, 3), pady=5)

        controls = ctk.CTkFrame(
            card,
            fg_color="transparent",
            width=CELL_W - BUTTON_W - 18,
            height=CARD_H - 10,
        )
        controls.pack_propagate(False)
        controls.pack(side="left", fill="both", expand=True, padx=(2, 5), pady=5)
        allow_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(
            controls,
            text=self.s.species_allow,
            variable=allow_var,
            width=120,
            font=ctk.CTkFont(size=11),
            command=lambda: self._toggle_species(key),
        ).pack(anchor="w", pady=(2, 2))
        self._cards[key] = card
        self._buttons[key] = button
        self._allow_vars[key] = allow_var
        self._paint_card(key)

    def _apply_sort(self) -> None:
        lang = self.app.profile.language
        keys = list(self._defaults)
        if self.app.profile.species_sort == "level":
            keys.sort(
                key=lambda key: (
                    int(self._defaults.get(key, 99)),
                    species_display_name_ui(key, lang).lower(),
                    key,
                )
            )
        else:
            keys.sort(
                key=lambda key: (
                    species_display_name_ui(key, lang).lower(),
                    key,
                )
            )
        self._order = keys

    def _place_cards(self) -> None:
        cols = max(1, self._cols)
        for index, key in enumerate(self._order):
            row, column = divmod(index, cols)
            self._cards[key].grid(
                row=row, column=column, padx=3, pady=3, sticky="nsew"
            )
        for column in range(5):
            self.grid_host.grid_columnconfigure(
                column, weight=1 if column < cols else 0
            )

    def _paint_card(self, key: str) -> None:
        default = int(self._defaults.get(key, 10))
        blocked = key in self.app.profile.species_blacklist
        name = species_display_name_ui(key, self.app.profile.language)
        wrapped_name = "\n".join(
            textwrap.wrap(
                name,
                width=12,
                break_long_words=True,
                break_on_hyphens=True,
            )
        )
        self._buttons[key].configure(
            text=f"{wrapped_name}\nLv {default}",
            fg_color=_OFF_COLOR if blocked else _ON_COLOR,
        )
        self._syncing = True
        try:
            self._allow_vars[key].set(not blocked)
        finally:
            self._syncing = False

    def _busy(self) -> bool:
        return self.app.controller.state == RunState.RUNNING

    def _flip_species(self, key: str) -> None:
        variable = self._allow_vars.get(key)
        if variable is not None:
            variable.set(not bool(variable.get()))
        self._toggle_species(key)

    def _toggle_species(self, key: str) -> None:
        if self._syncing:
            return
        if self._busy():
            messagebox.showinfo(self.s.setup, self.s.stop_to_change_setup)
            self._paint_card(key)
            return
        allow = bool(self._allow_vars[key].get())
        blocked = [
            item for item in self.app.profile.species_blacklist if item != key
        ]
        if not allow:
            blocked.append(key)
        self.app.profile.species_blacklist = blocked
        save_profile(self.app.profile)
        self._paint_card(key)
