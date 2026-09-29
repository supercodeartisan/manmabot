"""State machine logic for decision making."""
from __future__ import annotations

from typing import Optional

from app._03_world import (
    GameState, WorldState, ActionType, Position,
    REIDENTIFY_RADIUS, ATTACK_RANGE, LOOT_OR_NOT_RADIUS
)
from app._04_decision.types import ActionIntent
from app._04_decision.legacy.evaluators import (
    combat_evaluate,
    loot_evaluate,
    navigation_evaluate,
    survival_evaluate,
)
from app._03_world.objects import distance_squared, ObjectType


class StateMachine:
    """Handles state transitions for each action type."""

    def __init__(self):
        pass

    def handle_idle(self, game_state: GameState) -> ActionIntent:
        """IDLE -> SEARCHING/TRAVELING"""
        ws = game_state.world_state
        nav_result = navigation_evaluate(ws)
        if nav_result:
            return nav_result
        return ActionIntent(action=ActionType.IDLE, priority=0.0, reason="idle")

    def handle_combat(self, game_state: GameState, memory_enemy_id: int | None) -> ActionIntent:
        """COMBAT state with re-identification and target switching."""
        ws = game_state.world_state
        player = ws.player
        if player is None:
            return self.handle_idle(game_state)

        weak_monsters = ws.weak_monsters
        items = ws.items()

        # Re-identify previous enemy
        current_enemy = None
        if memory_enemy_id is not None:
            current_enemy = game_state.get_object(memory_enemy_id)

        # If previous enemy still valid and nearby, keep targeting it
        if current_enemy and current_enemy.object_type is ObjectType.MONSTER:
            dist_sq = distance_squared(current_enemy.position, player.position)
            if dist_sq <= REIDENTIFY_RADIUS * REIDENTIFY_RADIUS:
                # Check for closer weak monster
                nearest_weak = self._nearest_weak_monster(ws, player.position)
                if nearest_weak and nearest_weak.track_id != current_enemy.track_id:
                    dist_to_new = distance_squared(nearest_weak.position, player.position)
                    dist_to_current = distance_squared(current_enemy.position, player.position)
                    if dist_to_new < dist_to_current * 0.5:
                        return self._combat_action(nearest_weak, mid_act=False)
                return self._combat_action(current_enemy, mid_act=True)

        # No valid previous enemy - pick nearest weak monster
        nearest_weak = self._nearest_weak_monster(ws, player.position)
        if nearest_weak:
            return self._combat_action(nearest_weak, mid_act=False)

        # No weak monsters - check for items to loot
        if items:
            nearest_item = min(items, key=lambda i: distance_squared(i.position, player.position))
            return ActionIntent(
                action=ActionType.LOOTING,
                target_id=nearest_item.track_id,
                priority=0.4,
                reason="combat ended, switching to loot",
            )

        # Nothing to do - search/travel
        nav_result = navigation_evaluate(ws)
        if nav_result:
            return nav_result

        return self._combat_action(None, mid_act=False)

    def handle_looting(self, game_state: GameState, memory_item_id: int | None) -> ActionIntent:
        """LOOTING state with re-identification and combat awareness."""
        ws = game_state.world_state
        player = ws.player
        if player is None:
            return self.handle_idle(game_state)

        weak_monsters = ws.weak_monsters
        items = ws.items()

        current_item = None
        if memory_item_id is not None:
            current_item = game_state.get_object(memory_item_id)

        nearest_enemy = self._nearest_weak_monster(ws, player.position)
        nearest_item = min(items, key=lambda i: distance_squared(i.position, player.position)) if items else None

        # Combat takes priority if enemy in range
        if nearest_enemy:
            enemy_dist_sq = distance_squared(nearest_enemy.position, player.position)
            attack_range_sq = ATTACK_RANGE * ATTACK_RANGE
            loot_or_not_sq = LOOT_OR_NOT_RADIUS * LOOT_OR_NOT_RADIUS

            if nearest_item:
                item_dist_sq = distance_squared(nearest_item.position, player.position)
                if enemy_dist_sq <= attack_range_sq:
                    if not (item_dist_sq < enemy_dist_sq and item_dist_sq < loot_or_not_sq):
                        return self._combat_action(nearest_enemy, mid_act=False)

            if not nearest_item:
                return self._combat_action(nearest_enemy, mid_act=False)

        # Re-identify item target
        target_item = nearest_item
        if current_item and target_item:
            if distance_squared(current_item.position, target_item.position) <= REIDENTIFY_RADIUS * REIDENTIFY_RADIUS:
                target_item = current_item

        if target_item:
            return ActionIntent(
                action=ActionType.LOOTING,
                target_id=target_item.track_id,
                priority=0.4,
                reason="loot target",
            )

        # No items - check for enemies
        if nearest_enemy:
            return self._combat_action(nearest_enemy, mid_act=False)

        # Nothing to do - search/travel
        nav_result = navigation_evaluate(ws)
        if nav_result:
            return nav_result

        return ActionIntent(action=ActionType.IDLE, priority=0.0, reason="nothing to do")

    def handle_searching(self, game_state: GameState) -> ActionIntent:
        """SEARCHING state - look for enemies/items while moving."""
        ws = game_state.world_state
        player = ws.player
        if player is None:
            return self.handle_idle(game_state)

        weak_monsters = ws.weak_monsters
        items = ws.items()

        # Enemy found -> COMBAT
        if weak_monsters:
            nearest = self._nearest_weak_monster(ws, player.position)
            if nearest:
                return self._combat_action(nearest, mid_act=False)

        # Item found -> LOOTING
        if items:
            nearest = min(items, key=lambda i: distance_squared(i.position, player.position))
            return ActionIntent(
                action=ActionType.LOOTING,
                target_id=nearest.track_id,
                priority=0.4,
                reason="item found while searching",
            )

        # Continue searching with navigation
        nav_result = navigation_evaluate(ws)
        if nav_result:
            return nav_result

        return ActionIntent(action=ActionType.SEARCHING, priority=0.1, reason="continue searching")

    def handle_traveling(self, game_state: GameState) -> ActionIntent:
        """TRAVELING state - same as SEARCHING but with destination."""
        return self.handle_searching(game_state)

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _nearest_weak_monster(self, ws: WorldState, origin: Position) -> Optional[object]:
        """Find nearest weak monster to origin."""
        weak_monsters = ws.weak_monsters
        if not weak_monsters:
            return None
        return min(weak_monsters, key=lambda m: distance_squared(m.position, origin))

    def _combat_action(self, enemy, mid_act: bool) -> ActionIntent:
        """Create combat action intent."""
        if enemy is None:
            return ActionIntent(action=ActionType.COMBAT, priority=0.5, reason="combat (no target)")
        return ActionIntent(
            action=ActionType.COMBAT,
            target_id=enemy.track_id,
            priority=0.5,
            reason="combat target",
            mid_act=mid_act,
        )