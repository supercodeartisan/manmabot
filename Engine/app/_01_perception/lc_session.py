"""Background host for the memory-team module DLLs.

Each module is ``analysis/dll/<name>.dll``. It reads
``analysis/registry/LC930_REGISTRY.txt`` and pushes text samples here.
The bot does not open the old listener DLLs.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"
_DLL_DIR = _ANALYSIS / "dll"
_REGISTRY = _ANALYSIS / "registry" / "LC930_REGISTRY.txt"

# interval_ms, optional extra KEY=VALUE params (registry names).
_MODULES: dict[str, tuple[int, str]] = {
    "charread": (100, ""),
    "map": (200, ""),
    "enttrack": (100, "ENT_SWEEP_MS=400;ENT_READ_INTERVAL_MS=100"),
    "bodyact": (50, ""),
    "inventory": (500, ""),
    "hotbar": (400, ""),
    "shop": (400, ""),
    "buff": (300, ""),
    "uidialogmon": (200, ""),
    "party": (300, ""),
}

_SINK = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_char_p,
    ctypes.c_uint32,
)


class _Slot:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.text = ""
        self.error = ""
        self.ready = threading.Event()
        self.waited = False


class LcSession:
    """One process-wide set of module threads."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._slots: dict[str, _Slot] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._held: dict[str, object] = {}

    def ensure(self, name: str) -> None:
        spec = _MODULES.get(name)
        if spec is None:
            raise KeyError(name)
        dll = _DLL_DIR / f"{name}.dll"
        if not dll.is_file():
            raise FileNotFoundError(f"memory module DLL is missing: {dll}")
        if not _REGISTRY.is_file():
            raise FileNotFoundError(f"registry is missing: {_REGISTRY}")
        os.environ["LCAPI_ROOT"] = str(_ANALYSIS)
        with self._guard:
            self._stop.clear()
            thread = self._threads.get(name)
            if thread is not None and thread.is_alive():
                return
            slot = self._slots.setdefault(name, _Slot())
            thread = threading.Thread(
                target=self._run,
                name=f"lc-{name}",
                args=(name, dll, spec, slot),
                daemon=True,
            )
            self._threads[name] = thread
            thread.start()

    def text(self, name: str) -> str:
        """Latest sample. Starts the module if its DLL is present.

        The first call waits once so a cold start still returns a sample.
        Later calls return whatever the module has already pushed.
        """
        self.ensure(name)
        slot = self._slots.get(name)
        if slot is None:
            return ""
        if not slot.ready.is_set() and not slot.waited:
            slot.waited = True
            slot.ready.wait(1.5)
        with slot.lock:
            return slot.text

    def peek(self, name: str) -> str:
        """Latest sample without starting a module."""
        slot = self._slots.get(name)
        if slot is None:
            return ""
        with slot.lock:
            return slot.text

    def stop(self) -> None:
        """Ask running modules to end after the current sample."""
        self._stop.set()

    def _run(self, name: str, dll: Path, spec: tuple[int, str], slot: _Slot) -> None:
        os.environ["LCAPI_ROOT"] = str(_ANALYSIS)
        interval, params = spec
        lib = ctypes.CDLL(str(dll))
        configure = lib.lcapi_configure
        configure.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_char_p,
        ]
        configure.restype = ctypes.c_int
        set_params = getattr(lib, "lcapi_set_params", None)
        if set_params is not None:
            set_params.argtypes = [ctypes.c_char_p]
            set_params.restype = ctypes.c_int
        run = lib.lcapi_run
        run.argtypes = [_SINK, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        run.restype = ctypes.c_int
        registry = str(_REGISTRY).encode("utf-8")
        param_bytes = params.encode("utf-8") if params else None

        @_SINK
        def sink(_ctx, _seq, text, length):
            if text and length:
                raw = ctypes.string_at(text, int(length))
                decoded = raw.decode("utf-8", "replace")
            else:
                decoded = ""
            with slot.lock:
                slot.text = decoded
                slot.error = ""
            slot.ready.set()
            return 1 if self._stop.is_set() else 0

        self._held[name] = (lib, sink)
        err = ctypes.create_string_buffer(512)
        while not self._stop.is_set():
            configure(registry, int(interval), 0, 100000, None)
            if set_params is not None and param_bytes:
                set_params(param_bytes)
            err[0] = 0
            rc = int(run(sink, None, err, len(err)))
            if self._stop.is_set():
                break
            message = err.value.decode("utf-8", "replace") or f"module rc={rc}"
            with slot.lock:
                slot.error = message
            time.sleep(1.0)


class ModuleReader:
    """Reader facade. ``module`` is the DLL name; ``_read`` returns the snapshot."""

    module = ""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._closed = False
        self._loaded = False
        try:
            session.ensure(self.module)
            self._loaded = True
        except Exception:
            self._loaded = False

    @property
    def dll_loaded(self) -> bool:
        return self._loaded and not self._closed

    def snapshot(self, fresh: bool = False) -> object:
        del fresh
        if not self.dll_loaded:
            return None
        return self._read()

    def snapshot_fresh(self) -> object:
        return self.snapshot(fresh=True)

    def close(self) -> None:
        self._closed = True

    def _read(self) -> object:
        raise NotImplementedError(self.module)


session = LcSession()
