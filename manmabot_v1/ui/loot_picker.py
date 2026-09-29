"""Loot-mode radios with icons from ``images/Adena_vs_All``."""
from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

LOOT_MODES = ("all_items", "adena_only")


def pack_loot_choices(
    parent,
    *,
    variable,
    strings,
    command: Optional[Callable[[], Any]] = None,
    icon_box: tuple[int, int] = (128, 128),
    wraplength: int = 220,
) -> list:
    """Pack All-items / Adená-only cards in a row. Return image refs."""
    refs: list = []
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=8, pady=4)
    for key in LOOT_MODES:
        meta = strings.loot_labels.get(key) or {"title": key, "desc": ""}
        card = ctk.CTkFrame(row, fg_color="transparent")
        card.pack(side="left", padx=(0, 20), anchor="n")

        ctk.CTkRadioButton(
            card,
            text=meta["title"],
            variable=variable,
            value=key,
            command=command,
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            card,
            text=meta["desc"],
            text_color="gray",
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w")
    return refs
