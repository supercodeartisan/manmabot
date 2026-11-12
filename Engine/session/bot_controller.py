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
    as_of = time.monotonic()
    elapsed_fn = getattr(cursor, "elapsed", None)
    ticking_fn = getattr(cursor, "ticking", None)
    try:
        elapsed_s = float(elapsed_fn(as_of)) if callable(elapsed_fn) else 0.0
    except (TypeError, ValueError):
        elapsed_s = 0.0
    try:
        ticking = bool(ticking_fn()) if callable(ticking_fn) else False
    except (TypeError, ValueError):
        ticking = False
    active = entries[index % len(entries)] if entries else None
    kind = ""
    if isinstance(active, dict):
        kind = str(active.get("kind") or "").strip().lower()
    if not kind:
        kind = str(scratch.get("routine_kind") or "").strip().lower()
    from app._04_decision.world_nav.routine import routine_hunt_zone_inside

    # "Moving" is the walk before the hunt zone. Inside the zone the
    # countdown runs even while world nav is still walking to the center.
    navigating = kind != "break" and not routine_hunt_zone_inside(blackboard)
    return {
        "index": index % len(ids),
        "elapsed_s": elapsed_s,
        "as_of": as_of,
        "ticking": ticking,
        "ids": ids,
        "durations_s": durations_s,
        "navigating": navigating,
        "kind": kind,
    }


def _farm_clock_from_board(blackboard) -> dict | None:
    """Copy the hunt-area stay clock. Does not change the tour."""
    try:
        from app._04_decision import farm_time
        from app._04_decision.farm_time import farm_elapsed_seconds
        from app._04_decision.nav_config import get_farm_areas
    except Exception:
        return None
    farms = list(get_farm_areas() or [])
    names: list[str] = []
    limits: list[float] = []
    default_limit = float(farm_time.FARM_DURATION_LIMIT)
    per_farm = list(farm_time.FARM_DURATION_LIMITS or [])
    for i, farm in enumerate(farms):
        names.append(str(getattr(farm, "name", "") or ""))
        if 0 <= i < len(per_farm):
            limits.append(float(per_farm[i]))
        else:
            limits.append(default_limit)
    try:
        index = int(getattr(blackboard, "farm_area_index", 0) or 0)
    except (TypeError, ValueError):
        index = 0
    if names:
        index = index % len(names)
    scratch = getattr(blackboard, "scratch", None)
    session = scratch.get("world_nav_session") if isinstance(scratch, dict) else None
    purpose = str(getattr(blackboard, "travel_purpose", "") or "")
    inside = False
    try:
        from app._04_decision.farm_time import clock_farm, inside_farm_stay

        inside = bool(inside_farm_stay(blackboard))
        dest = clock_farm(blackboard)
    except Exception:
        inside = False
        dest = None
    dest_name = str(getattr(dest, "name", "") or "")
    if dest_name:
        if dest_name in names:
            index = names.index(dest_name)
        else:
            names.append(dest_name)
            limits.append(float(farm_time.active_farm_duration_limit(blackboard)))
            index = len(names) - 1
    if not names:
        return None
    kind = str(scratch.get("routine_kind") or "") if isinstance(scratch, dict) else ""
    on_trip = (
        kind != "break"
        and (session is not None or purpose in ("next_farm", "enter_farm"))
    )
    # Crossing the destination rectangle starts the countdown. "Moving"
    # stays only while that trip is still outside the rect.
    navigating = on_trip and not inside
    try:
        elapsed = float(farm_elapsed_seconds(blackboard))
    except Exception:
        elapsed = 0.0
    try:
        from app._04_decision.farm_time import farm_clock_ticking

        ticking = bool(farm_clock_ticking(blackboard))
    except Exception:
        ticking = False
    return {
        "index": index,
        "names": names,
        "limits_s": limits,
        "elapsed_s": elapsed,
        "as_of": time.monotonic(),
        "ticking": ticking,
        "navigating": navigating,
    }


def _freeze_stay_clocks(blackboard) -> None:
    """Stop the routine row and the hunt-area stay. Pause time is not counted."""
    scratch = getattr(blackboard, "scratch", None)
    cursor = scratch.get("routine_cursor") if isinstance(scratch, dict) else None
    freeze = getattr(cursor, "freeze", None)
    if callable(freeze):
        freeze()
    from app._04_decision.farm_time import freeze_farm_clock

    freeze_farm_clock(blackboard)


def _resume_stay_clocks(blackboard) -> None:
    """Continue the farm-area stay. The routine row opens only inside its zone.

    Resuming the row clock here would count the walk. ``sample_routine_zone_clock``
    opens it on the next decide when the character is inside. A dungeon hold
    stays closed until the hunt floor releases it.
    """
    from app._04_decision.farm_time import resume_farm_clock

    resume_farm_clock(blackboard)


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
        self._farm_clock: dict | None = None
        self._farm_clock_gen = 0
        self._preview_watchers = 0
        # Schedule Start may begin while the console still owns focus.
        # Later focus loss still pauses; see auto_pause_tick.
        self._unattended = False
        # Paused "update schedule" bumps the epoch. The worker applies it
        # before the next decision tick. Start resets both counters.
        self._settings_epoch = 0
        self._settings_applied = 0
        self._route_identity: tuple | None = None
        # Party WebSocket I/O (leader server / member client). Session mirrors
        # handles onto ``_party_ws`` / ``_party_client`` for the monitor UI.
        from app._06_party.comms import PartyComms

        self._party_comms = PartyComms()
        self._party_ws = None
        self._party_ws_owned = False
        self._party_client = None
        self._party_heartbeat = None
        self._party_farm_started = False
        self._party_wait_log_at = 0.0
        self._party_policy_key = ""
        self._party_policy_at = 0.0
        self._party_policy_id = ""
        self._party_leader_name = ""
        self._member_policy_sig = ""
        self._invite_accepter = None
        from app._06_party.chat_queue import PartyChatQueue

        self._party_chat = PartyChatQueue()
        self._member_state_reporter = None
        # Monitor-only records (read by ``party_monitor_snapshot``).
        self._party_invites = None
        self._party_start_error = ""
        self._party_start_wait: dict = {}
        self._party_socket_wait_note_at = 0.0
        self._party_turret_info: dict = {}
        self._party_line_info: dict = {}
        self._formation_hold = False
        self._formation_reform = False
        self._reform_published = False
        self._formation_anchor = None
        self._party_line_watch = None
        self._party_slot_formation = None
        self._party_line_map: Optional[int] = None
        self._party_near_hold = False
        self._party_policy_info: dict = {}
        self._member_policy_info: dict = {}
        self._party_brain_ref = None
        self._party_leader_ref = None
        self._party_client_id = ""

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
            "elapsed_s": float(clock.get("elapsed_s") or 0.0),
            "as_of": float(clock.get("as_of") or 0.0),
            "ticking": bool(clock.get("ticking")),
            "ids": list(clock["ids"]),
            "durations_s": list(clock["durations_s"]),
            "navigating": bool(clock["navigating"]),
            "kind": str(clock.get("kind") or ""),
        }

    def farm_clock(self) -> dict | None:
        """Live hunt-area index and stay clock. None when the worker is stopped."""
        if self.state == RunState.STOPPED:
            return None
        with self._debug_lock:
            clock = self._farm_clock
        if not clock:
            return None
        return {
            "index": int(clock["index"]),
            "names": list(clock["names"]),
            "limits_s": list(clock["limits_s"]),
            "elapsed_s": float(clock["elapsed_s"]),
            "as_of": float(clock.get("as_of") or 0.0),
            "ticking": bool(clock.get("ticking")),
            "navigating": bool(clock["navigating"]),
        }

    def _note_routine_clock(self, blackboard, gen: int) -> None:
        clock = _routine_clock_from_board(blackboard)
        with self._debug_lock:
            if self._routine_clock_gen != gen:
                return
            self._routine_clock = clock

    def _note_farm_clock(self, blackboard, gen: int) -> None:
        clock = _farm_clock_from_board(blackboard)
        with self._debug_lock:
            if self._farm_clock_gen != gen:
                return
            self._farm_clock = clock

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

    def _party_socket_snapshot(self) -> dict:
        """Live WebSocket link status for the party monitor banner."""
        profile = self._profile
        role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        if role not in ("member", "leader"):
            role = "member"
        party_on = bool(
            getattr(
                profile,
                "party_enabled",
                getattr(profile, "party_member_enabled", False),
            )
        )
        try:
            port = int(getattr(profile, "party_ws_port", 8765) or 8765)
        except (TypeError, ValueError):
            port = 8765
        port = max(1, min(65535, port))
        host = str(getattr(profile, "party_leader_host", "") or "").strip()
        out: dict = {
            "role": "none",
            "party_on": party_on,
            "profile_role": role,
            "port": port,
            "host": host,
            "listening": False,
            "connected": False,
            "running": False,
            "clients": 0,
            "client_ids": [],
            "uri": "",
            "advertise": "",
            "error": "",
            "state": "off",
        }
        if not party_on:
            out["state"] = "off"
            return out
        # Leader server (watchdog wraps PartyServer).
        watchdog = self._party_ws
        if watchdog is not None and role == "leader":
            try:
                st = watchdog.status() if hasattr(watchdog, "status") else {}
            except Exception as exc:
                st = {"last_error": str(exc)}
            try:
                from websocket.netinfo import local_ipv4

                advertise = local_ipv4()
            except Exception:
                advertise = "127.0.0.1"
            listening = bool(st.get("listening"))
            running = bool(st.get("running") or st.get("watchdog_running"))
            err = str(st.get("last_error") or st.get("watchdog_error") or "")
            out.update(
                {
                    "role": "server",
                    "listening": listening,
                    "running": running,
                    "bind_host": str(st.get("host") or "0.0.0.0"),
                    "port": int(st.get("port") or port),
                    "clients": int(st.get("clients") or 0),
                    "client_ids": list(st.get("client_ids") or []),
                    "advertise": advertise,
                    "uri": f"ws://{advertise}:{int(st.get('port') or port)}/",
                    "error": err,
                    "state": (
                        "listening"
                        if listening
                        else ("starting" if running else "down")
                    ),
                }
            )
            return out
        # Member client.
        client = self._party_client
        if client is not None and role == "member":
            try:
                st = client.status() if hasattr(client, "status") else {}
            except Exception as exc:
                st = {"last_error": str(exc)}
            connected = bool(st.get("connected"))
            running = bool(st.get("running"))
            uri = str(st.get("uri") or (f"ws://{host}:{port}/" if host else ""))
            err = str(st.get("last_error") or "")
            watch = self._party_comms.member_link_info()
            if connected:
                state = "connected"
            elif not running:
                state = "down"
            elif watch["drops"] > 0:
                state = "reconnecting"
            else:
                state = "connecting"
            out.update(
                {
                    "role": "client",
                    "connected": connected,
                    "running": running,
                    "uri": uri,
                    "host": host,
                    "port": port,
                    "error": err,
                    "state": state,
                    "drops": watch["drops"],
                    "restarts": watch["restarts"],
                    "down_s": watch["down_s"],
                }
            )
            return out
        # Party on but socket not started yet (bot Stopped / still arming).
        if role == "leader":
            try:
                from websocket.netinfo import local_ipv4

                advertise = local_ipv4()
            except Exception:
                advertise = "127.0.0.1"
            out.update(
                {
                    "role": "server",
                    "advertise": advertise,
                    "uri": f"ws://{advertise}:{port}/",
                    "state": "idle",
                    "error": "Start the bot to listen",
                }
            )
        else:
            uri = f"ws://{host}:{port}/" if host else ""
            out.update(
                {
                    "role": "client",
                    "uri": uri,
                    "state": "idle",
                    "error": (
                        "Start the bot to connect"
                        if host
                        else "Set leader LAN IP on the Party tab"
                    ),
                }
            )
        return out

    def party_monitor_snapshot(self) -> dict:
        """Party monitor payload: live DLL party + socket message log."""
        with self._debug_lock:
            snap = dict(self._party_monitor) if self._party_monitor else {}
        try:
            from websocket.traffic_log import snapshot as party_messages

            snap["messages"] = party_messages()
        except Exception:
            snap.setdefault("messages", [])
        try:
            from websocket.party_orders import member_orders

            snap["party_buffs"] = [
                dict(row)
                for row in (getattr(member_orders, "party_buffs", None) or [])
                if isinstance(row, dict)
            ]
        except Exception:
            snap["party_buffs"] = []
        try:
            snap["socket"] = self._party_socket_snapshot()
        except Exception as exc:
            snap["socket"] = {"role": "none", "state": "error", "error": str(exc)}
        try:
            snap["chat_action"] = self._party_chat.snapshot()
        except Exception:
            snap["chat_action"] = {}
        snap.setdefault("bot_state", self.state.value)
        snap.setdefault("bot_reason", self.reason)
        snap["start_error"] = str(getattr(self, "_party_start_error", "") or "")
        wait = dict(getattr(self, "_party_start_wait", None) or {})
        if wait.get("since"):
            wait["waited_s"] = round(max(0.0, time.time() - float(wait["since"])), 1)
        snap["start_wait"] = wait
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
        try:
            snap["session"] = self._party_session_snapshot(snap)
        except Exception as exc:
            snap["session"] = {"role": "unknown", "error": str(exc)}
        return snap

    def _party_session_snapshot(self, snap: dict) -> dict:
        """Role-specific party state for the monitor (read-only)."""
        profile = self._profile
        party_on = bool(snap.get("profile_party_enabled"))
        role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        if not party_on:
            role = "solo"
        out: dict = {"role": role, "now": time.time()}
        party_raw = snap.get("party") if isinstance(snap.get("party"), dict) else None
        party = party_raw or {}
        in_party_names = {
            str(m.get("name") or "").strip().casefold()
            for m in (party.get("members") or [])
            if isinstance(m, dict)
        }
        if role == "leader":
            from settings.profile import normalize_party_roster
            from app._06_party.comms.orders import rally

            roster = normalize_party_roster(getattr(profile, "party_roster", None))
            start = getattr(self, "_start_rally", None)
            arrived = {str(n).casefold() for n in rally.arrived}
            expected = sorted(getattr(start, "expected", set()) or set())
            wait_started = getattr(start, "_wait_started", None)
            out["rally"] = {
                "state": str(getattr(start, "state", "off") or "off"),
                "stage": rally.stage,
                "armed": rally.armed,
                "expected": expected,
                "arrived": sorted(rally.arrived),
                "missing": rally.missing(set(expected)) if expected else [],
                "wait_s": (
                    round(time.monotonic() - float(wait_started), 1)
                    if wait_started is not None
                    else None
                ),
            }
            invites = getattr(self, "_party_invites", None)
            invite = dict(getattr(invites, "info", None) or {})
            inviter = getattr(invites, "inviter", None)
            rstate = str(getattr(start, "state", "off") or "off")
            if inviter is not None and inviter.active:
                phase = "forming"
            elif rstate in ("await_mark", "await_plan", "hold_at", "waiting"):
                phase = "rally"
            elif inviter is not None or rstate == "done":
                phase = "hunting"
            else:
                phase = "off"
            remaining = (
                inviter.remaining_s()
                if inviter is not None
                else (start.remaining_s() if start is not None else None)
            )
            left_behind = {
                str(n).casefold() for n in (getattr(start, "left_behind", None) or [])
            }
            invite_rows = {
                str(r.get("name") or "").casefold(): r
                for r in (invite.get("rows") or [])
                if isinstance(r, dict)
            }
            out["phase"] = {
                "name": phase,
                "remaining_s": round(remaining, 1) if remaining is not None else None,
                "start_wait_s": invite.get("start_wait_s"),
                "late": list(invite.get("late") or []),
                "not_arrived": list(getattr(start, "left_behind", None) or []),
            }

            def _member_state(key, joined, at, irow, fresh, acked, mphase) -> str:
                if joined and at:
                    return "ready"
                if joined and key in left_behind:
                    return "not_arrived"
                if joined:
                    return "following" if phase == "hunting" else "joined"
                if not fresh:
                    return "late_offline" if irow.get("late") else "offline"
                if not acked:
                    return "policy_wait"
                if mphase in ("popup", "pressed"):
                    return "accepting"
                if irow.get("late"):
                    return "late"
                return "inviting"

            from app._06_party.comms.orders import policy_acks
            from app._06_party.sync import invite_accepts, member_states, reported_joined
            from app._06_party.workflow import roster_member_steps

            pid = str(getattr(self, "_party_policy_id", "") or "")
            out["party_mem"] = "ok" if party_raw is not None else "blind"
            leader_known = party_raw is not None and party.get("subs_ok") is not False
            out["roster"] = []
            for row in roster:
                key = row["name"].casefold()
                irow = invite_rows.get(key) or {}
                mstate = member_states.row(row["name"])
                iacc = invite_accepts.row(row["name"])
                if leader_known and key in in_party_names:
                    joined, joined_src = True, "leader memory"
                elif not leader_known and reported_joined(row["name"], self._party_leader_name):
                    joined, joined_src = True, "member memory"
                elif not leader_known and irow.get("joined"):
                    joined, joined_src = True, "seen joined"
                else:
                    joined, joined_src = False, ""
                at = key in arrived
                ack = policy_acks.row(row["name"])
                mparty = mstate.get("party") or {}
                minv = mstate.get("invite") or {}
                fresh = bool(mstate.get("fresh"))
                acked = policy_acks.acked(row["name"], pid or None)
                out["roster"].append(
                    {
                        "name": row["name"],
                        "role": row.get("role", "mage"),
                        "loot": row.get("loot", "none"),
                        "in_party": joined,
                        "in_party_src": joined_src,
                        "state_fresh": fresh,
                        "awaiting_fresh": bool(mstate.get("awaiting_fresh")),
                        "state_age_s": mstate.get("age_s"),
                        "state_frames": int(mstate.get("frames") or 0),
                        "live": dict(mstate.get("live") or {}),
                        "late": bool(irow.get("late")),
                        "left": int(irow.get("left") or 0),
                        "leaving_s": irow.get("leaving_s"),
                        "state_mem": str(mparty.get("mem") or ""),
                        "state_in_party": mparty.get("in_party"),
                        "state_invite": f"{minv.get('id') or '—'}:{minv.get('phase') or 'idle'}",
                        "invite_hold": str(irow.get("hold") or ""),
                        "invite_accepted": bool(iacc),
                        "invite_accept_id": str(iacc.get("accept_id") or ""),
                        "invite_accept_at": iacc.get("at"),
                        "at_rally": at,
                        "policy_acked": acked,
                        "ack_at": ack.get("at"),
                        "invites": int(irow.get("invites") or 0),
                        "invite_failed": int(irow.get("failed") or 0),
                        "invite_ago_s": irow.get("last_ago_s"),
                        "state": _member_state(
                            key, joined, at, irow, fresh, acked,
                            str(minv.get("phase") or ""),
                        ),
                    }
                )
                out["roster"][-1]["steps"] = roster_member_steps(
                    out["roster"][-1], phase=phase
                )
            out["unnamed_member"] = member_states.unnamed_recent()
            from app._06_party.member_discovery import discovery

            out["discovery"] = discovery.snapshot(roster)
            out["invite"] = invite
            out["policy"] = dict(getattr(self, "_party_policy_info", {}) or {})
            from app._06_party.workflow import leader_workflow

            out["workflow"] = leader_workflow(
                sock=snap.get("socket") if isinstance(snap.get("socket"), dict) else {},
                roster=out["roster"],
                policy=out["policy"],
                invite=invite,
                rally=out["rally"],
                phase=phase,
                now=out["now"],
                party_mem=out["party_mem"],
            )
            out["turret"] = dict(getattr(self, "_party_turret_info", {}) or {})
            out["line_wait"] = dict(getattr(self, "_party_line_info", {}) or {})
            brain = getattr(self, "_party_leader_ref", None)
            live_mode = str(getattr(brain, "hunt_mode", "moving") or "moving")
            if live_mode not in ("turret", "moving"):
                live_mode = "moving"
            out["settings"] = {
                "leader_mode": live_mode,
                "lag_tiles": int(getattr(profile, "party_lag_tiles", 30) or 30),
                "random_loot": bool(getattr(profile, "party_random_loot", False)),
            }
        elif role == "member":
            from app._06_party.comms.orders import member_orders

            brain = getattr(self, "_party_brain_ref", None)
            cfg = getattr(brain, "config", None)
            base = getattr(brain, "base_config", None)
            gather = member_orders.gather or {}
            out["policy"] = dict(getattr(self, "_member_policy_info", {}) or {})
            out["policy"]["received"] = member_orders.policy is not None
            out["policy"]["overlay"] = bool(
                brain is not None and getattr(brain, "leader_policy", None) is not None
            )
            if cfg is not None:
                out["effective"] = {
                    "leader_mode": cfg.leader_mode,
                    "farm_mode": cfg.farm_mode,
                    "seat_role": cfg.seat_role,
                    "loot_role": cfg.loot_role,
                    "random_loot": cfg.random_loot,
                    "follow_tiles": cfg.follow_tiles,
                    "stop_tiles": cfg.stop_tiles,
                    "assist_leash_tiles": cfg.assist_leash_tiles,
                }
            if base is not None:
                out["own"] = {
                    "farm_mode": base.farm_mode,
                    "follow_tiles": base.follow_tiles,
                    "stop_tiles": base.stop_tiles,
                }
            out["orders"] = {
                "gather_stage": str(gather.get("stage") or ""),
                "gather_map": gather.get("map_id"),
                "gather_xy": (
                    [gather.get("x"), gather.get("y")] if gather else None
                ),
                "arrived": bool(member_orders.arrived),
                "recovery": member_orders.recovery is not None,
            }
            from app._06_party.workflow import member_workflow

            accepter = getattr(self, "_invite_accepter", None)
            out["accept"] = accepter.status() if accepter is not None else {}
            reporter = getattr(self, "_member_state_reporter", None)
            out["sync"] = reporter.status() if reporter is not None else {}
            out["workflow"] = member_workflow(
                sock=snap.get("socket") if isinstance(snap.get("socket"), dict) else {},
                policy=out["policy"],
                party=party_raw,
                orders=out["orders"],
                accept=out["accept"],
                now=out["now"],
                sync=out["sync"],
            )
        return out

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
                    "name": _player_chat_name(world, party),
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

    def _sync_party_handles(self) -> None:
        """Mirror ``PartyComms`` handles for the monitor / legacy readers."""
        comms = getattr(self, "_party_comms", None)
        if comms is None:
            self._party_ws = None
            self._party_ws_owned = False
            self._party_client = None
            self._party_heartbeat = None
            return
        self._party_ws = comms.watchdog
        self._party_ws_owned = bool(comms.leader_owned)
        self._party_client = comms.client
        self._party_heartbeat = comms.heartbeat

    def _start_party_socket(self) -> None:
        """Listen while this worker runs, when Party is enabled as leader.

        An empty roster still listens: members can hello and sit in discovery
        until they match a saved name (invite/rally stay off).
        """
        if not self._party_server_on():
            return
        profile = self._profile
        self._ensure_party_log(role="leader")

        def _log(msg: str) -> None:
            self.log(msg)
            self._party_event(
                "socket" if msg.startswith("Party socket") else "setup", msg
            )

        self._party_comms.start_leader(
            port=getattr(profile, "party_ws_port", 8765),
            log=_log,
        )
        self._sync_party_handles()
        from settings.profile import normalize_party_roster

        roster = [
            str(row.get("name") or "").strip()
            for row in normalize_party_roster(
                getattr(profile, "party_roster", None)
            )
        ]
        roster = [n for n in roster if n]
        if roster:
            _log(
                "Party roster: "
                + ", ".join(roster)
                + " — /초대 after the game world is ready (not the WS local test)."
            )
        else:
            _log(
                "Party roster empty — server listening, waiting for member hello"
            )

    def _stop_party_socket(self) -> None:
        self._party_comms.stop_leader(log=self.log)
        self._sync_party_handles()

    # Log line cadence while a member waits for the leader socket.
    MEMBER_WAIT_NOTE_S = 30.0

    def _party_enabled(self) -> bool:
        """Master Party-tab switch. Role leftovers must not bypass this."""
        return bool(getattr(self._profile, "party_enabled", False))

    def _leader_roster_ready(self) -> bool:
        """Leader party needs at least one named seat."""
        from settings.profile import normalize_party_roster

        rows = normalize_party_roster(getattr(self._profile, "party_roster", None))
        return any(str(row.get("name") or "").strip() for row in rows)

    def _party_server_on(self) -> bool:
        """Listen for member sockets. Roster may still be empty."""
        if not self._party_enabled():
            return False
        role = str(
            getattr(self._profile, "party_role", "member") or "member"
        ).strip().lower()
        return role == "leader"

    def _party_leader_on(self) -> bool:
        """Invite / rally / turret: leader server plus at least one approved name."""
        return self._party_server_on() and self._leader_roster_ready()

    def _leader_turret_on(self) -> bool:
        """True while this leader stands on a party-map point."""
        if not self._party_leader_on():
            return False
        brain = getattr(self, "_party_leader_ref", None)
        return str(getattr(brain, "hunt_mode", "moving") or "moving") == "turret"

    def _party_socket_note(self, msg: str) -> None:
        self.log(msg)
        self._party_event("socket", msg)

    def _start_party_client(self) -> bool:
        """Member bot connects to the leader. Returns False when party is on but unreachable."""
        profile = self._profile
        role = str(getattr(profile, "party_role", "member") or "member").strip().lower()
        party_on = bool(
            getattr(
                profile,
                "party_enabled",
                getattr(profile, "party_member_enabled", False),
            )
        )
        member_on = bool(getattr(profile, "party_member_enabled", False))
        self._party_start_error = ""
        if role != "member" or not party_on or not member_on:
            return True
        host = str(getattr(profile, "party_leader_host", "") or "").strip()
        port = getattr(profile, "party_ws_port", 8765)
        self._party_comms.start_member(host=host, port=port, log=self.log)
        self._sync_party_handles()
        if self._party_comms.client is None:
            self.log(
                "Party member: no leader socket — follow and combat use party memory only"
            )
            return True
        # The socket carries policy and rally. Follow and combat read party memory
        # whether or not this connect ever succeeds.
        self._party_start_wait = {"since": time.time(), "uri": f"{host}:{port}"}
        self._party_socket_wait_note_at = 0.0
        self.log(
            f"Party member: leader socket {host}:{port} connecting in the background. "
            "Follow and combat use party memory."
        )
        return True

    def _stop_party_client(self) -> None:
        self._party_start_wait = {}
        self._party_socket_wait_note_at = 0.0
        self._party_comms.stop_member(log=self.log)
        self._sync_party_handles()

    def _member_socket_pending(self) -> bool:
        """True until the first leader-socket connect.

        Follow and combat do not wait on this. A drop keeps the last policy.
        No leader IP leaves this false and the member runs on party memory only.
        """
        wait = getattr(self, "_party_start_wait", None) or {}
        if not wait.get("since"):
            return False
        uri = str(wait.get("uri") or "")
        if self._party_comms.member_connected:
            since = float(wait.get("since") or 0.0)
            waited = max(0.0, time.time() - since) if since else 0.0
            self._party_start_wait = {}
            self._party_socket_wait_note_at = 0.0
            self.log(
                f"Party member: connected to leader {uri} after {waited:.0f}s"
            )
            self._party_event("socket", f"connected {uri}")
            return False
        self._party_comms.watch_member(log=self._party_socket_note)
        self._sync_party_handles()
        now = time.monotonic()
        last = float(getattr(self, "_party_socket_wait_note_at", 0.0) or 0.0)
        if last <= 0.0:
            self._party_socket_wait_note_at = now
        elif now - last >= float(self.MEMBER_WAIT_NOTE_S):
            self._party_socket_wait_note_at = now
            since = float(wait.get("since") or 0.0)
            waited = max(0.0, time.time() - since) if since else 0.0
            self.log(
                f"Party member: leader socket {uri} still down ({waited:.0f}s) — "
                "follow and combat stay on party memory"
            )
        return True

    def _install_party_nav_hooks(self) -> None:
        """Leader only: the start rally reads the first hunt route and holds on it."""
        if not self._party_leader_on():
            return
        from app._04_decision.world_nav.session import WorldNavHooks
        from app._06_party.comms.orders import rally
        from app._06_party.leader_rally import LeaderStartRally

        def _note(msg: str) -> None:
            self.log(msg)
            self._party_event("session", msg)

        self._start_rally = LeaderStartRally(rally, log=_note)
        WorldNavHooks.on_plan = self._start_rally.on_plan
        WorldNavHooks.should_hold = self._start_rally.should_hold

    def _clear_party_nav_hooks(self) -> None:
        from app._04_decision.world_nav.session import WorldNavHooks
        from app._06_party.comms.orders import reset_orders

        WorldNavHooks.on_plan = None
        WorldNavHooks.should_hold = None
        self._start_rally = None
        reset_orders()
        self._party_tree_trip = ""

    def _ensure_party_log(self, *, role: str = "", level: str = "INFO") -> None:
        """Open ``party-*.log`` once party is known to be on (after profile apply)."""
        try:
            from app._06_party import party_log
            from session.paths import manmabot_root

            if party_log.active():
                return
            profile = self._profile
            party_on = bool(
                getattr(
                    profile,
                    "party_enabled",
                    getattr(profile, "party_member_enabled", False),
                )
            )
            if not party_on:
                return
            role_txt = str(role or getattr(profile, "party_role", "") or "").strip()
            if role_txt.lower() == "leader" and not self._leader_roster_ready():
                return
            path = party_log.configure(
                log_dir=manmabot_root() / "logs",
                level=str(level or "INFO"),
                role=role_txt,
            )
            self.log(f"Party log {path}")
        except Exception as exc:
            self.log(f"Party log open failed: {exc}")

    def _run_leader_party_setup(self, world) -> None:
        """Once after Start: policy first, leave if needed, then arm the inviter.

        Invites themselves go out from ``_leader_invite_tick`` (one line per tick).
        """
        self._party_invites = None
        if not self._party_leader_on():
            return
        profile = self._profile
        self._ensure_party_log(role="leader")
        from settings.profile import normalize_party_roster
        from app._06_party.invite import LeaderInvites

        rows = normalize_party_roster(getattr(profile, "party_roster", None))
        names = [str(row.get("name") or "").strip() for row in rows]
        if not any(names):
            self.log("Party roster empty — party not started")
            return
        snap = None
        try:
            from session.party_probe import probe_party_live

            probed = probe_party_live().get("party")
            if isinstance(probed, dict) and probed.get("subs_ok") is not False:
                snap = probed
        except Exception:
            snap = None
        if snap is None:
            from app._06_party.invite import action_party_snapshot

            snap = action_party_snapshot(world)
        self_name = _player_chat_name(world, snap)

        def _setup_log(msg: str) -> None:
            self.log(msg)
            self._party_event("setup", msg)

        server = self._party_comms.server

        def _ws_clients() -> int:
            return int(server.client_count()) if server is not None else 0

        from app._06_party.sync import InviteHold, member_states, reported_joined

        self._party_leader_name = self_name
        invites = LeaderInvites(
            publish_policy=lambda: self._publish_party_policy(force=True),
            ws_clients=_ws_clients,
            policy_acked=self._leader_policy_acked,
            hold=InviteHold(member_states),
            reported_joined=lambda name: reported_joined(name, self_name),
            reported_out=lambda name: member_states.out_of_party(name, self_name),
            wait=self._stop_event.wait,
            log=_setup_log,
            on_beep=lambda: self._send_leader_beep("already_in_party"),
        )
        self._party_invites = invites
        invites.start(names, snapshot=snap, self_name=self_name)

    def _send_leader_beep(self, why: str = "already_in_party") -> int:
        """Broadcast a socket test beep. 0 = no member connected yet."""
        try:
            sent = int(self._party_comms.publish_beep(why=why) or 0)
        except Exception as exc:
            self.log(f"Party beep failed: {exc}")
            return 0
        if sent:
            msg = f"Party beep → {sent} member(s) ({why})"
            self.log(msg)
            self._party_event("socket", msg)
        return sent

    def submit_party_chat(self, kind: str, name: str = "") -> str:
        """Queue one monitor Invite or Y+Enter for the game worker.

        The worker runs it on the same path as automatic party chat. A paused
        or minimized worker keeps the job until it is acting again.
        """
        kind_s = str(kind or "").strip().lower()
        if kind_s not in ("invite", "accept"):
            return "rejected: unknown party action"
        if kind_s == "invite" and not str(name or "").strip():
            return "Enter a character name"
        if self.state != RunState.RUNNING or not (
            self._thread is not None and self._thread.is_alive()
        ):
            return "rejected: bot is not running"
        self._party_chat.submit(kind_s, name)
        if not self._pause_gate.is_set():
            text = "queued: bot is paused — runs when the worker resumes"
            self._party_chat.note(text, state="queued")
            return text
        return "queued"

    def _drain_party_chat(self) -> str:
        """Run at most one queued manual party action. Returns its kind, or ""."""
        job = self._party_chat.pop()
        if job is None:
            return ""
        try:
            from session.probes import bring_game_to_front, probe_game

            hwnd = int(getattr(probe_game(), "hwnd", 0) or 0)
            if hwnd:
                bring_game_to_front(hwnd)
            if job.kind == "invite":
                from app._06_party.invite import deliver_chat, invite_command

                line = invite_command(job.name)
                ok = deliver_chat(line, log=self.log)
                invites = getattr(self, "_party_invites", None)
                if invites is not None:
                    invites.note_manual_invite(job.name, ok=ok)
                text = f"manual {line}" if ok else f"manual {line} failed"
            elif job.kind == "accept":
                from app._06_party.accept import type_accept_key

                err = type_accept_key()
                ok = not err
                text = "manual Y+Enter" if ok else f"manual Y+Enter failed: {err}"
                if ok:
                    from app._06_party import accept as accept_mod

                    note = str(getattr(accept_mod, "_last_y_note", "") or "")
                    if note:
                        text += note
            else:
                ok = False
                text = f"rejected: unknown party action {job.kind}"
        except Exception as exc:
            ok = False
            text = f"manual party action failed: {exc}"
        self._party_chat.finish(job, text, ok=ok)
        self.log(text)
        self._party_event("chat", text)
        return job.kind if ok or job.kind in ("invite", "accept") else ""

    def _leader_invite_tick(self, world, last_action, *, hold_chat: bool = False) -> None:
        """One invite step per tick while the party window is open."""
        if not self._party_leader_on():
            return
        invites = getattr(self, "_party_invites", None)
        if invites is not None:
            from app._06_party.invite import action_party_snapshot

            invites.tick(
                action_party_snapshot(world),
                last_action,
                hold_chat=hold_chat,
            )

    def _log_party_until_farm(
        self,
        *,
        party_role: str,
        party_brain,
        world,
        action,
    ) -> None:
        """Repeat wait reasons until follow/farm actually starts."""
        if self._party_farm_started:
            return
        if not bool(getattr(self._profile, "party_enabled", False)):
            return
        kind = ""
        reason = ""
        leader_name = ""
        dist = None
        if party_brain is not None:
            kind = str(getattr(party_brain.runtime, "last_kind", "") or "")
            reason = str(getattr(party_brain.runtime, "last_reason", "") or "")
            leader_name = str(
                getattr(party_brain.runtime, "leader_name_seen", "") or ""
            )
            dist = getattr(party_brain.runtime, "leader_dist", None)
        elif action is not None:
            raw = getattr(action, "action", None)
            kind = str(getattr(raw, "value", None) or raw or "")
            reason = str(getattr(action, "reason", "") or "")

        farmed = False
        if party_role == "member" and party_brain is not None:
            farmed = kind in (
                "follow",
                "assist",
                "hold",
                "defend",
            ) and (leader_name or dist is not None)
        elif party_role == "leader":
            farmed = bool(kind) and kind not in ("", "idle")

        if farmed:
            self._party_farm_started = True
            msg = (
                f"Party farm start kind={kind or '—'} "
                f"leader={leader_name or '—'} dist={dist}"
            )
            self.log(msg)
            try:
                from app._06_party.party_log import event as party_event

                party_event("session", "%s", msg)
            except Exception:
                pass
            return

        now = time.monotonic()
        if now - float(self._party_wait_log_at or 0.0) < 2.5:
            return
        self._party_wait_log_at = now
        party = getattr(world, "last_party", None) if world is not None else None
        in_party = bool(isinstance(party, dict) and party.get("in_party"))
        count = party.get("count") if isinstance(party, dict) else None
        mem_lead = ""
        xy = ""
        pmap = ""
        if isinstance(party, dict):
            block = party.get("leader")
            if isinstance(block, dict):
                mem_lead = str(block.get("name") or "").strip()
                try:
                    xy = f"{int(block.get('x'))},{int(block.get('y'))}"
                except (TypeError, ValueError):
                    xy = ""
                try:
                    pmap = str(int(block.get("map_id")))
                except (TypeError, ValueError):
                    pmap = ""
            mem_lead = mem_lead or str(party.get("leader_name") or "").strip()
        ws = ""
        try:
            sock = self._party_socket_snapshot()
            ws = str(sock.get("state") or "")
        except Exception:
            ws = ""
        mem = f"in_party={in_party} count={count}" if isinstance(party, dict) else "party_mem=blind"
        msg = (
            "Party wait: "
            f"role={party_role} {mem} "
            f"mem_leader={mem_lead or '—'} xy={xy or '—'} map={pmap or '—'} "
            f"seen={leader_name or '—'} dist={dist} kind={kind or '—'} "
            f"reason={reason or '—'} ws={ws or '—'}"
        )
        self.log(msg)
        try:
            from app._06_party.party_log import event as party_event

            party_event("session", "%s", msg)
        except Exception:
            pass

    def _leader_party_policy_kwargs(self) -> dict:
        """Global farm/loot knobs from the leader profile + roster."""
        from settings.profile import normalize_party_roster

        profile = self._profile
        roster = normalize_party_roster(getattr(profile, "party_roster", None))
        brain = getattr(self, "_party_leader_ref", None)
        mode = str(getattr(brain, "hunt_mode", "moving") or "moving")
        if mode not in ("turret", "moving"):
            mode = "moving"
        anchor = getattr(self, "_formation_anchor", None)

        def _anchor_coord(index: int):
            if not isinstance(anchor, tuple) or len(anchor) <= index:
                return None
            return int(anchor[index])

        return {
            "leader_mode": mode,
            "formation_hold": bool(getattr(self, "_formation_hold", False)),
            "formation_reform": bool(getattr(self, "_formation_reform", False)),
            "formation_anchor_x": _anchor_coord(0),
            "formation_anchor_y": _anchor_coord(1),
            "formation_anchor_dx": _anchor_coord(2),
            "formation_anchor_dy": _anchor_coord(3),
            "random_loot": bool(getattr(profile, "party_random_loot", False)),
            "loot_role": str(getattr(profile, "party_loot_role", "none") or "none"),
            "yard_scale_with_roster": True,
            "party_size": max(1, len(roster) + 1),
            "roster": roster,
            "leader_name": str(getattr(self, "_party_leader_name", "") or ""),
            "member_arrow_min": int(getattr(profile, "party_member_arrow_min", 300) or 300),
            "shopkeeper_arrow_min": int(
                getattr(profile, "party_shopkeeper_arrow_min", 300) or 300
            ),
            "member_arrow_give": int(
                getattr(profile, "party_member_arrow_give", 100) or 100
            ),
            "shopkeeper_arrow_buy": int(
                getattr(profile, "party_shopkeeper_arrow_buy", 200) or 200
            ),
            "member_hp_min": int(getattr(profile, "party_member_hp_min", 10) or 0),
            "shopkeeper_hp_min": int(getattr(profile, "party_shopkeeper_hp_min", 20) or 0),
            "member_hp_give": int(getattr(profile, "party_member_hp_give", 10) or 10),
            "shopkeeper_hp_buy": int(getattr(profile, "party_shopkeeper_hp_buy", 20) or 20),
            "member_depoison_min": int(
                getattr(profile, "party_member_depoison_min", 1) or 0
            ),
            "shopkeeper_depoison_min": int(
                getattr(profile, "party_shopkeeper_depoison_min", 2) or 0
            ),
            "member_depoison_give": int(
                getattr(profile, "party_member_depoison_give", 1) or 1
            ),
            "shopkeeper_depoison_buy": int(
                getattr(profile, "party_shopkeeper_depoison_buy", 5) or 5
            ),
            "member_mp_min": int(getattr(profile, "party_member_mp_min", 5) or 0),
            "shopkeeper_mp_min": int(getattr(profile, "party_shopkeeper_mp_min", 10) or 0),
            "member_mp_give": int(getattr(profile, "party_member_mp_give", 5) or 5),
            "shopkeeper_mp_buy": int(getattr(profile, "party_shopkeeper_mp_buy", 10) or 10),
            "loot_pickup": str(getattr(profile, "party_loot_pickup", "all") or "all"),
            "loot_weight_pct": int(getattr(profile, "party_loot_weight_pct", 30) or 30),
            "member_heal_pct": int(getattr(profile, "party_member_heal_pct", 70) or 70),
            "member_potion_pct": int(getattr(profile, "party_member_potion_pct", 50) or 50),
            "mage_heal_pct": int(getattr(profile, "party_mage_heal_pct", 80) or 80),
            "retreat_pct": int(getattr(profile, "party_retreat_pct", 30) or 30),
            "mother_tree": bool(getattr(profile, "party_mother_tree", True)),
            "talking_scroll": bool(getattr(profile, "party_talking_scroll", True)),
            "safe_zone": bool(getattr(profile, "party_safe_zone", True)),
            "tree_hp_to_mp": bool(getattr(profile, "party_tree_hp_to_mp", True)),
            "tree_hp_to_mp_hp": int(getattr(profile, "party_tree_hp_to_mp_hp", 85) or 85),
            "tree_hp_to_mp_mp": int(getattr(profile, "party_tree_hp_to_mp_mp", 80) or 80),
            "tree_heal": bool(getattr(profile, "party_tree_heal", True)),
            "tree_heal_hp": int(getattr(profile, "party_tree_heal_hp", 40) or 40),
            "tree_heal_mp": int(getattr(profile, "party_tree_heal_mp", 80) or 80),
        }

    def _publish_party_policy(self, *, force: bool = False) -> int:
        """Broadcast leader farm policy; refresh every few seconds or on change."""
        import json
        import time as _time

        from app._06_party.comms.orders import leader_session, policy_message

        kwargs = self._leader_party_policy_kwargs()
        key = json.dumps(kwargs, sort_keys=True, default=str)
        self._party_policy_id = str(policy_message(**kwargs).get("policy_id") or "")
        now = _time.time()
        last_at = float(getattr(self, "_party_policy_at", 0.0) or 0.0)
        if (
            not force
            and key == getattr(self, "_party_policy_key", "")
            and now - last_at < 5.0
        ):
            return 0
        sent = int(self._party_comms.publish_policy(**kwargs) or 0)
        self._party_policy_key = key
        self._party_policy_at = now
        prev = getattr(self, "_party_policy_info", {}) or {}
        self._party_policy_info = {
            "at": now,
            "sent": sent,
            "sends": int(prev.get("sends", 0)) + 1,
            "policy_id": self._party_policy_id,
            "session": leader_session(),
            "leader_mode": kwargs["leader_mode"],
            "random_loot": kwargs["random_loot"],
            "party_size": kwargs["party_size"],
        }
        if sent or force:
            self.log(
                f"Party policy sent mode={kwargs['leader_mode']} "
                f"loot={'solo' if kwargs['random_loot'] else 'responsible'} "
                f"roster={len(kwargs['roster'])} → {sent} member(s)"
            )
        return sent

    def _leader_party_tick(self, world, blackboard, map_id) -> None:
        """Collect hellos / reports always; policy and recovery only with a roster."""
        if not self._party_server_on():
            return
        self._drain_party_reports(world)
        if not self._party_leader_on():
            return
        from app._04_decision.world_nav.session import live_pose_from_state

        trip = str(blackboard.scratch.get("mother_tree_trip") or "")
        prev = str(getattr(self, "_party_tree_trip", "") or "")
        if trip == "cast" and prev != "cast":
            pose = live_pose_from_state(world)
            mx = my = None
            mid = map_id
            if pose is not None:
                mx, my = int(pose.x), int(pose.y)
                mid = int(pose.map_id)
            sent = self._party_comms.publish_recovery(map_id=mid, x=mx, y=my)
            self.log(f"Party recovery sent to {sent} member(s)")
        self._party_tree_trip = trip
        self._publish_party_policy()
        self._publish_shop_reports(world, map_id)
        self._publish_supply_notice()
        self._publish_supply_hold()
        self._publish_supply_stand(world, map_id, blackboard)

    def _leader_walk_party(self, world, blackboard, action, map_id):
        """Leader travel with members: ask for room when blocked, pace when they lag.

        A guide with no click for 3 seconds sends ``make_way`` (once per 5 s).
        A travel click waits up to 1 second while the farthest same-map member
        within 12 tiles is past ``PACE_GAP_TILES``, then clicks freely for 2.
        Unstick clicks, retreat, and the walk before the start rally ends are
        not paced. Other actions pass through.
        """
        from app._02_state.enums import ActionType
        from app._04_decision.player_mode import PlayerMode
        from app._06_party.leader_pace import PACE_GAP_TILES, LeaderPace, pace_gap
        from app._06_party.make_way import (
            BLOCKED_NOTES,
            LeaderBlockWatch,
            guide_ahead,
            make_way_message,
        )

        if not self._party_leader_on() or action is None or blackboard is None:
            return action
        watch = getattr(self, "_party_block_watch", None)
        if not isinstance(watch, LeaderBlockWatch):
            watch = self._party_block_watch = LeaderBlockWatch()
        pace = getattr(self, "_party_pace", None)
        if not isinstance(pace, LeaderPace):
            pace = self._party_pace = LeaderPace()
        origin = getattr(blackboard, "world_origin", None)
        kind = getattr(action, "action", None)
        reason = str(getattr(action, "reason", "") or "")
        blocked = kind is ActionType.IDLE and reason in BLOCKED_NOTES
        if watch.note(blocked) and origin is not None:
            here = (int(origin.x), int(origin.y))
            guide = guide_ahead(getattr(blackboard, "nav_path", None) or [], here)
            sent = self._party_comms_publish_body(
                make_way_message(map_id=map_id, x=here[0], y=here[1], guide=guide)
            )
            self.log(f"Party: leader blocked at {here}, make way sent to {sent}")
        if (
            kind is not ActionType.TRAVELING
            or "unstick" in reason
            or origin is None
            or getattr(blackboard, "player_mode", None) is PlayerMode.RETREATING
        ):
            pace.reset()
            return action
        rally = getattr(self, "_start_rally", None)
        if rally is None or str(getattr(rally, "state", "") or "") != "done":
            pace.reset()
            return action
        if getattr(world, "party_read_ok", None) is not True:
            return action
        from app._06_party.formation import followers_from_party

        snap = getattr(world, "last_party", None)
        followers = followers_from_party(
            snap, map_id, self_name=_player_chat_name(world, snap)
        )
        gap = pace_gap((int(origin.x), int(origin.y)), followers)
        limit = int(PACE_GAP_TILES)
        was = pace.holding
        if not pace.check(behind=gap is not None and gap > limit):
            if was and not pace.holding:
                self.log(f"Party: pace released, farthest member {gap} tiles")
            return action
        if not was:
            self.log(f"Party: pace wait, farthest member {gap} tiles (limit {limit})")
        from app._06_party.types import ActionIntent

        return ActionIntent(
            action=ActionType.IDLE,
            priority=float(getattr(action, "priority", 0.0) or 0.0),
            reason=f"party pace wait gap={gap} limit={limit}",
        )

    @staticmethod
    def _party_comms_publish_body(body) -> int:
        from app._06_party.comms.publish import publish_body

        return int(publish_body(body) or 0)

    def _leader_blackboard(self):
        board = getattr(getattr(self, "_party_leader_ref", None), "decision", None)
        blackboard = getattr(board, "blackboard", None)
        if blackboard is None:
            blackboard = getattr(getattr(self, "decision", None), "blackboard", None)
        return blackboard

    def _leader_leaving_hunt(self, blackboard) -> bool:
        """Retreat, mother tree, or a return scroll. A new hunt map is not leaving."""
        from app._04_decision.player_mode import PlayerMode
        from app._04_decision.world_nav.hooks import SCRATCH_NEED_WORLD_NAV

        mode = getattr(blackboard, "player_mode", None)
        if mode is PlayerMode.RETREATING:
            return True
        scratch = getattr(blackboard, "scratch", None)
        if isinstance(scratch, dict):
            if scratch.get("mother_tree_trip"):
                return True
            if scratch.get("hp_safe_scrolled") or scratch.get("hp_safe_scroll_spot"):
                return True
            if str(scratch.get(SCRATCH_NEED_WORLD_NAV) or "") == "post_retreat":
                return True
        return False

    def _party_hunt_open(self, world) -> bool:
        """True after the start rally has reached the hunt mark."""
        from app._04_decision.world_nav.session import live_pose_from_state
        from app._06_party.arrow_policy import hunt_map_after_pose

        rally = getattr(self, "_start_rally", None)
        if rally is None or str(getattr(rally, "state", "") or "") != "done":
            return False
        pose = live_pose_from_state(world)
        pose_map = int(pose.map_id) if pose is not None else None
        self._party_hunt_map = hunt_map_after_pose(
            getattr(self, "_party_hunt_map", None),
            pose_map,
            leaving=self._leader_leaving_hunt(self._leader_blackboard()),
        )
        return True

    def _leader_supply_away(self, world, blackboard) -> bool:
        """Leader is leaving the hunt, or is no longer on the hunt map."""
        from app._04_decision.world_nav.session import live_pose_from_state

        if self._leader_leaving_hunt(blackboard):
            return True
        hunt = getattr(self, "_party_hunt_map", None)
        pose = live_pose_from_state(world)
        if hunt is not None and pose is not None and int(pose.map_id) != int(hunt):
            return True
        return False

    def _supply_away_names(self, world) -> set[str]:
        """Recipients the shopkeeper must not walk to."""
        from app._06_party.sync import member_states

        hunt = getattr(self, "_party_hunt_map", None)
        away: set[str] = set()
        for name, row in member_states.rows.items():
            live = row.get("live") if isinstance(row, dict) else None
            if not isinstance(live, dict):
                continue
            kind = str(live.get("kind") or "")
            if kind == "retreat":
                away.add(str(name).casefold())
                continue
            if hunt is None:
                continue
            try:
                if int(live.get("map_id")) != int(hunt):
                    away.add(str(name).casefold())
            except (TypeError, ValueError):
                continue
        me = _player_chat_name(world, getattr(world, "last_party", None))
        board = getattr(getattr(self, "_party_leader_ref", None), "decision", None)
        blackboard = getattr(board, "blackboard", None)
        if blackboard is None:
            blackboard = getattr(getattr(self, "decision", None), "blackboard", None)
        if me and blackboard is not None and self._leader_supply_away(world, blackboard):
            away.add(me.casefold())
        return away

    def _publish_shop_reports(self, world, map_id) -> None:
        """Forward member reports and this leader's report to the shopkeeper."""
        from app._04_decision.world_nav.session import live_pose_from_state
        from app._06_party.comms.publish import publish_shop_reports
        from settings.profile import normalize_party_roster

        pose = live_pose_from_state(world)
        x = y = None
        mid = map_id
        if pose is not None:
            x, y = int(pose.x), int(pose.y)
            mid = int(pose.map_id)
        rows = normalize_party_roster(getattr(self._profile, "party_roster", None))
        hunt_open = self._party_hunt_open(world)
        sent = publish_shop_reports(
            world,
            rows,
            _player_chat_name(world, getattr(world, "last_party", None)),
            mid,
            x,
            y,
            hunt_open=hunt_open,
            away=self._supply_away_names(world),
        )
        if sent:
            self.log(f"Party reports sent to shopkeeper ({sent})")

    def _arm_party_self_shop(self, blackboard, seat_role: str) -> None:
        """A roster shopkeeper is the only party seat that starts its own shop.

        The socket may be down. No shopkeeper name leaves personal shopping on.
        HP retreat sell does not read the flag.
        """
        scratch = getattr(blackboard, "scratch", None)
        if not isinstance(scratch, dict):
            return
        if not self._party_enabled():
            scratch.pop("party_self_shop_blocked", None)
            scratch.pop("party_arrow_shop_covered", None)
            return
        from app._06_party.comms.publish import _shopkeeper_names
        from settings.profile import normalize_party_roster

        names = _shopkeeper_names(
            normalize_party_roster(getattr(self._profile, "party_roster", None))
        )
        seat = str(seat_role or "").strip().lower()
        if names and seat != "shopkeeper":
            scratch["party_self_shop_blocked"] = True
            scratch["party_arrow_shop_covered"] = True
        else:
            scratch.pop("party_self_shop_blocked", None)
            scratch.pop("party_arrow_shop_covered", None)

    def _leader_supply_claim(self) -> dict | None:
        from app._06_party.comms.publish import _shopkeeper_names
        from app._06_party.sync import member_states
        from settings.profile import normalize_party_roster

        names = _shopkeeper_names(
            normalize_party_roster(getattr(self._profile, "party_roster", None))
        )
        if not names:
            return None
        row = member_states.rows.get(names[0])
        if not isinstance(row, dict):
            for key, value in member_states.rows.items():
                if str(key).casefold() == names[0].casefold():
                    row = value
                    break
        live = row.get("live") if isinstance(row, dict) else None
        supply = live.get("supply") if isinstance(live, dict) else None
        return dict(supply) if isinstance(supply, dict) else None

    def _leader_arrow_pickup(self, world, blackboard):
        claim = self._leader_supply_claim()
        if not isinstance(claim, dict):
            return None
        me = _player_chat_name(world, getattr(world, "last_party", None))
        who = str(claim.get("for") or "").strip()
        if not me or not who or me.casefold() != who.casefold():
            return None
        from app._06_party.arrow_duty import leader_supply_pickup

        return leader_supply_pickup(world, blackboard, claim)

    def _publish_supply_notice(self) -> None:
        claim = self._leader_supply_claim()
        sent_id = str(getattr(self, "_party_supply_id", "") or "")
        from app._06_party.comms.publish import publish_body

        if not isinstance(claim, dict) or not claim.get("id"):
            if not sent_id:
                return
            publish_body({"type": "supply_drop", "from": "leader", "clear": True})
            self._party_supply_id = ""
            return
        if str(claim.get("id")) == sent_id:
            return
        publish_body(
            {
                "type": "supply_drop",
                "from": "leader",
                "clear": False,
                "id": claim.get("id"),
                "for": claim.get("for"),
                "item": claim.get("item") or "arrow",
                "map_id": claim.get("map_id"),
                "x": claim.get("x"),
                "y": claim.get("y"),
                "qty": claim.get("qty"),
            }
        )
        self._party_supply_id = str(claim.get("id"))

    def _shopkeeper_live(self) -> dict | None:
        from app._06_party.comms.publish import _shopkeeper_names
        from app._06_party.sync import member_states
        from settings.profile import normalize_party_roster

        names = _shopkeeper_names(
            normalize_party_roster(getattr(self._profile, "party_roster", None))
        )
        if not names:
            return None
        row = member_states.rows.get(names[0])
        if not isinstance(row, dict):
            for key, value in member_states.rows.items():
                if str(key).casefold() == names[0].casefold():
                    row = value
                    break
        live = row.get("live") if isinstance(row, dict) else None
        return live if isinstance(live, dict) else None

    def _leader_supply_hold(self) -> dict | None:
        live = self._shopkeeper_live()
        hold = live.get("supply_hold") if isinstance(live, dict) else None
        return dict(hold) if isinstance(hold, dict) else None

    def _publish_supply_hold(self) -> None:
        hold = self._leader_supply_hold()
        sent_id = str(getattr(self, "_party_hold_id", "") or "")
        from app._06_party.comms.publish import publish_body

        if not isinstance(hold, dict) or not hold.get("id"):
            if not sent_id:
                return
            publish_body({"type": "supply_hold", "from": "leader", "clear": True})
            publish_body({"type": "supply_stand", "from": "leader", "clear": True})
            self._party_hold_id = ""
            self._party_hold_drop = False
            self._party_stand_key = None
            return
        dropping = bool(hold.get("dropping"))
        sent_drop = bool(getattr(self, "_party_hold_drop", False))
        if str(hold.get("id")) != sent_id or sent_drop != dropping:
            body = {
                "type": "supply_hold",
                "from": "leader",
                "clear": False,
                "id": hold.get("id"),
                "for": hold.get("for"),
                "item": hold.get("item") or "arrow",
                "qty": hold.get("qty"),
                "min": hold.get("min"),
                "dropping": dropping,
            }
            if str(hold.get("guid") or "").strip():
                body["guid"] = hold.get("guid")
            publish_body(body)
            self._party_hold_id = str(hold.get("id"))
            self._party_hold_drop = dropping
            self._party_stand_key = None

    def _publish_supply_stand(self, world, map_id, blackboard=None) -> None:
        del map_id
        hold = self._leader_supply_hold()
        if not isinstance(hold, dict) or not hold.get("id"):
            return
        from app._06_party.comms.publish import publish_body
        from app._06_party.sync import member_states

        me = _player_chat_name(world, getattr(world, "last_party", None))
        who = str(hold.get("for") or "").strip()
        leader_self = bool(me and who and me.casefold() == who.casefold())
        stand = None
        if leader_self:
            from app._06_party.arrow_duty import leader_supply_stand

            stand = leader_supply_stand(
                blackboard, getattr(world, "last_party", None), hold
            )
        else:
            for row in member_states.rows.values():
                live = row.get("live") if isinstance(row, dict) else None
                body = live.get("supply_stand") if isinstance(live, dict) else None
                if not isinstance(body, dict):
                    continue
                if str(body.get("id") or "") != str(hold.get("id")):
                    continue
                stand = body
                break
        if not isinstance(stand, dict) or stand.get("confirmed") is not True:
            return
        try:
            mid = int(stand["map_id"])
            sx = int(stand["x"])
            sy = int(stand["y"])
        except (TypeError, ValueError, KeyError):
            return
        if sx == 0 and sy == 0:
            return
        key = (str(stand.get("id") or ""), mid, sx, sy)
        if key == getattr(self, "_party_stand_key", None):
            return
        publish_body(
            {
                "type": "supply_stand",
                "from": "leader",
                "clear": False,
                "id": stand.get("id"),
                "for": stand.get("for") or who,
                "map_id": mid,
                "x": sx,
                "y": sy,
                "confirmed": True,
            }
        )
        self._party_stand_key = key

    def _nudge_supply_live(self) -> None:
        """Send member_state on the tick a hold, its drop phase, or a stand tile changes."""
        reporter = getattr(self, "_member_state_reporter", None)
        if reporter is None:
            return
        brain = getattr(self, "_party_brain_ref", None)
        runtime = getattr(brain, "runtime", None)
        hold = getattr(runtime, "supply_hold", None) if runtime is not None else None
        stand = getattr(runtime, "supply_stand", None) if runtime is not None else None
        key = (
            str(hold.get("id") or "") if isinstance(hold, dict) else "",
            bool(hold.get("dropping")) if isinstance(hold, dict) else False,
            str(stand.get("id") or "") if isinstance(stand, dict) else "",
            stand.get("x") if isinstance(stand, dict) else None,
            stand.get("y") if isinstance(stand, dict) else None,
        )
        if key == getattr(self, "_supply_live_key", None):
            return
        reporter.nudge()
        self._supply_live_key = key

    def _drain_party_reports(self, world) -> int:
        """Feed member reports to the rally, policy acks to the invite gate."""
        from app._06_party.invite import roster_invite_names
        from settings.profile import normalize_party_roster

        rows = normalize_party_roster(getattr(self._profile, "party_roster", None))
        snap = getattr(world, "last_party", None)

        def _note(msg: str) -> None:
            self.log(msg)
            self._party_event("socket", msg)

        return self._party_comms.drain_reports(
            start_rally=getattr(self, "_start_rally", None),
            party_snapshot=snap,
            roster_names=roster_invite_names(
                rows, _player_chat_name(world, snap)
            ),
            log=_note,
        )

    def _leader_policy_acked(self, name: str) -> bool:
        """Invite gate: ``name`` confirmed the policy currently being sent.

        A dropped socket must send a new ``member_state`` before another
        ``/초대``. A name already in party memory is not in the due list.
        """
        from app._06_party.comms.orders import policy_acks
        from app._06_party.sync import member_states

        if member_states.awaiting_fresh(name):
            return False
        return policy_acks.acked(name, getattr(self, "_party_policy_id", "") or None)

    def _leader_may_begin_start_rally(self, world) -> bool:
        """Rally starts with the party. The leader walks to the mark immediately.

        Empty roster stays off (the leader still farms). A named roster does not
        wait for the invite window or for a member socket.
        """
        if not self._party_leader_on():
            return False
        start = getattr(self, "_start_rally", None)
        if start is None or str(getattr(start, "state", "off") or "off") != "off":
            return False
        from app._06_party.invite import roster_required_names
        from settings.profile import normalize_party_roster

        snap = getattr(world, "last_party", None)
        rows = normalize_party_roster(getattr(self._profile, "party_roster", None))
        expected = set(roster_required_names(rows, _player_chat_name(world, snap)))
        if not expected:
            return False
        invites = getattr(self, "_party_invites", None)
        return invites is not None

    def _begin_leader_start_rally(self, world, blackboard) -> None:
        """Party start: rally on this tile, or on the last teleport landing of the route."""
        if not self._party_leader_on():
            return
        start = getattr(self, "_start_rally", None)
        if start is None:
            return
        from app._04_decision.dungeon_floor_route import inside_target_dungeon
        from app._04_decision.talking_scroll import player_on_selected_map
        from app._04_decision.world_nav.session import live_pose_from_state
        from app._06_party.invite import roster_required_names
        from settings.profile import normalize_party_roster

        snap = getattr(world, "last_party", None)
        rows = normalize_party_roster(getattr(self._profile, "party_roster", None))
        expected = set(roster_required_names(rows, _player_chat_name(world, snap)))
        travel = not (player_on_selected_map(blackboard) or inside_target_dungeon(blackboard))
        invites = getattr(self, "_party_invites", None)
        start.begin(
            expected,
            travel=travel,
            pose=live_pose_from_state(world),
            deadline=invites.deadline if invites is not None else None,
        )

    @staticmethod
    def _party_event(channel: str, msg: str) -> None:
        try:
            from app._06_party.party_log import event as party_event

            party_event(channel, "%s", msg)
        except Exception:
            pass

    def _apply_member_party_policy(self, world, map_id, party_brain, policy) -> None:
        """Overlay the leader policy on this member's own party knobs.

        In memory only: the profile is never touched, so a solo run (party off)
        always starts from the member's own settings. Re-applied when the policy
        or this character's name changes (the policy can arrive before the
        in-game invite, when the name is not known yet).
        """
        import json

        snap = getattr(world, "last_party", None)
        name = _player_chat_name(world, snap)
        body = {k: v for k, v in policy.items() if k not in ("ts", "sender")}
        sig = json.dumps(body, sort_keys=True, default=str) + "|" + str(name or "")
        if sig == getattr(self, "_member_policy_sig", ""):
            return
        self._member_policy_sig = sig
        party_brain.apply_leader_policy(policy, self_name=name)
        cfg = party_brain.config
        prev = self._member_policy_info or {}
        self._member_policy_info = {
            **prev,
            "applied_at": time.time(),
            "applied_id": str(policy.get("policy_id") or ""),
            "as_name": name or "",
            "applies": int(prev.get("applies", 0)) + 1,
        }
        self.log(
            f"Party policy applied (temporary) mode={cfg.leader_mode} "
            f"farm={cfg.farm_mode} "
            f"seat={cfg.seat_role} "
            f"loot={'solo' if cfg.random_loot else cfg.loot_role} "
            f"follow={cfg.follow_tiles}/{cfg.stop_tiles} as={name or '—'}"
        )

    def _reset_member_for_leader_session(self, session: str, party_brain) -> None:
        """New leader run id: drop the overlay and start policy confirm again.

        A member socket reconnect does not call this. ``InviteAccepter`` is
        reset only when the leader bot starts a new run, not when the socket drops.
        """
        from app._06_party.comms.orders import member_orders

        if party_brain is not None:
            party_brain.reset_for_new_leader_session()
        prev = self._member_policy_info if isinstance(self._member_policy_info, dict) else {}
        first = not prev.get("session")
        self._member_policy_sig = ""
        # First contact often lands while the uidialog invite is already open.
        # Resetting here restarts the 3-press Y budget mid-accept.
        if self._invite_accepter is not None and not first:
            self._invite_accepter.reset()
        if self._member_state_reporter is not None:
            self._member_state_reporter.reset()
        self._party_beep_sent = False
        self._member_hello_key = None
        self._member_policy_info = {
            "session": session,
            "session_at": time.time(),
            "session_resets": int(member_orders.session_resets),
        }
        msg = (
            f"Party leader session {session} — "
            + ("first contact" if first else f"leader restarted (was {prev.get('session')})")
            + ": orders and policy reset, waiting for the new leader policy"
        )
        self.log(msg)
        self._party_event("socket", msg)

    def _member_client_id(self) -> str:
        """Stable id for this member run, used to book unnamed policy acks."""
        cid = str(getattr(self, "_party_client_id", "") or "").strip()
        if cid:
            return cid
        import uuid

        cid = uuid.uuid4().hex[:8]
        self._party_client_id = cid
        return cid

    def _send_member_policy_ack(self, policy: dict) -> None:
        """Answer each applied policy frame so the leader may invite this member."""
        info = self._member_policy_info if isinstance(self._member_policy_info, dict) else {}
        name = str(info.get("as_name") or "")
        pid = str(policy.get("policy_id") or "")
        try:
            sent = self._party_comms.send_policy_ack(
                name=name,
                policy_id=pid,
                client_id=self._member_client_id(),
            )
        except Exception as exc:
            self.log(f"Party policy ack send failed: {exc}")
            return
        if not sent:
            return
        first = pid != str(info.get("acked_id") or "")
        info["acked_at"] = time.time()
        info["acked_id"] = pid
        info["acks"] = int(info.get("acks", 0)) + 1
        self._member_policy_info = info
        if first:
            msg = f"Party policy confirmed to leader as={name or 'member'} id={pid or '—'}"
            self.log(msg)
            self._party_event("socket", msg)

    def _member_beep_if_already_in(self, world) -> None:
        """Once: already in party (memory) → socket beep, no invite wait."""
        from app._06_party.invite import already_in_party

        if getattr(self, "_party_beep_sent", False):
            return
        from app._06_party.invite import action_party_snapshot

        if not already_in_party(action_party_snapshot(world)):
            return
        if not self._party_comms.member_connected:
            return
        info = self._member_policy_info if isinstance(self._member_policy_info, dict) else {}
        name = str(info.get("as_name") or "") or _player_chat_name(
            world, getattr(world, "last_party", None)
        ) or "member"
        try:
            ok = bool(self._party_comms.send_beep(name=name, why="already_in_party"))
        except Exception as exc:
            self.log(f"Party beep failed: {exc}")
            return
        if not ok:
            return
        self._party_beep_sent = True
        msg = f"Party beep sent to leader as={name} (already in party)"
        self.log(msg)
        self._party_event("socket", msg)

    def _member_invite_accept(self, world) -> None:
        """Invite popup on screen → Y; once it closed, ``invite_accept`` to the leader."""
        from app._06_party.accept import InviteAccepter
        from app._06_party.comms.orders import member_orders
        from app._06_party.invite_popup import party_invite
        from app._06_party.sync import memory_in_party

        if self._invite_accepter is None:
            def _log(msg: str) -> None:
                self.log(msg)
                self._party_event("socket", msg)

            def _send_accept(body: dict) -> bool:
                if isinstance(body, dict) and not body.get("client_id"):
                    body = {**body, "client_id": self._member_client_id()}
                return self._party_comms.send_invite_accept(body)

            self._invite_accepter = InviteAccepter(send_ack=_send_accept, log=_log)
        from app._06_party.invite import action_party_snapshot

        snap = action_party_snapshot(world)
        info = self._member_policy_info if isinstance(self._member_policy_info, dict) else {}
        from app._06_party.sync import party_view

        self._invite_accepter.tick(
            party_invite(getattr(world, "last_uidialog", None)),
            leader_name=str((member_orders.policy or {}).get("leader_name") or ""),
            name=str(info.get("as_name") or "") or _player_chat_name(world, snap) or "member",
            session=member_orders.session,
            in_party=memory_in_party(snap),
            memory_leader=str(party_view(snap).get("leader") or ""),
        )

    def _set_invite_join_hold(self, world, party_brain) -> None:
        """Keep join-map off while the invite popup is open or memory is the old party."""
        runtime = getattr(party_brain, "runtime", None) if party_brain is not None else None
        if runtime is None:
            return
        accepter = getattr(self, "_invite_accepter", None)
        leader = ""
        if accepter is not None and world is not None:
            from app._06_party.invite import action_party_snapshot
            from app._06_party.sync import party_view

            leader = str(party_view(action_party_snapshot(world)).get("leader") or "")
        runtime.hold_join_map = bool(
            accepter is not None and accepter.blocks_join_map(leader)
        )

    def _member_on_leader_roster(self, world, policy: dict) -> bool:
        """Pending members do not overlay policy or walk a rally."""
        from app._06_party.member_identity import name_on_roster

        snap = getattr(world, "last_party", None)
        name = _player_chat_name(world, snap)
        return name_on_roster(name, (policy or {}).get("roster"))

    def _member_hello_tick(self, world) -> None:
        """Send ``member_hello`` once the local name is real; never a placeholder."""
        from app._06_party.comms.orders import member_orders
        from app._06_party.member_identity import (
            CharacterIdentity,
            build_member_hello,
            class_token,
        )

        if not self._party_comms.member_connected:
            return
        snap = getattr(world, "last_party", None)
        player = getattr(world, "player", None)
        level = getattr(player, "level", None) if player is not None else None
        ident = CharacterIdentity(
            name=_player_chat_name(world, snap),
            character_class=class_token(
                getattr(player, "character_type", None) if player is not None else None
            ),
            level=level if isinstance(level, (int, float)) else None,
        )
        farm = ""
        brain = getattr(self, "_party_brain_ref", None)
        if brain is not None:
            farm = str(getattr(getattr(brain, "config", None), "farm_mode", "") or "")
        body = build_member_hello(
            ident, client_id=self._member_client_id(), farm_mode=farm
        )
        if body is None:
            return
        key = (
            ident.character_key.casefold(),
            ident.character_class,
            ident.level,
            str(member_orders.session or ""),
        )
        if key == getattr(self, "_member_hello_key", None):
            return
        try:
            ok = bool(self._party_comms.send_member_hello(body))
        except Exception:
            ok = False
        if not ok:
            return
        self._member_hello_key = key
        self.log(f"Party hello sent as {ident.character_key}")

    def _member_state_report(self, world) -> None:
        """Send ``member_state`` (party memory, policy, invite phase) on change / every 2 s."""
        from app._06_party.comms.orders import member_orders
        from app._06_party.sync import MemberStateReporter, party_view

        if not member_orders.session:
            return
        if self._member_state_reporter is None:
            self._member_state_reporter = MemberStateReporter()
        info = self._member_policy_info if isinstance(self._member_policy_info, dict) else {}
        acc = self._invite_accepter
        invite = (
            acc.report()
            if acc is not None
            else {"id": "", "phase": "idle", "presses": 0, "inviter": ""}
        )
        from app._06_party.invite import action_party_snapshot

        snap = action_party_snapshot(world)
        name = str(info.get("as_name") or "") or _player_chat_name(world, snap)
        self._nudge_supply_live()
        self._member_state_reporter.tick(
            self._party_comms.send_member_state,
            name=name or "member",
            session=member_orders.session,
            policy_id=str(info.get("applied_id") or ""),
            party=party_view(snap),
            invite=invite,
            live=self._member_live_view(world),
            client_id=self._member_client_id(),
        )

    def _member_live_view(self, world) -> dict:
        """Monitor extras for ``member_state``: bot state, map, xy, hp/mp, brain, rally."""
        from app._04_decision.world_nav.session import live_pose_from_state
        from app._06_party.comms.orders import member_orders

        out: dict = {"bot": self.state.value}
        try:
            pose = live_pose_from_state(world)
        except Exception:
            pose = None
        if pose is not None:
            out["map_id"] = int(pose.map_id)
            out["xy"] = [int(pose.x), int(pose.y)]
        player = getattr(world, "player", None)
        for key in ("hp", "mp", "max_hp", "max_mp"):
            val = getattr(player, key, None) if player is not None else None
            if isinstance(val, (int, float)):
                out[key] = int(val)
        brain = getattr(self, "_party_brain_ref", None)
        runtime = getattr(brain, "runtime", None)
        if runtime is not None:
            out["kind"] = str(getattr(runtime, "last_kind", "") or "")
            out["reason"] = str(getattr(runtime, "last_reason", "") or "")[:80]
            phase = str(getattr(runtime, "duty_phase", "") or "follow")
            out["phase"] = phase if phase in ("follow", "shop", "supply") else "follow"
            notice = getattr(runtime, "supply_notice", None)
            if isinstance(notice, dict) and notice.get("id"):
                out["supply"] = {
                    "id": notice.get("id"),
                    "for": notice.get("for"),
                    "item": notice.get("item") or "arrow",
                    "map_id": notice.get("map_id"),
                    "x": notice.get("x"),
                    "y": notice.get("y"),
                    "qty": notice.get("qty"),
                }
            hold = getattr(runtime, "supply_hold", None)
            if isinstance(hold, dict) and hold.get("id"):
                reported = {
                    "id": hold.get("id"),
                    "for": hold.get("for"),
                    "item": hold.get("item") or "arrow",
                    "qty": hold.get("qty"),
                    "min": hold.get("min"),
                    "dropping": bool(hold.get("dropping")),
                }
                if str(hold.get("guid") or "").strip():
                    reported["guid"] = hold.get("guid")
                out["supply_hold"] = reported
            stand = getattr(runtime, "supply_stand", None)
            if isinstance(stand, dict) and stand.get("id"):
                out["supply_stand"] = {
                    "id": stand.get("id"),
                    "for": stand.get("for"),
                    "map_id": stand.get("map_id"),
                    "x": stand.get("x"),
                    "y": stand.get("y"),
                    "confirmed": stand.get("confirmed") is True,
                }
        gather = member_orders.gather or {}
        out["rally"] = str(gather.get("stage") or "")
        out["arrived"] = bool(member_orders.arrived)
        return out

    def _member_party_tick(
        self, world, map_id, *, send: bool, party_brain=None, skip_accept: bool = False
    ) -> None:
        """Read leader orders (incl. farm policy), then send buffs/items."""
        if self._party_comms.client is None:
            # Invite Y is a local popup. The socket only reports that it happened.
            # Once per loop (the send=False pass). A manual Y this tick wins.
            if not send and not skip_accept:
                self._member_invite_accept(world)
            if not send:
                self._set_invite_join_hold(world, party_brain)
            return
        from app._04_decision.world_nav.session import live_pose_from_state
        from app._06_party.comms.orders import member_orders

        if not send:
            restored = self._party_comms.watch_member(log=self._party_socket_note)
            if restored:
                self._member_hello_key = None
                reporter = getattr(self, "_member_state_reporter", None)
                if reporter is not None:
                    reporter.nudge()
                self.log(
                    "Party socket restored — resend hello and member_state; "
                    "invite accept is kept"
                )
            try:
                self._party_comms.ingest_orders()
            except Exception as exc:
                self.log(f"Party member order read failed: {exc}")
            session = member_orders.take_session_change()
            if session is not None:
                self._reset_member_for_leader_session(session, party_brain)
            beep = member_orders.take_beep()
            if beep is not None:
                why = str(beep.get("why") or "already_in_party")
                msg = f"Party beep from leader — socket ok ({why})"
                self.log(msg)
                self._party_event("socket", msg)
            fresh = member_orders.take_policy()
            policy = member_orders.policy
            rostered = bool(
                policy is not None and self._member_on_leader_roster(world, policy)
            )
            if not rostered:
                member_orders.gather = None
                member_orders.recovery = None
            if party_brain is not None and policy is not None and rostered:
                self._apply_member_party_policy(
                    world, map_id, party_brain, policy
                )
                if fresh is not None:
                    self._send_member_policy_ack(fresh)
            self._member_hello_tick(world)
            if not skip_accept:
                self._member_invite_accept(world)
            self._set_invite_join_hold(world, party_brain)
            self._member_beep_if_already_in(world)
            self._member_state_report(world)
            return
        pose = live_pose_from_state(world)
        px = py = None
        mid = map_id
        if pose is not None:
            px, py = int(pose.x), int(pose.y)
            mid = int(pose.map_id)
        self._party_comms.send_status(
            world, map_id=mid, x=px, y=py, log=self.log
        )

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
            self._clear_party_nav_hooks()
            self._start_party_socket()
            if self._start_party_client():
                self._run_bot_loop()
            elif not self._stop_event.is_set():
                self.stop(reason="party_ws_unreachable")
        except Exception:
            crashed = True
            self.log("Worker crashed:\n" + traceback.format_exc())
        finally:
            self._clear_party_nav_hooks()
            self._party_brain_ref = None
            self._party_leader_ref = None
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
            try:
                from app._06_party.party_log import reset as reset_party_log

                reset_party_log()
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
        from app._04_decision.behaviors.party_turret import (
            set_party_turret,
            turret_status,
        )
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
                    getattr(profile, "hp_potion_ratio", 0.50) or 0.50
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
                "seat_role": (
                    "mage"
                    if str(getattr(profile, "character", "") or "").strip().lower()
                    == "mage"
                    else "member"
                ),
                "mage_support_skills": dict(
                    getattr(profile, "party_mage_support_skills", None) or {}
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
            f"→ party_mode={party_mode} "
            f"server_on={self._party_server_on()} "
            f"leader_on={self._party_leader_on()} "
            f"roster={self._leader_roster_ready()}"
        )
        if self._party_leader_on():
            self._install_party_nav_hooks()
            self.log(
                "Party leader uses the party schedule. "
                "NPC teleporter and mother-tree decisions are sent to members."
            )
        else:
            self._clear_party_nav_hooks()
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
        from app._04_decision.game_language import get_game_language

        get_logger("session").info(
            "click language=%s (account server locale)",
            get_game_language(),
        )
        self._route_identity = route_identity(profile_snap)
        with self._lock:
            self._settings_applied = seen_epoch

        # Party flags land on the profile during install_profile_runtime.
        # Opening the party file before that left party_enabled=False → no file.
        self._ensure_party_log(role=party_role, level=log_level)
        try:
            from app._06_party.party_log import active as party_log_active
            from app._06_party.party_log import event as party_event

            if party_log_active():
                party_event(
                    "session",
                    "gate role=%s member_mode=%s party_enabled=%s ws_port=%s",
                    party_role,
                    party_mode,
                    bool(getattr(self._profile, "party_enabled", False)),
                    int(getattr(self._profile, "party_ws_port", 8765) or 8765),
                )
        except Exception:
            pass


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
        self._party_farm_started = False
        self._party_wait_log_at = 0.0
        party_brain: PartyMemberManager | None = None
        leader_brain = None
        self._member_policy_sig = ""
        self._member_policy_info = {}
        self._invite_accepter = None
        self._member_state_reporter = None
        self._party_policy_info = {}
        self._party_policy_id = ""
        self._party_leader_name = ""
        self._party_invites = None
        self._party_brain_ref = None
        self._party_beep_sent = False
        self._party_client_id = ""
        self._party_leader_ref = None
        from app._06_party.comms.orders import (
            member_orders,
            new_leader_session,
            policy_acks,
        )
        from app._06_party.sync import invite_accepts

        policy_acks.clear()
        member_orders.clear()
        invite_accepts.clear()
        if self._party_leader_on():
            session = new_leader_session()
            self.log(f"Party leader session {session} (members reset on this id)")
            self._party_event("session", f"leader session {session}")
        if party_mode:
            party_brain = PartyMemberManager(party_cfg)
            self._party_brain_ref = party_brain
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
                "off-UI chase + other-map join. "
                "Needs an in-game party (party_listen). "
                "WebSocket is reports/orders only — it does not set the leader. "
                "/초대 is typed by the leader bot after Start, not by this member."
            )
        elif self._party_server_on():
            from app._06_party.leader_manager import PartyLeaderManager

            leader_brain = PartyLeaderManager(decision)
            self._party_leader_ref = leader_brain
            decision.blackboard.scratch["party_leader_no_loot"] = True
            try:
                count = leader_brain.arm(
                    getattr(profile, "party_routine", None) or []
                )
                if count:
                    self.log(
                        "Party leader armed on party routine "
                        f"({count} entries) — solo schedule left unused"
                    )
                else:
                    self.log(
                        "Party leader has no party routine — "
                        "solo schedule was not armed"
                    )
            except Exception as exc:
                self.log(f"Party leader routine init skipped: {exc}")
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

        want_party = bool(party_mode or self._party_server_on())
        sensors = PerceptionSensors(config)
        set_shared_sensors(sensors)
        for err in list(sensors.buffer.errors):
            self.log(f"Perception sensor: {err}")
        if sensors.monitor is not None:
            self.log(
                "Memory uses the single-version in-process readers "
                "(print_state, realtime_monitor, inventory, hotbar, buff, dialog)."
            )
            if want_party:
                self.log("Party roster still comes from the party module.")
        else:
            self.log("Memory monitor unavailable at worker start")
        buf0 = sensors.capture_tick(
            force_inventory=True, hotbar=True, party=want_party
        )
        # Party init is lazy inside capture_tick — surface those errors now.
        for err in list(sensors.buffer.errors):
            self.log(f"Perception sensor: {err}")
        if want_party:
            calib = sensors.party_calibration
            if calib is None:
                self.log("Party memory: not anchored (LC not running, not elevated, or old party_listen.dll)")
            elif calib.get("subs_ok"):
                delta = int(calib.get("delta") or 0)
                self.log(
                    "Party memory: OK"
                    + (f" (party vfts calibrated {delta:+#x} vs PARTY_SEC17.txt)" if delta else "")
                )
            else:
                self.log(
                    "Party memory: PartySubsystem not found for this LC build — party "
                    "state comes from member reports only. Check "
                    "Engine/analysis/dll/party.dll and "
                    "Engine/analysis/registry/LC930_REGISTRY.txt"
                )
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
                    "Place it at Engine/analysis/dll/party.dll, then restart."
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
            from app._05_action.input_backend import backend_name, configure_hunt_input
            from app._05_action.mouse import prepare_capture

            configure_hunt_input(profile)
            self.log(f"Hunt input: {backend_name()}")
            prepare_capture()
        except Exception as exc:
            self.log(f"Input capture failed: {exc}")
            if backend_name() == "pico":
                self._stop_event.set()
                self._set_state(RunState.STOPPED, f"Input capture failed: {exc}")

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
        leader_setup_done = False
        with self._debug_lock:
            self._routine_clock_gen += 1
            routine_clock_gen = self._routine_clock_gen
            self._farm_clock_gen += 1
            farm_clock_gen = self._farm_clock_gen

        def publish(note: str, *, force: bool = False) -> None:
            nonlocal last_publish_t
            now = time.perf_counter()
            try:
                self._note_routine_clock(decision.blackboard, routine_clock_gen)
                self._note_farm_clock(decision.blackboard, farm_clock_gen)
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
                    _freeze_stay_clocks(decision.blackboard)
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
                    _freeze_stay_clocks(decision.blackboard)
                    self._set_preview_hold("Game window minimized — bot paused")
                    publish("minimized")
                    time.sleep(0.05)
                    continue
                minimized_dropped = False

                if cap_status != "ok":
                    _freeze_stay_clocks(decision.blackboard)
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
                    party=want_party,
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
                    _freeze_stay_clocks(decision.blackboard)
                    self._set_preview_hold("Paused")
                    publish("paused")
                    continue

                if is_cursor_paralyzed():
                    if not paralyzed_dropped:
                        executor.drop_mouse()
                        paralyzed_dropped = True
                    _freeze_stay_clocks(decision.blackboard)
                    # Capture/vision already ran; skip decide+act until cursor clears.
                    publish("cursor_paralyzed")
                    continue
                paralyzed_dropped = False

                _resume_stay_clocks(decision.blackboard)

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

                if self._party_leader_on() and not leader_setup_done:
                    leader_setup_done = True
                    try:
                        self._run_leader_party_setup(world)
                    except Exception as setup_exc:
                        self.log(f"Party invite setup failed: {setup_exc}")
                chat_kind = ""
                try:
                    chat_kind = self._drain_party_chat()
                except Exception as chat_exc:
                    self.log(f"Party chat queue failed: {chat_exc}")
                if self._party_leader_on():
                    try:
                        self._leader_invite_tick(
                            world, last_action, hold_chat=chat_kind == "invite"
                        )
                    except Exception as invite_exc:
                        self.log(f"Party invite tick failed: {invite_exc}")

                start_rally = (
                    getattr(self, "_start_rally", None)
                    if self._party_leader_on()
                    else None
                )
                if start_rally is not None and start_rally.state == "off":
                    try:
                        if self._leader_may_begin_start_rally(world):
                            self._begin_leader_start_rally(world, decision.blackboard)
                    except Exception as rally_exc:
                        start_rally.skip(f"failed: {rally_exc}")
                if leader_brain is not None:
                    try:
                        leader_brain.prepare(world, rally=start_rally)
                    except Exception as schedule_exc:
                        self.log(f"Party schedule prepare failed: {schedule_exc}")
                self._formation_hold = False
                help_scratch = getattr(decision.blackboard, "scratch", None)
                if isinstance(help_scratch, dict):
                    if self._party_leader_on():
                        help_scratch["party_help_open"] = True
                    else:
                        help_scratch.pop("party_help_open", None)
                turret_anchor = getattr(
                    getattr(self, "_party_leader_ref", None), "turret_anchor", None
                )
                set_party_turret(
                    decision.blackboard,
                    self._leader_turret_on(),
                    map_id=last_logged_map_id,
                    anchor=turret_anchor,
                )
                if self._party_leader_on():
                    self._party_turret_info = turret_status(decision.blackboard)

                # Scroll land: solo always; party only while joining the leader's map.
                party_joining = (
                    party_brain is not None and party_brain.joining_map()
                )
                if party_brain is None or party_joining:
                    apply_talking_scroll_arrival(
                        decision.blackboard, config, state=world
                    )

                self._party_world = world
                if party_brain is not None:
                    # Socket is policy/rally only. Leader pose comes from party memory.
                    self._member_socket_pending()
                    self._member_party_tick(
                        world,
                        last_logged_map_id,
                        send=False,
                        party_brain=party_brain,
                        skip_accept=chat_kind == "accept",
                    )
                    self._arm_party_self_shop(
                        decision.blackboard,
                        str(getattr(party_brain.config, "seat_role", "") or ""),
                    )
                    party_brain.note_travel_click_failed(
                        bool(getattr(executor, "last_travel_click_failed", False))
                    )
                    action = party_brain.decide(world)
                    if self._party_comms.client is not None:
                        try:
                            self._member_state_report(world)
                        except Exception as supply_live_exc:
                            self.log(f"Party supply live send failed: {supply_live_exc}")
                    self._member_party_tick(
                        world,
                        last_logged_map_id,
                        send=True,
                        party_brain=party_brain,
                    )
                    party_joining = party_brain.joining_map()
                    self._publish_party_monitor(
                        party_brain=party_brain,
                        world=world,
                        action=action,
                        note="decide",
                    )
                elif leader_brain is not None:
                    self._arm_party_self_shop(decision.blackboard, "leader")
                    if self._party_leader_on():
                        try:
                            self._drain_party_reports(world)
                        except Exception as drain_exc:
                            self.log(f"Party leader drain failed: {drain_exc}")
                    supply_here = (
                        self._party_leader_on()
                        and self._party_hunt_open(world)
                        and not self._leader_supply_away(world, decision.blackboard)
                    )
                    hold = self._leader_supply_hold() if supply_here else None
                    claim = self._leader_supply_claim() if supply_here else None
                    from app._06_party.arrow_duty import leader_supply_action

                    action = leader_supply_action(
                        world, decision.blackboard, hold, claim
                    )
                    if action is None:
                        action = leader_brain.decide(world)
                        try:
                            action = self._leader_walk_party(
                                world, decision.blackboard, action, last_logged_map_id
                            )
                        except Exception as pace_exc:
                            self.log(f"Party leader pace failed: {pace_exc}")
                    try:
                        self._leader_party_tick(
                            world, decision.blackboard, last_logged_map_id
                        )
                    except Exception as party_tick_exc:
                        self.log(f"Party leader tick failed: {party_tick_exc}")
                    if self._party_leader_on():
                        try:
                            sent = self._party_comms.publish_decision(
                                action,
                                world,
                                map_id=last_logged_map_id,
                            )
                            if sent:
                                self.log(f"Party leader decision sent: {sent}")
                        except Exception as party_exc:
                            self.log(f"Party leader decision send failed: {party_exc}")
                else:
                    decision.blackboard.scratch.pop("party_self_shop_blocked", None)
                    decision.blackboard.scratch.pop("party_arrow_shop_covered", None)
                    action = decision.decide(world)
                if self._party_enabled() and party_role in ("member", "leader"):
                    try:
                        self._log_party_until_farm(
                            party_role=party_role,
                            party_brain=party_brain,
                            world=world,
                            action=action,
                        )
                    except Exception:
                        pass
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
                if self._farm_clock_gen == farm_clock_gen:
                    self._farm_clock = None
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



def _player_chat_name(world, snapshot) -> str:
    """Local character name for invite skip / leader check / member hello."""
    from app._06_party.member_identity import my_player_name

    seen = my_player_name(getattr(world, "last_print_state", None) if world is not None else None)
    if seen:
        return seen
    player = getattr(world, "player", None) if world is not None else None
    identity = getattr(player, "identity", None)
    name = str(getattr(identity, "name", None) or "").strip()
    if name:
        return name
    name = str(getattr(player, "species_name", None) or "").strip()
    if name:
        return name
    return ""
