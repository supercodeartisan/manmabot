"""Read 24 hotbar slots from memory and map names to bot spell roles."""
from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from manmabot_v1.paths import app_root
from manmabot_v1.spell_defaults import (
    DEFAULT_SPELL_SLOTS,
    SKILL_KEYS,
    SLOT_IDS,
    default_spell_slots,
)

BOX_KEYS = {1: "f1", 2: "f2", 3: "f3"}
HOTBAR_REFRESH_MIN_S = 5.0
HOTBAR_REFRESH_MAX_S = 7.0


def next_hotbar_refresh_s(rng: random.Random | None = None) -> float:
    """Seconds until the next live F-key hotbar reread (5–7)."""
    pick = rng if rng is not None else random
    return float(pick.uniform(HOTBAR_REFRESH_MIN_S, HOTBAR_REFRESH_MAX_S))


def slot_to_box_key(slot: int) -> tuple[int, str]:
    """Memory slot 0–23 → (box 1–3, f5–f12)."""
    index = max(0, int(slot))
    return index // 8 + 1, SKILL_KEYS[index % 8]

GetFrameFn = Callable[[], Any]
PressKeyFn = Callable[[str], None]


class HotbarInspectError(RuntimeError):
    """Hotbar assets, map file, or scan failed."""


@dataclass
class DetectedCell:
    box: int
    key: str
    template: str = ""
    kr_name: str = ""
    zh_name: str = ""
    role: str = ""
    score: float = 0.0
    bound: bool = False
    kind: str = ""
    count: int | None = None
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "box": self.box,
            "key": self.key,
            "template": self.template,
            "kr_name": self.kr_name,
            "zh_name": self.zh_name,
            "role": self.role,
            "score": round(float(self.score), 4),
            "bound": bool(self.bound),
            "kind": self.kind,
            "count": self.count,
            "label": self.label,
        }


@dataclass
class DetectedLayout:
    cells: list[DetectedCell] = field(default_factory=list)
    spell_slots: dict[str, dict[str, Any]] = field(default_factory=default_spell_slots)
    unbound_icons: list[str] = field(default_factory=list)

    def to_profile_dict(self) -> dict[str, Any]:
        boxes: dict[str, dict[str, dict[str, Any]]] = {
            str(n): {k: {} for k in SKILL_KEYS} for n in (1, 2, 3)
        }
        for cell in self.cells:
            boxes[str(cell.box)][cell.key] = cell.to_dict()
        return {
            "boxes": boxes,
            "unbound_icons": list(self.unbound_icons),
            "active_roles": {
                sid: {
                    "box": int(spec.get("box", 0) or 0),
                    "key": str(spec.get("key", "")),
                    "enabled": bool(spec.get("enabled", False)),
                }
                for sid, spec in self.spell_slots.items()
            },
        }


def role_map_path() -> Path:
    """Prefer package data; allow override under product userdata later if needed."""
    packaged = Path(__file__).resolve().parents[1] / "data" / "hotbar_role_map.csv"
    if packaged.is_file():
        return packaged
    alt = app_root() / "manmabot_v1" / "data" / "hotbar_role_map.csv"
    return alt


def hotbar_asset_root() -> Path:
    return Path(__file__).resolve().parent


def load_role_map(path: Path | None = None) -> dict[str, Any]:
    """Return lookup keys → role id, plus icon templates by Korean name."""
    csv_path = path or role_map_path()
    if not csv_path.is_file():
        raise HotbarInspectError(f"Hotbar role map is missing: {csv_path}")
    allowed = set(SLOT_IDS)
    by_template: dict[str, str] = {}
    by_kr: dict[str, str] = {}
    by_zh: dict[str, str] = {}
    icon_by_kr: dict[str, str] = {}
    try:
        from app._03_world.zh_convert import chinese_aliases as _zh_aliases
    except Exception:
        def _zh_aliases(text: str) -> tuple[str, ...]:
            raw = str(text or "").strip()
            return (raw,) if raw else ()
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                template = str(row.get("template") or "").strip().replace("\\", "/")
                kr = str(row.get("kr_name") or "").strip()
                zh = str(row.get("zh_name") or "").strip()
                role = str(row.get("role") or "").strip()
                if template and kr:
                    icon_by_kr[kr] = template
                if not role:
                    continue
                if role not in allowed:
                    raise HotbarInspectError(
                        f"Unknown role {role!r} in {csv_path.name} "
                        f"(template={row.get('template')!r}). "
                        f"Allowed: {', '.join(SLOT_IDS)}"
                    )
                if template:
                    by_template[template] = role
                if kr:
                    by_kr[kr] = role
                if zh:
                    for alias in _zh_aliases(zh) or (zh,):
                        by_zh[alias] = role
    except HotbarInspectError:
        raise
    except OSError as exc:
        raise HotbarInspectError(f"Could not read hotbar role map: {csv_path}") from exc
    return {
        "__templates__": by_template,
        "__kr__": by_kr,
        "__zh__": by_zh,
        "__icons__": icon_by_kr,
    }


_TRAILING_META = re.compile(r"\s*[\(\（][\d,./\s]+[\)\）]\s*$")
_ENCHANT_PREFIX = re.compile(r"^\+\d+\s*")
_STACK_SUFFIX = re.compile(r"[\(\（]([\d,]+)[\)\）]\s*$")


_SILVER_ARROW_NEEDLES = (
    "은 화살",
    "銀箭",
    "银箭",
    "silver arrow",
    "silver arrows",
)
_NORMAL_ARROW_NAMES = frozenset({"화살", "箭", "arrow", "arrows"})


def hotbar_cell_arrow_kind(cell: dict[str, Any] | DetectedCell) -> str:
    """``silver``, ``normal``, or empty when the cell is not an arrow stack."""
    if isinstance(cell, DetectedCell):
        parts = (cell.kr_name, cell.zh_name, cell.label, cell.template)
    elif isinstance(cell, dict):
        parts = (
            cell.get("kr_name"),
            cell.get("zh_name"),
            cell.get("label"),
            cell.get("template"),
        )
    else:
        return ""
    names = [fold_hotbar_name(str(part or "")).strip() for part in parts]
    blob = " ".join(names).lower()
    if any(needle.lower() in blob for needle in _SILVER_ARROW_NEEDLES):
        return "silver"
    normal = {name.lower() for name in _NORMAL_ARROW_NAMES}
    if any(name.lower() in normal for name in names if name):
        return "normal"
    template = str(parts[3] or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = fold_hotbar_name(template).lower().removesuffix(".png")
    if base in normal:
        return "normal"
    return ""


def hotbar_arrow_slot(
    layout: dict[str, Any] | None,
    kind: str,
) -> tuple[int, str] | None:
    """First F-key cell that holds ``kind`` arrows (``silver`` or ``normal``)."""
    wanted = str(kind or "").strip().lower()
    if wanted not in ("silver", "normal"):
        return None
    boxes = (layout or {}).get("boxes") if isinstance(layout, dict) else None
    if not isinstance(boxes, dict):
        return None
    for box_key in ("1", "2", "3"):
        page = boxes.get(box_key)
        if not isinstance(page, dict):
            continue
        try:
            box = int(box_key)
        except (TypeError, ValueError):
            continue
        for key, cell in page.items():
            if hotbar_cell_arrow_kind(cell if isinstance(cell, dict) else {}) != wanted:
                continue
            return box, str(key)
    return None


def fold_hotbar_name(text: str) -> str:
    """``체력 회복제 (11)`` / ``+0 화살 (2,540)`` / ``힐(4/0)`` → bare name."""
    raw = str(text or "").strip()
    raw = _TRAILING_META.sub("", raw).strip()
    raw = _ENCHANT_PREFIX.sub("", raw).strip()
    return raw


def count_from_hotbar_label(text: str) -> int | None:
    """Stack count in ``이름 (12)``. Skill ranks like ``(4/0)`` are ignored."""
    raw = str(text or "").strip()
    if not raw:
        return None
    tail_at = max(raw.rfind("("), raw.rfind("（"))
    if tail_at >= 0 and "/" in raw[tail_at:]:
        return None
    match = _STACK_SUFFIX.search(raw)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def resolve_role(
    template: str,
    kr_name: str,
    zh_name: str,
    role_lookups: dict[str, Any],
) -> str:
    templates: dict[str, str] = role_lookups.get("__templates__") or {}
    by_kr: dict[str, str] = role_lookups.get("__kr__") or {}
    by_zh: dict[str, str] = role_lookups.get("__zh__") or {}
    cleaned = str(template or "").replace("\\", "/")
    if cleaned in templates:
        return templates[cleaned]
    # Basename-only template match (stage folder may vary).
    base = cleaned.split("/")[-1] if cleaned else ""
    if base:
        for key, role in templates.items():
            if key.endswith("/" + base) or key == base:
                return role
    # Memory may put the Chinese client name in kr_name (zh_name empty).
    for raw in (kr_name, zh_name):
        text = str(raw or "").strip()
        if not text:
            continue
        for name in (text, fold_hotbar_name(text)):
            if name in by_kr:
                return by_kr[name]
            if name in by_zh:
                return by_zh[name]
    return ""


# Escape teleport is the skill only. The role map also tags mass teleport,
# return/teleport scrolls, and fairy wings as ``teleport``.
TELEPORT_SKILL_NAMES = frozenset({"텔레포트", "傳送術", "传送术"})


def _cell_folded_names(raw: dict[str, Any]) -> tuple[str, str]:
    kr = fold_hotbar_name(
        str(raw.get("name") or raw.get("label") or raw.get("kr_name") or "")
    )
    zh = fold_hotbar_name(
        str(raw.get("name_tw") or raw.get("name_cn") or raw.get("zh_name") or "")
    )
    return kr, zh


def _is_escape_teleport_skill(raw: dict[str, Any]) -> bool:
    return any(name in TELEPORT_SKILL_NAMES for name in _cell_folded_names(raw) if name)


def _hotbar_cells_for_role(snap: Any, role: str):
    wanted = str(role or "").strip()
    raw_slots = snap.get("slots") if isinstance(snap, dict) else None
    if not wanted or not isinstance(raw_slots, list):
        return
    lookups = load_role_map()
    for raw in raw_slots:
        if not isinstance(raw, dict):
            continue
        kr, zh = _cell_folded_names(raw)
        if wanted == "teleport":
            if _is_escape_teleport_skill(raw):
                yield raw
            continue
        template = str(raw.get("template") or "").strip()
        if resolve_role(template, kr, zh, lookups) == wanted:
            yield raw


def hotbar_has_role(snap: Any, role: str) -> bool:
    """True when a live slot name maps to ``role``."""
    return next(_hotbar_cells_for_role(snap, role), None) is not None


def find_role_on_hotbar(snap: Any, role: str) -> tuple[int, str] | None:
    """Live 24-slot box/key for ``role``, or None when it is not on the bar."""
    for raw in _hotbar_cells_for_role(snap, role):
        try:
            box = int(raw.get("box") or 0)
        except (TypeError, ValueError):
            box = 0
        key = str(raw.get("key") or "").strip().lower()
        if box in (1, 2, 3) and key in SKILL_KEYS:
            return box, key
        try:
            index = int(raw.get("slot", -1))
        except (TypeError, ValueError):
            index = -1
        if 0 <= index <= 23:
            return slot_to_box_key(index)
    return None


def merge_detected_spell_slots(
    detected: dict[str, dict[str, Any]] | None,
    previous: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Keep operator bindings for roles the scan did not place on the bar."""
    merged = _disabled_slots()
    prev = previous if isinstance(previous, dict) else {}
    found = detected if isinstance(detected, dict) else {}

    def _usable(spec: object) -> bool:
        if not isinstance(spec, dict) or not spec.get("enabled"):
            return False
        try:
            return int(spec.get("box") or 0) in (1, 2, 3)
        except (TypeError, ValueError):
            return False

    occupied: dict[tuple[int, str], str] = {}
    for sid in SLOT_IDS:
        spec = found.get(sid)
        if not _usable(spec):
            continue
        row = dict(spec)
        merged[sid] = row
        occupied[(int(row["box"]), str(row["key"]).lower())] = sid
    for sid in SLOT_IDS:
        if sid in occupied.values():
            continue
        spec = prev.get(sid)
        if not _usable(spec):
            continue
        row = dict(spec)
        key = (int(row["box"]), str(row["key"]).lower())
        if key in occupied:
            continue
        merged[sid] = row
        occupied[key] = sid
    return merged


def _disabled_slots() -> dict[str, dict[str, Any]]:
    slots = default_spell_slots()
    for sid, spec in slots.items():
        fallback = DEFAULT_SPELL_SLOTS[sid]
        spec["box"] = 0
        spec["key"] = str(fallback["key"])
        spec["reuse_s"] = float(fallback["reuse_s"])
        spec["cast"] = str(fallback["cast"])
        spec["enabled"] = False
    return slots


def _memory_snapshot() -> dict[str, Any]:
    try:
        from app._03_world.hotbar_listen_reader import shared_hotbar
    except Exception as exc:
        raise HotbarInspectError(f"Could not import hotbar memory reader: {exc}") from exc
    try:
        snap = shared_hotbar().snapshot()
    except FileNotFoundError as exc:
        raise HotbarInspectError(str(exc)) from exc
    except Exception as exc:
        raise HotbarInspectError(f"Hotbar memory read failed: {exc}") from exc
    if not isinstance(snap, dict) or not isinstance(snap.get("slots"), list):
        raise HotbarInspectError(
            "Hotbar memory read returned no slots (is LC.exe running and signeddrv loaded?)."
        )
    return snap


def inspect_hotbars(
    *,
    get_frame: GetFrameFn | None = None,
    press_key: PressKeyFn | None = None,
    humanize: bool = True,
    threshold: float = 0.65,
    rng: random.Random | None = None,
) -> DetectedLayout:
    """Read 24 hotbar slots from LC memory and bind roles from the name map.

    get_frame / press_key / humanize / threshold / rng are unused (kept so
    older callers that pressed F1–F3 for template matching still compile).
    """
    _ = (get_frame, press_key, humanize, threshold, rng)
    role_lookups = load_role_map()
    icons: dict[str, str] = role_lookups.get("__icons__") or {}
    snap = _memory_snapshot()
    cells: list[DetectedCell] = []
    slots = _disabled_slots()
    claimed: set[str] = set()
    unbound: list[str] = []
    by_slot: dict[int, dict[str, Any]] = {}
    for raw in snap.get("slots") or []:
        if isinstance(raw, dict):
            try:
                by_slot[int(raw.get("slot", -1))] = raw
            except (TypeError, ValueError):
                continue

    for index in range(24):
        box = index // 8 + 1
        key = SKILL_KEYS[index % 8]
        raw = by_slot.get(index) or {}
        kind = str(raw.get("type") or "EMPTY").upper()
        raw_name = str(raw.get("name") or "").strip()
        raw_label = str(raw.get("label") or raw_name).strip()
        kr_name = fold_hotbar_name(raw_name)
        label = fold_hotbar_name(raw_label)
        if not kr_name and label:
            kr_name = label
        template = icons.get(kr_name, "") or icons.get(raw_name, "")
        zh_name = ""
        count_raw = raw.get("count")
        try:
            count = int(count_raw) if count_raw is not None else None
        except (TypeError, ValueError):
            count = None
        if count is None:
            count = count_from_hotbar_label(raw_name) or count_from_hotbar_label(
                raw_label
            )
        empty = kind in {"EMPTY", "?", ""} and not kr_name
        if empty:
            cells.append(DetectedCell(box=box, key=key, kind="EMPTY"))
            continue
        role = resolve_role(template, kr_name, zh_name, role_lookups)
        bound = False
        if role and role not in claimed:
            claimed.add(role)
            fallback = DEFAULT_SPELL_SLOTS[role]
            slots[role] = {
                "box": box,
                "key": key,
                "reuse_s": float(fallback["reuse_s"]),
                "cast": str(fallback["cast"]),
                "enabled": True,
            }
            bound = True
        elif role and role in claimed:
            pass
        else:
            unbound.append(f"box{box}/{key}:{kr_name or label or kind}")
        cells.append(
            DetectedCell(
                box=box,
                key=key,
                template=template,
                kr_name=kr_name,
                zh_name=zh_name,
                role=role,
                score=1.0,
                bound=bound,
                kind=kind,
                count=count,
                label=label,
            )
        )

    return DetectedLayout(
        cells=cells,
        spell_slots=slots,
        unbound_icons=unbound,
    )
