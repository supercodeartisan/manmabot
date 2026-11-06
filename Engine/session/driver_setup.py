"""Readiness checks and elevated setup helpers for bot drivers."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Callable, Optional

from session.paths import INTERCEPTION_DIR
from session.probes import Lamp, probe_memory

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class DriverReadiness:
    interception: bool
    memory: bool
    pico: bool
    interception_detail: str
    memory_detail: str
    pico_detail: str
    hunt_backend: str

    @property
    def ready(self) -> bool:
        hunt_ok = self.pico if self.hunt_backend == "pico" else self.interception
        return hunt_ok and self.memory


def interception_ready() -> tuple[bool, str]:
    """Open the Interception device handles without sending any input."""
    try:
        from interception.interception import Interception

        context = Interception()
        try:
            if context.valid:
                return True, "Interception input driver is ready."
            return False, "Interception input driver is not installed."
        finally:
            context.destroy()
    except Exception as exc:
        return False, f"Interception input driver is unavailable: {exc}"


def hunt_input_ready(profile=None) -> tuple[bool, str]:
    """Ready state of the hunt input selected on the profile."""
    from app._05_action.input_backend import probe_pico, resolve_hunt_input

    name, port, baud = resolve_hunt_input(profile)
    if name == "pico":
        return probe_pico(port, baud)
    return interception_ready()


def driver_readiness(profile=None) -> DriverReadiness:
    from app._05_action.input_backend import probe_pico, resolve_hunt_input

    input_ok, input_detail = interception_ready()
    name, port, baud = resolve_hunt_input(profile)
    if name == "pico":
        pico_ok, pico_detail = probe_pico(port, baud)
    else:
        pico_ok, pico_detail = (False, "Hunt input is Interception.")
        if port:
            pico_ok, pico_detail = probe_pico(port, baud)
    memory = probe_memory()
    return DriverReadiness(
        interception=input_ok,
        memory=memory.lamp in (Lamp.GREEN, Lamp.YELLOW),
        pico=pico_ok,
        interception_detail=input_detail,
        memory_detail=memory.detail,
        pico_detail=pico_detail,
        hunt_backend=name,
    )


def install_interception_driver(
    *, log: Optional[LogFn] = None
) -> tuple[bool, str]:
    """Launch the bundled Interception installer as administrator."""
    _log = log or (lambda _message: None)
    installer = (
        INTERCEPTION_DIR
        / "command line installer"
        / "install-interception.exe"
    )
    if not installer.is_file():
        return False, f"Interception installer not found: {installer}"
    try:
        from win32_prototypes import bind_shell32

        bind_shell32(ctypes.windll.shell32)
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(installer),
            "/install",
            str(installer.parent),
            1,
        )
        if int(rc or 0) <= 32:
            return False, f"Interception install failed (ShellExecute={rc})"
        message = "Interception installation requested. Restart Windows before use."
        _log(message)
        return True, message
    except Exception as exc:
        return False, f"Interception install failed: {exc}"
