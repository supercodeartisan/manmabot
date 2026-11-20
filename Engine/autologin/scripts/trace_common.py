"""Shared utilities for the autologin live diagnostics.

Everything here is deliberately dependency-light so the trace writer can be
imported before the bot (and before Interception/OCR) is initialized.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable

# --- paths -----------------------------------------------------------------

def repo_root() -> Path:
    # Engine/autologin/scripts/trace_common.py -> repo root
    return Path(__file__).resolve().parents[3]


def engine_dir() -> Path:
    return repo_root() / "Engine"


def bot_dir() -> Path:
    return engine_dir() / "autologin" / "bot"


def default_trace_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    return Path(base) / "Manmabot" / "autologin_trace"


def new_trace_dir() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = default_trace_root() / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_python() -> Path | None:
    """The product's bundled interpreter, when this is a dev/portable tree."""
    candidate = repo_root() / "python" / "python.exe"
    return candidate if candidate.is_file() else None


def _missing_deps() -> list[str]:
    import importlib.util
    missing: list[str] = []
    for module in ("numpy", "cv2", "PIL", "psutil", "onnxruntime", "winrt"):
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):
            missing.append(module)
    return missing


def maybe_reexec() -> int | None:
    """Relaunch with the bundled Python when the current one lacks bot deps.

    Returns the child exit code when a relaunch happened, or ``None`` when the
    current interpreter is already suitable. The elevation token is inherited
    by the child process.
    """
    if os.environ.get("AUTOLOGIN_NO_REEXEC"):
        return None
    bundled = bundled_python()
    if bundled is None:
        return None
    try:
        if Path(sys.executable).resolve() == bundled.resolve():
            return None
    except OSError:
        pass
    missing = _missing_deps()
    if not missing:
        return None
    import subprocess
    env = dict(os.environ)
    env["AUTOLOGIN_NO_REEXEC"] = "1"
    args = [str(bundled), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    print(
        "relaunch with bundled python %s (missing: %s)"
        % (bundled, ", ".join(missing)),
        flush=True,
    )
    try:
        return int(subprocess.call(args, env=env))
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print("relaunch failed: %r" % exc, flush=True)
        return 2


# --- redaction -------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/=_\-]{28,}\b")


def redact(text: Any) -> str:
    """Mask account identifiers and secret-looking tokens in trace text."""
    if text is None:
        return ""
    value = _EMAIL_RE.sub("***@***", str(text))
    value = _LONG_TOKEN_RE.sub("***", value)
    return value


# --- hashing ---------------------------------------------------------------

def sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        return "error:%s" % exc


def hash_tree(paths: Iterable[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in paths:
        root = Path(root)
        if root.is_file():
            out[str(root)] = sha256_file(root)
            continue
        if not root.is_dir():
            out[str(root)] = "missing"
            continue
        for item in sorted(root.rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts:
                out[str(item)] = sha256_file(item)
    return out


def diff_hashes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    changed = [k for k in before if k in after and before[k] != after[k]]
    missing = [k for k in before if k not in after]
    added = [k for k in after if k not in before]
    return {"changed": changed, "missing": missing, "added": added}


# --- json helpers ----------------------------------------------------------

def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


# --- trace -----------------------------------------------------------------

def _iso(wall: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(wall)) + (
        ".%03d" % int((wall % 1.0) * 1000)
    )


class Trace:
    """Thread-safe JSONL event writer with a monotonic clock shared by the
    screen recorder (ts is seconds since trace start)."""

    def __init__(self, out_dir: Path | str, name: str = "trace.jsonl") -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.out_dir / name
        self._lock = threading.Lock()
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        self.t0 = time.monotonic()
        self.t0_wall = time.time()
        self.seq = 0
        self.tick = 0
        self.video_frame: int | None = None
        self.run_id = self.out_dir.name

    def mono(self) -> float:
        return time.monotonic()

    def elapsed(self, mono: float | None = None) -> float:
        return round((mono if mono is not None else time.monotonic()) - self.t0, 4)

    def event(self, layer: str, event: str, **fields: Any) -> dict:
        mono = time.monotonic()
        wall = time.time()
        with self._lock:
            self.seq += 1
            record: dict[str, Any] = {
                "seq": self.seq,
                "ts": round(mono - self.t0, 4),
                "iso": _iso(wall),
                "run": self.run_id,
                "tick": self.tick,
                "layer": layer,
                "event": event,
            }
            if self.video_frame is not None:
                record["video_frame"] = self.video_frame
            record.update(fields)
            self._fh.write(
                json.dumps(record, ensure_ascii=False, default=str) + "\n"
            )
        return record

    def span(self, layer: str, event: str, started: float, **fields: Any) -> dict:
        fields["duration_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        return self.event(layer, event, **fields)

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass
