import tkinter as tk
from tkinter import ttk


class Colors:
    BG = "#f5f5f5"
    SURFACE = "#ffffff"
    ACCENT = "#5b5fc7"
    ACCENT_HOVER = "#484bb6"
    ACCENT_LIGHT = "#ededfc"
    DANGER = "#d13438"
    DANGER_HOVER = "#b4262a"
    DISABLED = "#d0d3d9"
    BORDER = "#e0e0e0"
    FIELD_ERROR = "#d13438"
    HEADER_BG = "#3b3f5c"
    HEADER_FG = "#ffffff"
    TEXT = "#1b1b1b"
    TEXT_DIM = "#6b6b6b"


C = Colors


def setup_style(root):
    style = ttk.Style(root)
    for theme in ("vista", "xpnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    root.configure(bg=C.BG)
    style.configure(".", font=("Segoe UI", 8), background=C.BG)
    style.configure("TFrame", background=C.BG)
    style.configure("Surface.TFrame", background=C.SURFACE)
    style.configure("TLabel", background=C.BG, foreground=C.TEXT)
    style.configure("Header.TLabel", background=C.HEADER_BG,
                    foreground=C.HEADER_FG, font=("Segoe UI", 10, "bold"))
    style.configure("Hdr.TLabel", font=("Segoe UI", 8, "bold"), foreground="#555")
    style.configure("Dim.TLabel", foreground=C.TEXT_DIM)
    style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
    style.configure("TNotebook", background=C.BG, borderwidth=0)
    style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=(14, 5))
    style.map("TNotebook.Tab",
              background=[("selected", C.SURFACE)],
              foreground=[("selected", C.ACCENT)])


def make_button(parent, text, cmd, kind):
    base, hover = ((C.ACCENT, C.ACCENT_HOVER) if kind == "primary"
                   else (C.DANGER, C.DANGER_HOVER))
    b = tk.Button(parent, text=text, command=cmd, bg=base, fg="white",
                  activebackground=hover, activeforeground="white",
                  disabledforeground="white", relief="flat", bd=0,
                  font=("Segoe UI", 9, "bold"), padx=10, pady=4,
                  cursor="hand2")
    b.bind("<Enter>", lambda e: b["state"] == "normal" and b.config(bg=hover))
    b.bind("<Leave>", lambda e: b["state"] == "normal" and b.config(bg=base))
    return b


def set_button_enabled(btn, enabled, kind):
    if enabled:
        base = C.ACCENT if kind == "primary" else C.DANGER
        btn.configure(state="normal", bg=base)
    else:
        btn.configure(state="disabled", bg=C.DISABLED)


def make_field(parent, width, value="", show="", on_clear=None):
    e = tk.Entry(parent, width=width, show=show, relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C.BORDER,
                 highlightcolor=C.ACCENT,
                 font=("Segoe UI", 8), insertbackground="#333",
                 bg=C.SURFACE)
    if value:
        e.insert(0, value)
    if on_clear:
        e.bind("<KeyRelease>", lambda ev, w=e: on_clear(w))
    return e


def field_error(w):
    w.configure(highlightbackground=C.FIELD_ERROR,
                highlightcolor=C.FIELD_ERROR)


def clear_field_error(w):
    w.configure(highlightbackground=C.BORDER,
                highlightcolor=C.ACCENT)


def spin_var(var, delta, lo=1, hi=99):
    try:
        v = int(var.get())
    except (ValueError, tk.TclError):
        v = lo
    v = max(lo, min(hi, v + delta))
    var.set(str(v))
