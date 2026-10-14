#!/usr/bin/env python3
"""Talking Scroll plan editor.

Loads the project's world-nav hubs JSON (click + wheel notches), edits those
fields on live LC.exe captures or offline 1..5.png snapshots, and writes the
same hubs file back so the bot picks up the change.
"""

from __future__ import annotations

import json
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
ENGINE_HUBS = (
    REPO
    / "Engine"
    / "data"
    / "world_nav"
    / "providers"
    / "20_hubs_talking_scroll.json"
)
TOOL_PLANS = ROOT / "talking_scroll_plans.json"
HANDWRITE_FILE = ROOT / "handwrite_data.txt"

SNAPSHOT_FILES = ["1.png", "2.png", "3.png", "4.png", "5.png"]
DEFAULT_SCROLL_TIMES = {
    name: scrolls for name, scrolls in zip(SNAPSHOT_FILES, (0, 18, 36, 54, 73))
}
REF_W = 800
REF_H = 600
LIVE_LABEL = "live"
ZOOM_MIN = 0.15
ZOOM_MAX = 8.0
ZOOM_STEP = 1.15


def parse_scroll_times_from_handwrite(text: str) -> dict[str, int]:
    """Read 'N - scrolls' from the first 5 non-empty lines of the notes file."""
    result = dict(DEFAULT_SCROLL_TIMES)
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\s*[-–—:]\s*(-?\d+)\s*$", line)
        if not match:
            break
        idx = int(match.group(1))
        scrolls = int(match.group(2))
        if 1 <= idx <= len(SNAPSHOT_FILES):
            result[SNAPSHOT_FILES[idx - 1]] = scrolls
        count += 1
        if count >= len(SNAPSHOT_FILES):
            break
    return result


def empty_spot(snapshot: str = "1.png", scroll_times: int = 0) -> dict[str, Any]:
    return {
        "index": None,
        "name": "",
        "snapshot": snapshot,
        "scroll_times": scroll_times,
        "click": {"x": None, "y": None},
        "region": "",
        "map": "",
        "mapId": None,
        "coordinates": {"x": None, "y": None},
    }


def hubs_to_spots(doc: dict[str, Any]) -> list[dict[str, Any]]:
    spots: list[dict[str, Any]] = []
    for raw in doc.get("hubs") or []:
        if not isinstance(raw, dict):
            continue
        ui = raw.get("ui") or {}
        click = ui.get("click") or {}
        spot = empty_spot(
            str(ui.get("snapshot") or "1.png"),
            int(ui.get("scroll_times") or 0),
        )
        spot["index"] = int(raw["index"]) if raw.get("index") is not None else None
        spot["name"] = str(raw.get("name") or "")
        spot["region"] = str(raw.get("region") or "")
        spot["map"] = str(raw.get("map_label") or "")
        spot["mapId"] = raw.get("mapId")
        spot["click"] = {
            "x": click.get("x"),
            "y": click.get("y"),
        }
        spot["coordinates"] = {"x": raw.get("x"), "y": raw.get("y")}
        spots.append(spot)
    spots.sort(key=lambda s: (s["index"] is None, s["index"] if s["index"] is not None else 0))
    return spots


def plans_to_spots(doc: dict[str, Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for i, item in enumerate(doc.get("plans") or []):
        if not isinstance(item, dict):
            continue
        snap = item.get("snapshot") or "1.png"
        spot = empty_spot(snap, int(item.get("scroll_times") or 0))
        spot["index"] = i
        spot["name"] = str(item.get("name") or "")
        spot["region"] = str(item.get("region") or "")
        map_val = item.get("map")
        spot["map"] = "" if map_val is None else map_val
        click = item.get("click") or {}
        coords = item.get("coordinates") or {}
        spot["click"] = {
            "x": click.get("x") if click.get("x") is not None else item.get("click_x"),
            "y": click.get("y") if click.get("y") is not None else item.get("click_y"),
        }
        spot["coordinates"] = {
            "x": coords.get("x") if coords.get("x") is not None else item.get("coord_x"),
            "y": coords.get("y") if coords.get("y") is not None else item.get("coord_y"),
        }
        cleaned.append(spot)
    return cleaned


def spots_to_plans_export(spots: list[dict[str, Any]], scroll_by_snapshot: dict[str, int]) -> dict[str, Any]:
    plans = []
    for spot in spots:
        plans.append(
            {
                "name": spot.get("name") or "",
                "snapshot": spot.get("snapshot") or "1.png",
                "scroll_times": int(spot.get("scroll_times") or 0),
                "click": {
                    "x": (spot.get("click") or {}).get("x"),
                    "y": (spot.get("click") or {}).get("y"),
                },
                "region": spot.get("region") or "",
                "map": spot.get("map") or "",
                "coordinates": {
                    "x": (spot.get("coordinates") or {}).get("x"),
                    "y": (spot.get("coordinates") or {}).get("y"),
                },
            }
        )
    return {
        "version": 1,
        "_comment": "Talking Scroll teleport plans. click.x/y are pixel coords on the snapshot images.",
        "_comment_snapshot_size": (
            "All snapshots share this resolution. Convert click to UV with: "
            "u = click.x / snapshot_size.width, v = click.y / snapshot_size.height"
        ),
        "snapshot_size": {"width": REF_W, "height": REF_H},
        "folder": str(ROOT),
        "snapshots": [
            {"file": name, "scroll_times": int(scroll_by_snapshot.get(name, 0))}
            for name in SNAPSHOT_FILES
        ],
        "plans": plans,
    }


def apply_spots_to_hubs_doc(doc: dict[str, Any], spots: list[dict[str, Any]]) -> int:
    """Patch click + scroll_times (+ snapshot) into hubs and mirrored edges.

    Name / region / world xy / mapId are left untouched.
    """
    by_index: dict[int, dict[str, Any]] = {}
    for spot in spots:
        idx = spot.get("index")
        if idx is None:
            continue
        by_index[int(idx)] = spot

    updated = 0
    for hub in doc.get("hubs") or []:
        if not isinstance(hub, dict):
            continue
        try:
            idx = int(hub["index"])
        except (KeyError, TypeError, ValueError):
            continue
        spot = by_index.get(idx)
        if spot is None:
            continue
        ui = hub.setdefault("ui", {})
        click = spot.get("click") or {}
        if click.get("x") is not None and click.get("y") is not None:
            ui["click"] = {"x": int(click["x"]), "y": int(click["y"])}
        ui["scroll_times"] = int(spot.get("scroll_times") or 0)
        snap = str(spot.get("snapshot") or ui.get("snapshot") or "1.png")
        if snap != LIVE_LABEL:
            ui["snapshot"] = snap
        ui.setdefault("snapshot_size", {"width": REF_W, "height": REF_H})
        ui["snapshot_size"] = {"width": REF_W, "height": REF_H}
        updated += 1

    for edge in doc.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        action = edge.get("action") or {}
        if action.get("op") != "use_talking_scroll":
            continue
        try:
            idx = int(action["plan_index"])
        except (KeyError, TypeError, ValueError):
            continue
        spot = by_index.get(idx)
        if spot is None:
            continue
        ui = action.setdefault("ui", {})
        click = spot.get("click") or {}
        if click.get("x") is not None and click.get("y") is not None:
            ui["click"] = {"x": int(click["x"]), "y": int(click["y"])}
        ui["scroll_times"] = int(spot.get("scroll_times") or 0)
        snap = str(spot.get("snapshot") or ui.get("snapshot") or "1.png")
        if snap != LIVE_LABEL:
            ui["snapshot"] = snap
        ui["snapshot_size"] = {"width": REF_W, "height": REF_H}

    return updated


def _aspect_crop_rect(width: int, height: int, aspect: tuple[int, int] = (4, 3)) -> tuple[int, int, int, int]:
    """Return (left, top, crop_w, crop_h) for a centered aspect crop."""
    if width <= 0 or height <= 0:
        return 0, 0, max(0, width), max(0, height)
    tw, th = aspect
    target = tw / th
    frame = width / height
    if abs(frame - target) <= 0.01 * target:
        return 0, 0, width, height
    if frame > target:
        crop_w = min(width, int(round(height * target)))
        return (width - crop_w) // 2, 0, crop_w, height
    crop_h = min(height, int(round(width / target)))
    return 0, (height - crop_h) // 2, width, crop_h


def capture_lc_client_rgb() -> Image.Image:
    """Grab LC.exe client pixels (4:3 content crop), RGB PIL image."""
    try:
        import mss
    except ImportError as exc:
        raise RuntimeError("mss is required for live capture (pip install mss)") from exc

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _exe_name(pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)

    def _class_name(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        if not user32.GetClassNameW(hwnd, buf, len(buf)):
            return ""
        return buf.value

    matches: list[int] = []

    def _cb(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _exe_name(pid.value) != "lc.exe":
            return True
        if _class_name(hwnd) == "$GIVEmeMINT":
            return True
        matches.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if not matches:
        raise RuntimeError("LC.exe window not found (is the game running?)")
    hwnd = matches[0]
    if user32.IsIconic(hwnd):
        raise RuntimeError("LC.exe is minimized")

    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("GetClientRect failed")
    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("ClientToScreen failed")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        raise RuntimeError("invalid client size")

    left, top, crop_w, crop_h = _aspect_crop_rect(width, height)
    region = {
        "left": int(origin.x + left),
        "top": int(origin.y + top),
        "width": int(crop_w),
        "height": int(crop_h),
    }
    with mss.mss() as sct:
        shot = sct.grab(region)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return img


def to_ref_xy(x: int, y: int, iw: int, ih: int) -> tuple[int, int]:
    """Map a pixel on the displayed capture into the stored 800×600 space."""
    if iw <= 0 or ih <= 0:
        return x, y
    return int(round(x * REF_W / iw)), int(round(y * REF_H / ih))


def from_ref_xy(x: int, y: int, iw: int, ih: int) -> tuple[float, float]:
    """Map a stored 800×600 click onto the current image pixels."""
    if iw <= 0 or ih <= 0:
        return float(x), float(y)
    return x * iw / REF_W, y * ih / REF_H


class PlanEditor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Talking Scroll Plan Editor")
        self.geometry("1420x740")
        self.minsize(1100, 600)

        self.spots: list[dict[str, Any]] = []
        self.current_index: int | None = None
        self.current_snapshot = SNAPSHOT_FILES[0]
        self.scroll_by_snapshot = dict(DEFAULT_SCROLL_TIMES)
        self.pil_image: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self._suppress = False
        self._snap_radio_labels: dict[str, tk.StringVar] = {}
        self.hubs_doc: dict[str, Any] | None = None
        self.save_path = ENGINE_HUBS if ENGINE_HUBS.is_file() else TOOL_PLANS
        self.source_kind = "hubs" if ENGINE_HUBS.is_file() else "plans"
        self.view_mode = tk.StringVar(value="offline")  # offline | live
        self.live_image: Image.Image | None = None
        self._panning = False

        self._build_ui()
        self._load_default()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="Reload project", command=self._load_default).pack(
            side="left", padx=2
        )
        ttk.Button(toolbar, text="Load JSON…", command=self._load_json_dialog).pack(
            side="left", padx=2
        )
        ttk.Button(toolbar, text="Save to project", command=self._save_project).pack(
            side="left", padx=2
        )
        ttk.Button(toolbar, text="Save As…", command=self._save_json_as).pack(
            side="left", padx=2
        )
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Capture LC.exe", command=self._capture_live).pack(
            side="left", padx=2
        )
        ttk.Radiobutton(
            toolbar,
            text="Offline PNGs",
            value="offline",
            variable=self.view_mode,
            command=self._on_view_mode,
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            toolbar,
            text="Live capture",
            value="live",
            variable=self.view_mode,
            command=self._on_view_mode,
        ).pack(side="left", padx=4)

        self.status = tk.StringVar(value=f"Project: {ENGINE_HUBS}")
        ttk.Label(toolbar, textvariable=self.status).pack(side="right", padx=6)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body)
        body.add(left, weight=3)

        snap_bar = ttk.Frame(left)
        snap_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(snap_bar, text="Snapshot page:").pack(side="left")
        self.snapshot_var = tk.StringVar(value=self.current_snapshot)
        for name in SNAPSHOT_FILES:
            label_var = tk.StringVar(value=f"{name} ({self.scroll_by_snapshot.get(name, 0)})")
            self._snap_radio_labels[name] = label_var
            ttk.Radiobutton(
                snap_bar,
                textvariable=label_var,
                value=name,
                variable=self.snapshot_var,
                command=self._on_snapshot_change,
            ).pack(side="left", padx=4)
        ttk.Separator(snap_bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(snap_bar, text="−", width=3, command=lambda: self._zoom_by(1 / ZOOM_STEP)).pack(
            side="left", padx=1
        )
        ttk.Button(snap_bar, text="+", width=3, command=lambda: self._zoom_by(ZOOM_STEP)).pack(
            side="left", padx=1
        )
        ttk.Button(snap_bar, text="Fit", width=4, command=self._zoom_fit).pack(side="left", padx=2)
        self.zoom_label = tk.StringVar(value="100%")
        ttk.Label(snap_bar, textvariable=self.zoom_label).pack(side="left", padx=4)

        canvas_frame = ttk.Frame(left)
        canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            canvas_frame, bg="#1a1a1a", highlightthickness=0, cursor="crosshair"
        )
        self.hbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e, ZOOM_STEP))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e, 1 / ZOOM_STEP))
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.focus_set())

        hint = ttk.Label(
            left,
            text=(
                "Left-click = set click (800×600). "
                "Wheel = zoom. Right-drag = pan. "
                "Scroll times = wheel notches. "
                "Markers: red = current, teal = same scroll bucket."
            ),
        )
        hint.pack(fill="x", pady=(4, 0))

        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(right, weight=1)

        ttk.Label(right, text="Spots (project hubs)", font=("", 10, "bold")).pack(anchor="w")
        list_wrap = ttk.Frame(right)
        list_wrap.pack(fill="both", expand=True, pady=(2, 8))
        self.listbox = tk.Listbox(list_wrap, exportselection=False, activestyle="dotbox")
        lb_scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lb_scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        lb_scroll.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        form = ttk.LabelFrame(right, text="Selected spot", padding=8)
        form.pack(fill="x")

        self.fields: dict[str, tk.Variable] = {}
        rows = [
            ("name", "Name"),
            ("scroll_times", "Scroll times (wheels)"),
            ("click_x", "Click X (800-space)"),
            ("click_y", "Click Y (800-space)"),
            ("region", "Region"),
            ("map", "Map label"),
            ("coord_x", "World X"),
            ("coord_y", "World Y"),
        ]
        readonly = {"name", "region", "map", "coord_x", "coord_y"}
        for i, (key, label) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.fields[key] = var
            entry = ttk.Entry(form, textvariable=var, width=28)
            entry.grid(row=i, column=1, sticky="ew", pady=2, padx=(6, 0))
            if key in readonly:
                entry.configure(state="readonly")
            else:
                var.trace_add("write", lambda *_a, k=key: self._on_field_edit(k))
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(form)
        btns.grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Clear click", command=self._clear_click).pack(side="left")
        ttk.Button(
            btns, text="Use page scroll default", command=self._apply_snapshot_scroll
        ).pack(side="left", padx=6)

        self.mouse_xy = tk.StringVar(value="mouse: —")
        ttk.Label(right, textvariable=self.mouse_xy).pack(anchor="w", pady=(8, 0))

        notes = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(notes, weight=1)
        notes_head = ttk.Frame(notes)
        notes_head.pack(fill="x")
        ttk.Label(notes_head, text="handwrite_data.txt", font=("", 10, "bold")).pack(
            side="left", anchor="w"
        )
        ttk.Button(notes_head, text="Reload", command=self._load_handwrite).pack(side="right")
        ttk.Label(
            notes,
            text="Reference notes only (world coords). Double-click does not rewrite hubs.",
        ).pack(anchor="w", pady=(2, 4))
        notes_wrap = ttk.Frame(notes)
        notes_wrap.pack(fill="both", expand=True)
        self.notes_text = tk.Text(
            notes_wrap, wrap="none", width=28, font=("Consolas", 10), undo=False
        )
        notes_y = ttk.Scrollbar(notes_wrap, orient="vertical", command=self.notes_text.yview)
        notes_x = ttk.Scrollbar(notes_wrap, orient="horizontal", command=self.notes_text.xview)
        self.notes_text.configure(yscrollcommand=notes_y.set, xscrollcommand=notes_x.set)
        self.notes_text.grid(row=0, column=0, sticky="nsew")
        notes_y.grid(row=0, column=1, sticky="ns")
        notes_x.grid(row=1, column=0, sticky="ew")
        notes_wrap.rowconfigure(0, weight=1)
        notes_wrap.columnconfigure(0, weight=1)
        self._load_handwrite()

    def _load_default(self) -> None:
        if ENGINE_HUBS.is_file():
            try:
                self._import_path(ENGINE_HUBS, quiet=True)
                return
            except Exception as exc:
                messagebox.showerror("Load failed", f"{ENGINE_HUBS}\n{exc}")
        if TOOL_PLANS.is_file():
            try:
                self._import_path(TOOL_PLANS, quiet=True)
                self.status.set(f"Fallback plans: {TOOL_PLANS}")
                return
            except Exception as exc:
                messagebox.showerror("Load failed", f"{TOOL_PLANS}\n{exc}")
        self.spots = []
        self.current_index = None
        self._refresh_list(keep_selection=False)
        self.status.set("No project hubs / plans found")

    def _load_handwrite(self) -> None:
        if not hasattr(self, "notes_text"):
            return
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        if HANDWRITE_FILE.exists():
            text = HANDWRITE_FILE.read_text(encoding="utf-8")
            self.notes_text.insert("1.0", text)
            self.notes_text.configure(state="disabled")
            self.scroll_by_snapshot = parse_scroll_times_from_handwrite(text)
            self._refresh_snapshot_labels()
        else:
            self.notes_text.insert("1.0", f"(missing)\n{HANDWRITE_FILE}")
            self.notes_text.configure(state="disabled")
            self.scroll_by_snapshot = dict(DEFAULT_SCROLL_TIMES)
            self._refresh_snapshot_labels()

    def _refresh_snapshot_labels(self) -> None:
        for name, label_var in self._snap_radio_labels.items():
            scrolls = self.scroll_by_snapshot.get(name, 0)
            label_var.set(f"{name} ({scrolls})")

    def _snapshot_default_scroll(self, name: str) -> int:
        return int(self.scroll_by_snapshot.get(name, DEFAULT_SCROLL_TIMES.get(name, 0)))

    def _on_view_mode(self) -> None:
        if self.view_mode.get() == "live":
            if self.live_image is None:
                self.status.set("Live mode: press Capture LC.exe first")
                return
            self.pil_image = self.live_image
            self.current_snapshot = LIVE_LABEL
            self._zoom_fit()
            return
        name = self.snapshot_var.get() or SNAPSHOT_FILES[0]
        self._load_snapshot(name)

    def _capture_live(self) -> None:
        try:
            img = capture_lc_client_rgb()
        except Exception as exc:
            messagebox.showerror("Capture failed", str(exc))
            return
        self.live_image = img
        self.view_mode.set("live")
        self.pil_image = img
        self.current_snapshot = LIVE_LABEL
        self._zoom_fit()
        self.status.set(f"Live capture {img.size[0]}×{img.size[1]} (clicks stored as {REF_W}×{REF_H})")

    def _on_snapshot_change(self) -> None:
        if self.view_mode.get() == "live":
            # Page radios only change the suggested wheel default while live.
            self._apply_scroll_for_snapshot(self.snapshot_var.get())
            self.status.set(
                f"Live view — page default wheels = "
                f"{self._snapshot_default_scroll(self.snapshot_var.get())}"
            )
            return
        name = self.snapshot_var.get()
        self._load_snapshot(name)
        self._apply_scroll_for_snapshot(name)
        self._draw_markers()
        self.status.set(
            f"Snapshot {name}  |  scroll times = {self._snapshot_default_scroll(name)}"
        )

    def _load_snapshot(self, name: str) -> None:
        path = ROOT / name
        if not path.exists():
            self.pil_image = None
            self.canvas.delete("all")
            self.status.set(f"Offline PNG missing: {path.name} (use Capture LC.exe)")
            return
        self.current_snapshot = name
        self.pil_image = Image.open(path).convert("RGB")
        self._zoom_fit()

    def _fit_scale(self) -> float:
        if self.pil_image is None:
            return 1.0
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        iw, ih = self.pil_image.size
        if iw <= 0 or ih <= 0:
            return 1.0
        return max(ZOOM_MIN, min(cw / iw, ch / ih))

    def _clamp_scale(self, scale: float) -> float:
        return max(ZOOM_MIN, min(ZOOM_MAX, float(scale)))

    def _update_zoom_label(self) -> None:
        if hasattr(self, "zoom_label"):
            self.zoom_label.set(f"{int(round(self.scale * 100))}%")

    def _zoom_fit(self) -> None:
        if self.pil_image is None:
            return
        self.scale = self._fit_scale()
        self._redraw_image(keep_scroll=False)

    def _zoom_by(self, factor: float) -> None:
        """Zoom about the canvas center (toolbar +/−)."""
        if self.pil_image is None:
            return
        class _E:
            x = max(self.canvas.winfo_width(), 1) // 2
            y = max(self.canvas.winfo_height(), 1) // 2

        self._zoom_at(_E(), factor)

    def _zoom_at(self, event: Any, factor: float) -> None:
        if self.pil_image is None or self.scale <= 0:
            return
        old = self.scale
        new = self._clamp_scale(old * factor)
        if abs(new - old) < 1e-9:
            return
        img_x = self.canvas.canvasx(event.x) / old
        img_y = self.canvas.canvasy(event.y) / old
        self.scale = new
        self._redraw_image(keep_scroll=False)
        # Keep the image point under the cursor after zoom.
        disp_x = img_x * self.scale
        disp_y = img_y * self.scale
        iw, ih = self.pil_image.size
        disp_w = max(1, int(round(iw * self.scale)))
        disp_h = max(1, int(round(ih * self.scale)))
        left = disp_x - event.x
        top = disp_y - event.y
        self.canvas.xview_moveto(max(0.0, min(1.0, left / max(disp_w, 1))))
        self.canvas.yview_moveto(max(0.0, min(1.0, top / max(disp_h, 1))))
        self._draw_markers()

    def _on_mousewheel(self, event: tk.Event) -> None:
        if getattr(event, "delta", 0) > 0:
            self._zoom_at(event, ZOOM_STEP)
        elif getattr(event, "delta", 0) < 0:
            self._zoom_at(event, 1 / ZOOM_STEP)

    def _on_pan_start(self, event: tk.Event) -> None:
        self._panning = True
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.configure(cursor="fleur")

    def _on_pan_drag(self, event: tk.Event) -> None:
        if not self._panning:
            return
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_pan_end(self, _event: tk.Event) -> None:
        self._panning = False
        self.canvas.configure(cursor="crosshair")

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        if self.pil_image is None:
            return
        # Keep current zoom; only rebuild the bitmap if the widget was empty.
        if self.tk_image is None:
            self.scale = self._fit_scale()
            self._redraw_image(keep_scroll=False)
        else:
            self._redraw_image(keep_scroll=True)

    def _redraw_image(self, keep_scroll: bool = True) -> None:
        if self.pil_image is None:
            return
        iw, ih = self.pil_image.size
        self.scale = self._clamp_scale(self.scale if self.scale > 0 else self._fit_scale())
        disp_w = max(1, int(round(iw * self.scale)))
        disp_h = max(1, int(round(ih * self.scale)))
        # Keep exact scale for hit-testing (avoid int rounding drift).
        self.scale = disp_w / iw if iw else self.scale

        xview = self.canvas.xview() if keep_scroll else (0.0, 1.0)
        yview = self.canvas.yview() if keep_scroll else (0.0, 1.0)

        resized = self.pil_image.resize((disp_w, disp_h), Image.Resampling.NEAREST)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image, tags=("img",))
        self.canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
        if keep_scroll:
            self.canvas.xview_moveto(xview[0])
            self.canvas.yview_moveto(yview[0])
        self._update_zoom_label()
        self._draw_markers()

    def _img_xy_from_event(self, event: tk.Event) -> tuple[int, int] | None:
        if self.pil_image is None or self.scale <= 0:
            return None
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        x = int(cx / self.scale)
        y = int(cy / self.scale)
        iw, ih = self.pil_image.size
        if not (0 <= x < iw and 0 <= y < ih):
            return None
        return x, y

    def _on_canvas_motion(self, event: tk.Event) -> None:
        if self._panning:
            return
        xy = self._img_xy_from_event(event)
        if xy is None or self.pil_image is None:
            self.mouse_xy.set("mouse: —")
            return
        x, y = xy
        rx, ry = to_ref_xy(x, y, *self.pil_image.size)
        self.mouse_xy.set(f"mouse: {x},{y}  →  store {rx},{ry}")

    def _on_canvas_click(self, event: tk.Event) -> None:
        if self._panning:
            return
        xy = self._img_xy_from_event(event)
        if xy is None or self.current_index is None or self.pil_image is None:
            return
        x, y = xy
        rx, ry = to_ref_xy(x, y, *self.pil_image.size)
        self._suppress = True
        self.fields["click_x"].set(str(rx))
        self.fields["click_y"].set(str(ry))
        self._suppress = False
        spot = self.spots[self.current_index]
        spot["click"] = {"x": rx, "y": ry}
        if self.view_mode.get() != "live":
            spot["snapshot"] = self.current_snapshot
            self._apply_scroll_for_snapshot(self.current_snapshot)
        self._draw_markers()
        self.status.set(f"Click set to ({rx}, {ry}) in {REF_W}×{REF_H} space")

    def _marker_bucket(self, spot: dict[str, Any]) -> int:
        return int(spot.get("scroll_times") or 0)

    def _draw_markers(self) -> None:
        self.canvas.delete("marker")
        if self.pil_image is None:
            return
        iw, ih = self.pil_image.size
        cur_wheels: Optional[int] = None
        if self.current_index is not None and 0 <= self.current_index < len(self.spots):
            cur_wheels = self._marker_bucket(self.spots[self.current_index])
        for i, spot in enumerate(self.spots):
            if self.view_mode.get() == "live":
                if cur_wheels is not None and self._marker_bucket(spot) != cur_wheels:
                    continue
            else:
                if spot.get("snapshot") != self.current_snapshot:
                    continue
            click = spot.get("click") or {}
            x, y = click.get("x"), click.get("y")
            if x is None or y is None:
                continue
            px, py = from_ref_xy(int(x), int(y), iw, ih)
            sx, sy = px * self.scale, py * self.scale
            current = i == self.current_index
            color = "#ff3344" if current else "#22c8b0"
            r = 7 if current else 5
            self.canvas.create_oval(
                sx - r, sy - r, sx + r, sy + r, outline=color, width=2, tags=("marker",)
            )
            self.canvas.create_line(
                sx - 10, sy, sx + 10, sy, fill=color, width=1, tags=("marker",)
            )
            self.canvas.create_line(
                sx, sy - 10, sx, sy + 10, fill=color, width=1, tags=("marker",)
            )
            label = spot.get("name") or f"#{i + 1}"
            self.canvas.create_text(
                sx + 10, sy - 10, text=label, anchor="sw", fill=color, tags=("marker",)
            )

    def _spot_label(self, i: int, spot: dict[str, Any]) -> str:
        name = (spot.get("name") or "").strip() or f"spot {i + 1}"
        click = spot.get("click") or {}
        cx, cy = click.get("x"), click.get("y")
        click_s = f"{cx},{cy}" if cx is not None and cy is not None else "no-click"
        region = (spot.get("region") or "").strip() or "?"
        idx = spot.get("index")
        idx_s = str(idx) if idx is not None else "?"
        return (
            f"{idx_s}. {name}  |  {spot.get('snapshot')}  "
            f"scroll={spot.get('scroll_times')}  click={click_s}  {region}"
        )

    def _refresh_list(self, keep_selection: bool = True) -> None:
        sel = self.current_index if keep_selection else None
        self.listbox.delete(0, "end")
        for i, spot in enumerate(self.spots):
            self.listbox.insert("end", self._spot_label(i, spot))
        if sel is not None and 0 <= sel < len(self.spots):
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(sel)
            self.listbox.see(sel)

    def _on_list_select(self, _event: object = None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        self.current_index = int(sel[0])
        spot = self.spots[self.current_index]
        if self.view_mode.get() != "live":
            snap = spot.get("snapshot") or self.current_snapshot
            if snap in SNAPSHOT_FILES and snap != self.current_snapshot:
                self.snapshot_var.set(snap)
                self._load_snapshot(snap)
        self._load_spot_into_form()
        self._draw_markers()

    def _clear_form(self) -> None:
        self._suppress = True
        for var in self.fields.values():
            var.set("")
        self._suppress = False

    def _load_spot_into_form(self) -> None:
        if self.current_index is None:
            self._clear_form()
            return
        spot = self.spots[self.current_index]
        click = spot.get("click") or {}
        coords = spot.get("coordinates") or {}
        self._suppress = True
        self.fields["name"].set(spot.get("name") or "")
        self.fields["scroll_times"].set(
            "" if spot.get("scroll_times") is None else str(spot["scroll_times"])
        )
        self.fields["click_x"].set("" if click.get("x") is None else str(click["x"]))
        self.fields["click_y"].set("" if click.get("y") is None else str(click["y"]))
        self.fields["region"].set(spot.get("region") or "")
        map_val = spot.get("map")
        self.fields["map"].set("" if map_val in (None, "") else str(map_val))
        self.fields["coord_x"].set("" if coords.get("x") is None else str(coords["x"]))
        self.fields["coord_y"].set("" if coords.get("y") is None else str(coords["y"]))
        self._suppress = False

    def _parse_int(self, text: str) -> int | None:
        text = text.strip()
        if text == "":
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def _on_field_edit(self, _key: str) -> None:
        if self._suppress or self.current_index is None:
            return
        spot = self.spots[self.current_index]
        st = self._parse_int(self.fields["scroll_times"].get())
        if st is not None:
            spot["scroll_times"] = st
        spot["click"] = {
            "x": self._parse_int(self.fields["click_x"].get()),
            "y": self._parse_int(self.fields["click_y"].get()),
        }
        if self.listbox.curselection():
            i = self.current_index
            self.listbox.delete(i)
            self.listbox.insert(i, self._spot_label(i, spot))
            self.listbox.selection_set(i)
        self._draw_markers()

    def _clear_click(self) -> None:
        if self.current_index is None:
            return
        self._suppress = True
        self.fields["click_x"].set("")
        self.fields["click_y"].set("")
        self._suppress = False
        self.spots[self.current_index]["click"] = {"x": None, "y": None}
        self._refresh_list()
        self._draw_markers()

    def _apply_scroll_for_snapshot(self, snapshot: str | None = None) -> None:
        if self.current_index is None:
            return
        name = snapshot or self.snapshot_var.get()
        val = self._snapshot_default_scroll(name)
        spot = self.spots[self.current_index]
        if self.view_mode.get() != "live":
            spot["snapshot"] = name
        spot["scroll_times"] = val
        self._suppress = True
        self.fields["scroll_times"].set(str(val))
        self._suppress = False
        self._refresh_list(keep_selection=True)

    def _apply_snapshot_scroll(self) -> None:
        self._apply_scroll_for_snapshot(self.snapshot_var.get())
        if self.current_index is not None:
            self.status.set(
                f"Scroll times set to {self._snapshot_default_scroll(self.snapshot_var.get())}"
            )

    def _import_path(self, path: Path, quiet: bool = False) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("hubs"), list):
            self.hubs_doc = data
            self.spots = hubs_to_spots(data)
            self.source_kind = "hubs"
            self.save_path = path if path.resolve() == ENGINE_HUBS.resolve() else ENGINE_HUBS
        elif isinstance(data.get("plans"), list):
            self.hubs_doc = None
            if ENGINE_HUBS.is_file():
                # Keep hubs doc for save target; overlay click/wheels from plans.
                self.hubs_doc = json.loads(ENGINE_HUBS.read_text(encoding="utf-8"))
            self.spots = plans_to_spots(data)
            self.source_kind = "plans"
            self.save_path = ENGINE_HUBS if ENGINE_HUBS.is_file() else path
            snaps = data.get("snapshots") or []
            for entry in snaps:
                if isinstance(entry, dict) and entry.get("file") in SNAPSHOT_FILES:
                    self.scroll_by_snapshot[str(entry["file"])] = int(
                        entry.get("scroll_times") or 0
                    )
                    self._refresh_snapshot_labels()
        else:
            raise ValueError("JSON needs 'hubs' (project) or 'plans' (tool) list")

        self.current_index = 0 if self.spots else None
        self._refresh_list(keep_selection=False)
        if self.current_index is not None:
            self.listbox.selection_set(0)
            spot = self.spots[0]
            snap = spot.get("snapshot") or "1.png"
            if snap in SNAPSHOT_FILES:
                self.snapshot_var.set(snap)
            if self.view_mode.get() == "live" and self.live_image is not None:
                self.pil_image = self.live_image
                self._zoom_fit()
            else:
                self.view_mode.set("offline")
                self._load_snapshot(self.snapshot_var.get())
            self._load_spot_into_form()
        self._draw_markers()
        if not quiet:
            self.status.set(f"Loaded {len(self.spots)} spots from {path}")
        else:
            self.status.set(f"Loaded {len(self.spots)} · {path}")

    def _save_project(self) -> None:
        if not ENGINE_HUBS.is_file() and self.hubs_doc is None:
            messagebox.showerror(
                "No project file",
                f"Missing hubs JSON:\n{ENGINE_HUBS}\nUse Save As for a plans.json export.",
            )
            return
        if self.hubs_doc is None:
            if ENGINE_HUBS.is_file():
                self.hubs_doc = json.loads(ENGINE_HUBS.read_text(encoding="utf-8"))
            else:
                messagebox.showerror("No hubs document loaded", "Reload project first.")
                return
        n = apply_spots_to_hubs_doc(self.hubs_doc, self.spots)
        ENGINE_HUBS.write_text(
            json.dumps(self.hubs_doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Keep tool-local plans mirror in sync (same click/wheels).
        TOOL_PLANS.write_text(
            json.dumps(
                spots_to_plans_export(self.spots, self.scroll_by_snapshot),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.save_path = ENGINE_HUBS
        self.source_kind = "hubs"
        self.status.set(f"Saved {n} hubs → {ENGINE_HUBS.name} (+ tool plans mirror)")
        messagebox.showinfo(
            "Saved",
            f"Updated click/scroll_times on {n} hubs.\n\n"
            f"{ENGINE_HUBS}\n\n"
            f"Also wrote plans mirror:\n{TOOL_PLANS}\n\n"
            "Restart the bot so scroll_spot_plans() reloads.",
        )

    def _save_json_as(self) -> None:
        path = filedialog.asksaveasfilename(
            initialdir=str(ENGINE_HUBS.parent if ENGINE_HUBS.parent.is_dir() else ROOT),
            initialfile=ENGINE_HUBS.name if self.source_kind == "hubs" else TOOL_PLANS.name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        out = Path(path)
        if out.name == ENGINE_HUBS.name or (
            self.hubs_doc is not None and out.suffix.lower() == ".json" and "hubs" in out.name
        ):
            if self.hubs_doc is None:
                messagebox.showerror("Save As", "No hubs document in memory.")
                return
            apply_spots_to_hubs_doc(self.hubs_doc, self.spots)
            out.write_text(
                json.dumps(self.hubs_doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            out.write_text(
                json.dumps(
                    spots_to_plans_export(self.spots, self.scroll_by_snapshot),
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        self.status.set(f"Saved → {out}")

    def _load_json_dialog(self) -> None:
        path = filedialog.askopenfilename(
            initialdir=str(ENGINE_HUBS.parent if ENGINE_HUBS.is_file() else ROOT),
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            self._import_path(Path(path))
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))


def main() -> None:
    if not ENGINE_HUBS.is_file():
        print(f"warning: project hubs missing: {ENGINE_HUBS}", file=sys.stderr)
    app = PlanEditor()
    app.mainloop()


if __name__ == "__main__":
    main()
