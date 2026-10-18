"""Pick one walkable tile on an engine map pack."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from PIL import Image, ImageTk

from dungeon.floor_route import MapChoice, PickedPoint, list_engine_maps
from ui.design_system import (
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


class MapPickDialog(tk.Toplevel):
    """Map list from ``Engine/data/maps``. Closing the window keeps the click."""

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("1100x720")
        self.minsize(860, 560)
        self.configure(bg=BG)
        apply_classic_style(self)
        self.transient(master)
        self.result: Optional[PickedPoint] = None
        self._maps = list_engine_maps()
        self._shown: list[MapChoice] = []
        self._choice: Optional[MapChoice] = None
        self._base: Optional[Image.Image] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._walkable = None
        self._point: Optional[tuple[int, int]] = None
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_origin = [0.0, 0.0]
        self._filter = tk.StringVar()
        self._build()
        self._apply_filter()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.grab_set()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.rowconfigure(2, weight=1)
        ttk.Label(left, text="엔진 맵", font=FONT_SECTION).grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self._filter, width=34).grid(
            row=1, column=0, sticky="ew", pady=(4, 4)
        )
        self._filter.trace_add("write", lambda *_a: self._apply_filter())
        wrap = ttk.Frame(left)
        wrap.grid(row=2, column=0, sticky="nsw")
        self.listbox = tk.Listbox(
            wrap,
            width=42,
            height=28,
            activestyle="dotbox",
            exportselection=False,
            bg=SURFACE,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=FONT_BODY,
        )
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="y")
        scroll.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(
            right,
            text="맵을 고르고 흰 칸을 클릭한 뒤 창을 닫으면 그 점이 선택됩니다.",
            foreground=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        host = ttk.Frame(right, relief="solid", borderwidth=1)
        host.grid(row=1, column=0, sticky="nsew")
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(host, bg="#1a1d23", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.status = ttk.Label(right, text="", foreground=TEXT_MUTED)
        self.status.grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _apply_filter(self) -> None:
        query = self._filter.get().strip().lower()
        self._shown = [
            item
            for item in self._maps
            if not query or query in item.label.lower() or query in item.pack_id.lower()
        ]
        self.listbox.delete(0, "end")
        for item in self._shown:
            self.listbox.insert("end", item.label)

    def _on_select(self, *_args) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        self._load(self._shown[int(sel[0])])

    def _load(self, choice: MapChoice) -> None:
        import numpy as np

        self._choice = choice
        self._point = None
        try:
            self._base = Image.open(choice.nav_path).convert("RGB")
        except OSError as exc:
            self.status.configure(text=f"맵을 열지 못했습니다: {exc}")
            return
        pixels = np.asarray(self._base, dtype=np.uint8)
        walkable = (
            (pixels[:, :, 0] == 255)
            & (pixels[:, :, 1] == 255)
            & (pixels[:, :, 2] == 255)
        )
        ps = choice.pixel_scale
        if ps > 1:
            height, width = walkable.shape
            th, tw = height // ps, width // ps
            blocks = walkable[: th * ps, : tw * ps].reshape(th, ps, tw, ps)
            walkable = blocks.mean(axis=(1, 3)) >= 0.5
        self._walkable = walkable
        self._fit()
        self.status.configure(text=f"{choice.label}  ·  칸을 클릭하세요")
        self._redraw()

    def _pixel_scale(self) -> int:
        if self._choice is None:
            return 1
        return max(1, self._choice.pixel_scale)

    def _fit(self) -> None:
        if self._base is None:
            return
        self.update_idletasks()
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self._base.size
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, min(cw / iw, ch / ih) * 0.98))
        self._pan = [(cw - iw * self._zoom) / 2, (ch - ih * self._zoom) / 2]

    def _canvas_to_tile(self, cx: float, cy: float) -> tuple[int, int]:
        scale = max(self._zoom * self._pixel_scale(), 1e-6)
        tx = int((cx - self._pan[0]) / scale)
        ty = int((cy - self._pan[1]) / scale)
        if self._walkable is None:
            return tx, ty
        height, width = self._walkable.shape
        return max(0, min(tx, width - 1)), max(0, min(ty, height - 1))

    def _walkable_at(self, tx: int, ty: int) -> bool:
        if self._walkable is None:
            return False
        height, width = self._walkable.shape
        if not (0 <= tx < width and 0 <= ty < height):
            return False
        return bool(self._walkable[ty, tx])

    def _on_click(self, event: tk.Event) -> None:
        if self._choice is None or self._walkable is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        if not self._walkable_at(tx, ty):
            self.status.configure(text="흰 칸만 선택할 수 있습니다.")
            return
        self._point = (tx, ty)
        world_x = self._choice.origin_x + tx * self._choice.pixel_scale
        world_y = self._choice.origin_y + ty * self._choice.pixel_scale
        self.status.configure(
            text=f"선택 ({tx}, {ty})  월드 ({world_x}, {world_y})  ·  창을 닫으면 확정"
        )
        self._redraw()

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
        tx = (event.x - self._pan[0]) / max(self._zoom, 1e-6)
        ty = (event.y - self._pan[1]) / max(self._zoom, 1e-6)
        self._zoom = new_zoom
        self._pan = [event.x - tx * self._zoom, event.y - ty * self._zoom]
        self._redraw()

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self._base is None:
            return
        iw, ih = self._base.size
        dw = max(1, int(round(iw * self._zoom)))
        dh = max(1, int(round(ih * self._zoom)))
        shown = self._base.resize((dw, dh), Image.Resampling.NEAREST)
        self._photo = ImageTk.PhotoImage(shown)
        self.canvas.create_image(self._pan[0], self._pan[1], anchor="nw", image=self._photo)
        if self._point is None:
            return
        ps = self._pixel_scale()
        tx, ty = self._point
        cx = self._pan[0] + (tx * ps + ps / 2) * self._zoom
        cy = self._pan[1] + (ty * ps + ps / 2) * self._zoom
        r = max(5, int(5 * self._zoom))
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r, fill="#22d3ee", outline="#ffffff", width=2
        )

    def _close(self) -> None:
        if self._choice is not None and self._point is not None:
            self.result = PickedPoint(
                choice=self._choice,
                nav_x=self._point[0],
                nav_y=self._point[1],
            )
        self.grab_release()
        self.destroy()


def pick_map_point(master: tk.Misc, title: str) -> Optional[PickedPoint]:
    dialog = MapPickDialog(master, title)
    master.wait_window(dialog)
    return dialog.result
