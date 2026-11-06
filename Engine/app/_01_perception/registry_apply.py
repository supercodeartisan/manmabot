"""Apply a copied dist registry onto the files the bot listeners already read.

Copy the contents of a memory-team dist folder into ``Engine/analysis``.
That places ``registry/LC930_REGISTRY.txt`` at
``Engine/analysis/registry/LC930_REGISTRY.txt``. The next bot start reads
that file and rewrites the listener tables (character, entities, inventory,
hotbar, party, combat settings) from it. Restart the bot after the copy.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[2]
_ANALYSIS = _ENGINE / "analysis"
_DROP = _ANALYSIS / "registry" / "LC930_REGISTRY.txt"
_PARTY_KEYS = _ANALYSIS / "registry" / "PARTY_SEC17.txt"
_STAMP = _ANALYSIS / "registry" / ".applied.sha"
_DIST = _ENGINE / "dist" / "registry" / "LC930_REGISTRY.txt"

_CHAR_MAP = {
    "MGR": "MGR",
    "CD_VFT": "CD_VFT",
    "VFT_STATUS": "VFT_STATUS",
    "CD_OFF": "CD_OFF",
    "K_XOR": "K_XOR",
    "K_MUL": "K_MUL",
    "HOLDER_OFF": "HOLDER_OFF",
    "SUBLIST_BEG": "SUBB",
    "ST_BLOCK": "ST_BLOCK",
    "ST_X": "ST_X",
    "ST_Y": "ST_Y",
    "ST_HP": "ST_HP",
    "ST_MAXHP": "ST_MAXHP",
    "ST_MP": "ST_MP",
    "ST_MAXMP": "ST_MAXMP",
    "ST_LEVEL": "ST_LEVEL",
    "STR": "STAT_STR",
    "DEX": "STAT_DEX",
    "CON": "STAT_CON",
    "WIS": "STAT_WIS",
    "CHA": "STAT_CHA",
    "INT": "STAT_INT",
    "LEVEL": "STAT_LEVEL",
    "HP": "STAT_HP",
    "MAXHP": "STAT_MAXHP",
    "MP": "STAT_MP",
    "MAXMP": "STAT_MAXMP",
    "FOOD": "STAT_FOOD",
    "WEIGHT": "STAT_WEIGHT",
    "WEIGHT_CUR": "STAT_WEIGHT_CUR",
    "WEIGHT_MAX": "STAT_WEIGHT_MAX",
    "LAWFUL": "STAT_LAWFUL",
    "AC": "STAT_AC",
}


def parse_registry(path: Path) -> dict[str, str]:
    """First KEY=VALUE wins, matching lcreg_raw."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        if key and key not in out:
            out[key] = value
    return out


def _u32(reg: dict[str, str], key: str) -> int | None:
    raw = reg.get(key)
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def _hx(value: int) -> str:
    return f"0x{value:X}"


def _need(reg: dict[str, str], *keys: str) -> int:
    for key in keys:
        value = _u32(reg, key)
        if value is not None:
            return value
    raise KeyError(keys[0])


def source_registry() -> Path | None:
    """Registry a dist copy drops into Engine/analysis."""
    if _DROP.is_file():
        return _DROP
    if _DIST.is_file():
        _DROP.parent.mkdir(parents=True, exist_ok=True)
        _DROP.write_bytes(_DIST.read_bytes())
        return _DROP
    return None


def _set_kv(path: Path, updates: dict[str, str]) -> None:
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key = raw.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _set_json(path: Path, updates: dict[str, object]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for key, value in updates.items():
        if isinstance(value, str):
            rendered = json.dumps(value)
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        pattern = re.compile(
            rf'("{re.escape(key)}"\s*:\s*)(?:"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?)'
        )
        text, count = pattern.subn(rf"\g<1>{rendered}", text, count=1)
        if count == 0 and text.rstrip().endswith("}"):
            body = text.rstrip()
            tail = "\n" if text.endswith("\n") else ""
            cut = body[:-1].rstrip()
            comma = "," if cut and not cut.endswith("{") else ""
            text = f"{cut}{comma}\n  {json.dumps(key)}: {rendered}\n}}{tail}"
    path.write_text(text, encoding="utf-8")


def _publish_registry(drop: Path, reg: dict[str, str]) -> None:
    """Readers open ``registry/LC930_REGISTRY.txt`` itself. No second copy."""
    del drop, reg


def _party_vfts(reg: dict[str, str]) -> None:
    updates = {}
    for key in ("PARTY_VFT_SUBS", "PARTY_VFT_RC", "PARTY_VFT_RC_PLAYER"):
        value = _u32(reg, key)
        if value is not None:
            updates[key] = _hx(value)
    build = reg.get("BUILD")
    if build:
        updates["PARTY_BUILD"] = build
    if _PARTY_KEYS.is_file():
        _set_kv(_PARTY_KEYS, updates)


def _char_offsets(reg: dict[str, str]) -> None:
    updates: dict[str, str] = {}
    for dest, src in _CHAR_MAP.items():
        value = _u32(reg, src)
        if value is not None:
            updates[dest] = _hx(value)
    path = _ANALYSIS / "registry" / "char_offsets.txt"
    _set_kv(path, updates)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "# dist charread retired the static HUD block. 0 disables that fallback.\n",
            "# Static HUD block. ST_* values are copied from the registry.\n",
        )
        path.write_text(text, encoding="utf-8")


def _entity_files(reg: dict[str, str]) -> None:
    mgr = _u32(reg, "MGR")
    block = _u32(reg, "ST_BLOCK")
    names = (
        ("VFT_SELF", "MyPlayer"),
        ("VFT_PLAYER", "Player"),
        ("VFT_NPC", "InteractiveNPC"),
        ("VFT_MONSTER", "Monster"),
        ("VFT_ITEM", "Item"),
        ("VFT_SEGPROP", "SegmentProp"),
        ("VFT_SHIP", "Ship"),
        ("VFT_SUMMON", "SummonedMonster"),
        ("VFT_ACTOR", "Actor"),
    )
    parts: list[str] = []
    classes: list[str] = []
    for key, _label in names:
        value = _u32(reg, key)
        if value is None:
            continue
        parts.append(f"{value:X}")
    role_order = (
        ("VFT_AC", "ActionComponent"),
        ("VFT_DEATH", "DeathAction"),
        ("VFT_DEADBODY", "AppearDeadBody"),
        ("VFT_MONSTER", "Monster"),
        ("VFT_ACTOR", "Actor"),
        ("VFT_ITEM", "Item"),
        ("VFT_SHIP", "Ship"),
        ("VFT_SUMMON", "SummonedMonster"),
        ("VFT_PLAYER", "Player"),
        ("VFT_SELF", "MyPlayer"),
        ("VFT_NPC", "InteractiveNPC"),
        ("VFT_SEGPROP", "SegmentProp"),
    )
    for key, label in role_order:
        value = _u32(reg, key)
        if value is not None:
            classes.append(f"{value:X}:{label}")
    updates: dict[str, str] = {}
    if mgr is not None:
        updates["MGR"] = _hx(mgr)
    actor = _u32(reg, "VFT_ACTORSUBS")
    if actor is not None:
        updates["ACTOR_VFT"] = _hx(actor)
    for dest, src in (
        ("ACTOR_VEC_OFF", "ACTOR_VEC_OFF"),
        ("ACTOR_VEC_END", "ACTOR_VEC_END"),
        ("VFT_PRES_A", "VFT_PRES_A"),
        ("VFT_PRES_B", "VFT_PRES_B"),
        ("OFF_LIVE_U", "OFF_LIVE_U"),
        ("OFF_LIVE_V", "OFF_LIVE_V"),
    ):
        value = _u32(reg, src)
        if value is not None:
            updates[dest] = _hx(value)
    ac = _u32(reg, "VFT_AC")
    if ac is not None:
        updates["ACT_VFT"] = f"{ac:X}"
    for dest, src in (
        ("ATTACK_ACT_VFT", "VFT_ATTACKACT"),
        ("DEATH_VFT", "VFT_DEATH"),
        ("DEADBODY_VFT", "VFT_DEADBODY"),
        ("VFT_MONSTER", "VFT_MONSTER"),
        ("VFT_ACTOR", "VFT_ACTOR"),
        ("VFT_ITEM", "VFT_ITEM"),
        ("VFT_SHIP", "VFT_SHIP"),
        ("VFT_SUMMONED", "VFT_SUMMON"),
        ("VFT_PLAYER", "VFT_PLAYER"),
        ("VFT_SELF", "VFT_SELF"),
        ("VFT_INTERACT", "VFT_NPC"),
        ("VFT_INTERACTIVE", "VFT_NPC"),
    ):
        value = _u32(reg, src)
        if value is not None:
            updates[dest] = f"{value:X}"
    monster = _u32(reg, "VFT_MONSTER")
    summon = _u32(reg, "VFT_SUMMON")
    if monster is not None and summon is not None:
        updates["MON_VFTS"] = f"{monster:X},{summon:X}"
    if parts:
        updates["ENT_VFT_SET"] = ",".join(parts)
    if classes:
        updates["CLASSES"] = ",".join(classes)
    px = _u32(reg, "PLAYER_X")
    py = _u32(reg, "PLAYER_Y")
    if px is not None:
        updates["PLAYER_X"] = f"{px:X}"
    if py is not None:
        updates["PLAYER_Y"] = f"{py:X}"
    if block is not None:
        for dest, src, default in (
            ("PLAYER_HP", "ST_HP", 0xC),
            ("PLAYER_MAXHP", "ST_MAXHP", 0x10),
            ("PLAYER_MP", "ST_MP", 0x14),
            ("PLAYER_MAXMP", "ST_MAXMP", 0x18),
            ("PLAYER_LEVEL", "ST_LEVEL", 0x1C),
        ):
            off = _u32(reg, src)
            updates[dest] = f"{block + (off if off is not None else default):X}"
    cam = _u32(reg, "CAM_GLOB")
    if cam:
        updates["CAM_GLOB"] = f"{cam:X}"
    _set_kv(_ANALYSIS / "registry" / "entity_offsets.txt", updates)

    settings = _ANALYSIS / "registry" / "settings_print_state.json"
    json_updates: dict[str, object] = {}
    if px is not None:
        json_updates["player_x_offset"] = _hx(px)
    if py is not None:
        json_updates["player_y_offset"] = _hx(py)
    if block is not None:
        json_updates["player_hp_offset"] = _hx(block + (_u32(reg, "ST_HP") or 0xC))
        json_updates["player_maxhp_offset"] = _hx(block + (_u32(reg, "ST_MAXHP") or 0x10))
        json_updates["player_mp_offset"] = _hx(block + (_u32(reg, "ST_MP") or 0x14))
        json_updates["player_maxmp_offset"] = _hx(block + (_u32(reg, "ST_MAXMP") or 0x18))
        json_updates["player_level_offset"] = _hx(block + (_u32(reg, "ST_LEVEL") or 0x1C))
    if mgr is not None:
        json_updates["ent_mgr_offset"] = _hx(mgr)
    if actor is not None:
        json_updates["grid_vft"] = _hx(actor)
    pres_a = _u32(reg, "VFT_PRES_A")
    pres_b = _u32(reg, "VFT_PRES_B")
    if pres_a is not None:
        json_updates["vft_pres_a"] = _hx(pres_a)
    if pres_b is not None:
        json_updates["vft_pres_b"] = _hx(pres_b)
    _set_json(settings, json_updates)
    if settings.is_file() and classes:
        text = settings.read_text(encoding="utf-8")
        rows = []
        world = (
            ("VFT_MONSTER", "Monster"),
            ("VFT_NPC", "InteractiveNPC"),
            ("VFT_ITEM", "Item"),
            ("VFT_SELF", "MyPlayer"),
            ("VFT_SEGPROP", "SegmentProp"),
            ("VFT_SHIP", "Ship"),
            ("VFT_SUMMON", "SummonedMonster"),
            ("VFT_PLAYER", "Player"),
        )
        for key, label in world:
            value = _u32(reg, key)
            if value is not None:
                rows.append(f'    "{_hx(value)}": "{label}"')
        block_text = "{\n" + ",\n".join(rows) + "\n  }"
        text = re.sub(r'"classes"\s*:\s*\{[^}]*\}', f'"classes": {block_text}', text, count=1)
        settings.write_text(text, encoding="utf-8")


def _combat(reg: dict[str, str]) -> None:
    block = _u32(reg, "ST_BLOCK") or 0
    common = {
        "ent_mgr_offset": _hx(_need(reg, "MGR")),
        "grid_vft": _hx(_need(reg, "VFT_ACTORSUBS")),
        "act_vft": _hx(_need(reg, "VFT_AC")),
        "attack_act_vft": _hx(_need(reg, "VFT_ATTACKACT")),
        "vft_self": _hx(_need(reg, "VFT_SELF")),
        "vft_player": _hx(_need(reg, "VFT_PLAYER")),
        "vft_monster": _hx(_need(reg, "VFT_MONSTER")),
        "vft_summon": _hx(_need(reg, "VFT_SUMMON")),
        "player_x_offset": _hx(block),
        "player_y_offset": _hx(block + (_u32(reg, "ST_Y") or 4)),
    }
    for name in ("settings_attacks_me.json", "settings_contested_mobs.json"):
        _set_json(_ANALYSIS / "registry" / name, common)


def _inventory_hotbar(reg: dict[str, str]) -> None:
    inv = {
        "MGR": _hx(_need(reg, "MGR")),
        "INV_VFT": _hx(_need(reg, "INV_VFT", "VFT_INVENTORY")),
        "ITEM_VFT": _hx(_need(reg, "ITEM_VFT")),
        "MSG_ANCHOR_RVA": _hx(_need(reg, "MSG_ANCHOR_RVA")),
    }
    for dest, src in (
        ("INV_VEC_BEG", "INV_VEC_BEG"),
        ("INV_VEC_END", "INV_VEC_END"),
        ("ITEM_ID", "ITEM_ID"),
        ("ITEM_CFG", "ITEM_CFG"),
        ("ITEM_COUNT", "ITEM_COUNT"),
        ("ITEM_KIND", "ITEM_KIND"),
        ("ITEM_FMT", "ITEM_FMT"),
    ):
        value = _u32(reg, src)
        if value is not None:
            inv[dest] = _hx(value)
    _set_kv(_ANALYSIS / "registry" / "inventory_offsets.txt", inv)
    module = reg.get("MODULE_SIZE")
    item = _u32(reg, "ITEM_VFT")
    map_vft = _u32(reg, "VFT_MAPSUBS")
    json_updates: dict[str, object] = {}
    if module:
        json_updates["_moduleSize"] = module if module.startswith("0x") else _hx(int(module, 0))
    if map_vft is not None:
        json_updates["MapSubsystemVftRva"] = _hx(map_vft)
    if item is not None:
        json_updates["ItemEntityVtableRva"] = _hx(item)
    _set_json(_ANALYSIS / "registry" / "inventory_offsets.json", json_updates)

    hot = {"MGR": _hx(_need(reg, "MGR"))}
    primary = _u32(reg, "VFT_HUDSLOT")
    secondary = _u32(reg, "HUD_VFT")
    adj = _u32(reg, "HSD_MAP_OFF")
    if secondary is not None:
        hot["HSD_VFT"] = f"{secondary:X}"
    if primary is not None:
        hot["HSD_VFT2"] = f"{primary:X}"
    if adj is not None:
        hot["HSD_ADJ"] = _hx(adj)
    _set_kv(_ANALYSIS / "registry" / "skill_offsets.txt", hot)


def _player_json(reg: dict[str, str]) -> None:
    block = _u32(reg, "ST_BLOCK")
    hp_off = _u32(reg, "ST_HP") or 0
    updates: dict[str, object] = {}
    module = reg.get("MODULE_SIZE")
    if module:
        updates["_moduleSize"] = module if str(module).startswith("0x") else _hx(int(module, 0))
    map_vft = _u32(reg, "VFT_MAPSUBS")
    if map_vft is not None:
        updates["MapSubsystemVftRva"] = _hx(map_vft)
    map_id = _u32(reg, "MAP_ID_OFF")
    if map_id is not None:
        updates["MapIdOff"] = _hx(map_id)
    pair = _u32(reg, "MAP_ID_PAIR_OFF")
    if pair is not None:
        updates["MapIdPairOff"] = _hx(pair)
    if block is not None:
        updates["PlayerBase"] = block + hp_off
    px = _u32(reg, "PLAYER_X")
    py = _u32(reg, "PLAYER_Y")
    if px is not None:
        updates["PosXAbs"] = px
    if py is not None:
        updates["PosYAbs"] = py
    exp = _u32(reg, "ExperiencePct64")
    if exp is not None:
        updates["ExperiencePct64"] = exp
    _set_json(_ANALYSIS / "registry" / "offsets.json", updates)


def apply_registry(force: bool = False) -> Path | None:
    """Rewrite listener tables from the dropped registry. No-op when unchanged."""
    drop = source_registry()
    if drop is None or not drop.is_file():
        return None
    digest = hashlib.sha256(drop.read_bytes()).hexdigest()
    if (
        not force
        and _STAMP.is_file()
        and _STAMP.read_text(encoding="utf-8").strip() == digest
    ):
        return drop
    reg = parse_registry(drop)
    if "MGR" not in reg or "VFT_MAPSUBS" not in reg:
        return drop
    _publish_registry(drop, reg)
    _char_offsets(reg)
    _entity_files(reg)
    _combat(reg)
    _inventory_hotbar(reg)
    _player_json(reg)
    _party_vfts(reg)
    _STAMP.parent.mkdir(parents=True, exist_ok=True)
    _STAMP.write_text(digest + "\n", encoding="utf-8")
    return drop
