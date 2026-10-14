"""Map window: pick a goal, walk a pawn, watch the avoidance click.

The map uses the same isometric projection as the debug field view, so the
tool faces the same way as the game screen. Game +Y goes down the screen.
"""
from __future__ import annotations

import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

from avoid_view.live import LiveReader, LiveView
from avoid_view.move import RealWalk
from avoid_view.planner import (
    AVOID_RADIUS,
    HopPlan,
    LoadedMap,
    default_hop,
    list_packs,
    load_map,
    plan_hop,
)

_BG = "#1c1e1a"
_PANEL = "#262822"
_INK = "#e7e4d8"
_MUTED = "#9aa094"
_WALK = (58, 62, 54)
_WALL = (16, 16, 14)
_KIND_COLOR = {
    "monster": "#e24b4b",
    "player": "#3aa0ff",
    "npc": "#f0c84a",
    "pin": "#ff7ad9",
}


class AvoidView:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Avoidance map")
        self.root.configure(bg=_BG)
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)

        self._packs = list_packs()
        self._by_id = {pack.id: pack for pack in self._packs}
        self.loaded: LoadedMap | None = None
        self.pawn: tuple[int, int] | None = None
        self.goal: tuple[int, int] | None = None
        self.pins: set[tuple[int, int]] = set()
        self.live_view = LiveView()
        self.plan = HopPlan(note="load a map, set a start and a goal")
        self._walk: list[tuple[int, int]] = []
        self._plan_gen = 0
        self._scale = 10
        # Nav tile under the canvas centre.
        self._view_x = 0.0
        self._view_y = 0.0
        self._drag: tuple[float, float, float, float] | None = None
        self._dragged = False
        self._photo: tk.PhotoImage | None = None
        self._photo_hold: tk.PhotoImage | None = None
        self._map_item: int | None = None
        self._paint_due = False
        self._follow = tk.BooleanVar(value=True)
        self._live_on = tk.BooleanVar(value=True)
        self._tool = tk.StringVar(value="goal")
        self._hop = tk.IntVar(value=5)
        self._status = tk.StringVar(value="starting")
        self._plan_text = tk.StringVar(value=self.plan.note)
        self._reader = LiveReader()
        self.walker = RealWalk(self._reader)
        self._walk_seen = False
        self._photo_view: tuple[float, float, int, int, int] | None = None
        self._raster_stop = threading.Event()
        self._raster_event = threading.Event()
        self._raster_lock = threading.Lock()
        self._raster_job = None
        self._raster_sent: tuple | None = None
        self._raster_out: queue.Queue = queue.Queue()

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        if self._packs:
            prefer = "talking_island" if "talking_island" in self._by_id else self._packs[0].id
            self.map_var.set(prefer)
            self._load_selected()
        self._reader.start()
        self._slide_tile: tuple[int, int] | None = None
        self._slide_xy: tuple[float, float] | None = None
        self._slide_bodies: tuple[tuple[float, float], ...] | None = None
        self._raster_thread = threading.Thread(target=self._raster_loop, name="avoid-view-map", daemon=True)
        self._raster_thread.start()
        self.root.after(100, self._poll_live)
        self.root.after(100, self._slide)
        self.root.after(16, self._pump_raster)
        self.root.after(33, self._anim)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=_PANEL)
        style.configure("TLabel", background=_PANEL, foreground=_INK, font=("Malgun Gothic", 10))
        style.configure("Muted.TLabel", background=_PANEL, foreground=_MUTED, font=("Malgun Gothic", 9))
        style.configure("TRadiobutton", background=_PANEL, foreground=_INK, font=("Malgun Gothic", 10))
        style.configure("TCheckbutton", background=_PANEL, foreground=_INK, font=("Malgun Gothic", 10))
        style.configure("TButton", font=("Malgun Gothic", 10))

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(outer, bg=_BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-3>", self._press)
        self.canvas.bind("<B3-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-3>", self._release_pan)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Configure>", lambda _e: self._request_paint())

        side = ttk.Frame(outer, padding=10, width=280)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)

        ttk.Label(side, text="Avoidance map").pack(anchor=tk.W)
        ttk.Label(
            side,
            text="Green is the A* guide. Yellow is the last guide tile still inside the avoid radius before the path leaves that window, and not a living body. Orange is the one click after the detour check.",
            style="Muted.TLabel",
            wraplength=250,
        ).pack(anchor=tk.W, pady=(4, 10))

        self.map_var = tk.StringVar()
        names = [pack.id for pack in self._packs]
        self.map_box = ttk.Combobox(side, textvariable=self.map_var, values=names, state="readonly")
        self.map_box.pack(fill=tk.X)
        self.map_box.bind("<<ComboboxSelected>>", lambda _e: self._load_selected())

        hop_row = ttk.Frame(side)
        hop_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(hop_row, text="Hop").pack(side=tk.LEFT)
        ttk.Spinbox(hop_row, from_=1, to=12, textvariable=self._hop, width=5, command=self._mark_dirty).pack(side=tk.LEFT, padx=8)

        ttk.Radiobutton(side, text="Click sets the end point", value="goal", variable=self._tool).pack(anchor=tk.W, pady=(10, 0))
        ttk.Radiobutton(side, text="Click pins a body", value="pin", variable=self._tool).pack(anchor=tk.W)

        ttk.Checkbutton(side, text="Live obstacles", variable=self._live_on, command=self._request_paint).pack(anchor=tk.W, pady=(8, 0))
        ttk.Checkbutton(side, text="Follow character", variable=self._follow, command=self._on_follow).pack(anchor=tk.W)

        buttons = ttk.Frame(side)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Start move", command=self._toggle_run).pack(fill=tk.X)
        ttk.Button(buttons, text="Stop", command=self._stop_walk).pack(fill=tk.X, pady=4)
        ttk.Button(buttons, text="Clear pins", command=self._clear_pins).pack(fill=tk.X)

        ttk.Label(side, textvariable=self._plan_text, wraplength=250).pack(anchor=tk.W, pady=(12, 0))
        ttk.Label(side, textvariable=self._status, style="Muted.TLabel", wraplength=250).pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(
            side,
            text="The live character is the start.\nClick an end point, then Start move. The game character walks there.\nDrag pans. Wheel zooms.\nThe map faces the same way as the game screen.\nDo not run the bot at the same time; both would click.",
            style="Muted.TLabel",
            wraplength=250,
        ).pack(anchor=tk.W, pady=(16, 0))

        self.root.bind("<space>", lambda _e: self._toggle_run())

    def _close(self) -> None:
        self._raster_stop.set()
        self._raster_event.set()
        self.walker.close()
        self._reader.close()
        self.root.destroy()

    def _load_selected(self) -> None:
        pack = self._by_id.get(self.map_var.get())
        if pack is None:
            return
        self.walker.stop()
        self._status.set(f"loading {pack.id}")
        self.root.update_idletasks()
        try:
            self.loaded = load_map(pack)
        except Exception as exc:
            self.loaded = None
            self._status.set(str(exc))
            return
        self._reader.set_origin((self.loaded.origin_x, self.loaded.origin_y))
        with self._raster_lock:
            self._raster_sent = None
            self._raster_job = None
        self._hop.set(default_hop(self.loaded.pack_id))
        self.pawn = None
        self.goal = None
        self.pins.clear()
        self._walk = []
        self.plan = HopPlan(note="click the map to set an end point")
        width = int(self.loaded.terrain.width)
        height = int(self.loaded.terrain.height)
        focus = self.live_view.world_xy()
        if focus is not None:
            self._center_on(focus)
        else:
            self._view_x = float(width // 2)
            self._view_y = float(height // 2)
        self._plan_text.set(self.plan.note)
        self._status.set(f"{self.loaded.pack_id}  {width}×{height}")
        self._request_paint()

    def _actor(self) -> tuple[int, int] | None:
        return self.live_view.world_tile()

    def _bodies(self) -> dict[tuple[int, int], str]:
        out: dict[tuple[int, int], str] = {}
        if self._live_on.get() and self.live_view.ok:
            for body in self.live_view.bodies:
                out[body.world_tile()] = body.kind
        for tile in self.pins:
            out[tile] = "pin"
        return out

    def _mark_dirty(self) -> None:
        self._walk = []
        self._request_plan()

    def _request_plan(self) -> None:
        loaded = self.loaded
        start = self._actor()
        if loaded is None or start is None or self.goal is None:
            self.plan = HopPlan(note="waiting for the character" if start is None else "click an end point")
            self._plan_text.set(self.plan.note)
            self._request_paint()
            return
        self._plan_gen += 1
        gen = self._plan_gen
        goal = self.goal
        bodies = set(self._bodies())
        hop = int(self._hop.get() or 1)
        self.root.after(1, lambda: self._plan_now(gen, loaded, start, goal, bodies, hop))

    def _plan_now(self, gen, loaded, start, goal, bodies, hop) -> None:
        if gen != self._plan_gen or self.loaded is not loaded:
            return
        try:
            plan = plan_hop(loaded, start, goal, bodies, max_hop=hop)
        except Exception as exc:
            plan = HopPlan(note=f"plan failed: {exc}")
        if gen != self._plan_gen:
            return
        self.plan = plan
        self._plan_text.set(self._describe(plan))
        if plan.click is not None and plan.polyline:
            self._walk = list(plan.polyline)
        else:
            self._walk = []
        self._request_paint()

    def _describe(self, plan: HopPlan) -> str:
        parts = [plan.note]
        if plan.waypoint is not None:
            parts.append(f"waypoint {plan.waypoint}")
        if plan.click is not None:
            parts.append(f"click {plan.click}")
        parts.append(f"bodies in window {len(plan.considered)}")
        return "\n".join(parts)

    def _push_walk(self) -> None:
        self.walker.update(self.loaded, self.goal, int(self._hop.get() or 1), set(self.pins))

    def _toggle_run(self) -> None:
        if self.walker.running:
            self._stop_walk()
            return
        if self.live_view.world_tile() is None:
            self._plan_text.set("waiting for the live character")
            return
        if self.goal is None:
            self._plan_text.set("click an end point")
            return
        from app._05_action.window_bounds import find_game_window
        from session.probes import bring_game_to_front

        hwnd = int(find_game_window("LC.exe") or 0)
        if not hwnd:
            self._plan_text.set("game window not found")
            return
        bring_game_to_front(hwnd)
        self._follow.set(True)
        self._center_on(self.live_view.world_xy())
        self._push_walk()
        self._walk_seen = True
        self.walker.start()
        self._plan_text.set("walking")

    def _stop_walk(self) -> None:
        self._walk_seen = False
        self.walker.stop()
        self._plan_text.set("stopped")

    def _poll_live(self) -> None:
        view = self._reader.latest()
        prev_player = self.live_view.world_tile()
        prev_bodies = [(b.world_tile(), b.kind) for b in self.live_view.bodies]
        self.live_view = view
        switched = False
        if self.loaded is not None and view.pack_id and view.pack_id != self.loaded.pack_id:
            if view.pack_id in self._by_id:
                self.map_var.set(view.pack_id)
                self._load_selected()
                switched = True
        focus = view.world_xy()
        if focus is not None and self._follow.get() and self._drag is None and not switched:
            self._center_on(focus)
        bodies_changed = [(b.world_tile(), b.kind) for b in view.bodies] != prev_bodies
        player_moved = view.world_tile() != prev_player
        just_stopped = self._walk_seen and not self.walker.running
        if self.walker.running and self.walker.plan is not None:
            self._walk_seen = True
            self.plan = self.walker.plan
            self._plan_text.set(self.walker.message or self._describe(self.plan))
        elif just_stopped:
            self._walk_seen = False
            self._plan_text.set(self.walker.message or "stopped")
        elif player_moved or bodies_changed or switched:
            if self._actor() is not None and self.goal is not None:
                self._request_plan()
        if player_moved or bodies_changed or switched or self.walker.running:
            self._request_paint()
        live = view.message if (self._live_on.get() or not view.ok) else self._status.get()
        if self.walker.running and self.walker.message:
            self._status.set(f"{live}  |  {self.walker.message}")
        else:
            self._status.set(live)
        self.root.after(100, self._poll_live)

    def _slide(self) -> None:
        """Advance the 516ms step between memory polls so a 2-tile step crosses the middle tile."""
        view = self.live_view
        sliding = view.step is not None or any(body.step is not None for body in view.bodies)
        if sliding and self._drag is None and self.loaded is not None:
            focus = view.world_xy()
            tile = view.world_tile()
            prev = self._slide_xy
            body_pts = tuple(body.world_xy() for body in view.bodies)
            moved = focus is not None and (
                prev is None
                or abs(focus[0] - prev[0]) + abs(focus[1] - prev[1]) >= 0.02
            )
            bodies_moved = body_pts != self._slide_bodies
            if moved or bodies_moved:
                self._slide_xy = focus
                self._slide_bodies = body_pts
                if moved and focus is not None and self._follow.get():
                    self._center_on(focus)
                body_tiles = tuple(body.world_tile() for body in view.bodies)
                if (
                    self.goal is not None
                    and not self.walker.running
                    and (
                        (tile is not None and tile != self._slide_tile)
                        or body_tiles != getattr(self, "_slide_body_tiles", None)
                    )
                ):
                    self._request_plan()
                self._slide_tile = tile
                self._slide_body_tiles = body_tiles
                self._request_paint()
        self.root.after(100, self._slide)

    def _on_follow(self) -> None:
        actor = self.live_view.world_xy() or self.pawn
        if self._follow.get() and actor is not None:
            self._center_on(actor)
            self._request_paint()

    def _clear_pins(self) -> None:
        self.pins.clear()
        self._push_walk()
        self._mark_dirty()

    def _center_on(self, tile: tuple[float, float]) -> None:
        self._view_x = float(tile[0])
        self._view_y = float(tile[1])

    def _tile_at(self, cx: int, cy: int) -> tuple[int, int]:
        width = max(1, int(self.canvas.winfo_width()))
        height = max(1, int(self.canvas.winfo_height()))
        scale = float(max(2, int(self._scale)))
        tx, ty = _iso_tile(
            cx, cy, self._view_x, self._view_y, width / 2.0, height / 2.0, scale
        )
        return _nearest(tx), _nearest(ty)

    def _press(self, event) -> None:
        self._drag = (float(event.x), float(event.y), self._view_x, self._view_y)
        self._dragged = False

    def _drag_move(self, event) -> None:
        if self._drag is None:
            return
        x0, y0, vx, vy = self._drag
        dx = float(event.x) - x0
        dy = float(event.y) - y0
        if abs(dx) + abs(dy) < 3:
            return
        self._dragged = True
        scale = float(max(2, int(self._scale)))
        self._view_x, self._view_y = _pan_focus(vx, vy, dx, dy, scale)
        self._request_paint()

    def _release_pan(self, _event) -> None:
        self._drag = None

    def _release(self, event) -> None:
        dragged = self._dragged
        self._drag = None
        if dragged or self.loaded is None:
            if dragged:
                self._follow.set(False)
            return
        tile = self._tile_at(event.x, event.y)
        tool = self._tool.get()
        if tool == "pin":
            if tile in self.pins:
                self.pins.discard(tile)
            else:
                self.pins.add(tile)
        else:
            self.goal = tile
            self.walker._note_click(tile)
        self._push_walk()
        self._mark_dirty()

    def _wheel(self, event) -> None:
        width = max(1, int(self.canvas.winfo_width()))
        height = max(1, int(self.canvas.winfo_height()))
        cx = width / 2.0
        cy = height / 2.0
        old = float(max(2, int(self._scale)))
        tx, ty = _iso_tile(event.x, event.y, self._view_x, self._view_y, cx, cy, old)
        self._scale = min(18, self._scale + 1) if event.delta > 0 else max(4, self._scale - 1)
        self._view_x, self._view_y = _focus_keeping(
            event.x, event.y, tx, ty, cx, cy, float(self._scale)
        )
        self._request_paint()

    def _request_paint(self) -> None:
        if self._paint_due:
            return
        self._paint_due = True
        self.root.after(16, self._flush_paint)

    def _flush_paint(self) -> None:
        self._paint_due = False
        self._paint()

    def _raster_loop(self) -> None:
        """Build the map image off the GUI thread so a plan is not waiting on it."""
        while not self._raster_stop.is_set():
            self._raster_event.wait()
            if self._raster_stop.is_set():
                return
            while not self._raster_stop.is_set():
                with self._raster_lock:
                    job = self._raster_job
                    self._raster_job = None
                    self._raster_event.clear()
                if job is None:
                    break
                ppm = _terrain_ppm(*job)
                self._raster_out.put((ppm, job[1], job[2], job[3], job[4], job[5]))
                with self._raster_lock:
                    if self._raster_job is None:
                        break

    def _submit_raster(self, walkable, focus_x: float, focus_y: float, width: int, height: int, scale: int) -> None:
        key = (float(focus_x), float(focus_y), int(width), int(height), int(scale))
        with self._raster_lock:
            if self._raster_sent == key:
                return
            self._raster_sent = key
            self._raster_job = (walkable, *key)
        self._raster_event.set()

    def _pump_raster(self) -> None:
        latest = None
        try:
            while True:
                latest = self._raster_out.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            ppm, fx, fy, width, height, scale = latest
            try:
                photo = tk.PhotoImage(data=ppm, format="PPM")
            except tk.TclError:
                photo = None
            if photo is not None:
                # Keep the picture the canvas is still showing until itemconfig
                # points at the new one. Dropping it first blanks the map.
                self._photo_hold = self._photo
                self._photo = photo
                self._photo_view = (float(fx), float(fy), int(width), int(height), int(scale))
                self._place_map()
            self._request_paint()
        if not self._raster_stop.is_set():
            self.root.after(16, self._pump_raster)

    def _no_click(self) -> bool:
        """True when a goal is set and this plan could not choose the next click."""
        if self.goal is None or self._actor() is None:
            return False
        note = self.plan.note
        return self.plan.click is None and (
            note in ("no click on the guide", "no path to the goal", "window has no safe click")
            or note.startswith("plan failed")
        )

    def _anim(self) -> None:
        if self.walker.marks() or self._no_click():
            self._request_paint()
        if not self._raster_stop.is_set():
            self.root.after(33, self._anim)

    def _place_map(self) -> None:
        """Move the one map image. Never delete it; a gap there is the flicker."""
        photo = self._photo
        view = self._photo_view
        canvas = getattr(self, "canvas", None)
        if photo is None or view is None or canvas is None:
            return
        if int(canvas.winfo_width()) < 8 or int(canvas.winfo_height()) < 8:
            return
        margin = _map_margin(view[4])
        ox, oy = _image_shift(view[0], view[1], self._view_x, self._view_y, view[4])
        x = ox - margin
        y = oy - margin
        if self._map_item is None:
            self._map_item = canvas.create_image(x, y, image=photo, anchor=tk.NW, tags="map")
        else:
            canvas.coords(self._map_item, x, y)
            canvas.itemconfig(self._map_item, image=photo)
        canvas.tag_lower("map")
        self._photo_hold = None

    def _paint(self) -> None:
        canvas = self.canvas
        canvas.delete("overlay")
        loaded = self.loaded
        if loaded is None:
            return
        width = int(canvas.winfo_width())
        height = int(canvas.winfo_height())
        if width < 8 or height < 8:
            return
        scale = max(2, int(self._scale))
        cx = width / 2.0
        cy = height / 2.0
        view = self._photo_view
        stale = (
            view is None
            or view[2] != width
            or view[3] != height
            or view[4] != scale
            or abs(view[0] - self._view_x) + abs(view[1] - self._view_y) >= 1.0
        )
        if stale:
            self._submit_raster(loaded.terrain.walkable, self._view_x, self._view_y, width, height, scale)
        self._place_map()

        def xy(tile: tuple[float, float]) -> tuple[float, float]:
            return _iso_screen(tile[0], tile[1], self._view_x, self._view_y, cx, cy, scale)

        actor = self._actor()
        if actor is not None:
            canvas.create_polygon(
                *_block(
                    actor[0] - AVOID_RADIUS,
                    actor[1] - AVOID_RADIUS,
                    actor[0] + AVOID_RADIUS,
                    actor[1] + AVOID_RADIUS,
                    xy,
                    scale,
                ),
                outline="#8d907f",
                fill="",
                dash=(3, 3),
                tags="overlay",
            )
        if len(self.plan.guide) >= 2:
            flat: list[int] = []
            for tile in self.plan.guide:
                sx, sy = xy(tile)
                flat.extend((int(round(sx)), int(round(sy))))
            canvas.create_line(*flat, fill="#7dcea0", width=2, tags="overlay")
        if self.plan.waypoint is not None:
            _diamond(canvas, xy(self.plan.waypoint), scale, "#f4e04d")
        if len(self.plan.polyline) >= 2:
            flat = []
            for tile in self.plan.polyline:
                sx, sy = xy(tile)
                flat.extend((int(round(sx)), int(round(sy))))
            canvas.create_line(*flat, fill="#ff9f1c", width=3, tags="overlay")
        if self.plan.click is not None:
            _diamond(canvas, xy(self.plan.click), scale, "#ff9f1c")
        now = time.monotonic()
        dot_r = _dot_radius(scale)
        clicks = self.walker.marks(now)
        if self._live_on.get() and self.live_view.ok:
            for body in self.live_view.bodies:
                _dot(canvas, xy(body.world_xy()), scale, _KIND_COLOR.get(body.kind, "#ffffff"))
        for tile in self.pins:
            _dot(canvas, xy(tile), scale, _KIND_COLOR["pin"])
        spot = self.live_view.world_xy()
        if spot is not None:
            _dot(canvas, xy(spot), scale, "#ffffff")
        elif actor is not None:
            _dot(canvas, xy(actor), scale, "#ffffff")
        if self.goal is not None:
            _diamond(canvas, xy(self.goal), scale, "#8dff6a")
        for tx, ty, started in clicks:
            t = (now - started) / _PULSE_S
            if t < 0.0 or t > 1.0:
                continue
            radius = dot_r * (0.15 + 0.35 * t)
            sx, sy = xy((tx, ty))
            canvas.create_oval(
                sx - radius,
                sy - radius,
                sx + radius,
                sy + radius,
                outline=_pulse_color(t),
                width=2,
                tags="overlay",
            )
        if self._no_click() and int(now / 0.25) % 2 == 0:
            live = self.live_view.world_tile() or self._actor()
            sx, sy = xy((float(live[0]), float(live[1])))
            canvas.create_text(
                sx,
                sy - dot_r - 10,
                text="ALARM",
                fill="#ff4d4d",
                font=("Malgun Gothic", 12, "bold"),
                tags="overlay",
            )


def _iso_screen(
    tx: float,
    ty: float,
    focus_x: float,
    focus_y: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    """Same projection as the debug field view."""
    rx = float(tx) - float(focus_x)
    ry = float(ty) - float(focus_y)
    return (
        cx + (rx + ry) * tile,
        cy - (rx - ry) * tile * 0.5,
    )


def _iso_tile(
    sx: float,
    sy: float,
    focus_x: float,
    focus_y: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    u = (float(sx) - cx) / tile
    v = (cy - float(sy)) * 2.0 / tile
    return ((u + v) * 0.5 + focus_x, (u - v) * 0.5 + focus_y)


def _nearest(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _pan_focus(
    focus_x: float, focus_y: float, dx: float, dy: float, tile: float
) -> tuple[float, float]:
    """Move the centre tile so the map follows a screen drag of (dx, dy)."""
    return (
        focus_x - dx / (2.0 * tile) + dy / tile,
        focus_y - dx / (2.0 * tile) - dy / tile,
    )


def _focus_keeping(
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    cx: float,
    cy: float,
    tile: float,
) -> tuple[float, float]:
    """Focus that keeps continuous tile (tx, ty) under screen point (sx, sy)."""
    u = (float(sx) - cx) / tile
    v = (cy - float(sy)) * 2.0 / tile
    return (float(tx) - (u + v) * 0.5, float(ty) - (u - v) * 0.5)


def _block(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    project,
    tile: float,
) -> list[float]:
    """Outer diamond of the inclusive tile rectangle, in screen points."""
    top = project((x1, y0))
    right = project((x1, y1))
    bottom = project((x0, y1))
    left = project((x0, y0))
    half = tile * 0.5
    return [
        top[0],
        top[1] - half,
        right[0] + tile,
        right[1],
        bottom[0],
        bottom[1] + half,
        left[0] - tile,
        left[1],
    ]


def _diamond(canvas: tk.Canvas, center: tuple[float, float], tile: float, color: str) -> None:
    x, y = center
    half = tile * 0.5
    canvas.create_polygon(
        x,
        y - half,
        x + tile,
        y,
        x,
        y + half,
        x - tile,
        y,
        outline=color,
        fill="",
        width=2,
        tags="overlay",
    )


_PULSE_S = 0.5


def _dot_radius(scale: float) -> float:
    return max(3.0, float(scale) * 0.35)


def _pulse_color(t: float) -> str:
    fade = 1.0 - min(1.0, max(0.0, t))
    red = int(122 * fade + 28 * (1.0 - fade))
    green = int(215 * fade + 30 * (1.0 - fade))
    blue = int(255 * fade + 26 * (1.0 - fade))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _map_margin(scale: float) -> int:
    """Extra pixels so a one-tile camera shift still covers the canvas."""
    return max(48, int(scale) * 3)


def _image_shift(
    old_x: float, old_y: float, focus_x: float, focus_y: float, scale: float
) -> tuple[float, float]:
    """Where to place a map image drawn for an older centre."""
    dx = old_x - focus_x
    dy = old_y - focus_y
    return (dx + dy) * scale, -((dx - dy) * scale * 0.5)


def _dot(canvas: tk.Canvas, center: tuple[float, float], tile: float, color: str) -> None:
    x, y = center
    radius = _dot_radius(tile)
    canvas.create_oval(
        x - radius, y - radius, x + radius, y + radius, fill=color, outline="", tags="overlay"
    )


def _terrain_ppm(
    walkable: np.ndarray,
    focus_x: float,
    focus_y: float,
    width: int,
    height: int,
    tile: float,
) -> bytes:
    """PPM larger than the canvas. Safe to build off the GUI thread."""
    margin = _map_margin(tile)
    width = int(width) + 2 * margin
    height = int(height) + 2 * margin
    cx = width / 2.0
    cy = height / 2.0
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    u = (xs[None, :] - cx) / tile
    v = (cy - ys[:, None]) * 2.0 / tile
    tx = np.floor((u + v) * 0.5 + focus_x + 0.5).astype(np.int32)
    ty = np.floor((u - v) * 0.5 + focus_y + 0.5).astype(np.int32)
    rows, cols = walkable.shape
    valid = (tx >= 0) & (tx < cols) & (ty >= 0) & (ty < rows)
    color = np.empty((height, width, 3), dtype=np.uint8)
    color[:] = (28, 30, 26)
    if np.any(valid):
        walk = np.asarray(walkable[ty[valid], tx[valid]], dtype=bool)
        painted = color[valid]
        painted[walk] = _WALK
        painted[~walk] = _WALL
        color[valid] = painted
    header = f"P6 {width} {height} 255\n".encode("ascii")
    return header + np.ascontiguousarray(color).tobytes()
