"""Live etview-style entity + ATK probe for the Party monitor overlay.

Uses print_state (markers / iscr) and contested_mobs (AttackAction owner→tgt),
same observations etview.exe paints. Independent of bot Start.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

_LOCK = threading.Lock()
_print_reader = None
_print_tried = False
_contested_reader = None
_contested_tried = False


def reset_etview_probe() -> None:
    global _print_reader, _print_tried, _contested_reader, _contested_tried
    with _LOCK:
        readers = [_print_reader, _contested_reader]
        _print_reader = None
        _contested_reader = None
        _print_tried = False
        _contested_tried = False
    for r in readers:
        if r is None:
            continue
        try:
            r.close()
        except Exception:
            pass


def _ensure_print():
    global _print_reader, _print_tried
    with _LOCK:
        if _print_tried:
            return _print_reader
        _print_tried = True
        try:
            from app._01_perception.print_state_reader import PrintStateReader

            _print_reader = PrintStateReader()
        except Exception:
            _print_reader = None
        return _print_reader


def _ensure_contested():
    global _contested_reader, _contested_tried
    with _LOCK:
        if _contested_tried:
            return _contested_reader
        _contested_tried = True
        try:
            from app._01_perception.contested_mobs_reader import ContestedMobsReader

            _contested_reader = ContestedMobsReader()
        except Exception:
            _contested_reader = None
        return _contested_reader


def _guid_int(value: object) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _xy(block: object) -> Optional[tuple[float, float]]:
    if not isinstance(block, dict):
        return None
    try:
        return float(block["x"]), float(block["y"])
    except (KeyError, TypeError, ValueError):
        return None


def probe_etview_live() -> dict[str, Any]:
    """One live sweep for the Party etview canvas.

    Returns ``entities`` (etview marker rows), ``attacks`` (owner→tgt lines),
    ``client_w`` / ``client_h``, and soft ``error`` when a DLL is missing.
    """
    out: dict[str, Any] = {
        "ok": False,
        "entities": [],
        "attacks": [],
        "client_w": 800,
        "client_h": 600,
        "error": "",
        "probed_at": time.time(),
    }
    errors: list[str] = []
    print_reader = _ensure_print()
    contested_reader = _ensure_contested()

    snap: Optional[dict[str, Any]] = None
    if print_reader is None:
        errors.append("print_state DLL missing/unloadable")
    else:
        try:
            snap = print_reader.snapshot()
        except Exception as exc:
            errors.append(f"print_state: {exc}")
            snap = None

    by_guid: dict[int, dict[str, Any]] = {}
    entities: list[dict[str, Any]] = []
    if isinstance(snap, dict):
        try:
            out["client_w"] = int(snap.get("client_w") or 800)
            out["client_h"] = int(snap.get("client_h") or 600)
        except (TypeError, ValueError):
            pass
        for raw in snap.get("entities") or []:
            if not isinstance(raw, dict):
                continue
            cls = str(raw.get("class") or "?")
            # Skip map props noise (etview shows them; party view stays readable).
            if cls in ("SegmentProp", "Ship"):
                continue
            iscr = _xy(raw.get("iscr"))
            scr = _xy(raw.get("screen"))
            sx, sy = iscr or scr or (None, None)
            if sx is None or sy is None:
                continue
            # Off-world projections (teleport blink) — skip.
            if abs(sx) > 4000 or abs(sy) > 4000:
                continue
            guid = _guid_int(raw.get("guid"))
            row = {
                "class": cls,
                "name": str(raw.get("name") or "").strip(),
                "guid": str(raw.get("guid") or ""),
                "ent": str(raw.get("ent") or ""),
                "sx": float(sx),
                "sy": float(sy),
                "dead": bool(raw.get("dead")),
                "bait": bool(raw.get("bait")),
                "atk": bool(raw.get("atk")),
                "self": bool(raw.get("self")) or cls == "MyPlayer",
            }
            entities.append(row)
            if guid is not None:
                by_guid[guid] = row
        out["ok"] = True

    attacks: list[dict[str, Any]] = []
    contested = None
    if contested_reader is None:
        errors.append("contested_mobs DLL missing/unloadable")
    else:
        try:
            contested = contested_reader.snapshot()
        except Exception as exc:
            errors.append(f"contested: {exc}")

    if isinstance(contested, dict):
        for raw in contested.get("contested") or []:
            if not isinstance(raw, dict):
                continue
            ag = _guid_int(raw.get("attacker_guid") or raw.get("owner"))
            tg = _guid_int(raw.get("guid") or raw.get("tgt"))
            attacker = by_guid.get(ag) if ag is not None else None
            target = by_guid.get(tg) if tg is not None else None
            attacks.append(
                {
                    "attacker_guid": str(raw.get("attacker_guid") or raw.get("owner") or ""),
                    "attacker_name": str(raw.get("attacker_name") or ""),
                    "tgt_guid": str(raw.get("guid") or raw.get("tgt") or ""),
                    "tgt_name": str(raw.get("name") or ""),
                    "ax": float(attacker["sx"]) if attacker else None,
                    "ay": float(attacker["sy"]) if attacker else None,
                    "tx": float(target["sx"]) if target else None,
                    "ty": float(target["sy"]) if target else None,
                }
            )
            if attacker is not None:
                attacker["atk"] = True

    out["entities"] = entities
    out["attacks"] = attacks
    out["error"] = "; ".join(errors)
    return out


__all__ = ["probe_etview_live", "reset_etview_probe"]
