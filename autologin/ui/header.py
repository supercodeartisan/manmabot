import tkinter as tk
from tkinter import ttk

from .i18n import LANGUAGES
from .theme import C


def build_header(root, tr, lang_disp, on_language, admin_status="",
                 on_elevate=None):
    hdr = tk.Frame(root, bg=C.HEADER_BG, height=38)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)

    tk.Label(hdr, text=tr["title"], bg=C.HEADER_BG, fg=C.HEADER_FG,
             font=("Segoe UI", 12, "bold")).pack(side="left", padx=12)

    # Admin status (left of language) — critical for Purple/UIPI control
    admin_fr = tk.Frame(hdr, bg=C.HEADER_BG)
    admin_fr.pack(side="right", padx=(0, 8))
    admin_lbl = tk.Label(
        admin_fr, text=admin_status, bg=C.HEADER_BG, fg=C.HEADER_FG,
        font=("Segoe UI", 9))
    admin_lbl.pack(side="left")
    elevate_btn = None
    if on_elevate is not None:
        elevate_btn = tk.Button(
            admin_fr, text=tr.get("elevate_btn", "Run as Admin"),
            command=on_elevate, bg="#5b5fc7", fg="#ffffff",
            activebackground="#484bb6", activeforeground="#ffffff",
            relief="flat", padx=8, pady=1, font=("Segoe UI", 8, "bold"),
            cursor="hand2")
        elevate_btn.pack(side="left", padx=(8, 0))

    lf = tk.Frame(hdr, bg=C.HEADER_BG)
    lf.pack(side="right", padx=12)
    tk.Label(lf, text="\U0001f310", bg=C.HEADER_BG, fg=C.HEADER_FG,
             font=("Segoe UI", 10)).pack(side="left")

    lang_box = ttk.Combobox(lf, textvariable=None, width=8,
                            values=list(LANGUAGES), state="readonly")
    lang_box.set(lang_disp)
    lang_box.pack(side="left", padx=(6, 0))
    lang_box.bind("<<ComboboxSelected>>", on_language)
    return lang_box, admin_lbl, elevate_btn
