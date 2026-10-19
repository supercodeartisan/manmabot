"""Serialize live bot internals into debug-GUI sections."""
from __future__ import annotations

import time
from typing import Any, Iterable, Mapping, Sequence

from settings.spell_defaults import SKILL_KEYS

STATUS_SECTIONS: tuple[str, ...] = (
    "overview",
    "player",
    "decision",
    "party",
    "world",
    "navigation",
    "nav_show",
    "memory",
    "vision",
    "hotbar",
    "logs",
    "preview",
    "field_view",
    "tables",
    "astar",
    "decide_time",
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


def _object_record(obj: Any, world: Any = None) -> dict[str, Any]:
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
        "rx": _get(obj, "world_rx"),
        "ry": _get(obj, "world_ry"),
        "bait": bool(_get(obj, "bait")),
        "dead": _object_dead(obj, world),
        "detail": _get(obj, "detail_classification"),
        "missed": _get(obj, "frames_lost") or 0,
    }


def _object_dead(obj: Any, world: Any) -> bool:
    """True once the reader has dropped this monster or combat marked it dead.

    print_state omits a corpse, but the object stays for a few frames.
    ``frames_lost`` stays 0 on that leftover, so the field view uses the
    sweep miss count and ``ObjectStatus.DEAD`` instead.
    """
    kind = _enum(_get(obj, "object_type")) or _get(obj, "classification")
    if str(kind or "") != "monster":
        return False
    if str(_enum(_get(obj, "status")) or "") == "dead":
        return True
    tid = _get(obj, "track_id")
    missing = getattr(world, "missing_frames", None) if world is not None else None
    if not callable(missing) or tid is None:
        return False
    try:
        return int(missing(int(tid))) > 0
    except (TypeError, ValueError):
        return False


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


def _give_up_rows(blackboard: Any) -> list[dict[str, Any]]:
    """Active temporary give-ups with remaining cooldown seconds."""
    given = _get(blackboard, "given_up_target_ids") or {}
    if not isinstance(given, Mapping):
        return []
    try:
        from app._04_decision.behaviors.combat import GIVE_UP_COOLDOWN_SECONDS

        window = max(0.1, float(GIVE_UP_COOLDOWN_SECONDS))
    except Exception:
        window = 4.0
    now = time.time()
    scratch = _get(blackboard, "scratch") or {}
    meta_by_id: dict[int, dict[str, Any]] = {}
    hist = scratch.get("give_up_history") if isinstance(scratch, Mapping) else None
    if isinstance(hist, list):
        for item in hist:
            if not isinstance(item, Mapping):
                continue
            try:
                tid_i = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            meta_by_id[tid_i] = dict(item)
    last = scratch.get("last_give_up") if isinstance(scratch, Mapping) else None
    if isinstance(last, Mapping):
        try:
            meta_by_id[int(last.get("id"))] = dict(last)
        except (TypeError, ValueError):
            pass
    rows: list[dict[str, Any]] = []
    for tid, started in given.items():
        try:
            tid_i = int(tid)
            age = now - float(started)
        except (TypeError, ValueError):
            continue
        if age < 0 or age >= window:
            continue
        meta = meta_by_id.get(tid_i) or {}
        remain = window - age
        rows.append(
            {
                "id": tid_i,
                "reason": str(meta.get("reason") or "give-up"),
                "name": str(meta.get("name") or "").strip(),
                "cursor_label": str(meta.get("cursor_label") or "").strip(),
                "cursor_category": str(meta.get("cursor_category") or "").strip(),
                "cursor_score": meta.get("cursor_score"),
                "need_score": meta.get("need_score"),
                "age_s": round(age, 2),
                "remain_s": round(remain, 2),
            }
        )
    rows.sort(key=lambda row: float(row.get("remain_s") or 0))
    return rows


def _cursor_fail_section(blackboard: Any) -> dict[str, Any]:
    """Last cursor-verify reject + active fail streaks (debug Session panel)."""
    scratch = _get(blackboard, "scratch") or {}
    last = scratch.get("last_cursor_reject") if isinstance(scratch, Mapping) else None
    streaks_raw = _get(blackboard, "cursor_verify_fail_streak") or {}
    streaks: list[dict[str, Any]] = []
    if isinstance(streaks_raw, Mapping):
        for tid, count in streaks_raw.items():
            try:
                streaks.append({"id": int(tid), "streak": int(count)})
            except (TypeError, ValueError):
                continue
        streaks.sort(key=lambda row: (-int(row["streak"]), int(row["id"])))
    return {
        "last_reject": dict(last) if isinstance(last, Mapping) else None,
        "streaks": streaks[:8],
    }


def _decision_section(blackboard: Any, action: Any) -> dict[str, Any]:
    dest = _get(action, "destination")
    scratch = _get(blackboard, "scratch") or {}
    last_give_up = scratch.get("last_give_up") if isinstance(scratch, Mapping) else None
    last_blacklist = scratch.get("last_blacklist") if isinstance(scratch, Mapping) else None
    give_ups = _give_up_rows(blackboard)
    cursor_fail = _cursor_fail_section(blackboard)
    path_cap_skips: list[dict[str, Any]] = []
    try:
        from app._04_decision.combat_query import path_cap_skips as _path_cap_skips

        path_cap_skips = [
            dict(row) for row in _path_cap_skips() if isinstance(row, Mapping)
        ]
    except Exception:
        path_cap_skips = []
    no_intent_why: list[str] = []
    if isinstance(scratch, Mapping):
        raw_why = scratch.get("no_intent_why")
        if isinstance(raw_why, list):
            no_intent_why = [str(x).strip() for x in raw_why[-8:] if str(x).strip()]
    blocked_origin = None
    blocked_tried: list[Any] = []
    if isinstance(scratch, Mapping):
        blocked_origin = scratch.get("dungeon_blocked_origin")
        raw_tried = scratch.get("dungeon_blocked_tried")
        if isinstance(raw_tried, list):
            blocked_tried = list(raw_tried)[:24]
    idle_diag = {
        "no_intent_why": no_intent_why,
        "travel_hop_miss": (
            str(scratch.get("travel_hop_miss") or "").strip()
            if isinstance(scratch, Mapping)
            else ""
        ),
        "travel_purpose": _get(blackboard, "travel_purpose"),
        "nav_goal": _fmt_xy(_get(blackboard, "nav_goal")),
        "nav_waypoint": _fmt_xy(_get(blackboard, "nav_waypoint")),
        "world_origin": _fmt_xy(_get(blackboard, "world_origin")),
        "dungeon_blocked_origin": blocked_origin,
        "dungeon_blocked_tried": blocked_tried,
        "dungeon_blocked_tried_n": len(blocked_tried),
    }
    return {
        "mode": _enum(_get(blackboard, "player_mode")),
        "goal": _get(blackboard, "current_goal"),
        "action": _enum(_get(action, "action")),
        "reason": _get(action, "reason"),
        "idle_diag": idle_diag,
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
        "given_up": len(give_ups),
        "give_ups": give_ups,
        "last_give_up": dict(last_give_up) if isinstance(last_give_up, Mapping) else None,
        "path_cap_skips": path_cap_skips,
        "attacks_me": [],
        "contested_mobs": [],
        "blacklisted": len(_get(blackboard, "blacklisted_target_ids") or []),
        "blacklisted_ids": sorted(
            int(tid)
            for tid in (_get(blackboard, "blacklisted_target_ids") or set())
            if str(tid).lstrip("-").isdigit()
        ),
        "last_blacklist": dict(last_blacklist) if isinstance(last_blacklist, Mapping) else None,
        "resume_mode": _enum(_get(blackboard, "resume_mode")),
        "cursor_fail": cursor_fail,
        "last_cursor_reject": cursor_fail.get("last_reject"),
    }


def _abs_to_nav_xy(pack_id: str, ax: int, ay: int) -> tuple[int, int] | None:
    try:
        from app._04_decision.world_nav import pack_ids

        nav = pack_ids.abs_to_nav(str(pack_id), int(ax), int(ay))
    except Exception:
        return None
    if nav is None:
        return None
    return int(nav[0]), int(nav[1])


def _live_pose_debug(world: Any) -> tuple[int | None, tuple[int, int] | None]:
    """MapSubsystem mapId + absolute game tile from memory/print_state."""
    mid: int | None = None
    abs_xy: tuple[int, int] | None = None
    try:
        from app._03_world.merge.memory_sync import (
            player_game_xy_from_snapshot,
            player_map_id_from_snapshot,
        )

        mem = _get(world, "last_memory_snapshot")
        if isinstance(mem, Mapping):
            mid = player_map_id_from_snapshot(mem)
            abs_xy = player_game_xy_from_snapshot(mem)
        print_state = _get(world, "last_print_state")
        if isinstance(print_state, Mapping):
            print_xy = player_game_xy_from_snapshot(print_state)
            if print_xy is not None:
                abs_xy = print_xy
    except Exception:
        pass
    return mid, abs_xy


def _resolve_display_pack(
    *,
    live_map_id: int | None,
    profile: Any,
) -> str:
    if live_map_id is not None:
        try:
            from app._04_decision.world_nav import pack_ids

            pack = pack_ids.map_id_to_pack_id(int(live_map_id))
            if pack:
                return str(pack)
        except Exception:
            pass
    try:
        from app._03_world.space.map_pack import get_active_map_pack

        active = get_active_map_pack()
        if active is not None and getattr(active, "id", None):
            return str(active.id)
    except Exception:
        pass
    return str(_get(profile, "active_map") or "talking_island")


def _world_nav_debug(
    blackboard: Any,
    *,
    live_map_id: int | None,
    display_pack: str,
) -> dict[str, Any] | None:
    scratch = _get(blackboard, "scratch") or {}
    if not isinstance(scratch, Mapping):
        return None
    session = scratch.get("world_nav_session")
    if session is None:
        return None
    plan = getattr(session, "plan", None)
    step_i = int(getattr(session, "step_i", 0) or 0)
    steps_out: list[dict[str, Any]] = []
    plan_path: list[list[int]] = []
    plan_markers: list[dict[str, Any]] = []
    raw_steps = list(getattr(plan, "steps", None) or []) if plan is not None else []
    for i, step in enumerate(raw_steps):
        op = str(getattr(step, "op", "") or "")
        detail = dict(getattr(step, "detail", None) or {})
        try:
            summary = str(step.summary()) if hasattr(step, "summary") else op
        except Exception:
            summary = op
        steps_out.append(
            {
                "i": i,
                "op": op,
                "active": i == step_i,
                "done": i < step_i,
                "summary": summary,
                "cost_tiles": int(getattr(step, "cost_tiles", 0) or 0),
            }
        )
        if live_map_id is None:
            continue
        mid = int(live_map_id)
        if op == "walk":
            frm = detail.get("from") if isinstance(detail.get("from"), Mapping) else {}
            to = detail.get("to") if isinstance(detail.get("to"), Mapping) else {}
            try:
                walk_map = int(frm.get("mapId"))
            except (TypeError, ValueError):
                continue
            if walk_map != mid:
                continue
            raw_path = detail.get("path") or []
            converted: list[list[int]] = []
            for pt in raw_path:
                xy = _xy(pt)
                if xy is None:
                    continue
                nav = _abs_to_nav_xy(display_pack, int(xy[0]), int(xy[1]))
                if nav is not None:
                    converted.append([nav[0], nav[1]])
            if not converted:
                for key, kind in (("from", "plan_from"), ("to", "plan_to")):
                    src = detail.get(key) if isinstance(detail.get(key), Mapping) else {}
                    try:
                        nav = _abs_to_nav_xy(
                            display_pack, int(src["x"]), int(src["y"])
                        )
                    except (KeyError, TypeError, ValueError):
                        nav = None
                    if nav is not None:
                        plan_markers.append(
                            {"xy": [nav[0], nav[1]], "kind": kind, "active": i == step_i}
                        )
            elif i == step_i or (not plan_path and i >= step_i):
                plan_path = converted
                try:
                    to_nav = _abs_to_nav_xy(
                        display_pack, int(to["x"]), int(to["y"])
                    )
                except (KeyError, TypeError, ValueError):
                    to_nav = None
                if to_nav is not None:
                    plan_markers.append(
                        {
                            "xy": [to_nav[0], to_nav[1]],
                            "kind": "plan_to",
                            "active": True,
                        }
                    )
        elif op == "map_transition":
            frm = detail.get("from") if isinstance(detail.get("from"), Mapping) else {}
            to = detail.get("to") if isinstance(detail.get("to"), Mapping) else {}
            for src, kind in ((frm, "gate_from"), (to, "gate_to")):
                try:
                    if int(src.get("mapId")) != mid:
                        continue
                    nav = _abs_to_nav_xy(
                        display_pack, int(src["x"]), int(src["y"])
                    )
                except (TypeError, ValueError, KeyError):
                    continue
                if nav is not None:
                    plan_markers.append(
                        {"xy": [nav[0], nav[1]], "kind": kind, "active": i == step_i}
                    )
        elif op == "talking_scroll":
            to = detail.get("to") if isinstance(detail.get("to"), Mapping) else {}
            try:
                if int(to.get("mapId")) != mid:
                    continue
                nav = _abs_to_nav_xy(display_pack, int(to["x"]), int(to["y"]))
            except (TypeError, ValueError, KeyError):
                continue
            if nav is not None:
                plan_markers.append(
                    {"xy": [nav[0], nav[1]], "kind": "scroll_to", "active": i == step_i}
                )
    end = getattr(plan, "end_pose", None) if plan is not None else None
    end_pose = None
    if end is not None:
        end_pose = {
            "mapId": getattr(end, "map_id", None),
            "x": getattr(end, "x", None),
            "y": getattr(end, "y", None),
        }
    return {
        "phase": str(getattr(session, "phase", "") or ""),
        "reason": str(getattr(session, "reason", "") or ""),
        "step_i": step_i,
        "steps_n": len(raw_steps),
        "error": getattr(session, "error", None),
        "steps": steps_out[:24],
        "plan_path": plan_path[:800],
        "plan_markers": plan_markers[:32],
        "end_pose": end_pose,
        "total_cost": int(getattr(plan, "total_cost_tiles", 0) or 0) if plan else 0,
    }


def _navigation_section(
    blackboard: Any,
    *,
    world: Any = None,
    profile: Any = None,
) -> dict[str, Any]:
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
    live_map_id, live_abs = _live_pose_debug(world)
    display_pack = _resolve_display_pack(live_map_id=live_map_id, profile=profile)
    live_origin = None
    if live_abs is not None:
        live_origin = _abs_to_nav_xy(display_pack, int(live_abs[0]), int(live_abs[1]))
    world_nav = _world_nav_debug(
        blackboard, live_map_id=live_map_id, display_pack=display_pack
    )
    gate_warn = None
    if isinstance(scratch, Mapping):
        raw_warn = scratch.get("nav_gate_warn")
        if isinstance(raw_warn, Mapping) and raw_warn.get("message"):
            gate_warn = {
                "message": str(raw_warn.get("message") or ""),
                "to_map": raw_warn.get("to_map"),
                "from_map": raw_warn.get("from_map"),
                "edge": str(raw_warn.get("edge") or ""),
                "at": raw_warn.get("at"),
            }
    # Prefer live MapSubsystem pose for the nav-show marker when available.
    draw_origin = live_origin or (tuple(origin_xy) if origin_xy else None)
    draw_path = path_xy
    if world_nav and world_nav.get("plan_path"):
        # World-nav A* plan on the live map takes priority over farm hop crumbs.
        draw_path = [
            (int(p[0]), int(p[1]))
            for p in world_nav["plan_path"]
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
    return {
        "world_origin": _fmt_xy(origin_xy),
        "nav_goal": _fmt_xy(goal_xy),
        "nav_waypoint": _fmt_xy(waypoint_xy),
        "origin_xy": list(draw_origin) if draw_origin else None,
        "goal_xy": list(goal_xy) if goal_xy else None,
        "waypoint_xy": list(waypoint_xy) if waypoint_xy else None,
        "path": [list(pair) for pair in draw_path],
        "path_len": len(draw_path),
        "path_head": draw_path[:6] if draw_path is not path_xy else path[:6],
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
        "live_map_id": live_map_id,
        "live_pack": display_pack,
        "live_abs_xy": list(live_abs) if live_abs else None,
        "live_origin_xy": list(live_origin) if live_origin else None,
        "profile_map": str(_get(profile, "active_map") or ""),
        "display_map": display_pack,
        "world_nav": world_nav,
        "plan_markers": list((world_nav or {}).get("plan_markers") or []),
        "gate_warn": gate_warn,
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
        from app._01_perception.sensors import shared_sensors
        from app._01_perception.shop_listen_reader import (
            last_shop_snapshot,
            last_shop_snapshot_age_s,
            parse_sell_entries,
        )
    except Exception as exc:
        meta.append(("shop_listen", f"import failed: {exc}"))
        return rows, meta

    if not shared_sensors().shop_ready:
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
        from shop.behaviors import (
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
        objects = [_object_record(obj, world) for obj in raw_objects]
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


def _cursor_match_fields(executor: Any) -> dict[str, Any]:
    match = _get(executor, "last_cursor_match")
    if match is None:
        return {"cursor_label": "", "cursor_category": "", "cursor_score": None}
    category = _get(match, "category")
    score = _get(match, "score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return {
        "cursor_label": str(_get(match, "label") or ""),
        "cursor_category": str(_enum(category) or ""),
        "cursor_score": score_f,
    }


def _action_result_section(executor: Any) -> dict[str, Any]:
    """Real mouse result from the last ActionExecutor.execute() call."""
    if executor is None:
        return {
            "kind": "none",
            "clicked": False,
            "hovered": False,
            "detail": "",
            "cursor_label": "",
            "cursor_category": "",
            "cursor_score": None,
            "verify_failed": False,
        }
    raw = _get(executor, "last_mouse_outcome") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    kind = str(raw.get("kind") or "none").strip().lower() or "none"
    reject_reason = str(raw.get("reject_reason") or "").strip()
    verify_failed = bool(
        raw.get("reject_target_id") is not None
        or raw.get("reject_item_id") is not None
        or reject_reason
    )
    travel_cursor = raw.get("travel_cursor")
    if not isinstance(travel_cursor, Mapping):
        travel_cursor = getattr(executor, "last_travel_cursor_stats", None) or {}
        if not isinstance(travel_cursor, Mapping):
            travel_cursor = {}
    out = {
        "kind": kind,
        "clicked": bool(raw.get("clicked")),
        "hovered": bool(raw.get("hovered")),
        "detail": str(raw.get("detail") or "").strip(),
        "attack_id": raw.get("attack_id"),
        "cast_id": raw.get("cast_id"),
        "loot_id": raw.get("loot_id"),
        "reject_target_id": raw.get("reject_target_id"),
        "reject_item_id": raw.get("reject_item_id"),
        "reject_reason": reject_reason,
        "verify_failed": verify_failed,
        "travel_cursor": dict(travel_cursor),
    }
    out.update(_cursor_match_fields(executor))
    return out


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
    executor: Any = None,
) -> dict[str, Any]:
    """Build a JSON-friendly snapshot of one bot tick for the debug GUI."""
    loop = dict(loop or {})
    vision_rows = [_vision_record(item) for item in list(vision or [])]
    decision = _decision_section(blackboard, action)
    try:
        from app._03_world.merge.memory_entities import (
            attacks_targeting_me,
            contested_monster_guids,
            player_targeting_me,
        )

        snap = _get(world, "last_print_state")
        attackers = list(attacks_targeting_me(snap))
        player = player_targeting_me(snap)
        if player is not None:
            attackers.append(player)
        decision["attacks_me"] = attackers
        claimed = contested_monster_guids(snap)
        decision["contested_mobs"] = [{"guid": f"0x{guid:X}"} for guid in sorted(claimed)]
    except Exception:
        decision["attacks_me"] = []
        decision["contested_mobs"] = []
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
        "decision": decision,
        "action_result": _action_result_section(executor),
        "world": _world_section(world),
        "navigation": _navigation_section(
            blackboard, world=world, profile=profile
        ),
        "memory": _memory_section(_get(world, "last_memory_snapshot")),
        "vision": {"count": len(vision_rows), "detections": vision_rows},
        "hotbar": _hotbar_section(hotbar_layout, spell_slots),
        "tables": _tables_section(world, hotbar_layout, spell_slots),
        "astar": _astar_section(loop.get("astar")),
        "decide_time": _decide_time_section(loop.get("decide_spans")),
    }


def _decide_time_section(raw: Any) -> dict[str, Any]:
    from app._04_decision.decide_spans import summarize

    runs = [dict(item) for item in list(raw or []) if isinstance(item, Mapping)]
    total, groups = summarize(runs)
    return {"total_ms": total, "parts": groups}


def _astar_section(raw: Any) -> dict[str, Any]:
    runs = [dict(item) for item in list(raw or []) if isinstance(item, Mapping)]
    total = round(sum(float(item.get("ms") or 0.0) for item in runs), 1)
    return {"count": len(runs), "total_ms": total, "runs": runs}


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
    if section == "astar":
        info = snapshot.get("astar") or {}
        runs = list(info.get("runs") or []) if isinstance(info, Mapping) else []
        rows = [
            (
                str(info.get("count") or 0),
                _fmt(info.get("total_ms")),
                "tick total",
                "",
                "",
                "",
                "",
            )
        ]
        for index, item in enumerate(runs, start=1):
            if not isinstance(item, Mapping):
                continue
            rows.append(
                (
                    str(index),
                    _fmt(item.get("ms")),
                    _fmt(item.get("cause")),
                    _fmt(item.get("search")),
                    f"{_fmt(item.get('start'))} → {_fmt(item.get('goal'))}",
                    _fmt(item.get("steps")),
                    _fmt(item.get("expanded")),
                )
            )
        return rows
    if section == "decide_time":
        from app._04_decision.decide_spans import label_for

        info = snapshot.get("decide_time") or {}
        parts = list(info.get("parts") or []) if isinstance(info, Mapping) else []
        total = float(info.get("total_ms") or 0.0)
        rows: list[tuple[str, ...]] = [
            (
                "decision",
                "1",
                _fmt(total),
                _fmt(total),
                "100%",
            )
        ]
        for item in parts:
            if not isinstance(item, Mapping):
                continue
            depth = int(item.get("depth") or 0)
            ms = float(item.get("ms") or 0.0)
            share = (ms / total * 100.0) if total > 0 else 0.0
            rows.append(
                (
                    ("  " * depth) + label_for(str(item.get("name") or "")),
                    _fmt(item.get("calls")),
                    _fmt(ms),
                    _fmt(item.get("max_ms")),
                    f"{share:.0f}%",
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
    if section == "astar":
        return (
            ("n", "debug_astar_n"),
            ("ms", "debug_astar_ms"),
            ("cause", "debug_astar_cause"),
            ("search", "debug_astar_search"),
            ("tiles", "debug_astar_tiles"),
            ("steps", "debug_astar_steps"),
            ("expanded", "debug_astar_expanded"),
        )
    if section == "decide_time":
        return (
            ("component", "debug_decide_component"),
            ("calls", "debug_decide_calls"),
            ("ms", "debug_decide_ms"),
            ("max", "debug_decide_max"),
            ("share", "debug_decide_share"),
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
