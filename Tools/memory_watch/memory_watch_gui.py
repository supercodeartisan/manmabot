"""Memory Watch — live sensor dump; print first read and every change."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from common.bootstrap import bootstrap

bootstrap()

from memory_watch.watch_core import (
    ensure_sensors_loaded,
    fingerprint,
    format_payload,
    read_unit,
    watch_choices,
    watch_unit_by_key,
)
from ui.design_system import TEXT_MUTED, apply_classic_style


def run_memory_watch() -> int:
    root = tk.Tk()
    root.title("Memory Watch")
    root.geometry("820x720")
    root.minsize(640, 520)
    apply_classic_style(root)

    choices = watch_choices()
    key_by_label = {label: key for key, label in choices}
    labels = [label for _, label in choices]

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Memory Watch", font=("Segoe UI", 14, "bold")).pack(
        anchor="w"
    )
    ttk.Label(
        frm,
        text=(
            "Select a memory reader → Start. Shows the first snapshot, then "
            "only when the payload changes."
        ),
        foreground=TEXT_MUTED,
        wraplength=780,
    ).pack(anchor="w", pady=(2, 10))

    row = ttk.Frame(frm)
    row.pack(fill="x", pady=(0, 6))
    ttk.Label(row, text="Target").pack(side="left")
    unit_var = tk.StringVar(value=labels[0] if labels else "")
    combo = ttk.Combobox(
        row, textvariable=unit_var, values=labels, state="readonly", width=48
    )
    combo.pack(side="left", padx=(8, 12), fill="x", expand=True)

    ttk.Label(row, text="Poll ms").pack(side="left")
    poll_var = tk.IntVar(value=200)
    ttk.Spinbox(row, from_=50, to=5000, increment=50, textvariable=poll_var, width=7).pack(
        side="left", padx=(6, 0)
    )

    blurb_var = tk.StringVar(value="")
    if labels:
        try:
            blurb_var.set(watch_unit_by_key(key_by_label[labels[0]]).blurb)
        except Exception:
            pass
    ttk.Label(
        frm, textvariable=blurb_var, foreground=TEXT_MUTED, wraplength=780
    ).pack(anchor="w", pady=(0, 8))

    def _on_unit(_evt=None) -> None:
        key = key_by_label.get(unit_var.get(), "")
        try:
            blurb_var.set(watch_unit_by_key(key).blurb)
        except Exception:
            blurb_var.set("")

    combo.bind("<<ComboboxSelected>>", _on_unit)

    status_var = tk.StringVar(value="Idle — LC should be in-world.")
    ttk.Label(frm, textvariable=status_var).pack(anchor="w", pady=(0, 6))

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(0, 8))
    start_btn = ttk.Button(btns, text="Start")
    start_btn.pack(side="left")
    stop_btn = ttk.Button(btns, text="Stop", state="disabled")
    stop_btn.pack(side="left", padx=(8, 0))
    clear_btn = ttk.Button(btns, text="Clear")
    clear_btn.pack(side="left", padx=(8, 0))

    meta = ttk.Frame(frm)
    meta.pack(fill="x", pady=(0, 4))
    count_var = tk.StringVar(value="updates: 0")
    ttk.Label(meta, textvariable=count_var, foreground=TEXT_MUTED).pack(side="left")

    body = ttk.Frame(frm)
    body.pack(fill="both", expand=True)
    text = tk.Text(
        body,
        wrap="none",
        font=("Consolas", 10),
        bg="#1e1e1e",
        fg="#d4d4d4",
        insertbackground="#d4d4d4",
        relief="flat",
        padx=8,
        pady=8,
    )
    yscroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    xscroll = ttk.Scrollbar(body, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    yscroll.pack(side="right", fill="y")
    xscroll.pack(side="bottom", fill="x")
    text.pack(side="left", fill="both", expand=True)

    state = {
        "running": False,
        "thread": None,
        "stop": threading.Event(),
        "updates": 0,
    }

    def _set_status(msg: str) -> None:
        root.after(0, lambda: status_var.set(msg))

    def _append(block: str, *, scroll: bool = True) -> None:
        def _apply() -> None:
            text.insert("end", block)
            if not block.endswith("\n"):
                text.insert("end", "\n")
            if scroll:
                text.see("end")
            count_var.set(f"updates: {state['updates']}")

        root.after(0, _apply)

    def _clear() -> None:
        text.delete("1.0", "end")
        state["updates"] = 0
        count_var.set("updates: 0")

    def _set_running(on: bool) -> None:
        state["running"] = on
        start_btn.configure(state="disabled" if on else "normal")
        stop_btn.configure(state="normal" if on else "disabled")
        combo.configure(state="disabled" if on else "readonly")

    def _emit(kind: str, summary: str, payload: object, ms: float) -> None:
        state["updates"] += 1
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        header = (
            f"──────── {stamp}  #{state['updates']}  {kind}  "
            f"{summary}  ({ms:.1f} ms) ────────\n"
        )
        body_txt = format_payload(payload)
        _append(header + body_txt + "\n\n")

    def _loop(key: str, poll_ms: int) -> None:
        try:
            ensure_sensors_loaded(progress=_set_status)
        except Exception as exc:
            _set_status(f"Sensor load failed: {exc}")
            root.after(0, lambda: _set_running(False))
            return

        label = watch_unit_by_key(key).label
        _set_status(f"Watching {label}…")
        last_fp: str | None = None
        stop_evt: threading.Event = state["stop"]

        while not stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                ok, payload, summary = read_unit(key)
            except Exception as exc:
                ok, payload, summary = False, {"error": str(exc)}, f"error: {exc}"
            ms = (time.perf_counter() - t0) * 1000.0
            fp = fingerprint(payload)
            if last_fp is None:
                _emit("FIRST", summary if ok else f"FAIL {summary}", payload, ms)
                last_fp = fp
            elif fp != last_fp:
                _emit("CHANGE", summary if ok else f"FAIL {summary}", payload, ms)
                last_fp = fp
            else:
                _set_status(
                    f"Watching {label} — stable  last={summary}  poll={poll_ms}ms"
                )

            # Sleep in small slices so Stop is responsive.
            deadline = time.perf_counter() + max(0.05, poll_ms / 1000.0)
            while time.perf_counter() < deadline:
                if stop_evt.is_set():
                    break
                time.sleep(0.02)

        _set_status("Stopped.")
        root.after(0, lambda: _set_running(False))

    def _start() -> None:
        if state["running"]:
            return
        key = key_by_label.get(unit_var.get())
        if not key:
            _set_status("Select a target.")
            return
        try:
            poll_ms = max(50, min(5000, int(poll_var.get())))
        except (TypeError, ValueError):
            poll_ms = 200
            poll_var.set(200)
        state["stop"].clear()
        _set_running(True)
        th = threading.Thread(
            target=_loop, args=(key, poll_ms), name="memory-watch", daemon=True
        )
        state["thread"] = th
        th.start()

    def _stop() -> None:
        state["stop"].set()
        _set_status("Stopping…")

    def _on_close() -> None:
        state["stop"].set()
        root.destroy()

    start_btn.configure(command=_start)
    stop_btn.configure(command=_stop)
    clear_btn.configure(command=_clear)
    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_memory_watch())
