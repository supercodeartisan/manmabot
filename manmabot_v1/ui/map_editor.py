"""Nav-map canvas to edit farm rects and dungeon patrol points."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk
from tkinter import messagebox

from manmabot_v1.localized_names import route_point_display_name
from manmabot_v1.map_previews import open_real_map_image
from manmabot_v1.paths import assert_userdata_write, ensure_userdata, manmabot_root
from manmabot_v1.ui import design_system as ui_theme
from manmabot_v1.probes import (
    farms_yaml_path,
    is_dungeon_map_id,
    list_patrol_entries,
    load_map_pack_safe,
    writable_farms_yaml_path,
    writable_patrol_yaml_path,
)


Handle = Optional[str]  # nw/n/ne/e/se/s/sw/w/move
_HANDLE_PX = 8
_ZOOM_MIN = 0.4
_ZOOM_MAX = 12.0


class MapEditor(ctk.CTkFrame):
    """Draw / resize farms and place patrol midpoints on ``images/real_maps`` art."""

    def __init__(
        self,
        master,
        *,
        strings,
        can_edit: Callable[[], bool],
        on_changed: Optional[Callable[[], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        language: str | None = None,
    ) -> None:
        super().__init__(master)
        self.s = strings
        self._can_edit = can_edit
        self._on_changed = on_changed or (lambda: None)
        self._on_done = on_done or (lambda: None)
        self.language = str(language or "en")
        self.map_id = ""
        self._pack = None
        self._dungeon = False
        self._scale = 1.0
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_origin = [0.0, 0.0]
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._base: Optional[Image.Image] = None
        self._terrain = None
        self.farms: list[dict] = []
        self.patrol: list[tuple[int, int, str]] = []
        self._patrol_paths: list[list[tuple[int, int]]] = []
        self.selected: tuple[str, int] | None = None
        self._dungeon_override: Optional[bool] = None
        self.tool = "select"
        self._drag: Handle = None
        self._drag_origin: dict | tuple | None = None
        self._rect_anchor: tuple[int, int] | None = None
        self._hover_tile: tuple[int, int] | None = None
        self._hover_move: tuple[int, int] | None = None
        self._dirty = False
        self._filling_inspector = False
        self._reflowing = False
        self._scroll_sync = False
        self._laying_side = False

        self.grid_columnconfigure(0, minsize=300, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.configure(fg_color="#f3f5f8")

        header = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 4))
        title_box = ctk.CTkFrame(title_row, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            title_box,
            text=self.s.edit_farms,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#1f2937",
            anchor="w",
        ).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(
            title_box,
            text=self.s.editor_hint_island,
            font=ctk.CTkFont(size=11),
            text_color="#6b7280",
            anchor="w",
            wraplength=520,
            justify="left",
        )
        self.subtitle.pack(anchor="w")

        self.tools = ctk.CTkFrame(header, fg_color="transparent", height=40)
        self.tools.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        self.tools.grid_propagate(False)
        self.tools.bind("<Configure>", self._reflow_tools)
        quiet = {
            "fg_color": "#ffffff",
            "hover_color": "#eef4ff",
            "text_color": "#1f2937",
            "border_width": 1,
            "border_color": "#d7dee8",
            "corner_radius": 8,
            "height": 32,
        }
        self.btn_select = ctk.CTkButton(
            self.tools, text=self.s.select_tool, width=self._text_width(self.s.select_tool),
            command=lambda: self._set_tool("select"), **quiet
        )
        self.btn_draw = ctk.CTkButton(
            self.tools, text=self.s.draw_farm, width=self._text_width(self.s.draw_farm),
            command=lambda: self._set_tool("draw"), **quiet
        )
        self.btn_patrol = ctk.CTkButton(
            self.tools, text=self.s.place_patrol, width=self._text_width(self.s.place_patrol),
            command=lambda: self._set_tool("patrol"), **quiet
        )
        self.btn_delete = ctk.CTkButton(
            self.tools, text=self.s.delete_selected, width=self._text_width(self.s.delete_selected),
            command=self._delete_selected, **quiet
        )
        self.btn_dup = ctk.CTkButton(
            self.tools, text=self.s.duplicate, width=self._text_width(self.s.duplicate),
            command=self._duplicate_selected, **quiet
        )
        self.btn_up = ctk.CTkButton(
            self.tools, text=self.s.move_up, width=self._text_width(self.s.move_up),
            command=lambda: self._nudge_selected(-1), **quiet
        )
        self.btn_down = ctk.CTkButton(
            self.tools, text=self.s.move_down, width=self._text_width(self.s.move_down),
            command=lambda: self._nudge_selected(1), **quiet
        )
        self.btn_clear = ctk.CTkButton(
            self.tools, text=self.s.clear_all, width=self._text_width(self.s.clear_all),
            command=self._clear_all, **quiet
        )
        self.btn_reload = ctk.CTkButton(
            self.tools, text=self.s.reload_areas, width=self._text_width(self.s.reload_areas),
            command=self._reload_from_disk, **quiet
        )
        self.btn_save = ctk.CTkButton(
            self.tools, text=self.s.save_areas, width=self._text_width(self.s.save_areas),
            command=self.save, **quiet
        )
        self.btn_done = ctk.CTkButton(
            title_row,
            text=self.s.edit_done,
            width=self._text_width(self.s.edit_done),
            height=32,
            corner_radius=8,
            fg_color="#1d6fe8",
            hover_color="#1558c0",
            command=self._done,
        )
        self.btn_done.pack(side="right", padx=(12, 0))
        self._tool_buttons = (
            self.btn_select,
            self.btn_draw,
            self.btn_patrol,
            self.btn_delete,
            self.btn_dup,
            self.btn_up,
            self.btn_down,
            self.btn_clear,
            self.btn_reload,
            self.btn_save,
            self.btn_done,
        )

        side = ctk.CTkFrame(self, width=300, fg_color="#ffffff", corner_radius=0)
        side.grid(row=1, column=0, sticky="nsew")
        self._side = side
        list_head = ctk.CTkFrame(side, fg_color="transparent")
        list_head.pack(side="top", fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            list_head,
            text=self.s.editor_list,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#1f2937",
        ).pack(side="left")
        self.list_count = ctk.CTkLabel(
            list_head,
            text="0",
            width=28,
            height=20,
            corner_radius=10,
            fg_color="#eef2f6",
            text_color="#4b5563",
            font=ctk.CTkFont(size=11),
        )
        self.list_count.pack(side="left", padx=6)
        self.btn_add = ctk.CTkButton(
            side,
            text="+",
            height=32,
            corner_radius=8,
            fg_color="#ffffff",
            hover_color="#eef4ff",
            text_color="#1d6fe8",
            border_width=1,
            border_color="#1d6fe8",
            command=self._add_from_list,
        )
        insp = ctk.CTkFrame(side, fg_color="transparent")
        self._insp = insp
        insp.pack(side="bottom", fill="x", padx=12, pady=(4, 12))
        self.btn_add.pack(side="top", fill="x", padx=12, pady=(0, 6))
        self.item_list = ctk.CTkScrollableFrame(
            side, height=80, fg_color="#ffffff",
        )
        self.item_list.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        self.item_list._parent_frame.grid_propagate(False)
        self.item_list._parent_frame.pack_propagate(False)
        ctk.CTkLabel(
            insp,
            text=self.s.rename_label,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#1f2937",
        ).pack(anchor="w", pady=(4, 2))
        self.name_var = tk.StringVar()
        self.name_entry = ctk.CTkEntry(
            insp, textvariable=self.name_var, height=32, corner_radius=8,
            border_color="#d7dee8",
        )
        self.name_entry.pack(fill="x", pady=(0, 8))
        self.name_entry.bind("<Return>", lambda _e: self._apply_inspector())
        self.name_entry.bind("<FocusOut>", lambda _e: self._apply_inspector())

        self.coord_frame = ctk.CTkFrame(insp, fg_color="transparent")
        self.coord_frame.pack(fill="x")
        self.coord_frame.grid_columnconfigure(1, weight=1)
        self._coord_vars = {
            "x0": tk.StringVar(),
            "y0": tk.StringVar(),
            "x1": tk.StringVar(),
            "y1": tk.StringVar(),
            "x": tk.StringVar(),
            "y": tk.StringVar(),
        }
        self._coord_labels: dict[str, ctk.CTkLabel] = {}
        self._coord_entries: dict[str, ctk.CTkEntry] = {}
        self._coord_steps: dict[str, tuple[ctk.CTkButton, ctk.CTkButton]] = {}
        for key, caption in (
            ("x0", "X0"),
            ("y0", "Y0"),
            ("x1", "X1"),
            ("y1", "Y1"),
            ("x", "X"),
            ("y", "Y"),
        ):
            lab = ctk.CTkLabel(
                self.coord_frame, text=caption, width=28, anchor="w", text_color="#4b5563",
            )
            ent = ctk.CTkEntry(
                self.coord_frame, textvariable=self._coord_vars[key], height=30,
                corner_radius=8, border_color="#d7dee8",
            )
            ent.bind("<Return>", lambda _e: self._apply_inspector())
            ent.bind("<FocusOut>", lambda _e: self._apply_inspector())
            step = {
                "width": 22, "height": 30, "fg_color": "#f8fafc", "hover_color": "#eef4ff",
                "text_color": "#1f2937", "border_width": 1, "border_color": "#d7dee8",
                "corner_radius": 6,
            }
            minus = ctk.CTkButton(
                self.coord_frame, text="−", command=lambda k=key: self._step_coord(k, -1), **step
            )
            plus = ctk.CTkButton(
                self.coord_frame, text="+", command=lambda k=key: self._step_coord(k, 1), **step
            )
            self._coord_labels[key] = lab
            self._coord_entries[key] = ent
            self._coord_steps[key] = (minus, plus)

        canvas_wrap = ctk.CTkFrame(self, fg_color="#e8edf2", corner_radius=0)
        self.canvas_wrap = canvas_wrap
        canvas_wrap.grid(row=1, column=1, sticky="nsew")
        canvas_wrap.grid_rowconfigure(0, weight=1)
        canvas_wrap.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_wrap, background="#e8edf2", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = tk.Scrollbar(canvas_wrap, orient="vertical", command=self._on_yview)
        self.hbar = tk.Scrollbar(canvas_wrap, orient="horizontal", command=self._on_xview)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        zoom = ctk.CTkFrame(canvas_wrap, fg_color="#ffffff", corner_radius=8, border_width=1, border_color="#e5e7eb")
        zoom.place(relx=1.0, rely=0.0, x=-28, y=12, anchor="ne")
        canvas_wrap.bind("<Configure>", self._layout_sidebar)
        for text, command in (
            ("+", lambda: self._zoom_by(1.15)),
            ("−", lambda: self._zoom_by(1 / 1.15)),
            ("⌂", self._recenter),
        ):
            ctk.CTkButton(
                zoom, text=text, width=32, height=32, fg_color="#ffffff",
                hover_color="#eef4ff", text_color="#1f2937", command=command,
            ).pack(padx=4, pady=2)

        footer = ctk.CTkFrame(self, fg_color="#e8f1ff", corner_radius=0, height=36)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.status = ctk.CTkLabel(
            footer,
            text="",
            text_color="#1e4b8f",
            wraplength=760,
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self.status.pack(side="left", padx=12, pady=6)
        self.zoom_label = ctk.CTkLabel(
            footer, text="100%", text_color="#4b5563", font=ctk.CTkFont(size=12),
        )
        self.zoom_label.pack(side="right", padx=12)

        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-3>", self._pan_start_event)
        self.canvas.bind("<B3-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self.canvas.bind("<ButtonPress-2>", self._pan_start_event)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<Delete>", lambda _e: self._delete_selected())
        self.canvas.bind("<BackSpace>", lambda _e: self._delete_selected())
        self.canvas.bind("<Escape>", lambda _e: self._deselect())
        self.canvas.bind("<Control-s>", lambda _e: self.save())
        self.canvas.bind("<Control-S>", lambda _e: self.save())
        self._sync_tools()

    def _layout_sidebar(self, _event=None) -> None:
        if self._laying_side or not hasattr(self, "_insp"):
            return
        height = self.canvas_wrap.winfo_height()
        if height < 160:
            return
        if abs(self._side.winfo_height() - height) > 2:
            self._side.configure(height=height)
        used = (
            self.list_count.master.winfo_reqheight()
            + self.btn_add.winfo_reqheight()
            + self._insp.winfo_reqheight()
            + 40
        )
        remain = max(72, height - used)
        self._laying_side = True
        try:
            self.item_list.configure(height=remain)
            self.item_list._parent_frame.configure(height=remain)
        finally:
            self._laying_side = False

    def _text_width(self, text: str, pad: int = 28, minimum: int = 64) -> int:
        font = tkfont.Font(family="Segoe UI", size=13)
        return max(minimum, font.measure(str(text)) + pad)

    def _visible_tools(self) -> list:
        buttons = [self.btn_select]
        buttons.append(self.btn_patrol if self._dungeon else self.btn_draw)
        buttons.extend(
            [
                self.btn_delete,
                self.btn_dup,
                self.btn_up,
                self.btn_down,
                self.btn_clear,
                self.btn_reload,
                self.btn_save,
            ]
        )
        return buttons

    def _sync_tools(self) -> None:
        for btn in self._tool_buttons:
            if btn is self.btn_done:
                continue
            btn.place_forget()
        add = self.s.place_patrol if self._dungeon else self.s.draw_farm
        self.btn_add.configure(text=f"+  {add}")
        self._paint_tools()
        self._reflow_tools()

    def _reflow_tools(self, _event=None) -> None:
        if self._reflowing or not hasattr(self, "tools"):
            return
        self._reflowing = True
        try:
            width = self.tools.winfo_width()
            if width < 80:
                return
            x = 0
            y = 0
            row_h = 40
            for btn in self._visible_tools():
                w = int(btn.cget("width"))
                if x and x + w > width:
                    x = 0
                    y += row_h
                btn.place(x=x, y=y)
                x += w + 6
            height = y + 36
            if int(self.tools.cget("height")) != height:
                self.tools.configure(height=height)
        finally:
            self._reflowing = False

    def _paint_tools(self) -> None:
        active = {
            "select": self.btn_select,
            "draw": self.btn_draw,
            "patrol": self.btn_patrol,
        }.get(self.tool)
        for btn in (
            self.btn_select, self.btn_draw, self.btn_patrol, self.btn_delete,
            self.btn_dup, self.btn_up, self.btn_down, self.btn_clear,
            self.btn_reload, self.btn_save,
        ):
            if btn is active:
                btn.configure(
                    fg_color="#1d6fe8", hover_color="#1558c0", text_color="#ffffff",
                    border_width=0,
                )
            else:
                btn.configure(
                    fg_color="#ffffff", hover_color="#eef4ff", text_color="#1f2937",
                    border_width=1, border_color="#d7dee8",
                )

    def _add_from_list(self) -> None:
        self._set_tool("patrol" if self._dungeon else "draw")

    def _step_coord(self, key: str, delta: int) -> None:
        try:
            value = int(self._coord_vars[key].get() or "0") + delta
        except ValueError:
            return
        self._coord_vars[key].set(str(value))
        self._apply_inspector()

    def _zoom_by(self, factor: float) -> None:
        if self._base is None:
            return
        cx = max(self.canvas.winfo_width(), 40) / 2
        cy = max(self.canvas.winfo_height(), 40) / 2
        old = max(self._scale, 1e-6)
        wx = (cx - self._pan[0]) / old
        wy = (cy - self._pan[1]) / old
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        self._fit()
        self._pan[0] = cx - wx * self._scale
        self._pan[1] = cy - wy * self._scale
        self._redraw()

    def _recenter(self) -> None:
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._redraw()

    def _mark_dirty(self) -> None:
        self._dirty = True
        if self._dungeon:
            self._recompute_patrol_paths()

    def _hint(self) -> str:
        extra = self.s.editor_nav_hint
        if self._dungeon:
            return f"{self.s.editor_hint_dungeon}  {extra}"
        return f"{self.s.editor_hint_island}  {extra}"

    def _set_tool(self, tool: str) -> None:
        if not self._can_edit():
            return
        if self._dungeon and tool == "draw":
            return
        if not self._dungeon and tool == "patrol":
            return
        self.tool = tool
        self._paint_tools()
        self.status.configure(text=self._hint())
        self._redraw()

    def load_map(self, map_id: str, *, dungeon: bool | None = None) -> None:
        self.map_id = str(map_id or "")
        self._pack = load_map_pack_safe(self.map_id)
        self.selected = None
        self.farms = []
        self.patrol = []
        self._patrol_paths = []
        self._terrain = None
        self._base = None
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._dungeon_override = dungeon
        if dungeon is None:
            self._dungeon = is_dungeon_map_id(self.map_id)
        else:
            self._dungeon = bool(dungeon)
        self.subtitle.configure(
            text=self.s.editor_hint_dungeon if self._dungeon else self.s.editor_hint_island
        )
        self.tool = "select"
        self._dirty = False
        self._sync_tools()
        if self._pack is None:
            self.status.configure(text=self.s.map_missing_short)
            self._refresh_list()
            self._fill_inspector()
            self._redraw()
            return
        try:
            self._base = open_real_map_image(self.map_id)
        except Exception:
            self._base = None
        if self._base is None and self._pack is not None:
            try:
                self._base = Image.open(self._pack.terrain_path).convert("RGBA")
            except Exception:
                self._base = None
        if self._base is None:
            self.status.configure(text=self.s.map_missing_short)
        if not self._dungeon:
            self._load_farms()
        self.patrol = list_patrol_entries(self.map_id) if self._dungeon else []
        try:
            from app._03_world.terrain_map import TerrainMap

            self._terrain = TerrainMap.from_png(
                self._pack.terrain_path,
                pixel_scale=max(1, int(self._pack.pixel_scale)),
            )
        except Exception:
            self._terrain = None
        self.status.configure(
            text=self.s.map_missing_short if self._base is None else self._hint()
        )
        self._recompute_patrol_paths()
        self._refresh_list()
        self._fill_inspector()
        self._redraw()

    def _recompute_patrol_paths(self) -> None:
        self._patrol_paths = []
        if not self._dungeon or self._terrain is None or len(self.patrol) < 2:
            return
        try:
            from app._04_decision.pathfinding import find_path
        except Exception:
            return
        for i in range(len(self.patrol) - 1):
            a = self.patrol[i][:2]
            b = self.patrol[i + 1][:2]
            self._patrol_paths.append(find_path(self._terrain, a, b))
        a = self.patrol[-1][:2]
        b = self.patrol[0][:2]
        self._patrol_paths.append(find_path(self._terrain, a, b))

    def _load_farms(self) -> None:
        import yaml

        path = farms_yaml_path(self.map_id)
        self.farms = []
        if path is None or not path.is_file():
            return
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        areas = doc.get("areas") or doc.get("farm_areas") or []
        region = (self._pack.default_region if self._pack else "") or ""
        for i, item in enumerate(areas):
            if not isinstance(item, dict):
                continue
            try:
                self.farms.append(
                    {
                        "name": str(item.get("name") or f"area_{i + 1}"),
                        "region": str(item.get("region") or region),
                        "x0": int(item["x0"]),
                        "y0": int(item["y0"]),
                        "x1": int(item["x1"]),
                        "y1": int(item["y1"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

    def save(self, *_args) -> bool:
        if not self._can_edit():
            return False
        if self._pack is None:
            return False
        ensure_userdata()
        root = manmabot_root()
        if str(root) not in __import__("sys").path:
            __import__("sys").path.insert(0, str(root))
        from app._04_decision.farm_area import FarmRect, save_farm_areas_yaml
        from app._04_decision.patrol import save_patrol_waypoints_yaml

        self._apply_inspector()
        if self._dungeon:
            pts = [(x, y) for x, y, _n in self.patrol]
            names = [n for _x, _y, n in self.patrol]
            path = assert_userdata_write(writable_patrol_yaml_path(self.map_id))
            save_patrol_waypoints_yaml(path, pts, names)
            self.status.configure(text=self.s.saved_patrol)
        else:
            rects = [
                FarmRect(
                    x0=f["x0"],
                    y0=f["y0"],
                    x1=f["x1"],
                    y1=f["y1"],
                    name=f["name"],
                    region=f["region"],
                )
                for f in self.farms
                if not f.get("_preview")
            ]
            farms_path = assert_userdata_write(writable_farms_yaml_path(self.map_id))
            save_farm_areas_yaml(
                farms_path, rects, default_region=self._pack.default_region
            )
            self.status.configure(text=self.s.saved_areas)
        self._dirty = False
        self._on_changed()
        return True

    def dismiss(self) -> None:
        """Save dirty edits (if allowed) and close the extra editor panel."""
        self._done()

    def _done(self) -> None:
        if self._dirty and self._can_edit():
            self.save()
        self._on_done()

    def _reload_from_disk(self) -> None:
        if not self._can_edit():
            return
        if self._dirty and not messagebox.askyesno(
            self.s.tab_farms, self.s.confirm_reload, parent=self.winfo_toplevel()
        ):
            return
        self.load_map(self.map_id)

    def _pixel_scale(self) -> int:
        if self._pack is None:
            return 4
        return max(1, int(self._pack.pixel_scale))

    def _map_limits(self) -> tuple[int, int]:
        if self._terrain is not None:
            return self._terrain.width - 1, self._terrain.height - 1
        if self._base is not None:
            ps = self._pixel_scale()
            iw, ih = self._base.size
            return max(0, iw // ps - 1), max(0, ih // ps - 1)
        return 9999, 9999

    def _clamp_tile(self, tx: int, ty: int) -> tuple[int, int]:
        mx, my = self._map_limits()
        return max(0, min(mx, tx)), max(0, min(my, ty))

    def _fit(self) -> None:
        if self._base is None:
            return
        cw = max(self.canvas.winfo_width(), 40)
        ch = max(self.canvas.winfo_height(), 40)
        iw, ih = self._base.size
        fit = min(cw / iw, ch / ih)
        self._scale = max(0.05, fit * self._zoom)

    def _tile_to_canvas(self, tx: float, ty: float) -> tuple[float, float]:
        ps = self._pixel_scale()
        return tx * ps * self._scale + self._pan[0], ty * ps * self._scale + self._pan[1]

    def _canvas_to_tile(self, cx: float, cy: float) -> tuple[int, int]:
        ps = self._pixel_scale()
        scale = max(self._scale * ps, 1e-6)
        tx = int((cx - self._pan[0]) / scale)
        ty = int((cy - self._pan[1]) / scale)
        return self._clamp_tile(tx, ty)

    def _view_size(self) -> tuple[int, int]:
        return max(self.canvas.winfo_width(), 40), max(self.canvas.winfo_height(), 40)

    def _image_size(self) -> tuple[int, int]:
        if self._base is None:
            return 1, 1
        iw, ih = self._base.size
        return max(1, int(iw * self._scale)), max(1, int(ih * self._scale))

    def _clamp_pan(self) -> None:
        if self._base is None:
            return
        dw, dh = self._image_size()
        cw, ch = self._view_size()
        self._pan[0] = self._axis_pan(self._pan[0], dw, cw)
        self._pan[1] = self._axis_pan(self._pan[1], dh, ch)

    @staticmethod
    def _axis_pan(pan: float, content: int, view: int) -> float:
        if content <= view:
            return float(max(0, min(view - content, pan)))
        return float(max(view - content, min(0, pan)))

    def _sync_scrollbars(self) -> None:
        if not hasattr(self, "hbar"):
            return
        dw, dh = self._image_size()
        cw, ch = self._view_size()
        self._scroll_sync = True
        try:
            self.hbar.set(*self._scroll_span(-self._pan[0], dw, cw))
            self.vbar.set(*self._scroll_span(-self._pan[1], dh, ch))
        finally:
            self._scroll_sync = False

    @staticmethod
    def _scroll_span(offset: float, content: int, view: int) -> tuple[float, float]:
        if content <= view:
            return 0.0, 1.0
        start = max(0.0, min(float(content - view), offset)) / content
        end = min(1.0, (start * content + view) / content)
        return start, end

    def _on_xview(self, *args) -> None:
        self._scroll_axis(0, *args)

    def _on_yview(self, *args) -> None:
        self._scroll_axis(1, *args)

    def _scroll_axis(self, axis: int, *args) -> None:
        if self._scroll_sync or self._base is None or not args:
            return
        self._fit()
        dw, dh = self._image_size()
        cw, ch = self._view_size()
        content, view = (dw, cw) if axis == 0 else (dh, ch)
        if content <= view:
            return
        pan = self._pan[axis]
        if args[0] == "moveto":
            pan = -float(args[1]) * content
        elif args[0] == "scroll":
            step = int(args[1])
            amount = 48 if len(args) < 3 or args[2] == "units" else view * 0.8
            pan -= step * amount
        self._pan[axis] = pan
        self._clamp_pan()
        self._redraw()

    def _on_wheel(self, event) -> str:
        if self._base is None:
            return "break"
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        old = max(self._scale, 1e-6)
        wx = (event.x - self._pan[0]) / old
        wy = (event.y - self._pan[1]) / old
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        self._fit()
        self._pan[0] = event.x - wx * self._scale
        self._pan[1] = event.y - wy * self._scale
        self._redraw()
        return "break"

    def _pan_start_event(self, event) -> None:
        self._panning = True
        self._pan_start = (event.x, event.y)
        self._pan_origin = list(self._pan)
        self.canvas.focus_set()

    def _pan_move(self, event) -> None:
        if not self._panning:
            return
        self._pan[0] = self._pan_origin[0] + (event.x - self._pan_start[0])
        self._pan[1] = self._pan_origin[1] + (event.y - self._pan_start[1])
        self._redraw()

    def _pan_end(self, _event) -> None:
        self._panning = False

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self._base is None:
            self.canvas.create_text(
                10, 10, anchor="nw", fill="#888888", text=self.s.map_missing_short
            )
            return
        self._fit()
        self._clamp_pan()
        iw, ih = self._base.size
        dw, dh = max(1, int(iw * self._scale)), max(1, int(ih * self._scale))
        shown = self._base.resize((dw, dh), Image.Resampling.NEAREST).convert("RGBA")
        overlay = Image.new("RGBA", shown.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        ps = self._pixel_scale()
        if not self._dungeon:
            for i, f in enumerate(self.farms):
                if f.get("_preview"):
                    fill = (250, 204, 21, 70)
                    outline = (202, 138, 4, 255)
                elif self.selected == ("farm", i):
                    fill = (29, 111, 232, 80)
                    outline = (29, 111, 232, 255)
                else:
                    fill = (56, 189, 248, 55)
                    outline = (29, 111, 232, 200)
                x0 = int(f["x0"] * ps * self._scale)
                y0 = int(f["y0"] * ps * self._scale)
                x1 = int((f["x1"] + 1) * ps * self._scale) - 1
                y1 = int((f["y1"] + 1) * ps * self._scale) - 1
                draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=2)
        if len(self.patrol) >= 2:
            ps = self._pixel_scale()
            # Prefer A* corridors; fall back to straight segments.
            paths = self._patrol_paths
            if paths:
                for path in paths:
                    if len(path) < 2:
                        continue
                    pts = []
                    for tx, ty in path:
                        pts.append(
                            (
                                (tx * ps + ps / 2) * self._scale,
                                (ty * ps + ps / 2) * self._scale,
                            )
                        )
                    draw.line(pts, fill=(56, 189, 248, 210), width=max(2, int(2 * self._scale)))
            else:
                pts = []
                for tx, ty, _n in self.patrol:
                    cx = tx * ps * self._scale + ps * self._scale / 2
                    cy = ty * ps * self._scale + ps * self._scale / 2
                    pts.append((cx, cy))
                draw.line(pts, fill="#ca8a04", width=2)
                if len(pts) >= 3:
                    draw.line([pts[-1], pts[0]], fill="#854d0e", width=1)
        for i, (tx, ty, _n) in enumerate(self.patrol):
            cx = tx * ps * self._scale + ps * self._scale / 2
            cy = ty * ps * self._scale + ps * self._scale / 2
            r = 6 if self.selected == ("patrol", i) else 5
            fill = "#f97316" if self.selected == ("patrol", i) else "#eab308"
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=2)
        shown = Image.alpha_composite(shown, overlay)
        self._photo = ImageTk.PhotoImage(shown)
        self.canvas.create_image(self._pan[0], self._pan[1], anchor="nw", image=self._photo)
        if not self._dungeon:
            for i, f in enumerate(self.farms):
                x0, y0 = self._tile_to_canvas(f["x0"], f["y0"])
                selected = self.selected == ("farm", i)
                label = self.canvas.create_text(
                    x0 + 6,
                    max(8, y0 - 16),
                    anchor="nw",
                    fill="#ffffff" if selected else "#1f2937",
                    text=str(f["name"]),
                    font=(ui_theme.FONT_BODY[0], 9, "bold"),
                )
                bounds = self.canvas.bbox(label)
                if bounds:
                    background = self.canvas.create_rectangle(
                        bounds[0] - 4,
                        bounds[1] - 2,
                        bounds[2] + 4,
                        bounds[3] + 2,
                        fill="#1d6fe8" if selected else "#ffffff",
                        outline="#1d6fe8",
                    )
                    self.canvas.tag_lower(background, label)
            if self.selected and self.selected[0] == "farm":
                self._draw_handles(self.farms[self.selected[1]])
        for i, (tx, ty, _n) in enumerate(self.patrol):
            cx, cy = self._tile_to_canvas(tx + 0.5, ty + 0.5)
            self.canvas.create_text(
                cx + 8,
                cy - 8,
                anchor="nw",
                fill="#fde68a",
                text=str(i + 1),
                font=(ui_theme.FONT_BODY[0], 9, "bold"),
            )
        if self._hover_tile is not None:
            hx, hy = self._hover_tile
            self.canvas.create_text(
                8,
                max(self.canvas.winfo_height() - 18, 8),
                anchor="sw",
                fill="#1e3a5f",
                text=self.s.editor_hover.format(x=hx, y=hy),
                font=(ui_theme.FONT_BODY[0], 9),
                tags="hover",
            )
        self._sync_scrollbars()
        self._show_zoom()

    def _show_zoom(self) -> None:
        if not hasattr(self, "zoom_label"):
            return
        pct = int(round(self._zoom * 100))
        self.zoom_label.configure(text=f"{pct}%")

    def _redraw_hover(self) -> None:
        self.canvas.delete("hover")
        if self._hover_tile is None:
            return
        hx, hy = self._hover_tile
        self.canvas.create_text(
            8,
            max(self.canvas.winfo_height() - 18, 8),
            anchor="sw",
            fill="#1e3a5f",
            text=self.s.editor_hover.format(x=hx, y=hy),
            font=(ui_theme.FONT_BODY[0], 9),
            tags="hover",
        )
        self._show_zoom()

    def _draw_handles(self, f: dict) -> None:
        for _name, (cx, cy) in self._handle_points(f).items():
            self.canvas.create_oval(
                cx - 5, cy - 5, cx + 5, cy + 5, outline="#1d6fe8", fill="#ffffff", width=2
            )

    def _handle_points(self, f: dict) -> dict[str, tuple[float, float]]:
        x0, y0 = self._tile_to_canvas(f["x0"], f["y0"])
        x1, y1 = self._tile_to_canvas(f["x1"] + 1, f["y1"] + 1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return {
            "nw": (x0, y0),
            "n": (mx, y0),
            "ne": (x1, y0),
            "e": (x1, my),
            "se": (x1, y1),
            "s": (mx, y1),
            "sw": (x0, y1),
            "w": (x0, my),
        }

    def _hit_handle(self, f: dict, cx: float, cy: float) -> Handle:
        best: Handle = None
        best_d = _HANDLE_PX
        for name, (hx, hy) in self._handle_points(f).items():
            d = max(abs(cx - hx), abs(cy - hy))
            if d <= best_d:
                best_d = d
                best = name
        return best

    def _hit_farm(self, tx: int, ty: int) -> Optional[int]:
        for i in range(len(self.farms) - 1, -1, -1):
            f = self.farms[i]
            if f.get("_preview"):
                continue
            if f["x0"] <= tx <= f["x1"] and f["y0"] <= ty <= f["y1"]:
                return i
        return None

    def _hit_patrol(self, tx: int, ty: int) -> Optional[int]:
        best_i = None
        best_d = 3
        for i, (x, y, _n) in enumerate(self.patrol):
            d = max(abs(x - tx), abs(y - ty))
            if d <= best_d:
                best_d = d
                best_i = i
        return best_i

    def _select(self, kind: str, idx: int) -> None:
        self.selected = (kind, idx)
        self._refresh_list()
        self._fill_inspector()
        self._redraw()

    def _deselect(self) -> None:
        self.selected = None
        self.tool = "select"
        self._refresh_list()
        self._fill_inspector()
        self._redraw()

    def _refresh_list(self) -> None:
        for w in self.item_list.winfo_children():
            w.destroy()
        if self._dungeon:
            items = [
                (name, f"({x}, {y})", "patrol", i)
                for i, (x, y, name) in enumerate(self.patrol)
            ]
        else:
            items = [
                (
                    f["name"],
                    f"({f['x0']}, {f['y0']} ~ {f['x1']}, {f['y1']})",
                    "farm",
                    i,
                )
                for i, f in enumerate(self.farms)
                if not f.get("_preview")
            ]
        if not items:
            self.list_count.configure(text="0")
            ctk.CTkLabel(
                self.item_list,
                text=self.s.editor_list_empty,
                text_color="#6b7280",
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=6, pady=8)
            return
        self.list_count.configure(text=str(len(items)))
        for name, detail, kind, idx in items:
            selected = self.selected == (kind, idx)
            card = ctk.CTkFrame(
                self.item_list,
                fg_color="#e8f1ff" if selected else "#ffffff",
                border_width=1,
                border_color="#1d6fe8" if selected else "#e5e7eb",
                corner_radius=8,
            )
            card.pack(fill="x", padx=4, pady=3)
            title = ctk.CTkLabel(
                card,
                text=route_point_display_name(name, self.language),
                anchor="w",
                text_color="#1f2937",
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            title.pack(fill="x", padx=10, pady=(8, 0))
            subtitle = ctk.CTkLabel(
                card, text=detail, anchor="w", text_color="#6b7280",
                font=ctk.CTkFont(size=11),
            )
            subtitle.pack(fill="x", padx=10, pady=(0, 8))
            for widget in (card, title, subtitle):
                widget.bind("<Button-1>", lambda _e, k=kind, i=idx: self._select(k, i))
        self._layout_sidebar()

    def _fill_inspector(self) -> None:
        self._filling_inspector = True
        try:
            if self.selected is None:
                self.name_var.set("")
                for v in self._coord_vars.values():
                    v.set("")
                self._show_coords(patrol=self._dungeon)
                return
            kind, idx = self.selected
            if kind == "farm" and 0 <= idx < len(self.farms):
                f = self.farms[idx]
                self.name_var.set(str(f["name"]))
                self._coord_vars["x0"].set(str(f["x0"]))
                self._coord_vars["y0"].set(str(f["y0"]))
                self._coord_vars["x1"].set(str(f["x1"]))
                self._coord_vars["y1"].set(str(f["y1"]))
                self._show_coords(patrol=False)
            elif kind == "patrol" and 0 <= idx < len(self.patrol):
                x, y, name = self.patrol[idx]
                self.name_var.set(name)
                self._coord_vars["x"].set(str(x))
                self._coord_vars["y"].set(str(y))
                self._show_coords(patrol=True)
        finally:
            self._filling_inspector = False

    def _show_coords(self, *, patrol: bool) -> None:
        keys = ("x", "y") if patrol else ("x0", "y0", "x1", "y1")
        hide = ("x0", "y0", "x1", "y1") if patrol else ("x", "y")
        for key in hide:
            self._coord_labels[key].grid_forget()
            self._coord_entries[key].grid_forget()
            for step in self._coord_steps[key]:
                step.grid_forget()
        for i, key in enumerate(keys):
            self._coord_labels[key].grid(row=i, column=0, sticky="w", pady=3)
            self._coord_entries[key].grid(row=i, column=1, sticky="ew", padx=6, pady=3)
            minus, plus = self._coord_steps[key]
            minus.grid(row=i, column=2, pady=3)
            plus.grid(row=i, column=3, padx=(4, 0), pady=3)

    def _apply_inspector(self) -> None:
        if self._filling_inspector or self.selected is None or not self._can_edit():
            return
        kind, idx = self.selected
        name = self.name_var.get().strip()
        try:
            if kind == "farm" and not self._dungeon and 0 <= idx < len(self.farms):
                f = self.farms[idx]
                x0 = int(self._coord_vars["x0"].get())
                y0 = int(self._coord_vars["y0"].get())
                x1 = int(self._coord_vars["x1"].get())
                y1 = int(self._coord_vars["y1"].get())
                x0, y0 = self._clamp_tile(x0, y0)
                x1, y1 = self._clamp_tile(x1, y1)
                f["x0"], f["x1"] = min(x0, x1), max(x0, x1)
                f["y0"], f["y1"] = min(y0, y1), max(y0, y1)
                if name:
                    f["name"] = name
                self._mark_dirty()
            elif kind == "patrol" and self._dungeon and 0 <= idx < len(self.patrol):
                x = int(self._coord_vars["x"].get())
                y = int(self._coord_vars["y"].get())
                x, y = self._clamp_tile(x, y)
                if self._terrain is not None and not self._terrain.is_walkable(x, y):
                    self.status.configure(text=self.s.patrol_not_walkable)
                    self._fill_inspector()
                    return
                old = self.patrol[idx]
                self.patrol[idx] = (x, y, name or old[2])
                self._mark_dirty()
        except ValueError:
            self._fill_inspector()
            return
        self._refresh_list()
        self._fill_inspector()
        self._redraw()

    def _on_down(self, event) -> None:
        if not self._can_edit() or self._base is None:
            return
        self.canvas.focus_set()
        tx, ty = self._canvas_to_tile(event.x, event.y)
        if self.tool == "draw":
            if self._dungeon:
                return
            self._rect_anchor = (tx, ty)
            self.selected = None
            return
        if self.tool == "patrol":
            if not self._dungeon:
                return
            hit = self._hit_patrol(tx, ty)
            if hit is not None:
                self._select("patrol", hit)
                self._drag = "move"
                self._drag_origin = self.patrol[hit]
                return
            if self._terrain is not None and not self._terrain.is_walkable(tx, ty):
                self.status.configure(text=self.s.patrol_not_walkable)
                return
            name = f"mid_{len(self.patrol) + 1}"
            self.patrol.append((tx, ty, name))
            self._mark_dirty()
            self._select("patrol", len(self.patrol) - 1)
            return
        if self._dungeon:
            hit_p = self._hit_patrol(tx, ty)
            if hit_p is not None:
                self._select("patrol", hit_p)
                self._drag = "move"
                self._drag_origin = self.patrol[hit_p]
                return
            self._deselect()
            return
        if self.selected and self.selected[0] == "farm":
            handle = self._hit_handle(self.farms[self.selected[1]], event.x, event.y)
            if handle:
                self._drag = handle
                self._drag_origin = dict(self.farms[self.selected[1]])
                self._hover_move = (tx, ty)
                return
        hit_f = self._hit_farm(tx, ty)
        if hit_f is not None:
            self._select("farm", hit_f)
            handle = self._hit_handle(self.farms[hit_f], event.x, event.y)
            self._drag = handle or "move"
            self._drag_origin = dict(self.farms[hit_f])
            self._hover_move = (tx, ty)
            return
        self._deselect()

    def _on_drag(self, event) -> None:
        if not self._can_edit() or self._base is None:
            return
        tx, ty = self._canvas_to_tile(event.x, event.y)
        if self.tool == "draw" and not self._dungeon and self._rect_anchor is not None:
            ax, ay = self._rect_anchor
            preview = {
                "name": "new",
                "region": self._pack.default_region if self._pack else "",
                "x0": min(ax, tx),
                "y0": min(ay, ty),
                "x1": max(ax, tx),
                "y1": max(ay, ty),
            }
            if self.farms and self.farms[-1].get("_preview"):
                self.farms[-1] = {**preview, "_preview": True}
            else:
                self.farms.append({**preview, "_preview": True})
            self._redraw()
            return
        if self.selected is None or self._drag is None:
            return
        kind, idx = self.selected
        if kind == "patrol":
            if self._terrain is not None and not self._terrain.is_walkable(tx, ty):
                return
            x, y, name = self.patrol[idx]
            self.patrol[idx] = (tx, ty, name)
            self._mark_dirty()
            self._redraw()
            return
        if self._dungeon or kind != "farm":
            return
        f = self.farms[idx]
        orig = self._drag_origin if isinstance(self._drag_origin, dict) else f
        handle = self._drag
        x0, y0, x1, y1 = orig["x0"], orig["y0"], orig["x1"], orig["y1"]
        if handle == "move" and self._hover_move:
            dx, dy = tx - self._hover_move[0], ty - self._hover_move[1]
            w, h = x1 - x0, y1 - y0
            x0, y0 = x0 + dx, y0 + dy
            x1, y1 = x0 + w, y0 + h
            self._hover_move = (tx, ty)
            self._drag_origin = {
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "name": f["name"],
                "region": f["region"],
            }
        else:
            if "n" in (handle or ""):
                y0 = ty
            if "s" in (handle or ""):
                y1 = ty
            if "w" in (handle or ""):
                x0 = tx
            if "e" in (handle or ""):
                x1 = tx
        x0, y0 = self._clamp_tile(x0, y0)
        x1, y1 = self._clamp_tile(x1, y1)
        f["x0"], f["x1"] = min(x0, x1), max(x0, x1)
        f["y0"], f["y1"] = min(y0, y1), max(y0, y1)
        self._mark_dirty()
        self._redraw()

    def _on_up(self, event) -> None:
        if self.tool == "draw" and not self._dungeon and self._rect_anchor is not None:
            tx, ty = self._canvas_to_tile(event.x, event.y)
            ax, ay = self._rect_anchor
            self._rect_anchor = None
            if self.farms and self.farms[-1].get("_preview"):
                self.farms.pop()
            x0, x1 = min(ax, tx), max(ax, tx)
            y0, y1 = min(ay, ty), max(ay, ty)
            if x1 - x0 < 1 and y1 - y0 < 1:
                self._redraw()
                return
            region = self._pack.default_region if self._pack else ""
            name = f"area_{len([f for f in self.farms if not f.get('_preview')]) + 1}"
            self.farms.append(
                {"name": name, "region": region, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
            )
            self._mark_dirty()
            self.tool = "select"
            self._select("farm", len(self.farms) - 1)
            return
        self._drag = None
        self._drag_origin = None
        self._hover_move = None
        self._refresh_list()
        self._fill_inspector()

    def _on_move(self, event) -> None:
        if self._base is None:
            return
        tile = self._canvas_to_tile(event.x, event.y)
        if tile == self._hover_tile:
            return
        self._hover_tile = tile
        self._redraw_hover()

    def _delete_selected(self) -> None:
        if not self._can_edit() or self.selected is None:
            return
        kind, idx = self.selected
        if kind == "farm" and not self._dungeon and 0 <= idx < len(self.farms):
            self.farms.pop(idx)
            self._mark_dirty()
        elif kind == "patrol" and 0 <= idx < len(self.patrol):
            self.patrol.pop(idx)
            self._mark_dirty()
        self.selected = None
        self._refresh_list()
        self._fill_inspector()
        self._redraw()

    def _duplicate_selected(self) -> None:
        if not self._can_edit() or self.selected is None:
            return
        kind, idx = self.selected
        if kind == "farm" and not self._dungeon and 0 <= idx < len(self.farms):
            src = dict(self.farms[idx])
            src["name"] = f"{src['name']}_copy"
            src["x0"], src["y0"] = self._clamp_tile(src["x0"] + 2, src["y0"] + 2)
            src["x1"], src["y1"] = self._clamp_tile(src["x1"] + 2, src["y1"] + 2)
            self.farms.append(src)
            self._mark_dirty()
            self._select("farm", len(self.farms) - 1)
        elif kind == "patrol" and 0 <= idx < len(self.patrol):
            x, y, name = self.patrol[idx]
            nx, ny = self._clamp_tile(x + 1, y)
            if self._terrain is not None and not self._terrain.is_walkable(nx, ny):
                nx, ny = x, y
            self.patrol.append((nx, ny, f"{name}_copy"))
            self._mark_dirty()
            self._select("patrol", len(self.patrol) - 1)

    def _nudge_selected(self, delta: int) -> None:
        if not self._can_edit() or self.selected is None:
            return
        kind, idx = self.selected
        seq = self.patrol if kind == "patrol" else self.farms
        nxt = idx + delta
        if nxt < 0 or nxt >= len(seq):
            return
        seq[idx], seq[nxt] = seq[nxt], seq[idx]
        self._mark_dirty()
        self._select(kind, nxt)

    def _clear_all(self) -> None:
        if not self._can_edit():
            return
        msg = self.s.confirm_clear_patrol if self._dungeon else self.s.confirm_clear_farms
        if not messagebox.askyesno(self.s.tab_farms, msg, parent=self.winfo_toplevel()):
            return
        if self._dungeon:
            self.patrol.clear()
        else:
            self.farms.clear()
        self.selected = None
        self._mark_dirty()
        self._refresh_list()
        self._fill_inspector()
        self._redraw()
