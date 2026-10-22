"""Modal setup window for the Interception and memory drivers."""
from __future__ import annotations

import threading

import customtkinter as ctk

from session.driver_setup import (
    driver_readiness,
    install_interception_driver,
)
from session.monitor_launch import ensure_monitor_connected


class DriverSetupDialog(ctk.CTkToplevel):
    def __init__(self, master, *, require_ready: bool = True) -> None:
        super().__init__(master)
        self.master_app = master
        self.s = master.s
        self.require_ready = require_ready
        self.ready = False
        self._working = False

        self.title(self.s.drivers_setup)
        self.geometry("520x480")
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
        ).pack(anchor="w", padx=20, pady=(0, 8))

        self._profile = getattr(master, "profile", None)
        if self._profile is None:
            from settings.profile import load_profile

            self._profile = load_profile()
        self._loading = True
        ctk.CTkLabel(
            self, text=self.s.hunt_input, font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=20, pady=(4, 2))
        radios = ctk.CTkFrame(self, fg_color="transparent")
        radios.pack(fill="x", padx=20)
        self._backend_var = ctk.StringVar(
            value="pico"
            if str(getattr(self._profile, "input_backend", "")).strip().lower() == "pico"
            else "interception"
        )
        ctk.CTkRadioButton(
            radios,
            text=self.s.hunt_input_interception,
            variable=self._backend_var,
            value="interception",
            command=self._save_choice,
        ).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(
            radios,
            text=self.s.hunt_input_pico,
            variable=self._backend_var,
            value="pico",
            command=self._save_choice,
        ).pack(side="left")
        port_row = ctk.CTkFrame(self, fg_color="transparent")
        port_row.pack(fill="x", padx=20, pady=(6, 4))
        ctk.CTkLabel(port_row, text=self.s.pico_port, width=90, anchor="w").pack(
            side="left"
        )
        self.port_label = ctk.CTkLabel(port_row, text="—", width=160, anchor="w")
        self.port_label.pack(side="left", padx=6)
        self._reload_ports()
        self._loading = False

        self.input_status = self._status_row(
            self.s.interception_driver, self._install_input
        )
        self.pico_status = self._status_row(
            self.s.hunt_input_pico, self._check_pico
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
        if title == self.s.interception_driver:
            button_text = self.s.install_interception
        elif title == self.s.hunt_input_pico:
            button_text = self.s.pico_check
        else:
            button_text = self.s.setup_memory_reader
        button = ctk.CTkButton(row, text=button_text, width=170, command=command)
        button.pack(side="right", padx=10, pady=8)
        return {"label": status, "button": button}

    def _set_working(self, working: bool) -> None:
        self._working = working
        state = "disabled" if working else "normal"
        for item in (self.input_status, self.pico_status, self.memory_status):
            item["button"].configure(state=state)
        self.retry_btn.configure(state=state)
        self.close_btn.configure(state=state)

    def _reload_ports(self) -> None:
        from app._05_action.input_backend import find_pico_data_port

        found = find_pico_data_port()
        self.port_label.configure(text=found or "—")
        self._profile.pico_com = found
        if self._loading:
            return
        try:
            from settings.profile import save_profile

            save_profile(self._profile)
        except Exception:
            pass

    def _save_choice(self) -> None:
        if self._loading:
            return
        from settings.profile import save_profile

        backend = str(self._backend_var.get() or "interception")
        if backend == "pico":
            self._reload_ports()
        if backend == str(getattr(self._profile, "input_backend", "") or ""):
            return
        self._profile.input_backend = backend
        try:
            save_profile(self._profile)
        except Exception as exc:
            self.restart_hint.configure(text=str(exc))
            return
        log = getattr(self.master_app, "append_log", None)
        if callable(log):
            log(self.s.hunt_input_saved)

    def _check_pico(self) -> None:
        self._save_choice()
        self.refresh()

    def refresh(self) -> None:
        state = driver_readiness(self._profile)
        self.ready = state.ready
        for ok, detail, item in (
            (state.interception, state.interception_detail, self.input_status),
            (state.pico, state.pico_detail, self.pico_status),
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
        self._save_choice()
        self.grab_release()
        self.destroy()


def show_driver_setup(master, *, require_ready: bool = True) -> bool:
    dialog = DriverSetupDialog(master, require_ready=require_ready)
    master.wait_window(dialog)
    return bool(dialog.ready)
