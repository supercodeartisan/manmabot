"""Background thumbnails for the sell table.

The table paints names first. File lookup and PNG decode run on a small
thread pool. Results return through a signal and are applied on the UI thread.
"""
from __future__ import annotations

import threading
from collections import OrderedDict, deque
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from ui_qt.icon_helpers import HUNT_ICON_SIZE, hunt_qimage

_CACHE_MAX = 1024
_WORKERS = 2
_template_lock = threading.Lock()
_template_index: dict[str, Path | None] | None = None


class _Epoch:
    def __init__(self) -> None:
        self.generation = 0
        self.alive = True


class _Bridge(QObject):
    ready = Signal(int, str, QImage, str, str)


def _file_token(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        if not path.is_file():
            return ""
        stat = path.stat()
    except OSError:
        return ""
    return f"{path}|{stat.st_mtime_ns}|{stat.st_size}"


def _hotbar_template_index() -> dict[str, Path | None]:
    """One walk of the hotbar item folders, shared by every sell-icon job."""
    global _template_index
    if _template_index is not None:
        return _template_index
    with _template_lock:
        if _template_index is not None:
            return _template_index
        index: dict[str, Path | None] = {}
        try:
            from hotbar.item_catalog import list_item_templates, template_abs_path

            for entry in list_item_templates(pack="hotbar"):
                name = str(entry.kr_name or "").strip()
                if not name or name in index:
                    continue
                try:
                    path = template_abs_path(entry.template, pack="hotbar")
                except Exception:
                    path = None
                index[name] = path if path is not None and path.is_file() else None
        except Exception:
            index = {}
        _template_index = index
        return index


def resolve_sell_icon_path(names: Iterable[str], ids: Iterable[int]) -> Path | None:
    """Same match as ``item_image_path``: official list PNG, then hotbar template.

    The hotbar walk happens once per process. A missing file returns None.
    """
    try:
        from app._03_world.catalog.game_catalog import resolve_catalog_image

        found = resolve_catalog_image("item", names, ids)
    except Exception:
        found = None
    if found is not None:
        return found
    index = _hotbar_template_index()
    seen: set[str] = set()
    for raw in names:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        path = index.get(text)
        if path is not None and path.is_file():
            return path
    return None


class _IconTask(QRunnable):
    def __init__(
        self,
        generation: int,
        key: str,
        names: tuple[str, ...],
        ids: tuple[int, ...],
        bridge: _Bridge,
        epoch: _Epoch,
    ) -> None:
        super().__init__()
        self.generation = int(generation)
        self.key = str(key)
        self.names = names
        self.ids = ids
        self.bridge = bridge
        self.epoch = epoch
        self.setAutoDelete(True)

    def run(self) -> None:
        if not self.epoch.alive or self.epoch.generation != self.generation:
            return
        path: Path | None = None
        try:
            path = resolve_sell_icon_path(self.names, self.ids)
            qimage = hunt_qimage(path, enabled=True, size=HUNT_ICON_SIZE)
        except Exception:
            path = None
            try:
                qimage = hunt_qimage(None, enabled=True, size=HUNT_ICON_SIZE)
            except Exception:
                return
        if not self.epoch.alive or self.epoch.generation != self.generation:
            return
        self.bridge.ready.emit(
            self.generation,
            self.key,
            qimage,
            str(path) if path is not None else "",
            _file_token(path),
        )


class SellIconLoader(QObject):
    """Decode sell thumbnails off the UI thread and cache the pixmaps."""

    updated = Signal(str, QPixmap)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._epoch = _Epoch()
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._on_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(_WORKERS)
        self._cache: OrderedDict[str, tuple[str, QPixmap]] = OrderedDict()
        self._paths: dict[str, str] = {}
        self._jobs: dict[str, tuple[tuple[str, ...], tuple[int, ...]]] = {}
        self._pending: deque[str] = deque()
        self._pending_set: set[str] = set()
        self._inflight: dict[str, int] = {}
        self.rest_queued = False
        self._placeholder: QPixmap | None = None
        self.applied = 0

    @property
    def generation(self) -> int:
        return int(self._epoch.generation)

    def placeholder(self) -> QPixmap:
        if self._placeholder is None:
            from ui_qt.icon_helpers import hunt_icon

            self._placeholder = hunt_icon(None)
        return self._placeholder

    def remember(self, key: str, names: Iterable[str], ids: Iterable[int]) -> None:
        text = str(key or "").strip()
        if not text:
            return
        clean_names = tuple(str(name).strip() for name in names if str(name or "").strip())
        clean_ids: list[int] = []
        for raw in ids:
            try:
                clean_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        self._jobs[text] = (clean_names, tuple(clean_ids))

    def cached(self, key: str) -> QPixmap | None:
        text = str(key or "")
        slot = self._cache.get(text)
        if slot is None:
            return None
        token, pixmap = slot
        path_text = self._paths.get(text, "")
        if path_text:
            current = _file_token(Path(path_text))
            if current != token:
                self._cache.pop(text, None)
                self._paths.pop(text, None)
                return None
        self._cache.move_to_end(text)
        return pixmap

    def cancel(self) -> None:
        """Drop queued work. A finished job from the old pass is ignored."""
        self._epoch.generation += 1
        self._pending.clear()
        self._pending_set.clear()
        self._inflight.clear()
        self.rest_queued = False

    def shutdown(self) -> None:
        self._epoch.alive = False
        self.cancel()

    def idle(self) -> bool:
        return not self._pending and not self._inflight

    def enqueue(self, keys: Iterable[str], *, front: bool = False) -> None:
        ordered = [str(key) for key in keys if str(key or "").strip()]
        if front:
            ordered.reverse()
        for key in ordered:
            if key in self._inflight or self.cached(key) is not None:
                continue
            if key not in self._jobs:
                continue
            if key in self._pending_set:
                if not front:
                    continue
                self._pending.remove(key)
            if front:
                self._pending.appendleft(key)
            else:
                self._pending.append(key)
            self._pending_set.add(key)
        self._pump()

    def _pump(self) -> None:
        generation = self._epoch.generation
        while len(self._inflight) < _WORKERS and self._pending:
            if generation != self._epoch.generation:
                return
            key = self._pending.popleft()
            self._pending_set.discard(key)
            if key in self._inflight or self.cached(key) is not None:
                continue
            names, ids = self._jobs.get(key, ((), ()))
            self._inflight[key] = generation
            self._pool.start(
                _IconTask(generation, key, names, ids, self._bridge, self._epoch)
            )

    def _store(self, key: str, token: str, pixmap: QPixmap) -> None:
        self._cache[key] = (token, pixmap)
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_MAX:
            old, _slot = self._cache.popitem(last=False)
            self._paths.pop(old, None)

    def _on_ready(self, generation: int, key: str, image: QImage, path: str, token: str) -> None:
        if self._inflight.get(key) == int(generation):
            self._inflight.pop(key, None)
        if not self._epoch.alive or int(generation) != self._epoch.generation:
            self._pump()
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            pixmap = self.placeholder()
        if path:
            self._paths[key] = path
        else:
            self._paths.pop(key, None)
        self._store(key, token, pixmap)
        self.applied += 1
        self.updated.emit(key, pixmap)
        self._pump()
