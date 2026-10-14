"""NPC click-offset calibrator — bot data editor.

Capture the game content frame next to a registered shopping NPC, draw
candidate point A from (player tile, NPC tile) → content UV, then let the
operator click the true click spot B. Saves ``click_offset_uv`` (= B − A)
straight into ``Engine/data/npc_behaviors.yaml``.

Modes:
- Live: player world tile from memory monitor.
- Offline: operator types player world tile (memory not required).
  Frame capture still needs LC visible for clicking B.

Live ``open_shop_npc`` uses that field for a single click when present;
otherwise it keeps cursor-search open.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Optional

from shop.behaviors import (
    ACTION_BUY,
    ACTION_SELL,
    ACTION_STORE,
    ACTION_TELEPORTER,
    BEHAVIORS_PATH,
    ShoppingBehavior,
    load_behaviors,
    update_click_offset_uv,
)
from ui.design_system import TEXT_MUTED, apply_classic_style

_FILTER_VALUES = (
    ACTION_TELEPORTER,
    ACTION_BUY,
    ACTION_SELL,
    ACTION_STORE,
    "all",
)

_MODE_LIVE = "live"
_MODE_OFFLINE = "offline"


def compute_candidate_a(
    behavior: ShoppingBehavior,
    *,
    player_game: Optional[tuple[int, int]] = None,
) -> dict[str, Any]:
    """Player + NPC world tiles → content UV and relative nav tiles.

    ``player_game`` overrides the live memory read (offline calibrator).
    """
    from app._02_state.geometry import WorldOrigin
    from app._03_world.merge.memory_sync import game_to_nav
    from shop.runtime import ensure_behavior_map_origin, npc_content_uv

    ensure_behavior_map_origin(behavior)
    if player_game is None:
        from shopping.memory_fill import read_player_game_xy

        gx, gy = read_player_game_xy()
    else:
        gx, gy = int(player_game[0]), int(player_game[1])
    px, py = game_to_nav(gx, gy)
    origin = WorldOrigin(x=int(px), y=int(py))
    uv = npc_content_uv(behavior, origin)
    nx, ny = game_to_nav(behavior.npc_world_x, behavior.npc_world_y)
    return {
        "player_game": (int(gx), int(gy)),
        "player_nav": (int(px), int(py)),
        "npc_game": (int(behavior.npc_world_x), int(behavior.npc_world_y)),
        "npc_nav": (int(nx), int(ny)),
        "a_uv": (float(uv.x), float(uv.y)),
        "rel_nav": (int(nx - px), int(ny - py)),
    }


class NpcClickOffsetCalibrator(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NPC Click Offset — bot data editor")
        self.geometry("1180x760")
        self.minsize(960, 600)
        apply_classic_style(self)

        self._all_behaviors: list[ShoppingBehavior] = []
        self._behaviors: list[ShoppingBehavior] = []
        self._selected: Optional[ShoppingBehavior] = None
        self._frame = None  # BGR
        self._photo = None
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._scale = 1.0
        self._offset = (0.0, 0.0)
        self._img_size = (0, 0)
        self._a: Optional[dict[str, Any]] = None
        self._b_uv: Optional[tuple[float, float]] = None
        self._b_px: Optional[tuple[float, float]] = None
        self._drag_pan = False
        self._drag_start = (0, 0)
        self._drag_pan0 = (0.0, 0.0)

        self.status_var = tk.StringVar(self, value="")
        self.filter_var = tk.StringVar(self, value=ACTION_TELEPORTER)
        self.mode_var = tk.StringVar(self, value=_MODE_LIVE)
        self.player_x_var = tk.StringVar(self, value="")
        self.player_y_var = tk.StringVar(self, value="")
        self.zoom_label_var = tk.StringVar(self, value="100%")
        self.info_var = tk.StringVar(self, value="")
        self.help_var = tk.StringVar(self, value="")
        self.stored_badge_var = tk.StringVar(self, value="")
        self.a_var = tk.StringVar(self, value="A: —")
        self.b_var = tk.StringVar(self, value="B: —")
        self.delta_var = tk.StringVar(self, value="Δ: —")
        self.path_var = tk.StringVar(self, value=str(BEHAVIORS_PATH))

        self._build()
        self._apply_mode_ui()
        self._reload_behaviors()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _log(self, message: str) -> None:
        self.status_var.set(message)

    def _is_offline(self) -> bool:
        return str(self.mode_var.get() or "").strip().lower() == _MODE_OFFLINE

    def _build(self) -> None:
        root = ttk.Frame(self, padding=6)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(2, weight=1)

        left = ttk.Frame(root)
        left.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 8))
        ttk.Label(left, text="NPC / behavior", style="Chrome.TLabel").pack(anchor="w")
        filt = ttk.Frame(left)
        filt.pack(fill="x", pady=(2, 4))
        ttk.Combobox(
            filt,
            textvariable=self.filter_var,
            values=_FILTER_VALUES,
            state="readonly",
            width=12,
        ).pack(side="left")
        ttk.Button(filt, text="Reload", command=self._reload_behaviors).pack(
            side="left", padx=(4, 0)
        )
        self.listbox = tk.Listbox(left, width=36, height=28, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        top = ttk.Frame(root, style="Chrome.TFrame")
        top.grid(row=0, column=1, sticky="ew")
        mode_row = ttk.Frame(top)
        mode_row.pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            mode_row,
            text="Live",
            value=_MODE_LIVE,
            variable=self.mode_var,
            command=self._on_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="Offline",
            value=_MODE_OFFLINE,
            variable=self.mode_var,
            command=self._on_mode_change,
        ).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="Recapture + A", command=self.recapture).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="Recompute A", command=self.recompute_a).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="Clear B", command=self.clear_b).pack(side="left", padx=2)
        ttk.Button(top, text="Zoom -", command=lambda: self._zoom_by(1 / 1.25)).pack(
            side="left", padx=2
        )
        ttk.Label(top, textvariable=self.zoom_label_var, width=5).pack(side="left")
        ttk.Button(top, text="Zoom +", command=lambda: self._zoom_by(1.25)).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="Reset zoom", command=self._zoom_reset).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="Clear stored", command=self.clear_stored_offset).pack(
            side="right", padx=2
        )
        ttk.Button(
            top, text="Δ → same NPC", command=self.copy_delta_to_same_npc
        ).pack(side="right", padx=2)
        ttk.Button(
            top, text="Paste Δ from…", command=self.paste_delta_from
        ).pack(side="right", padx=2)
        ttk.Button(top, text="Copy Δ text", command=self.copy_delta).pack(
            side="right", padx=2
        )
        ttk.Button(top, text="Save → YAML", command=self.save_offset).pack(
            side="right", padx=2
        )

        self.offline_bar = ttk.Frame(root, style="Chrome.TFrame")
        self.offline_bar.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        ttk.Label(
            self.offline_bar,
            text="Player world XY",
            style="Chrome.TLabel",
        ).pack(side="left", padx=(0, 4))
        ttk.Entry(self.offline_bar, textvariable=self.player_x_var, width=8).pack(
            side="left"
        )
        ttk.Label(self.offline_bar, text=",", style="Chrome.TLabel").pack(
            side="left", padx=2
        )
        ttk.Entry(self.offline_bar, textvariable=self.player_y_var, width=8).pack(
            side="left"
        )
        ttk.Button(
            self.offline_bar,
            text="Apply → A",
            command=self.recompute_a,
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            self.offline_bar,
            text="(memory unused; LC still needed for Recapture)",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=(8, 0))

        mid = ttk.Frame(root)
        mid.grid(row=2, column=1, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(mid, background="#1a1d23", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Button-1>", self._on_left)
        self.canvas.bind("<Button-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        side = ttk.Frame(mid, padding=(8, 0, 0, 0))
        side.grid(row=0, column=1, sticky="ns")
        ttk.Label(
            side,
            textvariable=self.help_var,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.stored_badge = tk.Label(
            side,
            textvariable=self.stored_badge_var,
            justify="left",
            wraplength=260,
            font=("Segoe UI", 10, "bold"),
            bg=self.cget("bg") if self.cget("bg") else "#f0f0f0",
            fg="#15803d",
        )
        self.stored_badge.pack(anchor="w", pady=(0, 6))
        ttk.Label(side, textvariable=self.info_var, justify="left", wraplength=260).pack(
            anchor="w", pady=2
        )
        ttk.Separator(side).pack(fill="x", pady=6)
        ttk.Label(side, textvariable=self.a_var, justify="left", wraplength=260).pack(
            anchor="w", pady=2
        )
        ttk.Label(side, textvariable=self.b_var, justify="left", wraplength=260).pack(
            anchor="w", pady=2
        )
        ttk.Label(
            side,
            textvariable=self.delta_var,
            justify="left",
            wraplength=260,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=4)
        ttk.Label(
            side,
            textvariable=self.path_var,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
            wraplength=260,
        ).pack(anchor="w", pady=(12, 0))

        bot = ttk.Frame(root, style="Chrome.TFrame")
        bot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(bot, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )
        self.filter_var.trace_add("write", lambda *_: self._reload_behaviors())

    def _on_mode_change(self) -> None:
        self._a = None
        self._apply_mode_ui()
        self._refresh_labels()
        self._redraw()
        mode = "Offline" if self._is_offline() else "Live"
        self._log(f"Mode → {mode}")

    def _apply_mode_ui(self) -> None:
        offline = self._is_offline()
        mark_help = (
            "[Δ] = click_offset_uv stored (skip)\n"
            "[ ] = not stored yet\n"
            "Paste Δ from… = reuse another Δ\n"
            "Δ → same NPC = copy to siblings"
        )
        if offline:
            self.offline_bar.grid(row=1, column=1, sticky="ew", pady=(4, 0))
            self.help_var.set(
                "Offline:\n"
                "1) Stand near the NPC (game on)\n"
                "2) Enter your world XY\n"
                "3) Recapture + A (or Apply → A)\n"
                "4) Left-click true click spot B\n"
                "5) Save → npc_behaviors.yaml\n"
                "Right-drag = pan, wheel = zoom\n"
                + mark_help
            )
        else:
            self.offline_bar.grid_remove()
            self.help_var.set(
                "Live:\n"
                "1) Stand near the NPC\n"
                "2) Recapture + A\n"
                "3) Left-click true click spot B\n"
                "4) Save → npc_behaviors.yaml\n"
                "Right-drag = pan, wheel = zoom\n"
                + mark_help
            )

    def _manual_player_game(self) -> tuple[int, int]:
        """Parse offline player world XY entries."""
        raw_x = str(self.player_x_var.get() or "").strip()
        raw_y = str(self.player_y_var.get() or "").strip()
        if not raw_x or not raw_y:
            raise ValueError("Offline mode needs player world X and Y")
        try:
            gx = int(float(raw_x))
            gy = int(float(raw_y))
        except ValueError as exc:
            raise ValueError("Player world XY must be integers") from exc
        return gx, gy

    def _player_game_for_a(self) -> Optional[tuple[int, int]]:
        """None → live memory; tuple → offline override."""
        if not self._is_offline():
            return None
        return self._manual_player_game()

    @staticmethod
    def _npc_key(b: ShoppingBehavior) -> tuple[str, int, int]:
        return (str(b.map_id), int(b.npc_world_x), int(b.npc_world_y))

    def _list_label(self, b: ShoppingBehavior) -> str:
        mark = "[Δ]" if b.has_click_offset() else "[ ]"
        return f"{mark} {b.id}  [{b.action}]  ({b.npc_world_x},{b.npc_world_y})"

    def _color_list_marks(self) -> None:
        """Green for stored Δ, muted for missing (Windows listbox fg)."""
        for i, b in enumerate(self._behaviors):
            if b.has_click_offset():
                self.listbox.itemconfigure(i, foreground="#15803d")
            else:
                self.listbox.itemconfigure(i, foreground="#6b7280")

    def _reload_behaviors(self) -> None:
        try:
            all_b = load_behaviors()
        except Exception as exc:
            self._log(f"Load behaviors failed: {exc}")
            all_b = []
        self._all_behaviors = list(all_b)
        mode = str(self.filter_var.get() or ACTION_TELEPORTER).strip().lower()
        if mode == "all":
            self._behaviors = list(all_b)
        else:
            self._behaviors = [b for b in all_b if b.action == mode]
        self.listbox.delete(0, "end")
        for b in self._behaviors:
            self.listbox.insert("end", self._list_label(b))
        self._color_list_marks()
        if self._selected is not None:
            want = self._selected.id
            for i, b in enumerate(self._behaviors):
                if b.id == want:
                    self._selected = b
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    break
            else:
                self._selected = None
        self._refresh_labels()
        with_d = sum(1 for b in self._behaviors if b.has_click_offset())
        self._log(
            f"{len(self._behaviors)} behaviors ({mode}) — "
            f"{with_d} with [Δ], {len(self._behaviors) - with_d} need Δ"
        )

    def _on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._behaviors):
            return
        self._selected = self._behaviors[idx]
        self._b_uv = None
        self._b_px = None
        self._a = None
        self._refresh_labels()
        self._redraw()
        self._log(f"Selected {self._selected.id}")

    def recapture(self) -> None:
        if self._selected is None:
            messagebox.showinfo(
                "NPC offset", "Select a behavior first.", parent=self
            )
            return
        try:
            from session.perception_capture import (
                grab_perception_frame,
                open_perception_capture,
            )

            capture = open_perception_capture()
            try:
                frame = grab_perception_frame(capture, retries=40, wait_s=0.05)
            finally:
                close = getattr(capture, "stop", None) or getattr(capture, "close", None)
                if callable(close):
                    close()
            if frame is None:
                raise RuntimeError("No game frame — make sure LC.exe is visible")
            self._frame = frame
            self._zoom = 1.0
            self._pan = (0.0, 0.0)
            self.zoom_label_var.set("100%")
            self._b_uv = None
            self._b_px = None
            self.recompute_a(silent=True)
            self._redraw()
            h, w = frame.shape[:2]
            self._log(f"Captured {w}x{h}")
            self.canvas.focus_set()
        except Exception as exc:
            messagebox.showwarning("NPC offset", str(exc), parent=self)
            self._log(f"Recapture failed: {exc}")

    def recompute_a(self, *, silent: bool = False) -> None:
        if self._selected is None:
            if not silent:
                messagebox.showinfo(
                    "NPC offset", "Select a behavior first.", parent=self
                )
            return
        try:
            player_game = self._player_game_for_a()
            self._a = compute_candidate_a(
                self._selected, player_game=player_game
            )
            self._refresh_labels()
            self._redraw()
            if not silent:
                if player_game is None:
                    self._log("Recomputed A from live player + NPC tiles")
                else:
                    self._log(
                        f"Recomputed A from manual player "
                        f"({player_game[0]}, {player_game[1]}) + NPC tiles"
                    )
        except Exception as exc:
            self._a = None
            self._refresh_labels()
            self._redraw()
            if not silent:
                messagebox.showwarning("NPC offset", str(exc), parent=self)
            self._log(f"A failed: {exc}")

    def clear_b(self) -> None:
        self._b_uv = None
        self._b_px = None
        self._refresh_labels()
        self._redraw()

    def _set_stored_badge(self, b: Optional[ShoppingBehavior]) -> None:
        if b is None:
            self.stored_badge_var.set("")
            return
        if b.click_offset_uv is not None:
            du, dv = b.click_offset_uv
            self.stored_badge_var.set(
                f"[Δ] STORED — already calibrated\n"
                f"Δuv = ({du:+.6f}, {dv:+.6f})\n"
                f"(no need to recalculate unless wrong)"
            )
            self.stored_badge.configure(fg="#15803d")
        else:
            siblings = self._same_npc_siblings(b, with_offset_only=True)
            if siblings:
                src = siblings[0]
                assert src.click_offset_uv is not None
                du, dv = src.click_offset_uv
                self.stored_badge_var.set(
                    f"[ ] NOT STORED — needs Δ\n"
                    f"Same NPC has Δ on {src.id}\n"
                    f"({du:+.6f}, {dv:+.6f}) — use Paste Δ from…"
                )
            else:
                self.stored_badge_var.set(
                    "[ ] NOT STORED — needs Δ\n"
                    "(open falls back to cursor search)"
                )
            self.stored_badge.configure(fg="#b45309")

    def _same_npc_siblings(
        self,
        b: ShoppingBehavior,
        *,
        with_offset_only: bool = False,
        include_self: bool = False,
    ) -> list[ShoppingBehavior]:
        key = self._npc_key(b)
        out: list[ShoppingBehavior] = []
        for other in self._all_behaviors:
            if not include_self and other.id == b.id:
                continue
            if self._npc_key(other) != key:
                continue
            if with_offset_only and not other.has_click_offset():
                continue
            out.append(other)
        return out

    def _refresh_labels(self) -> None:
        b = self._selected
        self._set_stored_badge(b)
        if b is None:
            self.info_var.set("No behavior selected")
            self.a_var.set("A: —")
            self.b_var.set("B: —")
            self.delta_var.set("Δ: —")
            return
        mode = "offline" if self._is_offline() else "live"
        sib_n = len(self._same_npc_siblings(b, include_self=True))
        lines = [
            f"mode: {mode}",
            f"id: {b.id}",
            f"name: {b.name}",
            f"map: {b.map_id}",
            f"npc_world: ({b.npc_world_x}, {b.npc_world_y})",
            f"same-NPC behaviors: {sib_n}",
        ]
        if b.click_offset_uv is not None:
            du, dv = b.click_offset_uv
            lines.append(f"stored Δuv: ({du:+.6f}, {dv:+.6f})")
        else:
            lines.append("stored Δuv: (none → cursor search)")
        a = self._a
        if a is None:
            self.info_var.set("\n".join(lines))
            if self._is_offline():
                self.a_var.set("A: (enter world XY → Apply / Recapture)")
            else:
                self.a_var.set("A: (capture / recompute)")
            self.b_var.set("B: —")
            if b.click_offset_uv is not None:
                du, dv = b.click_offset_uv
                self.delta_var.set(
                    f"stored Δ uv = ({du:+.6f}, {dv:+.6f})\n"
                    f"(session A/B empty — already saved)"
                )
            else:
                self.delta_var.set("Δ: — (not stored)")
            return
        pg, pn = a["player_game"], a["player_nav"]
        ng, nn = a["npc_game"], a["npc_nav"]
        au, av = a["a_uv"]
        rx, ry = a["rel_nav"]
        src = "manual" if self._is_offline() else "live"
        lines.extend(
            [
                f"player game ({src}): ({pg[0]}, {pg[1]})",
                f"player nav: ({pn[0]}, {pn[1]})",
                f"npc nav: ({nn[0]}, {nn[1]})  Δnav ({rx}, {ry})",
            ]
        )
        self.info_var.set("\n".join(lines))
        apx = apy = None
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            apx, apy = au * w, av * h
            self.a_var.set(
                f"A uv=({au:.5f}, {av:.5f})\n"
                f"A px=({apx:.1f}, {apy:.1f})  on {w}x{h}"
            )
        else:
            self.a_var.set(f"A uv=({au:.5f}, {av:.5f})\nA px= (need capture)")

        if self._b_uv is None or self._b_px is None:
            self.b_var.set("B: click image")
            if b.click_offset_uv is not None:
                du, dv = b.click_offset_uv
                self.delta_var.set(
                    f"stored Δ uv = ({du:+.6f}, {dv:+.6f})\n"
                    f"(click B only to overwrite)"
                )
            else:
                self.delta_var.set("Δ: — (not stored)")
            return
        bu, bv = self._b_uv
        bx, by = self._b_px
        self.b_var.set(
            f"B uv=({bu:.5f}, {bv:.5f})\nB px=({bx:.1f}, {by:.1f})"
        )
        if apx is None or apy is None:
            self.delta_var.set("Δ: —")
            return
        dpx, dpy = bx - apx, by - apy
        du, dv = bu - au, bv - av
        self.delta_var.set(
            f"Δ px = ({dpx:+.1f}, {dpy:+.1f})\n"
            f"Δ uv = ({du:+.6f}, {dv:+.6f})\n"
            f"(open click = A + Δ)"
        )

    def _current_delta_uv(self) -> Optional[tuple[float, float]]:
        if self._selected is None or self._a is None:
            return None
        if self._b_uv is None:
            return None
        au, av = self._a["a_uv"]
        bu, bv = self._b_uv
        return (float(bu - au), float(bv - av))

    def copy_delta(self) -> None:
        duv = self._current_delta_uv()
        if duv is None and self._selected is not None:
            duv = self._selected.click_offset_uv
        if duv is None or self._selected is None:
            messagebox.showinfo(
                "NPC offset",
                "Need a session Δ (A+B) or a stored click_offset_uv.",
                parent=self,
            )
            return
        text = (
            f"{self._selected.id}\n"
            f"click_offset_uv: [{duv[0]:+.6f}, {duv[1]:+.6f}]\n"
        )
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log("Copied Δ to clipboard")

    def _offset_sources_sorted(
        self, target: ShoppingBehavior
    ) -> list[ShoppingBehavior]:
        """Behaviors that already have Δ, same-NPC first."""
        key = self._npc_key(target)
        sources = [
            b
            for b in self._all_behaviors
            if b.has_click_offset() and b.id != target.id
        ]

        def sort_key(b: ShoppingBehavior) -> tuple:
            same = 0 if self._npc_key(b) == key else 1
            same_action = 0 if b.action == target.action else 1
            return (same, same_action, b.action, b.id)

        return sorted(sources, key=sort_key)

    def paste_delta_from(self) -> None:
        """Copy stored click_offset_uv from another behavior onto the selection."""
        if self._selected is None:
            messagebox.showinfo(
                "NPC offset", "Select a target behavior first.", parent=self
            )
            return
        target = self._selected
        sources = self._offset_sources_sorted(target)
        if not sources:
            messagebox.showinfo(
                "NPC offset",
                "No other behavior has a stored click_offset_uv yet.\n"
                "Calibrate one first, then paste/reuse it.",
                parent=self,
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Paste Δ from…")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("520x360")
        ttk.Label(
            dlg,
            text=(
                f"Target: {target.id}\n"
                f"Pick a source with [Δ]. Same-NPC entries are listed first."
            ),
            justify="left",
        ).pack(anchor="w", padx=8, pady=8)
        lb = tk.Listbox(dlg, exportselection=False)
        lb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for src in sources:
            same = "same-NPC" if self._npc_key(src) == self._npc_key(target) else "other"
            assert src.click_offset_uv is not None
            du, dv = src.click_offset_uv
            lb.insert(
                "end",
                f"[Δ] {src.id}  [{src.action}]  {same}  "
                f"Δ=({du:+.5f},{dv:+.5f})",
            )
            if same == "same-NPC":
                lb.itemconfigure(lb.size() - 1, foreground="#15803d")
        if sources:
            lb.selection_set(0)
            lb.see(0)

        def apply_pick() -> None:
            sel = lb.curselection()
            if not sel:
                return
            src = sources[int(sel[0])]
            assert src.click_offset_uv is not None
            duv = src.click_offset_uv
            try:
                updated = update_click_offset_uv(target.id, duv)
                self._selected = updated
                self._reload_behaviors()
                self._log(
                    f"Pasted Δ from {src.id} → {updated.id} "
                    f"[{duv[0]:+.6f}, {duv[1]:+.6f}]"
                )
                dlg.destroy()
                messagebox.showinfo(
                    "NPC offset",
                    f"Copied click_offset_uv\n"
                    f"{src.id} → {updated.id}\n"
                    f"[{duv[0]:+.6f}, {duv[1]:+.6f}]",
                    parent=self,
                )
            except Exception as exc:
                messagebox.showwarning("NPC offset", str(exc), parent=dlg)

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Paste → target", command=apply_pick).pack(
            side="right", padx=(0, 6)
        )
        lb.bind("<Double-Button-1>", lambda _e: apply_pick())

    def copy_delta_to_same_npc(self) -> None:
        """Apply this behavior's Δ to other behaviors on the same NPC tile."""
        if self._selected is None:
            messagebox.showinfo(
                "NPC offset", "Select a behavior first.", parent=self
            )
            return
        src = self._selected
        duv = self._current_delta_uv() or src.click_offset_uv
        if duv is None:
            messagebox.showinfo(
                "NPC offset",
                "This behavior has no Δ yet.\n"
                "Calibrate A+B (or Paste Δ from…) first.",
                parent=self,
            )
            return
        siblings = self._same_npc_siblings(src, include_self=False)
        if not siblings:
            messagebox.showinfo(
                "NPC offset",
                "No other behavior shares this map + npc_world.",
                parent=self,
            )
            return
        missing = [b for b in siblings if not b.has_click_offset()]
        already = [b for b in siblings if b.has_click_offset()]
        lines = [
            f"Apply Δ from {src.id}",
            f"[{duv[0]:+.6f}, {duv[1]:+.6f}]",
            f"to {len(siblings)} same-NPC sibling(s):",
            "",
        ]
        for b in siblings:
            tag = "overwrite" if b.has_click_offset() else "new"
            lines.append(f"  • {b.id}  [{b.action}]  ({tag})")
        if already:
            lines.append("")
            lines.append(f"{len(already)} already have Δ and will be overwritten.")
        if not messagebox.askyesno(
            "NPC offset",
            "\n".join(lines),
            parent=self,
        ):
            return
        try:
            # Persist source too if only session Δ exists.
            if src.click_offset_uv is None:
                src = update_click_offset_uv(src.id, duv)
            for b in siblings:
                update_click_offset_uv(b.id, duv)
            self._selected = src
            self._reload_behaviors()
            self._log(
                f"Δ → same NPC: {src.id} → {len(siblings)} sibling(s)"
                + (f" ({len(missing)} were empty)" if missing else "")
            )
        except Exception as exc:
            messagebox.showwarning("NPC offset", str(exc), parent=self)

    def save_offset(self) -> None:
        duv = self._current_delta_uv()
        if duv is None or self._selected is None:
            messagebox.showinfo(
                "NPC offset", "Need A and click B first.", parent=self
            )
            return
        try:
            updated = update_click_offset_uv(self._selected.id, duv)
            self._selected = updated
            self.path_var.set(str(BEHAVIORS_PATH))
            self._reload_behaviors()
            self._log(f"Saved click_offset_uv → {BEHAVIORS_PATH.name}")
            messagebox.showinfo(
                "NPC offset",
                f"Saved click_offset_uv for {updated.id}\n"
                f"[{duv[0]:+.6f}, {duv[1]:+.6f}]\n"
                f"{BEHAVIORS_PATH}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showwarning("NPC offset", str(exc), parent=self)

    def clear_stored_offset(self) -> None:
        if self._selected is None:
            messagebox.showinfo(
                "NPC offset", "Select a behavior first.", parent=self
            )
            return
        if not self._selected.has_click_offset():
            messagebox.showinfo(
                "NPC offset",
                "No stored click_offset_uv on this behavior.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "NPC offset",
            f"Clear click_offset_uv on {self._selected.id}?\n"
            "Open will fall back to cursor search.",
            parent=self,
        ):
            return
        try:
            updated = update_click_offset_uv(self._selected.id, None)
            self._selected = updated
            self._reload_behaviors()
            self._log(f"Cleared click_offset_uv on {updated.id}")
        except Exception as exc:
            messagebox.showwarning("NPC offset", str(exc), parent=self)

    # ── canvas ──────────────────────────────────────────────────────────

    def _zoom_by(self, factor: float) -> None:
        self._zoom = max(0.25, min(8.0, self._zoom * factor))
        self.zoom_label_var.set(f"{int(round(self._zoom * 100))}%")
        self._redraw()

    def _zoom_reset(self) -> None:
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.zoom_label_var.set("100%")
        self._redraw()

    def _on_wheel(self, event: tk.Event) -> None:
        if event.delta > 0:
            self._zoom_by(1.25)
        else:
            self._zoom_by(1 / 1.25)

    def _on_pan_start(self, event: tk.Event) -> None:
        self._drag_pan = True
        self._drag_start = (event.x, event.y)
        self._drag_pan0 = self._pan

    def _on_pan_drag(self, event: tk.Event) -> None:
        if not self._drag_pan:
            return
        self._pan = (
            self._drag_pan0[0] + (event.x - self._drag_start[0]),
            self._drag_pan0[1] + (event.y - self._drag_start[1]),
        )
        self._redraw()

    def _on_pan_end(self, _event: tk.Event) -> None:
        self._drag_pan = False

    def _fit(self):
        import cv2
        from PIL import Image, ImageTk

        frame = self._frame
        assert frame is not None
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        fit = min(cw / image.width, ch / image.height)
        scale = fit * self._zoom
        dw = max(1, int(round(image.width * scale)))
        dh = max(1, int(round(image.height * scale)))
        image = image.resize((dw, dh), getattr(Image, "Resampling", Image).BILINEAR)
        photo = ImageTk.PhotoImage(image, master=self)
        ox = (cw - dw) / 2 + self._pan[0]
        oy = (ch - dh) / 2 + self._pan[1]
        return photo, scale, ox, oy, dw, dh

    def _canvas_to_frame_uv(
        self, x: float, y: float
    ) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
        if self._frame is None or self._scale <= 0:
            return None
        h, w = self._frame.shape[:2]
        ox, oy = self._offset
        fx = (x - ox) / self._scale
        fy = (y - oy) / self._scale
        if fx < 0 or fy < 0 or fx > w or fy > h:
            return None
        return (fx, fy), (fx / w, fy / h)

    def _on_left(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        hit = self._canvas_to_frame_uv(event.x, event.y)
        if hit is None:
            return
        (fx, fy), (u, v) = hit
        self._b_px = (fx, fy)
        self._b_uv = (u, v)
        self._refresh_labels()
        self._redraw()
        self._log(f"B @ uv=({u:.5f},{v:.5f}) px=({fx:.1f},{fy:.1f})")

    def _draw_cross(
        self,
        cx: float,
        cy: float,
        *,
        color: str,
        label: str,
        size: int = 14,
    ) -> None:
        self.canvas.create_line(cx - size, cy, cx + size, cy, fill=color, width=2)
        self.canvas.create_line(cx, cy - size, cx, cy + size, fill=color, width=2)
        self.canvas.create_oval(
            cx - 4, cy - 4, cx + 4, cy + 4, outline=color, width=2
        )
        self.canvas.create_text(
            cx + 10,
            cy - 10,
            anchor="sw",
            fill=color,
            text=label,
            font=("Segoe UI", 9, "bold"),
        )

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self._frame is None:
            if self._is_offline():
                hint = (
                    "Offline: select NPC, enter player world XY,\n"
                    "then Recapture + A (LC visible) and click B."
                )
            else:
                hint = (
                    "Select an NPC behavior, stand nearby, then Recapture + A."
                )
            self.canvas.create_text(
                20,
                20,
                anchor="nw",
                fill="#aaaaaa",
                text=hint,
            )
            return
        photo, scale, ox, oy, dw, dh = self._fit()
        self._photo = photo
        self._scale = scale
        self._offset = (ox, oy)
        self._img_size = (dw, dh)
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)
        h, w = self._frame.shape[:2]
        if self._a is not None:
            au, av = self._a["a_uv"]
            ax = ox + au * w * scale
            ay = oy + av * h * scale
            self._draw_cross(ax, ay, color="#ef4444", label="A")
        if self._b_uv is not None:
            bu, bv = self._b_uv
            bx = ox + bu * w * scale
            by = oy + bv * h * scale
            self._draw_cross(bx, by, color="#22c55e", label="B")
            if self._a is not None:
                au, av = self._a["a_uv"]
                ax = ox + au * w * scale
                ay = oy + av * h * scale
                self.canvas.create_line(
                    ax, ay, bx, by, fill="#fbbf24", width=1, dash=(4, 3)
                )


def run_npc_click_offset_calibrator() -> int:
    app = NpcClickOffsetCalibrator()
    app.mainloop()
    return 0


if __name__ == "__main__":
    from common.bootstrap import bootstrap

    bootstrap()
    raise SystemExit(run_npc_click_offset_calibrator())
