"""GUI: capture LC.exe frames paired with realtime_monitor world coords."""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Optional

from lib.memory_pipe import LineageMonitor
from lib.monitor_start import try_start_monitor
from lib.screen_capture import capture_backend_label, open_capture
from lib.ui_style import TEXT_MUTED, apply_classic_style
from paths import OUTPUT_DIR, TOOL_DIR
from session import (
    CaptureSession,
    annotate_frame,
    format_world,
    player_world_from_snapshot,
)
from settings import load_settings

VK_SPACE = 0x20
VK_ESCAPE = 0x1B


def _is_elevated() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _key_down(vk: int) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _our_window_foreground(hwnd: int) -> bool:
    if os.name != "nt" or not hwnd:
        return False
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _close_capture(capture: Any) -> None:
    if capture is None:
        return
    try:
        close = getattr(capture, "close", None) or getattr(capture, "stop", None)
        if callable(close):
            close()
    except Exception:
        pass


def capture_miss_reason(capture: Any) -> str:
    """Why ``get_frame()`` returned None — LC.exe missing is only one case."""
    process = str(getattr(capture, "window_process", None) or "LC.exe")
    if getattr(capture, "is_minimized", False):
        return f"{process} is minimized — restore the game window"
    tracker = getattr(capture, "_tracker", None)
    hwnd = None
    if tracker is not None:
        resolve = getattr(tracker, "_resolve_hwnd", None)
        if callable(resolve):
            try:
                hwnd = resolve()
            except Exception:
                hwnd = None
    if not hwnd:
        return (
            f"{process} window not found. Start the client and keep it visible "
            "(GameGuard dummy windows are ignored)."
        )
    monitor = getattr(capture, "_monitor", None)
    if not monitor:
        getattr(capture, "_refresh_window_region", lambda: False)()
        monitor = getattr(capture, "_monitor", None)
    if not monitor:
        return f"{process} found but client bounds are empty"
    return (
        f"{process} found (hwnd={hwnd}) but mss grab returned no pixels "
        "(BitBlt failed — often a dead/cross-thread mss instance)"
    )


def _relaunch_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        from elevate import main as elevate_main

        return elevate_main() == 0
    except Exception:
        try:
            import ctypes

            script = TOOL_DIR / "run.py"
            py = Path(sys.executable).resolve()
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(py),
                f'"{script}"',
                str(TOOL_DIR),
                1,
            )
            return int(rc) > 32
        except Exception:
            return False


class ScreenVsCoordinateApp(tk.Tk):
    """Standalone capture: perception frame + player world coordinate."""

    def __init__(self) -> None:
        super().__init__()
        self._elevated = _is_elevated()
        title = "Screen vs coordinate capture"
        if self._elevated:
            title += " (Administrator)"
        self.title(title)
        self.geometry("980x720")
        self.minsize(820, 560)
        apply_classic_style(self)
        self.attributes("-topmost", True)

        self._capture = None
        self._monitor = None
        self._session: CaptureSession | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._armed = threading.Event()
        self._lock = threading.Lock()
        self._closing = False
        self._photo = None
        self._last_frame = None
        self._last_world: Optional[dict[str, Any]] = None
        self._space_was_down = False
        self._esc_was_down = False
        self._count = 0
        self._hwnd = 0
        self._once = threading.Event()
        self._last_miss_log = 0.0
        self._last_preview_at = 0.0

        self.mode_var = tk.StringVar(self, value="space")
        self.fps_var = tk.StringVar(self, value="2")
        self.status_var = tk.StringVar(self, value="Connect capture + monitor, then Start.")
        self.coord_var = tk.StringVar(self, value="world: —")
        self.count_var = tk.StringVar(self, value="saved: 0")
        self.backend_var = tk.StringVar(self, value="capture: not open")
        self.monitor_var = tk.StringVar(self, value="monitor: not connected")
        self.armed_var = tk.StringVar(self, value="idle")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._boot_async)
        self.after(100, self._refresh_hwnd)
        if not self._elevated:
            self.after(250, self._warn_elevation)

    def _refresh_hwnd(self) -> None:
        """Cache the Win32 toplevel HWND (safe to read from the capture thread)."""
        if self._closing:
            return
        try:
            import ctypes

            hwnd = int(self.winfo_id())
            root = int(ctypes.windll.user32.GetAncestor(hwnd, 2) or 0)
            self._hwnd = root or hwnd
        except Exception:
            pass
        self.after(1000, self._refresh_hwnd)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6, style="Chrome.TFrame")
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Screen vs coordinate",
            style="Chrome.TLabel",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        elev = (
            "Admin · memory pipe OK"
            if self._elevated
            else "Not admin · pipe may be WinError 5"
        )
        ttk.Label(header, text=elev, style="Chrome.TLabel", foreground=TEXT_MUTED).pack(
            side="left", padx=12
        )
        if not self._elevated:
            ttk.Button(
                header, text="Relaunch as Admin", command=self._on_relaunch_admin
            ).pack(side="right", padx=2)

        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="Mode").pack(side="left")
        self.space_radio = ttk.Radiobutton(
            bar, text="Space", variable=self.mode_var, value="space"
        )
        self.space_radio.pack(side="left", padx=(6, 2))
        self.fps_radio = ttk.Radiobutton(
            bar, text="FPS", variable=self.mode_var, value="fps"
        )
        self.fps_radio.pack(side="left", padx=2)
        ttk.Label(bar, text="FPS").pack(side="left", padx=(12, 4))
        self.fps_spin = ttk.Spinbox(
            bar, from_=0.5, to=30.0, increment=0.5, width=6, textvariable=self.fps_var
        )
        self.fps_spin.pack(side="left")

        self.start_btn = ttk.Button(bar, text="Start", command=self._on_start)
        self.start_btn.pack(side="left", padx=(16, 2))
        self.stop_btn = ttk.Button(
            bar, text="Stop", command=self._on_stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=2)
        ttk.Button(bar, text="Capture once", command=self._on_once).pack(
            side="left", padx=(12, 2)
        )
        ttk.Button(bar, text="Reconnect", command=self._on_reconnect).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Open output", command=self._open_output).pack(
            side="right", padx=2
        )

        meta = ttk.Frame(self, padding=(8, 0, 8, 4))
        meta.pack(fill="x")
        ttk.Label(meta, textvariable=self.backend_var, foreground=TEXT_MUTED).pack(
            anchor="w"
        )
        ttk.Label(meta, textvariable=self.monitor_var, foreground=TEXT_MUTED).pack(
            anchor="w"
        )

        live = ttk.Frame(self, padding=(8, 0, 8, 4))
        live.pack(fill="x")
        ttk.Label(
            live, textvariable=self.coord_var, font=("Segoe UI", 12, "bold")
        ).pack(side="left")
        ttk.Label(live, textvariable=self.count_var).pack(side="left", padx=16)
        ttk.Label(live, textvariable=self.armed_var, foreground=TEXT_MUTED).pack(
            side="left"
        )

        self.canvas = tk.Canvas(self, background="#1a1a1a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas.bind("<Configure>", lambda _e: self._redraw_preview())

        foot = ttk.Frame(self, padding=(8, 4, 8, 6), style="Chrome.TFrame")
        foot.pack(fill="x")
        ttk.Label(foot, textvariable=self.status_var, style="Chrome.TLabel").pack(
            anchor="w"
        )
        hint = (
            "Space mode: press Space in-game to save a pair (ignored while this window is focused). "
            "Esc stops recording. FPS mode saves at the chosen rate. "
            "Each save is the bot perception crop plus player.pos from realtime_monitor."
        )
        ttk.Label(foot, text=hint, style="Chrome.TLabel", foreground=TEXT_MUTED, wraplength=920).pack(
            anchor="w", pady=(2, 0)
        )

        log_fr = ttk.Frame(self, padding=(8, 0, 8, 8))
        log_fr.pack(fill="x")
        self.log = tk.Text(log_fr, height=6, wrap="word")
        self.log.pack(fill="x")
        self.log.configure(state="disabled")

    def _log(self, message: str) -> None:
        def _append() -> None:
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.after(0, _append)

    def _warn_elevation(self) -> None:
        self._log(
            "Not running as Administrator — realtime_monitor_full.exe is elevated, "
            "so the named pipe often returns WinError 5. Use Relaunch as Admin."
        )
        self.status_var.set("Need Administrator to read the memory pipe")

    def _on_relaunch_admin(self) -> None:
        if _relaunch_elevated():
            self._on_close()
        else:
            messagebox.showwarning(
                "Screen vs coordinate",
                "Elevation failed. Accept the UAC prompt, or run the Admin bat.",
                parent=self,
            )

    def _boot_async(self) -> None:
        threading.Thread(target=self._boot_worker, daemon=True).start()

    def _boot_worker(self) -> None:
        # Do not open mss here. python-mss is per-thread; grab must happen
        # on the same thread that created ScreenCapture.
        self._connect_monitor(start_if_needed=True)
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="svc-capture")
        self._worker.start()

    def _open_capture_on_loop_thread(self) -> Any:
        self._ui(lambda: self.status_var.set("Opening capture…"))
        capture = open_capture(load_settings())
        with self._lock:
            old = self._capture
            self._capture = capture
        _close_capture(old)
        label = capture_backend_label(capture)
        self._ui(lambda: self.backend_var.set(f"capture: {label}"))
        self._log(label)
        return capture

    def _connect_monitor(self, *, start_if_needed: bool) -> None:
        self._close_monitor()
        self._ui(lambda: self.monitor_var.set("monitor: connecting…"))
        try:
            settings = load_settings()
            if start_if_needed:
                ok_start, msg_start = try_start_monitor(log=self._log)
                self._log(msg_start)
                if not ok_start:
                    pass

            mon = LineageMonitor(
                pipe=settings.pipe, connect_retries=20, connect_delay=0.2
            )
            mon.connect()
            mon.ping()
            snap = mon.snapshot(fresh=False)
            world = player_world_from_snapshot(snap)
            with self._lock:
                self._monitor = mon
                self._last_world = world
            if world:
                detail = f"monitor: connected  {format_world(world)}"
            else:
                detail = "monitor: connected — waiting for player.pos (enter the world)"
            self._ui(lambda: self.monitor_var.set(detail))
            self._ui(lambda: self.coord_var.set(f"world: {format_world(world)}"))
            self._ui(lambda: self.status_var.set("Ready. Start to record pairs."))
            self._log(detail)
        except Exception as exc:
            self._close_monitor()
            msg = str(exc)
            self._ui(lambda: self.monitor_var.set(f"monitor: {msg}"))
            self._ui(lambda: self.status_var.set("Monitor not connected"))
            self._log(f"Monitor connect failed: {msg}")

    def _close_monitor(self) -> None:
        with self._lock:
            mon = self._monitor
            self._monitor = None
        if mon is not None:
            try:
                mon.close()
            except Exception:
                pass

    def _on_reconnect(self) -> None:
        threading.Thread(
            target=lambda: self._connect_monitor(start_if_needed=True),
            daemon=True,
        ).start()

    def _parsed_fps(self) -> float:
        try:
            fps = float(self.fps_var.get().strip() or "2")
        except ValueError:
            fps = 2.0
        return max(0.2, min(30.0, fps))

    def _on_start(self) -> None:
        if self._armed.is_set():
            return
        mode = self.mode_var.get().strip() or "space"
        fps = self._parsed_fps()
        self._session = CaptureSession(OUTPUT_DIR, mode=mode, fps=fps)
        self._count = 0
        self.count_var.set("saved: 0")
        self._space_was_down = _key_down(VK_SPACE)
        self._esc_was_down = _key_down(VK_ESCAPE)
        self._armed.set()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.fps_spin.configure(state="disabled")
        self.space_radio.configure(state="disabled")
        self.fps_radio.configure(state="disabled")
        if mode == "space":
            armed = f"recording · Space to capture · session {self._session.dir.name}"
        else:
            armed = f"recording · {fps:g} FPS · session {self._session.dir.name}"
        self.armed_var.set(armed)
        self.status_var.set(armed)
        self._log(f"Started {mode} session → {self._session.dir}")

    def _on_stop(self) -> None:
        if not self._armed.is_set():
            return
        self._armed.clear()
        session = self._session
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.fps_spin.configure(state="normal")
        self.space_radio.configure(state="normal")
        self.fps_radio.configure(state="normal")
        self.armed_var.set("idle")
        folder = session.dir if session is not None else OUTPUT_DIR
        self.status_var.set(f"Stopped. {self._count} pairs in {folder}")
        self._log(f"Stopped. saved={self._count} dir={folder}")

    def _on_once(self) -> None:
        self._once.set()

    def _open_output(self) -> None:
        path = self._session.dir if self._session is not None else OUTPUT_DIR
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Screen vs coordinate", str(exc), parent=self)

    def _grab_frame(self, capture: Any):
        """One mss grab; short retry only if the first read misses."""
        get_frame = getattr(capture, "get_frame", None)
        if not callable(get_frame):
            return None
        frame = get_frame()
        if frame is not None:
            return frame
        for _ in range(6):
            time.sleep(0.01)
            frame = get_frame()
            if frame is not None:
                return frame
        return None

    def _grab_and_save(self, session: CaptureSession):
        with self._lock:
            capture = self._capture
            monitor = self._monitor
        if capture is None:
            self._ui(lambda: self.status_var.set("No capture yet"))
            return None
        t0 = time.perf_counter()
        frame = self._grab_frame(capture)
        t_frame = time.perf_counter()
        snap = None
        snap_error = ""
        if monitor is not None:
            try:
                # player.pos is always current on the cached snapshot; fresh=True
                # forces a heap rescan and can stall for seconds.
                snap = monitor.snapshot(fresh=False)
            except Exception as exc:
                snap_error = str(exc)
                self._log(f"snapshot failed: {exc}")
                self._ui(lambda: self.monitor_var.set(f"monitor: {exc}"))
        else:
            snap_error = "monitor not connected"
        t_snap = time.perf_counter()
        elapsed_ms = (t_snap - t0) * 1000.0
        if frame is None:
            reason = capture_miss_reason(capture)
            self._ui(lambda: self.status_var.set(reason))
            now = time.perf_counter()
            if now - self._last_miss_log >= 2.0:
                self._last_miss_log = now
                self._log(reason)
            return None
        world = player_world_from_snapshot(snap)
        if world is None and not snap_error:
            snap_error = "no player.pos in snapshot"
        rec = session.save_pair(
            frame, snap, world=world, elapsed_ms=elapsed_ms, error=snap_error
        )
        save_ms = (time.perf_counter() - t_snap) * 1000.0
        rec_timing = (
            f"grab {((t_frame - t0) * 1000):.0f}ms  "
            f"coord {((t_snap - t_frame) * 1000):.0f}ms  "
            f"save {save_ms:.0f}ms"
        )
        with self._lock:
            self._last_frame = frame
            self._last_world = world
            self._count = session.index
        self._ui(lambda: self._after_save(rec, elapsed_ms, rec_timing))
        return rec

    def _after_save(self, rec, elapsed_ms: float, timing: str = "") -> None:
        self.count_var.set(f"saved: {rec.index}")
        self.coord_var.set(f"world: {format_world(rec.world)}")
        if rec.ok:
            extra = f"  {timing}" if timing else ""
            self.status_var.set(
                f"#{rec.index}  {format_world(rec.world)}  {elapsed_ms:.0f} ms{extra}  {rec.png_path.name}"
            )
        else:
            self.status_var.set(f"#{rec.index} saved without coord: {rec.error}")
        now = time.perf_counter()
        fps_mode = self._session is not None and self._session.mode == "fps"
        if (not fps_mode) or now - self._last_preview_at >= 0.12:
            self._last_preview_at = now
            self._redraw_preview()

    def _poll_live_coord(self) -> None:
        with self._lock:
            monitor = self._monitor
        if monitor is None:
            return
        try:
            snap = monitor.snapshot(fresh=False)
        except Exception:
            return
        world = player_world_from_snapshot(snap)
        with self._lock:
            self._last_world = world
        self._ui(lambda: self.coord_var.set(f"world: {format_world(world)}"))
        if world:
            self._ui(
                lambda: self.monitor_var.set(f"monitor: connected  {format_world(world)}")
            )

    def _handle_once(self) -> None:
        if self._session is not None and self._armed.is_set():
            session = self._session
            created = False
        else:
            session = CaptureSession(OUTPUT_DIR, mode="once", fps=0.0)
            created = True
        rec = self._grab_and_save(session)
        if rec is not None and created:
            self._log(f"Single capture → {rec.png_path.name}")

    def _loop(self) -> None:
        capture = None
        try:
            try:
                capture = self._open_capture_on_loop_thread()
            except Exception as exc:
                self._ui(lambda: self.status_var.set(f"Capture failed: {exc}"))
                self._log(f"Capture open failed: {exc}")
                return
            self._ui(lambda: self.status_var.set("Ready. Start to record pairs."))
            last_live = 0.0
            next_fps = 0.0
            while not self._stop.is_set() and not self._closing:
                now = time.perf_counter()
                if self._once.is_set():
                    self._once.clear()
                    self._handle_once()
                if _key_down(VK_ESCAPE):
                    if not self._esc_was_down and self._armed.is_set():
                        self._ui(self._on_stop)
                    self._esc_was_down = True
                else:
                    self._esc_was_down = False

                if not self._armed.is_set():
                    if now - last_live >= 0.4:
                        last_live = now
                        self._poll_live_coord()
                    time.sleep(0.03)
                    continue

                session = self._session
                if session is None:
                    time.sleep(0.03)
                    continue

                if session.mode == "space":
                    space = _key_down(VK_SPACE)
                    edge = space and not self._space_was_down
                    self._space_was_down = space
                    if edge and not _our_window_foreground(self._hwnd):
                        self._grab_and_save(session)
                    elif now - last_live >= 0.35:
                        last_live = now
                        self._poll_live_coord()
                    time.sleep(0.012)
                    continue

                fps = max(0.2, float(session.fps) or 2.0)
                if now >= next_fps:
                    self._grab_and_save(session)
                    next_fps = time.perf_counter() + (1.0 / fps)
                else:
                    time.sleep(0.005)
        finally:
            with self._lock:
                if self._capture is capture:
                    self._capture = None
            _close_capture(capture)

    def _redraw_preview(self) -> None:
        frame = self._last_frame
        if frame is None:
            return
        import cv2
        from PIL import Image, ImageTk

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        h, w = frame.shape[:2]
        scale = min(cw / w, ch / h, 1.0)
        dw = max(1, int(round(w * scale)))
        dh = max(1, int(round(h * scale)))
        if dw != w or dh != h:
            small = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA)
        else:
            small = frame
        preview = annotate_frame(small, self._last_world)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(image, master=self)
        self._photo = photo
        self.canvas.delete("all")
        ox = (cw - dw) / 2
        oy = (ch - dh) / 2
        self.canvas.create_image(ox, oy, anchor="nw", image=photo)

    def _ui(self, fn) -> None:
        if self._closing:
            return
        self.after(0, fn)

    def _on_close(self) -> None:
        self._closing = True
        self._armed.clear()
        self._stop.set()
        self._close_monitor()
        self.destroy()


def run_app() -> int:
    app = ScreenVsCoordinateApp()
    app.mainloop()
    return 0
