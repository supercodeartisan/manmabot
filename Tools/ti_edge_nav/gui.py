"""Tk viewer: edge bit0 map, live iso render, avoidance walk trial."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from app._04_decision.avoidance import AVOID_RADIUS
from avoid_view.live import LiveReader, LiveView

from ti_edge_nav.graph import (
    DEFAULT_CLUSTER,
    build_edge_portal_graph,
    cache_dir,
    load_cache,
    plan_path,
    save_cache,
)
from ti_edge_nav.hop import EdgeHopPlan, plan_edge_hop
from ti_edge_nav.iso import (
    block_diamond,
    class_rgb_ppm,
    focus_keeping,
    image_shift,
    iso_screen,
    iso_tile,
    map_margin,
    nearest,
    pan_focus,
)
from ti_edge_nav.layers import DEFAULT_S32_DIR, TILE_PX, EdgeLayers, load_edge_layers
from ti_edge_nav.walk import EdgeWalk

_BG = "#1a1c1e"
_PANEL = "#242628"
_INK = "#e8e6e0"
_MUTED = "#9a9a94"
# Overlays on black/white fence map (open = white).
_KIND_COLOR = {
    "monster": "#ff3b3b",
    "player": "#4aa3ff",
    "npc": "#ffcc33",
    "pin": "#ff66cc",
}
_CHAR = "#00f0ff"
_GOAL = "#b8ff3a"
_GUIDE = "#5ef0a0"
_WAYPOINT = "#ffe14a"
_CLICK = "#ff8a1a"
_AVOID_RING = "#c8cbb8"
_PULSE_S = 0.5


class TiEdgeNavView:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TI edge nav (live avoid)")
        self.root.configure(bg=_BG)
        self.root.geometry("1200x780")
        self.root.minsize(900, 600)

        self.layers: EdgeLayers | None = None
        self.graph = None
        self._base_rgb = None
        self.goal: tuple[int, int] | None = None
        self.pins: set[tuple[int, int]] = set()
        self.live_view = LiveView()
        self.plan = EdgeHopPlan(note="load map, click a goal")
        self._plan_gen = 0
        self._scale = 8
        self._view_x = 0.0
        self._view_y = 0.0
        self._drag: tuple[float, float, float, float] | None = None
        self._dragged = False
        self._photo: tk.PhotoImage | None = None
        self._photo_hold: tk.PhotoImage | None = None
        self._map_item: int | None = None
        self._paint_due = False
        self._photo_view: tuple[float, float, int, int, int] | None = None
        self._busy = False
        self._tile_px = TILE_PX

        self._follow = tk.BooleanVar(value=True)
        self._live_on = tk.BooleanVar(value=True)
        self._tool = tk.StringVar(value="goal")
        self._hop = tk.IntVar(value=5)
        self._status = tk.StringVar(value="starting")
        self._plan_text = tk.StringVar(value=self.plan.note)
        self._info = tk.StringVar(value="")
        self._s32 = tk.StringVar(value=str(DEFAULT_S32_DIR))
        self._cluster = tk.IntVar(value=DEFAULT_CLUSTER)

        self._reader = LiveReader()
        self.walker = EdgeWalk(self._reader)
        self._walk_seen = False

        self._raster_stop = threading.Event()
        self._raster_event = threading.Event()
        self._raster_lock = threading.Lock()
        self._raster_job = None
        self._raster_sent: tuple | None = None
        self._raster_out: queue.Queue = queue.Queue()
        self._slide_tile: tuple[int, int] | None = None
        self._slide_xy: tuple[float, float] | None = None
        self._slide_bodies: tuple[tuple[float, float], ...] | None = None

        # Offline animate (optional)
        self._offline_path: list[tuple[int, int]] = []
        self._animating = False
        self._anim_i = 0

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._raster_thread = threading.Thread(
            target=self._raster_loop, name="ti-edge-map", daemon=True
        )
        self._raster_thread.start()
        self._reader.start()
        self.root.after(50, self._boot)
        self.root.after(100, self._poll_live)
        self.root.after(100, self._slide)
        self.root.after(16, self._pump_raster)
        self.root.after(33, self._anim_pulse)

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

        side = ttk.Frame(outer, padding=10, width=300)
        side.pack(side=tk.RIGHT, fill=tk.Y)
        side.pack_propagate(False)

        ttk.Label(side, text="TI edge nav").pack(anchor=tk.W)
        ttk.Label(
            side,
            text="bit0 solid/fence map. Live start = character. Walk uses avoidance hops on can_step.",
            style="Muted.TLabel",
            wraplength=270,
        ).pack(anchor=tk.W, pady=(4, 10))

        ttk.Label(side, text=".s32 dir").pack(anchor=tk.W)
        ttk.Entry(side, textvariable=self._s32).pack(fill=tk.X, pady=(2, 6))
        crow = ttk.Frame(side)
        crow.pack(fill=tk.X)
        ttk.Label(crow, text="Cluster").pack(side=tk.LEFT)
        ttk.Spinbox(crow, from_=8, to=64, textvariable=self._cluster, width=5).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(side, text="Rebuild from .s32", command=self._rebuild).pack(fill=tk.X, pady=(8, 0))
        ttk.Button(side, text="Load tool cache", command=self._load_cache).pack(fill=tk.X, pady=4)

        hop_row = ttk.Frame(side)
        hop_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(hop_row, text="Hop").pack(side=tk.LEFT)
        ttk.Spinbox(
            hop_row, from_=1, to=12, textvariable=self._hop, width=5, command=self._mark_dirty
        ).pack(side=tk.LEFT, padx=8)

        ttk.Radiobutton(side, text="Click = goal", value="goal", variable=self._tool).pack(
            anchor=tk.W, pady=(10, 0)
        )
        ttk.Radiobutton(side, text="Click = pin body", value="pin", variable=self._tool).pack(
            anchor=tk.W
        )
        ttk.Checkbutton(
            side, text="Live obstacles", variable=self._live_on, command=self._request_paint
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Checkbutton(
            side, text="Follow character", variable=self._follow, command=self._on_follow
        ).pack(anchor=tk.W)

        buttons = ttk.Frame(side)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Start move", command=self._toggle_run).pack(fill=tk.X)
        ttk.Button(buttons, text="Stop", command=self._stop_walk).pack(fill=tk.X, pady=4)
        ttk.Button(buttons, text="Clear pins", command=self._clear_pins).pack(fill=tk.X)
        ttk.Button(buttons, text="Offline animate path", command=self._toggle_offline_anim).pack(
            fill=tk.X, pady=(8, 0)
        )

        ttk.Label(side, textvariable=self._plan_text, wraplength=270).pack(anchor=tk.W, pady=(12, 0))
        ttk.Label(side, textvariable=self._info, wraplength=270).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(side, textvariable=self._status, style="Muted.TLabel", wraplength=270).pack(
            anchor=tk.W, pady=(8, 0)
        )
        ttk.Label(
            side,
            text="Map faces the game screen. Iso step is interpolated.\n"
            "Do not run the bot at the same time.\n"
            "Cache stays under Tools/ti_edge_nav/cache only.",
            style="Muted.TLabel",
            wraplength=270,
        ).pack(anchor=tk.W, pady=(16, 0))

        self.root.bind("<space>", lambda _e: self._toggle_run())

    def _close(self) -> None:
        self._raster_stop.set()
        self._raster_event.set()
        self.walker.close()
        self._reader.close()
        self.root.destroy()

    def _boot(self) -> None:
        cache = cache_dir() / "talking_island_edge.pkl"
        if cache.is_file():
            self._load_cache()
        else:
            self._rebuild()

    def _set_busy(self, msg: str) -> None:
        self._busy = True
        self._status.set(msg)
        self.root.update_idletasks()

    def _clear_busy(self, msg: str) -> None:
        self._busy = False
        self._status.set(msg)

    def _apply_loaded(self, layers: EdgeLayers, graph, note: str) -> None:
        self.layers = layers
        self.graph = graph
        self._base_rgb = layers.fence_bw_rgb(TILE_PX)
        self._tile_px = TILE_PX
        self.plan = EdgeHopPlan(note="click a goal")
        self._plan_text.set(self.plan.note)
        self._offline_path = []
        self._animating = False
        self._reader.set_origin((layers.origin_x, layers.origin_y))
        with self._raster_lock:
            self._raster_sent = None
            self._raster_job = None
        focus = self.live_view.world_xy()
        if focus is not None:
            self._center_on(focus)
        else:
            self._view_x = layers.width / 2.0
            self._view_y = layers.height / 2.0
        self._info.set(
            f"{layers.width}×{layers.height}  nodes={len(graph.nodes)}  "
            f"cluster={graph.cluster}  tile={TILE_PX}px\n{layers.source}"
        )
        self._push_walk()
        self._clear_busy(note)
        self._request_paint()

    def _rebuild(self) -> None:
        if self._busy:
            return
        root = Path(self._s32.get().strip())
        cluster = int(self._cluster.get())

        def work() -> None:
            try:
                layers = load_edge_layers(root)
                graph = build_edge_portal_graph(layers, cluster=cluster)
                path = save_cache(layers, graph)
                self.root.after(
                    0, lambda: self._apply_loaded(layers, graph, f"built → {path.name}")
                )
            except Exception as exc:
                self.root.after(0, lambda: self._clear_busy(f"rebuild failed: {exc}"))

        self._set_busy("building layers + portal graph…")
        threading.Thread(target=work, daemon=True).start()

    def _load_cache(self) -> None:
        if self._busy:
            return

        def work() -> None:
            try:
                layers, graph = load_cache()
                self.root.after(0, lambda: self._apply_loaded(layers, graph, "loaded tool cache"))
            except Exception as exc:
                self.root.after(0, lambda: self._clear_busy(f"cache load failed: {exc}"))

        self._set_busy("loading cache…")
        threading.Thread(target=work, daemon=True).start()

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

    def _push_walk(self) -> None:
        self.walker.update(
            self.layers, self.graph, self.goal, int(self._hop.get() or 1), set(self.pins)
        )

    def _mark_dirty(self) -> None:
        self._offline_path = []
        self._request_plan()

    def _request_plan(self) -> None:
        layers = self.layers
        graph = self.graph
        start = self._actor()
        if layers is None or graph is None or start is None or self.goal is None:
            self.plan = EdgeHopPlan(
                note="waiting for the character" if start is None else "click a goal"
            )
            self._plan_text.set(self.plan.note)
            self._request_paint()
            return
        self._plan_gen += 1
        gen = self._plan_gen
        goal = self.goal
        bodies = set(self._bodies())
        hop = int(self._hop.get() or 1)
        self.root.after(1, lambda: self._plan_now(gen, layers, graph, start, goal, bodies, hop))

    def _plan_now(self, gen, layers, graph, start, goal, bodies, hop) -> None:
        if gen != self._plan_gen or self.layers is not layers:
            return
        try:
            plan = plan_edge_hop(layers, graph, start, goal, bodies, max_hop=hop)
        except Exception as exc:
            plan = EdgeHopPlan(note=f"plan failed: {exc}")
        if gen != self._plan_gen:
            return
        self.plan = plan
        self._plan_text.set(self._describe(plan))
        self._request_paint()

    def _describe(self, plan: EdgeHopPlan) -> str:
        parts = [plan.note]
        if plan.waypoint is not None:
            parts.append(f"waypoint {plan.waypoint}")
        if plan.click is not None:
            parts.append(f"click {plan.click}")
        parts.append(f"bodies in window {len(plan.considered)}")
        return "\n".join(parts)

    def _toggle_run(self) -> None:
        if self.walker.running:
            self._stop_walk()
            return
        if self.live_view.world_tile() is None:
            self._plan_text.set("waiting for the live character")
            return
        if self.goal is None:
            self._plan_text.set("click a goal")
            return
        if self.layers is None or self.graph is None:
            self._plan_text.set("load the edge map first")
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

    def _clear_pins(self) -> None:
        self.pins.clear()
        self._push_walk()
        self._mark_dirty()

    def _toggle_offline_anim(self) -> None:
        if self._animating:
            self._animating = False
            self._status.set("anim paused")
            return
        if self.layers is None or self.graph is None or self.goal is None:
            self._status.set("need map + goal")
            return
        start = self._actor()
        if start is None:
            self._status.set("waiting for character for offline path")
            return
        path = plan_path(self.layers, self.graph, start, self.goal)
        if not path:
            self._status.set("no offline path")
            return
        self._offline_path = path
        self._anim_i = 0
        self._animating = True
        self._status.set("offline animating")
        self.root.after(40, self._offline_anim_tick)

    def _offline_anim_tick(self) -> None:
        if not self._animating or not self._offline_path:
            return
        self._anim_i += 1
        if self._anim_i >= len(self._offline_path):
            self._animating = False
            self._status.set("offline anim done")
            self._request_paint()
            return
        self._request_paint()
        self.root.after(40, self._offline_anim_tick)

    def _poll_live(self) -> None:
        view = self._reader.latest()
        prev_player = self.live_view.world_tile()
        prev_bodies = [(b.world_tile(), b.kind) for b in self.live_view.bodies]
        self.live_view = view
        focus = view.world_xy()
        if focus is not None and self._follow.get() and self._drag is None:
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
        elif player_moved or bodies_changed:
            if self._actor() is not None and self.goal is not None:
                self._request_plan()
        if player_moved or bodies_changed or self.walker.running:
            self._request_paint()
        live = view.message if (self._live_on.get() or not view.ok) else self._status.get()
        if self.walker.running and self.walker.message:
            self._status.set(f"{live}  |  {self.walker.message}")
        else:
            self._status.set(live)
        self.root.after(100, self._poll_live)

    def _slide(self) -> None:
        view = self.live_view
        sliding = view.step is not None or any(body.step is not None for body in view.bodies)
        if sliding and self._drag is None and self.layers is not None:
            focus = view.world_xy()
            tile = view.world_tile()
            prev = self._slide_xy
            body_pts = tuple(body.world_xy() for body in view.bodies)
            moved = focus is not None and (
                prev is None or abs(focus[0] - prev[0]) + abs(focus[1] - prev[1]) >= 0.02
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
        self.root.after(33, self._slide)

    def _on_follow(self) -> None:
        actor = self.live_view.world_xy()
        if self._follow.get() and actor is not None:
            self._center_on(actor)
            self._request_paint()

    def _center_on(self, tile: tuple[float, float] | None) -> None:
        if tile is None:
            return
        self._view_x = float(tile[0])
        self._view_y = float(tile[1])

    def _tile_at(self, cx: int, cy: int) -> tuple[int, int]:
        width = max(1, int(self.canvas.winfo_width()))
        height = max(1, int(self.canvas.winfo_height()))
        scale = float(max(2, int(self._scale)))
        tx, ty = iso_tile(cx, cy, self._view_x, self._view_y, width / 2.0, height / 2.0, scale)
        return nearest(tx), nearest(ty)

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
        self._view_x, self._view_y = pan_focus(vx, vy, dx, dy, scale)
        self._request_paint()

    def _release_pan(self, _event) -> None:
        self._drag = None

    def _release(self, event) -> None:
        dragged = self._dragged
        self._drag = None
        if dragged or self.layers is None:
            if dragged:
                self._follow.set(False)
            return
        tile = self._tile_at(event.x, event.y)
        if not self.layers.standable(tile[0], tile[1]) and self._tool.get() != "pin":
            self._status.set(f"not standable {tile}")
            return
        if self._tool.get() == "pin":
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
        tx, ty = iso_tile(event.x, event.y, self._view_x, self._view_y, cx, cy, old)
        if event.delta > 0:
            self._scale = min(24, int(self._scale) + 1)
        else:
            self._scale = max(2, int(self._scale) - 1)
        new = float(max(2, int(self._scale)))
        self._view_x, self._view_y = focus_keeping(event.x, event.y, tx, ty, cx, cy, new)
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
                rgb, fx, fy, w, h, scale, tile_px = job
                ppm = class_rgb_ppm(rgb, fx, fy, w, h, scale, tile_px=tile_px)
                self._raster_out.put((ppm, fx, fy, w, h, scale))
                with self._raster_lock:
                    if self._raster_job is None:
                        break

    def _submit_raster(self, rgb, focus_x, focus_y, width, height, scale) -> None:
        tile_px = int(getattr(self, "_tile_px", TILE_PX) or TILE_PX)
        key = (float(focus_x), float(focus_y), int(width), int(height), int(scale), tile_px)
        with self._raster_lock:
            if self._raster_sent == key:
                return
            self._raster_sent = key
            self._raster_job = (rgb, float(focus_x), float(focus_y), int(width), int(height), int(scale), tile_px)
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
                self._photo_hold = self._photo
                self._photo = photo
                self._photo_view = (float(fx), float(fy), int(width), int(height), int(scale))
                self._place_map()
            self._request_paint()
        if not self._raster_stop.is_set():
            self.root.after(16, self._pump_raster)

    def _no_click(self) -> bool:
        if self.goal is None or self._actor() is None:
            return False
        note = self.plan.note
        return self.plan.click is None and (
            note
            in ("no click on the guide", "no path to the goal", "window has no safe click")
            or note.startswith("plan failed")
        )

    def _anim_pulse(self) -> None:
        if self.walker.marks() or self._no_click() or self._animating:
            self._request_paint()
        if not self._raster_stop.is_set():
            self.root.after(33, self._anim_pulse)

    def _place_map(self) -> None:
        photo = self._photo
        view = self._photo_view
        canvas = getattr(self, "canvas", None)
        if photo is None or view is None or canvas is None:
            return
        if int(canvas.winfo_width()) < 8 or int(canvas.winfo_height()) < 8:
            return
        margin = map_margin(view[4])
        ox, oy = image_shift(view[0], view[1], self._view_x, self._view_y, view[4])
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
        if self.layers is None or self._base_rgb is None:
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
            self._submit_raster(self._base_rgb, self._view_x, self._view_y, width, height, scale)
        self._place_map()

        def xy(tile: tuple[float, float]) -> tuple[float, float]:
            return iso_screen(tile[0], tile[1], self._view_x, self._view_y, cx, cy, scale)

        actor = self._actor()
        if actor is not None:
            canvas.create_polygon(
                *block_diamond(
                    actor[0] - AVOID_RADIUS,
                    actor[1] - AVOID_RADIUS,
                    actor[0] + AVOID_RADIUS,
                    actor[1] + AVOID_RADIUS,
                    xy,
                    scale,
                ),
                outline=_AVOID_RING,
                fill="",
                dash=(3, 3),
                tags="overlay",
            )
        if len(self.plan.guide) >= 2:
            flat: list[int] = []
            for tile in self.plan.guide:
                sx, sy = xy(tile)
                flat.extend((int(round(sx)), int(round(sy))))
            canvas.create_line(*flat, fill=_GUIDE, width=2, tags="overlay")
        if self.plan.waypoint is not None:
            _diamond(canvas, xy(self.plan.waypoint), scale, _WAYPOINT)
        if len(self.plan.polyline) >= 2:
            flat = []
            for tile in self.plan.polyline:
                sx, sy = xy(tile)
                flat.extend((int(round(sx)), int(round(sy))))
            canvas.create_line(*flat, fill=_CLICK, width=3, tags="overlay")
        if self.plan.click is not None:
            _diamond(canvas, xy(self.plan.click), scale, _CLICK)
        if self._animating and self._offline_path:
            idx = min(self._anim_i, len(self._offline_path) - 1)
            for i, tile in enumerate(self._offline_path[: idx + 1]):
                if i % 2 == 0 or i == idx:
                    _dot(canvas, xy(tile), scale, _GUIDE, outline="#0a1a10")
        now = time.monotonic()
        if self._live_on.get() and self.live_view.ok:
            for body in self.live_view.bodies:
                _dot(
                    canvas,
                    xy(body.world_xy()),
                    scale,
                    _KIND_COLOR.get(body.kind, "#eeeeee"),
                    outline="#101010",
                )
        for tile in self.pins:
            _dot(canvas, xy(tile), scale, _KIND_COLOR["pin"], outline="#101010")
        spot = self.live_view.world_xy()
        if spot is not None:
            _dot(canvas, xy(spot), scale, _CHAR, outline="#001018", scale_boost=1.35)
        elif actor is not None:
            _dot(canvas, xy(actor), scale, _CHAR, outline="#001018", scale_boost=1.35)
        if self.goal is not None:
            _diamond(canvas, xy(self.goal), scale, _GOAL)
        for tx, ty, started in self.walker.marks(now):
            t = (now - started) / _PULSE_S
            if t < 0.0 or t > 1.0:
                continue
            radius = _dot_radius(scale) * (0.15 + 0.35 * t)
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
            live = self.live_view.world_tile() or actor
            if live is not None:
                sx, sy = xy((float(live[0]), float(live[1])))
                canvas.create_text(
                    sx,
                    sy - _dot_radius(scale) - 10,
                    text="ALARM",
                    fill="#ff4d4d",
                    font=("Malgun Gothic", 12, "bold"),
                    tags="overlay",
                )


def _dot_radius(scale: float) -> float:
    return max(3.0, float(scale) * 0.35)


def _pulse_color(t: float) -> str:
    fade = 1.0 - min(1.0, max(0.0, t))
    red = int(122 * fade + 28 * (1.0 - fade))
    green = int(215 * fade + 30 * (1.0 - fade))
    blue = int(255 * fade + 26 * (1.0 - fade))
    return f"#{red:02x}{green:02x}{blue:02x}"


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


def _dot(
    canvas: tk.Canvas,
    center: tuple[float, float],
    tile: float,
    color: str,
    *,
    outline: str = "",
    scale_boost: float = 1.0,
) -> None:
    x, y = center
    radius = _dot_radius(tile) * float(scale_boost)
    canvas.create_oval(
        x - radius,
        y - radius,
        x + radius,
        y + radius,
        fill=color,
        outline=outline or "",
        width=2 if outline else 0,
        tags="overlay",
    )
