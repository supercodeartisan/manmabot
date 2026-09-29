"""Constants and configuration for the World module."""
from __future__ import annotations

from typing import Iterable

from .objects import ObjectType


# Monster level mapping for weak/strong classification
MONSTER_LEVELS: dict[str, int] = {
    "bat": 5,
    "spider": 8,
    "skeleton": 12,
    "zombie": 15,
    "ghost": 18,
    "wolf": 10,
    "goblin": 14,
    "orc": 20,
    "troll": 25,
    "dragon": 50,
}

# Player level assumed while OCR has not populated the real value.
# Used by weak/strong monster classification in GameState.
DEFAULT_PLAYER_LEVEL = 10

# Synthetic track id for PlayerState (not a vision track).
LOCAL_PLAYER_TRACK_ID = -1

# Level cap assumed for the open-ended monster_41- detail band.
MONSTER_BAND_OPEN_LEVEL = 50

# Optional species→level table (same file vision uses). Loaded lazily.
_species_level_lookup: dict[str, int] | None = None

# Operator-forced levels (product v1). Win over name suffix and tables.
# Keys are species ids (``monster_오크`` or ``monster_오크_2``).
_operator_level_overrides: dict[str, int] = {}

SPECIES_LEVEL_MIN = 1
SPECIES_LEVEL_MAX = 50


def _looks_like_level_band(name: str) -> bool:
    """True for v1 bands like ``monster_1-10`` / ``monster_41-``."""
    text = name.strip().lower()
    if not text.startswith("monster_"):
        return False
    return "-" in text[len("monster_"):]


def monster_level_from_detail(detail: str | None) -> int | None:
    """Upper bound of a monster_XX-YY detail band (conservative).

    The ResNet detail head classifies monsters into level bands:
    monster_1-10, monster_11-20, monster_21-30, monster_31-40,
    monster_41- (open-ended). Prefer :func:`monster_level_from_species` when
    a v2 species name is available. Returns ``None`` when not a band.
    """
    if not detail:
        return None
    name = detail.strip().lower()
    if not name.startswith("monster_"):
        return None
    band = name[len("monster_"):]
    if "-" not in band:
        return None
    _, upper = band.split("-", 1)
    if not upper:
        # Open-ended band (e.g. monster_41-): assume the cap level.
        return MONSTER_BAND_OPEN_LEVEL
    try:
        return int(upper)
    except ValueError:
        return None


def _strip_species_level_suffix(species: str) -> str:
    parts = species.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        return "_".join(parts[:-1])
    return species


def _load_species_level_lookup() -> dict[str, int]:
    """Load catalog + ``label_tables.json`` species levels."""
    global _species_level_lookup
    if _species_level_lookup is not None:
        return _species_level_lookup
    import json
    from pathlib import Path

    from app._03_world.game_catalog import list_monster_rows

    lookup: dict[str, int] = {}
    for row in list_monster_rows():
        lookup[row.key] = int(row.level)
        lookup[row.name_ko] = int(row.level)
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "classify_model"
        / "label_tables.json"
    )
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        # Official JSON levels win. label_tables only fill unknown names.
        for table_name in ("species_level", "level_override"):
            raw = data.get(table_name) or {}
            if isinstance(raw, dict):
                for key, value in raw.items():
                    name = str(key)
                    if name in lookup:
                        continue
                    try:
                        lookup[name] = int(value)
                    except (TypeError, ValueError):
                        continue
    _species_level_lookup = lookup
    return lookup


def configure_species_level_overrides(
    overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    """Install operator-forced species levels (empty dict clears).

    Values are clamped to ``SPECIES_LEVEL_MIN`` … ``SPECIES_LEVEL_MAX``.
    """
    global _operator_level_overrides
    cleaned: dict[str, int] = {}
    for raw_key, raw_val in (overrides or {}).items():
        key = str(raw_key).strip()
        if not key:
            continue
        try:
            level = int(raw_val)
        except (TypeError, ValueError):
            continue
        cleaned[key] = max(SPECIES_LEVEL_MIN, min(SPECIES_LEVEL_MAX, level))
    _operator_level_overrides = cleaned
    return dict(_operator_level_overrides)


def get_species_level_overrides() -> dict[str, int]:
    return dict(_operator_level_overrides)


# Species ids the operator turned off. Never engage, at any character level.
_species_blacklist: set[str] = set()
_species_whitelist: set[str] = set()
_species_filter_mode = "blacklist"


def _fold_species_key(text: str) -> str:
    """``monster_오크 전사`` / ``오크전사`` → same compact id."""
    return "".join(str(text or "").split()).lower()


def _species_key_forms(text: str) -> tuple[str, ...]:
    raw = str(text or "").strip()
    if not raw:
        return ()
    stripped = _strip_species_level_suffix(raw)
    forms = (raw, stripped, raw.lower(), stripped.lower())
    folded = (_fold_species_key(raw), _fold_species_key(stripped))
    return tuple(dict.fromkeys((*forms, *folded)))


def _expand_species_keys(keys: Iterable[str]) -> set[str]:
    from app._03_world.game_catalog import monster_by_key

    expanded: set[str] = set()
    for raw in keys:
        key = str(raw).strip()
        if not key:
            continue
        expanded.update(_species_key_forms(key))
        row = monster_by_key(key) or monster_by_key(_strip_species_level_suffix(key))
        if row is None:
            continue
        for alias in row.aliases():
            expanded.update(_species_key_forms(alias))
    return expanded


def _species_listed(species: str | None, expanded: set[str]) -> bool:
    if not species or not expanded:
        return False
    return any(name in expanded for name in _species_key_forms(species))


def configure_species_blacklist(keys: Iterable[str] | None = None) -> set[str]:
    """Install operator species blacklist (empty clears). Keys are catalog ids."""
    global _species_blacklist
    cleaned: set[str] = set()
    for raw in keys or []:
        key = str(raw).strip()
        if key:
            cleaned.add(key)
    _species_blacklist = cleaned
    return set(_species_blacklist)


def configure_species_filter(
    mode: str | None = None,
    blacklist: Iterable[str] | None = None,
    whitelist: Iterable[str] | None = None,
) -> None:
    """Blacklist skips listed species. Whitelist attacks only listed species."""
    global _species_filter_mode, _species_whitelist
    cleaned = str(mode or "blacklist").strip().lower()
    _species_filter_mode = cleaned if cleaned in ("blacklist", "whitelist") else "blacklist"
    configure_species_blacklist(blacklist)
    wanted: set[str] = set()
    for raw in whitelist or []:
        key = str(raw).strip()
        if key:
            wanted.add(key)
    _species_whitelist = wanted


def get_species_blacklist() -> set[str]:
    return set(_species_blacklist)


def is_species_blacklisted(species: str | None) -> bool:
    """True when this species id (or ``_N`` variant) is operator-blacklisted."""
    return _species_listed(species, _expand_species_keys(_species_blacklist))


def is_species_filtered_out(*names: str | None) -> bool:
    """True when the operator filter says this monster must not be attacked.

    Blacklist: listed names are skipped. Whitelist: only listed names are
    attacked, including an empty list (attack nothing).
    """
    if _species_filter_mode == "whitelist":
        expanded = _expand_species_keys(_species_whitelist)
        return not any(_species_listed(name, expanded) for name in names)
    return any(is_species_blacklisted(name) for name in names)


def _operator_override_level(species: str) -> int | None:
    """Match an override on the full id or the name with ``_N`` stripped."""
    if not _operator_level_overrides:
        return None
    candidates = (species, _strip_species_level_suffix(species))
    for name in candidates:
        if name in _operator_level_overrides:
            return _operator_level_overrides[name]
    folded: dict[str, int] = {}
    for key, value in _operator_level_overrides.items():
        folded[key.lower()] = value
        folded[_strip_species_level_suffix(key).lower()] = value
    for name in candidates:
        got = folded.get(name.lower())
        if got is not None:
            return got
    return None


def species_display_name(species: str) -> str:
    """``monster_오크`` / ``monster_오크_2`` → ``오크``."""
    text = species.strip()
    lowered = text.lower()
    if lowered.startswith("monster_"):
        text = text[len("monster_") :]
    return _strip_species_level_suffix(text)


def list_species_catalog() -> list[tuple[str, int]]:
    """``(species_key, default_level)`` from the official JSON lists.

    Keys are unsuffixed ids (``monster_오크``). Default level is the catalog
    value, not an operator override. Names missing from both Korean and
    Chinese lists are omitted.
    """
    from app._03_world.game_catalog import list_monster_rows

    return [(row.key, int(row.level)) for row in list_monster_rows()]


def monster_level_from_species(species: str | None) -> int | None:
    """Exact monster level from a v2 species id (``monster_오크_2``).

    Resolution order: operator override, trailing ``_N``, then label_tables
    lookup (full name then stripped name). Level bands are rejected (use
    :func:`monster_level_from_detail`).
    """
    if not species:
        return None
    text = species.strip()
    if not text or _looks_like_level_band(text):
        return None

    forced = _operator_override_level(text)
    if forced is not None:
        return forced

    parts = text.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])

    lookup = _load_species_level_lookup()
    for name in (text, _strip_species_level_suffix(text)):
        if name in lookup:
            return lookup[name]
    lowered = {key.lower(): value for key, value in lookup.items()}
    for name in (text, _strip_species_level_suffix(text)):
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def monster_level_for_object(
    species_name: str | None,
    detail_classification: str | None = None,
) -> int | None:
    """Prefer exact species level; fall back to v1 detail band upper bound."""
    level = monster_level_from_species(species_name)
    if level is not None:
        return level
    return monster_level_from_detail(detail_classification)


def is_monster_species(species: str | None) -> bool:
    """True when ``species_name`` identifies a monster (resolvable or prefixed)."""
    if not species:
        return False
    text = species.strip()
    if not text or _looks_like_level_band(text):
        return False
    if monster_level_from_species(text) is not None:
        return True
    try:
        from app._03_world.game_catalog import resolve_monster_key

        if resolve_monster_key(text) is not None:
            return True
    except Exception:
        pass
    return text.lower().startswith("monster_")


# Live ResNet confidence floors — set only from ``config.yaml`` via
# ``configure_classification_thresholds`` (vision.coarse/detail_class_conf_min).
# Boot values match config.yaml so unit tests work before configure() runs.
_coarse_class_conf_min: float = 0.7
_detail_class_conf_min: float = 0.7


def configure_classification_thresholds(config: dict | None = None) -> tuple[float, float]:
    """Load classification gates from config.yaml (sole tunable source)."""
    global _coarse_class_conf_min, _detail_class_conf_min
    section = (config or {}).get("vision") or {}
    if "coarse_class_conf_min" not in section or "detail_class_conf_min" not in section:
        raise KeyError(
            "config.vision must define coarse_class_conf_min and detail_class_conf_min"
        )
    _coarse_class_conf_min = float(section["coarse_class_conf_min"])
    _detail_class_conf_min = float(section["detail_class_conf_min"])
    return _coarse_class_conf_min, _detail_class_conf_min


def get_classification_thresholds() -> tuple[float, float]:
    return _coarse_class_conf_min, _detail_class_conf_min


# After attacking, blacklist if the target stays on the same WCS tile this long.
ATTACK_NO_MOVE_SECONDS = 2.0


def is_monster_coarse(coarse: str | None) -> bool:
    """True when the ResNet main/coarse head says monster."""
    return bool(coarse) and coarse.strip().lower() == "monster"


def is_monster_detail(detail: str | None) -> bool:
    """True when the ResNet detail head is a monster level band."""
    return monster_level_from_detail(detail) is not None


def coarse_to_object_type(coarse: str | None) -> ObjectType:
    """Map ResNet coarse class name to ObjectType (non-monster path)."""
    if not coarse:
        return ObjectType.OTHER
    name = coarse.strip().lower()
    if name == "player":
        return ObjectType.PLAYER
    if name == "npc":
        return ObjectType.NPC
    if name in ("grounditem", "item"):
        return ObjectType.ITEM
    return ObjectType.OTHER


def object_type_from_classifiers(
    coarse: str | None,
    detail: str | None,
    coarse_conf: float | None = None,
    detail_conf: float | None = None,
    *,
    species_name: str | None = None,
    species_conf: float | None = None,
) -> ObjectType:
    """Derive ObjectType from ResNet coarse + species/detail and confidences.

    YOLO labels are detection-only and must not be used here.

    Rules:
      - coarse confidence below threshold → OTHER
      - coarse monster + (species or band) with fine confidence OK → MONSTER
      - mixed / weak fine signal → OTHER
      - neither monster → follow coarse (already confidence-gated)

    Prefer ``species_name`` when present; ``detail`` bands remain a fallback.
    Fine-head confidence uses ``species_conf`` when set, else ``detail_conf``.
    """
    c_conf = 0.0 if coarse_conf is None else float(coarse_conf)
    fine_conf = (
        float(species_conf)
        if species_conf is not None
        else (0.0 if detail_conf is None else float(detail_conf))
    )
    if c_conf < _coarse_class_conf_min:
        return ObjectType.OTHER

    coarse_monster = is_monster_coarse(coarse)
    species_monster = is_monster_species(species_name)
    detail_monster = is_monster_detail(detail)
    fine_monster = species_monster or detail_monster
    fine_ok = fine_monster and fine_conf >= _detail_class_conf_min

    if coarse_monster and fine_ok:
        return ObjectType.MONSTER
    if coarse_monster or fine_monster:
        # Monster signal without both confident heads → reject.
        return ObjectType.OTHER
    return coarse_to_object_type(coarse)


# Legacy YOLO label map (debug / display only; not used for ObjectType).
VISION_LABEL_TO_TYPE = {
    "player": ObjectType.PLAYER,
    "monster": ObjectType.MONSTER,
    "npc": ObjectType.NPC,
    "item": ObjectType.ITEM,
}


# ==================================================
# CONFIG CONSTANTS (from Lineage_bot config/paths.py, normalized)
# ==================================================

# Euclidean distance threshold for re-identifying the same entity across frames
REIDENTIFY_RADIUS = 0.03  # normalized (was 30 pixels at 1920x1080)
LOOT_OR_NOT_RADIUS = 0.1  # normalized (was 100 pixels)
ATTACK_RANGE = 0.23  # normalized (was 450 pixels at 1920 width)
# Mage spell reach in discrete relative WCS tiles (Chebyshev / max-distance).
MAGE_SPELL_RANGE = 10
CRITICAL_HP_THRESHOLD = 0.3
CRITICAL_MP_THRESHOLD = 0.3


ATTACK_MP_UNCHANGED_TICKS = 2