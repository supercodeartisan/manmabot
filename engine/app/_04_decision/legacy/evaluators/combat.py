"""Combat evaluator: hunting behavior with re-identification and retreat."""
from __future__ import annotations

from app._04_decision.types import ActionIntent, ActionType
from app._03_world import WorldState, REIDENTIFY_RADIUS, ATTACK_RANGE
from app._03_world.objects import ObjectType, distance_squared


def evaluate(world_state: WorldState, memory_enemy_id: int | None = None) -> ActionIntent | None:
    """Return attack action toward nearest weak monster with re-identification."""
    player = world_state.player
    if player is None:
        return None

    weak_monsters = world_state.weak_monsters
    if not weak_monsters:
        return None

    # Re-identification: prefer previous target if still nearby
    target = None
    if memory_enemy_id is not None:
        prev_enemy = world_state.get_object(memory_enemy_id)
        if prev_enemy and prev_enemy.object_type is ObjectType.MONSTER:
            dist_sq = distance_squared(prev_enemy.position, player.position)
            if dist_sq <= REIDENTIFY_RADIUS * REIDENTIFY_RADIUS:
                target = prev_enemy

    # Otherwise pick nearest weak monster
    if target is None:
        target = min(
            weak_monsters,
            key=lambda m: distance_squared(m.position, player.position),
        )

    # Check if we should retreat (strong monsters nearby or low HP)
    strong_monsters = world_state.strong_monsters
    if strong_monsters and player.hp is not None and player.max_hp is not None:
        hp_ratio = player.hp / player.max_hp if player.max_hp > 0 else 1.0
        nearest_strong = min(
            strong_monsters,
            key=lambda m: distance_squared(m.position, player.position),
        )
        strong_dist_sq = distance_squared(nearest_strong.position, player.position)
        # Retreat if strong monster in attack range and HP is low
        if strong_dist_sq <= ATTACK_RANGE * ATTACK_RANGE and hp_ratio < 0.5:
            return ActionIntent(
                action=ActionType.RETREATING,
                target_id=nearest_strong.track_id,
                priority=0.8,
                reason="strong monster in range with low HP",
            )

    return ActionIntent(
        action=ActionType.ATTACK,
        target_id=target.track_id,
        priority=0.5,
        reason="nearest weak monster",
    )


def evaluate_retreat(world_state: WorldState, enemy_id: int) -> ActionIntent | None:
    """Evaluate retreat action away from enemy."""
    player = world_state.player
    if player is None:
        return None

    enemy = world_state.get_object(enemy_id)
    if enemy is None:
        return None

    # Flee in opposite direction from enemy
    return ActionIntent(
        action=ActionType.RETREATING,
        target_id=enemy_id,
        priority=0.7,
        reason="retreat from enemy",
        destination=_calculate_retreat_destination(player.position, enemy.position),
    )


def _calculate_retreat_destination(player_pos: Position, enemy_pos: Position) -> Position:
    """Calculate retreat destination away from enemy."""
    import random
    # Vector from enemy to player
    dx = player_pos.x - enemy_pos.x
    dy = player_pos.y - enemy_pos.y
    length = (dx * dx + dy * dy) ** 0.5

    if length > 0:
        # Normalize and extend
        offset = 0.15  # normalized distance
        dx = dx / length * offset + random.uniform(-0.03, 0.03)
        dy = dy / length * offset + random.uniform(-0.03, 0.03)
    else:
        dx = 0.15 + random.uniform(-0.03, 0.03)
        dy = random.uniform(-0.03, 0.03)

    # Clamp to valid range (0-1 normalized)
    dest_x = max(0.1, min(0.9, player_pos.x + dx))
    dest_y = max(0.1, min(0.9, player_pos.y + dy))

    return Position(x=dest_x, y=dest_y)