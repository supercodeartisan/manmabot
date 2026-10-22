"""Read live player game xy / mapId for shopping editors."""

from __future__ import annotations


def _player_snapshot() -> dict:
    """Shared monitor snapshot (never ``fresh`` / never close a private handle)."""
    from app._01_perception.sensors import shared_sensors

    sensors = shared_sensors()
    if not bool(getattr(sensors, "_memory_enabled", False)):
        raise RuntimeError("memory.enabled is false in Engine/config")
    snap = sensors.pull_player(fresh=False)
    if not isinstance(snap, dict) or not snap:
        raise RuntimeError(
            "no player snapshot yet (enter the game world; memory lamp green)"
        )
    return snap


def read_player_game_xy() -> tuple[int, int]:
    """Absolute LC tile from the process-wide monitor."""
    from app._03_world.merge.memory_sync import player_game_xy_from_snapshot

    snap = _player_snapshot()
    xy = player_game_xy_from_snapshot(snap)
    if xy is None:
        raise RuntimeError(
            "no player position yet (enter the game world; memory lamp green)"
        )
    return int(xy[0]), int(xy[1])


def read_player_map_id() -> int:
    """Live LC mapId via MapSubsystem (same path as world-nav)."""
    from app._03_world.merge.memory_sync import player_map_id_from_snapshot

    snap = _player_snapshot()
    mid = player_map_id_from_snapshot(snap)
    if mid is None:
        raise RuntimeError(
            "no player mapId yet (enter the game world; memory lamp green)"
        )
    return int(mid)
