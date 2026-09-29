"""UI copy for Version 0 — English, Korean, and Mandarin Chinese.

Operator-facing strings only. Probe / diagnostic details stay English.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LANG_EN = "en"
LANG_KO = "ko"
LANG_ZH = "zh"
SUPPORTED_LANGUAGES: tuple[str, ...] = (LANG_EN, LANG_KO, LANG_ZH)

# Display names shown in the Language dropdown.
LANGUAGE_CHOICES: tuple[tuple[str, str], ...] = (
    (LANG_EN, "English"),
    (LANG_KO, "한국어"),
    (LANG_ZH, "简体中文"),
)

DEFAULT_HOTKEYS = {
    "pause_resume": "alt+a",
    "stop": "alt+q",
}


def normalize_language(code: str | None) -> str:
    c = (code or LANG_EN).strip().lower().replace("_", "-")
    if c.startswith("ko"):
        return LANG_KO
    if c.startswith("zh"):
        return LANG_ZH
    return LANG_EN


def detect_system_language() -> str:
    """Best-effort OS locale → en|ko|zh for first-run profile default."""
    try:
        import locale

        loc = locale.getdefaultlocale()[0] or ""
    except Exception:
        loc = ""
    return normalize_language(loc)


GAME_LANG_KO = "ko"
GAME_LANG_ZH = "zh"
GAME_LANGUAGES: tuple[str, ...] = (GAME_LANG_KO, GAME_LANG_ZH)


def normalize_game_language(code: str | None) -> str:
    """Lineage client language: ``ko`` or ``zh``. Empty / unknown → Korean."""
    c = (code or GAME_LANG_KO).strip().lower().replace("_", "-")
    if c.startswith("zh") or c in ("cn", "chinese"):
        return GAME_LANG_ZH
    return GAME_LANG_KO


@dataclass(frozen=True)
class UiStrings:
    """All operator-facing copy for one language."""

    # chrome
    window_title: str
    brand: str
    brand_sub: str
    lamp_game: str
    lamp_memory: str
    lamp_map: str
    headline_stopped: str
    headline_running: str
    headline_paused: str
    ready_to_start: str
    btn_start: str
    btn_resume: str
    btn_stop: str
    show_preview: str
    preview_title: str
    preview_waiting: str
    tab_setup: str
    tab_farms: str
    tab_species: str
    tab_spells: str
    tab_hotkeys: str
    tab_advanced: str
    tab_log: str
    tab_nav: str
    # setup
    region: str
    region_locked: str
    map_select: str
    map_hint: str
    map_preview_missing: str
    game_window: str
    not_checked: str
    detect: str
    bring_game_front: str
    character: str
    game_language: str
    game_language_hint: str
    game_lang_ko: str
    game_lang_zh: str
    loot: str
    loot_adena_weight: str
    survival: str
    drink_hp: str
    escape_hp: str
    escape_mp: str
    reset_survival: str
    buy_arrows: str
    buy_arrows_hint: str
    buy_normal_arrows: str
    buy_silver_arrows: str
    silver_arrow_qty: str
    restock_potions: str
    restock_potions_hint: str
    memory: str
    test_connection: str
    start_monitor: str
    # farms
    farms_heading: str
    farms_hint_empty: str
    farms_banner: str  # format: n, total, minutes
    select_all: str
    clear: str
    rotate_farms: str
    draw_farm: str
    place_patrol: str
    delete_selected: str
    save_areas: str
    editor_hint_island: str
    editor_hint_dungeon: str
    saved_areas: str
    saved_patrol: str
    farms_unsupported_dungeon: str
    patrol_not_walkable: str
    map_missing_short: str
    select_tool: str
    duplicate: str
    move_up: str
    move_down: str
    clear_all: str
    reload_areas: str
    edit_farms: str
    edit_patrol: str
    edit_done: str
    editor_close: str
    editor_list: str
    editor_list_empty: str
    rename_label: str
    editor_hover: str  # format: x, y
    editor_nav_hint: str
    nav_heading: str
    nav_hint: str
    nav_live: str
    nav_select_start: str
    nav_select_end: str
    nav_run: str
    nav_reset: str
    nav_idle: str
    nav_building: str
    nav_build_fail: str
    nav_live_connecting: str
    nav_live_on: str
    nav_live_fail: str
    nav_live_no_window: str
    nav_live_no_pos: str
    nav_live_start_locked: str
    nav_live_lost: str
    nav_bot_running: str
    nav_click_tile: str
    nav_blocked: str
    nav_start_set: str
    nav_end_set: str
    nav_reset_live: str
    nav_computing: str
    nav_preview_fail: str
    nav_no_path: str
    nav_path_ready: str
    nav_need_points: str
    nav_need_end: str
    nav_press_live: str
    nav_sim_walk: str
    nav_live_travel: str
    nav_arrived: str
    nav_stopped: str
    nav_path_error: str
    nav_no_click: str
    nav_click_fail: str
    nav_clicked: str
    nav_teleport: str
    nav_mem_fail: str
    confirm_clear_farms: str
    confirm_clear_patrol: str
    confirm_reload: str
    # species
    species_heading: str
    species_hint: str
    species_level_label: str
    species_default_fmt: str
    species_forced_fmt: str
    species_reset: str
    species_blocked: str
    species_sort_by: str
    species_sort_name: str
    species_sort_level: str
    species_allow: str
    species_done: str
    species_no_image: str
    # spells
    spells_heading: str
    spells_hint: str
    spells_usage_heading: str
    spells_box: str
    spells_box_n: str  # format: n
    spells_key: str
    spell_empty: str
    spell_enabled: str
    spell_assign: str
    spells_cell_hint: str
    spell_off: str
    spell_buff_cd: str
    spell_heal_until: str
    spell_mana_reserve: str
    spell_heal_double: str
    spell_cooldown: str
    spell_gcd_note: str
    spell_cast: str
    spell_cast_press: str
    spell_cast_double: str
    reset_spells: str
    restore_spells_q: str
    spell_conflict: str  # format: a, b
    spells_detected_heading: str
    spells_waiting_scan: str
    spells_active_heading: str
    spells_ignored: str
    spells_unmapped: str
    spell_titles: dict[str, str]
    spell_guides: dict[str, str]
    wizard_spells_note: str
    # hotkeys
    hotkeys_intro: str
    change: str
    reset_hotkeys: str
    hotkeys_tip: str
    change_shortcut_title: str
    press_new_shortcut: str  # format: action title
    waiting: str
    hotkey_need_modifier: str
    hotkey_conflict: str  # format: other action
    restore_hotkeys_q: str
    # advanced
    always_on_top: str
    humanize: str
    language: str
    language_hint: str
    memory_section: str
    load_driver: str
    monitor_path_hint: str  # format: path
    setup_section: str
    run_wizard: str
    logs_support: str
    open_log_folder: str
    copy_diagnostics: str
    danger_zone: str
    reset_all: str
    profiles_section: str
    profile_name: str
    profile_save_as: str
    profile_saved_profiles: str
    profile_save: str
    profile_load: str
    profile_delete: str
    profile_select: str
    profile_saved: str
    profile_loaded: str
    profile_deleted: str
    profile_overwrite_q: str
    profile_delete_q: str
    profile_name_invalid: str
    accounts_section: str
    account_secure_hint: str
    account_select: str
    account_none: str
    account_add: str
    account_update: str
    account_delete: str
    account_display_name: str
    account_username: str
    account_password: str
    account_server_language: str
    account_server: str
    account_character: str
    account_click_mode: str
    account_purple_path: str
    account_game_path: str
    account_browse: str
    account_saved: str
    account_deleted: str
    account_delete_q: str
    account_error_title: str
    account_invalid_username: str
    account_invalid_password: str
    account_invalid_display_name: str
    account_invalid_server_language: str
    account_invalid_server: str
    account_invalid_character: str
    account_invalid_purple_path: str
    account_invalid_game_path: str
    account_server_language_ko: str
    account_server_language_zh_cn: str
    account_server_language_zh_tw: str
    account_server_language_ja: str
    account_duplicate: str
    account_storage_error: str
    autologin_account_required: str
    autologin_starting: str
    autologin_status: str
    autologin_cancelled: str
    autologin_failed: str
    recovery_starting: str
    recovery_completed: str
    recovery_limit: str
    # dialogs / misc
    setup: str
    stop_to_change_setup: str
    cannot_start: str
    memory_title: str
    memory_connected: str
    memory_failed: str
    memory_failed_detail: str
    driver_title: str
    driver_ok: str
    driver_fail_prefix: str
    drivers_setup: str
    drivers_setup_hint: str
    interception_driver: str
    install_interception: str
    setup_memory_reader: str
    check_again: str
    driver_ready: str
    driver_not_ready: str
    driver_restart_hint: str
    stop_open_setup_q: str
    reset_title: str
    reset_confirm: str
    settings_reset_log: str
    wizard_done_log: str
    diagnostics_copied: str
    memory_connected_session: str
    logs: dict[str, str]
    # maps of codes
    reason: dict[str, str]
    start_fail: dict[str, str]
    loot_labels: dict[str, dict[str, str]]
    loot_weight_note: str
    char_blurbs: dict[str, str]
    char_titles: dict[str, str]
    hotkey_labels: dict[str, str]
    # wizard
    wizard_title: str
    wizard_back: str
    wizard_continue: str
    wizard_finish: str
    wizard_step: str  # format: cur, total
    wizard_block_close: str
    wizard_welcome: str
    wizard_welcome_body: str
    wizard_memory_hint: str
    wizard_not_tested: str
    wizard_starting_monitor: str
    monitor_closing: str
    monitor_closed: str
    monitor_close_failed: str
    bring_to_front: str
    wizard_loot_survival: str
    drink_hp_pct: str
    escape_hp_pct: str
    wizard_farms_title: str
    wizard_map_title: str
    wizard_map_body: str
    wizard_dungeon_farms: str
    select_one_farm: str
    wizard_hotkeys: str
    wizard_hotkeys_later: str
    wizard_review: str
    wizard_review_body: str  # format kwargs
    game_not_found: str
    no_farms: str
    memory_continue_anyway: str
    game_continue_anyway: str


_EN = UiStrings(
    window_title="Manmabot v1",
    brand="Manmabot",
    brand_sub="Version 1 (no license)",
    lamp_game="Game",
    lamp_memory="Memory",
    lamp_map="Map",
    headline_stopped="Stopped",
    headline_running="Running",
    headline_paused="Paused",
    ready_to_start="Ready to start.",
    btn_start="Start",
    btn_resume="Resume",
    btn_stop="Stop",
    show_preview="Show live preview",
    preview_title="Vision preview",
    preview_waiting="Waiting for frames…",
    tab_setup="Setup",
    tab_farms="Farms",
    tab_species="Species",
    tab_spells="Spells",
    tab_hotkeys="Hotkeys",
    tab_advanced="Advanced",
    tab_log="Log",
    tab_nav="Nav test",
    region="Map",
    region_locked="Talking Island (locked)",
    map_select="Map",
    map_hint="Change map only while the bot is stopped.",
    map_preview_missing="No map image yet.",
    game_window="Game window",
    not_checked="Not checked",
    detect="Detect",
    bring_game_front="Bring game to front",
    character="Character",
    game_language="Game language",
    game_language_hint="Lineage client language. Shop and some dialog clicks differ.",
    game_lang_ko="Korean",
    game_lang_zh="Chinese",
    loot="Loot",
    loot_adena_weight="Switch to adená-only when weight exceeds",
    survival="Survival",
    drink_hp="Drink HP potion below",
    escape_hp="Escape when HP below",
    escape_mp="Escape when MP below",
    reset_survival="Reset survival to defaults",
    buy_arrows="Buy arrows",
    buy_arrows_hint="How many arrows to buy at the shop (1–999). Pick normal or silver (not both).",
    buy_normal_arrows="Buy normal arrows",
    buy_silver_arrows="Buy silver arrows",
    silver_arrow_qty="Silver arrow quantity",
    restock_potions="Restock HP potions",
    restock_potions_hint="Shop for potions when bag HP potions are at or below Fix/Return limit.",
    memory="Memory",
    test_connection="Test connection",
    start_monitor="Start monitor & connect",
    farms_heading="Farms",
    farms_hint_empty=(
        "Select at least one farm, or click Edit farms to draw new areas."
    ),
    farms_banner="{n} of {total} farms enabled · rotate every {minutes:.0f} min",
    select_all="Select all",
    clear="Clear",
    rotate_farms="Rotate farms every (minutes)",
    draw_farm="Draw farm",
    place_patrol="Place patrol",
    delete_selected="Delete",
    save_areas="Save",
    editor_hint_island="Draw farm: drag a box. Click a farm to select, drag a handle to resize.",
    editor_hint_dungeon="Place patrol: click walkable tiles. Drag a marker to move it.",
    saved_areas="Saved farm areas for this map.",
    saved_patrol="Saved patrol points for this dungeon.",
    farms_unsupported_dungeon=(
        "Farming areas are not used in dungeons. Click Edit patrol to place points."
    ),
    patrol_not_walkable="That tile is not walkable.",
    map_missing_short="Map image is missing.",
    select_tool="Select",
    duplicate="Duplicate",
    move_up="Up",
    move_down="Down",
    clear_all="Clear all",
    reload_areas="Reload",
    edit_farms="Edit farms",
    edit_patrol="Edit patrol",
    edit_done="Done",
    editor_close="Close",
    editor_list="Items",
    editor_list_empty="Nothing yet — draw or place on the map.",
    rename_label="Name",
    editor_hover="Tile {x}, {y}",
    editor_nav_hint="Wheel or Ctrl+wheel zoom · right-drag pan · Delete removes selection.",
    nav_heading="Navigation test",
    nav_hint=(
        "Live reads your in-game tile. Select start and end on the map, then Run. "
        "Live Run walks the character with the same travel code as the bot. "
        "Stop the bot first."
    ),
    nav_live="Live",
    nav_select_start="Select start",
    nav_select_end="Select end",
    nav_run="Run",
    nav_reset="Reset",
    nav_idle="Select start, then end, then Run. Or press Live to use the character as start.",
    nav_building="Building pathfinding for this map…",
    nav_build_fail="Could not build pathfinding: {err}",
    nav_live_connecting="Connecting Live (memory + game window)…",
    nav_live_on="Live on. Position {pos}. Select end, then Run.",
    nav_live_fail="Live failed: {err}",
    nav_live_no_window="Live: game window not found.",
    nav_live_no_pos="Live: cannot read player position.",
    nav_live_start_locked="Live: start is the character. Select end instead.",
    nav_live_lost="Live: lost player position.",
    nav_bot_running="Stop the bot before Live or live Run.",
    nav_click_tile="Click a walkable tile ({kind}).",
    nav_blocked="Blocked tile ({x}, {y}). Click walkable ground.",
    nav_start_set="Start = ({x}, {y}). Now select end.",
    nav_end_set="End = ({x}, {y}).",
    nav_reset_live="Reset. Live: Select end, then Run.",
    nav_computing="Computing path…",
    nav_preview_fail="Path preview failed: {err}",
    nav_no_path="No path {start} → {goal}.",
    nav_path_ready="{tiles} tiles, {clicks} clicks  {start} → {goal}",
    nav_need_points="Set start and end first.",
    nav_need_end="Select end on the map first.",
    nav_press_live="Press Live first.",
    nav_sim_walk="Walking {tiles} tiles ({clicks} hops)…",
    nav_live_travel="Live travel {start} → {goal} ({tiles} tiles)…",
    nav_arrived="Arrived at {goal}.",
    nav_stopped="Stopped at {start} (goal {goal}).",
    nav_path_error="Travel error: {err}",
    nav_no_click="No click target from travel.",
    nav_click_fail="Click failed: {err}",
    nav_clicked="Clicked waypoint {wp} at screen ({x}, {y}).",
    nav_teleport="Travel asked for teleport (unstick) — skipped in this test.",
    nav_mem_fail="Memory read failed: {err}",
    confirm_clear_farms="Delete all farm areas on this map?",
    confirm_clear_patrol="Delete all patrol points on this map?",
    confirm_reload="Reload from disk and discard unsaved edits?",
    species_heading="Species",
    species_hint=(
        "Use the switch beside a monster to allow attacks. Enter a forced level, "
        "or click the monster button to reset its level to the default. "
        "A golem's forced level is the minimum character level that may attack it."
    ),
    species_level_label="Forced level",
    species_default_fmt="Default {level}",
    species_forced_fmt="Forced {level}",
    species_reset="Reset to default",
    species_blocked="off",
    species_sort_by="Sort",
    species_sort_name="Name",
    species_sort_level="Level",
    species_allow="Allow attack",
    species_done="Done",
    species_no_image="No image",
    spells_heading="Spell shortcuts",
    spells_hint=(
        "On Start the bot reads 24 hotbar slots from memory. "
        "Mapped names become keybinds automatically; unmapped slots are ignored."
    ),
    spells_usage_heading="Usage",
    spells_box="Box",
    spells_box_n="Box {n}",
    spells_key="Key",
    spell_empty="(empty)",
    spell_enabled="Enabled",
    spell_assign="Skill",
    spells_cell_hint="Detected F5–F12 slots for this box.",
    spell_off="off",
    spell_buff_cd="Recast buffs every (minutes)",
    spell_heal_until="Stop healing when HP reaches",
    spell_mana_reserve="Keep this much mana unused",
    spell_heal_double="Double-press heal",
    spell_cooldown="Reuse",
    spell_gcd_note="Cast modes and reuse timers come from built-in role defaults.",
    spell_cast="Cast",
    spell_cast_press="Press once",
    spell_cast_double="Double press",
    reset_spells="Reset spells to defaults",
    restore_spells_q="Restore default spell keys and usage?",
    spell_conflict="{a} and {b} cannot share the same box and key.",
    spells_detected_heading="Detected hotbars",
    spells_waiting_scan="Start the bot once to scan skill boxes 1–3.",
    spells_active_heading="Roles the bot will use",
    spells_ignored="ignored",
    spells_unmapped="unmapped",
    spell_titles={
        "power_up": "Power-up",
        "armor_up": "Armor-up",
        "light": "Light",
        "heal": "Heal",
        "hp_potion": "HP potion",
        "teleport": "Teleport",
        "mage_attack": "Mage attack",
        "talking_scroll": "Talking scroll",
        "mother_tree": "Mother tree",
        "hp_to_mp": "HP to MP",
        "depoison": "Antidote",
    },
    spell_guides={
        "power_up": "Weapon power buff (holy weapon, enchant weapon, …).",
        "armor_up": "Armor buff (shell, …).",
        "light": "Light buff.",
        "heal": "Healing spell.",
        "hp_potion": "HP potion (item).",
        "teleport": "Teleport skill.",
        "mage_attack": "Mage attack spell (energy bolt, …).",
        "talking_scroll": "Talking scroll item. Opens the top-left list; the bot clicks a row to teleport. Keep Favorites empty so row order stays fixed.",
        "mother_tree": "Elf Return to Mother Tree. Instant warp to the tree to recover HP and MP, then talking-scroll home.",
        "hp_to_mp": "Convert HP into MP. Used at the Mother Tree once HP is full, to fill MP faster.",
    },
    wizard_spells_note="Skill keys are read from memory on every Start (24 slots: F1–F3 pages, F5–F12). Fill hotbar_role_map.csv so names map to bot roles.",
    hotkeys_intro="These shortcuts work even when the game is focused.",
    change="Change",
    reset_hotkeys="Reset to defaults",
    hotkeys_tip=(
        "Tip: Move the cursor outside the game or Alt-Tab to pause, "
        "then click Stop — or press Stop bot."
    ),
    change_shortcut_title="Change shortcut",
    press_new_shortcut="Press new shortcut for {action}…",
    waiting="Waiting…",
    hotkey_need_modifier="Add a modifier, e.g. Alt+A.",
    hotkey_conflict="That shortcut is already used by {action}.",
    restore_hotkeys_q="Restore default hotkeys?",
    always_on_top="Always on top",
    humanize="Humanize mouse / keys",
    language="Language",
    language_hint="Applies immediately to this window.",
    memory_section="Memory",
    load_driver="Load signed driver (admin)…",
    monitor_path_hint=(
        "Reads player HP/MP/position in this process from "
        "analysis/realtime_monitor.dll. Offsets: {path}. "
        "No separate console. Load the signed driver first; LC.exe should be running."
    ),
    setup_section="Setup",
    run_wizard="Run setup wizard…",
    logs_support="Logs & support",
    open_log_folder="Open log folder",
    copy_diagnostics="Copy diagnostics",
    danger_zone="Danger zone",
    reset_all="Reset all settings to defaults…",
    profiles_section="Settings profiles",
    profile_name="Profile name",
    profile_save_as="Save current settings as",
    profile_saved_profiles="Saved profiles",
    profile_save="Save",
    profile_load="Load",
    profile_delete="Delete",
    profile_select="Select a saved profile",
    profile_saved="Settings profile “{name}” saved.",
    profile_loaded="Settings profile “{name}” loaded.",
    profile_deleted="Settings profile “{name}” deleted.",
    profile_overwrite_q="A profile named “{name}” already exists. Overwrite it?",
    profile_delete_q="Delete settings profile “{name}”? This cannot be undone.",
    profile_name_invalid="Enter a valid profile name (1–40 letters, numbers, spaces, . _ or -).",
    accounts_section="Login accounts",
    account_secure_hint="Passwords are protected for your Windows user and are never saved in profiles.",
    account_select="Account",
    account_none="No accounts saved",
    account_add="Add",
    account_update="Update",
    account_delete="Delete",
    account_display_name="Display name",
    account_username="Email",
    account_password="Password",
    account_server_language="Server language",
    account_server="Server",
    account_character="Character number",
    account_click_mode="Click mode",
    account_purple_path="Purple launcher",
    account_game_path="Game executable",
    account_browse="Browse…",
    account_saved="Account saved securely.",
    account_deleted="Account deleted.",
    account_delete_q="Delete account “{name}”? This cannot be undone.",
    account_error_title="Account",
    account_invalid_username="Enter a valid email address.",
    account_invalid_password="Password must be at least 4 characters.",
    account_invalid_display_name="Display name must be 1–40 characters.",
    account_invalid_server_language="Select a valid server language.",
    account_invalid_server="Enter a server name (up to 80 characters).",
    account_invalid_character="Character number must be from 1 to 3.",
    account_invalid_purple_path="Select an existing Purple launcher executable.",
    account_invalid_game_path="Select an existing game executable.",
    account_server_language_ko="Korean",
    account_server_language_zh_cn="Chinese (Simplified)",
    account_server_language_zh_tw="Chinese (Traditional)",
    account_server_language_ja="Japanese",
    account_duplicate="That email address is already saved.",
    account_storage_error="The secure account store could not be updated.",
    autologin_account_required="Select or add an autologin account in Advanced.",
    autologin_starting="Starting Purple autologin…",
    autologin_status="Autologin: {status}",
    autologin_cancelled="Autologin was cancelled.",
    autologin_failed="Autologin failed: {detail}",
    recovery_starting="The game closed. Starting automatic recovery…",
    recovery_completed="Automatic recovery completed.",
    recovery_limit="Automatic recovery stopped after too many recent game closures.",
    setup="Setup",
    stop_to_change_setup="Stop the bot to change Setup.",
    cannot_start="Cannot start",
    memory_title="Memory",
    memory_connected="Connected.\n{detail}",
    memory_failed="Could not connect.\n{detail}\n\n"
    "Try Load signed driver, then Start monitor again "
    "(approve UAC). LC.exe should be running.",
    memory_failed_detail="Monitor ensure failed unexpectedly.",
    driver_title="Driver",
    driver_ok="{msg}\n\nApprove UAC if prompted, then use Start monitor & connect.",
    driver_fail_prefix="{msg}",
    drivers_setup="Set up drivers",
    drivers_setup_hint="Both drivers must be ready before the bot can start.",
    interception_driver="Interception input",
    install_interception="Install input driver (admin)…",
    setup_memory_reader="Set up memory reader (admin)…",
    check_again="Check again",
    driver_ready="Ready",
    driver_not_ready="Not ready",
    driver_restart_hint="Restart Windows after installing the input driver.",
    stop_open_setup_q="Stop the bot and open setup?",
    reset_title="Reset",
    reset_confirm="Reset all settings to defaults? This cannot be undone.",
    settings_reset_log="Settings reset to defaults",
    wizard_done_log="Setup wizard completed",
    diagnostics_copied="Diagnostics copied to clipboard",
    memory_connected_session="Memory connected (bot session)",
    logs={
        "running": "{via} → Running",
        "auto_pause": "Auto-pause ({code})",
        "start_paused": "Start → Paused ({code}) — will resume when game is focused",
        "start_running": "Start → Running",
        "resume_wait": (
            "Resume requested — click the game window "
            "(bot resumes automatically when focused)"
        ),
        "paused_hotkey": "Paused — hotkey",
        "stop_stopped": "Stop → Stopped",
        "stop_stopped_reason": "Stop → Stopped ({reason})",
        "worker_exited": "Bot worker exited",
        "hotbar_reading": "Reading hotbar from memory (24 slots)…",
        "hotbar_done": "Hotbar scan done · {roles}",
        "hotbar_done_none": "Hotbar scan done · no mapped roles",
        "hotbar_unmapped": "Unmapped hotbar icons: {names}",
        "hotbar_cancelled": "Hotbar scan cancelled.",
        "hotbar_failed": "Hotbar scan failed: {error}",
        "hotbar_save_failed": "Could not save detected spell slots: {error}",
        "loop_ready": (
            "Loop ready · {character} · {game_language} · "
            "map={map} · loot={loot} · farms={farms}"
        ),
        "inventory_started": (
            "Inventory listen started · {via} seed · "
            "hp={hp} arrows={arrows} silver={silver} depoison={depoison} "
            "(live scan in background)"
        ),
        "inventory_scanning": (
            "Inventory listen scanning in background ({dll} or place inv.json)."
        ),
        "inventory_setup_failed": "Inventory listen setup failed: {error}",
        "inventory_ready": (
            "Inventory listen ready (dll) · "
            "hp={hp} arrows={arrows} silver={silver} depoison={depoison}"
        ),
    },
    reason={
        "not_focused": "Paused — game is not in focus.",
        "cursor_outside": "Paused — cursor left the game window.",
        "minimized": "Paused — game window is minimized.",
        "memory_down": "Paused — memory monitor disconnected.",
        "user_pause": "Paused — hotkey.",
        "game_closed": "Stopped — game window was closed.",
        "ready_for_resume": (
            "Ready — click the game window "
            "(bot resumes when the game is focused)."
        ),
        "resume_hint": (
            "Click the game window — the bot resumes automatically when focused."
        ),
    },
    start_fail={
        "start_no_game": "Cannot start — game window not found.",
        "start_no_memory": (
            "Cannot start — memory monitor is not ready. "
            "Approve UAC if prompted, then try Start again."
        ),
        "start_no_setup": "Cannot start — finish Setup first.",
        "start_no_farms": "Select at least one farm in Farms.",
        "start_no_patrol": "Add at least one patrol point on the Map tab.",
        "map_missing": "Cannot start — map data is missing.",
    },
    loot_labels={
        "all_items": {
            "title": "Pick up everything",
            "desc": "Loot all reachable drops (adená and other items).",
        },
        "adena_only": {
            "title": "Adená only",
            "desc": "Only pick up adená; ignore other ground items.",
        },
    },
    loot_weight_note=(
        "If bag weight is above {pct}%, the bot temporarily picks up adená only."
    ),
    char_blurbs={
        "mage": "Casts spells on targets in range.",
        "elf": "Clicks to attack on a steady rhythm.",
        "knight": "Holds mouse on the target to melee.",
        "royal": "Royal melee class.",
    },
    char_titles={"mage": "Mage", "elf": "Elf", "knight": "Knight", "royal": "Royal"},
    hotkey_labels={
        "pause_resume": "Pause / Resume",
        "stop": "Stop bot",
    },
    wizard_title="Setup — Manmabot v1",
    wizard_back="Back",
    wizard_continue="Continue",
    wizard_finish="Finish",
    wizard_step="Step {cur} of {total}",
    wizard_block_close="Finish the setup wizard to use Manmabot v1.",
    wizard_welcome="Welcome",
    wizard_welcome_body=(
        "This assistant sets up Manmabot for the map you choose.\n\n"
        "We'll check your memory driver, game window, character, "
        "map, and farms.\n\n"
        "You need: LC.exe running, and the signed memory driver loaded."
    ),
    wizard_memory_hint=(
        "Reads player HP/MP/position in this process. "
        "Approve UAC if the driver must be loaded. LC.exe should be running. "
        "Change offsets in analysis/offsets.json."
    ),
    wizard_not_tested="Not tested",
    wizard_starting_monitor="Starting monitor…",
    monitor_closing="Closing memory monitor…",
    monitor_closed="Memory monitor closed.",
    monitor_close_failed="Could not close memory monitor: {detail}",
    bring_to_front="Bring to front",
    wizard_loot_survival="Loot & survival",
    drink_hp_pct="Drink HP potion below %",
    escape_hp_pct="Escape when HP below %",
    wizard_farms_title="Farms",
    wizard_map_title="Map",
    wizard_map_body="Choose the map pack the bot will use. You can change this later in Setup.",
    wizard_dungeon_farms=(
        "This map is a dungeon — farming areas are not used. "
        "Place patrol points on the Farms tab after setup."
    ),
    select_one_farm="Select at least one farm.",
    wizard_hotkeys="Hotkeys",
    wizard_hotkeys_later="You can change these later in Advanced.",
    wizard_review="Review",
    wizard_review_body=(
        "Character: {character}\n"
        "Game language: {game}\n"
        "Map: {map}\n"
        "Loot: {loot}\n"
        "Farms: {farms}\n"
        "Hotkeys: Pause {pause} · Stop {stop}\n"
        "{spells}\n\n"
        "Safety:\n"
        "• Cursor leaving the game or losing focus pauses the bot.\n"
        "• Resume is manual.\n"
        "• Stop after pause, or use the Stop hotkey."
    ),
    game_not_found="Game window not found. Start Lineage, then Detect.",
    no_farms="No farms available.",
    memory_continue_anyway=(
        "Memory monitor is not ready. Continue anyway?\n"
        "(Start will be blocked until it connects.)"
    ),
    game_continue_anyway=(
        "Game window not found. Continue anyway?\n"
        "(Start will be blocked until Lineage is running.)"
    ),
)


_KO = UiStrings(
    window_title="Manmabot v1",
    brand="Manmabot",
    brand_sub="Version 1 (라이선스 없음)",
    lamp_game="게임",
    lamp_memory="메모리",
    lamp_map="맵",
    headline_stopped="정지",
    headline_running="실행 중",
    headline_paused="일시정지",
    ready_to_start="시작할 준비가 되었습니다.",
    btn_start="시작",
    btn_resume="재개",
    btn_stop="중지",
    show_preview="실시간 미리보기",
    preview_title="비전 미리보기",
    preview_waiting="프레임 대기 중…",
    tab_setup="설정",
    tab_farms="사냥터",
    tab_species="종",
    tab_spells="스킬",
    tab_hotkeys="단축키",
    tab_advanced="고급",
    tab_log="로그",
    tab_nav="이동 테스트",
    region="맵",
    region_locked="말하는 섬 (고정)",
    map_select="맵",
    map_hint="봇이 정지된 동안에만 맵을 바꿀 수 있습니다.",
    map_preview_missing="맵 이미지가 아직 없습니다.",
    game_window="게임 창",
    not_checked="확인 안 됨",
    detect="감지",
    bring_game_front="게임 창 앞으로",
    character="캐릭터",
    game_language="게임 언어",
    game_language_hint="리니지 클라이언트 언어입니다. 상점 등 일부 클릭 위치가 달라집니다.",
    game_lang_ko="한국어",
    game_lang_zh="중국어",
    loot="룻",
    loot_adena_weight="무게가 이 값 이상이면 아데나만 줍기",
    survival="생존",
    drink_hp="HP 물약 사용 (이하)",
    escape_hp="HP 이하일 때 탈출",
    escape_mp="MP 이하일 때 탈출",
    reset_survival="생존 설정 초기화",
    buy_arrows="화살 구매",
    buy_arrows_hint="잡화 상인에서 살 화살 개수 (1–999). 일반/은화살 중 하나만 선택.",
    buy_normal_arrows="일반 화살 구매",
    buy_silver_arrows="은화살 구매",
    silver_arrow_qty="은화살 수량",
    restock_potions="물약 보충",
    restock_potions_hint="가방 체력 회복제가 Fix/Return 기준 이하이면 상점에서 보충.",
    memory="메모리",
    test_connection="연결 테스트",
    start_monitor="모니터 시작 & 연결",
    farms_heading="사냥터",
    farms_hint_empty=(
        "사냥터를 하나 이상 선택하거나, 사냥터 편집에서 새 영역을 그리세요."
    ),
    farms_banner="사냥터 {n}/{total} 사용 · {minutes:.0f}분마다 순환",
    select_all="모두 선택",
    clear="선택 해제",
    rotate_farms="사냥터 순환 주기 (분)",
    draw_farm="사냥터 그리기",
    place_patrol="패트롤 배치",
    delete_selected="삭제",
    save_areas="저장",
    editor_hint_island="사냥터 그리기: 박스를 드래그하세요. 핸들을 끌어 크기를 바꿉니다.",
    editor_hint_dungeon="패트롤 배치: 이동 가능한 타일을 클릭하세요. 마커를 끌어 옮깁니다.",
    saved_areas="이 맵의 사냥터를 저장했습니다.",
    saved_patrol="이 던전의 패트롤 지점을 저장했습니다.",
    farms_unsupported_dungeon=(
        "던전에서는 사냥터 영역을 사용하지 않습니다. 패트롤 편집에서 지점을 배치하세요."
    ),
    patrol_not_walkable="이동할 수 없는 타일입니다.",
    map_missing_short="맵 이미지가 없습니다.",
    select_tool="선택",
    duplicate="복제",
    move_up="위로",
    move_down="아래로",
    clear_all="모두 지우기",
    reload_areas="다시 불러오기",
    edit_farms="사냥터 편집",
    edit_patrol="패트롤 편집",
    edit_done="완료",
    editor_close="닫기",
    editor_list="목록",
    editor_list_empty="아직 없습니다 — 지도에서 그리거나 배치하세요.",
    rename_label="이름",
    editor_hover="타일 {x}, {y}",
    editor_nav_hint="휠 또는 Ctrl+휠 확대 · 오른쪽 드래그 이동 · Delete로 선택 삭제.",
    nav_heading="이동 테스트",
    nav_hint=(
        "Live는 게임 속 현재 타일을 읽습니다. 지도에서 시작점과 끝점을 고른 뒤 Run을 누르세요. "
        "Live Run은 봇과 같은 이동 코드로 캐릭터를 걷게 합니다. "
        "봇이 실행 중이면 쓸 수 없습니다."
    ),
    nav_live="Live",
    nav_select_start="시작점",
    nav_select_end="끝점",
    nav_run="실행",
    nav_reset="초기화",
    nav_idle="시작점, 끝점을 고른 뒤 실행하세요. Live를 누르면 캐릭터 위치가 시작점입니다.",
    nav_building="이 맵의 경로 탐색을 만드는 중…",
    nav_build_fail="경로 탐색을 만들지 못했습니다: {err}",
    nav_live_connecting="Live 연결 중 (메모리 + 게임 창)…",
    nav_live_on="Live 켜짐. 위치 {pos}. 끝점을 고른 뒤 실행하세요.",
    nav_live_fail="Live 실패: {err}",
    nav_live_no_window="Live: 게임 창을 찾지 못했습니다.",
    nav_live_no_pos="Live: 캐릭터 위치를 읽지 못했습니다.",
    nav_live_start_locked="Live: 시작점은 캐릭터입니다. 끝점을 고르세요.",
    nav_live_lost="Live: 캐릭터 위치를 잃었습니다.",
    nav_bot_running="Live 또는 Live 실행 전에 봇을 중지하세요.",
    nav_click_tile="이동 가능한 타일을 클릭하세요 ({kind}).",
    nav_blocked="막힌 타일 ({x}, {y}). 흰 땅을 클릭하세요.",
    nav_start_set="시작점 = ({x}, {y}). 이제 끝점을 고르세요.",
    nav_end_set="끝점 = ({x}, {y}).",
    nav_reset_live="초기화됨. Live: 끝점을 고른 뒤 실행하세요.",
    nav_computing="경로 계산 중…",
    nav_preview_fail="경로 미리보기 실패: {err}",
    nav_no_path="경로 없음 {start} → {goal}.",
    nav_path_ready="{tiles}칸, 클릭 {clicks}회  {start} → {goal}",
    nav_need_points="시작점과 끝점을 먼저 지정하세요.",
    nav_need_end="지도에서 끝점을 먼저 고르세요.",
    nav_press_live="먼저 Live를 누르세요.",
    nav_sim_walk="{tiles}칸 이동 중 (홉 {clicks}회)…",
    nav_live_travel="Live 이동 {start} → {goal} ({tiles}칸)…",
    nav_arrived="{goal}에 도착했습니다.",
    nav_stopped="{start}에서 멈춤 (목표 {goal}).",
    nav_path_error="이동 오류: {err}",
    nav_no_click="이동에서 클릭 목표가 없습니다.",
    nav_click_fail="클릭 실패: {err}",
    nav_clicked="경유점 {wp} 클릭, 화면 ({x}, {y}).",
    nav_teleport="이동이 텔레포트(unstick)를 요청했습니다 — 이 테스트에서는 건너뜁니다.",
    nav_mem_fail="메모리 읽기 실패: {err}",
    confirm_clear_farms="이 맵의 사냥터를 모두 삭제할까요?",
    confirm_clear_patrol="이 맵의 패트롤 지점을 모두 삭제할까요?",
    confirm_reload="디스크에서 다시 불러오고 저장하지 않은 편집을 버릴까요?",
    species_heading="종",
    species_hint=(
        "몬스터 옆 스위치로 공격을 허용하고 강제 레벨을 입력하세요. "
        "몬스터 버튼을 누르면 레벨이 기본값으로 돌아갑니다. "
        "골렘의 강제 레벨은 깨어 있어도 공격할 수 있는 최소 캐릭터 레벨입니다."
    ),
    species_level_label="강제 레벨",
    species_default_fmt="기본 {level}",
    species_forced_fmt="강제 {level}",
    species_reset="기본값으로",
    species_blocked="끔",
    species_sort_by="정렬",
    species_sort_name="이름",
    species_sort_level="레벨",
    species_allow="공격 허용",
    species_done="완료",
    species_no_image="이미지 없음",
    spells_heading="스킬 단축키",
    spells_hint=(
        "시작할 때 봇이 메모리에서 핫바 24칸을 읽습니다. "
        "매핑된 이름만 자동으로 단축키가 되고, 매핑되지 않은 칸은 무시합니다."
    ),
    spells_usage_heading="사용 방식",
    spells_box="창",
    spells_box_n="{n}번 창",
    spells_key="키",
    spell_empty="(비움)",
    spell_enabled="사용",
    spell_assign="스킬",
    spells_cell_hint="이 창에서 감지된 F5–F12 칸입니다.",
    spell_off="끔",
    spell_buff_cd="버프 재사용 (분)",
    spell_heal_until="힐을 멈출 HP",
    spell_mana_reserve="남겨 둘 마나",
    spell_heal_double="힐 두 번 누르기",
    spell_cooldown="재사용",
    spell_gcd_note="시전 방식과 재사용 시간은 역할 기본값을 따릅니다.",
    spell_cast="시전",
    spell_cast_press="한 번",
    spell_cast_double="두 번",
    reset_spells="스킬 기본값으로",
    restore_spells_q="스킬 키와 사용 방식을 기본값으로 되돌릴까요?",
    spell_conflict="{a}와 {b}는 같은 창·키를 쓸 수 없습니다.",
    spells_detected_heading="감지된 핫바",
    spells_waiting_scan="봇을 한 번 시작해 1–3번 창을 스캔하세요.",
    spells_active_heading="봇이 사용할 역할",
    spells_ignored="무시",
    spells_unmapped="미매핑",
    spell_titles={
        "power_up": "파워 업",
        "armor_up": "아머 업",
        "light": "라이트",
        "heal": "힐",
        "hp_potion": "HP 물약",
        "teleport": "텔레포트",
        "mage_attack": "마법 공격",
        "talking_scroll": "말하는 두루마리",
        "mother_tree": "마더 트리",
        "hp_to_mp": "HP를 MP로",
        "depoison": "해독제",
    },
    spell_guides={
        "power_up": "무기 강화 버프(홀리 웨폰, 인챈트 웨폰 등).",
        "armor_up": "방어 버프(셸 등).",
        "light": "라이트 버프.",
        "heal": "힐 스킬.",
        "hp_potion": "HP 물약(아이템).",
        "teleport": "텔레포트 스킬.",
        "mage_attack": "마법 공격 스킬(에너지 볼트 등).",
        "talking_scroll": "말하는 두루마리(아이템). 왼쪽 위 목록이 열리면 줄을 클릭해 이동합니다. 즐겨찾기를 비워 두세요. 넣으면 아래 줄이 밀립니다.",
        "mother_tree": "요정 마더 트리로 귀환. 세계수로 즉시 이동해 HP·MP를 회복한 뒤 말하는 두루마리로 돌아옵니다.",
        "hp_to_mp": "HP를 MP로 전환. 마더 트리에서 HP가 가득 찬 뒤 MP를 빨리 채울 때 씁니다.",
    },
    wizard_spells_note="시작할 때마다 메모리에서 핫바 24칸(F1–F3 창, F5–F12)을 읽습니다. hotbar_role_map.csv에 이름→역할 매핑을 채우세요.",
    hotkeys_intro="게임이 활성화된 상태에서도 이 단축키가 동작합니다.",
    change="변경",
    reset_hotkeys="기본값으로 복원",
    hotkeys_tip=(
        "팁: 커서를 게임 밖으로 옮기거나 Alt-Tab으로 일시정지한 뒤 "
        "중지를 누르거나, 중지 단축키를 사용하세요."
    ),
    change_shortcut_title="단축키 변경",
    press_new_shortcut="{action} 새 단축키를 누르세요…",
    waiting="대기 중…",
    hotkey_need_modifier="Alt+A처럼 수정 키를 포함하세요.",
    hotkey_conflict="이미 {action}에 사용 중인 단축키입니다.",
    restore_hotkeys_q="기본 단축키로 복원할까요?",
    always_on_top="항상 위",
    humanize="마우스/키 인간화",
    language="언어",
    language_hint="이 창에 바로 적용됩니다.",
    memory_section="메모리",
    load_driver="서명 드라이버 로드 (관리자)…",
    monitor_path_hint=(
        "이 프로세스에서 analysis/realtime_monitor.dll로 플레이어 HP/MP/위치를 읽습니다. "
        "오프셋: {path}. 별도 콘솔은 없습니다. 서명 드라이버를 먼저 로드하고 LC.exe가 실행 중이어야 합니다."
    ),
    setup_section="설정",
    run_wizard="설정 마법사 실행…",
    logs_support="로그 & 지원",
    open_log_folder="로그 폴더 열기",
    copy_diagnostics="진단 정보 복사",
    danger_zone="위험 구역",
    reset_all="모든 설정을 기본값으로…",
    profiles_section="설정 프로필",
    profile_name="프로필 이름",
    profile_save_as="현재 설정을 다른 이름으로 저장",
    profile_saved_profiles="저장된 프로필",
    profile_save="저장",
    profile_load="불러오기",
    profile_delete="삭제",
    profile_select="저장된 프로필 선택",
    profile_saved="설정 프로필 “{name}”을 저장했습니다.",
    profile_loaded="설정 프로필 “{name}”을 불러왔습니다.",
    profile_deleted="설정 프로필 “{name}”을 삭제했습니다.",
    profile_overwrite_q="“{name}” 프로필이 이미 있습니다. 덮어쓸까요?",
    profile_delete_q="“{name}” 설정 프로필을 삭제할까요? 되돌릴 수 없습니다.",
    profile_name_invalid="올바른 프로필 이름을 입력하세요 (1–40자, 문자/숫자/공백/._-).",
    accounts_section="로그인 계정",
    account_secure_hint="암호는 현재 Windows 사용자용으로 보호되며 프로필에는 저장되지 않습니다.",
    account_select="계정",
    account_none="저장된 계정 없음",
    account_add="추가",
    account_update="수정",
    account_delete="삭제",
    account_display_name="표시 이름",
    account_username="이메일",
    account_password="암호",
    account_server_language="서버 언어",
    account_server="서버",
    account_character="캐릭터 번호",
    account_click_mode="클릭 모드",
    account_purple_path="Purple 실행 파일",
    account_game_path="게임 실행 파일",
    account_browse="찾아보기…",
    account_saved="계정을 안전하게 저장했습니다.",
    account_deleted="계정을 삭제했습니다.",
    account_delete_q="“{name}” 계정을 삭제할까요? 되돌릴 수 없습니다.",
    account_error_title="계정",
    account_invalid_username="올바른 이메일 주소를 입력하세요.",
    account_invalid_password="암호는 4자 이상이어야 합니다.",
    account_invalid_display_name="표시 이름은 1–40자여야 합니다.",
    account_invalid_server_language="올바른 서버 언어를 선택하세요.",
    account_invalid_server="서버 이름을 입력하세요 (최대 80자).",
    account_invalid_character="캐릭터 번호는 1에서 3 사이여야 합니다.",
    account_invalid_purple_path="존재하는 Purple 실행 파일을 선택하세요.",
    account_invalid_game_path="존재하는 게임 실행 파일을 선택하세요.",
    account_server_language_ko="한국어",
    account_server_language_zh_cn="중국어(간체)",
    account_server_language_zh_tw="중국어(번체)",
    account_server_language_ja="일본어",
    account_duplicate="이미 저장된 이메일 주소입니다.",
    account_storage_error="보안 계정 저장소를 업데이트하지 못했습니다.",
    autologin_account_required="고급 설정에서 자동 로그인 계정을 선택하거나 추가하세요.",
    autologin_starting="Purple 자동 로그인을 시작하는 중…",
    autologin_status="자동 로그인: {status}",
    autologin_cancelled="자동 로그인이 취소되었습니다.",
    autologin_failed="자동 로그인 실패: {detail}",
    recovery_starting="게임이 종료되었습니다. 자동 복구를 시작합니다…",
    recovery_completed="자동 복구가 완료되었습니다.",
    recovery_limit="최근 게임 종료가 너무 많아 자동 복구를 중지했습니다.",
    setup="설정",
    stop_to_change_setup="설정을 바꾸려면 봇을 중지하세요.",
    cannot_start="시작할 수 없음",
    memory_title="메모리",
    memory_connected="연결됨.\n{detail}",
    memory_failed=(
        "연결할 수 없습니다.\n{detail}\n\n"
        "서명 드라이버를 로드한 뒤 모니터 시작을 다시 시도하세요 "
        "(UAC 승인). LC.exe가 실행 중이어야 합니다."
    ),
    memory_failed_detail="모니터 시작이 예기치 않게 실패했습니다.",
    driver_title="드라이버",
    driver_ok="{msg}\n\nUAC가 뜨면 승인한 뒤 모니터 시작 & 연결을 사용하세요.",
    driver_fail_prefix="{msg}",
    drivers_setup="드라이버 설정",
    drivers_setup_hint="봇을 시작하려면 두 드라이버가 모두 준비되어야 합니다.",
    interception_driver="Interception 입력",
    install_interception="입력 드라이버 설치 (관리자)…",
    setup_memory_reader="메모리 읽기 설정 (관리자)…",
    check_again="다시 확인",
    driver_ready="준비됨",
    driver_not_ready="준비 안 됨",
    driver_restart_hint="입력 드라이버를 설치한 뒤 Windows를 다시 시작하세요.",
    stop_open_setup_q="봇을 중지하고 설정을 열까요?",
    reset_title="초기화",
    reset_confirm="모든 설정을 기본값으로 되돌릴까요? 되돌릴 수 없습니다.",
    settings_reset_log="설정을 기본값으로 초기화했습니다",
    wizard_done_log="설정 마법사 완료",
    diagnostics_copied="진단 정보를 클립보드에 복사했습니다",
    memory_connected_session="메모리 연결됨 (봇 세션)",
    logs={
        "running": "{via} → 실행 중",
        "auto_pause": "자동 일시정지 ({code})",
        "start_paused": "시작 → 일시정지 ({code}) — 게임에 포커스되면 재개합니다",
        "start_running": "시작 → 실행 중",
        "resume_wait": (
            "재개를 요청했습니다 — 게임 창을 클릭하세요 "
            "(포커스되면 자동으로 재개됩니다)"
        ),
        "paused_hotkey": "일시정지 — 단축키",
        "stop_stopped": "정지 → 중지됨",
        "stop_stopped_reason": "정지 → 중지됨 ({reason})",
        "worker_exited": "봇 작업이 종료되었습니다",
        "hotbar_reading": "메모리에서 핫바 24칸을 읽는 중…",
        "hotbar_done": "핫바 스캔 완료 · {roles}",
        "hotbar_done_none": "핫바 스캔 완료 · 매핑된 역할 없음",
        "hotbar_unmapped": "매핑되지 않은 핫바 아이콘: {names}",
        "hotbar_cancelled": "핫바 스캔이 취소되었습니다.",
        "hotbar_failed": "핫바 스캔 실패: {error}",
        "hotbar_save_failed": "감지된 스킬 칸을 저장하지 못했습니다: {error}",
        "loop_ready": (
            "루프 준비 · {character} · {game_language} · "
            "맵={map} · 룻={loot} · 구역={farms}"
        ),
        "inventory_started": (
            "인벤토리 수신 시작 · {via} 시드 · "
            "hp={hp} 화살={arrows} 은화살={silver} 해독={depoison} "
            "(백그라운드 실시간 스캔)"
        ),
        "inventory_scanning": (
            "인벤토리를 백그라운드에서 스캔 중 "
            "({dll} 또는 inv.json을 두세요)."
        ),
        "inventory_setup_failed": "인벤토리 수신 설정 실패: {error}",
        "inventory_ready": (
            "인벤토리 수신 준비 (dll) · "
            "hp={hp} 화살={arrows} 은화살={silver} 해독={depoison}"
        ),
    },
    reason={
        "not_focused": "일시정지 — 게임이 포커스가 아닙니다.",
        "cursor_outside": "일시정지 — 커서가 게임 창을 벗어났습니다.",
        "minimized": "일시정지 — 게임 창이 최소화되었습니다.",
        "memory_down": "일시정지 — 메모리 모니터 연결이 끊겼습니다.",
        "user_pause": "일시정지 — 단축키.",
        "game_closed": "정지 — 게임 창이 닫혔습니다.",
        "ready_for_resume": (
            "준비됨 — 게임 창을 클릭하세요 "
            "(게임이 포커스되면 봇이 재개됩니다)."
        ),
        "resume_hint": (
            "게임 창을 클릭하세요 — 포커스되면 봇이 자동으로 재개됩니다."
        ),
    },
    start_fail={
        "start_no_game": "시작할 수 없음 — 게임 창을 찾을 수 없습니다.",
        "start_no_memory": (
            "시작할 수 없음 — 메모리 모니터가 준비되지 않았습니다. "
            "UAC가 뜨면 승인한 뒤 다시 시작하세요."
        ),
        "start_no_setup": "시작할 수 없음 — 설정을 먼저 완료하세요.",
        "start_no_farms": "사냥터 탭에서 하나 이상 선택하세요.",
        "start_no_patrol": "맵 탭에서 패트롤 지점을 하나 이상 추가하세요.",
        "map_missing": "시작할 수 없음 — 맵 데이터가 없습니다.",
    },
    loot_labels={
        "all_items": {
            "title": "전부 줍기",
            "desc": "닿는 드롭을 모두 룻합니다 (아데나 및 기타 아이템).",
        },
        "adena_only": {
            "title": "아데나만",
            "desc": "아데나만 줍고 다른 아이템은 무시합니다.",
        },
    },
    loot_weight_note=(
        "가방 무게가 {pct}%를 넘으면 일시적으로 아데나만 줍습니다."
    ),
    char_blurbs={
        "mage": "사거리 안 대상에게 마법을 시전합니다.",
        "elf": "일정한 리듬으로 클릭하여 공격합니다.",
        "knight": "대상에 마우스를 눌러 근접 공격을 유지합니다.",
        "royal": "로얄 근접 클래스.",
    },
    char_titles={"mage": "마법사", "elf": "요정", "knight": "기사", "royal": "로얄"},
    hotkey_labels={
        "pause_resume": "일시정지 / 재개",
        "stop": "봇 중지",
    },
    wizard_title="설정 — Manmabot v1",
    wizard_back="뒤로",
    wizard_continue="계속",
    wizard_finish="완료",
    wizard_step="{cur} / {total} 단계",
    wizard_block_close="Manmabot v1를 사용하려면 설정 마법사를 완료하세요.",
    wizard_welcome="환영합니다",
    wizard_welcome_body=(
        "이 어시스턴트는 선택한 맵으로 Manmabot을 설정합니다.\n\n"
        "메모리 드라이버, 게임 창, 캐릭터, 맵, 사냥터를 확인합니다.\n\n"
        "필요: LC.exe 실행, 서명된 메모리 드라이버 로드."
    ),
    wizard_memory_hint=(
        "이 프로세스에서 플레이어 HP/MP/위치를 읽습니다. "
        "드라이버 로드가 필요하면 UAC를 승인하세요. LC.exe가 실행 중이어야 합니다. "
        "오프셋은 analysis/offsets.json에서 바꿉니다."
    ),
    wizard_not_tested="테스트 안 됨",
    wizard_starting_monitor="모니터 시작 중…",
    monitor_closing="메모리 모니터를 닫는 중…",
    monitor_closed="메모리 모니터를 닫았습니다.",
    monitor_close_failed="메모리 모니터를 닫지 못했습니다: {detail}",
    bring_to_front="앞으로 가져오기",
    wizard_loot_survival="룻 & 생존",
    drink_hp_pct="HP 물약 사용 (이하 %)",
    escape_hp_pct="HP 이하일 때 탈출 %",
    wizard_farms_title="사냥터",
    wizard_map_title="맵",
    wizard_map_body="봇이 사용할 맵 팩을 고르세요. 나중에 설정에서 바꿀 수 있습니다.",
    wizard_dungeon_farms=(
        "이 맵은 던전이라 사냥터 영역을 사용하지 않습니다. "
        "패트롤 지점은 설정 후 사냥터 탭에서 배치하세요."
    ),
    select_one_farm="사냥터를 하나 이상 선택하세요.",
    wizard_hotkeys="단축키",
    wizard_hotkeys_later="나중에 고급 탭에서 바꿀 수 있습니다.",
    wizard_review="확인",
    wizard_review_body=(
        "캐릭터: {character}\n"
        "게임 언어: {game}\n"
        "맵: {map}\n"
        "룻: {loot}\n"
        "사냥터: {farms}\n"
        "단축키: 일시정지 {pause} · 중지 {stop}\n"
        "{spells}\n\n"
        "안전:\n"
        "• 커서가 게임을 벗어나거나 포커스를 잃으면 일시정지됩니다.\n"
        "• 재개는 수동입니다.\n"
        "• 일시정지 후 중지하거나 중지 단축키를 사용하세요."
    ),
    game_not_found="게임 창을 찾을 수 없습니다. 리니지를 실행한 뒤 감지를 누르세요.",
    no_farms="사용 가능한 사냥터가 없습니다.",
    memory_continue_anyway=(
        "메모리 모니터가 준비되지 않았습니다. 계속할까요?\n"
        "(연결될 때까지 시작이 막힙니다.)"
    ),
    game_continue_anyway=(
        "게임 창을 찾을 수 없습니다. 계속할까요?\n"
        "(리니지가 실행될 때까지 시작이 막힙니다.)"
    ),
)


_ZH = UiStrings(
    window_title="Manmabot v1",
    brand="Manmabot",
    brand_sub="Version 1（无许可证）",
    lamp_game="游戏",
    lamp_memory="内存",
    lamp_map="地图",
    headline_stopped="已停止",
    headline_running="运行中",
    headline_paused="已暂停",
    ready_to_start="可以开始。",
    btn_start="开始",
    btn_resume="继续",
    btn_stop="停止",
    show_preview="显示实时预览",
    preview_title="视觉预览",
    preview_waiting="等待画面…",
    tab_setup="设置",
    tab_farms="猎场",
    tab_species="物种",
    tab_spells="技能",
    tab_hotkeys="快捷键",
    tab_advanced="高级",
    tab_log="日志",
    tab_nav="导航测试",
    region="地图",
    region_locked="说话之岛（固定）",
    map_select="地图",
    map_hint="仅在机器人停止时可以更换地图。",
    map_preview_missing="还没有地图图片。",
    game_window="游戏窗口",
    not_checked="未检查",
    detect="检测",
    bring_game_front="将游戏置于前台",
    character="角色",
    game_language="游戏语言",
    game_language_hint="天堂客户端语言。商店等部分点击位置不同。",
    game_lang_ko="韩语",
    game_lang_zh="中文",
    loot="拾取",
    loot_adena_weight="负重超过此值时改为只拾取金币",
    survival="生存",
    drink_hp="HP药水触发（低于）",
    escape_hp="HP低于时逃跑",
    escape_mp="MP低于时逃跑",
    reset_survival="恢复生存默认值",
    buy_arrows="购买箭矢",
    buy_arrows_hint="在杂货商处购买的箭矢数量（1–999）。普通/银箭二选一。",
    buy_normal_arrows="购买普通箭矢",
    buy_silver_arrows="购买银箭",
    silver_arrow_qty="银箭数量",
    restock_potions="补充药水",
    restock_potions_hint="背包 HP 药水数量处于 Fix/Return 阈值及以下时去商店补货。",
    memory="内存",
    test_connection="测试连接",
    start_monitor="启动监视器并连接",
    farms_heading="猎场",
    farms_hint_empty="请至少选择一个猎场，或打开“编辑猎场”绘制新区域。",
    farms_banner="已启用 {n}/{total} 个猎场 · 每 {minutes:.0f} 分钟轮换",
    select_all="全选",
    clear="清除",
    rotate_farms="猎场轮换周期（分钟）",
    draw_farm="绘制猎场",
    place_patrol="放置巡逻点",
    delete_selected="删除",
    save_areas="保存",
    editor_hint_island="绘制猎场：拖出方框。点击选中，拖动手柄调整大小。",
    editor_hint_dungeon="放置巡逻点：点击可行走格子。拖动标记可移动。",
    saved_areas="已保存此地图的猎场。",
    saved_patrol="已保存此地下城的巡逻点。",
    farms_unsupported_dungeon="地下城不使用猎场区域。请打开“编辑巡逻”放置点。",
    patrol_not_walkable="该格子不可行走。",
    map_missing_short="缺少地图图像。",
    select_tool="选择",
    duplicate="复制",
    move_up="上移",
    move_down="下移",
    clear_all="全部清除",
    reload_areas="重新加载",
    edit_farms="编辑猎场",
    edit_patrol="编辑巡逻",
    edit_done="完成",
    editor_close="关闭",
    editor_list="列表",
    editor_list_empty="还没有项目 — 请在地图上绘制或放置。",
    rename_label="名称",
    editor_hover="格子 {x}, {y}",
    editor_nav_hint="滚轮或 Ctrl+滚轮缩放 · 右键拖动平移 · Delete 删除选中项。",
    nav_heading="导航测试",
    nav_hint=(
        "Live 读取游戏内当前格子。在地图上选择起点和终点，然后点运行。"
        "Live 运行用与机器人相同的移动代码让角色走路。"
        "请先停止机器人。"
    ),
    nav_live="Live",
    nav_select_start="选起点",
    nav_select_end="选终点",
    nav_run="运行",
    nav_reset="重置",
    nav_idle="先选起点再选终点，然后运行。或按 Live 用角色位置作为起点。",
    nav_building="正在为此地图构建寻路…",
    nav_build_fail="无法构建寻路：{err}",
    nav_live_connecting="正在连接 Live（内存 + 游戏窗口）…",
    nav_live_on="Live 已开启。位置 {pos}。请选终点，然后运行。",
    nav_live_fail="Live 失败：{err}",
    nav_live_no_window="Live：未找到游戏窗口。",
    nav_live_no_pos="Live：无法读取角色位置。",
    nav_live_start_locked="Live：起点就是角色。请改选终点。",
    nav_live_lost="Live：丢失角色位置。",
    nav_bot_running="请先停止机器人，再使用 Live 或 Live 运行。",
    nav_click_tile="点击可行走格子（{kind}）。",
    nav_blocked="阻挡格子 ({x}, {y})。请点击可行走地面。",
    nav_start_set="起点 = ({x}, {y})。请选择终点。",
    nav_end_set="终点 = ({x}, {y})。",
    nav_reset_live="已重置。Live：选择终点，然后运行。",
    nav_computing="正在计算路径…",
    nav_preview_fail="路径预览失败：{err}",
    nav_no_path="无路径 {start} → {goal}。",
    nav_path_ready="{tiles} 格，{clicks} 次点击  {start} → {goal}",
    nav_need_points="请先设置起点和终点。",
    nav_need_end="请先在地图上选择终点。",
    nav_press_live="请先按 Live。",
    nav_sim_walk="正在走 {tiles} 格（{clicks} 次跳跃）…",
    nav_live_travel="Live 移动 {start} → {goal}（{tiles} 格）…",
    nav_arrived="已到达 {goal}。",
    nav_stopped="停在 {start}（目标 {goal}）。",
    nav_path_error="移动错误：{err}",
    nav_no_click="移动没有点击目标。",
    nav_click_fail="点击失败：{err}",
    nav_clicked="点击途经点 {wp}，屏幕 ({x}, {y})。",
    nav_teleport="移动请求传送（脱困）— 本测试中跳过。",
    nav_mem_fail="内存读取失败：{err}",
    confirm_clear_farms="删除此地图上的全部猎场？",
    confirm_clear_patrol="删除此地图上的全部巡逻点？",
    confirm_reload="从磁盘重新加载并丢弃未保存的编辑？",
    species_heading="物种",
    species_hint=(
        "使用怪物旁的开关允许攻击，并输入强制等级。"
        "点击怪物按钮可将等级恢复为默认值。"
        "魔像的强制等级是即使已苏醒也允许攻击的最低角色等级。"
    ),
    species_level_label="强制等级",
    species_default_fmt="默认 {level}",
    species_forced_fmt="强制 {level}",
    species_reset="恢复默认",
    species_blocked="关",
    species_sort_by="排序",
    species_sort_name="名称",
    species_sort_level="等级",
    species_allow="允许攻击",
    species_done="完成",
    species_no_image="无图片",
    spells_heading="技能快捷键",
    spells_hint=(
        "每次启动时从内存读取 24 个快捷栏。"
        "已映射的名称会自动绑定；未映射的格子会被忽略。"
    ),
    spells_usage_heading="用法",
    spells_box="栏",
    spells_box_n="第 {n} 栏",
    spells_key="键",
    spell_empty="(空)",
    spell_enabled="启用",
    spell_assign="技能",
    spells_cell_hint="此栏检测到的 F5–F12 格子。",
    spell_off="关",
    spell_buff_cd="增益重施间隔（分钟）",
    spell_heal_until="治疗停止的 HP",
    spell_mana_reserve="保留不用的魔力",
    spell_heal_double="治疗连按两次",
    spell_cooldown="复用",
    spell_gcd_note="施放方式与复用间隔取自内置角色默认值。",
    spell_cast="施放",
    spell_cast_press="按一次",
    spell_cast_double="按两次",
    reset_spells="恢复技能默认",
    restore_spells_q="恢复默认技能键位和用法？",
    spell_conflict="{a} 与 {b} 不能使用同一栏和同一键。",
    spells_detected_heading="检测到的快捷栏",
    spells_waiting_scan="请先启动机器人一次以扫描第 1–3 栏。",
    spells_active_heading="机器人将使用的角色",
    spells_ignored="忽略",
    spells_unmapped="未映射",
    spell_titles={
        "power_up": "强化武器",
        "armor_up": "强化防具",
        "light": "照明",
        "heal": "治疗",
        "hp_potion": "HP 药水",
        "teleport": "传送",
        "mage_attack": "法师攻击",
        "talking_scroll": "说话的卷轴",
        "mother_tree": "母树",
        "hp_to_mp": "HP 转 MP",
        "depoison": "解毒剂",
    },
    spell_guides={
        "power_up": "武器强化增益（神圣武器、附魔武器等）。",
        "armor_up": "防具增益（庇护等）。",
        "light": "照明增益。",
        "heal": "治疗技能。",
        "hp_potion": "HP 药水（物品）。",
        "teleport": "传送技能。",
        "mage_attack": "法师攻击技能（能量弹等）。",
        "talking_scroll": "说话的卷轴（物品）。打开左上角列表后点击一行传送。请保持收藏为空，否则行顺序会错位。",
        "mother_tree": "精灵回归母树。立即传送到母树旁回复 HP 和 MP，再用说话的卷轴返回。",
        "hp_to_mp": "将 HP 转为 MP。在母树旁 HP 已满时用来更快回复 MP。",
    },
    wizard_spells_note="每次启动时从内存读取 24 格快捷栏（F1–F3 栏，F5–F12）。请在 hotbar_role_map.csv 中填写名称到角色的映射。",
    hotkeys_intro="即使游戏处于前台，这些快捷键也可用。",
    change="更改",
    reset_hotkeys="恢复默认",
    hotkeys_tip=(
        "提示：将光标移出游戏或按 Alt-Tab 暂停，"
        "然后点击停止——或使用停止快捷键。"
    ),
    change_shortcut_title="更改快捷键",
    press_new_shortcut="请为 {action} 按下新快捷键…",
    waiting="等待中…",
    hotkey_need_modifier="请加上修饰键，例如 Alt+A。",
    hotkey_conflict="该快捷键已被 {action} 使用。",
    restore_hotkeys_q="恢复默认快捷键？",
    always_on_top="始终置顶",
    humanize="人性化鼠标/按键",
    language="语言",
    language_hint="立即应用到此窗口。",
    memory_section="内存",
    load_driver="加载已签名驱动（管理员）…",
    monitor_path_hint=(
        "在本进程中用 analysis/realtime_monitor.dll 读取玩家 HP/MP/位置。"
        "偏移：{path}。不另开控制台。请先加载已签名驱动，且 LC.exe 正在运行。"
    ),
    setup_section="设置",
    run_wizard="运行设置向导…",
    logs_support="日志与支持",
    open_log_folder="打开日志文件夹",
    copy_diagnostics="复制诊断信息",
    danger_zone="危险操作",
    reset_all="将所有设置恢复默认…",
    profiles_section="设置配置文件",
    profile_name="配置文件名称",
    profile_save_as="将当前设置另存为",
    profile_saved_profiles="已保存的配置文件",
    profile_save="保存",
    profile_load="加载",
    profile_delete="删除",
    profile_select="选择已保存的配置文件",
    profile_saved="已保存设置配置文件“{name}”。",
    profile_loaded="已加载设置配置文件“{name}”。",
    profile_deleted="已删除设置配置文件“{name}”。",
    profile_overwrite_q="名为“{name}”的配置文件已存在。是否覆盖？",
    profile_delete_q="删除设置配置文件“{name}”？此操作无法撤销。",
    profile_name_invalid="请输入有效名称（1–40 个字符，可用字母、数字、空格及 . _ -）。",
    accounts_section="登录账号",
    account_secure_hint="密码仅供当前 Windows 用户解锁，绝不会保存到配置文件中。",
    account_select="账号",
    account_none="没有已保存账号",
    account_add="添加",
    account_update="更新",
    account_delete="删除",
    account_display_name="显示名称",
    account_username="电子邮箱",
    account_password="密码",
    account_server_language="服务器语言",
    account_server="服务器",
    account_character="角色编号",
    account_click_mode="点击模式",
    account_purple_path="Purple 启动程序",
    account_game_path="游戏可执行文件",
    account_browse="浏览…",
    account_saved="账号已安全保存。",
    account_deleted="账号已删除。",
    account_delete_q="删除账号“{name}”？此操作无法撤销。",
    account_error_title="账号",
    account_invalid_username="请输入有效的电子邮箱地址。",
    account_invalid_password="密码至少需要 4 个字符。",
    account_invalid_display_name="显示名称必须为 1–40 个字符。",
    account_invalid_server_language="请选择有效的服务器语言。",
    account_invalid_server="请输入服务器名称（最多 80 个字符）。",
    account_invalid_character="角色编号必须在 1 到 3 之间。",
    account_invalid_purple_path="请选择现有的 Purple 启动程序。",
    account_invalid_game_path="请选择现有的游戏可执行文件。",
    account_server_language_ko="韩语",
    account_server_language_zh_cn="中文（简体）",
    account_server_language_zh_tw="中文（繁体）",
    account_server_language_ja="日语",
    account_duplicate="该电子邮箱已保存。",
    account_storage_error="无法更新安全账号存储。",
    autologin_account_required="请在高级设置中选择或添加自动登录账号。",
    autologin_starting="正在启动 Purple 自动登录…",
    autologin_status="自动登录：{status}",
    autologin_cancelled="自动登录已取消。",
    autologin_failed="自动登录失败：{detail}",
    recovery_starting="游戏已关闭，正在启动自动恢复…",
    recovery_completed="自动恢复已完成。",
    recovery_limit="近期游戏关闭次数过多，自动恢复已停止。",
    setup="设置",
    stop_to_change_setup="请先停止机器人再更改设置。",
    cannot_start="无法启动",
    memory_title="内存",
    memory_connected="已连接。\n{detail}",
    memory_failed=(
        "无法连接。\n{detail}\n\n"
        "请先加载已签名驱动，再重新启动监视器"
        "（批准 UAC）。LC.exe 应在运行中。"
    ),
    memory_failed_detail="监视器启动意外失败。",
    driver_title="驱动",
    driver_ok="{msg}\n\n如出现 UAC 请批准，然后使用“启动监视器并连接”。",
    driver_fail_prefix="{msg}",
    drivers_setup="设置驱动程序",
    drivers_setup_hint="启动机器人前，两个驱动程序都必须准备就绪。",
    interception_driver="Interception 输入",
    install_interception="安装输入驱动（管理员）…",
    setup_memory_reader="设置内存读取（管理员）…",
    check_again="重新检查",
    driver_ready="已就绪",
    driver_not_ready="未就绪",
    driver_restart_hint="安装输入驱动后请重新启动 Windows。",
    stop_open_setup_q="停止机器人并打开设置？",
    reset_title="重置",
    reset_confirm="将所有设置恢复默认？此操作无法撤销。",
    settings_reset_log="设置已恢复默认",
    wizard_done_log="设置向导已完成",
    diagnostics_copied="诊断信息已复制到剪贴板",
    memory_connected_session="内存已连接（机器人会话）",
    logs={
        "running": "{via} → 运行中",
        "auto_pause": "自动暂停（{code}）",
        "start_paused": "启动 → 已暂停（{code}）— 游戏获得焦点后继续",
        "start_running": "启动 → 运行中",
        "resume_wait": (
            "已请求继续 — 请点击游戏窗口"
            "（获得焦点后会自动继续）"
        ),
        "paused_hotkey": "已暂停 — 快捷键",
        "stop_stopped": "停止 → 已停止",
        "stop_stopped_reason": "停止 → 已停止（{reason}）",
        "worker_exited": "机器人工作线程已退出",
        "hotbar_reading": "正在从内存读取 24 格快捷栏…",
        "hotbar_done": "快捷栏扫描完成 · {roles}",
        "hotbar_done_none": "快捷栏扫描完成 · 没有映射角色",
        "hotbar_unmapped": "未映射的快捷栏图标：{names}",
        "hotbar_cancelled": "快捷栏扫描已取消。",
        "hotbar_failed": "快捷栏扫描失败：{error}",
        "hotbar_save_failed": "无法保存检测到的技能格：{error}",
        "loop_ready": (
            "循环就绪 · {character} · {game_language} · "
            "地图={map} · 拾取={loot} · 区域={farms}"
        ),
        "inventory_started": (
            "背包监听已启动 · {via} 种子 · "
            "hp={hp} 箭={arrows} 银箭={silver} 解毒={depoison} "
            "（后台实时扫描）"
        ),
        "inventory_scanning": (
            "正在后台扫描背包（{dll} 或放置 inv.json）。"
        ),
        "inventory_setup_failed": "背包监听设置失败：{error}",
        "inventory_ready": (
            "背包监听已就绪（dll） · "
            "hp={hp} 箭={arrows} 银箭={silver} 解毒={depoison}"
        ),
    },
    reason={
        "not_focused": "已暂停 — 游戏未处于前台。",
        "cursor_outside": "已暂停 — 光标离开了游戏窗口。",
        "minimized": "已暂停 — 游戏窗口已最小化。",
        "memory_down": "已暂停 — 内存监视器已断开。",
        "user_pause": "已暂停 — 快捷键。",
        "game_closed": "已停止 — 游戏窗口已关闭。",
        "ready_for_resume": (
            "就绪 — 请点击游戏窗口"
            "（游戏获得焦点后机器人会继续）。"
        ),
        "resume_hint": "请点击游戏窗口 — 获得焦点后机器人会自动继续。",
    },
    start_fail={
        "start_no_game": "无法启动 — 未找到游戏窗口。",
        "start_no_memory": (
            "无法启动 — 内存监视器未就绪。"
            "如提示 UAC 请批准后再次点击开始。"
        ),
        "start_no_setup": "无法启动 — 请先完成设置。",
        "start_no_farms": "请在猎场选项卡中至少选择一个猎场。",
        "start_no_patrol": "请在地图选项卡中至少添加一个巡逻点。",
        "map_missing": "无法启动 — 缺少地图数据。",
    },
    loot_labels={
        "all_items": {
            "title": "全部拾取",
            "desc": "拾取所有可触及的掉落（金币及其他物品）。",
        },
        "adena_only": {
            "title": "仅金币",
            "desc": "只拾取金币，忽略其他地面物品。",
        },
    },
    loot_weight_note="若背包负重超过 {pct}%，机器人会暂时只拾取金币。",
    char_blurbs={
        "mage": "对范围内目标施放魔法。",
        "elf": "以稳定节奏点击攻击。",
        "knight": "按住鼠标对目标进行近战。",
        "royal": "王族近战职业。",
    },
    char_titles={"mage": "法师", "elf": "精灵", "knight": "骑士", "royal": "王族"},
    hotkey_labels={
        "pause_resume": "暂停 / 继续",
        "stop": "停止机器人",
    },
    wizard_title="设置 — Manmabot v1",
    wizard_back="返回",
    wizard_continue="继续",
    wizard_finish="完成",
    wizard_step="第 {cur} / {total} 步",
    wizard_block_close="请完成设置向导后再使用 Manmabot v1。",
    wizard_welcome="欢迎",
    wizard_welcome_body=(
        "本助手按你选择的地图设置 Manmabot。\n\n"
        "我们将检查内存驱动、游戏窗口、角色、地图与猎场。\n\n"
        "需要：LC.exe 正在运行，并已加载已签名的内存驱动。"
    ),
    wizard_memory_hint=(
        "在本进程中读取玩家 HP/MP/位置。"
        "如需加载驱动请批准 UAC。LC.exe 应在运行中。"
        "偏移只改 analysis/offsets.json。"
    ),
    wizard_not_tested="未测试",
    wizard_starting_monitor="正在启动监视器…",
    monitor_closing="正在关闭内存监视器…",
    monitor_closed="已关闭内存监视器。",
    monitor_close_failed="无法关闭内存监视器：{detail}",
    bring_to_front="置于前台",
    wizard_loot_survival="拾取与生存",
    drink_hp_pct="HP药水触发（低于 %）",
    escape_hp_pct="HP低于时逃跑 %",
    wizard_farms_title="猎场",
    wizard_map_title="地图",
    wizard_map_body="选择机器人将使用的地图包。之后可在设置中更改。",
    wizard_dungeon_farms="此地图为地下城，不使用猎场区域。完成设置后请在猎场选项卡中放置巡逻点。",
    select_one_farm="请至少选择一个猎场。",
    wizard_hotkeys="快捷键",
    wizard_hotkeys_later="之后可在高级选项卡中更改。",
    wizard_review="确认",
    wizard_review_body=(
        "角色：{character}\n"
        "游戏语言：{game}\n"
        "地图：{map}\n"
        "拾取：{loot}\n"
        "猎场：{farms}\n"
        "快捷键：暂停 {pause} · 停止 {stop}\n"
        "{spells}\n\n"
        "安全：\n"
        "• 光标离开游戏或失去焦点会暂停机器人。\n"
        "• 继续为手动操作。\n"
        "• 暂停后停止，或使用停止快捷键。"
    ),
    game_not_found="未找到游戏窗口。请启动天堂后点击检测。",
    no_farms="没有可用猎场。",
    memory_continue_anyway=(
        "内存监视器未就绪。仍要继续吗？\n"
        "（连接成功前无法开始。）"
    ),
    game_continue_anyway=(
        "未找到游戏窗口。仍要继续吗？\n"
        "（天堂运行前无法开始。）"
    ),
)


_CATALOG: dict[str, UiStrings] = {
    LANG_EN: _EN,
    LANG_KO: _KO,
    LANG_ZH: _ZH,
}


def ui_strings(language: str | None = None) -> UiStrings:
    return _CATALOG[normalize_language(language)]


# Backward-compatible English defaults (imports / tests).
_S = _EN
HEADLINE_STOPPED = _S.headline_stopped
HEADLINE_RUNNING = _S.headline_running
HEADLINE_PAUSED = _S.headline_paused
REASON = dict(_S.reason)
START_FAIL = dict(_S.start_fail)
LOOT_LABELS = {k: dict(v) for k, v in _S.loot_labels.items()}
LOOT_WEIGHT_NOTE = _S.loot_weight_note
CHAR_BLURBS = dict(_S.char_blurbs)
HOTKEY_LABELS = dict(_S.hotkey_labels)


def as_legacy_maps(s: UiStrings) -> dict[str, Any]:
    """Optional helper for callers that expect the old module maps."""
    return {
        "REASON": dict(s.reason),
        "START_FAIL": dict(s.start_fail),
        "LOOT_LABELS": {k: dict(v) for k, v in s.loot_labels.items()},
        "CHAR_BLURBS": dict(s.char_blurbs),
        "HOTKEY_LABELS": dict(s.hotkey_labels),
    }
