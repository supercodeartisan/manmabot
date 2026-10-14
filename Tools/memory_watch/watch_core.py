"""Read one memory unit and fingerprint the payload for change detection."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional

from memory_bench.bench_core import UNITS, UnitSpec, unit_by_key

# Units that are timing variants of the same reader — watch uses one live snap each.
_WATCH_SKIP = frozenset({"entities_compare", "entities_slow"})

WATCH_UNITS: tuple[UnitSpec, ...] = tuple(
    u for u in UNITS if u.key not in _WATCH_SKIP
)


def watch_choices() -> list[tuple[str, str]]:
    return [(u.key, u.label) for u in WATCH_UNITS]


def watch_unit_by_key(key: str) -> UnitSpec:
    if key == "entities_fast":
        return unit_by_key("entities_fast")
    for u in WATCH_UNITS:
        if u.key == key:
            return u
    # Allow bench keys that map onto a watch reader.
    if key == "entities_compare" or key == "entities_slow":
        return unit_by_key("entities_fast")
    return unit_by_key(key)


def _sensors():
    from app._01_perception.sensors import shared_sensors

    return shared_sensors()


def _print_reader():
    sensors = _sensors()
    reader = getattr(sensors, "_print_reader", None)
    if reader is not None and hasattr(reader, "snapshot"):
        return reader
    from app._01_perception.print_state_reader import PrintStateReader

    return PrintStateReader()


def _attacks_reader():
    return getattr(_sensors(), "_attacks_reader", None)


def _contested_reader():
    return getattr(_sensors(), "_contested_reader", None)


def read_unit(key: str) -> tuple[bool, Any, str]:
    """Return ``(ok, payload, summary)`` for one live read.

    ``payload`` is JSON-serializable (dict/list/str) for the text view.
    """
    key = str(key or "").strip()
    if key in ("entities_compare", "entities_slow", "entities_fast"):
        snap = _print_reader().snapshot()
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "no snapshot"}, "no snapshot"
        ents = snap.get("entities")
        n = len(ents) if isinstance(ents, list) else 0
        return True, snap, f"entities={n}"

    if key == "buff":
        snap = _sensors().capture_buff()
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "buff capture failed"}, "fail"
        n = len(snap.get("buffs") or [])
        return True, snap, f"buffs={n}"

    if key == "uidialog":
        from app._01_perception.uidialog_listen_reader import shared_uidialog

        reader = shared_uidialog()
        if getattr(reader, "_scan", None) is None:
            return False, {"error": "uidialog_listen_scan missing in DLL"}, "no scan export"
        snap = reader.scan()
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "uidialog scan failed"}, "fail"
        return (
            True,
            snap,
            "scan hits={hits} n_open={n_open} open={open} heap_total={heap}".format(
                hits=snap.get("n_hits"),
                n_open=snap.get("n_open"),
                open=snap.get("open"),
                heap=snap.get("heap_total"),
            ),
        )

    if key == "hotbar":
        snap = _sensors().capture_hotbar(force=True)
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "hotbar capture failed"}, "fail"
        n = len(snap.get("slots") or [])
        return True, snap, f"slots={n}"

    if key == "inventory":
        snap = _sensors().capture_inventory(force=False)
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "inventory idle empty"}, "fail"
        n = len(snap.get("items") or [])
        return True, snap, f"items={n} force=0"

    if key == "inventory_force":
        snap = _sensors().capture_inventory(force=True)
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "inventory force failed"}, "fail"
        n = len(snap.get("items") or [])
        return True, snap, f"items={n} force=1"

    if key == "shop":
        snap = _sensors().capture_shop()
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "shop capture failed"}, "fail"
        buy = len(snap.get("buy") or [])
        sell = len(snap.get("sell") or [])
        return True, snap, f"buy={buy} sell={sell}"

    if key == "attacks_me":
        reader = _attacks_reader()
        if reader is None:
            return False, {"error": "attacks_me reader missing"}, "missing"
        snap = reader.snapshot()
        ok = snap is not None
        return ok, snap if ok else {"error": "null"}, f"ok={ok}"

    if key == "contested":
        reader = _contested_reader()
        if reader is None:
            return False, {"error": "contested reader missing"}, "missing"
        snap = reader.snapshot()
        ok = snap is not None
        return ok, snap if ok else {"error": "null"}, f"ok={ok}"

    if key == "player":
        snap = _sensors().pull_player(fresh=False)
        ok = isinstance(snap, dict)
        if not ok:
            return False, {"error": "no player"}, "fail"
        p = snap.get("player") if isinstance(snap.get("player"), dict) else snap
        x = p.get("x") if isinstance(p, dict) else None
        y = p.get("y") if isinstance(p, dict) else None
        mid = p.get("mapId") if isinstance(p, dict) else None
        return True, snap, f"xy=({x},{y}) mapId={mid}"

    if key == "capture_tick":
        buf = _sensors().capture_tick(force_inventory=False, hotbar=False)
        payload = _buffer_payload(buf)
        return True, payload, _buffer_summary(payload)

    if key == "capture_tick_full":
        buf = _sensors().capture_tick(force_inventory=True, hotbar=True)
        payload = _buffer_payload(buf)
        return True, payload, _buffer_summary(payload)

    raise KeyError(key)


def _buffer_payload(buf: Any) -> dict[str, Any]:
    return {
        "player_ok": bool(getattr(buf, "player_ok", False)),
        "player": getattr(buf, "player", None),
        "print_state_ok": bool(getattr(buf, "print_state_ok", False)),
        "print_state": getattr(buf, "print_state", None),
        "buff_ok": bool(getattr(buf, "buff_ok", False)),
        "buff": getattr(buf, "buff", None),
        "uidialog_ok": bool(getattr(buf, "uidialog_ok", False)),
        "uidialog": getattr(buf, "uidialog", None),
        "hotbar_ok": bool(getattr(buf, "hotbar_ok", False)),
        "hotbar": getattr(buf, "hotbar", None),
        "inventory_ok": bool(getattr(buf, "inventory_ok", False)),
        "inventory": getattr(buf, "inventory", None),
        "errors": list(getattr(buf, "errors", None) or []),
    }


def _buffer_summary(payload: dict[str, Any]) -> str:
    bits: list[str] = []
    if payload.get("player_ok"):
        bits.append("player")
    ps = payload.get("print_state")
    if payload.get("print_state_ok") and isinstance(ps, dict):
        ents = ps.get("entities")
        bits.append(f"print({len(ents) if isinstance(ents, list) else 0})")
    if payload.get("buff_ok"):
        buff = payload.get("buff") if isinstance(payload.get("buff"), dict) else {}
        n = len(buff.get("buffs") or []) if isinstance(buff, dict) else 0
        bits.append(f"buff({n})")
    if payload.get("uidialog_ok"):
        bits.append("uidialog")
    if payload.get("hotbar_ok"):
        bits.append("hotbar")
    if payload.get("inventory_ok"):
        bits.append("inv")
    errs = payload.get("errors") or []
    if errs:
        bits.append(f"err={len(errs)}")
    return " ".join(bits) or "empty"


def fingerprint(payload: Any) -> str:
    """Stable hash of JSON-canonical payload (change detector)."""
    try:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        blob = repr(payload)
    return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()


def format_payload(payload: Any, *, indent: int = 2) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def ensure_sensors_loaded(progress: Optional[Callable[[str], None]] = None) -> None:
    if progress:
        progress("loading sensors…")
    _sensors()


__all__ = [
    "WATCH_UNITS",
    "watch_choices",
    "watch_unit_by_key",
    "read_unit",
    "fingerprint",
    "format_payload",
    "ensure_sensors_loaded",
]
