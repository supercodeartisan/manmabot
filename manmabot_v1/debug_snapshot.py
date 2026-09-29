"""Serialize live bot internals into debug-GUI sections."""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from manmabot_v1.spell_defaults import SKILL_KEYS

STATUS_SECTIONS: tuple[str, ...] = (
    "overview",
    "player",
    "decision",
    "world",
    "navigation",
    "memory",
    "vision",
    "hotbar",
    "logs",
    "preview",
    "tables",
)

TABLE_SECTIONS = {"world", "vision"}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _enum(value: Any) -> Any:
    if value is None:
        return None
    return getattr(value, "value", value)


def _xy(value: Any) -> tuple[Any, Any] | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return (value[0], value[1])
    x = _get(value, "x")
    y = _get(value, "y")
    if x is None and y is None:
        return None
    return (x, y)


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text or "0"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        if len(value) <= 8:
            return ", ".join(_fmt(item) for item in value)
        return ", ".join(_fmt(item) for item in value[:8]) + f" … +{len(value) - 8}"
    return str(value)


def _fmt_xy(value: Any) -> str:
    xy = _xy(value)
    if xy is None:
        return "—"
    return f"{_fmt(xy[0])}, {_fmt(xy[1])}"


def _ratio_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _object_record(obj: Any) -> dict[str, Any]:
    ident = _get(obj, "identity")
    name = (
        _get(obj, "species_name")
        or _get(obj, "label")
        or _get(ident, "name")
        or _get(obj, "detail_classification")
    )
    pos = _get(obj, "position")
    return {
        "id": _get(obj, "track_id"),
        "type": _enum(_get(obj, "object_type")) or _get(obj, "classification"),
        "name": name or "—",
        "conf": _get(obj, "yolo_conf") or _get(obj, "species_confidence") or 0.0,
        "x": _get(pos, "x") if pos is not None else _get(obj, "position_x"),
        "y": _get(pos, "y") if pos is not None else _get(obj, "position_y"),
        "detail": _get(obj, "detail_classification"),
        "missed": _get(obj, "frames_lost") or 0,
    }


def _vision_record(item: Any) -> dict[str, Any]:
    return {
        "id": _get(item, "track_id"),
        "type": _get(item, "classification") or _get(item, "label"),
        "name": _get(item, "species_name") or _get(item, "detail_classification") or _get(item, "label") or "—",
        "conf": _get(item, "yolo_conf") or _get(item, "classification_confidence") or 0.0,
        "x": _get(item, "position_x"),
        "y": _get(item, "position_y"),
        "detail": _get(item, "detail_classification"),
        "missed": _get(item, "frames_lost") or 0,
    }


def _player_section(world: Any) -> dict[str, Any]:
    player = _get(world, "player")
    if player is None:
        return {}
    inventory = _get(player, "inventory")
    hp = _get(player, "hp")
    max_hp = _get(player, "max_hp")
    mp = _get(player, "mp")
    max_mp = _get(player, "max_mp")
    return {
        "hp": hp,
        "max_hp": max_hp,
        "hp_text": f"{_fmt(hp)} / {_fmt(max_hp)} ({_ratio_pct(_get(player, 'hp_ratio'))})",
        "mp": mp,
        "max_mp": max_mp,
        "mp_text": f"{_fmt(mp)} / {_fmt(max_mp)} ({_ratio_pct(_get(player, 'mp_ratio'))})",
        "level": _get(player, "level"),
        "exp_percent": _get(player, "exp_percent"),
        "alive": _get(player, "alive"),
        "zone": _get(player, "zone"),
        "character": _enum(_get(player, "character_type")),
        "screen": _fmt_xy(_get(player, "position")),
        "weight_ratio": _get(inventory, "weight_ratio"),
        "weight_text": _ratio_pct(_get(inventory, "weight_ratio")),
        "buffs": [
            f"{_get(buff, 'name')} ({_fmt(_get(buff, 'duration'))})"
            for buff in list(_get(player, "buffs") or [])[:12]
        ],
    }


def _decision_section(blackboard: Any, action: Any) -> dict[str, Any]:
    dest = _get(action, "destination")
    return {
        "mode": _enum(_get(blackboard, "player_mode")),
        "goal": _get(blackboard, "current_goal"),
        "action": _enum(_get(action, "action")),
        "reason": _get(action, "reason"),
        "target_id": _get(action, "target_id") if action is not None else _get(blackboard, "current_target_id"),
        "item_id": _get(blackboard, "current_item_id"),
        "priority": _get(action, "priority"),
        "mid_act": _get(action, "mid_act"),
        "click": _fmt_xy(dest),
        "tick_count": _get(blackboard, "tick_count"),
        "farm_index": _get(blackboard, "farm_area_index"),
        "farm_elapsed_s": _get(blackboard, "farm_elapsed_seconds"),
        "farm_inside": _get(blackboard, "farm_time_inside"),
        "needs_arrows": _get(blackboard, "needs_arrows"),
        "given_up": len(_get(blackboard, "given_up_target_ids") or {}),
        "blacklisted": len(_get(blackboard, "blacklisted_target_ids") or []),
        "resume_mode": _enum(_get(blackboard, "resume_mode")),
    }


def _navigation_section(blackboard: Any) -> dict[str, Any]:
    path = list(_get(blackboard, "nav_path") or [])
    legs = list(_get(blackboard, "leg_history") or [])
    last_leg = None
    if legs:
        last = legs[-1]
        last_leg = last.to_dict() if hasattr(last, "to_dict") else str(last)
    scratch = _get(blackboard, "scratch") or {}
    detour_origin = scratch.get("enter_farm_detour_origin") if isinstance(scratch, Mapping) else None
    detour_tried = scratch.get("enter_farm_detour_tried") if isinstance(scratch, Mapping) else None
    origin_xy = _xy(_get(blackboard, "world_origin"))
    goal_xy = _xy(_get(blackboard, "nav_goal"))
    waypoint_xy = _xy(_get(blackboard, "nav_waypoint"))
    path_xy = [pair for pair in (_xy(item) for item in path[:400]) if pair is not None]
    return {
        "world_origin": _fmt_xy(origin_xy),
        "nav_goal": _fmt_xy(goal_xy),
        "nav_waypoint": _fmt_xy(waypoint_xy),
        "origin_xy": list(origin_xy) if origin_xy else None,
        "goal_xy": list(goal_xy) if goal_xy else None,
        "waypoint_xy": list(waypoint_xy) if waypoint_xy else None,
        "path": [list(pair) for pair in path_xy],
        "path_len": len(path),
        "path_head": path[:6],
        "travel_purpose": _get(blackboard, "travel_purpose"),
        "travel_hop_active": _get(blackboard, "travel_hop_active"),
        "travel_unstick_active": _get(blackboard, "travel_unstick_active"),
        "enter_farm_detour": bool(detour_origin),
        "enter_farm_detour_tried": len(list(detour_tried or [])),
        "travel_stuck_tile": _fmt_xy(_get(blackboard, "travel_stuck_tile")),
        "search_waypoint": _fmt_xy(_get(blackboard, "search_waypoint")),
        "search_hop_active": _get(blackboard, "search_hop_active"),
        "search_stuck_tile": _fmt_xy(_get(blackboard, "search_stuck_tile")),
        "loot_waypoint": _fmt_xy(_get(blackboard, "loot_approach_waypoint")),
        "loot_active": _get(blackboard, "loot_approach_active"),
        "virtual_position": _fmt_xy(_get(blackboard, "virtual_position")),
        "patrol_index": _get(blackboard, "patrol_index"),
        "last_leg": last_leg,
    }


def _memory_section(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping) or not snapshot:
        return {"status": "none"}
    raw = snapshot.get("player") or {}
    pos = raw.get("pos")
    return {
        "status": "live" if raw else "none",
        "frame": snapshot.get("frame"),
        "hp": raw.get("hp"),
        "max_hp": raw.get("maxHp"),
        "mp": raw.get("mp"),
        "max_mp": raw.get("maxMp"),
        "sp": raw.get("sp"),
        "level": raw.get("level"),
        "exp_percent": raw.get("expPct"),
        "pos": _fmt_xy(pos),
        "zone": raw.get("zone"),
        "online": raw.get("online"),
        "class_id": raw.get("classId"),
        "buffs": len(snapshot.get("buffs") or []),
        "items": len(snapshot.get("items") or []),
        "skills": len(snapshot.get("skills") or []),
        "party": len(snapshot.get("party") or []),
        "entities": len(snapshot.get("entities") or []),
    }


def _record_rows(items: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(items or []):
        if isinstance(item, Mapping):
            rows.append({key: item.get(key) for key in fields})
        else:
            rows.append({fields[0]: item, **{key: None for key in fields[1:]}})
    return rows


def _role_by_box_key(slots: Any) -> dict[tuple[int, str], str]:
    out: dict[tuple[int, str], str] = {}
    if not isinstance(slots, Mapping):
        return out
    for spell, spec in slots.items():
        if not isinstance(spec, Mapping) or not spec.get("enabled"):
            continue
        try:
            box = int(spec.get("box") or 0)
        except (TypeError, ValueError):
            continue
        key = str(spec.get("key") or "").strip().lower()
        if box in (1, 2, 3) and key:
            out[(box, key)] = str(spell)
    return out


def _hotbar_table_rows(world: Any, layout: Any, slots: Any) -> list[dict[str, Any]]:
    """24-slot memory hotbar for the tables view (live snap, else last scan)."""
    roles = _role_by_box_key(slots)
    boxes = layout.get("boxes") if isinstance(layout, Mapping) else None
    if not isinstance(boxes, Mapping):
        boxes = {}

    def _cell(box: int, key: str) -> Mapping[str, Any]:
        page = boxes.get(str(box))
        if not isinstance(page, Mapping):
            return {}
        cell = page.get(key)
        return cell if isinstance(cell, Mapping) else {}

    rows: list[dict[str, Any]] = []
    snap = _get(world, "last_hotbar")
    raw_slots = snap.get("slots") if isinstance(snap, Mapping) else None
    if isinstance(raw_slots, list) and raw_slots:
        by_index: dict[int, Mapping[str, Any]] = {}
        for item in raw_slots:
            if not isinstance(item, Mapping):
                continue
            try:
                by_index[int(item.get("slot", item.get("index", -1)))] = item
            except (TypeError, ValueError):
                continue
        for index in range(24):
            box = index // 8 + 1
            key = SKILL_KEYS[index % 8]
            item = by_index.get(index) or {}
            cell = _cell(box, key)
            kind = str(item.get("type") or cell.get("kind") or "EMPTY").upper()
            name = str(item.get("name") or cell.get("kr_name") or item.get("label") or "").strip()
            label = str(item.get("label") or cell.get("label") or name).strip()
            count = item.get("count")
            if count is None:
                count = cell.get("count")
            role = str(cell.get("role") or roles.get((box, key)) or "")
            rows.append(
                {
                    "slot": index + 1,
                    "box": f"F{box}",
                    "key": key.upper(),
                    "type": kind if kind else "EMPTY",
                    "name": name or "—",
                    "label": label or "—",
                    "count": count,
                    "role": role or "—",
                }
            )
        return rows

    for box in (1, 2, 3):
        for key in SKILL_KEYS:
            cell = _cell(box, key)
            kind = str(cell.get("kind") or ("EMPTY" if not cell.get("kr_name") else "")).upper()
            name = str(cell.get("kr_name") or cell.get("label") or "").strip()
            if not kind:
                kind = "EMPTY" if not name else "—"
            rows.append(
                {
                    "slot": (box - 1) * 8 + SKILL_KEYS.index(key) + 1,
                    "box": f"F{box}",
                    "key": key.upper(),
                    "type": kind,
                    "name": name or "—",
                    "label": str(cell.get("label") or name or "—"),
                    "count": cell.get("count"),
                    "role": str(cell.get("role") or roles.get((box, key)) or "") or "—",
                }
            )
    return rows


def _shop_sell_table_rows() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Cached shop_listen sell rows from the last Sell-button read (not live).

    Includes Keep/Sell decision from the active sell filter so empty sells
    can be diagnosed from Debug without guessing.
    """
    meta: list[tuple[str, str]] = []
    rows: list[dict[str, Any]] = []
    try:
        from app._03_world.shop_listen_reader import (
            last_shop_snapshot,
            last_shop_snapshot_age_s,
            parse_sell_entries,
            shared_shop,
        )
    except Exception as exc:
        meta.append(("shop_listen", f"import failed: {exc}"))
        return rows, meta

    shop = shared_shop()
    if not shop.dll_loaded:
        meta.append(("shop_listen", "dll missing"))
        return rows, meta

    snap = last_shop_snapshot()
    if not isinstance(snap, dict):
        meta.append(("shop_listen", "waiting for Sell button read"))
        return rows, meta

    age = last_shop_snapshot_age_s()
    if age is not None:
        meta.append(("shop_age_s", f"{age:.1f}"))

    err = snap.get("error")
    if err:
        meta.append(("shop_error", str(err)))
    meta.append(("shop_state", _fmt(snap.get("state"))))
    meta.append(("buy_n", _fmt(snap.get("buy_n"))))
    meta.append(("sell_n", _fmt(snap.get("sell_n"))))

    sell_mode = "sell_except_keep"
    keep_list: tuple[str, ...] = ()
    garbage_list: tuple[str, ...] = ()
    try:
        from manmabot_v1.shopping.behaviors import (
            item_passes_sell_filter,
            load_behaviors,
            load_sell_filters,
            resolve_active_sell_mode,
        )

        filters = load_sell_filters()
        keep_list = tuple(filters.keep_list)
        garbage_list = tuple(filters.garbage_list)
        behaviors = load_behaviors()
        modes: list[str] = []
        for behavior in behaviors:
            if getattr(behavior, "action", "") != "sell":
                continue
            mode = str(getattr(behavior, "sell_mode", "") or "").strip()
            if mode and mode not in modes:
                modes.append(mode)
        sell_mode = resolve_active_sell_mode(filters=filters, behaviors=behaviors)
        meta.append(("sell_mode", sell_mode))
        if modes:
            meta.append(("sell_modes_yaml", "+".join(modes)))
        meta.append(("keep_n", str(len(keep_list))))
        meta.append(("garbage_n", str(len(garbage_list))))
    except Exception as exc:
        meta.append(("sell_filter", f"unavailable: {exc}"))

        def item_passes_sell_filter(*_a, **_k):  # type: ignore[misc]
            return False

    for entry in parse_sell_entries(snap):
        name = str(entry.get("name") or "")
        try:
            item_id = int(entry.get("id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        try:
            will_sell = bool(
                item_passes_sell_filter(
                    name,
                    sell_mode=sell_mode,
                    garbage_list=garbage_list,
                    keep_list=keep_list,
                    item_id=item_id,
                )
            )
        except Exception:
            will_sell = False
        rows.append(
            {
                "idx": entry.get("idx"),
                "id": item_id,
                "name": name or "—",
                "count": entry.get("count"),
                "unit": entry.get("unit"),
                "tmpl": entry.get("tmpl"),
                "action": "Sell" if will_sell else "Keep",
            }
        )
    return rows, meta


def _tables_section(
    world: Any,
    hotbar_layout: Any = None,
    spell_slots: Any = None,
) -> dict[str, Any]:
    """Player / entity / bag / hotbar / list rows for the combined memory-tables view."""
    player_sec = _player_section(world)
    memory = _get(world, "last_memory_snapshot")
    raw = memory.get("player") if isinstance(memory, Mapping) else {}
    if not isinstance(raw, Mapping):
        raw = {}
    stats = raw.get("stats") if isinstance(raw.get("stats"), Mapping) else {}
    print_state = _get(world, "last_print_state")
    print_player = (
        print_state.get("player") if isinstance(print_state, Mapping) else None
    )
    if not isinstance(print_player, Mapping):
        print_player = {}
    player_rows = [
        {"field": "hp", "value": player_sec.get("hp_text") or _fmt(raw.get("hp"))},
        {"field": "mp", "value": player_sec.get("mp_text") or _fmt(raw.get("mp"))},
        {"field": "sp", "value": _fmt(raw.get("sp"))},
        {"field": "level", "value": _fmt(player_sec.get("level") if player_sec.get("level") is not None else raw.get("level") or print_player.get("lv"))},
        {"field": "exp", "value": _fmt(player_sec.get("exp_percent") if player_sec.get("exp_percent") is not None else raw.get("expPct"))},
        {"field": "class_id", "value": _fmt(raw.get("classId"))},
        {"field": "character", "value": _fmt(player_sec.get("character"))},
        {"field": "zone", "value": _fmt(player_sec.get("zone") or raw.get("zone"))},
        {"field": "world", "value": _fmt_xy(raw.get("pos") or (print_player.get("x"), print_player.get("y")))},
        {"field": "screen", "value": _fmt(player_sec.get("screen"))},
        {"field": "online", "value": _fmt(raw.get("online"))},
        {"field": "gm", "value": _fmt(raw.get("isGm"))},
        {"field": "chaotic", "value": _fmt(raw.get("isChaotic"))},
        {"field": "weight", "value": (
            f"{_fmt(raw.get('weight'))} / {_fmt(raw.get('maxWeight'))}"
            if raw.get("weight") is not None or raw.get("maxWeight") is not None
            else player_sec.get("weight_text") or "—"
        )},
        {"field": "food", "value": _fmt(raw.get("food"))},
        {"field": "lawful", "value": _fmt(raw.get("lawful"))},
        {"field": "ac", "value": _fmt(raw.get("ac"))},
        {"field": "str", "value": _fmt(stats.get("str"))},
        {"field": "dex", "value": _fmt(stats.get("dex"))},
        {"field": "con", "value": _fmt(stats.get("con"))},
        {"field": "int", "value": _fmt(stats.get("int"))},
        {"field": "wis", "value": _fmt(stats.get("wis"))},
        {"field": "cha", "value": _fmt(stats.get("cha"))},
        {"field": "alive", "value": _fmt(player_sec.get("alive"))},
        {"field": "tick_ms", "value": _fmt(raw.get("tickMs"))},
        {"field": "frame", "value": _fmt(_get(memory, "frame") if isinstance(memory, Mapping) else None)},
    ]

    entities: list[dict[str, Any]] = []
    raw_entities = print_state.get("entities") if isinstance(print_state, Mapping) else None
    if not isinstance(raw_entities, list):
        raw_entities = list(_get(world, "last_print_entities") or [])
    for item in raw_entities:
        if not isinstance(item, Mapping):
            continue
        world_pos = item.get("world") if isinstance(item.get("world"), Mapping) else {}
        screen = item.get("screen") if isinstance(item.get("screen"), Mapping) else {}
        iscr = item.get("iscr") if isinstance(item.get("iscr"), Mapping) else {}
        entities.append(
            {
                "class": item.get("class") or item.get("classification") or item.get("type") or "—",
                "name": item.get("name") or item.get("memory_name") or item.get("species_name") or "—",
                "species": item.get("species"),
                "world": (
                    f"{_fmt(world_pos.get('cx'))}, {_fmt(world_pos.get('cy'))}"
                    if world_pos
                    else _fmt_xy((item.get("world_cx"), item.get("world_cy")))
                ),
                "screen": (
                    f"{_fmt(screen.get('x'))}, {_fmt(screen.get('y'))}"
                    if screen
                    else _fmt_xy((item.get("x"), item.get("y")))
                ),
                "iscr": (
                    f"{_fmt(iscr.get('x'))}, {_fmt(iscr.get('y'))}"
                    if iscr
                    else "—"
                ),
                "src": (screen.get("src") if screen else None) or item.get("src") or "—",
                "ent": item.get("ent") or item.get("addr") or "—",
            }
        )

    inventory: list[dict[str, Any]] = []
    bag = _get(world, "last_inventory")
    raw_items = bag.get("items") if isinstance(bag, Mapping) else None
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            inventory.append(
                {
                    "slot": item.get("slot"),
                    "id": item.get("id"),
                    "name": item.get("name") or item.get("name_tw") or "—",
                    "tw": item.get("name_tw") or "—",
                    "name_tw": item.get("name_tw") or "",
                    "name_cn": item.get("name_cn") or "",
                    "name_en": item.get("name_en") or "",
                    "count": item.get("count"),
                    "kind": item.get("kind"),
                    "fmt": item.get("fmt") or "—",
                }
            )
    else:
        inv_state = _get(_get(world, "player"), "inventory")
        for item in list(_get(inv_state, "items") or []):
            inventory.append(
                {
                    "slot": "",
                    "id": _get(item, "item_id"),
                    "name": _get(item, "name") or "—",
                    "tw": _get(item, "name_tw") or "—",
                    "name_tw": _get(item, "name_tw") or "",
                    "name_cn": _get(item, "name_cn") or "",
                    "name_en": _get(item, "name_en") or "",
                    "count": _get(item, "quantity"),
                    "kind": _get(item, "kind"),
                    "fmt": "—",
                }
            )

    shop_sell, shop_meta = _shop_sell_table_rows()
    for field, value in shop_meta:
        player_rows.append({"field": field, "value": value})

    mem = memory if isinstance(memory, Mapping) else {}
    return {
        "player": player_rows,
        "entities": entities,
        "inventory": inventory,
        "shop_sell": shop_sell,
        "hotbar": _hotbar_table_rows(world, hotbar_layout, spell_slots),
        "buffs": _record_rows(mem.get("buffs"), ("id", "remain", "stacks")),
        "skills": _record_rows(mem.get("skills"), ("id", "name", "level")),
        "party": _record_rows(mem.get("party"), ("name", "hp", "class")),
    }


def _hotbar_section(layout: Any, slots: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if isinstance(slots, Mapping):
        for spell, spec in slots.items():
            if not isinstance(spec, Mapping):
                continue
            rows.append(
                {
                    "spell": spell,
                    "box": spec.get("box"),
                    "key": spec.get("key"),
                    "enabled": spec.get("enabled"),
                }
            )
    return {
        "slots": rows,
        "layout_boxes": sorted((layout or {}).keys()) if isinstance(layout, Mapping) else [],
    }


def _world_section(world: Any) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    if world is not None:
        raw_objects = []
        if hasattr(world, "all_objects"):
            raw_objects = list(world.all_objects())
        elif hasattr(world, "objects"):
            maybe = world.objects
            raw_objects = list(maybe.values()) if isinstance(maybe, Mapping) else list(maybe)
        objects = [_object_record(obj) for obj in raw_objects]
        raw_counts = {}
        if hasattr(world, "counts"):
            try:
                raw_counts = world.counts()
            except TypeError:
                raw_counts = {}
        counts = {
            _enum(key) or str(key): int(value) for key, value in dict(raw_counts).items()
        }
    return {
        "frame_id": _get(world, "frame_id"),
        "counts": counts,
        "objects": objects,
    }


def build_runtime_snapshot(
    *,
    state: str,
    reason: str = "",
    pause_kind: str | None = None,
    profile: Any = None,
    world: Any = None,
    blackboard: Any = None,
    action: Any = None,
    vision: Sequence[Any] | None = None,
    hotbar_layout: Mapping[str, Any] | None = None,
    spell_slots: Mapping[str, Any] | None = None,
    loop: Mapping[str, Any] | None = None,
    worker_alive: bool = False,
    arming: bool = False,
) -> dict[str, Any]:
    """Build a JSON-friendly snapshot of one bot tick for the debug GUI."""
    loop = dict(loop or {})
    vision_rows = [_vision_record(item) for item in list(vision or [])]
    return {
        "updated_at": loop.get("updated_at"),
        "overview": {
            "state": state,
            "reason": reason or "",
            "pause_kind": pause_kind or "",
            "worker_alive": worker_alive,
            "arming": arming,
            "note": loop.get("note") or "",
            "fps": loop.get("fps"),
            "tick_ms": loop.get("tick_ms"),
            "frame_id": loop.get("frame_id") or _get(world, "frame_id"),
            "map": _get(profile, "active_map"),
            "character": _get(profile, "character"),
            "loot_mode": _get(profile, "loot_mode"),
            "farms": list(_get(profile, "selected_farms") or []),
            "game_language": _get(profile, "game_language"),
        },
        "player": _player_section(world),
        "decision": _decision_section(blackboard, action),
        "world": _world_section(world),
        "navigation": _navigation_section(blackboard),
        "memory": _memory_section(_get(world, "last_memory_snapshot")),
        "vision": {"count": len(vision_rows), "detections": vision_rows},
        "hotbar": _hotbar_section(hotbar_layout, spell_slots),
        "tables": _tables_section(world, hotbar_layout, spell_slots),
    }


def _kv_rows(data: Mapping[str, Any], *, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key, value in data.items():
        label = f"{prefix}{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            if not value:
                rows.append((label, "—"))
            else:
                rows.extend(_kv_rows(value, prefix=f"{label}."))
            continue
        if isinstance(value, list) and value and isinstance(value[0], Mapping):
            rows.append((label, f"{len(value)} item(s)"))
            continue
        rows.append((label, _fmt(value)))
    return rows


def rows_for_section(section: str, snapshot: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """Rows for the selected debug section."""
    if section == "world":
        objects = list((snapshot.get("world") or {}).get("objects") or [])
        rows = [
            (
                _fmt(item.get("id")),
                _fmt(item.get("type")),
                _fmt(item.get("name")),
                _fmt(item.get("conf")),
                _fmt_xy((item.get("x"), item.get("y"))),
            )
            for item in objects
        ]
        counts = (snapshot.get("world") or {}).get("counts") or {}
        if counts and not rows:
            return [(_fmt(key), _fmt(value), "—", "—", "—") for key, value in counts.items()]
        return rows
    if section == "vision":
        detections = list((snapshot.get("vision") or {}).get("detections") or [])
        return [
            (
                _fmt(item.get("id")),
                _fmt(item.get("type")),
                _fmt(item.get("name")),
                _fmt(item.get("conf")),
                _fmt_xy((item.get("x"), item.get("y"))),
            )
            for item in detections
        ]
    if section == "hotbar":
        slots = list((snapshot.get("hotbar") or {}).get("slots") or [])
        rows = [
            (
                _fmt(item.get("spell")),
                _fmt(item.get("box")),
                _fmt(item.get("key")),
                _fmt(item.get("enabled")),
            )
            for item in slots
        ]
        if rows:
            return rows
        return _kv_rows(snapshot.get("hotbar") or {})
    if section == "tables":
        tables = snapshot.get("tables") or {}
        rows: list[tuple[str, ...]] = []
        for field_row in list((tables.get("player") or []) if isinstance(tables, Mapping) else []):
            if isinstance(field_row, Mapping):
                rows.append(("player", _fmt(field_row.get("field")), _fmt(field_row.get("value")), "", "", ""))
        for item in list((tables.get("entities") or []) if isinstance(tables, Mapping) else []):
            if isinstance(item, Mapping):
                rows.append(
                    (
                        "entity",
                        _fmt(item.get("class")),
                        _fmt(item.get("name")),
                        _fmt(item.get("world")),
                        _fmt(item.get("screen")),
                        "",
                    )
                )
        for item in list((tables.get("inventory") or []) if isinstance(tables, Mapping) else []):
            if isinstance(item, Mapping):
                rows.append(
                    (
                        "item",
                        _fmt(item.get("slot")),
                        _fmt(item.get("id")),
                        _fmt(item.get("name")),
                        _fmt(item.get("count")),
                        _fmt(item.get("fmt")),
                    )
                )
        for item in list((tables.get("shop_sell") or []) if isinstance(tables, Mapping) else []):
            if isinstance(item, Mapping):
                rows.append(
                    (
                        "shop_sell",
                        _fmt(item.get("idx")),
                        _fmt(item.get("id")),
                        _fmt(item.get("name")),
                        _fmt(item.get("count")),
                        _fmt(item.get("action")),
                    )
                )
        for item in list((tables.get("hotbar") or []) if isinstance(tables, Mapping) else []):
            if isinstance(item, Mapping):
                rows.append(
                    (
                        "hotbar",
                        _fmt(item.get("box")),
                        _fmt(item.get("key")),
                        _fmt(item.get("type")),
                        _fmt(item.get("name")),
                        _fmt(item.get("count")),
                    )
                )
        return rows
    payload = snapshot.get(section) or {}
    if not isinstance(payload, Mapping):
        return [("value", _fmt(payload))]
    return _kv_rows(payload)


def columns_for_section(section: str) -> tuple[tuple[str, str], ...]:
    if section in TABLE_SECTIONS:
        return (
            ("id", "debug_id"),
            ("type", "debug_type"),
            ("name", "debug_name"),
            ("conf", "debug_conf"),
            ("position", "debug_position"),
        )
    if section == "hotbar":
        return (
            ("spell", "spell"),
            ("box", "hotbar_box"),
            ("key", "hotbar_key"),
            ("enabled", "enabled"),
        )
    return (("field", "debug_field"), ("value", "debug_value"))


def section_text(section: str, snapshot: Mapping[str, Any], logs: Iterable[str] | None = None) -> str:
    if section == "logs":
        return "\n".join(list(logs or []))
    rows = rows_for_section(section, snapshot)
    if not rows:
        return ""
    width = max(len(str(row[0])) for row in rows)
    return "\n".join(
        f"{str(row[0]).ljust(width)}  {' | '.join(str(cell) for cell in row[1:])}"
        for row in rows
    )
