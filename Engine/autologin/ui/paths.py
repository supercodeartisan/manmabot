import tkinter as tk

from .theme import C


def build_paths(body, tr, path_var, lineage_var, browse_purple, browse_lineage):
    pf = tk.Frame(body, bg=C.SURFACE,
                  highlightbackground=C.BORDER, highlightthickness=1)
    pf.pack(fill="x", pady=(0, 8))

    inner = tk.Frame(pf, bg=C.SURFACE)
    inner.pack(fill="x", padx=10, pady=8)
    inner.columnconfigure(1, weight=1)

    tk.Label(inner, text=tr["game"] + ":", bg=C.SURFACE,
             fg=C.TEXT_DIM, font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
    pe = tk.Entry(inner, textvariable=path_var, relief="flat", bd=0,
                  font=("Consolas", 9), highlightthickness=1,
                  highlightbackground=C.BORDER, highlightcolor=C.ACCENT)
    pe.grid(row=0, column=1, padx=(6, 0), ipady=2, sticky="ew")
    tk.Button(inner, text=tr["browse"], relief="flat", bd=0,
              bg=C.ACCENT_LIGHT, fg=C.ACCENT,
              activebackground=C.ACCENT, activeforeground="#fff",
              font=("Segoe UI", 8, "bold"), padx=8, pady=2,
              cursor="hand2", command=browse_purple
              ).grid(row=0, column=2, padx=(4, 0))

    tk.Label(inner, text=tr["lineage_game"] + ":", bg=C.SURFACE,
             fg=C.TEXT_DIM, font=("Segoe UI", 8)
             ).grid(row=1, column=0, sticky="w", pady=(5, 0))
    le = tk.Entry(inner, textvariable=lineage_var, relief="flat", bd=0,
                  font=("Consolas", 9), highlightthickness=1,
                  highlightbackground=C.BORDER, highlightcolor=C.ACCENT)
    le.grid(row=1, column=1, padx=(6, 0), ipady=2, sticky="ew", pady=(5, 0))
    tk.Button(inner, text=tr["browse"], relief="flat", bd=0,
              bg=C.ACCENT_LIGHT, fg=C.ACCENT,
              activebackground=C.ACCENT, activeforeground="#fff",
              font=("Segoe UI", 8, "bold"), padx=8, pady=2,
              cursor="hand2", command=browse_lineage
              ).grid(row=1, column=2, padx=(4, 0), pady=(5, 0))

    return pf
