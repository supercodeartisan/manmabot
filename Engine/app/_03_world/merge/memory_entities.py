"""Turn a print_state snapshot into perception handoff dicts.

Rows use the same shape ``handoff_to_perception`` accepts so Decision/World
stay unchanged. These rows are the farm click list (print_state only).
``MyPlayer`` and off-screen non-item rows are omitted.

Monster level reuses the vision tables: Korean / Chinese / English display
names map to ``monster_*`` keys via ``species_aliases.json``, then
``monster_level_from_species`` reads ``label_tables.json``. Optional
``species_ids.json`` can still force a catalog key or level by numeric id.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from app._03_world.constants import monster_level_for_object, monster_level_from_species

_CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"
_SPECIES_PATH = _CATALOG_DIR / "species_ids.json"
_ALIASES_PATH = _CATALOG_DIR / "species_aliases.json"

# print_state class string → vision coarse name. None means "not a target".
_COARSE = {
    "Monster": "monster",
    "SummonedMonster": "monster",
    "InteractiveNPC": "npc",
    "Item": "item",
    "ITEM": "item",
    "ADENA": "item",
    "PLAYER": "player",
    "Player": "player",
    "MyPlayer": None,
}

_DETAIL = {
    "npc": "npc",
    "item": "item",
    "player": "player",
}

_alias_index: dict[str, str] | None = None


def attacks_me_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize rows from an attacks_me.dll snapshot.

    Live decisions use print_state ``atk`` / ``tgt`` via ``attacks_targeting_me``.
    """
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("attacks_me")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        ent = str(row.get("ent") or "").strip()
        if not ent:
            continue
        out.append(dict(row))
    return out


def contested_mobs_from_snapshot(
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize ``contested`` rows from contested_mobs.dll.

    Each row is a monster currently targeted by a visible other Player (or
    a summon not owned by me). Missing from the list means free to engage.
    """
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("contested")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        ent = str(row.get("ent") or "").strip()
        if not ent:
            continue
        out.append(dict(row))
    return out


_ME_CLASSES = frozenset({"MyPlayer", "SELF"})
_ATTACKER_CLASSES = frozenset({"Monster", "SummonedMonster"})


def _print_entities(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("entities")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _row_guid(value: object) -> int | None:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _row_attacking(row: dict[str, Any]) -> bool:
    return row.get("atk") in (1, True)


def me_guid_from_print_state(snapshot: dict[str, Any] | None) -> int | None:
    """MyPlayer guid (entity +0x18) from the same print_state snapshot."""
    for row in _print_entities(snapshot):
        if str(row.get("class") or "") not in _ME_CLASSES:
            continue
        key = _row_guid(row.get("guid"))
        if key is not None:
            return key
    return None


def attacks_targeting_me(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Monster and summon rows whose AttackAction target is MyPlayer.

    ``atk`` / ``owner`` / ``tgt`` come from print_state. A row with no live
    target is not an attacker. Callers match ``guid``, not a second cell.
    """
    me = me_guid_from_print_state(snapshot)
    if me is None:
        return []
    out: list[dict[str, Any]] = []
    for row in _print_entities(snapshot):
        if str(row.get("class") or "") not in _ATTACKER_CLASSES:
            continue
        if not _row_attacking(row):
            continue
        if _row_guid(row.get("tgt")) != me:
            continue
        out.append(row)
    return out


def player_targeting_me(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Another Player whose AttackAction target is MyPlayer."""
    me = me_guid_from_print_state(snapshot)
    if me is None:
        return None
    for row in _print_entities(snapshot):
        if str(row.get("class") or "") != "Player":
            continue
        if _row_guid(row.get("guid")) == me:
            continue
        if not _row_attacking(row):
            continue
        if _row_guid(row.get("tgt")) != me:
            continue
        return row
    return None


def contested_monster_guids(
    snapshot: dict[str, Any] | None,
    *,
    ignore_names: set[str] | None = None,
) -> set[int]:
    """Monster guids targeted by another Player, or a summon not owned by me.

    The claim is the monster's ``guid``, the same id handoff stores as
    ``memory_guid``. My own attacks and my summons are not claims. A name in
    ``ignore_names`` is a party member: their attack is not a claim either.
    """
    me = me_guid_from_print_state(snapshot)
    entities = _print_entities(snapshot)
    ignored = {_fold_name(name) for name in (ignore_names or set()) if str(name).strip()}
    allies: set[int] = set()
    if ignored:
        for row in entities:
            if str(row.get("class") or "") != "Player":
                continue
            if _fold_name(str(row.get("name") or "")) not in ignored:
                continue
            key = _row_guid(row.get("guid"))
            if key is not None:
                allies.add(key)
    monsters: set[int] = set()
    for row in entities:
        if str(row.get("class") or "") != "Monster":
            continue
        key = _row_guid(row.get("guid"))
        if key is not None:
            monsters.add(key)
    claimed: set[int] = set()
    for row in entities:
        cls = str(row.get("class") or "")
        if cls == "Player":
            guid = _row_guid(row.get("guid"))
            if me is not None and guid == me:
                continue
            if guid is not None and guid in allies:
                continue
        elif cls == "SummonedMonster":
            owner = _row_guid(row.get("owner"))
            if owner is None or (me is not None and owner == me):
                continue
            if owner is not None and owner in allies:
                continue
        else:
            continue
        if not _row_attacking(row):
            continue
        tgt = _row_guid(row.get("tgt"))
        if tgt is not None and tgt in monsters:
            claimed.add(tgt)
    return claimed


def monster_band(level: int) -> str:
    """Same v1 bands World already parses. Unknown levels must not use this."""
    level = int(level)
    if level <= 10:
        return "monster_1-10"
    if level <= 20:
        return "monster_11-20"
    if level <= 30:
        return "monster_21-30"
    if level <= 40:
        return "monster_31-40"
    return "monster_41-"


def default_state_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "analysis"
        / "entities"
        / "state.json"
    )


def _fold_name(text: str) -> str:
    return "".join(str(text).split()).lower()


def load_species_aliases(path: Optional[Path] = None) -> dict[str, str]:
    """Display name → ``monster_*`` catalog key (ko / zh / en / game aliases)."""
    global _alias_index
    if path is None and _alias_index is not None:
        return _alias_index
    from app._03_world.catalog.game_catalog import monster_alias_index

    src = path or _ALIASES_PATH
    aliases: dict[str, str] = dict(monster_alias_index())
    if src.is_file():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        raw = data.get("aliases") if isinstance(data, dict) else None
        if isinstance(raw, dict):
            for key, value in raw.items():
                label = str(key).strip()
                catalog = str(value).strip()
                if not label or not catalog:
                    continue
                if not catalog.lower().startswith("monster_"):
                    catalog = f"monster_{catalog}"
                aliases[label] = catalog
                aliases[label.lower()] = catalog
                aliases[_fold_name(label)] = catalog
    if path is None:
        _alias_index = aliases
    return aliases


def resolve_catalog_key(
    display: str,
    *,
    species_id: int = 0,
    id_table: Optional[dict[int, dict[str, Any]]] = None,
    aliases: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Map a memory display name like ``고블린`` onto the catalog row."""
    from app._03_world.catalog.game_catalog import resolve_monster_key, _strip_monster_prefix

    table = id_table or {}
    known = table.get(int(species_id)) if species_id else None
    if isinstance(known, dict):
        forced = str(known.get("name") or "").strip()
        if forced:
            return resolve_monster_key(forced) or (
                forced if forced.lower().startswith("monster_") else f"monster_{forced}"
            )
    text = str(display or "").strip()
    if not text:
        return None
    index = aliases if aliases is not None else load_species_aliases()
    from app._03_world.catalog.zh_convert import chinese_aliases

    queries = [text, _strip_monster_prefix(text)]
    queries.extend(chinese_aliases(text))
    queries.extend(chinese_aliases(_strip_monster_prefix(text)))
    seen: set[str] = set()
    for raw in queries:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        for candidate in (raw, raw.lower(), _fold_name(raw)):
            found = index.get(candidate)
            if found:
                return found
    return resolve_monster_key(text)


def load_species_ids(path: Optional[Path] = None) -> dict[int, dict[str, Any]]:
    """``species id → {name, level}``. Missing file or blank ids is empty."""
    src = path or _SPECIES_PATH
    if not src.is_file():
        return {}
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    table: dict[int, dict[str, Any]] = {}
    for key, row in raw.items():
        try:
            species_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        entry: dict[str, Any] = {}
        name = str(row.get("name") or "").strip()
        if name:
            entry["name"] = name
        if row.get("level") is not None:
            try:
                entry["level"] = int(row["level"])
            except (TypeError, ValueError):
                pass
        if entry:
            table[species_id] = entry
    return table


class TrackIds:
    """Stable int ids for heap addresses. Dropped addresses are forgotten."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._next = 1

    def resolve(self, ent: str) -> int:
        key = str(ent)
        found = self._ids.get(key)
        if found is not None:
            return found
        assigned = self._next
        self._next += 1
        self._ids[key] = assigned
        return assigned

    def prune(self, live: set[str]) -> None:
        for key in list(self._ids):
            if key not in live:
                self._ids.pop(key, None)


def _on_screen(x: float, y: float, width: float, height: float) -> bool:
    return 0.0 <= x <= width and 0.0 <= y <= height


def _xy_pair(block: Any) -> tuple[float, float] | None:
    if not isinstance(block, dict):
        return None
    try:
        return float(block["x"]), float(block["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _entity_screen_xy(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    """Entity click/position uses interpolated ``iscr`` only (not raw ``screen``)."""
    point = _xy_pair(raw.get("iscr"))
    if point is None:
        return None, None
    return point


def _species_fields(
    coarse: str,
    display: str,
    species_id: int,
    table: dict[int, dict[str, Any]],
    *,
    aliases: Optional[dict[str, str]] = None,
) -> tuple[dict[str, Any], bool]:
    """Return extra vision fields and whether a monster level is known."""
    known = table.get(species_id) or {}
    named = str(display or "").strip()
    if coarse != "monster":
        detail = _DETAIL.get(coarse, coarse)
        fields: dict[str, Any] = {
            "detail_classification": detail,
            "detail_classification_confidence": 1.0,
        }
        if named:
            fields["species_name"] = named
            fields["species_confidence"] = 1.0
        return fields, True

    catalog = resolve_catalog_key(
        display, species_id=species_id, id_table=table, aliases=aliases
    )
    level = None
    if known.get("level") is not None:
        try:
            level = int(known["level"])
        except (TypeError, ValueError):
            level = None
    if level is None and catalog:
        level = monster_level_from_species(catalog)
    if level is None:
        fields = {}
        if named:
            fields["species_name"] = named
            fields["species_confidence"] = 1.0
        return fields, False
    if catalog is None:
        catalog = f"monster_{named}" if named else "monster"

    species = catalog
    suffix = f"_{int(level)}"
    if not species.endswith(suffix):
        species = f"{species}{suffix}"
    return {
        "species_name": species,
        "species_confidence": 1.0,
        "detail_classification": monster_band(int(level)),
        "detail_classification_confidence": 1.0,
    }, True


def entities_to_handoff(
    snapshot: dict[str, Any],
    *,
    id_map: Optional[TrackIds] = None,
    species: Optional[dict[int, dict[str, Any]]] = None,
    aliases: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """On-screen print_state entities as perception handoff dicts."""
    width = float(snapshot.get("client_w") or 0)
    height = float(snapshot.get("client_h") or 0)
    if width < 1 or height < 1:
        return []
    table = species if species is not None else load_species_ids()
    name_index = aliases if aliases is not None else load_species_aliases()
    tracks = id_map
    rows: list[dict[str, Any]] = []
    live: set[str] = set()
    for raw in snapshot.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        coarse = _COARSE.get(str(raw.get("class") or ""))
        if coarse is None:
            continue
        sx, sy = _entity_screen_xy(raw)
        on_screen = (
            sx is not None
            and sy is not None
            and _on_screen(sx, sy, width, height)
        )
        world_block = raw.get("world") if isinstance(raw.get("world"), dict) else {}
        try:
            world_cx = int(world_block["cx"])
            world_cy = int(world_block["cy"])
        except (KeyError, TypeError, ValueError):
            world_cx = None
            world_cy = None
        # Ground piles often project just off the client. Keep them when the
        # same sweep still has a world cell so loot can walk to the pile.
        if not on_screen and not (coarse == "item" and world_cx is not None):
            continue
        ent = str(raw.get("ent") or "")
        if not ent:
            continue
        live.add(ent)
        try:
            species_id = int(raw.get("species") or 0)
        except (TypeError, ValueError):
            species_id = 0
        display = str(raw.get("name") or "").strip()
        class_name = str(raw.get("class") or "")
        if not display and class_name.upper() == "ADENA":
            display = "adena"
        extra, _known = _species_fields(
            coarse, display, species_id, table, aliases=name_index
        )
        if on_screen:
            pos_x = float(sx) / width
            pos_y = float(sy) / height
        else:
            pos_x = 0.5
            pos_y = 0.5
        row = {
            "track_id": tracks.resolve(ent) if tracks is not None else len(rows) + 1,
            "label": "object",
            "class_id": 0,
            "yolo_conf": 1.0,
            "position_x": pos_x,
            "position_y": pos_y,
            "velocity_x": 0.0,
            "velocity_y": 0.0,
            "width_ratio": 0.0,
            "height_ratio": 0.0,
            "classification": coarse,
            "classification_confidence": 1.0,
            "occluded": False,
            "frames_lost": 0,
            "memory_species_id": species_id,
            "memory_name": display,
        }
        if world_cx is not None and world_cy is not None:
            row["world_cx"] = world_cx
            row["world_cy"] = world_cy
            player = snapshot.get("player") if isinstance(snapshot.get("player"), dict) else {}
            try:
                row["world_rx"] = world_cx - int(player["x"])
                row["world_ry"] = world_cy - int(player["y"])
            except (KeyError, TypeError, ValueError):
                pass
            if not on_screen and "world_rx" in row and "world_ry" in row:
                from app._03_world.space.world_coords import world_to_content

                content = world_to_content(
                    float(row["world_rx"]), float(row["world_ry"])
                )
                row["position_x"] = content.x
                row["position_y"] = content.y
        if bool(raw.get("bait")):
            row["bait"] = True
        guid = str(raw.get("guid") or "").strip()
        if guid and guid != "0x0":
            row["memory_guid"] = guid
        own = str(raw.get("own") or "").strip()
        if own and own != "-":
            row["loot_own"] = own
        contrib_raw = raw.get("contrib")
        if contrib_raw is not None and contrib_raw != -1:
            try:
                row["loot_contrib"] = int(contrib_raw)
            except (TypeError, ValueError):
                pass
        qty_raw = raw.get("qty")
        if qty_raw is not None and qty_raw != -1:
            try:
                row["loot_qty"] = int(qty_raw)
            except (TypeError, ValueError):
                pass
        row.update(extra)
        rows.append(row)
    if tracks is not None:
        tracks.prune(live)
    return rows


# Historical name — same function as ``entities_to_handoff``.
entities_to_vision = entities_to_handoff


def project_memory_to_content(
    rows: list[dict[str, Any]],
    *,
    client_w: float,
    client_h: float,
    crop_left: float = 0.0,
    crop_top: float = 0.0,
    crop_w: float | None = None,
    crop_h: float | None = None,
) -> list[dict[str, Any]]:
    """Client-ratio memory rows → content-crop ratios used by clicks.

    Points in the pillarbox or letterbox are dropped. A 4:3 client with no
    crop leaves the ratios unchanged.
    """
    width = float(client_w)
    height = float(client_h)
    if width < 1 or height < 1:
        return []
    frame_w = width if crop_w is None else float(crop_w)
    frame_h = height if crop_h is None else float(crop_h)
    if frame_w < 1 or frame_h < 1:
        return []
    projected: list[dict[str, Any]] = []
    for row in rows:
        sx = float(row.get("position_x") or 0.0) * width
        sy = float(row.get("position_y") or 0.0) * height
        nx = (sx - float(crop_left)) / frame_w
        ny = (sy - float(crop_top)) / frame_h
        if nx < -1e-4 or ny < -1e-4 or nx > 1.0 + 1e-4 or ny > 1.0 + 1e-4:
            continue
        copied = dict(row)
        copied["position_x"] = min(1.0, max(0.0, nx))
        copied["position_y"] = min(1.0, max(0.0, ny))
        projected.append(copied)
    return projected


def resolve_entity_source(value: str | None) -> str:
    """Farm entity clicks are always memory (print_state).

    Legacy ``vision`` / ``hybrid`` config values are coerced to ``memory``.
    """
    _ = value
    return "memory"


def entity_source_is_legacy(value: str | None) -> bool:
    """True when config still names a removed farm-vision mode."""
    return str(value or "").strip().lower() in ("vision", "hybrid")


def decision_rows(
    source: str | None,
    vision_rows: list[dict[str, Any]] | None,
    memory_rows: list[dict[str, Any]] | None,
    *,
    sweep_ok: bool,
    hold_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Rows for ``update_from_perception`` (memory-only).

    ``source`` / ``vision_rows`` / ``hold_rows`` are ignored. Failed sweep
    yields an empty list — no stale hold.
    """
    _ = (source, vision_rows, hold_rows)
    if sweep_ok:
        return list(memory_rows or []), "memory"
    return [], "memory"


def align_memory_rows(
    rows: list[dict[str, Any]],
    snapshot: dict[str, Any] | None,
    content: Any,
) -> list[dict[str, Any]]:
    """Project memory rows into the content frame used by clicks."""
    snap = snapshot or {}
    client_w = float(snap.get("client_w") or 0)
    client_h = float(snap.get("client_h") or 0)
    crop_left = 0.0
    crop_top = 0.0
    crop_w: float | None = None
    crop_h: float | None = None
    if content is not None and bool(getattr(content, "valid", False)):
        crop_left = float(content.left)
        crop_top = float(content.top)
        crop_w = float(content.width)
        crop_h = float(content.height)
    return project_memory_to_content(
        rows,
        client_w=client_w,
        client_h=client_h,
        crop_left=crop_left,
        crop_top=crop_top,
        crop_w=crop_w,
        crop_h=crop_h,
    )


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("classification") or "?")
        counts[key] = counts.get(key, 0) + 1
    return counts


def fill_unleveled_from_vision(
    memory: list[dict[str, Any]],
    vision: list[dict[str, Any]],
    *,
    match_radius: float = 0.08,
) -> int:
    """Copy a nearby vision level onto memory monsters the name table missed.

    Unused by the live bot (farm vision removed). Kept for unit tests / tools.
    Vision rows are not changed. Returns how many memory rows received a level.
    """
    used: set[int] = set()
    filled = 0
    pending: list[tuple[float, int, int]] = []
    for mem_i, mem in enumerate(memory):
        if mem.get("classification") != "monster":
            continue
        if monster_level_for_object(
            mem.get("species_name"), mem.get("detail_classification")
        ) is not None:
            continue
        mx = float(mem.get("position_x") or 0.0)
        my = float(mem.get("position_y") or 0.0)
        best_i = -1
        best_d = match_radius
        for index, vis in enumerate(vision):
            if vis.get("classification") != "monster":
                continue
            if monster_level_for_object(
                vis.get("species_name"), vis.get("detail_classification")
            ) is None:
                continue
            dx = float(vis.get("position_x") or 0.0) - mx
            dy = float(vis.get("position_y") or 0.0) - my
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_d:
                best_d = dist
                best_i = index
        if best_i >= 0:
            pending.append((best_d, mem_i, best_i))
    pending.sort()
    for _dist, mem_i, vis_i in pending:
        if vis_i in used:
            continue
        used.add(vis_i)
        vis = vision[vis_i]
        mem = memory[mem_i]
        for key in (
            "species_name",
            "species_confidence",
            "detail_classification",
            "detail_classification_confidence",
        ):
            if vis.get(key) is not None:
                mem[key] = vis[key]
        mem["level_source"] = "vision"
        filled += 1
    return filled


def summarize_shadow(
    vision: list[dict[str, Any]],
    memory: list[dict[str, Any]],
    *,
    match_radius: float = 0.12,
) -> str:
    """One line: how memory entities line up with the vision list."""
    used: set[int] = set()
    paired = 0
    distances: list[float] = []
    for mem in memory:
        best_i = -1
        best_d = match_radius
        mx = float(mem.get("position_x") or 0.0)
        my = float(mem.get("position_y") or 0.0)
        kind = mem.get("classification")
        for index, vis in enumerate(vision):
            if index in used or vis.get("classification") != kind:
                continue
            dx = float(vis.get("position_x") or 0.0) - mx
            dy = float(vis.get("position_y") or 0.0) - my
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_d:
                best_d = dist
                best_i = index
        if best_i >= 0:
            used.add(best_i)
            paired += 1
            distances.append(best_d)
    median = 0.0
    if distances:
        ordered = sorted(distances)
        median = ordered[len(ordered) // 2]
    unleveled: list[str] = []
    for mem in memory:
        if mem.get("classification") != "monster":
            continue
        if mem.get("detail_classification"):
            continue
        species_id = mem.get("memory_species_id")
        name = mem.get("memory_name") or "?"
        token = f"{species_id}:{name}"
        if token not in unleveled:
            unleveled.append(token)
    vis_n = _counts(vision)
    mem_n = _counts(memory)
    extra = ""
    if unleveled:
        extra = " unleveled=" + ",".join(unleveled[:8])
    return (
        f"Entity shadow: vision={len(vision)} {vis_n} memory={len(memory)} {mem_n} "
        f"paired={paired} median={median:.3f}{extra}"
    )


def read_last_json_line(path: Path) -> Optional[dict[str, Any]]:
    """Last complete JSON object in a JSONL file. None if unreadable."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - 262144))
            chunk = handle.read()
    except OSError:
        return None
    text = chunk.decode("utf-8", errors="ignore")
    lines = [line for line in text.splitlines() if line.strip()]
    if size > 262144 and len(lines) > 1:
        lines = lines[1:]
    for line in reversed(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


# LiveEntitySweep / EntityShadow live in app._01_perception.entity_sweep
# (Tools/research only — not the live bot tick).