"""Bot run states and worker thread that drives Manmabot."""
from __future__ import annotations

import queue
import os
import sys
import threading
import time
import traceback
from enum import Enum
from typing import Callable, Optional

from manmabot_v1.paths import (
    ensure_userdata,
    manmabot_root,
    overlay_farms_path,
    overlay_patrol_path,
)
from manmabot_v1.probes import (
    Lamp,
    bring_game_to_front,
    load_selected_farm_rects,
    pause_reason_from_game,
    probe_game,
    probe_memory,
)
from manmabot_v1.profile import Profile
from manmabot_v1.strings import ui_strings


class RunState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


LogFn = Callable[[str], None]
StateFn = Callable[[RunState, str], None]
HotbarFn = Callable[[dict, dict], None]


class BotController:
    """UI-facing controller: Start / Resume / Stop + auto-pause gates."""

    def __init__(
        self,
        *,
        on_log: Optional[LogFn] = None,
        on_state: Optional[StateFn] = None,
        on_hotbar: Optional[HotbarFn] = None,
    ) -> None:
        self._on_log = on_log or (lambda _m: None)
        self._on_state = on_state or (lambda _s, _r: None)
        self._on_hotbar = on_hotbar or (lambda _layout, _slots: None)
        self.state = RunState.STOPPED
        self.reason = ""
        self._stop_event = threading.Event()
        self._pause_gate = threading.Event()  # set => worker may act
        self._thread: Optional[threading.Thread] = None
        self._profile = Profile()
        self._lock = threading.Lock()
        # "auto" = focus/cursor/memory pause (auto-resume when ready).
        # "user" = hotkey pause (needs Resume / hotkey; Resume arms pending).
        self._pause_kind: Optional[str] = None
        self._resume_pending: bool = False
        self._preview_enabled = threading.Event()
        self._preview_q: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self._last_pause_preview_t: float = 0.0
        self._debug_lock = threading.Lock()
        self._debug_snapshot: dict = {}
        self._debug_watchers = 0
        self._preview_watchers = 0
        # Schedule Start keeps running while the console owns focus.
        self._unattended = False

    def _ui(self):
        return ui_strings(getattr(self._profile, "language", None))

    def _reason(self, code: str) -> str:
        return self._ui().reason[code]

    def _log_ui(self, key: str, **kwargs) -> None:
        text = self._ui().logs.get(key, key)
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
        self.log(text)

    def _via_label(self, via: str) -> str:
        ui = self._ui()
        mapping = {
            "Start": ui.btn_start,
            "Resume": ui.btn_resume,
            "Hotkey resume": ui.hotkey_labels.get("pause_resume", via),
        }
        return mapping.get(via, via)

    def log(self, msg: str) -> None:
        self._on_log(msg)
        try:
            from app.bot_log import get_logger

            get_logger("session").info("%s", msg)
        except Exception:
            pass

    def set_preview_enabled(self, on: bool) -> None:
        if on:
            self._preview_enabled.set()
        else:
            self._preview_enabled.clear()
            self._drain_preview_queue()

    def pop_preview_jpeg(self) -> bytes | None:
        try:
            return self._preview_q.get_nowait()
        except queue.Empty:
            return None

    def add_debug_watcher(self) -> None:
        with self._debug_lock:
            self._debug_watchers += 1

    def remove_debug_watcher(self) -> None:
        with self._debug_lock:
            self._debug_watchers = max(0, self._debug_watchers - 1)
            remaining = self._debug_watchers
        if remaining == 0:
            self.set_preview_enabled(False)

    def add_preview_watcher(self) -> None:
        with self._debug_lock:
            self._preview_watchers += 1
        self.set_preview_enabled(True)

    def remove_preview_watcher(self) -> None:
        with self._debug_lock:
            self._preview_watchers = max(0, self._preview_watchers - 1)
            remaining = self._preview_watchers
        if remaining == 0:
            self.set_preview_enabled(False)

    def preview_busy(self) -> bool:
        """True when the UI has not consumed the latest preview JPEG."""
        return not self._preview_q.empty()

    def debug_snapshot(self) -> dict:
        """Latest runtime snapshot for the debug GUI (same worker as Start)."""
        from manmabot_v1.debug_snapshot import build_runtime_snapshot

        with self._debug_lock:
            snap = self._debug_snapshot
        if snap:
            overview = dict(snap.get("overview") or {})
            overview["state"] = self.state.value
            overview["reason"] = self.reason
            overview["pause_kind"] = self._pause_kind or ""
            overview["worker_alive"] = self._thread is not None and self._thread.is_alive()
            return {**snap, "overview": overview}
        return build_runtime_snapshot(
            state=self.state.value,
            reason=self.reason,
            pause_kind=self._pause_kind,
            profile=self._profile,
            hotbar_layout=getattr(self._profile, "hotbar_layout", None),
            spell_slots=getattr(self._profile, "spell_slots", None),
            worker_alive=self._thread is not None and self._thread.is_alive(),
            arming=False,
        )

    def _publish_debug(
        self,
        *,
        world=None,
        blackboard=None,
        action=None,
        vision=None,
        loop=None,
        arming: bool = False,
    ) -> None:
        with self._debug_lock:
            if self._debug_watchers <= 0:
                return
        try:
            from manmabot_v1.debug_snapshot import build_runtime_snapshot

            snap = build_runtime_snapshot(
                state=self.state.value,
                reason=self.reason,
                pause_kind=self._pause_kind,
                profile=self._profile,
                world=world,
                blackboard=blackboard,
                action=action,
                vision=vision,
                hotbar_layout=getattr(self._profile, "hotbar_layout", None),
                spell_slots=getattr(self._profile, "spell_slots", None),
                loop=loop,
                worker_alive=self._thread is not None and self._thread.is_alive(),
                arming=arming,
            )
            with self._debug_lock:
                self._debug_snapshot = snap
        except Exception:
            pass

    def _drain_preview_queue(self) -> None:
        while True:
            try:
                self._preview_q.get_nowait()
            except queue.Empty:
                return

    def _push_preview_image(self, image) -> None:
        if not self._preview_enabled.is_set() or image is None:
            return
        # Do not encode while the UI still holds a frame — JPEG work sits on
        # the click loop and is the main source of preview/start hitching.
        if not self._preview_q.empty():
            return
        from app._02_vision.preview import encode_preview_jpeg

        data = encode_preview_jpeg(image, quality=55, max_width=720)
        if not data:
            return
        try:
            self._preview_q.put_nowait(data)
        except queue.Full:
            pass

    def _push_paused_preview(
        self, last, message: str, *, throttle_s: float = 0.2
    ) -> None:
        if not self._preview_enabled.is_set():
            return
        now = time.time()
        if now - self._last_pause_preview_t < throttle_s:
            return
        self._last_pause_preview_t = now
        from app._02_vision.preview import paused_preview

        self._push_preview_image(paused_preview(last, message))

    def _set_state(self, state: RunState, reason: str = "") -> None:
        self.state = state
        self.reason = reason
        self._on_state(state, reason)

    def _commit_hotbar_scan(
        self,
        profile: Profile,
        world,
        detected,
        *,
        persist: bool,
        log_result: bool,
    ) -> None:
        """Bind F-key slots from a memory scan and push them to the operator UI."""
        from app._05_action.spell_box import configure_spell_box
        from manmabot_v1.hotbar.inspect import merge_detected_spell_slots
        from manmabot_v1.hp_actions import apply_recovery_to_spell_slots
        from manmabot_v1.profile import save_profile

        previous_slots = dict(getattr(profile, "spell_slots", {}) or {})
        profile.spell_slots = apply_recovery_to_spell_slots(
            merge_detected_spell_slots(detected.spell_slots, previous_slots),
            getattr(profile, "hp_actions", None),
        )
        profile.hotbar_layout = detected.to_profile_dict()
        if world is not None:
            world.hotbar_layout = profile.hotbar_layout
        try:
            from app._03_world.hotbar_listen_reader import shared_hotbar

            world.last_hotbar = shared_hotbar().snapshot()
        except Exception:
            pass
        if persist:
            try:
                save_profile(profile)
            except Exception as exc:
                self._log_ui("hotbar_save_failed", error=exc)
        configure_spell_box(profile.spell_slots)
        executor = getattr(self, "_action_executor", None)
        if executor is not None:
            executor.hotbar_layout = profile.hotbar_layout
        try:
            self._on_hotbar(profile.hotbar_layout, profile.spell_slots)
        except Exception:
            pass
        if not log_result:
            return
        ui = self._ui()
        from manmabot_v1.localized_names import memory_name_for_ui

        lang = getattr(profile, "language", None)
        active = [
            f"{ui.spell_titles.get(sid, sid)}@box{spec.get('box')}/{spec.get('key')}"
            for sid, spec in profile.spell_slots.items()
            if spec.get("enabled") and int(spec.get("box") or 0) in (1, 2, 3)
        ]
        if active:
            self._log_ui("hotbar_done", roles=", ".join(active))
        else:
            self._log_ui("hotbar_done_none")
        unbound = list(getattr(detected, "unbound_icons", None) or [])
        if unbound:
            shown: list[str] = []
            for raw in unbound[:12]:
                if ":" in raw:
                    prefix, name = raw.split(":", 1)
                    shown.append(f"{prefix}:{memory_name_for_ui(name, lang)}")
                else:
                    shown.append(memory_name_for_ui(raw, lang))
            extra = "…" if len(unbound) > 12 else ""
            self._log_ui("hotbar_unmapped", names=", ".join(shown) + extra)

    def start_gates_ok(self, profile: Profile) -> Optional[str]:
        """Return START_FAIL key if Start cannot proceed.

        Memory is not a UI-button gate — Start auto-connects the monitor.
        """
        game = probe_game()
        if game.lamp == Lamp.RED:
            return "start_no_game"
        from manmabot_v1.probes import (
            list_patrol_entries,
            load_map_pack_safe,
            map_style_is_dungeon,
        )

        pack = load_map_pack_safe(profile.active_map)
        if pack is None:
            return "map_missing"
        if map_style_is_dungeon(profile.active_map, getattr(profile, "map_style", None)):
            if not list_patrol_entries(profile.active_map):
                return "start_no_patrol"
        elif not profile.selected_farms:
            return "start_no_farms"
        mem = probe_memory()
        if mem.lamp == Lamp.RED:
            return "start_no_memory"
        return None

    def _try_enter_running_locked(self, *, via: str) -> bool:
        """If game is ready, enter Running. Caller holds ``_lock``.

        Does not re-open the memory pipe while the worker is alive — the worker
        already holds the only client connection; a second open looks "down"
        and permanently blocks resume.
        """
        game = probe_game()
        # Resume only needs focus (not cursor-inside): after Alt-Tab / click,
        # the cursor may still sit over our control panel.
        pr = pause_reason_from_game(game, require_cursor_inside=False)
        if pr:
            return False
        worker_alive = self._thread is not None and self._thread.is_alive()
        if not worker_alive:
            mem = probe_memory()
            if mem.lamp == Lamp.RED:
                return False
        self._pause_gate.set()
        self._pause_kind = None
        self._resume_pending = False
        self._set_state(RunState.RUNNING, "")
        self._log_ui("running", via=self._via_label(via))
        return True

    def _enter_auto_pause_locked(self, code: str) -> None:
        self._pause_gate.clear()
        self._pause_kind = "auto"
        ui = self._ui()
        hint = f"{ui.reason[code]} {ui.reason['resume_hint']}"
        self._set_state(RunState.PAUSED, hint)
        self._log_ui("auto_pause", code=ui.reason.get(code, code))

    def start(self, profile: Profile, unattended: bool = False) -> Optional[str]:
        """Arm the bot. Returns error key or None.

        ``unattended=True`` (schedule Start): run even if the console stole
        game focus, and do not auto-pause on later focus loss.
        """
        with self._lock:
            if self.state != RunState.STOPPED:
                return None
            err = self.start_gates_ok(profile)
            if err:
                return err
            self._profile = profile
            self._unattended = bool(unattended)
            self._stop_event.clear()
            self._resume_pending = False
            hwnd = 0
            game = probe_game()
            if game.hwnd:
                hwnd = int(game.hwnd)

        # One raise only — never sleep on the UI thread. Auto-resume covers
        # the case where Start steals focus for a moment.
        if hwnd:
            bring_game_to_front(hwnd)

        with self._lock:
            if self.state != RunState.STOPPED:
                return None
            game = probe_game()
            pr = None
            if not self._unattended:
                pr = pause_reason_from_game(game, require_cursor_inside=False)
            if pr:
                self._pause_gate.clear()
                self._pause_kind = "auto"
                ui = self._ui()
                hint = f"{ui.reason[pr]} {ui.reason['resume_hint']}"
                self._set_state(RunState.PAUSED, hint)
                self._log_ui(
                    "start_paused",
                    code=self._ui().reason.get(pr, pr),
                )
            else:
                self._pause_gate.set()
                self._pause_kind = None
                self._set_state(RunState.RUNNING, "")
                self._log_ui("start_running")
            self._thread = threading.Thread(
                target=self._worker, name="manmabot-v1-worker", daemon=True
            )
            self._thread.start()
            return None

    def resume(self) -> None:
        """Request resume. UI click steals focus, so we arm pending + activate game."""
        with self._lock:
            if self.state != RunState.PAUSED:
                return
            game = probe_game()
            if game.hwnd:
                bring_game_to_front(game.hwnd)
            if self._try_enter_running_locked(via="Resume"):
                return
            # Clicking Resume focused our app; wait until game is ready again.
            self._resume_pending = True
            self._pause_kind = "auto"
            game = probe_game()
            pr = pause_reason_from_game(game, require_cursor_inside=False) or "not_focused"
            ui = self._ui()
            hint = f"{ui.reason[pr]} {ui.reason['resume_hint']}"
            self._set_state(RunState.PAUSED, hint)
            self._log_ui("resume_wait")

    def pause_user(self) -> None:
        with self._lock:
            if self.state != RunState.RUNNING:
                return
            self._pause_gate.clear()
            self._pause_kind = "user"
            self._resume_pending = False
            self._set_state(RunState.PAUSED, self._reason("user_pause"))
            self._log_ui("paused_hotkey")

    def toggle_pause_hotkey(self) -> None:
        if self.state == RunState.RUNNING:
            self.pause_user()
        elif self.state == RunState.PAUSED:
            # Hotkey while game is focused: try immediate resume.
            with self._lock:
                if self._try_enter_running_locked(via="Hotkey resume"):
                    return
            self.resume()

    def stop(self, *, reason: str = "") -> bool:
        """Request shutdown and return whether the worker has fully exited."""
        with self._lock:
            if self.state == RunState.STOPPED:
                t = self._thread
                return t is None or not t.is_alive()
            self._stop_event.set()
            self._pause_gate.set()  # unblock waiters
            self._pause_kind = None
            self._resume_pending = False
            self._unattended = False
            self._set_state(RunState.STOPPED, reason)
            if reason:
                self._log_ui("stop_stopped_reason", reason=reason)
            else:
                self._log_ui("stop_stopped")
        # Never join here: Stop is clicked from the Tk thread and a 5s join
        # freezes Start/Stop/debug. Arming and close() wait in the background.
        return self.worker_stopped()

    def wait_stopped(self, timeout: float = 5.0) -> bool:
        """Block until the worker exits. Use only off the UI thread."""
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        return self.worker_stopped()

    def worker_stopped(self) -> bool:
        """Whether no previous worker can still own input or memory resources."""
        t = self._thread
        if t is not None and not t.is_alive():
            self._thread = None
            try:
                from app._04_decision.dungeon import set_dungeon_mode_override

                set_dungeon_mode_override(None)
            except Exception:
                pass
            return True
        return t is None

    def auto_pause_tick(self) -> Optional[str]:
        """Supervise an armed worker and return a machine-readable event."""
        if self.state not in (RunState.RUNNING, RunState.PAUSED):
            return None

        game = probe_game()
        # Closed / missing game window: stop fully (do not keep clicking).
        if game.lamp == Lamp.RED:
            self.stop(reason=self._reason("game_closed"))
            return "game_closed"

        if self.state == RunState.RUNNING:
            # Pause only when the game loses focus / is minimized.
            # Do NOT pause on cursor_outside: Start is clicked in our UI (often
            # always-on-top), so the cursor stays over Manmabot while the game
            # is focused — that used to thrash Auto-pause ↔ Auto-resume and
            # leave the bot stuck looking "Paused".
            # Schedule Start keeps the console in front; do not pause for that.
            if self._unattended:
                return None
            pr = pause_reason_from_game(game, require_cursor_inside=False)
            if pr:
                with self._lock:
                    if self.state != RunState.RUNNING:
                        return
                    self._enter_auto_pause_locked(pr)
            return None

        # Paused: auto-resume after Start/focus loss, or after Resume was clicked.
        if self._pause_kind != "auto" and not self._resume_pending:
            return None
        with self._lock:
            if self.state != RunState.PAUSED:
                return None
            if self._pause_kind != "auto" and not self._resume_pending:
                return None
            self._try_enter_running_locked(via="Auto-resume")
        return None

    def _worker(self) -> None:
        ensure_userdata()
        # Windowed / pythonw launches leave stdout/stderr as None; torch hub
        # and other libs crash on sys.stdout.write during model download.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        try:
            self._run_bot_loop()
        except Exception:
            self.log("Bot worker crashed:\n" + traceback.format_exc())
        finally:
            with self._lock:
                if self.state != RunState.STOPPED:
                    self._set_state(RunState.STOPPED, "")
            self._log_ui("worker_exited")
            try:
                from app._05_action.mouse import release_capture

                release_capture()
            except Exception:
                pass
            try:
                from manmabot_v1.input_release import restore_desktop_input

                restore_desktop_input()
            except Exception:
                pass
            try:
                from app.bot_log import reset as reset_bot_log

                reset_bot_log()
            except Exception:
                pass

    def _run_bot_loop(self) -> None:
        root = manmabot_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from tool.utils import load_config
        from app.bot_log import configure as configure_bot_log, get_logger

        from manmabot_v1.perception_capture import open_perception_capture
        from app._02_vision.vision_config import (
            apply_region_model_paths,
            resolve_active_vision_region,
            resolve_classifier_edition,
            sync_vision_region,
            vision_system_kwargs,
        )
        from app._02_vision.preview import draw_vision_preview, paused_preview
        from app._02_vision.vision_system import VisionSystem
        from app._02_vision.weight_hud import configure_weight_hud
        from app._03_world import ActionType, CharacterType, GameState, memory_weight_ready
        from app._03_world.battle_area import configure_battle_area
        from app._03_world.constants import (
            configure_classification_thresholds,
            configure_species_filter,
            configure_species_level_overrides,
        )
        from app._03_world.memory_client import open_monitor_from_config
        from app._03_world.memory_sync import apply_snapshot, world_origin_from_snapshot
        from app._04_decision.configure import (
            apply_action_executor_options,
            configure_action,
            configure_decision,
        )
        from app._04_decision.manager import DecisionManager
        from app._04_decision.nav_config import configure_navigation, get_terrain_map, set_loot_mode
        from app._04_decision.talking_scroll import (
            SCRATCH_VISION_REGION,
            apply_mother_tree_mainland_stay,
            apply_talking_scroll_arrival,
        )
        from app._05_action.controller import ActionExecutor
        from app._05_action.cursor_verify import is_cursor_paralyzed

        profile = self._profile
        config = load_config()
        log_cfg = (config.get("logging") or {}) if isinstance(config, dict) else {}
        log_level = str(log_cfg.get("level") or "INFO")
        session_log = configure_bot_log(
            log_dir=root / "logs",
            console=False,
            level=log_level,
            # Panel only — do not use self.log (would re-enter session logger).
            ui_sink=self._on_log,
        )
        self.log(f"Loading Manmabot from {root}")
        self.log(f"Session log {session_log}")
        get_logger("session").info(
            "character=%s loot=%s game_lang=%s map=%s farms=%s file=%s",
            profile.character,
            profile.loot_mode,
            profile.game_language,
            profile.active_map,
            profile.selected_farms,
            session_log,
        )
        nav = dict(config.get("navigation") or {})
        nav["active_map"] = profile.active_map
        from manmabot_v1.probes import map_style_is_dungeon
        from app._04_decision.dungeon import set_dungeon_mode_override

        dungeon = map_style_is_dungeon(
            profile.active_map, getattr(profile, "map_style", None)
        )
        set_dungeon_mode_override(dungeon)
        if dungeon:
            nav.pop("farm_areas", None)
            nav.pop("farm_areas_file", None)
        else:
            overlay_farms = overlay_farms_path(profile.active_map)
            if overlay_farms.is_file():
                nav["farm_areas_file"] = str(overlay_farms)
            farms = load_selected_farm_rects(
                profile.selected_farms, map_id=profile.active_map
            )
            if farms:
                nav["farm_areas"] = farms
                nav.pop("farm_areas_file", None)
        config["navigation"] = nav

        configure_species_level_overrides(profile.species_levels)
        configure_species_filter(
            getattr(profile, "species_filter_mode", "blacklist"),
            profile.species_blacklist,
            getattr(profile, "species_whitelist", []),
        )

        from manmabot_v1.hotbar.inspect import HotbarInspectError, inspect_hotbars

        # Survival overrides into decision block
        decision_cfg = dict(config.get("decision") or {})
        hp = dict(decision_cfg.get("hp") or {})
        mp = dict(decision_cfg.get("mp") or {})
        farm = dict(decision_cfg.get("farm") or {})
        spells_cfg = dict(decision_cfg.get("spells") or {})
        hp["low_ratio"] = float(profile.hp_potion_ratio)
        hp["critical_ratio"] = float(profile.hp_escape_ratio)
        hp["recover_enabled"] = bool(getattr(profile, "hp_recover_enabled", True))
        hp["use_potion"] = bool(getattr(profile, "use_hp_potion", True))
        hp["use_heal"] = bool(getattr(profile, "use_heal", True))
        from manmabot_v1.hp_actions import to_engine_actions

        hp["actions"] = to_engine_actions(getattr(profile, "hp_actions", None))
        mp["low_ratio"] = float(profile.mp_escape_ratio)
        mp["escape_enabled"] = False
        mp["potion_ratio"] = float(getattr(profile, "mp_potion_ratio", 0.30))
        mp["recover_enabled"] = bool(getattr(profile, "mp_recover_enabled", False))
        mp["use_potion"] = bool(getattr(profile, "use_mp_potion", False))
        mp["spell_reserve_ratio"] = float(profile.spell_reserve_ratio)
        farm["duration_limit_s"] = float(profile.farm_rotate_s)
        from manmabot_v1.farm_schedule import stay_seconds_for

        stay_map = getattr(profile, "farm_stays_s", None) or {}
        farm["duration_limits_s"] = [
            stay_seconds_for(
                str(area.get("name") or ""),
                stay_map,
                profile.farm_rotate_s,
            )
            for area in (nav.get("farm_areas") or [])
            if isinstance(area, dict)
        ]
        farm["loot_adena_weight_ratio"] = float(profile.loot_adena_weight_ratio)
        farm["area_empty"] = bool(getattr(profile, "area_empty", False))
        farm["area_empty_seconds"] = int(getattr(profile, "area_empty_seconds", 60))
        farm["area_low_yield"] = bool(getattr(profile, "area_low_yield", False))
        farm["area_low_yield_adena"] = int(getattr(profile, "area_low_yield_adena", 1000))
        farm["area_low_yield_seconds"] = int(getattr(profile, "area_low_yield_seconds", 180))
        farm["area_players"] = bool(getattr(profile, "area_players", False))
        farm["area_player_count"] = int(getattr(profile, "area_player_count", 3))
        returning = dict(decision_cfg.get("return") or {})
        returning["hp_enabled"] = bool(getattr(profile, "return_hp_enabled", True))
        returning["hp_ratio"] = float(getattr(profile, "return_hp_ratio", 0.30))
        returning["mp_enabled"] = bool(getattr(profile, "return_mp_enabled", True))
        returning["mp_ratio"] = float(getattr(profile, "return_mp_ratio", 0.15))
        returning["idle_enabled"] = bool(getattr(profile, "return_idle_enabled", False))
        returning["idle_seconds"] = float(getattr(profile, "return_idle_seconds", 60.0))
        returning["hunt_map"] = str(profile.active_map or "talking_island")
        decision_cfg["return"] = returning
        teleport_cfg = dict(decision_cfg.get("teleport") or {})
        teleport_cfg["enabled"] = bool(getattr(profile, "random_teleport_enabled", False))
        teleport_cfg["on_player"] = bool(getattr(profile, "teleport_on_player", False))
        teleport_cfg["when_surrounded"] = bool(
            getattr(profile, "teleport_when_surrounded", False)
        )
        teleport_cfg["surround_count"] = max(
            2, int(getattr(profile, "teleport_surround_count", 4) or 4)
        )
        decision_cfg["teleport"] = teleport_cfg
        death_cfg = dict(decision_cfg.get("death") or {})
        death_cfg["resurrect"] = bool(getattr(profile, "resurrect_if_dead", True))
        decision_cfg["death"] = death_cfg
        combat_cfg = dict(decision_cfg.get("combat") or {})
        combat_cfg["attack_jitter"] = bool(getattr(profile, "attack_jitter", False))
        combat_cfg["attack_jitter_ms"] = max(10, min(50, int(getattr(profile, "attack_jitter_ms", 35))))
        combat_cfg["target_delay"] = bool(getattr(profile, "target_delay", False))
        combat_cfg["target_delay_min_ms"] = max(10, min(50, int(getattr(profile, "target_delay_min_ms", 20))))
        combat_cfg["target_delay_max_ms"] = max(10, min(50, int(getattr(profile, "target_delay_max_ms", 50))))
        combat_cfg["abandon_same"] = bool(getattr(profile, "abandon_same", False))
        combat_cfg["abandon_seconds"] = int(getattr(profile, "abandon_seconds", 20))
        combat_cfg["antidote_auto"] = bool(getattr(profile, "antidote_auto", False))
        decision_cfg["combat"] = combat_cfg
        shop = dict(decision_cfg.get("shop") or {})
        shop["arrow_qty"] = int(profile.arrow_buy_qty)
        shop["silver_arrow_qty"] = int(getattr(profile, "silver_arrow_buy_qty", 200))
        shop["hp_potion_qty"] = int(getattr(profile, "hp_potion_buy_qty", 100))
        shop["depoison_qty"] = int(getattr(profile, "depoison_buy_qty", 1))
        shop["buy_normal_arrows"] = bool(getattr(profile, "buy_normal_arrows", True))
        shop["buy_silver_arrows"] = bool(getattr(profile, "buy_silver_arrows", False))
        if shop["buy_normal_arrows"] and shop["buy_silver_arrows"]:
            shop["buy_silver_arrows"] = False
        shop["restock_potions"] = bool(getattr(profile, "restock_potions", True))
        shop["buy_depoison"] = bool(getattr(profile, "buy_depoison", False))
        shop_locale = ""
        try:
            from manmabot_v1.accounts import AccountStore

            account = AccountStore().get(profile.selected_account_id or "")
            if account is not None and getattr(account, "locale", None):
                shop_locale = str(account.locale).strip().lower()
        except Exception:
            shop_locale = ""
        if not shop_locale:
            shop_locale = str(getattr(profile, "shop_locale", "") or "").strip().lower()
        if not shop_locale:
            shop_locale = str(profile.game_language or "ko")
        shop["shop_locale"] = "zh" if shop_locale.startswith("zh") else "ko"
        shop["hp_potion_npc"] = str(getattr(profile, "hp_potion_npc", "") or "")
        shop["return_potion_enabled"] = bool(
            getattr(profile, "return_potion_enabled", True)
        )
        shop["return_potion_count"] = int(getattr(profile, "return_potion_count", 20))
        shop["return_arrow_enabled"] = bool(
            getattr(profile, "return_arrow_enabled", True)
        )
        shop["return_arrow_count"] = int(getattr(profile, "return_arrow_count", 300))
        shop["return_depoison_enabled"] = bool(
            getattr(profile, "return_depoison_enabled", False)
        )
        shop["return_depoison_count"] = int(
            getattr(profile, "return_depoison_count", 1)
        )
        shop["return_weight_enabled"] = bool(
            getattr(profile, "return_weight_enabled", True)
        )
        try:
            weight_pct = max(
                0, min(100, int(getattr(profile, "return_weight_above", 85)))
            )
        except (TypeError, ValueError):
            weight_pct = 85
        shop["sell_weight_ratio"] = float(weight_pct) / 100.0
        sell_mode = str(
            getattr(profile, "sell_mode", "sell_except_keep") or "sell_except_keep"
        ).strip().lower()
        shop["sell_mode"] = (
            "sell_only_garbage"
            if sell_mode in ("sell_only_garbage", "only_garbage", "garbage")
            else "sell_except_keep"
        )
        shop["potion_suppress_s"] = 600.0
        spells_cfg["heal_until_hp_ratio"] = float(profile.heal_until_hp_ratio)
        decision_cfg["hp"] = hp
        decision_cfg["mp"] = mp
        decision_cfg["farm"] = farm
        decision_cfg["shop"] = shop
        decision_cfg["spells"] = spells_cfg
        decision_cfg["game_language"] = profile.game_language
        config["decision"] = decision_cfg

        configure_battle_area(config)
        configure_classification_thresholds(config)
        configure_decision(config)
        configure_action(config)
        world_origin = configure_navigation(config)
        set_loot_mode(profile.loot_mode)
        from app._04_decision.ground_loot import configure_ground_loot

        configure_ground_loot(profile.item_pickup_mode, profile.item_pickup_names)

        from app._04_decision.patrol import configure_patrol_waypoints

        overlay_patrol = overlay_patrol_path(profile.active_map)
        if overlay_patrol.is_file():
            configure_patrol_waypoints(
                path=overlay_patrol, terrain=get_terrain_map()
            )

        character = CharacterType(profile.character)
        capture = open_perception_capture(config)
        vision_kwargs = vision_system_kwargs(config)
        vision_region = resolve_active_vision_region(config)
        apply_region_model_paths(vision_kwargs, config, region=vision_region)
        clf_edition = resolve_classifier_edition(config)
        if clf_edition:
            vision_kwargs["classifier_edition"] = clf_edition
        vision = VisionSystem(**vision_kwargs)
        if vision_region:
            vision.set_region(vision_region, config)
        weight_hud = configure_weight_hud(config)
        world = GameState(character_type=character)
        world.hotbar_layout = getattr(profile, "hotbar_layout", None) or {}
        decision = DecisionManager()
        decision.blackboard.world_origin = world_origin

        memory_enabled = bool((config.get("memory") or {}).get("enabled", False))
        memory_reconnect_interval = float(
            ((config.get("memory") or {}).get("reconnect_interval_s", 2.5))
        )
        monitor = open_monitor_from_config(config, quiet=True)
        last_memory_reconnect = time.time()
        memory_cfg = config.get("memory") or {}
        from app._03_world.memory_entities import decision_rows, resolve_entity_source

        entity_source = resolve_entity_source(memory_cfg.get("entity_source", "hybrid"))
        entity_sweep = None
        want_sweep = bool(memory_cfg.get("entity_shadow", False)) or entity_source == "hybrid"
        if want_sweep:
            from app._03_world.memory_entities import LiveEntitySweep

            try:
                entity_sweep = LiveEntitySweep(
                    log_interval_s=float(memory_cfg.get("entity_log_interval_s", 5.0)),
                    level_fallback=bool(memory_cfg.get("entity_level_fallback", True)),
                )
            except FileNotFoundError as exc:
                self.log(str(exc))
                entity_source = "vision"
            else:
                if entity_source == "hybrid":
                    self.log(
                        "Entity clicks use memory names, species, and world cells. "
                        "Image recognition still runs. Set memory.entity_source "
                        "to vision to restore image-only clicks."
                    )
                else:
                    self.log(
                        "Entity sweep live via print_state.dll "
                        "(this process only, not injected; vision still targets)"
                    )
        entity_fallback_logged = False
        if monitor is not None:
            self.log(
                "Player memory is read in this process "
                "(realtime_monitor.dll, offsets.json). No separate console."
            )
        else:
            self.log("Memory monitor unavailable at worker start")

        inventory_sweep = None
        snap0 = None
        try:
            from app._03_world.inventory_listen_reader import (
                LiveInventorySweep,
                default_dll_path,
            )

            inventory_sweep = LiveInventorySweep(
                interval_s=float(memory_cfg.get("inventory_interval_s", 20.0)),
            )
            snap0 = inventory_sweep.poll(force=True)
            if snap0 is not None:
                from app._03_world.memory_inventory import (
                    apply_inventory_snapshot,
                    refresh_shop_needs_from_inventory,
                )

                apply_inventory_snapshot(world, snap0)
                refresh_shop_needs_from_inventory(world, decision.blackboard)
                inv = world.player.inventory
                via = (
                    "inv.json"
                    if snap0.get("source") == "inv.json"
                    else ("dll" if inventory_sweep.reader.dll_loaded else "inv.json")
                )
                self._log_ui(
                    "inventory_started",
                    via=via,
                    hp=inv.hp_potion,
                    arrows=inv.arrows,
                    silver=inv.silver_arrows,
                    depoison=inv.depoison,
                )
            else:
                dll = default_dll_path()
                self._log_ui("inventory_scanning", dll=dll.name)
        except Exception as exc:
            self._log_ui("inventory_setup_failed", error=exc)
            inventory_sweep = None

        executor = ActionExecutor(
            enabled=True, character=character, humanize=profile.humanize
        )
        apply_action_executor_options(executor)
        executor._perception_capture = capture
        executor.hotbar_layout = getattr(profile, "hotbar_layout", None) or {}
        world.hotbar_layout = executor.hotbar_layout
        self._action_executor = executor
        try:
            from app._05_action.mouse import prepare_capture

            prepare_capture()
        except Exception as exc:
            self.log(f"Input capture failed: {exc}")

        self._log_ui("hotbar_reading")
        self._publish_debug(loop={"note": "hotbar_scan"})

        def _abort_hotbar(reason: str) -> None:
            self.log(reason)
            self._set_state(RunState.STOPPED, reason)
            try:
                executor.drop_mouse()
            except Exception:
                pass
            if monitor is not None:
                try:
                    monitor.close()
                except Exception:
                    pass
            try:
                close = getattr(capture, "close", None) or getattr(capture, "stop", None)
                if callable(close):
                    close()
            except Exception:
                pass

        if self._stop_event.is_set():
            _abort_hotbar(self._ui().logs["hotbar_cancelled"])
            return
        try:
            detected = inspect_hotbars()
        except HotbarInspectError as exc:
            _abort_hotbar(self._ui().logs["hotbar_failed"].format(error=exc))
            return
        except Exception as exc:
            _abort_hotbar(self._ui().logs["hotbar_failed"].format(error=exc))
            return
        self._commit_hotbar_scan(
            profile, world, detected, persist=True, log_result=True
        )

        from manmabot_v1.localized_names import (
            language_display_name,
            map_display_name,
            route_point_display_name,
        )

        ui = self._ui()
        loot_spec = ui.loot_labels.get(str(profile.loot_mode), {})
        loot_label = (
            loot_spec.get("title") if isinstance(loot_spec, dict) else None
        ) or str(profile.loot_mode)
        farms = ", ".join(
            route_point_display_name(name, profile.language)
            for name in (profile.selected_farms or [])
        ) or "—"
        self._log_ui(
            "loop_ready",
            character=ui.char_titles.get(character.value, character.value),
            game_language=language_display_name(
                profile.game_language, profile.language
            ),
            map=map_display_name(profile.active_map, profile.language),
            loot=loot_label,
            farms=farms,
        )

        last_preview = None
        last_action = None
        last_vision = None
        last_inv_snap = snap0 if inventory_sweep is not None else None
        inv_live_logged = bool(
            last_inv_snap and last_inv_snap.get("source") != "inv.json"
        )
        last_tick_t = time.perf_counter()
        last_publish_t = 0.0
        last_preview_t = 0.0
        last_hotbar_t = 0.0
        last_hotbar_ui_t = time.perf_counter()
        from manmabot_v1.hotbar.inspect import next_hotbar_refresh_s

        hotbar_ui_interval = next_hotbar_refresh_s()
        last_fps = 0.0
        last_tick_ms = 0.0
        mouse_dropped = False
        paralyzed_dropped = False
        minimized_dropped = False
        # After autologin, the first ticks often have no live world cell yet.
        # Clicks then miss (shop NPC / combat cursor). Wait briefly for origin.
        session_origin_ready = False
        session_ready_deadline = time.perf_counter() + 2.5
        capture_rebound = False

        def publish(note: str, *, force: bool = False) -> None:
            nonlocal last_publish_t
            now = time.perf_counter()
            if not force and now - last_publish_t < 0.1:
                return
            last_publish_t = now
            self._publish_debug(
                world=world,
                blackboard=decision.blackboard,
                action=last_action,
                vision=last_vision,
                loop={
                    "note": note,
                    "fps": last_fps,
                    "tick_ms": last_tick_ms,
                    "frame_id": getattr(world, "frame_id", 0),
                    "updated_at": time.time(),
                },
            )

        publish("loop_ready", force=True)
        while not self._stop_event.is_set():
            while not self._stop_event.is_set() and not self._pause_gate.is_set():
                # Lift once on pause so a leftover click does not stick, then
                # leave the mouse alone so the operator can drag.
                if not mouse_dropped:
                    executor.drop_mouse()
                    mouse_dropped = True
                # Keep player nav origin live for Navigation-show while paused.
                if monitor is None and memory_enabled:
                    now = time.time()
                    if now - last_memory_reconnect >= memory_reconnect_interval:
                        last_memory_reconnect = now
                        monitor = open_monitor_from_config(
                            config, quiet=True, connect_retries=1
                        )
                elif monitor is not None:
                    try:
                        snap = monitor.snapshot(fresh=False)
                        apply_snapshot(world, decision.blackboard, snap)
                    except Exception:
                        try:
                            monitor.close()
                        except Exception:
                            pass
                        monitor = None
                        last_memory_reconnect = 0.0
                if entity_sweep is not None:
                    try:
                        print_snap, _rows, _shadow = entity_sweep.poll(
                            [], content=capture.content_rect
                        )
                        if print_snap is not None:
                            world.last_print_state = print_snap
                            from app._03_world.memory_sync import (
                                apply_print_state_vitals,
                            )

                            apply_print_state_vitals(world, print_snap)
                            print_origin = world_origin_from_snapshot(print_snap)
                            if print_origin is not None:
                                decision.blackboard.world_origin = print_origin
                    except Exception:
                        pass
                self._push_paused_preview(last_preview, "Bot paused")
                publish("paused")
                time.sleep(0.05)

            mouse_dropped = False
            if self._stop_event.is_set():
                break

            if capture.is_minimized:
                if not minimized_dropped:
                    executor.drop_mouse()
                    minimized_dropped = True
                self._push_paused_preview(
                    last_preview, "Game window minimized — bot paused"
                )
                publish("minimized")
                time.sleep(0.05)
                continue
            minimized_dropped = False

            frame = capture.get_frame()
            if frame is None:
                self._push_paused_preview(last_preview, "Waiting for game frame")
                publish("no_frame")
                time.sleep(0.01)
                continue

            sync_vision_region(
                vision,
                config,
                farm_index=decision.blackboard.farm_area_index,
                region_override=str(
                    decision.blackboard.scratch.get(SCRATCH_VISION_REGION) or ""
                ),
            )
            vision_output = vision.process(frame)
            last_vision = vision_output
            memory_rows: list = []
            sweep_ok = False
            if entity_sweep is not None:
                try:
                    snap, memory_rows, shadow_line = entity_sweep.poll(
                        vision_output, content=capture.content_rect
                    )
                    world.last_print_state = snap
                    world.last_print_entities = memory_rows
                    sweep_ok = (
                        snap is not None
                        and float(snap.get("client_w") or 0) >= 1
                        and float(snap.get("client_h") or 0) >= 1
                    )
                    if shadow_line:
                        self.log(shadow_line)
                except Exception as exc:
                    self.log(f"Entity sweep failed: {exc}")
                    try:
                        entity_sweep.close()
                    except Exception:
                        pass
                    entity_sweep = None
                    world.last_print_state = None
                    world.last_print_entities = []
            chosen, used_source = decision_rows(
                entity_source, vision_output, memory_rows, sweep_ok=sweep_ok
            )
            world.update_from_vision(chosen)
            if entity_source == "hybrid" and used_source != "hybrid" and not entity_fallback_logged:
                self.log(
                    "Memory entity sweep unavailable; clicks stayed on image recognition"
                )
                entity_fallback_logged = True

            if monitor is None and memory_enabled:
                now = time.time()
                if now - last_memory_reconnect >= memory_reconnect_interval:
                    last_memory_reconnect = now
                    monitor = open_monitor_from_config(
                        config, quiet=True, connect_retries=1
                    )
                    if monitor is not None:
                        self.log("Memory reconnected")
            elif monitor is not None:
                try:
                    snap = monitor.snapshot(fresh=False)
                    if apply_snapshot(world, decision.blackboard, snap):
                        if world_origin_from_snapshot(snap) is not None:
                            session_origin_ready = True
                except Exception as exc:
                    self.log(f"Memory snapshot failed: {exc}")
                    try:
                        monitor.close()
                    except Exception:
                        pass
                    monitor = None
                    last_memory_reconnect = 0.0

            # print_state player.x/y is the same sweep as ground items. Stamp
            # nav origin after the monitor so loot/travel share that cell.
            if sweep_ok:
                from app._03_world.memory_sync import apply_print_state_vitals

                print_snap = getattr(world, "last_print_state", None) or {}
                apply_print_state_vitals(world, print_snap)
                print_origin = world_origin_from_snapshot(print_snap)
                if print_origin is not None:
                    decision.blackboard.world_origin = print_origin
                    session_origin_ready = True
                    if not capture_rebound:
                        capture_rebound = True
                        try:
                            from app._05_action.mouse import prepare_capture

                            prepare_capture()
                        except Exception:
                            pass

            if inventory_sweep is not None:
                try:
                    inv_snap = inventory_sweep.poll()
                    if inv_snap is not None and inv_snap is not last_inv_snap:
                        last_inv_snap = inv_snap
                        from app._03_world.memory_inventory import (
                            apply_inventory_snapshot,
                            refresh_shop_needs_from_inventory,
                        )

                        apply_inventory_snapshot(world, inv_snap)
                        refresh_shop_needs_from_inventory(
                            world, decision.blackboard
                        )
                        if (
                            not inv_live_logged
                            and inv_snap.get("source") != "inv.json"
                        ):
                            inv_live_logged = True
                            inv = world.player.inventory
                            self._log_ui(
                                "inventory_ready",
                                hp=inv.hp_potion,
                                arrows=inv.arrows,
                                silver=inv.silver_arrows,
                                depoison=inv.depoison,
                            )
                except Exception as exc:
                    self.log(f"Inventory poll failed: {exc}")
                    try:
                        inventory_sweep.close()
                    except Exception:
                        pass
                    inventory_sweep = None

            now_hb = time.perf_counter()
            if now_hb - last_hotbar_t >= 1.0:
                last_hotbar_t = now_hb
                try:
                    from app._03_world.hotbar_listen_reader import shared_hotbar

                    hb_snap = shared_hotbar().snapshot()
                    if hb_snap is not None:
                        world.last_hotbar = hb_snap
                except Exception:
                    pass
            if now_hb - last_hotbar_ui_t >= hotbar_ui_interval:
                last_hotbar_ui_t = now_hb
                hotbar_ui_interval = next_hotbar_refresh_s()
                try:
                    live = inspect_hotbars()
                    self._commit_hotbar_scan(
                        profile, world, live, persist=False, log_result=False
                    )
                except Exception:
                    pass

            if not memory_weight_ready(world.player):
                weight_hud.update(world, frame)

            if not self._pause_gate.is_set() or self._stop_event.is_set():
                self._push_paused_preview(last_preview, "Bot paused")
                publish("paused")
                continue

            if is_cursor_paralyzed():
                if not paralyzed_dropped:
                    executor.drop_mouse()
                    paralyzed_dropped = True
                # Capture/vision already ran; skip decide+act until cursor clears.
                publish("cursor_paralyzed")
                continue
            paralyzed_dropped = False

            if (
                not session_origin_ready
                and time.perf_counter() < session_ready_deadline
            ):
                publish("waiting_live_origin")
                continue

            action = decision.decide(world)
            last_action = action
            now = time.perf_counter()
            dt = now - last_tick_t
            last_tick_t = now
            last_tick_ms = round(dt * 1000.0, 1)
            last_fps = round((1.0 / dt) if dt > 0 else 0.0, 1)
            executor.execute(world, action, bounds=capture.content_bounds)
            if action.action is ActionType.USE_TALKING_SCROLL:
                apply_talking_scroll_arrival(
                    decision.blackboard, config, vision=vision
                )
            apply_mother_tree_mainland_stay(
                decision.blackboard, config, vision=vision
            )
            decision.apply_cursor_verify_feedback(executor)

            if (
                self._preview_enabled.is_set()
                and self._preview_q.empty()
                and now - last_preview_t >= 0.05
            ):
                try:
                    last_preview = draw_vision_preview(
                        frame,
                        action,
                        world,
                        blackboard=decision.blackboard,
                        scale=0.5,
                    )
                except Exception:
                    last_preview = paused_preview(
                        last_preview, "Preview frame unavailable"
                    )
                self._push_preview_image(last_preview)
                last_preview_t = now
            publish("tick")

        try:
            executor.drop_mouse()
        except Exception:
            pass
        try:
            from app._05_action.mouse import release_capture

            release_capture()
        except Exception:
            pass
        try:
            from manmabot_v1.input_release import restore_desktop_input

            restore_desktop_input()
        except Exception:
            pass
        if monitor is not None:
            try:
                monitor.close()
            except Exception:
                pass
        if entity_sweep is not None:
            try:
                entity_sweep.close()
            except Exception:
                pass
        if inventory_sweep is not None:
            try:
                inventory_sweep.close()
            except Exception:
                pass
