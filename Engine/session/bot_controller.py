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

from session.paths import (
    ensure_userdata,
    manmabot_root,
)
from session.probes import (
    Lamp,
    bring_game_to_front,
    pause_reason_from_game,
    probe_game,
    probe_memory,
)
from settings.profile import Profile
from i18n.strings import ui_strings


class RunState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


LogFn = Callable[[str], None]
StateFn = Callable[[RunState, str], None]
HotbarFn = Callable[[dict, dict], None]


def _routine_clock_from_board(blackboard) -> dict | None:
    """Copy the active routine stay clock. Does not change the cursor."""
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return None
    cursor = scratch.get("routine_cursor")
    entries = getattr(cursor, "entries", None)
    if not entries:
        return None
    ids: list[str] = []
    durations_s: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ids.append(str(entry.get("id") or ""))
        try:
            minutes = int(entry.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        durations_s.append(max(0, minutes) * 60)
    if not ids:
        return None
    try:
        index = int(getattr(cursor, "index", 0) or 0)
    except (TypeError, ValueError):
        index = 0
    try:
        started_at = float(getattr(cursor, "started_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
    active = entries[index % len(entries)] if entries else None
    kind = ""
    if isinstance(active, dict):
        kind = str(active.get("kind") or "").strip().lower()
    if not kind:
        kind = str(scratch.get("routine_kind") or "").strip().lower()
    session = scratch.get("world_nav_session")
    need = bool(scratch.get("need_world_nav"))
    navigating = session is not None or need
    # Break stay must show a countdown, not a stuck "Moving" if need lingered.
    if kind == "break" and session is None:
        navigating = False
    return {
        "index": index % len(ids),
        "started_at": started_at,
        "ids": ids,
        "durations_s": durations_s,
        "navigating": navigating,
        "kind": kind,
    }


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
        # Read-only label for the income cards. Does not change shop clicks.
        self._shop_lock = threading.Lock()
        self._shop_kind = ""
        self._buy_until = 0.0
        self._preview_enabled = threading.Event()
        self._preview_q: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self._last_pause_preview_t: float = 0.0
        self._capture_lock = threading.Lock()
        self._preview_lock = threading.Lock()
        self._vision_preview_stop = threading.Event()
        self._vision_preview_thread: Optional[threading.Thread] = None
        self._preview_tick = None
        self._preview_hold: Optional[str] = None
        self._cap_status = "idle"
        self._cap_rect = None
        self._cap_bounds = None
        self._debug_lock = threading.Lock()
        self._debug_snapshot: dict = {}
        self._debug_watchers = 0
        # Temp party monitor UI — independent of debug watchers.
        self._party_monitor: dict = {}
        # Read-only copy of the live routine cursor for the schedule list.
        self._routine_clock: dict | None = None
        self._routine_clock_gen = 0
        self._preview_watchers = 0
        # Schedule Start may begin while the console still owns focus.
        # Later focus loss still pauses; see auto_pause_tick.
        self._unattended = False
        # Paused "update schedule" bumps the epoch. The worker applies it
        # before the next decision tick. Start resets both counters.
        self._settings_epoch = 0
        self._settings_applied = 0
        self._route_identity: tuple | None = None
        # Party leader socket. Lives only while this worker runs.
        self._party_ws = None
        self._party_ws_owned = False
        # Party member client. Reports player status while this worker runs.
        self._party_client = None
        self._party_heartbeat = None

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

    def set_humanize_move(self, on: bool) -> None:
        """Live curved-move toggle. Takes effect on the next mouse move."""
        executor = getattr(self, "_action_executor", None)
        mouse = getattr(executor, "mouse", None)
        if mouse is not None:
            mouse.humanize_move = bool(on)

    def _push_executor_profile(self, profile, world, executor) -> None:
        """Spell slots and humanize flags. Does not change character class."""
        from app._05_action.spell_box import configure_spell_box

        layout = getattr(profile, "hotbar_layout", None) or {}
        if world is not None:
            world.hotbar_layout = layout
        if executor is not None:
            executor.hotbar_layout = layout
            executor.humanize = bool(getattr(profile, "humanize", True))
            mouse = getattr(executor, "mouse", None)
            if mouse is not None:
                mouse.humanize = bool(getattr(profile, "humanize", True))
                mouse.humanize_move = bool(getattr(profile, "humanize_move", True))
            keyboard = getattr(executor, "keyboard", None)
            if keyboard is not None:
                keyboard.humanize = bool(getattr(profile, "humanize", True))
        configure_spell_box(getattr(profile, "spell_slots", None))

    def _consume_paused_settings(self, config, decision, world, executor) -> None:
        """Apply a paused schedule update before the next decision tick."""
        from session.runtime_settings import (
            install_profile_runtime,
            restart_paused_routine,
            route_identity,
            snapshot_profile,
        )

        with self._lock:
            epoch = self._settings_epoch
            if epoch == self._settings_applied:
                return
            snap = snapshot_profile(self._profile)
        reset_route = False
        try:
            new_route = route_identity(snap)
            reset_route = new_route != self._route_identity
            install_profile_runtime(snap, config, navigation=reset_route)
            if decision is not None:
                decision.blackboard.scratch["runtime_config"] = config
                if reset_route:
                    restart_paused_routine(snap, config, decision.blackboard)
            self._push_executor_profile(snap, world, executor)
            self._route_identity = new_route
            if reset_route:
                self.log("Paused settings applied; routine restarted")
            else:
                self.log("Paused settings applied")
        except Exception:
            self.log("Paused settings reload failed:\n" + traceback.format_exc())
        with self._lock:
            self._settings_applied = epoch

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

    def routine_clock(self) -> dict | None:
        """Live routine index and stay clock. None when the worker is stopped."""
        if self.state == RunState.STOPPED:
            return None
        with self._debug_lock:
            clock = self._routine_clock
        if not clock:
            return None
        return {
            "index": int(clock["index"]),
            "started_at": float(clock["started_at"]),
            "ids": list(clock["ids"]),
            "durations_s": list(clock["durations_s"]),
            "navigating": bool(clock["navigating"]),
            "kind": str(clock.get("kind") or ""),
        }

    def _note_routine_clock(self, blackboard, gen: int) -> None:
        clock = _routine_clock_from_board(blackboard)
        with self._debug_lock:
            if self._routine_clock_gen != gen:
                return
            self._routine_clock = clock

    def debug_snapshot(self) -> dict:
        """Latest runtime snapshot for the debug GUI (same worker as Start)."""
        from session.debug_snapshot import build_runtime_snapshot

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

    def party_monitor_snapshot(self) -> dict:
        """Party monitor payload: live DLL party + socket message log."""
        with self._debug_lock:
            snap = dict(self._party_monitor) if self._party_monitor else {}
        try:
            from websocket.traffic_log import snapshot as party_messages

            snap["messages"] = party_messages()
        except Exception:
            snap.setdefault("messages", [])
        snap.setdefault("bot_state", self.state.value)
        snap.setdefault("bot_reason", self.reason)
        snap.setdefault(
            "worker_alive",
            self._thread is not None and self._thread.is_alive(),
        )
        # Live party read every UI poll — do not wait for Start / party mode.
        try:
            from session.party_probe import probe_party_live

            live = probe_party_live()
            snap["dll_path"] = live.get("dll_path") or ""
            snap["dll_loaded"] = bool(live.get("dll_loaded"))
            snap["probe_error"] = str(live.get("error") or "")
            if isinstance(live.get("party"), dict):
                snap["party"] = live["party"]
            elif "party" not in snap:
                snap["party"] = None
            if live.get("error") and not snap.get("note"):
                snap["note"] = "probe"
        except Exception as exc:
            snap.setdefault("dll_loaded", False)
            snap["probe_error"] = str(exc)
        # Profile flag so UI shows whether the Party tab master switch is on.
        try:
            snap["profile_party_enabled"] = bool(
                getattr(
                    self._profile,
                    "party_enabled",
                    getattr(self._profile, "party_member_enabled", False),
                )
            )
        except Exception:
            snap["profile_party_enabled"] = False
        return snap

    def _publish_party_monitor(
        self,
        *,
        party_brain,
        world,
        action=None,
        note: str = "",
    ) -> None:
        """Always publish while party mode is on (does not need debug watchers)."""
        try:
            status = party_brain.status() if party_brain is not None else {}
            party = getattr(world, "last_party", None) if world is not None else None
            if isinstance(party, dict):
                party = dict(party)
            else:
                party = None
            action_name = ""
            target_id = None
            if action is not None:
                raw = getattr(action, "action", None)
                action_name = getattr(raw, "value", None) or str(raw or "")
                target_id = getattr(action, "target_id", None)
            player = getattr(world, "player", None) if world is not None else None
            self_xy = None
            self_hp = None
            self_mp = None
            # mapId only from MapSubsystem path already stored on party runtime.
            self_map = status.get("local_map_id")
            if player is not None:
                try:
                    self_hp = getattr(player, "hp", None)
                    self_mp = getattr(player, "mp", None)
                except Exception:
                    pass
                pos = getattr(player, "position", None)
                if pos is not None:
                    try:
                        self_xy = (int(pos.x), int(pos.y))
                    except Exception:
                        pass
            snap = {
                "enabled": party_brain is not None,
                "note": str(note or ""),
                "updated_at": time.time(),
                "status": status,
                "party": party,
                "decisions": list(status.get("decision_history") or []),
                "action": {
                    "name": str(action_name),
                    "target_id": target_id,
                },
                "self": {
                    "xy": self_xy,
                    "hp": self_hp,
                    "mp": self_mp,
                    "map_id": self_map,
                },
                "bot_state": self.state.value,
                "bot_reason": self.reason,
                "worker_alive": self._thread is not None and self._thread.is_alive(),
            }
            with self._debug_lock:
                self._party_monitor = snap
        except Exception:
            pass

    def _publish_debug(
        self,
        *,
        world=None,
        blackboard=None,
        action=None,
        vision=None,
        loop=None,
        arming: bool = False,
        executor=None,
    ) -> None:
        with self._debug_lock:
            if self._debug_watchers <= 0:
                return
        try:
            from session.debug_snapshot import build_runtime_snapshot

            if executor is None:
                executor = getattr(self, "_action_executor", None)
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
                executor=executor,
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
        # Match interface backpressure: do not encode while the UI still holds
        # a frame — JPEG/PhotoImage flood is the main preview hitch source.
        if not self._preview_q.empty():
            return
        from app._03_world.debug.preview import encode_preview_jpeg

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
        from app._03_world.debug.preview import paused_preview

        self._push_preview_image(paused_preview(last, message))

    def _set_preview_hold(self, message: Optional[str]) -> None:
        with self._preview_lock:
            self._preview_hold = message

    def _publish_preview_tick(self, tick) -> None:
        with self._preview_lock:
            self._preview_hold = None
            self._preview_tick = tick

    def _sample_capture(self, capture):
        """Client rect and 4:3 click bounds. Does not copy the framebuffer."""
        with self._capture_lock:
            status = capture.refresh_click_bounds()
            return status, capture.content_rect, capture.content_bounds

    def _start_vision_preview(self, capture) -> None:
        self._vision_preview_stop = threading.Event()
        with self._preview_lock:
            self._cap_status = "idle"
            self._cap_rect = None
            self._cap_bounds = None
            self._preview_tick = None
            self._preview_hold = None
        capture.release_grabber()
        worker = threading.Thread(
            target=self._vision_preview_loop,
            args=(capture, self._vision_preview_stop),
            name="vision-preview",
            daemon=True,
        )
        self._vision_preview_thread = worker
        worker.start()

    def _stop_vision_preview(self) -> None:
        self._vision_preview_stop.set()
        worker = self._vision_preview_thread
        self._vision_preview_thread = None
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)

    def _vision_preview_loop(self, capture, stop: threading.Event) -> None:
        """Draw the debug preview. Pixel grabs run only while it is open."""
        from app._03_world.debug.preview import (
            PREVIEW_PERIOD_S,
            draw_vision_preview,
            draw_waiting_preview,
            paused_preview,
        )

        last_image = None
        next_t = time.perf_counter()
        grabber_open = False
        try:
            while not stop.is_set():
                now = time.perf_counter()
                showing = self._preview_enabled.is_set()
                period = PREVIEW_PERIOD_S if showing else 0.25
                if now < next_t:
                    time.sleep(min(0.004, next_t - now))
                    continue
                next_t += period
                if next_t < now - period:
                    next_t = now + period
                if not showing:
                    if grabber_open:
                        with self._capture_lock:
                            capture.release_grabber()
                        grabber_open = False
                    continue
                if not grabber_open:
                    try:
                        with self._capture_lock:
                            capture.open_grabber()
                        grabber_open = True
                    except Exception as exc:
                        self.log(f"Preview capture failed to start: {exc}")
                        continue
                frame = None
                status = "no_window"
                try:
                    with self._capture_lock:
                        if capture.is_minimized:
                            status = "minimized"
                        else:
                            frame = capture.get_frame()
                            status = "ok" if frame is not None else "no_window"
                except Exception:
                    status = "no_window"
                    frame = None
                with self._preview_lock:
                    hold = self._preview_hold
                    tick = self._preview_tick
                # UI still displaying previous JPEG — skip draw/encode this tick.
                if not self._preview_q.empty():
                    continue
                try:
                    if hold:
                        image = paused_preview(
                            last_image if last_image is not None else frame, hold
                        )
                    elif status == "minimized":
                        image = paused_preview(
                            last_image, "Game window minimized — bot paused"
                        )
                    elif frame is None:
                        image = paused_preview(last_image, "Waiting for game window")
                    elif tick is None:
                        image = draw_waiting_preview(
                            frame, "waiting for decision tick", scale=0.5
                        )
                    else:
                        image = draw_vision_preview(
                            frame,
                            tick.action,
                            tick.state,
                            blackboard=tick.board,
                            scale=0.5,
                            tick_ms=tick.tick_ms,
                            tick_parts=getattr(tick, "tick_parts", None) or None,
                        )
                except Exception:
                    image = paused_preview(last_image, "Preview frame unavailable")
                if image is not None:
                    last_image = image
                    self._push_preview_image(image)
        finally:
            try:
                capture.release_grabber()
            except Exception:
                pass

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
        from hotbar.inspect import merge_detected_spell_slots
        from settings.antidote_potion import apply_antidote_potion_to_spell_slots
        from settings.haste_potion import apply_haste_potion_to_spell_slots
        from settings.hp_actions import apply_recovery_to_spell_slots
        from settings.profile import save_profile
        from settings.spell_defaults import spell_slot_bindings

        previous_slots = dict(getattr(profile, "spell_slots", {}) or {})
        profile.hotbar_layout = detected.to_profile_dict()
        if world is not None:
            world.hotbar_layout = profile.hotbar_layout
        try:
            from app._01_perception.sensors import shared_sensors

            world.last_hotbar = shared_sensors().capture_hotbar(force=True)
        except Exception:
            pass
        merged = apply_recovery_to_spell_slots(
            merge_detected_spell_slots(detected.spell_slots, previous_slots),
            getattr(profile, "hp_actions", None),
        )
        profile.spell_slots = spell_slot_bindings(
            apply_antidote_potion_to_spell_slots(
                apply_haste_potion_to_spell_slots(
                    merged,
                    use=bool(getattr(profile, "use_haste_potion", False)),
                    item_key=str(getattr(profile, "haste_potion_item", "") or ""),
                    box=getattr(profile, "haste_potion_box", 0),
                    key=getattr(profile, "haste_potion_key", ""),
                    layout=profile.hotbar_layout,
                    world=world,
                ),
                use=bool(getattr(profile, "use_antidote_potion", False)),
                item_key=str(getattr(profile, "antidote_potion_item", "") or ""),
                box=getattr(profile, "antidote_potion_box", 0),
                key=getattr(profile, "antidote_potion_key", ""),
                layout=profile.hotbar_layout,
                world=world,
            )
        )
        from app._05_action.spell_box import apply_boot_talking_scroll

        apply_boot_talking_scroll(
            profile.spell_slots, getattr(detected, "spell_slots", None)
        )
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
        from i18n.localized_names import memory_name_for_ui

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
        from session.probes import (
            list_patrol_entries,
            load_map_pack_safe,
            map_style_is_dungeon,
        )

        pack = load_map_pack_safe(profile.active_map)
        if pack is None:
            return "map_missing"
        from settings.farm_schedule import routine_is_break_only

        if routine_is_break_only(getattr(profile, "routine", None)):
            return "start_break_only"
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

        ``unattended=True`` (schedule Start): begin running even if the
        console stole game focus at the click. Later focus loss still pauses.
        """
        with self._lock:
            if self.state != RunState.STOPPED:
                return None
            err = self.start_gates_ok(profile)
            if err:
                return err
            self._profile = profile
            self._settings_epoch = 0
            self._settings_applied = 0
            self._route_identity = None
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

    def note_shop_action(self, action) -> None:
        """Remember a buy while that shop click sequence is running.

        The income cards ignore an Adena drop only during a buy. Selling stays
        a normal gain. This does not change what the shop click does.
        """
        kind = ""
        if action is not None:
            token = getattr(action, "action", None)
            label = str(
                getattr(token, "value", None)
                or getattr(token, "name", None)
                or token
                or ""
            ).lower()
            if label == "shop_run":
                if bool(getattr(action, "shop_use_recover", False)):
                    kind = "buy"
                else:
                    kind = str(getattr(action, "shop_kind", "") or "").strip().lower()
        with self._shop_lock:
            self._shop_kind = kind
            if kind == "buy":
                self._buy_until = time.monotonic() + 8.0

    def purchase_in_progress(self) -> bool:
        """True while a buy is clicking, and for a short time after it returns."""
        with self._shop_lock:
            kind = self._shop_kind
            until = self._buy_until
        if kind == "buy":
            return True
        return kind == "" and time.monotonic() < until

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

    def _start_party_socket(self) -> None:
        """Listen while this worker runs, only when Party is enabled as leader."""
        profile = self._profile
        if not bool(getattr(profile, "party_enabled", False)):
            return
        role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        if role != "leader":
            return
        try:
            port = int(getattr(profile, "party_ws_port", 8765) or 8765)
        except (TypeError, ValueError):
            port = 8765
        port = max(1, min(65535, port))
        try:
            from websocket.active import current, publish
            from websocket.netinfo import local_ipv4
            from websocket.watchdog import PartyServerWatchdog

            existing = current()
            if (
                existing is not None
                and existing.running
                and int(existing.server.port) == port
            ):
                self._party_ws = existing
                self._party_ws_owned = False
                self.log(
                    f"Party socket already listening on port {port}. Using that server."
                )
                return

            watchdog = PartyServerWatchdog(
                host="0.0.0.0",
                port=port,
                relay=True,
                announce=True,
            )
            watchdog.start(timeout=5.0)
        except Exception as exc:
            self._party_ws = None
            self._party_ws_owned = False
            self.log(f"Party socket failed to start on port {port}: {exc}")
            return
        publish(watchdog)
        self._party_ws = watchdog
        self._party_ws_owned = True
        try:
            from websocket.traffic_log import clear as clear_party_log

            clear_party_log()
        except Exception:
            pass
        try:
            advertise = local_ipv4()
        except Exception:
            advertise = "127.0.0.1"
        self.log(
            f"Party socket listening on {advertise}:{port} (bind 0.0.0.0). "
            "It stops when this bot stops."
        )

    def _stop_party_socket(self) -> None:
        watchdog = self._party_ws
        owned = self._party_ws_owned
        self._party_ws = None
        self._party_ws_owned = False
        if watchdog is None or not owned:
            return
        try:
            from websocket.active import clear

            clear(watchdog)
            watchdog.stop(timeout=3.0)
            self.log("Party socket stopped")
        except Exception as exc:
            self.log(f"Party socket stop failed: {exc}")

    def _start_party_client(self) -> None:
        """Member bot connects to the leader and reports player status."""
        profile = self._profile
        role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        enabled = bool(getattr(profile, "party_member_enabled", False))
        if role != "member" or not enabled:
            return
        host = str(getattr(profile, "party_leader_host", "") or "").strip()
        if not host:
            self.log("Party member status heartbeat needs the leader address.")
            return
        try:
            port = int(getattr(profile, "party_ws_port", 8765) or 8765)
        except (TypeError, ValueError):
            port = 8765
        port = max(1, min(65535, port))
        try:
            from websocket.client import PartyClient
            from websocket.member_status import MemberHeartbeat

            client = PartyClient(
                host=host,
                port=port,
                sender="member",
                reconnect=True,
            )
            client.connect(wait=False)
        except Exception as exc:
            self._party_client = None
            self._party_heartbeat = None
            self.log(f"Party member client failed to start: {exc}")
            return
        self._party_client = client
        self._party_heartbeat = MemberHeartbeat(client)
        try:
            from websocket.traffic_log import clear as clear_party_log

            clear_party_log()
        except Exception:
            pass
        self.log(f"Party member status heartbeat every 10s to {host}:{port}")

    def _stop_party_client(self) -> None:
        client = self._party_client
        self._party_client = None
        self._party_heartbeat = None
        if client is None:
            return
        try:
            client.close(timeout=3.0)
            self.log("Party member client stopped")
        except Exception as exc:
            self.log(f"Party member client stop failed: {exc}")

    def _worker(self) -> None:
        ensure_userdata()
        # Windowed / pythonw launches leave stdout/stderr as None; torch hub
        # and other libs crash on sys.stdout.write during model download.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        crashed = False
        try:
            self._start_party_socket()
            self._start_party_client()
            self._run_bot_loop()
        except Exception:
            crashed = True
            self.log("Worker crashed:\n" + traceback.format_exc())
        finally:
            self._stop_party_socket()
            self._stop_party_client()
            with self._lock:
                if self.state != RunState.STOPPED:
                    # Distinct from a clean user Stop so the UI can disarm the
                    # schedule and disable Stop (armed schedule alone kept Stop on).
                    self._set_state(
                        RunState.STOPPED,
                        "worker_crashed" if crashed else "",
                    )
            self._log_ui("worker_exited")
            try:
                from app._05_action.mouse import release_capture

                release_capture()
            except Exception:
                pass
            try:
                from session.input_release import restore_desktop_input

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

        from session.perception_capture import open_perception_capture
        from app._02_state import ActionType, CharacterType
        from app._03_world.merge.track import create_game_state
        from app._03_world.merge.memory_sync import world_origin_from_snapshot
        from app._04_decision.configure import apply_action_executor_options
        from app._04_decision.manager import DecisionManager
        from app._04_decision.talking_scroll import (
            apply_mother_tree_mainland_stay,
            apply_talking_scroll_arrival,
        )
        from app._05_action.controller import ActionExecutor
        from app._05_action.cursor_verify import is_cursor_paralyzed
        from app._06_party import PartyMemberConfig, PartyMemberManager

        profile = self._profile
        party_role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        if party_role not in ("member", "leader"):
            party_role = "member"
        # Leader hosts the socket and farms on its own. Member follow stays off.
        member_on = (
            bool(getattr(profile, "party_member_enabled", False)) and party_role != "leader"
        )
        config = load_config()
        # Single enable path: UI → SettingsBag → profile (no YAML / JSON dual path).
        party_cfg = PartyMemberConfig.from_mapping(
            {
                "enabled": member_on,
                # Leader identity comes from party_listen memory after join.
                "follow_tiles": int(
                    getattr(
                        profile,
                        "party_follow_tiles",
                        getattr(profile, "party_follow_start_tiles", 8),
                    )
                ),
                "stop_tiles": int(
                    getattr(
                        profile,
                        "party_stop_tiles",
                        getattr(profile, "party_follow_stop_tiles", 2),
                    )
                ),
                "assist_leash_tiles": int(
                    getattr(profile, "party_assist_leash_tiles", 10)
                ),
                "approach_tiles": int(
                    getattr(profile, "party_approach_tiles", 2)
                ),
                "potion_hp_ratio": float(
                    getattr(profile, "party_potion_hp_ratio", 0.45)
                ),
                "random_loot": bool(
                    getattr(profile, "party_random_loot", False)
                ),
                "loot_role": str(
                    getattr(profile, "party_loot_role", "none") or "none"
                ),
                "farm_mode": str(
                    getattr(profile, "party_farm_mode", "party") or "party"
                ),
            }
        )
        party_mode = bool(party_cfg.enabled)
        self.log(
            "Party gate: "
            f"role={party_role} "
            f"ws_port={int(getattr(profile, 'party_ws_port', 8765) or 8765)} "
            f"profile.party_enabled="
            f"{bool(getattr(profile, 'party_enabled', False))} "
            f"profile.party_member_enabled="
            f"{bool(getattr(profile, 'party_member_enabled', False))} "
            f"→ party_mode={party_mode}"
        )
        if party_role == "leader":
            self.log(
                "Party leader farms with the solo routine. "
                "Only a member bot uses party follow."
            )
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
        from session.runtime_settings import (
            install_profile_runtime,
            route_identity,
            snapshot_profile,
        )

        with self._lock:
            seen_epoch = self._settings_epoch
            profile_snap = snapshot_profile(profile)
        world_origin = install_profile_runtime(profile_snap, config, navigation=True)
        self._route_identity = route_identity(profile_snap)
        with self._lock:
            self._settings_applied = seen_epoch


        character = CharacterType(profile.character)
        attack_mode = str(
            getattr(profile, "attack_mode", "magic") or "magic"
        ).strip().lower()
        if attack_mode not in ("ranged", "magic", "melee"):
            attack_mode = "magic"
        try:
            from app._04_decision import player_mode as pm

            pm.ATTACK_MODE = attack_mode
        except Exception:
            pass
        capture = open_perception_capture(config)
        memory_cfg = config.get("memory") or {}
        from app._03_world.merge.memory_entities import entity_source_is_legacy

        raw_entity_source = memory_cfg.get("entity_source", "memory")
        if entity_source_is_legacy(raw_entity_source):
            self.log(
                f"memory.entity_source={raw_entity_source!r} ignored; "
                "farm image recognition was removed. Using memory entities."
            )
        world = create_game_state(character)
        world.hotbar_layout = getattr(profile, "hotbar_layout", None) or {}
        decision = DecisionManager()
        decision.blackboard.world_origin = world_origin
        decision.blackboard.scratch["runtime_config"] = config
        party_brain: PartyMemberManager | None = None
        if party_mode:
            party_brain = PartyMemberManager(party_cfg)
            party_brain.set_world_origin(world_origin)
            party_brain.set_nav_blackboard(decision.blackboard)
            self._publish_party_monitor(
                party_brain=party_brain,
                world=world,
                action=None,
                note="party_armed",
            )
            self.log(
                "Party member mode — follow memory party leader "
                f"(follow>{party_cfg.follow_tiles} "
                f"stop<={party_cfg.stop_tiles} farm={party_cfg.farm_mode}); "
                "off-UI chase + other-map join"
            )
        else:
            with self._debug_lock:
                self._party_monitor = {
                    "enabled": False,
                    "note": "solo",
                    "updated_at": time.time(),
                    "status": {},
                    "party": None,
                    "decisions": [],
                    "action": {"name": "", "target_id": None},
                    "self": {},
                    "bot_state": self.state.value,
                    "bot_reason": self.reason,
                    "worker_alive": True,
                }

            try:
                from app._04_decision.world_nav import (
                    begin_world_nav,
                    init_routine_on_blackboard,
                )
                from session.world_nav_inject import install_world_nav_overlays
                from settings.farm_schedule import normalize_routine

                fallback_map = str(profile.active_map or "talking_island")
                routine_rows = normalize_routine(
                    getattr(profile, "routine", None) or []
                )
                install_world_nav_overlays(
                    decision.blackboard,
                    routine_rows=routine_rows,
                    fallback_map=fallback_map,
                )
                init_routine_on_blackboard(
                    decision.blackboard,
                    routine=routine_rows,
                    fallback_map=fallback_map,
                    selected_farms=list(profile.selected_farms or []),
                    farm_stays_s=dict(getattr(profile, "farm_stays_s", {}) or {}),
                    entries_normalized=True,
                )
                begin_world_nav(decision.blackboard, "start")
                self.log(
                    f"World nav armed for routine "
                    f"({len(routine_rows)} entries)"
                )
            except Exception as exc:
                self.log(f"World nav init skipped: {exc}")

        from app._01_perception.sensors import (
            PerceptionSensors,
            clear_shared_sensors,
            set_shared_sensors,
        )
        from app._03_world.merge.apply_perception import apply_perception_buffer

        sensors = PerceptionSensors(config)
        set_shared_sensors(sensors)
        for err in list(sensors.buffer.errors):
            self.log(f"Perception sensor: {err}")
        if sensors.monitor is not None:
            self.log(
                "Player memory is read in this process "
                "(realtime_monitor.dll, offsets.json). No separate console."
            )
        else:
            self.log("Memory monitor unavailable at worker start")
        buf0 = sensors.capture_tick(
            force_inventory=True, hotbar=True, party=party_mode
        )
        # Party init is lazy inside capture_tick — surface those errors now.
        for err in list(sensors.buffer.errors):
            self.log(f"Perception sensor: {err}")
        if party_mode:
            from app._01_perception.party_listen_reader import default_dll_path

            party_reader = getattr(sensors, "_party", None)
            dll_ok = bool(
                party_reader is not None
                and getattr(party_reader, "dll_loaded", False)
            )
            if not dll_ok:
                dll_name = default_dll_path().name
                self.log(
                    f"Party member mode BLOCKED: {dll_name} missing. "
                    "Build Engine/analysis/party/build_party_listen_dll.bat "
                    "(needs VS Build Tools with VCTools), then restart."
                )
                self._publish_party_monitor(
                    party_brain=party_brain,
                    world=world,
                    action=None,
                    note=f"dll_missing:{dll_name}",
                )
            elif not buf0.party_ok:
                self.log(
                    "Party member mode on, but party memory read failed "
                    "(join a party in-game; check signeddrv / LC attach)."
                )
            else:
                snap = buf0.party if isinstance(buf0.party, dict) else {}
                self.log(
                    "Party memory ok "
                    f"in_party={bool(snap.get('in_party'))} "
                    f"count={snap.get('count')} "
                    f"leader={snap.get('leader_name') or '—'}"
                )
        apply_perception_buffer(world, decision.blackboard, buf0, content=None)
        if sensors.inventory_sweep is None:
            self._log_ui("inventory_setup_failed", error="inventory DLL unavailable")
        elif buf0.inventory_ok:
            inv = world.player.inventory
            self._log_ui(
                "inventory_started",
                via="dll",
                hp=inv.hp_potion,
                arrows=inv.arrows,
                silver=inv.silver_arrows,
                depoison=inv.depoison,
            )
        else:
            from app._01_perception.inventory_listen_reader import default_dll_path

            self._log_ui("inventory_scanning", dll=default_dll_path().name)
        last_inv_snap = buf0.inventory
        inv_live_logged = bool(buf0.inventory_ok)

        executor = ActionExecutor(
            enabled=True,
            character=character,
            humanize=profile.humanize,
            humanize_move=bool(getattr(profile, "humanize_move", True)),
            attack_mode=attack_mode,
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

        from hotbar.inspect import HotbarInspectError, inspect_hotbars

        self._log_ui("hotbar_reading")
        self._publish_debug(loop={"note": "hotbar_scan"})

        def _abort_hotbar(reason: str) -> None:
            self.log(reason)
            self._set_state(RunState.STOPPED, reason)
            try:
                executor.drop_mouse()
            except Exception:
                pass
            try:
                clear_shared_sensors()
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
        from app._05_action.spell_box import begin_talking_scroll_boot

        begin_talking_scroll_boot()
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

        from i18n.localized_names import (
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

        last_action = None
        last_vision = None
        shop_bag_armed = False
        bag_after_shop = False
        last_tick_t = time.perf_counter()
        last_publish_t = 0.0
        last_hotbar_ui_t = time.perf_counter()
        from hotbar.inspect import next_hotbar_refresh_s

        hotbar_ui_interval = next_hotbar_refresh_s()
        last_fps = 0.0
        last_tick_ms = 0.0
        last_astar: list = []
        last_decide: list = []
        mouse_dropped = False
        paralyzed_dropped = False
        minimized_dropped = False
        # After autologin, the first ticks often have no live world cell yet.
        # Clicks then miss (shop NPC / combat cursor). Wait briefly for origin.
        # Also require MapSubsystem mapId when the monitor is attached (TI=0 ok).
        session_origin_ready = False
        session_map_id_ready = sensors.monitor is None
        session_ready_deadline = time.perf_counter() + 2.5
        capture_rebound = False
        last_logged_map_id: int | None = None
        map_id_start_logged = False

        with self._debug_lock:
            self._routine_clock_gen += 1
            routine_clock_gen = self._routine_clock_gen

        def publish(note: str, *, force: bool = False) -> None:
            nonlocal last_publish_t
            now = time.perf_counter()
            try:
                self._note_routine_clock(decision.blackboard, routine_clock_gen)
            except Exception:
                pass
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
                    "astar": last_astar,
                    "decide_spans": last_decide,
                },
            )

        publish("loop_ready", force=True)
        self._start_vision_preview(capture)
        try:
            while not self._stop_event.is_set():
                while not self._stop_event.is_set() and not self._pause_gate.is_set():
                    # Lift once on pause so a leftover click does not stick, then
                    # leave the mouse alone so the operator can drag.
                    if not mouse_dropped:
                        executor.drop_mouse()
                        mouse_dropped = True
                    self._consume_paused_settings(config, decision, world, executor)
                    self._set_preview_hold("Paused")
                    publish("paused")
                    time.sleep(0.05)

                self._consume_paused_settings(config, decision, world, executor)
                mouse_dropped = False
                if self._stop_event.is_set():
                    break

                cap_status, content_rect, content_bounds = self._sample_capture(capture)
                if cap_status == "minimized":
                    if not minimized_dropped:
                        executor.drop_mouse()
                        minimized_dropped = True
                    self._set_preview_hold("Game window minimized — bot paused")
                    publish("minimized")
                    time.sleep(0.05)
                    continue
                minimized_dropped = False

                if cap_status != "ok":
                    self._set_preview_hold("Waiting for game window")
                    publish("no_window")
                    time.sleep(0.01)
                    continue
                self._set_preview_hold(None)
                tick_t0 = time.perf_counter()
                from app._04_decision.astar_trace import begin_tick

                begin_tick()

                inv_idle = not sensors.inventory_scanning()
                force_bag = False
                trip = bool(decision.blackboard.scratch.get("shop_trip"))
                if trip and not shop_bag_armed and inv_idle:
                    force_bag = True
                    shop_bag_armed = True
                elif not trip:
                    shop_bag_armed = False
                if bag_after_shop and inv_idle:
                    force_bag = True
                    bag_after_shop = False

                sense_buf = sensors.capture_tick(
                    force_inventory=force_bag,
                    party=party_brain is not None,
                )
                applied = apply_perception_buffer(
                    world,
                    decision.blackboard,
                    sense_buf,
                    content=content_rect,
                    previous_inventory=last_inv_snap,
                )
                last_vision = applied.entity_rows
                if applied.inventory_changed:
                    last_inv_snap = sense_buf.inventory
                    if not inv_live_logged and sense_buf.inventory_ok:
                        inv_live_logged = True
                        inv = world.player.inventory
                        self._log_ui(
                            "inventory_ready",
                            hp=inv.hp_potion,
                            arrows=inv.arrows,
                            silver=inv.silver_arrows,
                            depoison=inv.depoison,
                        )
                if applied.origin_ready:
                    session_origin_ready = True
                    if not capture_rebound:
                        capture_rebound = True
                        try:
                            from app._05_action.mouse import prepare_capture

                            prepare_capture()
                        except Exception:
                            pass
                if applied.map_id_ready and applied.live_map_id is not None:
                    session_map_id_ready = True
                    mid = int(applied.live_map_id)
                    if not map_id_start_logged:
                        map_id_start_logged = True
                        last_logged_map_id = mid
                        self.log(
                            f"Live mapId={mid} "
                            "(MapSubsystem, every-tick refresh)"
                        )
                    elif last_logged_map_id != mid:
                        self.log(f"Live mapId {last_logged_map_id}→{mid}")
                        last_logged_map_id = mid
                    try:
                        from app._04_decision.live_map_pack import (
                            ensure_navigation_for_live_map_id,
                        )

                        _ok, sync_msg = ensure_navigation_for_live_map_id(
                            decision.blackboard,
                            config,
                            mid,
                            snapshot=applied.live_map_snap,
                        )
                        if sync_msg:
                            self.log(sync_msg)
                        # Party same-map / join-map needs MapSubsystem id every tick,
                        # even when world-origin snap is briefly missing.
                        if party_brain is not None:
                            try:
                                party_brain.set_local_map_id(int(mid))
                            except (TypeError, ValueError):
                                pass
                        if isinstance(applied.live_map_snap, dict):
                            wo = world_origin_from_snapshot(applied.live_map_snap)
                            if wo is not None:
                                decision.blackboard.world_origin = wo
                                if party_brain is not None:
                                    party_brain.set_world_origin(wo)
                                session_origin_ready = True
                    except Exception as sync_exc:
                        self.log(f"Live map pack sync failed: {sync_exc}")

                t_entities = time.perf_counter()
                t_hotbar = t_entities
                now_hb = t_hotbar
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

                if not self._pause_gate.is_set() or self._stop_event.is_set():
                    self._set_preview_hold("Paused")
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
                    (not session_origin_ready or not session_map_id_ready)
                    and time.perf_counter() < session_ready_deadline
                ):
                    publish(
                        "waiting_live_origin"
                        if not session_origin_ready
                        else "waiting_live_mapId"
                    )
                    continue

                # Scroll land: solo always; party only while joining the leader's map.
                party_joining = (
                    party_brain is not None and party_brain.joining_map()
                )
                if party_brain is None or party_joining:
                    apply_talking_scroll_arrival(
                        decision.blackboard, config, state=world
                    )

                if party_brain is not None:
                    beat = self._party_heartbeat
                    if beat is not None:
                        try:
                            beat.maybe_send(world, map_id=last_logged_map_id)
                        except Exception as beat_exc:
                            err = str(beat_exc)
                            if err != getattr(self, "_party_hb_err", ""):
                                self._party_hb_err = err
                                self.log(f"Party member status send failed: {err}")
                    action = party_brain.decide(world)
                    party_joining = party_brain.joining_map()
                    self._publish_party_monitor(
                        party_brain=party_brain,
                        world=world,
                        action=action,
                        note="decide",
                    )
                else:
                    action = decision.decide(world)
                    if party_role == "leader":
                        try:
                            from websocket.leader_decisions import (
                                publish_leader_decision,
                            )

                            sent = publish_leader_decision(
                                action,
                                world,
                                map_id=last_logged_map_id,
                            )
                            if sent:
                                self.log(f"Party leader decision sent: {sent}")
                        except Exception as party_exc:
                            self.log(f"Party leader decision send failed: {party_exc}")
                t_decide = time.perf_counter()
                last_action = action
                if party_brain is None:
                    try:
                        from app._04_decision.world_nav import SCRATCH_WORLD_NAV_PAUSE

                        if decision.blackboard.scratch.pop(SCRATCH_WORLD_NAV_PAUSE, None):
                            # Legacy flag: world-nav fail_skip no longer stops the bot.
                            # Clear and continue so a stale scratch cannot halt Start.
                            self.log(
                                "World nav pause flag ignored — continuing routine"
                            )
                            publish("world_nav_continue")
                            continue
                    except Exception as gate_exc:
                        self.log(f"World nav pause check: {gate_exc}")
                self.note_shop_action(action)
                try:
                    # Party uses the same blackboard for heal/buff cooldowns,
                    # potion sides, and WORLD_NAV join — never solo mode columns.
                    executor.execute(
                        world,
                        action,
                        bounds=content_bounds,
                        side_intents=list(
                            getattr(decision.blackboard, "side_intents", None) or []
                        ),
                        blackboard=decision.blackboard,
                    )
                finally:
                    self.note_shop_action(None)
                t_act = time.perf_counter()
                if action.action is ActionType.GATE:
                    try:
                        from app._04_decision.world_nav import apply_gate_result

                        gate = getattr(executor, "result", None)
                        pose = getattr(gate, "gate_pose", None) if gate else None
                        apply_gate_result(
                            decision.blackboard,
                            ok=bool(getattr(gate, "gate_ok", False)),
                            error=str(getattr(gate, "gate_error", "") or ""),
                            live_map_id=(
                                int(pose[0]) if pose is not None else None
                            ),
                            live_x=int(pose[1]) if pose is not None else None,
                            live_y=int(pose[2]) if pose is not None else None,
                        )
                    except Exception as gate_exc:
                        self.log(f"World nav gate result: {gate_exc}")
                # Party join-map may use NPC teleporter shop behaviors.
                if party_joining and getattr(action, "shop_behavior_id", None):
                    try:
                        from app._04_decision.shops import is_teleporter_behavior
                        from app._04_decision.world_nav import (
                            apply_npc_teleporter_result,
                        )

                        bid = str(action.shop_behavior_id or "")
                        if is_teleporter_behavior(bid):
                            apply_npc_teleporter_result(
                                decision.blackboard, behavior_id=bid
                            )
                    except Exception as tp_exc:
                        self.log(f"Party join teleporter result: {tp_exc}")
                trip_now = bool(decision.blackboard.scratch.get("shop_trip"))
                if trip_now and not shop_bag_armed:
                    bag_after_shop = True
                    shop_bag_armed = True
                elif not trip_now:
                    shop_bag_armed = False
                if bool(getattr(getattr(executor, "result", None), "shop_ok", False)):
                    bag_after_shop = True
                apply_mother_tree_mainland_stay(decision.blackboard, config)
                decision.apply_cursor_verify_feedback(executor, world)
                now = time.perf_counter()
                dt = now - last_tick_t
                last_tick_t = now
                last_tick_ms = round((now - tick_t0) * 1000.0, 1)
                last_fps = round((1.0 / dt) if dt > 0 else 0.0, 1)
                from app._04_decision.astar_trace import take_tick
                from app._04_decision.decide_spans import take_tick as take_decide

                last_astar = take_tick()
                last_decide = take_decide()
                try:
                    from app._03_world.debug.preview import freeze_preview_tick, settle_tick_parts

                    tick_parts = settle_tick_parts(
                        [
                            ("perception", (t_entities - tick_t0) * 1000.0),
                            ("memory read", (t_hotbar - t_entities) * 1000.0),
                            ("decision", (t_decide - t_hotbar) * 1000.0),
                            ("act", (t_act - t_decide) * 1000.0),
                            ("other", (now - t_act) * 1000.0),
                        ],
                        last_tick_ms,
                    )
                    self._publish_preview_tick(
                        freeze_preview_tick(
                            action,
                            world,
                            decision.blackboard,
                            last_tick_ms,
                            tick_parts,
                        )
                    )
                except Exception:
                    pass
                publish("tick")
        finally:
            with self._debug_lock:
                if self._routine_clock_gen == routine_clock_gen:
                    self._routine_clock = None
                if party_brain is not None:
                    # Keep last decisions visible after stop; mark session ended.
                    ended = dict(self._party_monitor) if self._party_monitor else {}
                    ended["enabled"] = True
                    ended["note"] = "stopped"
                    ended["updated_at"] = time.time()
                    ended["worker_alive"] = False
                    self._party_monitor = ended
            self._stop_vision_preview()

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
            from session.input_release import restore_desktop_input

            restore_desktop_input()
        except Exception:
            pass
        try:
            clear_shared_sensors()
        except Exception:
            try:
                sensors.close()
            except Exception:
                pass
        try:
            close = getattr(capture, "close", None) or getattr(capture, "stop", None)
            if callable(close):
                close()
        except Exception:
            pass
        self._action_executor = None
