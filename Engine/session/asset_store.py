"""In-memory view of a customer ``Engine/data.pack``.

Dev trees keep a real ``Engine/data`` folder and never mount this store.
Customer builds have no ``Engine/data`` directory. Path, os, PIL, and cv2
reads under the mount root are served from RAM so map PNGs are not written
to disk.
"""
from __future__ import annotations

import builtins
import ctypes
import io
import os
from pathlib import Path, PurePosixPath
from typing import Iterator

_FILES: dict[str, bytes] = {}
_DIRS: set[str] = set()
_ROOT: Path | None = None
_ROOT_ABS = ""
_ROOT_KEY = ""
_ACTIVE = False
_HOOKS = False
# A list cell, not a bool: Nuitka can fold a module-level bool and then the
# re-entry guard never trips inside the compiled .pyd.
_BUSY = [False]
_LONG_CACHE: dict[str, str] = {}

_orig_path_is_file = Path.is_file
_orig_path_is_dir = Path.is_dir
_orig_path_exists = Path.exists
_orig_path_iterdir = Path.iterdir
_orig_path_open = Path.open
_orig_path_read_bytes = Path.read_bytes
_orig_path_read_text = Path.read_text
_orig_path_stat = Path.stat
_orig_path_glob = Path.glob
_orig_path_rglob = Path.rglob
_orig_listdir = os.listdir
_orig_scandir = os.scandir
_orig_walk = os.walk
_orig_isfile = os.path.isfile
_orig_isdir = os.path.isdir
_orig_exists = os.path.exists
_orig_open = builtins.open


class _Stat:
    def __init__(self, size: int, *, is_dir: bool) -> None:
        self.st_size = size
        self.st_mode = 0o040755 if is_dir else 0o100644
        self.st_mtime = 0
        self.st_atime = 0
        self.st_ctime = 0

    def __getattr__(self, name: str) -> int:
        if name.startswith("st_"):
            return 0
        raise AttributeError(name)


class _DirEntry:
    def __init__(self, parent: Path, name: str, *, is_file: bool) -> None:
        self.name = name
        self.path = os.fspath(parent / name)
        self._is_file = is_file

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return self._is_file

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return not self._is_file

    def is_symlink(self) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool = True) -> _Stat:
        rel = _under(Path(self.path))
        size = len(_FILES[rel]) if rel in _FILES else 0
        return _Stat(size, is_dir=not self._is_file)


def _strip_extended(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _kernel_long(path: str) -> str | None:
    """Long path for an existing file or directory. Missing paths return None."""
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetLongPathNameW(path, buf, len(buf))
    if not n or n >= len(buf):
        return None
    return _strip_extended(buf.value)


def _kernel_final(path: str) -> str | None:
    """Canonical path, so a share and a mapped drive for it compare equal."""
    kernel = ctypes.windll.kernel32
    handle = kernel.CreateFileW(
        path,
        0,
        7,
        None,
        3,
        0x02000000,
        None,
    )
    if handle in (-1, 0xFFFFFFFF):
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = kernel.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not n or n >= len(buf):
            return None
        return _strip_extended(buf.value)
    finally:
        kernel.CloseHandle(handle)


def _existing_canonical(path: str) -> str | None:
    return _kernel_final(path) or _kernel_long(path)


def _expand_short(path: str) -> str:
    """Make local, 8.3, and ``\\\\server\\share`` forms of one folder match.

    Packed files under ``Engine/data`` are not on disk, so the API is applied
    to the nearest existing parent and the missing tail is appended.
    """
    text = os.path.normpath(_strip_extended(path))
    key = os.path.normcase(text)
    hit = _LONG_CACHE.get(key)
    if hit is not None:
        return hit
    found = _existing_canonical(text)
    if found:
        result = os.path.normpath(found)
        _LONG_CACHE[key] = result
        return result
    tail: list[str] = []
    current = text
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            break
        tail.append(os.path.basename(current))
        current = parent
        found = _existing_canonical(current)
        if not found:
            continue
        result = os.path.normpath(found)
        for part in reversed(tail):
            result = os.path.normpath(os.path.join(result, part))
        _LONG_CACHE[key] = result
        return result
    _LONG_CACHE[key] = text
    return text


def _plain_abs(path: Path | str) -> str:
    """Absolute path without ``os.path.abspath``.

    On Python 3.14, ``os.path.abspath`` calls ``os.path.isdir``. After the
    hooks are installed that re-enters ``_under`` and overflows the stack.
    Short 8.3 paths are expanded so they match the long mount root.
    """
    text = os.fspath(path)
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not os.path.isabs(text):
        text = os.path.join(os.getcwd(), text)
    return _expand_short(os.path.normpath(text))


def _under(path: Path | str) -> str | None:
    """Posix path relative to the mount root, or None when the store is off."""
    root_abs = _ROOT_ABS
    if _BUSY[0] or not _ACTIVE or not root_abs:
        return None
    _BUSY[0] = True
    try:
        try:
            full = _plain_abs(path)
        except (OSError, ValueError, TypeError):
            return None
        full_key = os.path.normcase(full)
        base_key = _ROOT_KEY
        if full_key == base_key:
            return ""
        prefix = base_key + os.path.normcase(os.sep)
        if not full_key.startswith(prefix):
            return None
        return full[len(root_abs) :].lstrip("\\/").replace("\\", "/")
    finally:
        _BUSY[0] = False


def _child_names(rel: str) -> tuple[list[str], list[str]]:
    prefix = f"{rel}/" if rel else ""
    dirs: set[str] = set()
    files: set[str] = set()
    for directory in _DIRS:
        if directory == rel or not directory.startswith(prefix):
            continue
        rest = directory[len(prefix) :]
        if rest and "/" not in rest:
            dirs.add(rest)
    for name in _FILES:
        if rel == "":
            if "/" not in name:
                files.add(name)
            else:
                dirs.add(name.split("/", 1)[0])
            continue
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        if not rest:
            continue
        if "/" in rest:
            dirs.add(rest.split("/", 1)[0])
        else:
            files.add(rest)
    return sorted(dirs), sorted(files)


def _matches(relative: str, pattern: str) -> bool:
    return PurePosixPath(relative).full_match(pattern)


def _iter_rel(base_rel: str) -> Iterator[str]:
    prefix = f"{base_rel}/" if base_rel else ""
    seen: set[str] = set()
    for directory in _DIRS:
        if directory == base_rel:
            continue
        if base_rel and not directory.startswith(prefix):
            continue
        if directory not in seen:
            seen.add(directory)
            yield directory
    for name in _FILES:
        if base_rel and not name.startswith(prefix):
            continue
        if name not in seen:
            seen.add(name)
            yield name


def _virtual_iter(base: Path, base_rel: str, pattern: str) -> Iterator[Path]:
    prefix = f"{base_rel}/" if base_rel else ""
    for rel in sorted(_iter_rel(base_rel)):
        child = rel[len(prefix) :] if prefix else rel
        if child and _matches(child, pattern):
            yield base / child


def _read_mode(mode: str) -> bool:
    text = str(mode or "r")
    return "w" not in text and "a" not in text and "+" not in text


def _path_is_file(self: Path) -> bool:
    rel = _under(self)
    if rel is None:
        return _orig_path_is_file(self)
    return rel in _FILES


def _path_is_dir(self: Path) -> bool:
    rel = _under(self)
    if rel is None:
        return _orig_path_is_dir(self)
    return rel in _DIRS


def _path_exists(self: Path) -> bool:
    rel = _under(self)
    if rel is None:
        return _orig_path_exists(self)
    return rel in _FILES or rel in _DIRS


def _path_iterdir(self: Path) -> Iterator[Path]:
    rel = _under(self)
    if rel is None or rel not in _DIRS:
        return _orig_path_iterdir(self)
    dirs, files = _child_names(rel)
    return iter([self / name for name in dirs + files])


def _path_open(self: Path, mode: str = "r", buffering: int = -1, encoding=None, errors=None, newline=None):
    rel = _under(self)
    if rel is not None and rel in _FILES and _read_mode(mode):
        data = _FILES[rel]
        if "b" in str(mode):
            return io.BytesIO(data)
        return io.StringIO(data.decode(encoding or "utf-8", errors or "strict"))
    return _orig_path_open(
        self, mode, buffering, encoding=encoding, errors=errors, newline=newline
    )


def _path_read_bytes(self: Path) -> bytes:
    rel = _under(self)
    if rel is not None and rel in _FILES:
        return _FILES[rel]
    return _orig_path_read_bytes(self)


def _path_read_text(self: Path, encoding=None, errors=None, newline=None) -> str:
    rel = _under(self)
    if rel is not None and rel in _FILES:
        return _FILES[rel].decode(encoding or "utf-8", errors or "strict")
    return _orig_path_read_text(self, encoding, errors, newline)


def _path_stat(self: Path, *, follow_symlinks: bool = True):
    rel = _under(self)
    if rel is not None and rel in _FILES:
        return _Stat(len(_FILES[rel]), is_dir=False)
    if rel is not None and rel in _DIRS:
        return _Stat(0, is_dir=True)
    return _orig_path_stat(self, follow_symlinks=follow_symlinks)


def _path_glob(self: Path, pattern: str, *, case_sensitive=None, recurse_symlinks: bool = False):
    rel = _under(self)
    if rel is None or rel not in _DIRS:
        return _orig_path_glob(
            self, pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks
        )
    return _virtual_iter(self, rel, pattern.replace("\\", "/"))


def _path_rglob(self: Path, pattern: str, *, case_sensitive=None, recurse_symlinks: bool = False):
    rel = _under(self)
    if rel is None or rel not in _DIRS:
        return _orig_path_rglob(
            self, pattern, case_sensitive=case_sensitive, recurse_symlinks=recurse_symlinks
        )
    pat = pattern.replace("\\", "/")
    if not pat.startswith("**/"):
        pat = "**/" + pat
    return _virtual_iter(self, rel, pat)


def _os_isfile(path, _orig=_orig_isfile) -> bool:
    # Default arg keeps the pre-hook function. Nuitka otherwise calls the
    # patched os.path.isfile and overflows.
    if _BUSY[0]:
        return _orig(path)
    rel = _under(path)
    if rel is None:
        return _orig(path)
    return rel in _FILES


def _os_isdir(path, _orig=_orig_isdir) -> bool:
    if _BUSY[0]:
        return _orig(path)
    rel = _under(path)
    if rel is None:
        return _orig(path)
    return rel in _DIRS


def _os_exists(path, _orig=_orig_exists) -> bool:
    if _BUSY[0]:
        return _orig(path)
    rel = _under(path)
    if rel is None:
        return _orig(path)
    return rel in _FILES or rel in _DIRS


def _os_listdir(path):
    rel = _under(path)
    if rel is None or rel not in _DIRS:
        return _orig_listdir(path)
    dirs, files = _child_names(rel)
    return dirs + files


def _os_scandir(path):
    rel = _under(path)
    if rel is None or rel not in _DIRS:
        return _orig_scandir(path)
    parent = Path(path)
    dirs, files = _child_names(rel)
    entries = [_DirEntry(parent, name, is_file=False) for name in dirs]
    entries.extend(_DirEntry(parent, name, is_file=True) for name in files)
    return iter(entries)


def _os_walk(top, topdown: bool = True, onerror=None, followlinks: bool = False):
    rel = _under(top)
    if rel is None or rel not in _DIRS:
        return _orig_walk(top, topdown, onerror, followlinks)
    base = Path(top)

    def _recurse(directory: Path, directory_rel: str):
        dirs, files = _child_names(directory_rel)
        yield os.fspath(directory), dirs, files
        for name in dirs:
            child_rel = f"{directory_rel}/{name}" if directory_rel else name
            yield from _recurse(directory / name, child_rel)

    return _recurse(base, rel)


def _builtin_open(file, mode="r", *args, **kwargs):
    if _read_mode(str(mode)) and not hasattr(file, "read"):
        rel = _under(file)
        if rel is not None and rel in _FILES:
            data = _FILES[rel]
            if "b" in str(mode):
                return io.BytesIO(data)
            encoding = kwargs.get("encoding") or "utf-8"
            errors = kwargs.get("errors") or "strict"
            return io.StringIO(data.decode(encoding, errors))
    return _orig_open(file, mode, *args, **kwargs)


def _install_hooks() -> None:
    global _HOOKS
    if _HOOKS:
        return
    Path.is_file = _path_is_file  # type: ignore[method-assign]
    Path.is_dir = _path_is_dir  # type: ignore[method-assign]
    Path.exists = _path_exists  # type: ignore[method-assign]
    Path.iterdir = _path_iterdir  # type: ignore[method-assign]
    Path.open = _path_open  # type: ignore[method-assign]
    Path.read_bytes = _path_read_bytes  # type: ignore[method-assign]
    Path.read_text = _path_read_text  # type: ignore[method-assign]
    Path.stat = _path_stat  # type: ignore[method-assign]
    Path.glob = _path_glob  # type: ignore[method-assign]
    Path.rglob = _path_rglob  # type: ignore[method-assign]
    os.listdir = _os_listdir  # type: ignore[assignment]
    os.scandir = _os_scandir  # type: ignore[assignment]
    os.walk = _os_walk  # type: ignore[assignment]
    os.path.isfile = _os_isfile  # type: ignore[assignment]
    os.path.isdir = _os_isdir  # type: ignore[assignment]
    os.path.exists = _os_exists  # type: ignore[assignment]
    builtins.open = _builtin_open  # type: ignore[assignment]
    _patch_pil()
    _patch_cv2()
    _HOOKS = True


def _patch_pil() -> None:
    try:
        from PIL import Image
    except Exception:
        return
    orig = Image.open

    def open(fp, mode="r", formats=None):
        if not hasattr(fp, "read"):
            rel = _under(fp)
            if rel is not None and rel in _FILES:
                fp = io.BytesIO(_FILES[rel])
        return orig(fp, mode, formats)

    Image.open = open  # type: ignore[assignment]


def _patch_cv2() -> None:
    try:
        import cv2
    except Exception:
        return
    if getattr(cv2.imread, "_manmabot_asset", False):
        return
    orig = cv2.imread

    def imread(filename, flags=None):
        rel = _under(filename)
        if rel is not None and rel in _FILES:
            import numpy as np

            buf = np.frombuffer(_FILES[rel], dtype=np.uint8)
            flag = cv2.IMREAD_COLOR if flags is None else flags
            return cv2.imdecode(buf, flag)
        if flags is None:
            return orig(filename)
        return orig(filename, flags)

    imread._manmabot_asset = True  # type: ignore[attr-defined]
    cv2.imread = imread


def mount_bytes(root: Path, files: dict[str, bytes]) -> dict:
    """Serve ``files`` as ``root`` (the ``Engine/data`` directory)."""
    global _FILES, _DIRS, _ROOT, _ROOT_ABS, _ROOT_KEY, _ACTIVE
    dirs = {""}
    for rel in files:
        parts = rel.split("/")
        for index in range(1, len(parts)):
            dirs.add("/".join(parts[:index]))
    _FILES = dict(files)
    _DIRS = dirs
    _ROOT = root
    _ROOT_ABS = _plain_abs(root)
    _ROOT_KEY = os.path.normcase(_ROOT_ABS)
    _ACTIVE = True
    _install_hooks()
    return {"files": len(files), "root": str(root), "mode": "memory"}


def is_mounted() -> bool:
    return _ACTIVE
