"""Shop-sell list slot calibrator — drag/resize row_0..row_6 boxes (hotbar-style)."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Optional

from manmabot_v1.shopping.behaviors import load_sell_filters
from manmabot_v1.shopping.sell_slot_layout import (
    SELL_SLOT_KEYS,
    USERDATA_LAYOUT_PATH,
    default_sell_slot_layout,
    load_last_sell_category,
    load_sell_slot_layout,
    save_last_sell_category,
    save_sell_slot_layout,
)
from manmabot_v1.ui.design_system import TEXT_MUTED

HANDLE = 7


class ShoppingSellSlotCalibrator(ttk.Frame):
    """Capture a sell-dialog frame and edit template-match regions for each visible row."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, padding=2)
        self._on_log = on_log or (lambda _m: None)
        self._frame = None  # BGR
        self._photo = None
        self._slots: dict[str, dict[str, float]] = (
            load_sell_slot_layout() or default_sell_slot_layout()
        )
        self._selected_key: str | None = None
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._scale = 1.0
        self._offset = (0.0, 0.0)
        self._drag_mode: str | None = None
        self._drag_start = (0, 0)
        self._drag_box0: dict[str, float] | None = None
        self._drag_pan0 = (0.0, 0.0)
        self._slot_items: dict[str, int] = {}
        self._label_items: dict[str, int] = {}
        self._handle_items: list[int] = []
        self._match_hits: dict[str, Any] = {}
        self._matcher = None
        self._match_busy = False

        self.status_var = tk.StringVar(self, value="")
        self.zoom_label_var = tk.StringVar(self, value="100%")
        self.path_var = tk.StringVar(self, value=str(USERDATA_LAYOUT_PATH))
        self.pool_var = tk.StringVar(self, value="garbage_only")
        self.threshold_var = tk.StringVar(self, value="0.70")
        self.slot_w_px_var = tk.StringVar(self, value="32")
        self.slot_h_px_var = tk.StringVar(self, value="32")
        self.slot_size_info_var = tk.StringVar(self, value="")
        self._build()

    def _log(self, message: str) -> None:
        self._on_log(message)
        self.status_var.set(message)

    def _build(self) -> None:
        top = ttk.Frame(self, style="Chrome.TFrame")
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(
            top,
            text=(
                "Sell list slots · frame-normalized boxes for template matching "
                f"({len(SELL_SLOT_KEYS)} visible rows)"
            ),
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left")
        ttk.Label(
            top, textvariable=self.path_var, style="Chrome.TLabel", foreground=TEXT_MUTED
        ).pack(side="right")

        bar = ttk.Frame(self, style="Chrome.TFrame")
        bar.pack(fill="x")
        ttk.Button(bar, text="Recapture", command=self.recapture).pack(side="left", padx=2)
        ttk.Button(bar, text="Test match", command=self.test_match).pack(side="left", padx=2)
        ttk.Button(
            bar, text="Save slot crop…", command=self.save_slot_crop_browse
        ).pack(side="left", padx=2)
        ttk.Button(bar, text="Reset grid", command=self.reset_grid).pack(side="left", padx=2)
        ttk.Label(bar, text="Pool", style="Chrome.TLabel").pack(side="left", padx=(8, 2))
        ttk.Combobox(
            bar,
            textvariable=self.pool_var,
            values=("all_items", "garbage_only"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=2)
        ttk.Label(bar, text="Thr", style="Chrome.TLabel").pack(side="left", padx=(6, 2))
        ttk.Entry(bar, textvariable=self.threshold_var, width=5).pack(side="left", padx=2)
        ttk.Button(bar, text="Zoom -", command=lambda: self._zoom_by(1 / 1.25)).pack(
            side="left", padx=2
        )
        ttk.Label(bar, textvariable=self.zoom_label_var, width=5, style="Chrome.TLabel").pack(
            side="left"
        )
        ttk.Button(bar, text="Zoom +", command=lambda: self._zoom_by(1.25)).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Reset zoom", command=self._zoom_reset).pack(side="left", padx=2)
        ttk.Button(bar, text="Save layout", command=self.save_layout).pack(
            side="right", padx=2
        )
        ttk.Button(bar, text="Reload", command=self.reload_layout).pack(side="right", padx=2)

        size_bar = ttk.Frame(self, style="Chrome.TFrame")
        size_bar.pack(fill="x", pady=(4, 0))
        ttk.Label(size_bar, text="Slot size (px)", style="Chrome.TLabel").pack(
            side="left", padx=(0, 4)
        )
        ttk.Label(size_bar, text="W", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(size_bar, textvariable=self.slot_w_px_var, width=5).pack(
            side="left", padx=(2, 6)
        )
        ttk.Label(size_bar, text="H", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(size_bar, textvariable=self.slot_h_px_var, width=5).pack(
            side="left", padx=(2, 8)
        )
        ttk.Button(
            size_bar, text="Read from selected", command=self.read_size_from_selected
        ).pack(side="left", padx=2)
        ttk.Button(
            size_bar, text="Apply to selected", command=self.apply_size_to_selected
        ).pack(side="left", padx=2)
        ttk.Button(
            size_bar, text="Apply to all slots", command=self.apply_size_to_all
        ).pack(side="left", padx=2)
        ttk.Label(
            size_bar,
            textvariable=self.slot_size_info_var,
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
        ).pack(side="left", padx=10)

        mid = ttk.Panedwindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=4)
        list_box = ttk.Frame(mid, padding=2)
        canvas_box = ttk.Frame(mid, padding=2)
        mid.add(list_box, weight=1)
        mid.add(canvas_box, weight=4)

        ttk.Label(list_box, text="Slots / match", style="Chrome.TLabel").pack(anchor="w")
        self.slot_list = tk.Listbox(list_box, height=12, exportselection=False)
        self.slot_list.pack(fill="both", expand=True)
        self._refresh_slot_list()
        self.slot_list.selection_set(0)
        self.slot_list.bind("<<ListboxSelect>>", self._on_slot_list_select)
        self.slot_list.bind("<Up>", lambda e: self._shift_row(-1, e))
        self.slot_list.bind("<Down>", lambda e: self._shift_row(1, e))
        self.slot_list.bind("<Return>", self._on_enter_save_crop)
        self.slot_list.bind("<KP_Enter>", self._on_enter_save_crop)

        ttk.Label(
            list_box,
            text=(
                "↑↓ select row · Enter = Save slot crop… · "
                "move boxes only by mouse drag (no arrow nudge)"
            ),
            style="Chrome.TLabel",
            foreground=TEXT_MUTED,
            wraplength=160,
        ).pack(anchor="w", pady=(6, 0))

        self.canvas = tk.Canvas(canvas_box, background="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # Arrow keys select rows only — never nudge boxes (drag to move).
        self.canvas.bind("<Up>", lambda e: self._shift_row(-1, e))
        self.canvas.bind("<Down>", lambda e: self._shift_row(1, e))
        self.canvas.bind("<Left>", lambda _e: "break")
        self.canvas.bind("<Right>", lambda _e: "break")
        self.canvas.bind("<Return>", self._on_enter_save_crop)
        self.canvas.bind("<KP_Enter>", self._on_enter_save_crop)
        self.canvas.bind("<Tab>", self._cycle_selection)
        self.canvas.focus_set()

        foot = ttk.Frame(self, style="Chrome.TFrame")
        foot.pack(fill="x")
        ttk.Label(foot, textvariable=self.status_var, style="Chrome.TLabel").pack(
            side="left"
        )

        if self._slots:
            self._selected_key = SELL_SLOT_KEYS[0]
            self._update_size_info()
            self._log(
                f"Loaded sell slot layout ({len(self._slots)} boxes) — "
                "Recapture / set pixel size / Save slot crop"
            )
        else:
            self._log("No layout yet — Recapture a sell dialog, then Save layout")

    def _refresh_slot_list(self) -> None:
        sel = self.slot_list.curselection()
        self.slot_list.delete(0, "end")
        garbage: set[str] = set()
        keep: set[str] = set()
        try:
            filters = load_sell_filters()
            garbage = {str(n).strip() for n in filters.garbage_list if str(n).strip()}
            keep = {str(n).strip() for n in filters.keep_list if str(n).strip()}
        except Exception:
            pass
        for key in SELL_SLOT_KEYS:
            hit = self._match_hits.get(key)
            if hit is None:
                self.slot_list.insert("end", key)
                continue
            mark = ""
            if hit.kr_name in keep:
                mark = " [keep]"
            elif hit.kr_name in garbage:
                mark = " [garbage]"
            self.slot_list.insert(
                "end",
                f"{key}  {hit.kr_name}  {hit.score:.3f}{mark}",
            )
        if sel:
            try:
                self.slot_list.selection_set(sel[0])
            except tk.TclError:
                pass

    def recapture(self) -> None:
        try:
            from manmabot_v1.perception_capture import (
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
            self._match_hits.clear()
            if not self._slots:
                self._slots = default_sell_slot_layout()
            self._zoom = 1.0
            self._pan = (0.0, 0.0)
            self.zoom_label_var.set("100%")
            if self._selected_key is None:
                self._selected_key = SELL_SLOT_KEYS[0]
                self.slot_list.selection_clear(0, "end")
                self.slot_list.selection_set(0)
            self._refresh_slot_list()
            self._redraw()
            self._log(f"Captured frame {frame.shape[1]}x{frame.shape[0]} for sell slots")
            self._update_size_info()
            self.canvas.focus_set()
        except Exception as exc:
            messagebox.showwarning("Sell slots", str(exc), parent=self.winfo_toplevel())
            self._log(f"Recapture failed: {exc}")

    def test_match(self) -> None:
        """Run icon template matching on the current frame + slot boxes."""
        if self._match_busy:
            return
        if self._frame is None:
            messagebox.showinfo(
                "Sell slots",
                "Recapture a sell-list frame first, then Test match.",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            thr = float(self.threshold_var.get().strip())
        except ValueError:
            messagebox.showwarning(
                "Sell slots",
                "Threshold must be a number (e.g. 0.70).",
                parent=self.winfo_toplevel(),
            )
            return
        thr = max(0.5, min(0.99, thr))
        self.threshold_var.set(f"{thr:.2f}")
        self._match_busy = True
        self._log("Matching templates in sell slots…")
        frame = self._frame.copy()
        slots = {k: dict(v) for k, v in self._slots.items()}
        pool_mode = self.pool_var.get().strip()

        def worker() -> None:
            err: str | None = None
            hits_by_key: dict[str, Any] = {}
            try:
                from manmabot_v1.hotbar.item_catalog import make_sell_icon_matcher

                if self._matcher is None:
                    self._matcher = make_sell_icon_matcher()
                matcher = self._matcher
                if pool_mode == "garbage_only":
                    filters = load_sell_filters()
                    want = {
                        str(n).strip() for n in filters.garbage_list if str(n).strip()
                    }
                    if not want:
                        raise RuntimeError(
                            "garbage_list is empty — mark items on Sell → Filters first"
                        )
                    templates = matcher.item_templates(names=want)
                    if not templates:
                        raise RuntimeError(
                            "No shopping_slots templates match garbage_list — "
                            "Save slot crop into shopping_slots first"
                        )
                else:
                    templates = matcher.item_templates()
                    if not templates:
                        raise RuntimeError(
                            "shopping_slots is empty — Save slot crop to add sell templates"
                        )
                hits = matcher.match_slot_boxes(
                    frame,
                    slots,
                    SELL_SLOT_KEYS,
                    threshold=thr,
                    templates=templates,
                    use_color=True,
                )
                for hit in hits:
                    key = hit.fkey or ""
                    if key:
                        hits_by_key[key] = hit
            except Exception as exc:
                err = str(exc)

            def done() -> None:
                self._match_busy = False
                if err:
                    messagebox.showwarning(
                        "Sell slots", err, parent=self.winfo_toplevel()
                    )
                    self._log(f"Test match failed: {err}")
                    return
                self._match_hits = hits_by_key
                self._refresh_slot_list()
                self._redraw()
                parts = [
                    f"{k}={hits_by_key[k].kr_name}({hits_by_key[k].score:.2f})"
                    for k in SELL_SLOT_KEYS
                    if k in hits_by_key
                ]
                self._log(
                    f"Test match · {len(hits_by_key)}/{len(SELL_SLOT_KEYS)} hits · "
                    f"pool={pool_mode} · thr={thr:.2f}"
                    + (f" · {', '.join(parts)}" if parts else " · no hits")
                )

            self.after(0, done)

        threading.Thread(target=worker, name="sell-slot-match", daemon=True).start()

    def _frame_wh(self) -> tuple[int, int]:
        """Current capture size, or last saved layout size fallback."""
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            return int(w), int(h)
        loaded = load_sell_slot_layout()
        # layout file may have been saved with frame_w/h — re-read raw if needed
        try:
            import json

            path = USERDATA_LAYOUT_PATH
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                fw = int(data.get("frame_w") or 0)
                fh = int(data.get("frame_h") or 0)
                if fw > 0 and fh > 0:
                    return fw, fh
        except Exception:
            pass
        _ = loaded
        return 1280, 720

    def _parse_size_px(self) -> tuple[int, int]:
        try:
            w = int(float(self.slot_w_px_var.get().strip()))
            h = int(float(self.slot_h_px_var.get().strip()))
        except ValueError as exc:
            raise ValueError("W and H must be integers (pixels)") from exc
        if w < 4 or h < 4:
            raise ValueError("W and H must be at least 4 px")
        if w > 512 or h > 512:
            raise ValueError("W and H must be ≤ 512 px")
        return w, h

    def _box_size_px(self, box: dict[str, float], frame_w: int, frame_h: int) -> tuple[int, int]:
        pw = max(1, int(round((float(box["x1"]) - float(box["x0"])) * frame_w)))
        ph = max(1, int(round((float(box["y1"]) - float(box["y0"])) * frame_h)))
        return pw, ph

    def _resize_box_keep_center(
        self,
        box: dict[str, float],
        *,
        width_px: int,
        height_px: int,
        frame_w: int,
        frame_h: int,
    ) -> dict[str, float]:
        cx = (float(box["x0"]) + float(box["x1"])) / 2.0
        cy = (float(box["y0"]) + float(box["y1"])) / 2.0
        nw = width_px / max(frame_w, 1)
        nh = height_px / max(frame_h, 1)
        x0 = cx - nw / 2.0
        y0 = cy - nh / 2.0
        x1 = cx + nw / 2.0
        y1 = cy + nh / 2.0
        # Clamp inside frame without changing size when possible.
        if x0 < 0.0:
            x1 -= x0
            x0 = 0.0
        if y0 < 0.0:
            y1 -= y0
            y0 = 0.0
        if x1 > 1.0:
            x0 -= x1 - 1.0
            x1 = 1.0
        if y1 > 1.0:
            y0 -= y1 - 1.0
            y1 = 1.0
        x0 = max(0.0, min(1.0, x0))
        y0 = max(0.0, min(1.0, y0))
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        if x1 <= x0:
            x1 = min(1.0, x0 + nw)
        if y1 <= y0:
            y1 = min(1.0, y0 + nh)
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}

    def _update_size_info(self) -> None:
        key = self._selected_key
        if not key or key not in self._slots:
            self.slot_size_info_var.set("")
            return
        fw, fh = self._frame_wh()
        pw, ph = self._box_size_px(self._slots[key], fw, fh)
        src = "capture" if self._frame is not None else f"ref {fw}x{fh}"
        self.slot_size_info_var.set(f"{key} now {pw}×{ph} px ({src})")

    def read_size_from_selected(self) -> None:
        key = self._selected_slot_key()
        if not key or key not in self._slots:
            messagebox.showinfo(
                "Sell slots", "Select a slot first.", parent=self.winfo_toplevel()
            )
            return
        fw, fh = self._frame_wh()
        pw, ph = self._box_size_px(self._slots[key], fw, fh)
        self.slot_w_px_var.set(str(pw))
        self.slot_h_px_var.set(str(ph))
        self._update_size_info()
        self._log(f"Read size from {key}: {pw}×{ph} px")

    def apply_size_to_selected(self) -> None:
        key = self._selected_slot_key()
        if not key or key not in self._slots:
            messagebox.showinfo(
                "Sell slots", "Select a slot first.", parent=self.winfo_toplevel()
            )
            return
        try:
            pw, ph = self._parse_size_px()
        except ValueError as exc:
            messagebox.showwarning("Sell slots", str(exc), parent=self.winfo_toplevel())
            return
        fw, fh = self._frame_wh()
        self._slots[key] = self._resize_box_keep_center(
            self._slots[key], width_px=pw, height_px=ph, frame_w=fw, frame_h=fh
        )
        self._update_size_info()
        self._redraw()
        self._log(f"Applied {pw}×{ph} px to {key} (center kept)")

    def apply_size_to_all(self) -> None:
        try:
            pw, ph = self._parse_size_px()
        except ValueError as exc:
            messagebox.showwarning("Sell slots", str(exc), parent=self.winfo_toplevel())
            return
        fw, fh = self._frame_wh()
        for key in SELL_SLOT_KEYS:
            box = self._slots.get(key)
            if box is None:
                continue
            self._slots[key] = self._resize_box_keep_center(
                box, width_px=pw, height_px=ph, frame_w=fw, frame_h=fh
            )
        self._update_size_info()
        self._redraw()
        self._log(f"Applied {pw}×{ph} px to all {len(SELL_SLOT_KEYS)} slots (centers kept)")

    def _selected_slot_key(self) -> str | None:
        sel = self.slot_list.curselection()
        if not sel:
            return self._selected_key
        idx = int(sel[0])
        if 0 <= idx < len(SELL_SLOT_KEYS):
            return SELL_SLOT_KEYS[idx]
        return self._selected_key

    def _crop_bgr_for_slot(self, key: str):
        """BGR crop from the calibrated slot box on the current frame."""
        import numpy as np

        if self._frame is None:
            raise RuntimeError("Recapture a frame first")
        frame = self._frame
        h, w = frame.shape[:2]
        box = self._slots.get(key)
        if not box:
            raise RuntimeError(f"No slot box for {key}")
        x0 = max(0, int(round(float(box["x0"]) * w)))
        y0 = max(0, int(round(float(box["y0"]) * h)))
        x1 = min(w, int(round(float(box["x1"]) * w)))
        y1 = min(h, int(round(float(box["y1"]) * h)))
        if x1 - x0 < 4 or y1 - y0 < 4:
            raise RuntimeError(f"Crop for {key} is too small ({x1 - x0}x{y1 - y0})")
        return np.ascontiguousarray(frame[y0:y1, x0:x1])

    def _reload_matcher(self) -> None:
        from manmabot_v1.hotbar.item_catalog import make_sell_icon_matcher

        self._matcher = make_sell_icon_matcher()

    def save_slot_crop_browse(self) -> None:
        """Crop selected slot into shopping_slots (hotbar icons_unique stays untouched)."""
        from debug_tools.shopping_template_browse import TemplateBrowseDialog
        from manmabot_v1.hotbar.item_catalog import (
            replace_template_with_bgr_crop,
            save_new_item_template,
        )

        key = self._selected_slot_key()
        if not key:
            messagebox.showinfo(
                "Sell slots", "Select a slot row first.", parent=self.winfo_toplevel()
            )
            return
        try:
            crop = self._crop_bgr_for_slot(key)
        except Exception as exc:
            messagebox.showwarning("Sell slots", str(exc), parent=self.winfo_toplevel())
            return

        dlg = TemplateBrowseDialog(
            self,
            title=f"Save {key} crop ({crop.shape[1]}x{crop.shape[0]}) → shopping_slots",
            prefer_garbage=False,
            pack="sell",
            default_category=load_last_sell_category(),
        )
        pick = dlg.result
        if pick is None:
            self._log("Save slot crop cancelled")
            return
        entry = pick.entry
        if pick.is_new:
            msg = (
                f"Create a NEW sell template from the {key} slot crop?\n\n"
                f"Item: {entry.kr_name}\n"
                f"File: shopping_slots/{entry.template}\n"
                f"Crop: {crop.shape[1]}x{crop.shape[0]} px"
            )
            if not messagebox.askyesno("Save new template", msg, parent=self.winfo_toplevel()):
                return
            try:
                path = save_new_item_template(
                    entry.category,
                    entry.kr_name,
                    crop,
                    overwrite=False,
                    pack="sell",
                )
                save_last_sell_category(entry.category)
                self._reload_matcher()
                self._log(
                    f"Created sell template · {key} → {entry.kr_name} "
                    f"(shopping_slots/{entry.template})"
                )
            except FileExistsError as exc:
                messagebox.showwarning(
                    "Sell slots", str(exc), parent=self.winfo_toplevel()
                )
                self._log(f"Save new failed: {exc}")
            except Exception as exc:
                messagebox.showerror(
                    "Sell slots", f"Save new failed:\n{exc}", parent=self.winfo_toplevel()
                )
                self._log(f"Save new failed: {exc}")
            return

        if not messagebox.askyesno(
            "Replace sell template",
            f"Overwrite this sell template with the {key} slot crop?\n\n"
            f"Item: {entry.kr_name}\n"
            f"File: shopping_slots/{entry.template}\n"
            f"Crop: {crop.shape[1]}x{crop.shape[0]} px\n\n"
            "A backup is saved under shopping_slots/_replaced_backup/.\n"
            "(Hotbar icons_unique is not modified.)",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            path = replace_template_with_bgr_crop(
                entry.template, crop, backup=True, pack="sell"
            )
            save_last_sell_category(entry.category)
            self._reload_matcher()
            self._log(
                f"Replaced sell template · {key} → {entry.kr_name} "
                f"(shopping_slots/{entry.template}) · {path.name}"
            )
        except Exception as exc:
            messagebox.showerror(
                "Sell slots", f"Replace failed:\n{exc}", parent=self.winfo_toplevel()
            )
            self._log(f"Replace failed: {exc}")

    def reset_grid(self) -> None:
        self._slots = default_sell_slot_layout()
        self._match_hits.clear()
        self._selected_key = SELL_SLOT_KEYS[0]
        self.slot_list.selection_clear(0, "end")
        self.slot_list.selection_set(0)
        self._refresh_slot_list()
        self._redraw()
        self._log("Reset to default sell-list grid")

    def reload_layout(self) -> None:
        loaded = load_sell_slot_layout()
        if loaded is None:
            messagebox.showinfo(
                "Sell slots",
                "No saved layout on disk — keeping current boxes.",
                parent=self.winfo_toplevel(),
            )
            return
        self._slots = loaded
        self._match_hits.clear()
        self._refresh_slot_list()
        self._redraw()
        self._log(f"Reloaded sell slot layout from {USERDATA_LAYOUT_PATH.name}")

    def save_layout(self) -> None:
        if not self._slots:
            messagebox.showinfo(
                "Sell slots", "Nothing to save yet.", parent=self.winfo_toplevel()
            )
            return
        if self._frame is None:
            # Still allow save using last known / placeholder size.
            frame_w, frame_h = 1280, 720
        else:
            frame_h, frame_w = self._frame.shape[:2]
        path = save_sell_slot_layout(self._slots, frame_w=frame_w, frame_h=frame_h)
        self.path_var.set(str(path))
        self._log(f"Saved sell slot layout → {path}")

    def _on_slot_list_select(self, _event=None) -> None:
        sel = self.slot_list.curselection()
        if not sel:
            return
        self._selected_key = SELL_SLOT_KEYS[int(sel[0])]
        self._update_size_info()
        self._redraw()
        self.canvas.focus_set()

    def _zoom_by(self, factor: float, *, anchor: tuple[float, float] | None = None) -> None:
        if self._frame is None:
            return
        old_zoom = self._zoom
        new_zoom = max(0.25, min(12.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        ax = cw / 2 if anchor is None else anchor[0]
        ay = ch / 2 if anchor is None else anchor[1]
        h, w = self._frame.shape[:2]
        fit = min(cw / w, ch / h)
        old_s = fit * old_zoom
        new_s = fit * new_zoom
        ox0 = (cw - w * old_s) / 2 + self._pan[0]
        oy0 = (ch - h * old_s) / 2 + self._pan[1]
        img_x = (ax - ox0) / max(old_s, 1e-6)
        img_y = (ay - oy0) / max(old_s, 1e-6)
        ox1 = ax - img_x * new_s
        oy1 = ay - img_y * new_s
        self._pan = (ox1 - (cw - w * new_s) / 2, oy1 - (ch - h * new_s) / 2)
        self._zoom = new_zoom
        self.zoom_label_var.set(f"{int(round(new_zoom * 100))}%")
        self._redraw()

    def _zoom_reset(self) -> None:
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self.zoom_label_var.set("100%")
        self._redraw()

    def _on_wheel(self, event: tk.Event) -> None:
        if self._frame is None:
            return
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 1 / 1.25
        self._zoom_by(factor, anchor=(event.x, event.y))
        return "break"

    def _shift_row(self, delta: int, _event: tk.Event | None = None) -> str:
        """Up/Down: change selected slot row (does not move boxes)."""
        keys = list(SELL_SLOT_KEYS)
        if not keys:
            return "break"
        if self._selected_key in keys:
            idx = keys.index(self._selected_key)
        else:
            sel = self.slot_list.curselection()
            idx = int(sel[0]) if sel else 0
        idx = max(0, min(len(keys) - 1, idx + int(delta)))
        self._selected_key = keys[idx]
        self.slot_list.selection_clear(0, "end")
        self.slot_list.selection_set(idx)
        self.slot_list.activate(idx)
        self.slot_list.see(idx)
        self._update_size_info()
        self._redraw()
        return "break"

    def _on_enter_save_crop(self, _event: tk.Event | None = None) -> str:
        self.save_slot_crop_browse()
        try:
            self.slot_list.focus_set()
        except tk.TclError:
            pass
        return "break"

    def _cycle_selection(self, _event: tk.Event) -> str:
        keys = list(SELL_SLOT_KEYS)
        if self._selected_key in keys:
            idx = (keys.index(self._selected_key) + 1) % len(keys)
        else:
            idx = 0
        self._selected_key = keys[idx]
        self.slot_list.selection_clear(0, "end")
        self.slot_list.selection_set(idx)
        self.slot_list.see(idx)
        self._update_size_info()
        self._redraw()
        self.canvas.focus_set()
        return "break"
    def _on_pan_press(self, event: tk.Event) -> None:
        self._drag_mode = "pan"
        self._drag_start = (event.x, event.y)
        self._drag_pan0 = self._pan
        self.canvas.focus_set()

    def _on_pan_drag(self, event: tk.Event) -> None:
        if self._drag_mode != "pan":
            return
        self._pan = (
            self._drag_pan0[0] + (event.x - self._drag_start[0]),
            self._drag_pan0[1] + (event.y - self._drag_start[1]),
        )
        self._redraw()

    def _on_pan_release(self, _event: tk.Event) -> None:
        if self._drag_mode == "pan":
            self._drag_mode = None

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

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._slot_items.clear()
        self._label_items.clear()
        self._handle_items.clear()
        if self._frame is None:
            self.canvas.create_text(
                20,
                20,
                anchor="nw",
                fill="#aaaaaa",
                text="Recapture with the sell list open, then drag row_0..row_6 onto each icon.",
            )
            return
        photo, scale, ox, oy, dw, dh = self._fit()
        self._photo = photo
        self._scale = scale
        self._offset = (ox, oy)
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)
        h, w = self._frame.shape[:2]
        for key in SELL_SLOT_KEYS:
            box = self._slots.get(key)
            if box is None:
                continue
            x0, y0, x1, y1 = self._norm_to_canvas(box, w, h)
            color = "#22c55e" if key == self._selected_key else "#38bdf8"
            width = 2 if key == self._selected_key else 1
            rid = self.canvas.create_rectangle(
                x0, y0, x1, y1, outline=color, width=width, tags=("slot", key)
            )
            hit = self._match_hits.get(key)
            label = key if hit is None else f"{key} {hit.kr_name} {hit.score:.2f}"
            lid = self.canvas.create_text(
                x0 + 4,
                y0 + 4,
                anchor="nw",
                text=label,
                fill="#fbbf24" if hit is not None else color,
                font=("Segoe UI", 9, "bold"),
                tags=("slot", key),
            )
            self._slot_items[key] = rid
            self._label_items[key] = lid
            if hit is not None:
                hx0 = ox + hit.x * scale
                hy0 = oy + hit.y * scale
                hx1 = ox + (hit.x + hit.w) * scale
                hy1 = oy + (hit.y + hit.h) * scale
                self.canvas.create_rectangle(
                    hx0,
                    hy0,
                    hx1,
                    hy1,
                    outline="#fbbf24",
                    width=2,
                    tags=("match", key),
                )
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
        ox, oy = self._offset
        s = self._scale
        return (
            ox + box["x0"] * frame_w * s,
            oy + box["y0"] * frame_h * s,
            ox + box["x1"] * frame_w * s,
            oy + box["y1"] * frame_h * s,
        )

    def _hit_test(self, x: float, y: float) -> tuple[str | None, str | None]:
        if self._frame is None:
            return None, None
        h, w = self._frame.shape[:2]
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
        for key in reversed(SELL_SLOT_KEYS):
            box = self._slots.get(key)
            if not box:
                continue
            x0, y0, x1, y1 = self._norm_to_canvas(box, w, h)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key, "move"
        return None, None

    def _on_press(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        if self._frame is None:
            return
        key, mode = self._hit_test(event.x, event.y)
        self._selected_key = key
        self._drag_mode = mode if key else None
        self._drag_start = (event.x, event.y)
        if key and key in self._slots:
            self._drag_box0 = dict(self._slots[key])
            try:
                idx = SELL_SLOT_KEYS.index(key)
                self.slot_list.selection_clear(0, "end")
                self.slot_list.selection_set(idx)
                self.slot_list.see(idx)
            except ValueError:
                pass
        else:
            self._drag_box0 = None
            if self._zoom > 1.01:
                self._drag_mode = "pan"
                self._drag_pan0 = self._pan
        self._redraw()

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_mode == "pan":
            self._pan = (
                self._drag_pan0[0] + (event.x - self._drag_start[0]),
                self._drag_pan0[1] + (event.y - self._drag_start[1]),
            )
            self._redraw()
            return
        if (
            not self._selected_key
            or not self._drag_mode
            or self._drag_box0 is None
            or self._frame is None
        ):
            return
        h, w = self._frame.shape[:2]
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        s = max(self._scale, 1e-6)
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
        self._redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self._drag_box0 = None
        self._update_size_info()
