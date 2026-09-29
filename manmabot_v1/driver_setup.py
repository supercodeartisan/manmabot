"""Readiness checks and elevated setup helpers for bot drivers."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Callable, Optional

from manmabot_v1.paths import app_root
from manmabot_v1.probes import Lamp, probe_memory

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class DriverReadiness:
    interception: bool
    memory: bool
    interception_detail: str
    memory_detail: str

    @property
    def ready(self) -> bool:
        return self.interception and self.memory


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


def driver_readiness() -> DriverReadiness:
    input_ok, input_detail = interception_ready()
    memory = probe_memory()
    return DriverReadiness(
        interception=input_ok,
        memory=memory.lamp in (Lamp.GREEN, Lamp.YELLOW),
        interception_detail=input_detail,
        memory_detail=memory.detail,
    )


def install_interception_driver(
    *, log: Optional[LogFn] = None
) -> tuple[bool, str]:
    """Launch the bundled Interception installer as administrator."""
    _log = log or (lambda _message: None)
    installer = (
        app_root()
        / "Interception"
        / "command line installer"
        / "install-interception.exe"
    )
    if not installer.is_file():
        return False, f"Interception installer not found: {installer}"
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(installer),
            "/install",
            str(installer.parent),
            1,
        )
        if int(rc) <= 32:
            return False, f"Interception install failed (ShellExecute={rc})"
        message = "Interception installation requested. Restart Windows before use."
        _log(message)
        return True, message
    except Exception as exc:
        return False, f"Interception install failed: {exc}"
