"""Optional print_state sweep for Tools / research (not the live bot tick).

Live bot uses :class:`PerceptionSensors.capture_tick` instead.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from app._01_perception.print_state_reader import PrintStateReader
from app._03_world.merge.memory_entities import (
    TrackIds,
    align_memory_rows,
    entities_to_handoff,
    load_species_aliases,
    load_species_ids,
    read_last_json_line,
    summarize_shadow,
)


class LiveEntitySweep:
    """One print_state sweep per call. The DLL stays in this process, not LC.exe."""

    def __init__(
        self,
        *,
        log_interval_s: float = 5.0,
        reader: Any = None,
        species_path: Optional[Path] = None,
    ) -> None:
        if reader is None:
            reader = PrintStateReader()
        self.reader = reader
        self.log_interval_s = log_interval_s
        self.species = load_species_ids(species_path)
        self.aliases = load_species_aliases()
        self.ids = TrackIds()
        self._last_log = 0.0

    def poll(
        self,
        vision: list[dict[str, Any]] | None = None,
        now: Optional[float] = None,
        content: Any = None,
    ) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]], Optional[str]]:
        snap = self.reader.snapshot()
        if not isinstance(snap, dict):
            return None, [], None
        rows = entities_to_handoff(
            snap, id_map=self.ids, species=self.species, aliases=self.aliases
        )
        rows = align_memory_rows(rows, snap, content)
        stamp = time.perf_counter() if now is None else now
        line = None
        if stamp - self._last_log >= self.log_interval_s:
            self._last_log = stamp
            line = summarize_shadow(list(vision or []), rows)
        return snap, rows, line

    def close(self) -> None:
        close = getattr(self.reader, "close", None)
        if close is not None:
            close()


class EntityShadow:
    """Read a fresh print_state file and describe it next to vision (tools)."""

    def __init__(
        self,
        path: Path,
        *,
        stale_s: float = 2.0,
        log_interval_s: float = 5.0,
        species_path: Optional[Path] = None,
    ) -> None:
        self.path = Path(path)
        self.stale_s = stale_s
        self.log_interval_s = log_interval_s
        self.species = load_species_ids(species_path)
        self.aliases = load_species_aliases()
        self.ids = TrackIds()
        self._last_log = 0.0

    def observe(
        self,
        vision: list[dict[str, Any]] | None,
        now: Optional[float] = None,
    ) -> Optional[str]:
        stamp = time.perf_counter() if now is None else now
        if stamp - self._last_log < self.log_interval_s:
            return None
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if time.time() - mtime > self.stale_s:
            return None
        snapshot = read_last_json_line(self.path)
        if not snapshot:
            return None
        memory = entities_to_handoff(
            snapshot, id_map=self.ids, species=self.species, aliases=self.aliases
        )
        self._last_log = stamp
        return summarize_shadow(list(vision or []), memory)


__all__ = ["EntityShadow", "LiveEntitySweep"]
