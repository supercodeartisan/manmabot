"""Character radio rows with portraits from ``images/Characters``."""
from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

from manmabot_v1.map_previews import character_portrait_path, fitted_image
from manmabot_v1.profile import CHARACTER_IDS


def pack_character_choices(
    parent,
    *,
    variable,
    strings,
    command: Optional[Callable[[], Any]] = None,
    portrait_box: tuple[int, int] = (56, 72),
    padx: int = 8,
    wraplength: int = 280,
    show_portraits: bool = True,
    show_blurbs: bool = True,
    expand_rows: bool = False,
) -> list:
    """Pack Mage / Elf / Knight / Royal rows. Return image refs to keep alive."""
    refs: list = []
    max_w, max_h = portrait_box
    for key in CHARACTER_IDS:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(
            fill="both" if expand_rows else "x",
            expand=expand_rows,
            padx=padx,
            pady=0 if expand_rows else 4,
        )

        pic = None
        if show_portraits:
            path = character_portrait_path(key)
            if path is not None:
                try:
                    pil = fitted_image(path, max_w, max_h)
                    w, h = pil.size
                    ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(w, h))
                    refs.append((pil, ctk_img))
                    pic = ctk.CTkLabel(row, text="", image=ctk_img)
                    pic.pack(side="left", padx=(0, 10))
                except Exception:
                    pic = None

        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="both" if expand_rows else "x", expand=True)
        radio = ctk.CTkRadioButton(
            col,
            text=strings.char_titles.get(key, key),
            variable=variable,
            value=key,
            command=command,
            font=ctk.CTkFont(weight="bold"),
        )
        radio.pack(anchor="w", pady=8 if expand_rows else 0)
        if show_blurbs:
            ctk.CTkLabel(
                col,
                text=strings.char_blurbs.get(key, ""),
                text_color="gray",
                wraplength=wraplength,
                justify="left",
            ).pack(anchor="w")

        if pic is not None:

            def _pick(_event=None, k=key) -> None:
                variable.set(k)
                if command is not None:
                    command()

            pic.bind("<Button-1>", _pick)
            inner = getattr(pic, "_label", None)
            if inner is not None:
                inner.bind("<Button-1>", _pick)
    return refs
