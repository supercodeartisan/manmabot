"""Persisted user profile for Version 1."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from session.paths import (
    PROFILE_PATH,
    PROFILES_DIR,
    assert_userdata_write,
    ensure_userdata,
)
from settings.hp_actions import default_hp_actions, normalize_hp_actions
from settings.spell_defaults import (
    DEFAULT_BUFF_COOLDOWN_MIN,
    DEFAULT_HEAL_DOUBLE,
    DEFAULT_HEAL_UNTIL_HP,
    DEFAULT_SPELL_RESERVE,
    default_spell_bindings,
    merge_spell_slots,
    spell_slot_bindings,
)
from i18n.strings import (
    DEFAULT_HOTKEYS,
    detect_system_language,
    normalize_game_language,
    normalize_language,
)

DEFAULT_MAP_ID = "talking_island"
CHARACTER_IDS = ("royal", "knight", "elf", "mage")
# Shop-return bag weight threshold choices (GUI listbox / combo only).
RETURN_WEIGHT_PCT_CHOICES = (50, 60, 70)
DEFAULT_RETURN_WEIGHT_ABOVE = 70
_PROFILE_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


def snap_return_weight_above(value: Any, default: int = DEFAULT_RETURN_WEIGHT_ABOVE) -> int:
    """Clamp saved weight % to the nearest allowed GUI choice (50 / 60 / 70)."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raw = int(default)
    return min(RETURN_WEIGHT_PCT_CHOICES, key=lambda choice: abs(choice - raw))


@dataclass
class Profile:
    wizard_completed: bool = False
    language: str = "en"
    game_language: str = "ko"
    character: str = "mage"
    # Hunt Attack radios: ranged | magic | melee (mage ranged = bow).
    attack_mode: str = "magic"
    loot_mode: str = "all_items"
    loot_adena_weight_ratio: float = 0.70
    ignore_small_adena: bool = False
    ignore_small_adena_qty: int = 10
    active_map: str = DEFAULT_MAP_ID
    # ``normal`` = farm rectangles; ``dungeon`` = patrol midpoints.
    map_style: str = "normal"
    selected_farms: list[str] = field(default_factory=list)
    farm_stays_s: dict[str, float] = field(default_factory=dict)
    species_levels: dict[str, int] = field(default_factory=dict)
    species_blacklist: list[str] = field(default_factory=list)
    species_filter_mode: str = "blacklist"
    species_whitelist: list[str] = field(default_factory=list)
    species_sort: str = "name"
    item_pickup_mode: str = "all"
    item_pickup_names: list[str] = field(default_factory=list)
    hp_potion_ratio: float = 0.50
    hp_heal_ratio: float = 0.70
    hp_recover_enabled: bool = True
    use_hp_potion: bool = True
    use_heal: bool = True
    mp_recover_enabled: bool = False
    mp_potion_ratio: float = 0.30
    use_mp_potion: bool = False
    resurrect_if_dead: bool = True
    resume_after_relogin: bool = True
    max_retries: int = 3
    hp_escape_ratio: float = 0.30
    mp_escape_enabled: bool = False
    mp_escape_ratio: float = 0.15
    return_hp_enabled: bool = True
    return_hp_ratio: float = 0.30
    return_mp_enabled: bool = True
    return_mp_ratio: float = 0.15
    return_idle_enabled: bool = False
    return_idle_seconds: float = 60.0
    # Mother-tree stand. Percents live on the schedule; these are ratios.
    mother_tree_hp_to_mp_enabled: bool = True
    mother_tree_hp_to_mp_hp_ratio: float = 0.85
    mother_tree_hp_to_mp_mp_ratio: float = 0.80
    mother_tree_heal_enabled: bool = True
    mother_tree_heal_hp_ratio: float = 0.40
    mother_tree_heal_mp_ratio: float = 0.80
    random_teleport_enabled: bool = False
    teleport_on_player: bool = False
    teleport_when_surrounded: bool = False
    teleport_surround_count: int = 10
    farm_rotate_s: float = 600.0
    arrow_buy_qty: int = 200
    silver_arrow_buy_qty: int = 200
    buy_normal_arrows: bool = False
    buy_silver_arrows: bool = True
    restock_potions: bool = True
    store_after_sell: bool = True
    buy_depoison: bool = False
    hp_potion_buy_qty: int = 10
    depoison_buy_qty: int = 1
    hp_potion_npc: str = ""
    shop_locale: str = "ko"
    return_potion_enabled: bool = True
    return_potion_count: int = 0
    return_arrow_enabled: bool = True
    return_arrow_count: int = 300
    return_depoison_enabled: bool = False
    return_depoison_count: int = 1
    attack_jitter: bool = False
    attack_jitter_ms: int = 35
    target_delay: bool = False
    target_delay_min_ms: int = 20
    target_delay_max_ms: int = 50
    # Combat assist: green / greater-green haste potion (opt-in).
    use_haste_potion: bool = False
    haste_potion_item: str = ""
    haste_potion_box: int = 0
    haste_potion_key: str = ""
    # Combat assist: antidote on curable petrify / poison (opt-in).
    use_antidote_potion: bool = False
    antidote_potion_item: str = ""
    antidote_potion_box: int = 0
    antidote_potion_key: str = ""
    abandon_same: bool = False
    abandon_seconds: int = 30
    antidote_auto: bool = False
    area_empty: bool = False
    area_empty_seconds: int = 60
    area_low_yield: bool = False
    area_low_yield_adena: int = 1000
    area_low_yield_seconds: int = 180
    area_players: bool = False
    area_player_count: int = 3
    return_weight_enabled: bool = True
    return_weight_above: int = DEFAULT_RETURN_WEIGHT_ABOVE
    sell_mode: str = "sell_except_keep"
    always_on_top: bool = False
    humanize: bool = True
    # Curved mouse path. Off jumps the cursor. On finishes each move within 0.02s.
    humanize_move: bool = True
    # Hunt clicks/keys. Login and party chat stay on Interception.
    input_backend: str = "interception"
    pico_com: str = ""
    pico_baud: int = 115200
    show_preview: bool = False
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    spell_slots: dict[str, dict] = field(default_factory=default_spell_bindings)
    hotbar_layout: dict[str, Any] = field(default_factory=dict)
    buff_cooldown_min: float = DEFAULT_BUFF_COOLDOWN_MIN
    heal_until_hp_ratio: float = DEFAULT_HEAL_UNTIL_HP
    spell_reserve_ratio: float = DEFAULT_SPELL_RESERVE
    heal_double_press: bool = DEFAULT_HEAL_DOUBLE
    hp_actions: list[dict] = field(default_factory=default_hp_actions)
    selected_account_id: str | None = None
    # Schedule UI move.routine[] (battle/break). Empty → single active_map fallback.
    routine: list = field(default_factory=list)
    # Party member (``app._06_party``): mirror a leader instead of solo farm.
    # Master switch for the Party tab (member follow or leader socket).
    party_enabled: bool = False
    party_member_enabled: bool = False
    party_leader_name: str = ""
    party_follow_tiles: int = 8
    party_stop_tiles: int = 2
    # Legacy aliases kept for older profile JSON; mirrored on load/apply.
    party_follow_start_tiles: int = 8
    party_follow_stop_tiles: int = 2
    party_assist_leash_tiles: int = 10
    party_approach_tiles: int = 2
    party_potion_hp_ratio: float = 0.45
    party_random_loot: bool = False
    party_loot_role: str = "none"
    # follow = loot only while holding. loot = party drops before follow.
    party_loot_priority: str = "follow"
    # Member farm: party = attack the leader's target; solo = own mobs near leader.
    party_farm_mode: str = "party"
    # Leader mode (sent to members): turret = hold a yard; moving = roam.
    party_leader_mode: str = "turret"
    # Moving leader waits briefly when half or more members are this far behind.
    party_lag_tiles: int = 30
    # member = existing follow/assist. leader = this PC hosts the party socket.
    party_role: str = "member"
    party_ws_port: int = 8765
    # Member client: address of the leader PC's party socket.
    party_leader_host: str = ""
    # Leader roster: name, seat role, optional loot (none|responsible).
    party_roster: list = field(default_factory=list)

    def __post_init__(self) -> None:
        char = str(self.character or "").strip().lower()
        if char == "prince":
            char = "royal"
        if char not in CHARACTER_IDS:
            char = "mage"
        self.character = char
        style = str(getattr(self, "map_style", "normal") or "normal").strip().lower()
        self.map_style = "dungeon" if style == "dungeon" else "normal"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Persist placement only — cast/reuse_s live in Engine spell defaults.
        data["spell_slots"] = spell_slot_bindings(data.get("spell_slots"))
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        base = asdict(cls())
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in data.items() if k in known}
        if "hotkeys" in kwargs and isinstance(kwargs["hotkeys"], dict):
            merged = dict(DEFAULT_HOTKEYS)
            for k, v in kwargs["hotkeys"].items():
                if k in DEFAULT_HOTKEYS:
                    merged[k] = str(v).lower()
            kwargs["hotkeys"] = merged
        if "selected_farms" in kwargs and kwargs["selected_farms"] is None:
            kwargs["selected_farms"] = []
        if "farm_stays_s" in kwargs:
            from settings.farm_schedule import normalize_farm_stays_s

            kwargs["farm_stays_s"] = normalize_farm_stays_s(kwargs.get("farm_stays_s"))
        if "species_levels" in kwargs:
            raw = kwargs["species_levels"]
            cleaned: dict[str, int] = {}
            if isinstance(raw, dict):
                for key, value in raw.items():
                    try:
                        cleaned[str(key)] = int(value)
                    except (TypeError, ValueError):
                        continue
            kwargs["species_levels"] = cleaned
        if "species_blacklist" in kwargs:
            raw_bl = kwargs["species_blacklist"]
            blocked: list[str] = []
            seen: set[str] = set()
            items = raw_bl if isinstance(raw_bl, (list, tuple)) else []
            for item in items:
                key = str(item).strip()
                if key and key not in seen:
                    seen.add(key)
                    blocked.append(key)
            kwargs["species_blacklist"] = blocked
        if "species_filter_mode" in kwargs:
            mode = str(kwargs["species_filter_mode"] or "blacklist").strip().lower()
            kwargs["species_filter_mode"] = mode if mode in ("blacklist", "whitelist") else "blacklist"
        if "species_whitelist" in kwargs:
            raw_wl = kwargs["species_whitelist"]
            wanted: list[str] = []
            seen_wl: set[str] = set()
            items = raw_wl if isinstance(raw_wl, (list, tuple)) else []
            for item in items:
                key = str(item).strip()
                if key and key not in seen_wl:
                    seen_wl.add(key)
                    wanted.append(key)
            kwargs["species_whitelist"] = wanted
        if "item_pickup_mode" in kwargs:
            mode = str(kwargs["item_pickup_mode"] or "all").strip().lower()
            kwargs["item_pickup_mode"] = mode if mode in ("all", "blacklist", "whitelist") else "all"
        if "item_pickup_names" in kwargs:
            raw_names = kwargs["item_pickup_names"]
            names: list[str] = []
            seen_names: set[str] = set()
            items = raw_names if isinstance(raw_names, (list, tuple)) else []
            for item in items:
                key = str(item).strip()
                if key and key not in seen_names:
                    seen_names.add(key)
                    names.append(key)
            kwargs["item_pickup_names"] = names
        if "species_sort" in kwargs:
            raw_sort = str(kwargs["species_sort"] or "name").strip().lower()
            kwargs["species_sort"] = raw_sort if raw_sort in ("name", "level") else "name"
        if "language" in kwargs:
            kwargs["language"] = normalize_language(str(kwargs["language"]))
        if "game_language" in kwargs:
            kwargs["game_language"] = normalize_game_language(
                str(kwargs["game_language"])
            )
        if "character" in kwargs:
            char = str(kwargs["character"] or "").strip().lower()
            if char == "prince":
                char = "royal"
            if char not in CHARACTER_IDS:
                char = "mage"
            kwargs["character"] = char
        if "active_map" in kwargs:
            kwargs["active_map"] = str(kwargs["active_map"] or DEFAULT_MAP_ID).strip()
        if "spell_slots" in kwargs or "buff_cooldown_min" in data or "heal_double_press" in data:
            # Runtime merge for validation, then keep bindings only on the Profile.
            kwargs["spell_slots"] = spell_slot_bindings(
                merge_spell_slots(data.get("spell_slots"))
            )
        if "hotbar_layout" in kwargs:
            raw_layout = kwargs["hotbar_layout"]
            kwargs["hotbar_layout"] = (
                dict(raw_layout) if isinstance(raw_layout, dict) else {}
            )
        for name, lo, hi in (
            ("buff_cooldown_min", 1.0, 60.0),
            ("heal_until_hp_ratio", 0.10, 0.95),
            ("spell_reserve_ratio", 0.05, 0.50),
            ("loot_adena_weight_ratio", 0.05, 0.95),
            ("mp_potion_ratio", 0.05, 0.95),
            ("hp_potion_ratio", 0.05, 0.95),
            ("hp_heal_ratio", 0.05, 0.95),
            ("mother_tree_hp_to_mp_hp_ratio", 0.0, 1.0),
            ("mother_tree_hp_to_mp_mp_ratio", 0.0, 1.0),
            ("mother_tree_heal_hp_ratio", 0.0, 1.0),
            ("mother_tree_heal_mp_ratio", 0.0, 1.0),
        ):
            if name in kwargs:
                try:
                    kwargs[name] = max(lo, min(hi, float(kwargs[name])))
                except (TypeError, ValueError):
                    kwargs.pop(name, None)
        for name, lo, hi in (
            ("attack_jitter_ms", 10, 50),
            ("target_delay_min_ms", 10, 50),
            ("target_delay_max_ms", 10, 50),
        ):
            if name in kwargs:
                try:
                    kwargs[name] = max(lo, min(hi, int(kwargs[name])))
                except (TypeError, ValueError):
                    kwargs.pop(name, None)
        delay_min = int(kwargs.get("target_delay_min_ms", 20) or 20)
        delay_max = int(kwargs.get("target_delay_max_ms", 50) or 50)
        if delay_max < delay_min:
            kwargs["target_delay_max_ms"] = delay_min
        if "max_retries" in kwargs:
            try:
                kwargs["max_retries"] = max(1, min(20, int(kwargs["max_retries"])))
            except (TypeError, ValueError):
                kwargs.pop("max_retries", None)
        for flag in (
            "hp_recover_enabled",
            "use_hp_potion",
            "use_heal",
            "mp_recover_enabled",
            "use_mp_potion",
            "resurrect_if_dead",
            "resume_after_relogin",
            "return_mp_enabled",
            "return_potion_enabled",
            "return_arrow_enabled",
            "return_depoison_enabled",
            "return_weight_enabled",
            "return_idle_enabled",
            "attack_jitter",
            "target_delay",
            "use_haste_potion",
            "use_antidote_potion",
            "abandon_same",
            "antidote_auto",
            "party_enabled",
            "party_member_enabled",
            "party_random_loot",
            "area_empty",
            "area_low_yield",
            "area_players",
            "random_teleport_enabled",
            "teleport_on_player",
            "teleport_when_surrounded",
            "buy_normal_arrows",
            "buy_silver_arrows",
            "restock_potions",
            "store_after_sell",
            "buy_depoison",
            "humanize",
            "humanize_move",
        ):
            if flag in kwargs:
                raw = kwargs[flag]
                if isinstance(raw, str):
                    kwargs[flag] = raw.strip().lower() in ("1", "true", "yes", "on")
                else:
                    kwargs[flag] = bool(raw)
        if "heal_double_press" in kwargs:
            kwargs["heal_double_press"] = bool(kwargs["heal_double_press"])
        kwargs["hp_actions"] = normalize_hp_actions(
            data.get("hp_actions"),
            potion_pct=round(float(kwargs.get("hp_potion_ratio", 0.50)) * 100),
            heal_pct=round(float(kwargs.get("hp_heal_ratio", 0.70)) * 100),
            escape_pct=round(float(kwargs.get("hp_escape_ratio", 0.30)) * 100),
            use_heal=bool(kwargs.get("use_heal", True)),
            use_potion=bool(kwargs.get("use_hp_potion", True)),
        )
        if "show_preview" in kwargs:
            kwargs["show_preview"] = bool(kwargs["show_preview"])
        if "input_backend" in kwargs:
            name = str(kwargs.get("input_backend") or "").strip().lower()
            kwargs["input_backend"] = (
                "pico"
                if name in {"pico", "raspberry", "raspberrypi", "rasberry", "rasberrypi"}
                else "interception"
            )
        if "pico_com" in kwargs:
            kwargs["pico_com"] = str(kwargs.get("pico_com") or "").strip()
        if "pico_baud" in kwargs:
            try:
                baud = int(kwargs.get("pico_baud") or 115200)
            except (TypeError, ValueError):
                baud = 115200
            kwargs["pico_baud"] = baud if 1200 <= baud <= 1_000_000 else 115200
        if "selected_account_id" in kwargs:
            selected = kwargs["selected_account_id"]
            kwargs["selected_account_id"] = (
                str(selected).strip() if selected is not None else None
            ) or None
        if "arrow_buy_qty" in kwargs:
            try:
                kwargs["arrow_buy_qty"] = max(1, min(999, int(kwargs["arrow_buy_qty"])))
            except (TypeError, ValueError):
                kwargs.pop("arrow_buy_qty", None)
        if "silver_arrow_buy_qty" in kwargs:
            try:
                kwargs["silver_arrow_buy_qty"] = max(
                    1, min(999, int(kwargs["silver_arrow_buy_qty"]))
                )
            except (TypeError, ValueError):
                kwargs.pop("silver_arrow_buy_qty", None)
        if "buy_normal_arrows" in kwargs:
            kwargs["buy_normal_arrows"] = bool(kwargs["buy_normal_arrows"])
        if "buy_silver_arrows" in kwargs:
            kwargs["buy_silver_arrows"] = bool(kwargs["buy_silver_arrows"])
        if "restock_potions" in kwargs:
            kwargs["restock_potions"] = bool(kwargs["restock_potions"])
        if "buy_depoison" in kwargs:
            kwargs["buy_depoison"] = bool(kwargs["buy_depoison"])
        if "hp_potion_buy_qty" in kwargs:
            try:
                kwargs["hp_potion_buy_qty"] = max(
                    1, min(999, int(kwargs["hp_potion_buy_qty"]))
                )
            except (TypeError, ValueError):
                kwargs.pop("hp_potion_buy_qty", None)
        if "depoison_buy_qty" in kwargs:
            try:
                kwargs["depoison_buy_qty"] = max(
                    1, min(999, int(kwargs["depoison_buy_qty"]))
                )
            except (TypeError, ValueError):
                kwargs.pop("depoison_buy_qty", None)
        if "hp_potion_npc" in kwargs:
            kwargs["hp_potion_npc"] = str(kwargs["hp_potion_npc"] or "").strip()
        if "shop_locale" in kwargs:
            text = str(kwargs["shop_locale"] or "ko").strip().lower()
            kwargs["shop_locale"] = "zh" if text.startswith("zh") else "ko"
        if "sell_mode" in kwargs:
            mode = str(kwargs["sell_mode"] or "sell_except_keep").strip().lower()
            kwargs["sell_mode"] = (
                "sell_only_garbage"
                if mode in ("sell_only_garbage", "only_garbage", "garbage")
                else "sell_except_keep"
            )
        if "return_weight_above" in kwargs:
            kwargs["return_weight_above"] = snap_return_weight_above(
                kwargs.get("return_weight_above"), DEFAULT_RETURN_WEIGHT_ABOVE
            )
        if "party_loot_priority" in kwargs:
            priority = str(kwargs.get("party_loot_priority") or "follow").strip().lower()
            kwargs["party_loot_priority"] = priority if priority in ("follow", "loot") else "follow"
        if "party_farm_mode" in kwargs:
            mode = str(kwargs.get("party_farm_mode") or "party").strip().lower()
            kwargs["party_farm_mode"] = mode if mode in ("party", "solo") else "party"
        if "party_leader_mode" in kwargs:
            lead = str(kwargs.get("party_leader_mode") or "turret").strip().lower()
            kwargs["party_leader_mode"] = (
                lead if lead in ("turret", "moving") else "turret"
            )
        if "party_lag_tiles" in kwargs:
            try:
                lag = int(kwargs.get("party_lag_tiles"))
            except (TypeError, ValueError):
                lag = 30
            kwargs["party_lag_tiles"] = max(5, min(100, lag))
        if "party_role" in kwargs:
            role = str(kwargs.get("party_role") or "member").strip().lower()
            kwargs["party_role"] = role if role in ("member", "leader") else "member"
        if "party_leader_host" in kwargs:
            kwargs["party_leader_host"] = str(kwargs.get("party_leader_host") or "").strip()
        if "party_roster" in kwargs:
            kwargs["party_roster"] = normalize_party_roster(kwargs.get("party_roster"))
        if "party_ws_port" in kwargs:
            try:
                kwargs["party_ws_port"] = max(1, min(65535, int(kwargs["party_ws_port"])))
            except (TypeError, ValueError):
                kwargs["party_ws_port"] = 8765
        # Mutex arrow type.
        if kwargs.get("buy_normal_arrows") and kwargs.get("buy_silver_arrows"):
            kwargs["buy_silver_arrows"] = False
        if not kwargs.get("buy_normal_arrows", True) and not kwargs.get(
            "buy_silver_arrows", False
        ):
            kwargs["buy_normal_arrows"] = True
        return cls(**{**base, **kwargs})


_ROSTER_ROLES = ("member", "mage", "shopkeeper")
_ROSTER_LOOT = ("none", "responsible")


def normalize_party_roster(raw: Any) -> list[dict[str, str]]:
    """Leader seat list: name, seat (default mage), optional loot seat."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    items = raw if isinstance(raw, (list, tuple)) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        role = str(item.get("role") or "mage").strip().lower()
        if role not in _ROSTER_ROLES:
            role = "mage"
        loot = str(item.get("loot") or item.get("loot_role") or "none").strip().lower()
        if loot not in _ROSTER_LOOT:
            loot = "none"
        rows.append({"name": name, "role": role, "loot": loot})
    return rows


def load_profile(path: Path | None = None) -> Profile:
    """Load operator settings.

    Default path is the **trial** workspace (ops layout). Explicit ``path``
    still reads a flat Profile JSON (named presets / legacy).
    """
    ensure_userdata()
    if path is not None and path != PROFILE_PATH:
        p = path
        if not p.is_file():
            return Profile(language=detect_system_language())
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return Profile(language=detect_system_language())
            return Profile.from_dict(data)
        except (OSError, json.JSONDecodeError):
            return Profile(language=detect_system_language())

    from settings.ops_migrate import ensure_ops_layout
    from settings.schedule import ScheduleTask
    from settings.settings_sections import TOP_SECTIONS
    from settings.task_runtime import apply_runtime_settings
    from settings.trial_store import load_app_state, load_trial, trial_as_embedded_settings
    from session.paths import TRIAL_SETTINGS_PATH

    ensure_ops_layout()
    profile = Profile(language=detect_system_language())
    app = load_app_state()
    if app.get("language"):
        profile.language = normalize_language(str(app["language"]))
    profile.wizard_completed = bool(app.get("wizard_completed", False))
    profile.always_on_top = bool(app.get("always_on_top", False))
    if app.get("input_backend"):
        profile.input_backend = (
            "pico"
            if str(app.get("input_backend") or "").strip().lower()
            in {"pico", "raspberry", "raspberrypi", "rasberry", "rasberrypi"}
            else "interception"
        )
    if "pico_com" in app and app.get("pico_com") is not None:
        profile.pico_com = str(app.get("pico_com") or "").strip()
    if app.get("pico_baud") not in (None, ""):
        try:
            baud = int(app.get("pico_baud") or 115200)
        except (TypeError, ValueError):
            baud = 115200
        profile.pico_baud = baud if 1200 <= baud <= 1_000_000 else 115200
    trial_settings, trial_routine = load_trial()
    has_trial = bool(trial_routine) or any(
        bool(trial_settings.get(section)) for section in TOP_SECTIONS
    )
    if not has_trial and not TRIAL_SETTINGS_PATH.is_file() and PROFILE_PATH.is_file():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return Profile.from_dict(data)
        except (OSError, json.JSONDecodeError):
            pass
    settings = trial_as_embedded_settings()
    char = str((settings.get("magic") or {}).get("class") or profile.character or "mage")
    apply_runtime_settings(
        ScheduleTask(settings=settings, account_id=None, character=char),
        profile,
    )
    if not app.get("input_backend"):
        other = trial_settings.get("other") if isinstance(trial_settings, dict) else None
        if isinstance(other, dict) and other.get("input_backend"):
            raw_name = str(other.get("input_backend") or "").strip().lower()
            profile.input_backend = (
                "pico"
                if raw_name
                in {"pico", "raspberry", "raspberrypi", "rasberry", "rasberrypi"}
                else "interception"
            )
            if other.get("pico_com"):
                profile.pico_com = str(other.get("pico_com") or "").strip()
    profile.selected_account_id = None
    return profile


def save_profile(profile: Profile, path: Path | None = None) -> None:
    """Persist settings.

    Default: trial workspace (+ app.json chrome). Explicit path: flat JSON
    (named presets).
    """
    from session.paths import atomic_write_json

    ensure_userdata()
    profile.language = normalize_language(profile.language)
    profile.game_language = normalize_game_language(profile.game_language)

    if path is not None and path != PROFILE_PATH:
        p = assert_userdata_write(path)
        atomic_write_json(p, profile.to_dict())
        return

    from settings.ops_migrate import ensure_ops_layout
    from settings.schedule import profile_snapshot
    from settings.settings_sections import merge_settings_routine, split_settings_routine
    from settings.trial_store import save_app_state, save_trial

    ensure_ops_layout()
    snap = profile_snapshot(profile)
    if getattr(profile, "routine", None):
        snap = merge_settings_routine(snap, profile.routine)
    settings, routine = split_settings_routine(snap)
    save_trial(settings, routine)
    save_app_state(
        {
            "language": profile.language,
            "wizard_completed": bool(profile.wizard_completed),
            "always_on_top": bool(profile.always_on_top),
            "input_backend": (
                "pico"
                if str(getattr(profile, "input_backend", "interception") or "")
                .strip()
                .lower()
                in {"pico", "raspberry", "raspberrypi", "rasberry", "rasberrypi"}
                else "interception"
            ),
            "pico_com": str(getattr(profile, "pico_com", "") or "").strip(),
            "pico_baud": int(getattr(profile, "pico_baud", 115200) or 115200),
        }
    )


def reset_profile() -> Profile:
    profile = Profile(language=detect_system_language())
    save_profile(profile)
    return profile


def normalize_profile_name(name: str) -> str:
    cleaned = " ".join(str(name or "").strip().split())
    if not _PROFILE_NAME_OK.fullmatch(cleaned):
        raise ValueError(
            "Profile names must be 1–40 characters and use only letters, "
            "numbers, spaces, periods, underscores, or hyphens."
        )
    return cleaned


def named_profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{normalize_profile_name(name)}.json"


def list_profile_names() -> list[str]:
    ensure_userdata()
    return sorted(
        (path.stem for path in PROFILES_DIR.glob("*.json") if path.is_file()),
        key=str.casefold,
    )


def save_named_profile(name: str, profile: Profile) -> Path:
    path = named_profile_path(name)
    save_profile(profile, path)
    return path


def load_named_profile(name: str) -> Profile:
    path = named_profile_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Settings profile not found: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read settings profile {name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Settings profile {name} does not contain an object")
    return Profile.from_dict(data)


def delete_named_profile(name: str) -> None:
    path = assert_userdata_write(named_profile_path(name))
    if not path.is_file():
        raise FileNotFoundError(f"Settings profile not found: {name}")
    path.unlink()
