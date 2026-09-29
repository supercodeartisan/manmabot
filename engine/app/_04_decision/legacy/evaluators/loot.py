"""Loot evaluator: item pickup with re-identification and threat awareness."""
from __future__ import annotations

from app._04_decision.types import ActionIntent, ActionType
from app._03_world import WorldState, REIDENTIFY_RADIUS, ATTACK_RANGE, LOOT_OR_NOT_RADIUS
from app._03_world.objects import ObjectType, distance_squared


def evaluate(
    world_state: WorldState,
    memory_item_id: int | None = None,
) -> ActionIntent | None:
    """Return pickup action with re-identification and combat awareness."""
    player = world_state.player
    if player is None:
        return None

    items = world_state.items()
    if not items:
        return None

    weak_monsters = world_state.weak_monsters

    # Re-identification: prefer previous target if still nearby
    target = None
    if memory_item_id is not None:
        prev_item = world_state.get_object(memory_item_id)
        if prev_item and prev_item.object_type is ObjectType.ITEM:
            dist_sq = distance_squared(prev_item.position, player.position)
            if dist_sq <= REIDENTIFY_RADIUS * REIDENTIFY_RADIUS:
                target = prev_item

    # Otherwise pick nearest item
    if target is None:
        target = min(
            items,
            key=lambda i: distance_squared(i.position, player.position),
        )

    # Combat awareness: check if enemy is in attack range
    if weak_monsters:
        nearest_enemy = min(
            weak_monsters,
            key=lambda m: distance_squared(m.position, player.position),
        )
        enemy_dist_sq = distance_squared(nearest_enemy.position, player.position)
        item_dist_sq = distance_squared(target.position, player.position)

        attack_range_sq = ATTACK_RANGE * ATTACK_RANGE
        loot_or_not_sq = LOOT_OR_NOT_RADIUS * LOOT_OR_NOT_RADIUS

        # If enemy in attack range, prioritize combat unless item is very close
        if enemy_dist_sq <= attack_range_sq:
            if not (item_dist_sq < enemy_dist_sq and item_dist_sq < loot_or_not_sq):
                return None  # Let combat evaluator handle it

    return ActionIntent(
        action=ActionType.PICKUP,
        target_id=target.track_id,
        priority=0.3,
        reason="nearest item",
    )


def evaluate_with_memory(
    world_state: WorldState,
    memory_item_id: int | None,
    memory_enemy_id: int | None,
) -> ActionIntent | None:
    """Full Lineage_bot-style loot evaluation with all memory checks."""
    player = world_state.player
    if player is None:
        return None

    items = world_state.items()
    weak_monsters = world_state.weak_monsters

    # Current memory targets
    mem_item = world_state.get_object(memory_item_id) if memory_item_id else None
    mem_enemy = world_state.get_object(memory_enemy_id) if memory_enemy_id else None

    # Nearest current targets
    nearest_item = min(items, key=lambda i: distance_squared(i.position, player.position)) if items else None
    nearest_enemy = min(weak_monsters, key=lambda m: distance_squared(m.position, player.position)) if weak_monsters else None

    # If enemy exists, check combat priority
    if nearest_enemy:
        enemy_dist_sq = distance_squared(nearest_enemy.position, player.position)
        attack_range_sq = ATTACK_RANGE * ATTACK_RANGE
        loot_or_not_sq = LOOT_OR_NOT_RADIUS * LOOT_OR_NOT_RADIUS

        if nearest_item:
            item_dist_sq = distance_squared(nearest_item.position, player.position)
            # Enemy in range and item not closer/safer -> combat
            if enemy_dist_sq <= attack_range_sq:
                if not (item_dist_sq < enemy_dist_sq and item_dist_sq < loot_or_not_sq):
                    return None

        # No items or enemy is the priority
        if not nearest_item:
            return None

    # Re-identify item target
    target = nearest_item
    if mem_item and target:
        if distance_squared(mem_item.position, target.position) <= REIDENTIFY_RADIUS * REIDENTIFY_RADIUS:
            target = mem_item

    if target:
        return ActionIntent(
            action=ActionType.PICKUP,
            target_id=target.track_id,
            priority=0.4,
            reason="loot target",
        )

    return None