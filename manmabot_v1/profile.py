"""Persisted user profile for Version 1."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from manmabot_v1.paths import (
    PROFILE_PATH,
    PROFILES_DIR,
    assert_userdata_write,
    ensure_userdata,
)
from manmabot_v1.hp_actions import default_hp_actions, normalize_hp_actions
from manmabot_v1.spell_defaults import (
    DEFAULT_BUFF_COOLDOWN_MIN,
    DEFAULT_HEAL_DOUBLE,
    DEFAULT_HEAL_UNTIL_HP,
    DEFAULT_SPELL_RESERVE,
    default_spell_slots,
    merge_spell_slots,
)
from manmabot_v1.strings import (
    DEFAULT_HOTKEYS,
    detect_system_language,
    normalize_game_language,
    ui_language,
)

DEFAULT_MAP_ID = "talking_island"
CHARACTER_IDS = ("royal", "knight", "elf", "mage")
_PROFILE_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


@dataclass
class Profile:
    wizard_completed: bool = False
    language: str = "ko"
    game_language: str = "ko"
    character: str = "mage"
    loot_mode: str = "all_items"
    loot_adena_weight_ratio: float = 0.30
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
    hp_potion_ratio: float = 0.55
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
    random_teleport_enabled: bool = False
    teleport_on_player: bool = False
    teleport_when_surrounded: bool = False
    teleport_surround_count: int = 4
    farm_rotate_s: float = 600.0
    arrow_buy_qty: int = 200
    silver_arrow_buy_qty: int = 200
    buy_normal_arrows: bool = True
    buy_silver_arrows: bool = False
    restock_potions: bool = True
    buy_depoison: bool = False
    hp_potion_buy_qty: int = 100
    depoison_buy_qty: int = 1
    hp_potion_npc: str = ""
    shop_locale: str = "ko"
    return_potion_enabled: bool = True
    return_potion_count: int = 20
    return_arrow_enabled: bool = True
    return_arrow_count: int = 300
    return_depoison_enabled: bool = False
    return_depoison_count: int = 1
    attack_jitter: bool = False
    attack_jitter_ms: int = 35
    target_delay: bool = False
    target_delay_min_ms: int = 20
    target_delay_max_ms: int = 50
    abandon_same: bool = False
    abandon_seconds: int = 20
    antidote_auto: bool = False
    area_empty: bool = False
    area_empty_seconds: int = 60
    area_low_yield: bool = False
    area_low_yield_adena: int = 1000
    area_low_yield_seconds: int = 180
    area_players: bool = False
    area_player_count: int = 3
    return_weight_enabled: bool = True
    return_weight_above: int = 85
    sell_mode: str = "sell_except_keep"
    always_on_top: bool = False
    humanize: bool = True
    show_preview: bool = False
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    spell_slots: dict[str, dict] = field(default_factory=default_spell_slots)
    hotbar_layout: dict[str, Any] = field(default_factory=dict)
    buff_cooldown_min: float = DEFAULT_BUFF_COOLDOWN_MIN
    heal_until_hp_ratio: float = DEFAULT_HEAL_UNTIL_HP
    spell_reserve_ratio: float = DEFAULT_SPELL_RESERVE
    heal_double_press: bool = DEFAULT_HEAL_DOUBLE
    hp_actions: list[dict] = field(default_factory=default_hp_actions)
    selected_account_id: str | None = None

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
        return asdict(self)

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
            from manmabot_v1.farm_schedule import normalize_farm_stays_s

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
            kwargs["language"] = ui_language(str(kwargs["language"]))
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
            kwargs["spell_slots"] = merge_spell_slots(
                data.get("spell_slots"),
                buff_cooldown_min=(
                    float(data["buff_cooldown_min"])
                    if "buff_cooldown_min" in data
                    else None
                ),
                heal_double_press=(
                    bool(data["heal_double_press"])
                    if "heal_double_press" in data
                    else None
                ),
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
            "abandon_same",
            "antidote_auto",
            "area_empty",
            "area_low_yield",
            "area_players",
            "random_teleport_enabled",
            "teleport_on_player",
            "teleport_when_surrounded",
            "buy_normal_arrows",
            "buy_silver_arrows",
            "restock_potions",
            "buy_depoison",
            "humanize",
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
            potion_pct=round(float(kwargs.get("hp_potion_ratio", 0.55)) * 100),
            escape_pct=round(float(kwargs.get("hp_escape_ratio", 0.30)) * 100),
            use_heal=bool(kwargs.get("use_heal", True)),
            use_potion=bool(kwargs.get("use_hp_potion", True)),
        )
        if "show_preview" in kwargs:
            kwargs["show_preview"] = bool(kwargs["show_preview"])
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
            try:
                kwargs["return_weight_above"] = max(
                    0, min(100, int(kwargs["return_weight_above"]))
                )
            except (TypeError, ValueError):
                kwargs.pop("return_weight_above", None)
        # Mutex arrow type.
        if kwargs.get("buy_normal_arrows") and kwargs.get("buy_silver_arrows"):
            kwargs["buy_silver_arrows"] = False
        if not kwargs.get("buy_normal_arrows", True) and not kwargs.get(
            "buy_silver_arrows", False
        ):
            kwargs["buy_normal_arrows"] = True
        return cls(**{**base, **kwargs})


def load_profile(path: Path | None = None) -> Profile:
    ensure_userdata()
    p = path or PROFILE_PATH
    if not p.is_file():
        return Profile(language=detect_system_language())
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return Profile(language=detect_system_language())
        return Profile.from_dict(data)
    except (OSError, json.JSONDecodeError):
        return Profile(language=detect_system_language())


def save_profile(profile: Profile, path: Path | None = None) -> None:
    ensure_userdata()
    p = assert_userdata_write(path or PROFILE_PATH)
    profile.language = ui_language(profile.language)
    profile.game_language = normalize_game_language(profile.game_language)
    temporary = assert_userdata_write(p.with_suffix(p.suffix + ".tmp"))
    try:
        temporary.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(p)
    finally:
        temporary.unlink(missing_ok=True)


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
