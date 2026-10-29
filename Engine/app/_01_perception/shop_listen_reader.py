"""Shop Buy/Sell lists from the shop module."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader

_DLL = Path(__file__).resolve().parents[2] / "analysis" / "dll" / "shop.dll"
_LOCK = threading.Lock()
_SHARED: Optional["ShopListenReader"] = None
_LAST_SHOP_SNAPSHOT: Optional[dict[str, Any]] = None
_LAST_SHOP_SNAPSHOT_AT: float = 0.0


def default_dll_path() -> Path:
    return _DLL


class ShopListenReader(ModuleReader):
    module = "shop"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import shop

        data = shop()
        if not isinstance(data, dict):
            return None
        global _LAST_SHOP_SNAPSHOT, _LAST_SHOP_SNAPSHOT_AT
        _LAST_SHOP_SNAPSHOT = data
        _LAST_SHOP_SNAPSHOT_AT = time.monotonic()
        return data


def shared_shop() -> ShopListenReader:
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = ShopListenReader()
        return _SHARED


def last_shop_snapshot() -> Optional[dict[str, Any]]:
    """Most recent successful ``snapshot()`` dict (Debug sell table; not live)."""
    return _LAST_SHOP_SNAPSHOT


def last_shop_snapshot_age_s() -> Optional[float]:
    """Seconds since ``last_shop_snapshot`` was stored, or None if never read."""
    if _LAST_SHOP_SNAPSHOT is None or _LAST_SHOP_SNAPSHOT_AT <= 0.0:
        return None
    return max(0.0, time.monotonic() - _LAST_SHOP_SNAPSHOT_AT)


def parse_sell_entries(snapshot: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize sell rows: idx, id, tmpl, count, unit, name."""
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("sell")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("idx", i))
        except (TypeError, ValueError):
            idx = i
        try:
            item_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        try:
            tmpl = int(row.get("tmpl") or 0)
        except (TypeError, ValueError):
            tmpl = 0
        try:
            count = max(0, int(row.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        try:
            unit = int(row.get("unit") or 0)
        except (TypeError, ValueError):
            unit = 0
        name = str(row.get("name") or "").strip()
        out.append(
            {
                "idx": idx,
                "id": item_id,
                "tmpl": tmpl,
                "count": count,
                "unit": unit,
                "name": name,
            }
        )
    return out


__all__ = [
    "ShopListenReader",
    "shared_shop",
    "default_dll_path",
    "last_shop_snapshot",
    "last_shop_snapshot_age_s",
    "parse_sell_entries",
]
