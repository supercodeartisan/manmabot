"""Minimal ttk styling for this standalone tool."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#f3f4f6"
SURFACE = "#ffffff"
CHROME = "#f7f8fa"
CONTROL = "#e9ecef"
BORDER = "#c5c9ce"
BORDER_STRONG = "#9aa0a6"
TEXT = "#202124"
TEXT_MUTED = "#5f6368"
FONT = ("Segoe UI", 9)


def apply_classic_style(root: tk.Misc) -> ttk.Style:
    root.option_add("*Font", FONT)
    root.option_add("*Background", BG)
    root.option_add("*highlightThickness", 0)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=FONT)
    style.configure("TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Chrome.TFrame", background=CHROME)
    style.configure("Chrome.TLabel", background=CHROME, foreground=TEXT)
    style.configure("TRadiobutton", background=SURFACE, foreground=TEXT)
    style.map("TRadiobutton", background=[("active", SURFACE)])
    style.configure(
        "TButton",
        padding=(9, 4),
        background=CONTROL,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=SURFACE,
        darkcolor="#7f858c",
        borderwidth=1,
        relief="raised",
    )
    style.map(
        "TButton",
        background=[("pressed", "#cbdced"), ("active", "#d9eaf7")],
        relief=[("pressed", "sunken"), ("!pressed", "raised")],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=SURFACE,
        background=CONTROL,
        foreground=TEXT,
        arrowcolor=TEXT,
        bordercolor=BORDER_STRONG,
        padding=(3, 2),
    )
    return style
