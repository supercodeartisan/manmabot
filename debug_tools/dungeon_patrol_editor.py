"""Dungeon patrol editor — place waypoints on raw map images, A* between them, save YAML.

Launch::

    python run.py --dungeon-patrol
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

from debug_tools.bootstrap import bootstrap
from manmabot_v1.dungeon_assets import (
    DungeonAsset,
    discover_dungeon_assets,
    ensure_dungeon_pack,
    load_pack_meta,
    pack_dir_for,
    save_patrol_overlay,
    suggest_map_id,
)
from manmabot_v1.paths import ensure_userdata, map_overlay_slug
from manmabot_v1.probes import list_patrol_entries
from manmabot_v1.ui.design_system import (
    BG,
    BORDER,
    FONT_BODY,
    FONT_SECTION,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    apply_classic_style,
)

_ZOOM_MIN = 0.5
_ZOOM_MAX = 16.0
_HIT_R = 6


class DungeonPatrolEditor(tk.Tk):
    """Standalone tool: image + origin → pack meta/nav + patrol.yaml with path preview."""

    def __init__(self) -> None:
        super().__init__()
        bootstrap()
        ensure_userdata()
        self.title("Dungeon patrol editor")
        self.geometry("1280x820")
        self.minsize(960, 640)
        self.configure(bg=BG)
        apply_classic_style(self)

        self.assets: list[DungeonAsset] = []
        self.asset: Optional[DungeonAsset] = None
        self.map_id = ""
        self._base: Optional[Image.Image] = None
        self._terrain = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self.patrol: list[tuple[int, int, str]] = []
        self.paths: list[list[tuple[int, int]]] = []
        self.selected: Optional[int] = None
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_origin = [0.0, 0.0]
        self._dragging: Optional[int] = None
        self._dirty = False

        self._build()
        self.refresh_assets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.rowconfigure(1, weight=1)

        ttk.Label(left, text="Dungeon maps", font=FONT_SECTION).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        list_wrap = ttk.Frame(left)
        list_wrap.grid(row=1, column=0, sticky="nsw")
        self.map_list = tk.Listbox(
            list_wrap,
            width=34,
            height=22,
            activestyle="dotbox",
            exportselection=False,
            bg=SURFACE,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=FONT_BODY,
        )
        scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.map_list.yview)
        self.map_list.configure(yscrollcommand=scroll.set)
        self.map_list.pack(side="left", fill="y")
        scroll.pack(side="left", fill="y")
        self.map_list.bind("<<ListboxSelect>>", self._on_map_select)

        btn_row = ttk.Frame(left)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(btn_row, text="Refresh", command=self.refresh_assets).pack(
            side="left"
        )
        ttk.Button(btn_row, text="Open PNG…", command=self._open_png).pack(
            side="left", padx=(4, 0)
        )

        meta = ttk.LabelFrame(left, text="Pack / origin", padding=8)
        meta.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.var_id = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_ox = tk.IntVar(value=0)
        self.var_oy = tk.IntVar(value=0)
        self.var_ps = tk.IntVar(value=1)
        self._meta_row(meta, 0, "Map id", self.var_id, width=28)
        self._meta_row(meta, 1, "Display name", self.var_name, width=28)
        self._meta_row(meta, 2, "origin_x", self.var_ox, spin=(0, 99999))
        self._meta_row(meta, 3, "origin_y", self.var_oy, spin=(0, 99999))
        self._meta_row(meta, 4, "pixel_scale", self.var_ps, spin=(1, 16))
        ttk.Label(
            meta,
            text="White pixels = walkable. Click to place patrol points.",
            foreground=TEXT_MUTED,
            wraplength=240,
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        tools = ttk.Frame(right)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for text, cmd in (
            ("Delete selected", self._delete_selected),
            ("Clear all", self._clear_all),
            ("Reload YAML", lambda: self._reload_patrol()),
            ("Recompute paths", self._recompute_paths),
            ("Save pack + patrol", self.save),
        ):
            ttk.Button(tools, text=text, command=cmd).pack(side="left", padx=(0, 4))
        self.status = ttk.Label(tools, text="Select a dungeon map.", foreground=TEXT_MUTED)
        self.status.pack(side="right")
        for var in (self.var_ps,):
            var.trace_add("write", lambda *_a: self._on_scale_changed())

        body = ttk.Frame(right)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        canvas_host = ttk.Frame(body, relief="solid", borderwidth=1)
        canvas_host.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        canvas_host.rowconfigure(0, weight=1)
        canvas_host.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_host, bg="#1a1d23", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_lmb)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Motion>", self._on_motion)

        side = ttk.Frame(body, width=240)
        side.grid(row=0, column=1, sticky="ns")
        ttk.Label(side, text="Patrol points", font=FONT_SECTION).pack(anchor="w")
        self.point_list = tk.Listbox(
            side,
            width=28,
            height=28,
            exportselection=False,
            bg=SURFACE,
            fg=TEXT,
            font=FONT_BODY,
        )
        self.point_list.pack(fill="both", expand=True, pady=(4, 0))
        self.point_list.bind("<<ListboxSelect>>", self._on_point_select)
        self.path_info = ttk.Label(
            side, text="", foreground=TEXT_MUTED, wraplength=220, justify="left"
        )
        self.path_info.pack(anchor="w", pady=(8, 0))

    def _meta_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.Variable,
        *,
        width: int = 12,
        spin: tuple[int, int] | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        if spin is None:
            ttk.Entry(parent, textvariable=variable, width=width).grid(
                row=row, column=1, sticky="ew", pady=2, padx=(6, 0)
            )
        else:
            ttk.Spinbox(
                parent,
                from_=spin[0],
                to=spin[1],
                textvariable=variable,
                width=width,
            ).grid(row=row, column=1, sticky="ew", pady=2, padx=(6, 0))
        parent.columnconfigure(1, weight=1)

    # ── asset loading ─────────────────────────────────────────────────────

    def refresh_assets(self) -> None:
        self.assets = discover_dungeon_assets()
        self.map_list.delete(0, "end")
        for asset in self.assets:
            ox = "—" if asset.origin_x is None else str(asset.origin_x)
            oy = "—" if asset.origin_y is None else str(asset.origin_y)
            self.map_list.insert(
                "end", f"{asset.suggested_id}  ({ox},{oy})"
            )
        if self.assets and self.map_list.curselection() == ():
            self.map_list.selection_set(0)
            self._on_map_select()

    def _on_map_select(self, *_args) -> None:
        if self._dirty and not self._confirm_discard():
            return
        sel = self.map_list.curselection()
        if not sel:
            return
        self._load_asset(self.assets[int(sel[0])])

    def _open_png(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Open dungeon map PNG",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp"), ("All", "*.*")],
        )
        if not path:
            return
        p = Path(path)
        mid = suggest_map_id(p.stem)
        asset = DungeonAsset(
            label=p.stem,
            image_path=p.resolve(),
            origin_x=None,
            origin_y=None,
            suggested_id=mid,
        )
        self._load_asset(asset)

    def _load_asset(self, asset: DungeonAsset) -> None:
        self.asset = asset
        mid = asset.suggested_id
        meta = load_pack_meta(mid) or {}
        ox = int(meta.get("origin_x", asset.origin_x or 0))
        oy = int(meta.get("origin_y", asset.origin_y or 0))
        ps = int(meta.get("pixel_scale", 1) or 1)
        name = str(meta.get("name") or mid.replace("_", " ").title())
        self.map_id = mid
        self.var_id.set(mid)
        self.var_name.set(name)
        self.var_ox.set(ox)
        self.var_oy.set(oy)
        self.var_ps.set(max(1, ps))
        try:
            self._base = Image.open(asset.image_path).convert("RGB")
        except OSError as exc:
            messagebox.showerror(self.title(), f"Could not open image:\n{exc}", parent=self)
            return
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self.selected = None
        self._rebuild_terrain()
        self._reload_patrol(silent=True)
        self._dirty = False
        self.status.configure(
            text=f"{asset.image_path.name}  ·  {self._base.size[0]}×{self._base.size[1]}"
        )
        self._fit_view()
        self._redraw()

    def _rebuild_terrain(self) -> None:
        self._terrain = None
        if self._base is None:
            return
        from app._03_world.terrain_map import TerrainMap

        import numpy as np

        ps = max(1, int(self.var_ps.get() or 1))
        pixels = np.asarray(self._base, dtype=np.uint8)
        walkable = (
            (pixels[:, :, 0] == 255)
            & (pixels[:, :, 1] == 255)
            & (pixels[:, :, 2] == 255)
        )
        if ps > 1:
            h, w = walkable.shape
            th, tw = h // ps, w // ps
            if th >= 1 and tw >= 1:
                blocks = walkable[: th * ps, : tw * ps]
                blocks = blocks.reshape(th, ps, tw, ps)
                walkable = blocks.mean(axis=(1, 3)) >= 0.5
        self._terrain = TerrainMap.from_array(walkable)

    def _on_scale_changed(self) -> None:
        if self._base is None:
            return
        try:
            self._rebuild_terrain()
            self._recompute_paths()
            self._redraw()
        except Exception:
            pass

    def _reload_patrol(self, *, silent: bool = False) -> None:
        mid = str(self.var_id.get() or self.map_id).strip() or self.map_id
        entries = list_patrol_entries(mid)
        if not entries:
            pack_patrol = pack_dir_for(mid) / "patrol.yaml"
            if pack_patrol.is_file():
                from app._04_decision.patrol import load_patrol_entries_from_yaml

                entries = load_patrol_entries_from_yaml(pack_patrol)
        self.patrol = list(entries)
        self.selected = None
        self._refresh_point_list()
        self._recompute_paths()
        self._redraw()
        if not silent:
            self.status.configure(text=f"Loaded {len(self.patrol)} patrol points")

    # ── coords ────────────────────────────────────────────────────────────

    def _pixel_scale(self) -> int:
        try:
            return max(1, int(self.var_ps.get()))
        except (tk.TclError, TypeError, ValueError):
            return 1

    def _tile_to_canvas(self, tx: int, ty: int) -> tuple[float, float]:
        ps = self._pixel_scale()
        return tx * ps * self._zoom + self._pan[0], ty * ps * self._zoom + self._pan[1]

    def _canvas_to_tile(self, cx: float, cy: float) -> tuple[int, int]:
        ps = self._pixel_scale()
        scale = max(self._zoom * ps, 1e-6)
        tx = int((cx - self._pan[0]) / scale)
        ty = int((cy - self._pan[1]) / scale)
        return self._clamp_tile(tx, ty)

    def _clamp_tile(self, tx: int, ty: int) -> tuple[int, int]:
        if self._terrain is None:
            return tx, ty
        return (
            max(0, min(tx, self._terrain.width - 1)),
            max(0, min(ty, self._terrain.height - 1)),
        )

    def _fit_view(self) -> None:
        if self._base is None:
            return
        self.update_idletasks()
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self._base.size
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, min(cw / iw, ch / ih) * 0.98))
        self._pan = [
            (cw - iw * self._zoom) / 2,
            (ch - ih * self._zoom) / 2,
        ]

    def _is_walkable(self, tx: int, ty: int) -> bool:
        return self._terrain is not None and self._terrain.is_walkable(tx, ty)

    # ── paths ─────────────────────────────────────────────────────────────

    def _recompute_paths(self) -> None:
        self.paths = []
        if self._terrain is None or len(self.patrol) < 2:
            self._update_path_info()
            return
        from app._04_decision.pathfinding import find_path

        for i in range(len(self.patrol) - 1):
            a = self.patrol[i][:2]
            b = self.patrol[i + 1][:2]
            path = find_path(self._terrain, a, b)
            self.paths.append(path)
        # close loop preview
        if len(self.patrol) >= 2:
            a = self.patrol[-1][:2]
            b = self.patrol[0][:2]
            self.paths.append(find_path(self._terrain, a, b))
        self._update_path_info()
        self._redraw()

    def _update_path_info(self) -> None:
        if not self.paths:
            self.path_info.configure(text="Place 2+ points to see A* paths.")
            return
        lines = []
        for i, path in enumerate(self.paths):
            if i < len(self.patrol) - 1:
                label = f"{i + 1}→{i + 2}"
            else:
                label = f"{len(self.patrol)}→1 (loop)"
            if not path:
                lines.append(f"{label}: no path")
            else:
                lines.append(f"{label}: {len(path) - 1} steps")
        blocked = sum(1 for p in self.paths if not p)
        if blocked:
            lines.append(f"{blocked} segment(s) blocked — move points onto white.")
        self.path_info.configure(text="\n".join(lines))

    # ── drawing ───────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self._base is None:
            return
        iw, ih = self._base.size
        dw = max(1, int(round(iw * self._zoom)))
        dh = max(1, int(round(ih * self._zoom)))
        shown = self._base.resize((dw, dh), Image.Resampling.NEAREST)
        overlay = Image.new("RGBA", shown.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        ps = self._pixel_scale()

        # path polylines
        for path in self.paths:
            if len(path) < 2:
                continue
            pts = []
            for tx, ty in path:
                px = (tx * ps + ps / 2) * self._zoom
                py = (ty * ps + ps / 2) * self._zoom
                pts.append((px, py))
            draw.line(pts, fill=(56, 189, 248, 200), width=max(2, int(2 * self._zoom)))

        # waypoints
        for i, (tx, ty, _name) in enumerate(self.patrol):
            cx = (tx * ps + ps / 2) * self._zoom
            cy = (ty * ps + ps / 2) * self._zoom
            r = 7 if self.selected == i else 5
            r = max(r, int(4 * self._zoom))
            fill = (249, 115, 22, 255) if self.selected == i else (234, 179, 8, 255)
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=fill,
                outline=(255, 255, 255, 255),
                width=2,
            )
            draw.text((cx + r + 2, cy - r), str(i + 1), fill=(255, 255, 255, 230))

        composed = Image.alpha_composite(shown.convert("RGBA"), overlay)
        self._photo = ImageTk.PhotoImage(composed)
        self.canvas.create_image(
            self._pan[0], self._pan[1], anchor="nw", image=self._photo
        )

    def _refresh_point_list(self) -> None:
        self.point_list.delete(0, "end")
        for i, (x, y, name) in enumerate(self.patrol):
            self.point_list.insert("end", f"{i + 1}. {name}  ({x}, {y})")
        if self.selected is not None and 0 <= self.selected < len(self.patrol):
            self.point_list.selection_set(self.selected)
            self.point_list.see(self.selected)

    # ── interaction ───────────────────────────────────────────────────────

    def _on_point_select(self, *_args) -> None:
        sel = self.point_list.curselection()
        if not sel:
            return
        self.selected = int(sel[0])
        self._redraw()

    def _hit_patrol(self, tx: int, ty: int) -> Optional[int]:
        best = None
        best_d = None
        for i, (x, y, _n) in enumerate(self.patrol):
            d = max(abs(x - tx), abs(y - ty))
            if d <= _HIT_R and (best_d is None or d < best_d):
                best_d = d
                best = i
        return best

    def _on_lmb(self, event: tk.Event) -> None:
        if self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        hit = self._hit_patrol(tx, ty)
        if hit is not None:
            self.selected = hit
            self._dragging = hit
            self._refresh_point_list()
            self._redraw()
            return
        if not self._is_walkable(tx, ty):
            self.status.configure(text="That tile is not walkable (need white).")
            return
        name = f"mid_{len(self.patrol) + 1}"
        self.patrol.append((tx, ty, name))
        self.selected = len(self.patrol) - 1
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()
        self.status.configure(text=f"Added {name} at ({tx}, {ty})")

    def _on_drag(self, event: tk.Event) -> None:
        if self._dragging is None or self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        if not self._is_walkable(tx, ty):
            return
        idx = self._dragging
        _x, _y, name = self.patrol[idx]
        self.patrol[idx] = (tx, ty, name)
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()

    def _on_release(self, _event: tk.Event) -> None:
        self._dragging = None

    def _on_pan_start(self, event: tk.Event) -> None:
        self._panning = True
        self._pan_start = (event.x, event.y)
        self._pan_origin = list(self._pan)

    def _on_pan_move(self, event: tk.Event) -> None:
        if not self._panning:
            return
        self._pan = [
            self._pan_origin[0] + (event.x - self._pan_start[0]),
            self._pan_origin[1] + (event.y - self._pan_start[1]),
        ]
        self._redraw()

    def _on_wheel(self, event: tk.Event) -> None:
        if self._base is None:
            return
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        # zoom toward cursor
        tx = (event.x - self._pan[0]) / max(self._zoom, 1e-6)
        ty = (event.y - self._pan[1]) / max(self._zoom, 1e-6)
        self._zoom = new_zoom
        self._pan = [event.x - tx * self._zoom, event.y - ty * self._zoom]
        self._redraw()

    def _on_motion(self, event: tk.Event) -> None:
        if self._terrain is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        walk = "walkable" if self._is_walkable(tx, ty) else "blocked"
        self.status.configure(text=f"tile ({tx}, {ty}) · {walk}")

    def _delete_selected(self) -> None:
        if self.selected is None or not (0 <= self.selected < len(self.patrol)):
            return
        self.patrol.pop(self.selected)
        self.selected = None
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()

    def _clear_all(self) -> None:
        if not self.patrol:
            return
        if not messagebox.askyesno(
            self.title(), "Delete all patrol points on this map?", parent=self
        ):
            return
        self.patrol.clear()
        self.selected = None
        self._dirty = True
        self._refresh_point_list()
        self._recompute_paths()

    # ── save ──────────────────────────────────────────────────────────────

    def save(self) -> None:
        if self.asset is None or self._base is None:
            messagebox.showinfo(self.title(), "Select a map first.", parent=self)
            return
        mid = map_overlay_slug(str(self.var_id.get()).strip() or self.map_id)
        if "dungeon" not in mid.lower():
            mid = suggest_map_id(f"{mid}_dungeon")
        else:
            mid = suggest_map_id(mid)
        try:
            ox = int(self.var_ox.get())
            oy = int(self.var_oy.get())
            ps = max(1, int(self.var_ps.get()))
        except (tk.TclError, TypeError, ValueError):
            messagebox.showerror(self.title(), "Check origin / pixel_scale values.", parent=self)
            return
        if ox == 0 and oy == 0:
            if not messagebox.askyesno(
                self.title(),
                "origin_x and origin_y are both 0.\nSave anyway?",
                parent=self,
            ):
                return

        # rebuild terrain with current pixel_scale before validating points
        self.var_id.set(mid)
        self._rebuild_terrain()
        bad = [
            (i, x, y)
            for i, (x, y, _n) in enumerate(self.patrol)
            if not self._is_walkable(x, y)
        ]
        if bad:
            messagebox.showerror(
                self.title(),
                f"{len(bad)} point(s) are not on walkable tiles.\n"
                "Move them onto white before saving.",
                parent=self,
            )
            return
        blocked_segs = sum(1 for p in self.paths if not p) if len(self.patrol) >= 2 else 0
        if blocked_segs and not messagebox.askyesno(
            self.title(),
            f"{blocked_segs} path segment(s) have no walkable route.\n"
            "Save patrol points anyway?",
            parent=self,
        ):
            return

        try:
            pack = ensure_dungeon_pack(
                map_id=mid,
                image_path=self.asset.image_path,
                origin_x=ox,
                origin_y=oy,
                pixel_scale=ps,
                display_name=str(self.var_name.get()).strip() or mid,
            )
            pts = [(x, y) for x, y, _n in self.patrol]
            names = [n for _x, _y, n in self.patrol]
            overlay = save_patrol_overlay(mid, pts, names)
        except Exception as exc:
            messagebox.showerror(self.title(), str(exc), parent=self)
            return

        self.map_id = mid
        self._dirty = False
        self._recompute_paths()
        self.status.configure(text=f"Saved {mid} · {len(self.patrol)} points")
        messagebox.showinfo(
            self.title(),
            f"Saved:\n"
            f"  {pack / 'meta.yaml'}\n"
            f"  {pack / 'nav.png'}\n"
            f"  {overlay}\n"
            f"  {len(self.patrol)} patrol points",
            parent=self,
        )
        self.refresh_assets()

    def _confirm_discard(self) -> bool:
        return messagebox.askyesno(
            self.title(),
            "Discard unsaved patrol changes?",
            parent=self,
        )

    def _on_close(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        self.destroy()


def run_dungeon_patrol_editor() -> int:
    app = DungeonPatrolEditor()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_dungeon_patrol_editor())
