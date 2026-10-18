"""World Nav Probe — plan routes across maps, scroll hubs, and NPC teleporters."""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from common import OUTPUT_DIR
from common.bootstrap import bootstrap

bootstrap()

from ui.design_system import BG, TEXT_MUTED, apply_classic_style
from world_nav_probe.probe import (
    Catalog,
    GoalChoice,
    catalog_report,
    goal_choices,
    load_catalog,
    plan_one,
    read_live_pose,
    sweep,
)


def run_world_nav_probe() -> int:
    root = tk.Tk()
    root.title("World Nav Probe")
    root.geometry("920x720")
    root.minsize(720, 560)
    apply_classic_style(root)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="World Nav Probe", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    ttk.Label(
        frm,
        text=(
            "Plans only. The character does not walk, click, or use a scroll. "
            "Pick a start pose and a goal, or sweep every map, hub, or NPC teleporter."
        ),
        foreground=TEXT_MUTED,
        wraplength=860,
    ).pack(anchor="w", pady=(2, 10))

    status_var = tk.StringVar(value="Loading graph…")
    ttk.Label(frm, textvariable=status_var).pack(anchor="w", pady=(0, 6))

    start = ttk.LabelFrame(frm, text="Start", padding=8)
    start.pack(fill="x", pady=(0, 8))
    map_var = tk.StringVar(value="0")
    x_var = tk.StringVar(value="0")
    y_var = tk.StringVar(value="0")
    for label, var, width in (
        ("mapId", map_var, 8),
        ("x", x_var, 8),
        ("y", y_var, 8),
    ):
        ttk.Label(start, text=label).pack(side="left")
        ttk.Entry(start, textvariable=var, width=width).pack(side="left", padx=(4, 12))
    live_btn = ttk.Button(start, text="Read live pose")
    live_btn.pack(side="left")

    opts = ttk.LabelFrame(frm, text="Planner", padding=8)
    opts.pack(fill="x", pady=(0, 8))
    scroll_var = tk.BooleanVar(value=True)
    npc_var = tk.BooleanVar(value=True)
    adena_var = tk.StringVar(value="")
    ttk.Checkbutton(opts, text="Talking scroll", variable=scroll_var).pack(side="left")
    ttk.Checkbutton(opts, text="NPC teleporters", variable=npc_var).pack(
        side="left", padx=(12, 0)
    )
    ttk.Label(opts, text="Adena cap (blank = no fare filter)").pack(side="left", padx=(16, 4))
    ttk.Entry(opts, textvariable=adena_var, width=10).pack(side="left")

    goal_row = ttk.Frame(frm)
    goal_row.pack(fill="x", pady=(0, 8))
    ttk.Label(goal_row, text="Goal").pack(side="left")
    goal_var = tk.StringVar()
    goal_combo = ttk.Combobox(goal_row, textvariable=goal_var, state="readonly", width=88)
    goal_combo.pack(side="left", padx=(8, 0), fill="x", expand=True)

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(0, 8))
    plan_btn = ttk.Button(btns, text="Plan")
    plan_btn.pack(side="left")
    sweep_maps_btn = ttk.Button(btns, text="Sweep maps")
    sweep_maps_btn.pack(side="left", padx=(8, 0))
    sweep_hubs_btn = ttk.Button(btns, text="Sweep hubs")
    sweep_hubs_btn.pack(side="left", padx=(8, 0))
    sweep_npcs_btn = ttk.Button(btns, text="Sweep NPCs")
    sweep_npcs_btn.pack(side="left", padx=(8, 0))
    catalog_btn = ttk.Button(btns, text="Catalog")
    catalog_btn.pack(side="left", padx=(8, 0))
    stop_btn = ttk.Button(btns, text="Stop", state="disabled")
    stop_btn.pack(side="left", padx=(8, 0))
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

    state: dict = {
        "catalog": None,
        "by_label": {},
        "busy": False,
        "cancel": threading.Event(),
        "report": "",
    }

    def _set_status(msg: str) -> None:
        root.after(0, lambda: status_var.set(msg))

    def _show(report: str, status: str) -> None:
        def _apply() -> None:
            state["report"] = report
            text.delete("1.0", "end")
            text.insert("1.0", report)
            status_var.set(status)
            _set_busy(False)

        root.after(0, _apply)

    def _fail(err: str) -> None:
        def _apply() -> None:
            messagebox.showerror("World Nav Probe", err)
            status_var.set("Failed.")
            _set_busy(False)

        root.after(0, _apply)

    def _set_busy(busy: bool) -> None:
        state["busy"] = busy
        run_state = "disabled" if busy else "normal"
        for btn in (
            plan_btn,
            sweep_maps_btn,
            sweep_hubs_btn,
            sweep_npcs_btn,
            catalog_btn,
            live_btn,
        ):
            btn.configure(state=run_state)
        stop_btn.configure(state="normal" if busy else "disabled")

    def _catalog() -> Catalog:
        catalog = state["catalog"]
        if catalog is None:
            raise RuntimeError("Graph is still loading.")
        return catalog

    def _start_pose() -> tuple[int, int, int]:
        try:
            return int(map_var.get()), int(x_var.get()), int(y_var.get())
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Start mapId / x / y must be integers.") from exc

    def _adena() -> int | None:
        raw = adena_var.get().strip()
        if not raw:
            return None
        try:
            return max(0, int(raw))
        except ValueError as exc:
            raise RuntimeError("Adena cap must be a number or blank.") from exc

    def _selected() -> GoalChoice:
        choice = state["by_label"].get(goal_var.get())
        if choice is None:
            raise RuntimeError("Select a goal.")
        return choice

    def _fill_goals(catalog: Catalog) -> None:
        labels = [c.label for c in catalog.goals]
        state["by_label"] = {c.label: c for c in catalog.goals}
        goal_combo.configure(values=labels)
        if labels and not goal_var.get():
            goal_var.set(labels[0])

    def _load() -> None:
        try:
            catalog = load_catalog()
        except Exception as exc:
            _fail(str(exc))
            return

        def _apply() -> None:
            state["catalog"] = catalog
            _fill_goals(catalog)
            maps = sum(1 for c in catalog.goals if c.key.startswith("map:"))
            hubs = sum(1 for c in catalog.goals if c.key.startswith("hub:"))
            npcs = sum(1 for c in catalog.goals if c.key.startswith("npc:"))
            status_var.set(f"Ready — {maps} maps, {hubs} hubs, {npcs} NPC links.")

        root.after(0, _apply)

    def _run(worker) -> None:
        if state["busy"]:
            return
        state["cancel"].clear()
        _set_busy(True)
        status_var.set("Running…")
        threading.Thread(target=worker, daemon=True, name="world-nav-probe").start()

    def _on_live() -> None:
        def worker() -> None:
            try:
                mid, x, y = read_live_pose()
            except Exception as exc:
                _fail(str(exc))
                return

            def _apply() -> None:
                map_var.set(str(mid))
                x_var.set(str(x))
                y_var.set(str(y))
                status_var.set(f"Live pose  map {mid} ({x},{y})")
                _set_busy(False)

            root.after(0, _apply)

        _run(worker)

    def _on_plan() -> None:
        def worker() -> None:
            try:
                report = plan_one(
                    _catalog(),
                    _start_pose(),
                    _selected(),
                    has_talking_scroll=bool(scroll_var.get()),
                    adena=_adena(),
                    use_npc_teleporters=bool(npc_var.get()),
                )
            except Exception as exc:
                _fail(str(exc))
                return
            _show(report, "Plan done.")

        _run(worker)

    def _on_sweep(scope: str) -> None:
        def worker() -> None:
            try:
                catalog = _catalog()
                choices = goal_choices(catalog, scope=scope)
                if not choices:
                    raise RuntimeError(f"No {scope} in the graph.")
                report = sweep(
                    catalog,
                    _start_pose(),
                    choices,
                    has_talking_scroll=bool(scroll_var.get()),
                    adena=_adena(),
                    use_npc_teleporters=bool(npc_var.get()),
                    progress=_set_status,
                    cancelled=state["cancel"].is_set,
                )
            except Exception as exc:
                _fail(str(exc))
                return
            done = "Stopped." if state["cancel"].is_set() else "Sweep done."
            _show(report, done)

        _run(worker)

    def _on_catalog() -> None:
        def worker() -> None:
            try:
                report = catalog_report(_catalog())
            except Exception as exc:
                _fail(str(exc))
                return
            _show(report, "Catalog ready.")

        _run(worker)

    def _on_stop() -> None:
        state["cancel"].set()
        status_var.set("Stopping after the current plan…")

    def _on_save() -> None:
        report = str(state["report"]).strip()
        if not report:
            messagebox.showinfo("World Nav Probe", "Nothing to save yet.")
            return
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(OUTPUT_DIR) / f"world_nav_probe_{stamp}.txt"
        path.write_text(report + "\n", encoding="utf-8")
        messagebox.showinfo("World Nav Probe", f"Saved:\n{path}")

    def _on_clear() -> None:
        text.delete("1.0", "end")
        state["report"] = ""
        catalog = state["catalog"]
        if catalog is None:
            status_var.set("Loading graph…")
            return
        maps = sum(1 for c in catalog.goals if c.key.startswith("map:"))
        hubs = sum(1 for c in catalog.goals if c.key.startswith("hub:"))
        npcs = sum(1 for c in catalog.goals if c.key.startswith("npc:"))
        status_var.set(f"Ready — {maps} maps, {hubs} hubs, {npcs} NPC links.")

    live_btn.configure(command=_on_live)
    plan_btn.configure(command=_on_plan)
    sweep_maps_btn.configure(command=lambda: _on_sweep("maps"))
    sweep_hubs_btn.configure(command=lambda: _on_sweep("hubs"))
    sweep_npcs_btn.configure(command=lambda: _on_sweep("npcs"))
    catalog_btn.configure(command=_on_catalog)
    stop_btn.configure(command=_on_stop)
    save_btn.configure(command=_on_save)
    clear_btn.configure(command=_on_clear)

    root.configure(bg=BG)
    threading.Thread(target=_load, daemon=True, name="world-nav-catalog").start()
    root.mainloop()
    return 0
