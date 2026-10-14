"""Memory Read Bench — pick a sensor unit, time it, read the report."""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from common import OUTPUT_DIR
from common.bootstrap import bootstrap

bootstrap()

from memory_bench.bench_core import UNITS, bench_unit, unit_by_key, unit_choices
from ui.design_system import BG, TEXT_MUTED, apply_classic_style


def run_memory_bench() -> int:
    root = tk.Tk()
    root.title("Memory Read Bench")
    root.geometry("720x640")
    root.minsize(560, 480)
    apply_classic_style(root)

    choices = unit_choices()
    key_by_label = {label: key for key, label in choices}
    labels = [label for _, label in choices]

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Memory Read Bench", font=("Segoe UI", 14, "bold")).pack(
        anchor="w"
    )
    ttk.Label(
        frm,
        text=(
            "Choose a memory unit → Run. Times are milliseconds for one live read "
            "(no screen render / no bot control)."
        ),
        foreground=TEXT_MUTED,
        wraplength=680,
    ).pack(anchor="w", pady=(2, 10))

    row = ttk.Frame(frm)
    row.pack(fill="x", pady=(0, 6))
    ttk.Label(row, text="Unit").pack(side="left")
    unit_var = tk.StringVar(value=labels[0])
    combo = ttk.Combobox(
        row, textvariable=unit_var, values=labels, state="readonly", width=48
    )
    combo.pack(side="left", padx=(8, 0), fill="x", expand=True)

    blurb_var = tk.StringVar(value=UNITS[0].blurb)
    ttk.Label(
        frm, textvariable=blurb_var, foreground=TEXT_MUTED, wraplength=680
    ).pack(anchor="w", pady=(0, 8))

    def _on_unit(_evt=None) -> None:
        key = key_by_label.get(unit_var.get(), UNITS[0].key)
        try:
            blurb_var.set(unit_by_key(key).blurb)
        except KeyError:
            blurb_var.set("")

    combo.bind("<<ComboboxSelected>>", _on_unit)

    opts = ttk.Frame(frm)
    opts.pack(fill="x", pady=(0, 8))
    ttk.Label(opts, text="Iterations").pack(side="left")
    iter_var = tk.IntVar(value=20)
    ttk.Spinbox(opts, from_=1, to=500, textvariable=iter_var, width=6).pack(
        side="left", padx=(6, 16)
    )
    ttk.Label(opts, text="Warmup").pack(side="left")
    warm_var = tk.IntVar(value=2)
    ttk.Spinbox(opts, from_=0, to=50, textvariable=warm_var, width=6).pack(
        side="left", padx=(6, 0)
    )

    status_var = tk.StringVar(value="Idle — game should be in-world.")
    ttk.Label(frm, textvariable=status_var).pack(anchor="w", pady=(0, 6))

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(0, 8))
    run_btn = ttk.Button(btns, text="Run")
    run_btn.pack(side="left")
    save_btn = ttk.Button(btns, text="Save report")
    save_btn.pack(side="left", padx=(8, 0))
    clear_btn = ttk.Button(btns, text="Clear")
    clear_btn.pack(side="left", padx=(8, 0))

    body = ttk.Frame(frm)
    body.pack(fill="both", expand=True)
    text = tk.Text(
        body,
        wrap="word",
        font=("Consolas", 10),
        bg="#1e1e1e",
        fg="#d4d4d4",
        insertbackground="#d4d4d4",
        relief="flat",
        padx=8,
        pady=8,
    )
    scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    last_report: list[str] = [""]
    busy = {"v": False}

    def _set_status(msg: str) -> None:
        root.after(0, lambda: status_var.set(msg))

    def _show_report(report: str) -> None:
        def _apply() -> None:
            last_report[0] = report
            text.delete("1.0", "end")
            text.insert("1.0", report)
            status_var.set("Done.")
            run_btn.configure(state="normal")
            busy["v"] = False

        root.after(0, _apply)

    def _fail(err: str) -> None:
        def _apply() -> None:
            messagebox.showerror("Memory Read Bench", err)
            status_var.set("Failed.")
            run_btn.configure(state="normal")
            busy["v"] = False

        root.after(0, _apply)

    def _run() -> None:
        if busy["v"]:
            return
        key = key_by_label.get(unit_var.get())
        if not key:
            messagebox.showwarning("Memory Read Bench", "Select a unit.")
            return
        try:
            iterations = max(1, int(iter_var.get()))
            warmup = max(0, int(warm_var.get()))
        except (TypeError, ValueError):
            messagebox.showwarning("Memory Read Bench", "Bad iterations/warmup.")
            return
        busy["v"] = True
        run_btn.configure(state="disabled")
        status_var.set("Running…")
        text.delete("1.0", "end")
        text.insert("1.0", "Running…\n")

        def worker() -> None:
            try:
                from session.elevate import prepare_runtime

                prepare_runtime()
            except Exception:
                pass
            try:
                report = bench_unit(
                    key,
                    iterations=iterations,
                    warmup=warmup,
                    progress=_set_status,
                )
                _show_report(report)
            except Exception as exc:
                _fail(str(exc))

        threading.Thread(target=worker, daemon=True, name="memory-bench").start()

    def _save() -> None:
        report = last_report[0].strip()
        if not report:
            messagebox.showinfo("Memory Read Bench", "Nothing to save yet.")
            return
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(OUTPUT_DIR) / f"memory_bench_{stamp}.txt"
        path.write_text(report + "\n", encoding="utf-8")
        messagebox.showinfo("Memory Read Bench", f"Saved:\n{path}")

    def _clear() -> None:
        text.delete("1.0", "end")
        last_report[0] = ""
        status_var.set("Idle — game should be in-world.")

    run_btn.configure(command=_run)
    save_btn.configure(command=_save)
    clear_btn.configure(command=_clear)

    root.configure(bg=BG)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_memory_bench())
