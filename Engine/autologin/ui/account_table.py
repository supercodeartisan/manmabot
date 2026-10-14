import platform
import tkinter as tk
from tkinter import ttk

from .i18n import (DEFAULT_REGION, region_display,
                   region_display_list, region_key_from_display)
from .servers import server_names_list
from .theme import C, make_field, clear_field_error

ROW_H = 32
VISIBLE_ROWS = 5


def build_account_table(parent, n, tr, accounts_data, editing,
                        lang_code, on_save=None, on_edit=None):
    for w in parent.winfo_children():
        w.destroy()

    n = max(n, 1)
    table = tk.Frame(parent, bg=C.SURFACE,
                     highlightbackground=C.BORDER, highlightthickness=1)
    table.pack(fill="x", pady=(0, 3))

    hdr_frame = tk.Frame(table, bg=C.HEADER_BG)
    hdr_frame.pack(fill="x")
    hdrs = ("", tr["email"], tr["password"], tr["region"], tr["server"])
    widths = {"": 3, tr["email"]: 19, tr["password"]: 15,
              tr["region"]: 10, tr["server"]: 13}
    for c, title in enumerate(hdrs):
        tk.Label(hdr_frame, text=title, bg=C.HEADER_BG, fg=C.HEADER_FG,
                 width=widths[title], font=("Segoe UI", 8, "bold"),
                 anchor="w").grid(row=0, column=c, padx=3, pady=3)
    btns_frame = tk.Frame(hdr_frame, bg=C.HEADER_BG)
    btns_frame.grid(row=0, column=5, padx=3)
    if editing:
        tk.Button(btns_frame, text=tr["save"], relief="flat", bd=0,
                  bg=C.ACCENT, fg="white",
                  activebackground=C.ACCENT_HOVER, activeforeground="white",
                  font=("Segoe UI", 8, "bold"), padx=8, pady=1,
                  cursor="hand2", command=on_save).pack()
    else:
        tk.Button(btns_frame, text=tr["edit"], relief="flat", bd=0,
                  bg="#6b6b6b", fg="white",
                  activebackground="#555", activeforeground="white",
                  font=("Segoe UI", 8, "bold"), padx=8, pady=1,
                  cursor="hand2", command=on_edit).pack()

    canvas = tk.Canvas(table, bg=C.SURFACE, highlightthickness=0,
                       height=VISIBLE_ROWS * ROW_H)
    vsb = tk.Scrollbar(table, orient="vertical", command=canvas.yview)
    rows_frame = tk.Frame(canvas, bg=C.SURFACE)
    rows_frame_id = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="x", expand=True)
    vsb.pack(side="right", fill="y")
    rows_frame.configure(padx=3, pady=3)

    def _on_frame_configure(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        canvas.itemconfigure(rows_frame_id, width=event.width)

    def _on_mousewheel(event):
        if platform.system() == "Windows":
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        else:
            canvas.yview_scroll(-1 * event.num, "units")

    rows_frame.bind("<Configure>", _on_frame_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    for c in range(6):
        rows_frame.columnconfigure(c, pad=4)

    rn_list = region_display_list(lang_code)
    account_rows = []
    for i in range(n):
        vals = accounts_data[i] if i < len(accounts_data) else {}
        bg = C.SURFACE if i % 2 == 0 else "#fafafa"
        row_frame = tk.Frame(rows_frame, bg=bg)
        row_frame.grid(row=i, column=0, columnspan=6, sticky="ew", pady=0)
        for c in range(6):
            row_frame.columnconfigure(c, pad=3)

        tk.Label(row_frame, text=f"#{i+1}", bg=bg, fg=C.TEXT_DIM,
                 font=("Segoe UI", 8)).grid(row=0, column=0, padx=3)

        eid = make_field(row_frame, 19, vals.get("id", ""),
                         on_clear=clear_field_error)
        eid.grid(row=0, column=1, pady=3, ipady=2, padx=1)

        epw = make_field(row_frame, 17, vals.get("pw", ""), show="\u2022",
                         on_clear=clear_field_error)
        epw.grid(row=0, column=2, pady=3, ipady=2, padx=1)

        ereg = ttk.Combobox(row_frame, values=rn_list, state="readonly", width=9)
        saved_region = vals.get("region", DEFAULT_REGION)
        saved_disp = region_display(lang_code, saved_region)
        ereg.set(saved_disp if saved_disp in rn_list else rn_list[0])
        ereg.grid(row=0, column=3, pady=3, ipady=1, padx=1)

        srv_list = server_names_list(lang_code)
        esrv = ttk.Combobox(row_frame, values=srv_list,
                            state="readonly", width=13)
        saved_srv = vals.get("server", "")
        if saved_srv in srv_list:
            esrv.set(saved_srv)
        esrv.grid(row=0, column=4, pady=3, ipady=1, padx=1)

        if not editing:
            for w in (eid, epw, esrv):
                w.configure(state="disabled")
            ereg.configure(state="disabled")

        account_rows.append({"id": eid, "pw": epw, "region": ereg, "server": esrv})

    acc_status = tk.Label(table, text="", fg=C.FIELD_ERROR, bg=C.SURFACE,
                          font=("Segoe UI", 7), anchor="w")
    acc_status.pack(fill="x", padx=6, pady=(4, 6))

    _set_row_states(account_rows, editing)

    return account_rows, acc_status


def _set_row_states(account_rows, editing):
    state = "normal" if editing else "disabled"
    for row in account_rows:
        row["id"].configure(state=state)
        row["pw"].configure(state=state, show="\u2022")
        row["server"].configure(state=state)
        row["region"].configure(state=state)


def validate_accounts(account_rows, tr, lang_code):
    import re
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    errors, seen = [], {}
    for i, row in enumerate(account_rows):
        email = row["id"].get().strip()
        pw = row["pw"].get()
        if not email:
            errors.append((i, row["id"], tr["err_email_req"]))
        elif not EMAIL_RE.match(email):
            errors.append((i, row["id"], tr["err_email_inv"]))
        elif email.lower() in seen:
            errors.append((i, row["id"],
                           tr["err_dup"].format(n=seen[email.lower()])))
        else:
            seen[email.lower()] = i + 1

        if not pw:
            errors.append((i, row["pw"], tr["err_pw_req"]))
        elif len(pw) < 4:
            errors.append((i, row["pw"], tr["err_pw_min"]))

        if not row["server"].get().strip():
            errors.append((i, row["server"], tr["err_server"]))

    for row in account_rows:
        for key in ("id", "pw", "server"):
            w = row[key]
            if "highlightbackground" in w.keys():
                clear_field_error(w)

    for i, w, msg in errors:
        if "highlightbackground" in w.keys():
            field_error(w)

    return errors
