"""Turn memory-module text into the snapshot dicts the bot already consumes.

Decision code keeps reading player / print_state / inventory / hotbar / party.
This file is the only place that knows the module text layout.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from app._01_perception.lc_session import session

_CLASS = {
    "Summon": "SummonedMonster",
    "NPC": "InteractiveNPC",
}


def _json_object(text: str) -> Optional[dict[str, Any]]:
    for line in reversed(text.splitlines()):
        raw = line.strip()
        if not raw.startswith("{"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _xy(value: Any) -> Optional[dict[str, int]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return {"x": int(value[0]), "y": int(value[1])}
        except (TypeError, ValueError):
            return None
    return None


def _pair(value: Any) -> Optional[tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


_PROJ: Optional[dict[str, float]] = None


def _projection() -> dict[str, float]:
    """print_state click scale. Registry supplies PPS and the viewport. Anchor stays 0."""
    global _PROJ
    if _PROJ is not None:
        return _PROJ
    found = {
        "ref_w": 800.0,
        "ref_h": 600.0,
        "pps": 0.53,
        "vp_dx": 1.8,
        "vp_dy": 63.0,
        "feet_dx": 0.0,
        "feet_dy": 0.0,
        "anchor_du": 0.0,
        "anchor_dv": 0.0,
    }
    # print_state loads settings, then entity_offsets.txt. That file sets
    # ANCHOR_DU/DV to 0 and wins over the registry's ANCHOR_DV=24. The 24
    # shift puts the cursor above the sprite the working branch clicks.
    keys = {
        "REF_W": "ref_w",
        "REF_H": "ref_h",
        "PPS": "pps",
        "VP_DX": "vp_dx",
        "VP_DY": "vp_dy",
        "FEET_DX": "feet_dx",
        "FEET_DY": "feet_dy",
    }
    try:
        from app._01_perception.registry_apply import parse_registry, source_registry

        path = source_registry()
        reg = parse_registry(path) if path is not None else {}
    except Exception:
        reg = {}
    for key, name in keys.items():
        raw = reg.get(key)
        if not raw:
            continue
        try:
            found[name] = float(raw)
        except ValueError:
            continue
    _PROJ = found
    return found


def _click_iscr(
    width: int,
    height: int,
    du: float,
    dv: float,
) -> dict[str, int]:
    """Screen pixel print_state writes for the attack click.

    Same origin as ``entity_offsets.txt``: separate width and height scales,
    viewport ``VP_DX`` / ``VP_DY``, and anchor 0. The registry's
    ``ANCHOR_DV=24`` is not applied.
    """
    proj = _projection()
    ref_w = proj["ref_w"] if proj["ref_w"] else 800.0
    ref_h = proj["ref_h"] if proj["ref_h"] else 600.0
    sx = float(width) / ref_w
    sy = float(height) / ref_h
    pps = proj["pps"]
    origin_x = (
        float(width) * 0.5
        + proj["vp_dx"] * sx
        + proj["feet_dx"] * sx
        + proj["anchor_du"] * pps * sx
    )
    origin_y = (
        float(height) * 0.5
        - proj["vp_dy"] * sy
        + proj["feet_dy"] * sy
        - proj["anchor_dv"] * pps * sy
    )
    return {
        "x": int(round(origin_x + du * pps * sx)),
        "y": int(round(origin_y - dv * pps * sy)),
    }


def char_vitals() -> Optional[dict[str, Any]]:
    """Decoded character block from the latest charread sample."""
    text = session.text("charread")
    if not text:
        return None
    found: dict[str, Any] = {}
    level = re.search(r"Lv=(\d+)", text)
    hp = re.search(r"HP=(\d+)/(\d+)", text)
    mp = re.search(r"MP=(\d+)/(\d+)", text)
    if level:
        found["level"] = int(level.group(1))
    if hp:
        found["hp"] = int(hp.group(1))
        found["max_hp"] = int(hp.group(2))
    if mp:
        found["mp"] = int(mp.group(1))
        found["max_mp"] = int(mp.group(2))
    stats = re.search(
        r"STR=(\d+)\s+INT=(\d+)\s+CON=(\d+)\s+DEX=(\d+)\s+WIS=(\d+)\s+CHA=(\d+)",
        text,
    )
    if stats:
        found["stats"] = {
            "str": int(stats.group(1)),
            "int": int(stats.group(2)),
            "con": int(stats.group(3)),
            "dex": int(stats.group(4)),
            "wis": int(stats.group(5)),
            "cha": int(stats.group(6)),
        }
    weight = re.search(r"W=(\d+)/(\d+)", text)
    if weight:
        found["weight"] = int(weight.group(1))
        found["max_weight"] = int(weight.group(2))
    food = re.search(r"FOOD=(\d+)", text)
    if food:
        found["food"] = int(food.group(1))
    lawful = re.search(r"LAWFUL=(-?\d+)", text)
    if lawful:
        found["lawful"] = int(lawful.group(1))
    ac = re.search(r"AC=(-?\d+)", text)
    if ac:
        found["ac"] = int(ac.group(1))
    pos = re.search(r"POS:\s*X=(-?\d+)\s+Y=(-?\d+)", text)
    if pos:
        found["x"] = int(pos.group(1))
        found["y"] = int(pos.group(2))
    exp = re.search(r"EXP=([0-9.]+)%", text)
    if exp:
        found["exp_percent"] = float(exp.group(1))
    if "hp" not in found and "x" not in found and "level" not in found:
        return None
    return found


def map_info() -> Optional[dict[str, Any]]:
    text = session.text("map")
    if not text:
        return None
    match = None
    for line in reversed(text.splitlines()):
        if "mapId=" in line:
            match = line
            break
    if match is None:
        return None
    mid = re.search(r"mapId=(-?\d+)", match)
    cell = re.search(r"cell=\((-?\d+),(-?\d+)\)", match)
    region = re.search(r"region=(\S+)", match)
    sub = re.search(r"subregion=(\S+)", match)
    info: dict[str, Any] = {}
    if mid:
        value = int(mid.group(1))
        info["map_id"] = value
        info["map_ok"] = value >= 0
    if cell:
        info["x"] = int(cell.group(1))
        info["y"] = int(cell.group(2))
    zone = ""
    if region and region.group(1) not in ("-", ""):
        zone = region.group(1)
    if sub and sub.group(1) not in ("-", ""):
        zone = f"{zone} {sub.group(1)}".strip()
    if zone:
        info["zone"] = zone
    return info or None


def player_snapshot() -> Optional[dict[str, Any]]:
    """Monitor-shaped snapshot: ``{"player": {...}}``."""
    vitals = char_vitals() or {}
    geo = map_info() or {}
    if not vitals and not geo:
        return None
    x = vitals.get("x", geo.get("x"))
    y = vitals.get("y", geo.get("y"))
    map_id = geo.get("map_id")
    player: dict[str, Any] = {
        "hp": vitals.get("hp"),
        "maxHp": vitals.get("max_hp"),
        "mp": vitals.get("mp"),
        "maxMp": vitals.get("max_mp"),
        "level": vitals.get("level"),
        "expPct": vitals.get("exp_percent") or 0.0,
        "x": x,
        "y": y,
        "mapId": map_id if geo.get("map_ok") else None,
        "mapIdOk": 1 if geo.get("map_ok") else 0,
        "zone": geo.get("zone") or "",
    }
    if x is not None and y is not None:
        player["pos"] = [int(x), int(y)]
    if isinstance(vitals.get("stats"), dict):
        player["stats"] = vitals["stats"]
    for src, dest in (
        ("weight", "weight"),
        ("max_weight", "maxWeight"),
        ("food", "food"),
        ("lawful", "lawful"),
        ("ac", "ac"),
    ):
        if src in vitals:
            player[dest] = vitals[src]
    return {"player": player}


_last_body: Optional[tuple[int, int]] = None


def _body_pair_from_text(text: str) -> Optional[tuple[int, int]]:
    """Last ``t_ms body cmd body_rva cmd_rva`` row in one bodyact sample."""
    for line in reversed(text.splitlines()):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 5:
            continue
        try:
            return int(parts[3], 0), int(parts[4], 0)
        except ValueError:
            continue
    return None


def body_rvas() -> Optional[tuple[int, int]]:
    """Latest bodyact ``(body_rva, cmd_rva)``.

    The module writes a row only when the body or command changes, then
    pushes an empty sample on the ticks in between. An empty sample keeps
    the last row. A failed read stays None until the first row arrives.
    """
    global _last_body
    text = session.text("bodyact")
    if text:
        pair = _body_pair_from_text(text)
        if pair is not None:
            _last_body = pair
            return pair
    return _last_body


_client_hwnd = 0


def _live_client_size() -> Optional[tuple[int, int]]:
    """LC client width and height, the rectangle print_state projects into."""
    global _client_hwnd
    try:
        from app._05_action.window_bounds import find_game_window, get_client_bounds
    except Exception:
        return None
    bounds = get_client_bounds(_client_hwnd) if _client_hwnd else None
    if bounds is None:
        _client_hwnd = int(find_game_window("LC.exe") or 0)
        if not _client_hwnd:
            return None
        bounds = get_client_bounds(_client_hwnd)
    if bounds is None or bounds.width < 100 or bounds.height < 100:
        _client_hwnd = 0
        return None
    return int(bounds.width), int(bounds.height)


def _self_index(
    rows: list[dict[str, Any]],
    isos: list[Optional[tuple[float, float]]],
) -> Optional[int]:
    """MyPlayer row. A row with iso wins inside each group."""
    groups = (
        [i for i, row in enumerate(rows) if row.get("self")],
        [
            i
            for i, row in enumerate(rows)
            if str(row.get("class") or "") == "MyPlayer"
        ],
    )
    for group in groups:
        for i in group:
            if isos[i] is not None:
                return i
        if group:
            return group[0]
    return None


def _cell_delta(
    row: dict[str, Any],
    self_world: Optional[dict[str, Any]],
) -> Optional[tuple[float, float]]:
    """print_state's cell fallback: du=48*(dx+dy), dv=24*(dx-dy)."""
    world = row.get("world")
    if not isinstance(world, dict) or not isinstance(self_world, dict):
        return None
    try:
        dx = int(world["cx"]) - int(self_world["cx"])
        dy = int(world["cy"]) - int(self_world["cy"])
    except (KeyError, TypeError, ValueError):
        return None
    return 48.0 * (dx + dy), 24.0 * (dx - dy)


def _entity_rows(frame: dict[str, Any], width: int = 0, height: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    isos: list[Optional[tuple[float, float]]] = []
    for raw in frame.get("ents") or []:
        if not isinstance(raw, dict):
            continue
        cls = _CLASS.get(str(raw.get("cls") or ""), str(raw.get("cls") or ""))
        world = raw.get("world")
        world_block = None
        if isinstance(world, (list, tuple)) and len(world) >= 2:
            try:
                world_block = {"cx": int(world[0]), "cy": int(world[1])}
            except (TypeError, ValueError):
                world_block = None
        guid = str(raw.get("guid") or "")
        isos.append(_pair(raw.get("iiso")))
        rows.append(
            {
                "class": cls,
                "guid": guid,
                "ent": guid,
                "name": str(raw.get("name") or ""),
                "species": raw.get("sp") or 0,
                "iscr": _xy(raw.get("iscr")),
                "world": world_block,
                "qty": raw.get("qty"),
                "contrib": raw.get("contrib"),
                "own": raw.get("own"),
                "bait": raw.get("bait"),
                "atk": raw.get("atk"),
                "owner": raw.get("owner"),
                "tgt": raw.get("tgt"),
                "self": bool(raw.get("self")),
            }
        )
    if width < 1 or height < 1:
        return rows
    me = _self_index(rows, isos)
    if me is None:
        return rows
    self_iso = isos[me]
    self_world = rows[me].get("world") if isinstance(rows[me].get("world"), dict) else None
    if self_iso is None and self_world is None:
        return rows
    for row, iso in zip(rows, isos):
        if self_iso is not None and iso is not None:
            du = iso[0] - self_iso[0]
            dv = iso[1] - self_iso[1]
        else:
            delta = _cell_delta(row, self_world)
            if delta is None:
                continue
            du, dv = delta
        row["iscr"] = _click_iscr(width, height, du, dv)
    return rows


def print_state() -> Optional[dict[str, Any]]:
    """print_state-shaped entity frame from enttrack."""
    text = session.text("enttrack")
    frame = _json_object(text)
    if frame is None:
        return None
    live = _live_client_size()
    if live is not None:
        width, height = live
    else:
        res = frame.get("res") if isinstance(frame.get("res"), list) else [0, 0]
        try:
            width = int(res[0]) if len(res) > 0 else 0
            height = int(res[1]) if len(res) > 1 else 0
        except (TypeError, ValueError):
            width, height = 0, 0
    rows = _entity_rows(frame, width, height)
    player_wrap = player_snapshot() or {}
    player = dict(player_wrap.get("player") or {})
    cell = frame.get("self") if isinstance(frame.get("self"), dict) else {}
    xy = cell.get("cell") if isinstance(cell, dict) else None
    if isinstance(xy, (list, tuple)) and len(xy) >= 2 and player.get("x") is None:
        try:
            player["x"] = int(xy[0])
            player["y"] = int(xy[1])
        except (TypeError, ValueError):
            pass
    return {
        "client_w": width,
        "client_h": height,
        "player": player,
        "entities": rows,
    }


def _me_guid(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if str(row.get("class") or "") == "MyPlayer":
            return str(row.get("guid") or "")
    return ""


def attacks_me() -> Optional[dict[str, Any]]:
    frame = print_state()
    if not isinstance(frame, dict):
        return None
    rows = [row for row in frame.get("entities") or [] if isinstance(row, dict)]
    me = _me_guid(rows).lower()
    hits = []
    for row in rows:
        if str(row.get("class") or "") not in ("Monster", "SummonedMonster"):
            continue
        if row.get("atk") not in (1, True):
            continue
        tgt = str(row.get("tgt") or "").lower()
        if me and tgt == me:
            hits.append(row)
    return {"attacks_me": hits, "strikes": hits}


def contested_mobs() -> Optional[dict[str, Any]]:
    frame = print_state()
    if not isinstance(frame, dict):
        return None
    rows = [row for row in frame.get("entities") or [] if isinstance(row, dict)]
    me = _me_guid(rows).lower()
    monsters = {
        str(row.get("guid") or "").lower(): row
        for row in rows
        if str(row.get("class") or "") == "Monster"
    }
    claimed: list[dict[str, Any]] = []
    for row in rows:
        cls = str(row.get("class") or "")
        if cls == "Player":
            if me and str(row.get("guid") or "").lower() == me:
                continue
        elif cls == "SummonedMonster":
            owner = str(row.get("owner") or "").lower()
            if not owner or (me and owner == me):
                continue
        else:
            continue
        if row.get("atk") not in (1, True):
            continue
        mon = monsters.get(str(row.get("tgt") or "").lower())
        if mon is None:
            continue
        claimed.append(
            {
                "name": mon.get("name") or "",
                "guid": mon.get("guid") or "",
                "ent": mon.get("ent") or "",
                "tgt": mon.get("guid") or "",
                "world": mon.get("world"),
                "owner": row.get("guid") or "",
                "attacker_guid": row.get("guid") or "",
                "attacker_name": row.get("name") or "",
            }
        )
    return {"contested": claimed}


def inventory() -> Optional[dict[str, Any]]:
    text = session.text("inventory")
    if not text or "InventorySubsystem not found" in text:
        return None
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.search(
            r'id=(\d+)\s+cnt=(\d+)\s+ench=(\d+)\s+kind=(\d+)\s+fmt="([^"]*)"\s+name=(.*)$',
            line,
        )
        if not match:
            continue
        items.append(
            {
                "id": int(match.group(1)),
                "count": int(match.group(2)),
                "enchant": int(match.group(3)),
                "kind": int(match.group(4)),
                "name": match.group(6).strip(),
            }
        )
    if "t=" not in text and not items:
        return None
    return {"items": items}


def hotbar() -> Optional[dict[str, Any]]:
    text = session.text("hotbar")
    if not text or "HudSlotDataSubsystem not found" in text:
        return None
    slots: list[dict[str, Any]] = []
    for line in text.splitlines():
        # hotbar_930.c: key type cfg id mid name. mid is optional for older lines.
        match = re.search(
            r"key=(-?\d+)\s+type=(-?\d+)\s+cfg=(\d+)\s+id=(\d+)"
            r"(?:\s+mid=(-?\d+))?\s+name=(.*)$",
            line,
        )
        if not match:
            continue
        index = int(match.group(1))
        slots.append(
            {
                "slot": index,
                "key_index": index,
                "type": int(match.group(2)),
                "cfg": int(match.group(3)),
                "id": int(match.group(4)),
                "mid": int(match.group(5) or 0),
                "name": match.group(6).strip(),
            }
        )
    if "t=" not in text and not slots:
        return None
    return {"slots": slots}


def shop() -> Optional[dict[str, Any]]:
    text = session.text("shop")
    if not text or "ShopSubsystem not found" in text:
        return None
    buy: list[dict[str, Any]] = []
    sell: list[dict[str, Any]] = []
    for line in text.splitlines():
        bought = re.search(
            r"BUY\s+\[\s*\d+\]\s+order=(\d+)\s+id=(\d+)\s+tmpl=(\d+)\s+price=(\d+)\s+(.*)$",
            line,
        )
        if bought:
            buy.append(
                {
                    "order": int(bought.group(1)),
                    "id": int(bought.group(2)),
                    "tmpl": int(bought.group(3)),
                    "price": int(bought.group(4)),
                    "name": bought.group(5).strip(),
                }
            )
            continue
        sold = re.search(
            r"SELL\[\s*\d+\]\s+id=(\d+)\s+tmpl=(\d+)\s+invCnt=(\d+)\s+unit=(\d+)\s+(.*)$",
            line,
        )
        if sold:
            sell.append(
                {
                    "id": int(sold.group(1)),
                    "tmpl": int(sold.group(2)),
                    "count": int(sold.group(3)),
                    "unit": int(sold.group(4)),
                    "price": int(sold.group(4)),
                    "name": sold.group(5).strip(),
                }
            )
    if "t=" not in text and not buy and not sell:
        return None
    return {"buy": buy, "sell": sell}


def buffs() -> Optional[dict[str, Any]]:
    text = session.text("buff")
    if not text:
        return None
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.search(r"name=(.*?)\s+남은=([0-9.]+)s", line)
        if not match:
            match = re.search(r"name=(.*?)\s+remain=([0-9.]+)s", line)
        if not match:
            continue
        name = match.group(1).strip()
        if not name:
            continue
        rows.append({"name": name, "remain": float(match.group(2))})
    if "t=" not in text and "#" not in text and not rows:
        return None
    return {"buffs": rows, "cache": 0}


_CONFIRM_EVENT = re.compile(
    r"^\[(?P<op>[+~])\] CONFIRM kind=(?P<kind>\S+) ask=(?P<ask>\d+) "
    r"type=(?P<type>\d+)(?: inst=(?P<inst>0x[0-9A-Fa-f]+))? \"(?P<msg>.*)\"\s*$"
)
_CONFIRM_STATUS = re.compile(
    r"open=\d+\s+\[(?P<open>[^\]]*)\]\s+confirm=(?P<n>\d+)(?:\s+msg=\"(?P<msg>.*)\")?\s*$"
)
_OPEN_ONLY = re.compile(r"open=\d+\s+\[([^\]]*)\]")


def parse_uidialog_text(text: str) -> Optional[dict[str, Any]]:
    """Window labels plus Yes/No confirm rows (invite / trade / etc.).

    ``uidialogmon`` writes either a status line
    ``t=… open=N […] confirm=N msg="…"`` or event lines
    ``[+] CONFIRM kind=… ask=N … "message"``. Invite accept reads ``confirm``.
    """
    if not str(text or "").strip():
        return None
    open_labels: list[str] = []
    confirms: list[dict[str, Any]] = []
    saw_status = False
    saw_event = False
    for line in text.splitlines():
        raw = line.rstrip("\r")
        event = _CONFIRM_EVENT.match(raw)
        if event:
            saw_event = True
            confirms.append(
                {
                    "src": event.group("kind") or "",
                    "kind": event.group("kind") or "",
                    "ask": int(event.group("ask") or 0),
                    "type": int(event.group("type") or 0),
                    "inst": event.group("inst") or "",
                    "msg": event.group("msg") or "",
                }
            )
            continue
        if raw.startswith("[-] CONFIRM"):
            saw_event = True
            continue
        status = _CONFIRM_STATUS.search(raw)
        if status:
            saw_status = True
            open_labels = [part for part in status.group("open").split() if part]
            n = int(status.group("n") or 0)
            msg = status.group("msg") or ""
            if n <= 0:
                confirms = []
            elif msg:
                confirms = [
                    {
                        "src": "status",
                        "kind": "",
                        "ask": 0,
                        "type": 0,
                        "inst": "",
                        "msg": msg,
                    }
                ]
            continue
        opened = _OPEN_ONLY.search(raw)
        if opened and not saw_status:
            open_labels = [part for part in opened.group(1).split() if part]
    if not saw_status and not saw_event and not open_labels and "t=" not in text:
        return None
    windows = {label: True for label in open_labels}
    return {"windows": windows, "open": open_labels, "confirm": confirms}


def uidialog() -> Optional[dict[str, Any]]:
    text = session.text("uidialogmon")
    if not text:
        return None
    return parse_uidialog_text(text)


def party() -> Optional[dict[str, Any]]:
    text = session.text("party")
    if not text:
        return None
    if "PartySubsystem not found" in text:
        return {"leader": None, "members": [], "in_party": False, "subs_ok": False}
    members: list[dict[str, Any]] = []
    leader_name = ""
    header = re.search(r"leader=(\S+)", text)
    if header and header.group(1) not in ("(?)", "?"):
        leader_name = header.group(1).strip()
    for line in text.splitlines():
        if " name=" not in line:
            continue
        name_m = re.search(r"name=(\S+)", line)
        guid_m = re.search(r"guid=([0-9A-Fa-f]+)", line)
        map_m = re.search(r"map=(-?\d+)", line)
        pos_m = re.search(r"pos=(-?\d+),(-?\d+)", line)
        hp_m = re.search(r"hp%=(\d+)", line)
        mp_m = re.search(r"mp%=(\d+)", line)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        is_leader = "[LEADER]" in line
        row: dict[str, Any] = {
            "name": name,
            "guid": f"0x{guid_m.group(1)}" if guid_m else "",
            "is_leader": is_leader,
            "hp_pct": int(hp_m.group(1)) if hp_m else None,
            "mp_pct": int(mp_m.group(1)) if mp_m else None,
        }
        if map_m:
            row["map_id"] = int(map_m.group(1))
        if pos_m:
            row["x"] = int(pos_m.group(1))
            row["y"] = int(pos_m.group(2))
        if is_leader:
            leader_name = name
        members.append(row)
    leader = {"name": leader_name} if leader_name else None
    if leader and members:
        for row in members:
            if row.get("is_leader"):
                leader = dict(row)
                break
    if "t=" not in text and "party" not in text.lower() and not members:
        return None
    return {
        "leader": leader,
        "members": members,
        "in_party": bool(members),
        "subs_ok": True,
    }


_SLOT_LINE = re.compile(
    r"SLOT\s+(\d+)\s+guid=(0x[0-9A-Fa-f]+)\s+hp=([-\d.]+)\s+mp=([-\d.]+)\s+active=(\d+)"
)
_WIDGET_LINE = re.compile(
    r"W \+0x([0-9A-Fa-f]+)\s+\S+\s+abs=\([^)]*\)\s+size=\([^)]*\)\s+px=\[(-?\d+),(-?\d+),(-?\d+),(-?\d+)\]"
)
# Click the member row, not the name text or the HP bar.
_ROW_OFFS = ("0D0", "060")


def parse_party_hud_text(text: str) -> Optional[dict[str, Any]]:
    """Party HUD sample: one client-pixel box per active member row.

    The box is the row button (``+0xD0``) when that widget is on screen,
    otherwise the row layout (``+0x60``).
    """
    if not text or ("partyhud" not in text.lower() and "SLOT " not in text and "창 없음" not in text):
        return None
    slots: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    widgets: dict[str, dict[str, int]] = {}

    def finish() -> None:
        nonlocal current, widgets
        if current is None:
            return
        row = None
        for off in _ROW_OFFS:
            box = widgets.get(off)
            if box is not None:
                row = {"off": f"0x{off}", **box}
                break
        current["row"] = row
        slots.append(current)
        current = None
        widgets = {}

    for line in text.splitlines():
        slot_m = _SLOT_LINE.search(line)
        if slot_m:
            finish()
            current = {
                "index": int(slot_m.group(1)),
                "guid": slot_m.group(2),
                "hp": float(slot_m.group(3)),
                "mp": float(slot_m.group(4)),
                "active": slot_m.group(5) == "1",
            }
            widgets = {}
            continue
        if current is None:
            continue
        widget_m = _WIDGET_LINE.search(line)
        if not widget_m or "미배치" in line:
            continue
        widgets[widget_m.group(1).upper()] = {
            "x0": int(widget_m.group(2)),
            "y0": int(widget_m.group(3)),
            "x1": int(widget_m.group(4)),
            "y1": int(widget_m.group(5)),
        }
    finish()
    return {
        "open": "창 없음" not in text and "WIN " in text,
        "slots": slots,
    }


def party_hud() -> Optional[dict[str, Any]]:
    text = session.text("partyhud")
    if not text:
        return None
    return parse_party_hud_text(text)
