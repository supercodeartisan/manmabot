"""Load the in-process player monitor without importing the engine package."""
from __future__ import annotations

import importlib.util
import sys
from typing import Any

from manmabot_v1.paths import manmabot_root

_MODULE_NAME = "manmabot_realtime_monitor_reader"


def reader_module() -> Any:
    loaded = sys.modules.get(_MODULE_NAME)
    if loaded is not None:
        return loaded
    path = manmabot_root() / "app" / "_03_world" / "realtime_monitor_reader.py"
    if not path.is_file():
        raise FileNotFoundError(f"realtime monitor reader is missing: {path}")
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def shared_monitor() -> Any:
    return reader_module().shared_monitor()


def shutdown_shared_monitor() -> None:
    reader_module().shutdown_shared_monitor()
