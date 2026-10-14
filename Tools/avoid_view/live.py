"""Read-only live character and bodies. Never clicks and never changes nav state."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

_KINDS = {
    "Monster": "monster",
    "SummonedMonster": "monster",
    "InteractiveNPC": "npc",
    "PLAYER": "player",
    "Player": "player",
}


@dataclass
class LiveBody:
    tile: tuple[int, int]
    kind: str
    name: str
    step: IsoStep | None = None

    def world_xy(self, now: float | None = None) -> tuple[float, float]:
        if self.step is None:
            return float(self.tile[0]), float(self.tile[1])
        if now is None:
            now = time.monotonic()
        return _step_xy(self.step, now)

    def world_tile(self, now: float | None = None) -> tuple[int, int]:
        x, y = self.world_xy(now)
        return _nearest(x), _nearest(y)


# PRES_B iso: U = 48*(x+y) - 3145680, V = 24*(x-y). One step is 516ms.
_U_SCALE = 48.0
_V_SCALE = 24.0
_U_BIAS = 3145680.0
_STEP_S = 0.516


@dataclass
class IsoStep:
    """Nav-space endpoints of the current step, plus when A was committed."""

    ax: float
    ay: float
    bx: float
    by: float
    age_s: float
    seen_at: float


@dataclass
class LiveView:
    ok: bool = False
    message: str = "waiting for the game"
    map_id: int | None = None
    pack_id: str | None = None
    player: tuple[int, int] | None = None
    step: IsoStep | None = None
    bodies: list[LiveBody] = field(default_factory=list)

    def world_xy(self, now: float | None = None) -> tuple[float, float] | None:
        """Character position. Iso step while it is running, else the integer tile."""
        step = self.step
        if step is None:
            if self.player is None:
                return None
            return float(self.player[0]), float(self.player[1])
        if now is None:
            now = time.monotonic()
        return _step_xy(step, now)

    def world_tile(self, now: float | None = None) -> tuple[int, int] | None:
        xy = self.world_xy(now)
        if xy is None:
            return None
        return _nearest(xy[0]), _nearest(xy[1])


def _nav_tile(x: int, y: int, origin: tuple[int, int]) -> tuple[int, int]:
    from app._03_world.merge.memory_sync import game_to_nav

    return game_to_nav(int(x), int(y), origin=origin)


def iso_to_world(u: float, v: float) -> tuple[float, float]:
    """Inverse of U = 48*(x+y) - 3145680, V = 24*(x-y)."""
    sum_xy = (float(u) + _U_BIAS) / _U_SCALE
    diff_xy = float(v) / _V_SCALE
    return (sum_xy + diff_xy) * 0.5, (sum_xy - diff_xy) * 0.5


def world_to_iso(x: float, y: float) -> tuple[float, float]:
    return (_U_SCALE * (float(x) + float(y)) - _U_BIAS, _V_SCALE * (float(x) - float(y)))


def _nearest(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _step_xy(step: IsoStep, now: float) -> tuple[float, float]:
    elapsed = step.age_s + max(0.0, now - step.seen_at)
    t = min(1.0, max(0.0, elapsed / _STEP_S))
    return (
        step.ax + (step.bx - step.ax) * t,
        step.ay + (step.by - step.ay) * t,
    )


def _nav_float(x: float, y: float, origin: tuple[int, int]) -> tuple[float, float]:
    ix, iy = math.floor(x), math.floor(y)
    nx, ny = _nav_tile(ix, iy, origin)
    return nx + (x - ix), ny + (y - iy)


def _iso_step(player: dict, origin: tuple[int, int]) -> IsoStep | None:
    iso = player.get("iso")
    if not isinstance(iso, dict):
        return None
    try:
        au, av = float(iso["au"]), float(iso["av"])
        bu, bv = float(iso["bu"]), float(iso["bv"])
        age_ms = float(iso["age_ms"])
    except (KeyError, TypeError, ValueError):
        return None
    ax, ay = _nav_float(*iso_to_world(au, av), origin)
    bx, by = _nav_float(*iso_to_world(bu, bv), origin)
    return IsoStep(ax, ay, bx, by, max(0.0, age_ms) / 1000.0, time.monotonic())


class LiveReader:
    """Polls memory on one thread. The window reads ``latest``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest = LiveView()
        self._stop = threading.Event()
        self._origin = (0, 0)
        self._thread: threading.Thread | None = None
        self._print = None
        self._print_buf = None
        self._monitor = None

    def set_origin(self, origin: tuple[int, int]) -> None:
        with self._lock:
            self._origin = (int(origin[0]), int(origin[1]))

    def latest(self) -> LiveView:
        with self._lock:
            return self._latest

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="avoid-view-live", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
        if self._print is not None:
            shut = getattr(self._print, "_close", None)
            try:
                if callable(shut):
                    shut()
            except Exception:
                pass
            self._print = None
        if self._monitor is not None:
            try:
                self._monitor.close()
            except Exception:
                pass
            self._monitor = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            view = self._once()
            with self._lock:
                self._latest = view
            self._stop.wait(0.1)

    def _once(self) -> LiveView:
        with self._lock:
            origin = self._origin
        print_snap, print_err = self._print_snapshot()
        monitor_snap, monitor_err = self._monitor_snapshot()
        if print_snap is None and monitor_snap is None:
            detail = print_err or monitor_err or "game not attached"
            return LiveView(ok=False, message=detail)
        return _parse(print_snap, monitor_snap, origin)

    def _print_snapshot(self) -> tuple[dict | None, str]:
        try:
            if self._print is None:
                import ctypes

                from app._01_perception.print_state_reader import (
                    default_dll_path,
                    default_settings_path,
                )

                dll = default_dll_path()
                settings = default_settings_path()
                self._print = ctypes.CDLL(str(dll))
                snap = self._print.print_state_snapshot
                snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
                snap.restype = ctypes.c_int
                shut = self._print.print_state_shutdown
                shut.argtypes = []
                shut.restype = None
                self._print_cfg = str(settings).encode("utf-8")
                self._print_buf = ctypes.create_string_buffer(4 << 20)
                self._print._close = shut
            n = int(self._print.print_state_snapshot(self._print_cfg, self._print_buf, len(self._print_buf)))
        except Exception as exc:
            return None, f"entities: {exc}"
        if n == -2:
            return None, "entity list is too large"
        if n < 0 or self._print_buf is None:
            return None, "game not attached"
        import json

        try:
            data = json.loads(self._print_buf.raw[:n].decode("utf-8"))
        except Exception as exc:
            return None, f"entities: {exc}"
        return data if isinstance(data, dict) else None, ""

    def _monitor_snapshot(self) -> tuple[dict | None, str]:
        try:
            if self._monitor is None:
                from session.player_monitor import shared_monitor

                self._monitor = shared_monitor()
            data = self._monitor.snapshot(fresh=False)
        except Exception as exc:
            return None, f"character: {exc}"
        if not isinstance(data, dict):
            return None, "character not attached"
        return data, ""


def _parse(print_snap: dict | None, monitor_snap: dict | None, origin: tuple[int, int]) -> LiveView:
    from app._03_world.merge.memory_sync import player_game_xy_from_snapshot, player_map_id_from_snapshot
    from app._04_decision.world_nav.pack_ids import map_id_to_pack_id

    map_id = None
    if isinstance(monitor_snap, dict):
        map_id = player_map_id_from_snapshot(monitor_snap)
        if map_id is None and isinstance(monitor_snap.get("player"), dict):
            map_id = player_map_id_from_snapshot({"player": monitor_snap["player"]})
    pack_id = map_id_to_pack_id(int(map_id)) if map_id is not None else None

    player_raw = None
    if isinstance(print_snap, dict):
        player_raw = player_game_xy_from_snapshot(print_snap)
    if player_raw is None and isinstance(monitor_snap, dict):
        player_raw = player_game_xy_from_snapshot(monitor_snap)
        if player_raw is None and isinstance(monitor_snap.get("player"), dict):
            wrapped = monitor_snap if "x" in monitor_snap.get("player", {}) else {"player": monitor_snap["player"]}
            player_raw = player_game_xy_from_snapshot(wrapped)
    player = _nav_tile(player_raw[0], player_raw[1], origin) if player_raw else None
    raw_player = print_snap.get("player") if isinstance(print_snap, dict) else None
    step = _iso_step(raw_player, origin) if isinstance(raw_player, dict) else None
    if step is not None:
        player = LiveView(step=step).world_tile()

    bodies: list[LiveBody] = []
    if isinstance(print_snap, dict):
        for raw in print_snap.get("entities") or []:
            if not isinstance(raw, dict):
                continue
            kind = _KINDS.get(str(raw.get("class") or ""))
            if kind is None:
                continue
            world = raw.get("world") if isinstance(raw.get("world"), dict) else None
            if world is None:
                continue
            try:
                tile = _nav_tile(int(world["cx"]), int(world["cy"]), origin)
            except (KeyError, TypeError, ValueError):
                continue
            step_body = _iso_step(raw, origin)
            if step_body is not None:
                tile = LiveBody(tile=tile, kind=kind, name="", step=step_body).world_tile()
            if player is not None and tile == player:
                continue
            bodies.append(
                LiveBody(tile=tile, kind=kind, name=str(raw.get("name") or kind), step=step_body)
            )

    ok = player is not None or bool(bodies)
    if player is None and not bodies:
        message = "attached, no character tile yet"
    else:
        message = (
            f"mapId={map_id if map_id is not None else '-'}  "
            f"character={player if player else '-'}  "
            f"bodies={len(bodies)}"
        )
    return LiveView(
        ok=ok,
        message=message,
        map_id=map_id,
        pack_id=pack_id,
        player=player,
        step=step,
        bodies=bodies,
    )
