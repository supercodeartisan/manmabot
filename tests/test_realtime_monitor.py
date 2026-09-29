"""In-process player monitor wiring. Does not attach to LC.exe."""
from __future__ import annotations

import ctypes
from pathlib import Path


def test_open_monitor_skips_when_disabled() -> None:
    from app._03_world.memory_client import open_monitor_from_config

    assert open_monitor_from_config({"memory": {"enabled": False}}) is None


def test_realtime_monitor_dll_exports_and_offsets_path() -> None:
    from manmabot_v1.player_monitor import reader_module

    reader = reader_module()
    offsets = reader.default_offsets_path()
    dll = reader.default_dll_path()
    assert offsets.name == "offsets.json"
    assert offsets.is_file()
    assert dll.is_file()
    lib = ctypes.WinDLL(str(dll))
    assert hasattr(lib, "realtime_monitor_snapshot")
    assert hasattr(lib, "realtime_monitor_shutdown")
    assert Path(str(offsets)).parent == dll.parent
