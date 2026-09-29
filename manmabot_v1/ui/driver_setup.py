"""Modal setup window for the Interception and memory drivers."""
from __future__ import annotations

import threading

import customtkinter as ctk

from manmabot_v1.driver_setup import (
    driver_readiness,
    install_interception_driver,
)
from manmabot_v1.monitor_launch import ensure_monitor_connected


class DriverSetupDialog(ctk.CTkToplevel):
    def __init__(self, master, *, require_ready: bool = True) -> None:
        super().__init__(master)
        self.master_app = master
        self.s = master.s
        self.require_ready = require_ready
        self.ready = False
        self._working = False

        self.title(self.s.drivers_setup)
        self.geometry("480x330")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text=self.s.drivers_setup,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(
            self,
            text=self.s.drivers_setup_hint,
            text_color="gray",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        self.input_status = self._status_row(
            self.s.interception_driver, self._install_input
        )
        self.memory_status = self._status_row(
            self.s.lamp_memory, self._setup_memory
        )

        self.restart_hint = ctk.CTkLabel(
            self, text="", text_color="#eab308", wraplength=430, justify="left"
        )
        self.restart_hint.pack(anchor="w", padx=20, pady=(8, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=20, pady=18)
        self.retry_btn = ctk.CTkButton(
            footer, text=self.s.check_again, width=120, command=self.refresh
        )
        self.retry_btn.pack(side="left")
        self.close_btn = ctk.CTkButton(
            footer,
            text=self.s.species_done,
            width=120,
            command=self._close,
        )
        self.close_btn.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh()

    def _status_row(self, title: str, command):
        row = ctk.CTkFrame(self)
        row.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row, text=title, width=150, anchor="w").pack(
            side="left", padx=12, pady=12
        )
        status = ctk.CTkLabel(row, text="", width=90, anchor="w")
        status.pack(side="left", padx=4)
        button_text = (
            self.s.install_interception
            if title == self.s.interception_driver
            else self.s.setup_memory_reader
        )
        button = ctk.CTkButton(row, text=button_text, width=170, command=command)
        button.pack(side="right", padx=10, pady=8)
        return {"label": status, "button": button}

    def _set_working(self, working: bool) -> None:
        self._working = working
        state = "disabled" if working else "normal"
        for item in (self.input_status, self.memory_status):
            item["button"].configure(state=state)
        self.retry_btn.configure(state=state)
        self.close_btn.configure(state=state)

    def refresh(self) -> None:
        state = driver_readiness()
        self.ready = state.ready
        for ok, detail, item in (
            (state.interception, state.interception_detail, self.input_status),
            (state.memory, state.memory_detail, self.memory_status),
        ):
            item["label"].configure(
                text=self.s.driver_ready if ok else self.s.driver_not_ready,
                text_color="#22c55e" if ok else "#ef4444",
            )
            item["label"].tooltip_text = detail

    def _install_input(self) -> None:
        ok, detail = install_interception_driver(
            log=getattr(self.master_app, "append_log", None)
        )
        self.restart_hint.configure(text=detail if ok else detail)
        self.refresh()

    def _setup_memory(self) -> None:
        if self._working:
            return
        self._set_working(True)
        self.memory_status["label"].configure(text=self.s.wizard_starting_monitor)

        def runner() -> None:
            result = ensure_monitor_connected(
                elevate=True,
                start_driver=True,
                timeout_s=20.0,
                log=getattr(self.master_app, "append_log", None),
            )
            self.after(0, lambda: self._memory_done(result.detail))

        threading.Thread(target=runner, name="driver-setup", daemon=True).start()

    def _memory_done(self, detail: str) -> None:
        self.restart_hint.configure(text=detail)
        self._set_working(False)
        self.refresh()

    def _close(self) -> None:
        if self._working:
            return
        self.grab_release()
        self.destroy()


def show_driver_setup(master, *, require_ready: bool = True) -> bool:
    dialog = DriverSetupDialog(master, require_ready=require_ready)
    master.wait_window(dialog)
    return bool(dialog.ready)
