"""Read live player game xy for shopping editors (Fill NPC from memory)."""

from __future__ import annotations


def read_player_game_xy() -> tuple[int, int]:
    """Absolute LC tile from the process-wide monitor (never ``fresh`` / never close).

    Opening a private ``PerceptionSensors`` and ``close()``-ing it while the
    practice tool already holds a monitor handle can native-crash. Prefer
    :func:`shared_sensors` and ``pull_player(fresh=False)``.
    """
    from app._01_perception.sensors import shared_sensors
    from app._03_world.merge.memory_sync import player_game_xy_from_snapshot

    sensors = shared_sensors()
    if not bool(getattr(sensors, "_memory_enabled", False)):
        raise RuntimeError("memory.enabled is false in Engine/config")
    snap = sensors.pull_player(fresh=False)
    xy = player_game_xy_from_snapshot(snap or {})
    if xy is None:
        raise RuntimeError(
            "no player position yet (enter the game world; memory lamp green)"
        )
    return int(xy[0]), int(xy[1])
