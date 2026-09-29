"""GUI hotbar detection inspector — screen capture only, no bot control."""
from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any

from debug_tools import OUTPUT_DIR
from debug_tools.bootstrap import bootstrap

bootstrap()

from manmabot_v1.hotbar.icon_matcher import IconMatcher, to_bgr
from manmabot_v1.hotbar.inspect import (
    HotbarInspectError,
    hotbar_asset_root,
    load_role_map,
    resolve_role,
)
from manmabot_v1.hotbar.slot_layout import (
    SLOT_KEYS,
    USERDATA_LAYOUT_PATH,
    default_slot_layout,
    load_slot_layout,
    save_slot_layout,
)
from manmabot_v1.paths import manmabot_root
from manmabot_v1.perception_capture import (
    capture_backend_label,
    grab_perception_frame,
    open_perception_capture,
)
from manmabot_v1.spell_defaults import SKILL_KEYS
from manmabot_v1.ui.design_system import BG, TEXT_MUTED, apply_classic_style

HANDLE = 7
LAYOUT_PATH = USERDATA_LAYOUT_PATH


def _open_capture():
    """Same ScreenCapture instance factory as live bot perception."""
    root = manmabot_root()
    if str(root) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(root))
    return open_perception_capture()


def _annotate(
    frame,
    hits: list[Any],
    *,
    slots: dict[str, dict[str, float]] | None = None,
    crop_only: bool = True,
):
    import cv2

    screen = to_bgr(frame)
    H, W = screen.shape[:2]
    if slots is None:
        slots = default_slot_layout(W, H)

    if crop_only:
        xs = [b["x0"] for b in slots.values()] + [b["x1"] for b in slots.values()]
        ys = [b["y0"] for b in slots.values()] + [b["y1"] for b in slots.values()]
        pad = 0.01
        x0 = max(0, int((min(xs) - pad) * W))
        x1 = min(W, int((max(xs) + pad) * W))
        y0 = max(0, int((min(ys) - pad) * H))
        y1 = min(H, int((max(ys) + pad) * H))
        canvas = screen[y0:y1, x0:x1].copy()
        ox, oy = x0, y0
    else:
        canvas = screen.copy()
        ox = oy = 0

    for key, box in slots.items():
        hx0 = int(box["x0"] * W) - ox
        hy0 = int(box["y0"] * H) - oy
        hx1 = int(box["x1"] * W) - ox
        hy1 = int(box["y1"] * H) - oy
        cv2.rectangle(canvas, (hx0, hy0), (hx1, hy1), (90, 90, 90), 1)
        cv2.putText(
            canvas,
            key,
            (hx0 + 3, hy0 + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )

    for hit in hits:
        hx = int(hit.x - ox)
        hy = int(hit.y - oy)
        color = (0, 220, 0) if getattr(hit, "role", "") else (0, 165, 255)
        cv2.rectangle(canvas, (hx, hy), (hx + hit.w, hy + hit.h), color, 2)
        tag = hit.fkey or "?"
        score = f"{float(hit.score):.2f}"
        cv2.putText(
            canvas,
            f"{tag} {score}",
            (hx, max(12, hy - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas


class HotbarInspectorApp(tk.Tk):
    """Inspect IconMatcher hotbar hits on the live game capture."""

    def __init__(self) -> None:
        super().__init__()
        apply_classic_style(self)
        self.title("Hotbar detection inspector")
        self.geometry("1180x760")
        self.minsize(920, 600)
        self.configure(background=BG)
        self.attributes("-topmost", True)

        self._matcher: IconMatcher | None = None
        self._roles: dict[str, Any] | None = None
        self._capture = None
        self._busy = False
        self._closing = False
        self._photo = None
        self._last_frame = None
        self._last_hits: list[Any] = []
        self._last_rows: list[dict[str, Any]] = []

        self._slots = load_slot_layout() or {}
        self._calibrating = False
        self._calib_frame = None  # BGR full frame
        self._calib_scale = 1.0
        self._calib_zoom = 1.0
        self._calib_pan = (0.0, 0.0)  # canvas px after centering
        self._calib_offset = (0, 0)  # canvas pad before image
        self._calib_img_size = (1, 1)  # displayed image size
        self._selected_key: str | None = None
        self._drag_mode: str | None = None  # move | n | s | e | w | ne | nw | se | sw | pan
        self._drag_start = (0, 0)
        self._drag_box0: dict[str, float] | None = None
        self._drag_pan0 = (0.0, 0.0)
        self._slot_items: dict[str, int] = {}
        self._label_items: dict[str, int] = {}
        self._handle_items: list[int] = []
        self._zoom_label_var = tk.StringVar(self, value="100%")
        self.threshold_var = tk.DoubleVar(self, value=0.65)
        self.live_var = tk.BooleanVar(self, value=False)
        self.box_var = tk.IntVar(self, value=1)
        self.use_layout_var = tk.BooleanVar(self, value=bool(self._slots))
        self.status_var = tk.StringVar(self, value="Loading icon templates…")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._load_assets_async)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Threshold", style="Chrome.TLabel").pack(side="left")
        ttk.Scale(
            header,
            from_=0.50,
            to=0.95,
            variable=self.threshold_var,
            orient="horizontal",
            length=140,
        ).pack(side="left", padx=6)
        self.threshold_label = ttk.Label(
            header, text="0.65", width=4, style="Chrome.TLabel"
        )
        self.threshold_label.pack(side="left")
        self.threshold_var.trace_add(
            "write",
            lambda *_: self.threshold_label.configure(
                text=f"{float(self.threshold_var.get()):.2f}"
            ),
        )

        ttk.Label(header, text="Visible box", style="Chrome.TLabel").pack(
            side="left", padx=(12, 4)
        )
        box = ttk.Combobox(header, state="readonly", width=4, values=("1", "2", "3"))
        box.set("1")
        box.pack(side="left")
        box.bind(
            "<<ComboboxSelected>>",
            lambda _e: self.box_var.set(int(box.get() or 1)),
        )

        ttk.Checkbutton(
            header, text="Live", variable=self.live_var, command=self._toggle_live
        ).pack(side="left", padx=8)
        ttk.Checkbutton(
            header,
            text="Use calibrated slots",
            variable=self.use_layout_var,
        ).pack(side="left", padx=4)

        self.scan_btn = ttk.Button(
            header, text="Scan once", command=self.scan_once, state="disabled"
        )
        self.scan_btn.pack(side="right", padx=2)
        self.save_btn = ttk.Button(
            header, text="Save snapshot", command=self.save_snapshot, state="disabled"
        )
        self.save_btn.pack(side="right", padx=2)
        self.calib_btn = ttk.Button(
            header, text="Calibrate F5–F12", command=self.start_calibrate
        )
        self.calib_btn.pack(side="right", padx=2)

        ttk.Label(
            header,
            text="Capture only — no bot control",
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="right", padx=8)

        self.calib_bar = ttk.Frame(self, padding=4, style="Chrome.TFrame")
        ttk.Label(
            self.calib_bar,
            text="Drag · arrows nudge · wheel/+/- zoom · middle-drag pan",
            style="Chrome.TLabel",
        ).pack(side="left", padx=4)
        ttk.Button(self.calib_bar, text="Zoom −", command=lambda: self._zoom_by(1 / 1.25)).pack(
            side="left", padx=2
        )
        ttk.Label(
            self.calib_bar, textvariable=self._zoom_label_var, width=5, style="Chrome.TLabel"
        ).pack(side="left")
        ttk.Button(self.calib_bar, text="Zoom +", command=lambda: self._zoom_by(1.25)).pack(
            side="left", padx=2
        )
        ttk.Button(self.calib_bar, text="Reset zoom", command=self._zoom_reset).pack(
            side="left", padx=2
        )
        ttk.Button(
            self.calib_bar, text="Reset grid", command=self._calib_reset
        ).pack(side="right", padx=2)
        ttk.Button(
            self.calib_bar, text="Save layout", command=self._calib_save
        ).pack(side="right", padx=2)
        ttk.Button(
            self.calib_bar, text="Recapture", command=self._calib_recapture
        ).pack(side="right", padx=2)
        ttk.Button(
            self.calib_bar, text="Done", command=self.stop_calibrate
        ).pack(side="right", padx=2)

        self.body = ttk.Panedwindow(self, orient="horizontal")
        self.body.pack(fill="both", expand=True, padx=4, pady=4)
        left = ttk.Frame(self.body, padding=4)
        right = ttk.Frame(self.body, padding=4)
        self.body.add(left, weight=3)
        self.body.add(right, weight=2)

        preview_box = ttk.LabelFrame(left, text="Preview / slot layout", padding=(6, 4))
        preview_box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            preview_box, background="#111111", highlightthickness=0, takefocus=True
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_mousewheel)
        # Linux
        self.canvas.bind("<Button-4>", lambda e: self._on_mousewheel_linux(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._on_mousewheel_linux(e, -1))
        self.canvas.bind("<Configure>", lambda _e: self._redraw_canvas())
        self.canvas.bind("<Left>", lambda e: self._nudge_selected(-1, 0, e))
        self.canvas.bind("<Right>", lambda e: self._nudge_selected(1, 0, e))
        self.canvas.bind("<Up>", lambda e: self._nudge_selected(0, -1, e))
        self.canvas.bind("<Down>", lambda e: self._nudge_selected(0, 1, e))
        self.canvas.bind("<plus>", lambda _e: self._zoom_by(1.25))
        self.canvas.bind("<minus>", lambda _e: self._zoom_by(1 / 1.25))
        self.canvas.bind("<KP_Add>", lambda _e: self._zoom_by(1.25))
        self.canvas.bind("<KP_Subtract>", lambda _e: self._zoom_by(1 / 1.25))
        self.canvas.bind("<Key-plus>", lambda _e: self._zoom_by(1.25))
        self.canvas.bind("<Key-minus>", lambda _e: self._zoom_by(1 / 1.25))
        self.canvas.bind("<Tab>", self._cycle_selection)
        # Also bind arrows on the window so they work without extra click focus issues
        for seq, dx, dy in (
            ("<Left>", -1, 0),
            ("<Right>", 1, 0),
            ("<Up>", 0, -1),
            ("<Down>", 0, 1),
        ):
            self.bind(
                seq,
                lambda e, x=dx, y=dy: (
                    self._nudge_selected(x, y, e) if self._calibrating else None
                ),
            )
        self.bind(
            "<plus>",
            lambda _e: self._zoom_by(1.25) if self._calibrating else None,
        )
        self.bind(
            "<minus>",
            lambda _e: self._zoom_by(1 / 1.25) if self._calibrating else None,
        )
        self.bind(
            "<KP_Add>",
            lambda _e: self._zoom_by(1.25) if self._calibrating else None,
        )
        self.bind(
            "<KP_Subtract>",
            lambda _e: self._zoom_by(1 / 1.25) if self._calibrating else None,
        )
        table_box = ttk.LabelFrame(right, text="Detected slots", padding=(6, 4))
        table_box.pack(fill="both", expand=True)
        columns = ("key", "score", "role", "kr", "template")
        self.tree = ttk.Treeview(
            table_box, columns=columns, show="headings", style="Grid.Treeview"
        )
        widths = {"key": 50, "score": 60, "role": 110, "kr": 120, "template": 180}
        headings = {
            "key": "Key",
            "score": "Score",
            "role": "Role",
            "kr": "Name",
            "template": "Template",
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(
                col, width=widths[col], stretch=col in {"template", "kr", "role"}
            )
        scroll = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        footer = ttk.Frame(self, padding=5, style="Chrome.TFrame")
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )

    def _load_assets_async(self) -> None:
        def worker() -> None:
            err = ""
            try:
                icon_root = hotbar_asset_root() / "icons_unique"
                matcher = IconMatcher(icon_root=str(icon_root))
                roles = load_role_map()
            except Exception as exc:
                matcher = None
                roles = None
                err = str(exc)

            def done() -> None:
                if self._closing:
                    return
                if matcher is None:
                    self.status_var.set(f"Failed to load icons: {err}")
                    messagebox.showerror("Hotbar inspector", err, parent=self)
                    return
                self._matcher = matcher
                self._roles = roles
                self.scan_btn.configure(state="normal")
                layout_note = (
                    f" · calibrated slots ({USERDATA_LAYOUT_PATH.name})"
                    if self._slots
                    else " · default uniform grid"
                )
                try:
                    backend = capture_backend_label(self._ensure_capture())
                except Exception:
                    backend = "bot capture (pending)"
                self.status_var.set(
                    f"Ready · {len(matcher.hotbar_templates)} templates"
                    f"{layout_note} · {backend}"
                )

            self.after(0, done)

        threading.Thread(target=worker, name="hotbar-inspector-load", daemon=True).start()

    def _ensure_capture(self):
        if self._capture is not None:
            return self._capture
        self._capture = _open_capture()
        self.status_var.set(capture_backend_label(self._capture))
        return self._capture

    def _grab_frame(self):
        capture = self._ensure_capture()
        frame = grab_perception_frame(capture, retries=40, wait_s=0.05)
        if frame is None:
            raise HotbarInspectError(
                "No game frame from bot capture. Make sure LC.exe is visible "
                "(not minimized)."
            )
        return to_bgr(frame)

    def _active_slots(self, frame_w: int, frame_h: int) -> dict[str, dict[str, float]]:
        if self.use_layout_var.get() and self._slots:
            return self._slots
        return default_slot_layout(frame_w, frame_h)

    # ------------------------------------------------------------------ calibrate

    def start_calibrate(self) -> None:
        self.live_var.set(False)
        try:
            frame = self._grab_frame()
        except Exception as exc:
            messagebox.showwarning("Hotbar inspector", str(exc), parent=self)
            return
        self._calibrating = True
        self._calib_frame = frame
        self._calib_zoom = 1.0
        self._calib_pan = (0.0, 0.0)
        self._zoom_label_var.set("100%")
        h, w = frame.shape[:2]
        if not self._slots:
            self._slots = default_slot_layout(w, h)
        self.use_layout_var.set(True)
        self.calib_bar.pack(fill="x", before=self.body)
        self.scan_btn.configure(state="disabled")
        self.status_var.set(
            "Calibrate · click a box · arrows nudge (Shift=5px) · wheel zoom"
        )
        self._redraw_canvas()
        self.canvas.focus_set()

    def stop_calibrate(self) -> None:
        self._calibrating = False
        self.calib_bar.pack_forget()
        self.scan_btn.configure(
            state="normal" if self._matcher is not None else "disabled"
        )
        self.status_var.set("Calibration closed · layout kept in memory (Save layout to persist)")
        if self._last_frame is not None:
            self._show_scan_preview()
        else:
            self.canvas.delete("all")

    def _calib_recapture(self) -> None:
        try:
            self._calib_frame = self._grab_frame()
            self._redraw_canvas()
            self.status_var.set("Recaptured frame for calibration")
        except Exception as exc:
            messagebox.showwarning("Hotbar inspector", str(exc), parent=self)

    def _calib_reset(self) -> None:
        if self._calib_frame is None:
            return
        h, w = self._calib_frame.shape[:2]
        self._slots = default_slot_layout(w, h)
        self._selected_key = None
        self._redraw_canvas()
        self.status_var.set("Reset to uniform grid inside default hotbar region")

    def _calib_save(self) -> None:
        if not self._slots or self._calib_frame is None:
            messagebox.showinfo(
                "Hotbar inspector", "Nothing to save yet.", parent=self
            )
            return
        h, w = self._calib_frame.shape[:2]
        path = save_slot_layout(self._slots, frame_w=w, frame_h=h)
        self.use_layout_var.set(True)
        if self._matcher is not None:
            self._matcher.slot_layout = dict(self._slots)
        self.status_var.set(
            f"Saved slot layout → {path.name} (also mirrored under debug_tools/output)"
        )

    def _zoom_reset(self) -> None:
        if not self._calibrating:
            return
        self._calib_zoom = 1.0
        self._calib_pan = (0.0, 0.0)
        self._zoom_label_var.set("100%")
        self._redraw_canvas()

    def _zoom_by(self, factor: float, *, anchor: tuple[float, float] | None = None) -> None:
        if not self._calibrating or self._calib_frame is None:
            return
        old_zoom = self._calib_zoom
        new_zoom = max(0.25, min(12.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        ax = cw / 2 if anchor is None else anchor[0]
        ay = ch / 2 if anchor is None else anchor[1]
        # Keep the image point under the anchor fixed.
        h, w = self._calib_frame.shape[:2]
        fit = min(cw / w, ch / h)
        old_s = fit * old_zoom
        new_s = fit * new_zoom
        ox0 = (cw - w * old_s) / 2 + self._calib_pan[0]
        oy0 = (ch - h * old_s) / 2 + self._calib_pan[1]
        img_x = (ax - ox0) / max(old_s, 1e-6)
        img_y = (ay - oy0) / max(old_s, 1e-6)
        ox1 = ax - img_x * new_s
        oy1 = ay - img_y * new_s
        self._calib_pan = (
            ox1 - (cw - w * new_s) / 2,
            oy1 - (ch - h * new_s) / 2,
        )
        self._calib_zoom = new_zoom
        self._zoom_label_var.set(f"{int(round(new_zoom * 100))}%")
        self._redraw_canvas()

    def _on_mousewheel(self, event: tk.Event) -> None:
        if not self._calibrating:
            return
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 1 / 1.25
        self._zoom_by(factor, anchor=(event.x, event.y))
        return "break"

    def _on_mousewheel_linux(self, event: tk.Event, direction: int) -> None:
        if not self._calibrating:
            return
        factor = 1.25 if direction > 0 else 1 / 1.25
        self._zoom_by(factor, anchor=(event.x, event.y))
        return "break"

    def _nudge_selected(self, dx_px: int, dy_px: int, event: tk.Event | None = None) -> str | None:
        if not self._calibrating or self._calib_frame is None:
            return None
        if not self._selected_key or self._selected_key not in self._slots:
            return "break" if self._calibrating else None
        step = 5 if (event is not None and (event.state & 0x0001)) else 1  # Shift
        h, w = self._calib_frame.shape[:2]
        dnx = (dx_px * step) / max(w, 1)
        dny = (dy_px * step) / max(h, 1)
        box = dict(self._slots[self._selected_key])
        width = box["x1"] - box["x0"]
        height = box["y1"] - box["y0"]
        box["x0"] = max(0.0, min(1.0 - width, box["x0"] + dnx))
        box["y0"] = max(0.0, min(1.0 - height, box["y0"] + dny))
        box["x1"] = box["x0"] + width
        box["y1"] = box["y0"] + height
        self._slots[self._selected_key] = box
        self._redraw_canvas()
        return "break"

    def _cycle_selection(self, _event: tk.Event) -> str:
        if not self._calibrating or not self._slots:
            return "break"
        keys = list(SLOT_KEYS)
        if self._selected_key in keys:
            idx = (keys.index(self._selected_key) + 1) % len(keys)
        else:
            idx = 0
        self._selected_key = keys[idx]
        self._redraw_canvas()
        self.canvas.focus_set()
        return "break"

    def _on_pan_press(self, event: tk.Event) -> None:
        if not self._calibrating:
            return
        self._drag_mode = "pan"
        self._drag_start = (event.x, event.y)
        self._drag_pan0 = self._calib_pan
        self.canvas.focus_set()

    def _on_pan_drag(self, event: tk.Event) -> None:
        if not self._calibrating or self._drag_mode != "pan":
            return
        self._calib_pan = (
            self._drag_pan0[0] + (event.x - self._drag_start[0]),
            self._drag_pan0[1] + (event.y - self._drag_start[1]),
        )
        self._redraw_canvas()

    def _on_pan_release(self, _event: tk.Event) -> None:
        if self._drag_mode == "pan":
            self._drag_mode = None

    def _redraw_canvas(self) -> None:
        if self._calibrating and self._calib_frame is not None:
            self._draw_calibrate()
        elif self._last_frame is not None and not self._calibrating:
            self._show_scan_preview()

    def _fit_image_to_canvas(self, bgr, *, apply_zoom: bool = False):
        import cv2
        from PIL import Image, ImageTk

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        fit = min(cw / image.width, ch / image.height)
        scale = fit * self._calib_zoom if apply_zoom else min(fit, 1.0)
        dw = max(1, int(round(image.width * scale)))
        dh = max(1, int(round(image.height * scale)))
        image = image.resize((dw, dh), getattr(Image, "Resampling", Image).BILINEAR)
        photo = ImageTk.PhotoImage(image, master=self)
        ox = (cw - dw) / 2
        oy = (ch - dh) / 2
        if apply_zoom:
            ox += self._calib_pan[0]
            oy += self._calib_pan[1]
        return photo, scale, ox, oy, dw, dh

    def _draw_calibrate(self) -> None:
        frame = self._calib_frame
        if frame is None:
            return
        self.canvas.delete("all")
        photo, scale, ox, oy, dw, dh = self._fit_image_to_canvas(
            frame, apply_zoom=True
        )
        self._photo = photo
        self._calib_scale = scale
        self._calib_offset = (ox, oy)
        self._calib_img_size = (dw, dh)
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)
        self._slot_items.clear()
        self._label_items.clear()
        self._handle_items.clear()
        h, w = frame.shape[:2]
        for key in SLOT_KEYS:
            box = self._slots[key]
            x0, y0, x1, y1 = self._norm_to_canvas(box, w, h)
            color = "#22c55e" if key == self._selected_key else "#38bdf8"
            width = 2 if key == self._selected_key else 1
            rid = self.canvas.create_rectangle(
                x0, y0, x1, y1, outline=color, width=width, tags=("slot", key)
            )
            lid = self.canvas.create_text(
                x0 + 4,
                y0 + 4,
                anchor="nw",
                text=key,
                fill=color,
                font=("Segoe UI", 9, "bold"),
                tags=("slot", key),
            )
            self._slot_items[key] = rid
            self._label_items[key] = lid
            if key == self._selected_key:
                self._draw_handles(x0, y0, x1, y1)

    def _draw_handles(self, x0: float, y0: float, x1: float, y1: float) -> None:
        pts = {
            "nw": (x0, y0),
            "n": ((x0 + x1) / 2, y0),
            "ne": (x1, y0),
            "e": (x1, (y0 + y1) / 2),
            "se": (x1, y1),
            "s": ((x0 + x1) / 2, y1),
            "sw": (x0, y1),
            "w": (x0, (y0 + y1) / 2),
        }
        for name, (x, y) in pts.items():
            item = self.canvas.create_rectangle(
                x - HANDLE / 2,
                y - HANDLE / 2,
                x + HANDLE / 2,
                y + HANDLE / 2,
                fill="#f8fafc",
                outline="#0ea5e9",
                tags=("handle", name),
            )
            self._handle_items.append(item)

    def _norm_to_canvas(
        self, box: dict[str, float], frame_w: int, frame_h: int
    ) -> tuple[float, float, float, float]:
        ox, oy = self._calib_offset
        s = self._calib_scale
        return (
            ox + box["x0"] * frame_w * s,
            oy + box["y0"] * frame_h * s,
            ox + box["x1"] * frame_w * s,
            oy + box["y1"] * frame_h * s,
        )

    def _canvas_to_norm(
        self, x: float, y: float, frame_w: int, frame_h: int
    ) -> tuple[float, float]:
        ox, oy = self._calib_offset
        s = max(self._calib_scale, 1e-6)
        nx = (x - ox) / (frame_w * s)
        ny = (y - oy) / (frame_h * s)
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

    def _hit_test(self, x: float, y: float) -> tuple[str | None, str | None]:
        """Return (slot_key, handle_name|move|None)."""
        if self._calib_frame is None:
            return None, None
        h, w = self._calib_frame.shape[:2]
        # handles first if selected
        if self._selected_key and self._selected_key in self._slots:
            x0, y0, x1, y1 = self._norm_to_canvas(self._slots[self._selected_key], w, h)
            pts = {
                "nw": (x0, y0),
                "n": ((x0 + x1) / 2, y0),
                "ne": (x1, y0),
                "e": (x1, (y0 + y1) / 2),
                "se": (x1, y1),
                "s": ((x0 + x1) / 2, y1),
                "sw": (x0, y1),
                "w": (x0, (y0 + y1) / 2),
            }
            for name, (px, py) in pts.items():
                if abs(x - px) <= HANDLE and abs(y - py) <= HANDLE:
                    return self._selected_key, name
        # topmost slot containing point (later keys on top of earlier — reverse)
        for key in reversed(SLOT_KEYS):
            box = self._slots.get(key)
            if not box:
                continue
            x0, y0, x1, y1 = self._norm_to_canvas(box, w, h)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key, "move"
        return None, None

    def _on_canvas_press(self, event: tk.Event) -> None:
        if not self._calibrating:
            return
        self.canvas.focus_set()
        key, mode = self._hit_test(event.x, event.y)
        self._selected_key = key
        self._drag_mode = mode if key else None
        self._drag_start = (event.x, event.y)
        if key and key in self._slots:
            self._drag_box0 = dict(self._slots[key])
        else:
            self._drag_box0 = None
            # empty area + left drag pans when zoomed
            if self._calib_zoom > 1.01:
                self._drag_mode = "pan"
                self._drag_pan0 = self._calib_pan
        self._redraw_canvas()

    def _on_canvas_drag(self, event: tk.Event) -> None:
        if not self._calibrating:
            return
        if self._drag_mode == "pan":
            self._calib_pan = (
                self._drag_pan0[0] + (event.x - self._drag_start[0]),
                self._drag_pan0[1] + (event.y - self._drag_start[1]),
            )
            self._redraw_canvas()
            return
        if (
            not self._selected_key
            or not self._drag_mode
            or self._drag_box0 is None
            or self._calib_frame is None
        ):
            return
        h, w = self._calib_frame.shape[:2]
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        # convert pixel delta on canvas to normalized
        s = max(self._calib_scale, 1e-6)
        dnx = dx / (w * s)
        dny = dy / (h * s)
        box = dict(self._drag_box0)
        mode = self._drag_mode
        if mode == "move":
            width = box["x1"] - box["x0"]
            height = box["y1"] - box["y0"]
            box["x0"] = max(0.0, min(1.0 - width, box["x0"] + dnx))
            box["y0"] = max(0.0, min(1.0 - height, box["y0"] + dny))
            box["x1"] = box["x0"] + width
            box["y1"] = box["y0"] + height
        else:
            if "w" in mode:
                box["x0"] = min(box["x1"] - 0.005, max(0.0, box["x0"] + dnx))
            if "e" in mode:
                box["x1"] = max(box["x0"] + 0.005, min(1.0, box["x1"] + dnx))
            if "n" in mode:
                box["y0"] = min(box["y1"] - 0.005, max(0.0, box["y0"] + dny))
            if "s" in mode:
                box["y1"] = max(box["y0"] + 0.005, min(1.0, box["y1"] + dny))
        self._slots[self._selected_key] = box
        self._redraw_canvas()

    def _on_canvas_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self._drag_box0 = None
    # ------------------------------------------------------------------ scan

    def _toggle_live(self) -> None:
        if self._calibrating:
            self.live_var.set(False)
            return
        if self.live_var.get():
            self.scan_once()
            self.after(350, self._live_tick)

    def _live_tick(self) -> None:
        if self._closing or not self.live_var.get() or self._calibrating:
            return
        if not self._busy:
            self.scan_once(silent=True)
        self.after(400, self._live_tick)

    def scan_once(self, *, silent: bool = False) -> None:
        if self._busy or self._matcher is None or self._calibrating:
            return
        self._busy = True
        if not silent:
            self.status_var.set("Capturing…")
        threshold = float(self.threshold_var.get())
        box = int(self.box_var.get())
        use_layout = bool(self.use_layout_var.get())
        slots_snapshot = dict(self._slots) if use_layout and self._slots else None

        def worker() -> None:
            err = ""
            frame = None
            rows: list[dict[str, Any]] = []
            hits: list[Any] = []
            try:
                frame = self._grab_frame()
                H, W = frame.shape[:2]
                matcher = self._matcher
                assert matcher is not None
                previous = matcher.slot_layout
                try:
                    matcher.slot_layout = slots_snapshot
                    bar = matcher.hotbar_map(frame, threshold=threshold)
                finally:
                    matcher.slot_layout = previous
                roles = self._roles or {}
                for key in SKILL_KEYS:
                    fkey = key.upper()
                    hit = bar.get(fkey)
                    if hit is None:
                        rows.append(
                            {
                                "key": fkey,
                                "score": "",
                                "role": "",
                                "kr": "",
                                "zh": "",
                                "template": "",
                                "bound_box": box,
                            }
                        )
                        continue
                    role = resolve_role(hit.name, hit.kr_name, hit.zh_name, roles)
                    hit.role = role  # type: ignore[attr-defined]
                    hits.append(hit)
                    rows.append(
                        {
                            "key": fkey,
                            "score": round(float(hit.score), 4),
                            "role": role,
                            "kr": hit.kr_name,
                            "zh": hit.zh_name,
                            "template": hit.name,
                            "bound_box": box,
                            "x": hit.x,
                            "y": hit.y,
                            "w": hit.w,
                            "h": hit.h,
                        }
                    )
            except Exception as exc:
                err = str(exc)

            def done() -> None:
                self._busy = False
                if self._closing:
                    return
                if err:
                    if not silent:
                        self.status_var.set(err)
                        messagebox.showwarning("Hotbar inspector", err, parent=self)
                    else:
                        self.status_var.set(err)
                    return
                self._last_frame = frame
                self._last_hits = hits
                self._last_rows = rows
                self._show_rows(rows)
                self._show_scan_preview()
                self.save_btn.configure(state="normal")
                filled = sum(1 for r in rows if r.get("template"))
                roles_hit = sum(1 for r in rows if r.get("role"))
                mode = "calibrated" if slots_snapshot else "uniform"
                backend = ""
                if self._capture is not None:
                    backend = f" · {capture_backend_label(self._capture)}"
                self.status_var.set(
                    f"Box {box} · matched {filled}/8 · roles {roles_hit} · "
                    f"threshold {threshold:.2f} · {mode}"
                    + (" · live" if self.live_var.get() else "")
                    + backend
                )

            self.after(0, done)

        threading.Thread(target=worker, name="hotbar-inspector-scan", daemon=True).start()

    def _show_rows(self, rows: list[dict[str, Any]]) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    row.get("key", ""),
                    row.get("score", ""),
                    row.get("role", ""),
                    row.get("kr", ""),
                    row.get("template", ""),
                ),
            )

    def _show_scan_preview(self) -> None:
        if self._last_frame is None or self._calibrating:
            return
        h, w = self._last_frame.shape[:2]
        slots = self._active_slots(w, h)
        annotated = _annotate(
            self._last_frame, self._last_hits, slots=slots, crop_only=True
        )
        self.canvas.delete("all")
        photo, scale, ox, oy, dw, dh = self._fit_image_to_canvas(annotated)
        self._photo = photo
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)

    def save_snapshot(self) -> None:
        if self._last_frame is None:
            messagebox.showinfo(
                "Hotbar inspector", "Scan once before saving.", parent=self
            )
            return
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        png_path = OUTPUT_DIR / f"hotbar_{stamp}.png"
        json_path = OUTPUT_DIR / f"hotbar_{stamp}.json"
        try:
            import cv2

            h, w = self._last_frame.shape[:2]
            slots = self._active_slots(w, h)
            annotated = _annotate(
                self._last_frame, self._last_hits, slots=slots, crop_only=True
            )
            cv2.imencode(".png", annotated)[1].tofile(str(png_path))
            payload = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "threshold": float(self.threshold_var.get()),
                "visible_box": int(self.box_var.get()),
                "used_calibrated_slots": bool(
                    self.use_layout_var.get() and self._slots
                ),
                "slots_layout": slots,
                "detections": self._last_rows,
            }
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.status_var.set(f"Saved {png_path.name} + {json_path.name}")
        except Exception as exc:
            messagebox.showerror("Hotbar inspector", str(exc), parent=self)

    def _on_close(self) -> None:
        self._closing = True
        self.live_var.set(False)
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                close = getattr(capture, "close", None) or getattr(capture, "stop", None)
                if callable(close):
                    close()
            except Exception:
                pass
        self.destroy()


def run_hotbar_inspector() -> int:
    app = HotbarInspectorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_hotbar_inspector())
