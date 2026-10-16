"""Party member brain — decide one ActionIntent per tick (solo DecisionManager peer)."""
from __future__ import annotations

import logging
import random
import time
from collections import deque
from typing import Any, Optional

from .assist import (
    assist_in_attack_range,
    assist_monster_tile,
    pick_assist_target,
    resolve_self_defender,
)
from .config import PartyMemberConfig
from .follow_route import choose_follow_route, estimate_walk_cost
from .intents import intent_for_kind
from .join_map import PartyJoinNav
from .leader import (
    LeaderView,
    _party_game_xy,
    bind_leader_from_party,
    bind_leader_identity,
    leader_proxy_for_assist,
    party_member_block,
    resolve_leader,
)
from .policy import MemberKind, PolicyInput, decide_policy
from .state import MemberRuntime
from .support import apply_party_support

_log = logging.getLogger("party.member")

_DECISION_HISTORY = 20
# Keep last PartySubsystem pose when xy drops to 0,0 / missing (off-UI chase).
_STICKY_PARTY_POSE_SEC = 15.0
_STICKY_PARTY_POSE_OFF_UI_SEC = 45.0


class PartyMemberManager:
    """Independent member loop: follow leader + assist leader's fight.

    Only used when the session enabled party-member mode (Party tab).
    Solo ``DecisionManager`` is never called from here.
    """

    def __init__(self, config: PartyMemberConfig | dict | None = None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)
        self.runtime = MemberRuntime()
        self.world_origin: Any = None
        self._rng = random.Random()
        self.decision_history: deque[dict[str, Any]] = deque(maxlen=_DECISION_HISTORY)
        self._join_nav = PartyJoinNav()
        # Solo DecisionManager blackboard — required for WORLD_NAV join (scroll/gate).
        self._nav_blackboard: Any = None

    def configure(self, config: PartyMemberConfig | dict | None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)

    def pause(self) -> None:
        self.runtime.paused = True

    def resume(self) -> None:
        self.runtime.paused = False

    def set_world_origin(self, origin: Any) -> None:
        self.world_origin = origin
        bb = self._nav_blackboard
        if bb is not None and origin is not None:
            try:
                bb.world_origin = origin
            except Exception:
                pass

    def set_nav_blackboard(self, blackboard: Any) -> None:
        """Wire the session Blackboard so join-map can emit scroll/GATE intents."""
        self._nav_blackboard = blackboard
        if blackboard is not None and self.world_origin is not None:
            try:
                blackboard.world_origin = self.world_origin
            except Exception:
                pass

    def joining_map(self) -> bool:
        """True while WorldNav (other-map join or same-map scroll/TP follow) is active."""
        return bool(self._join_nav.active) or str(self.runtime.last_kind) in (
            "join_map",
            "follow_nav",
        )

    def set_local_map_id(self, map_id: Optional[int]) -> None:
        self.runtime.local_map_id = (
            int(map_id) if map_id is not None else None
        )

    def _apply_sticky_party_pose(self, view: LeaderView) -> None:
        """Refresh or reuse last PartySubsystem pose for off-screen follow."""
        now = time.time()
        rt = self.runtime
        # Always remember last good party/entity tile while we believe same map
        # (or map unknown). Cleared only when both map ids are known and differ.
        if view.tile is not None and view.same_map:
            rt.sticky_leader_tile = view.tile
            rt.sticky_leader_map_id = view.map_id
            rt.sticky_leader_pose_at = now
            return
        if not view.same_map:
            # Other map: join-nav uses live party xy; drop same-map sticky.
            rt.sticky_leader_tile = None
            rt.sticky_leader_map_id = None
            rt.sticky_leader_pose_at = 0.0
            return
        sticky = rt.sticky_leader_tile
        if sticky is None:
            return
        age = now - float(rt.sticky_leader_pose_at or 0.0)
        # Longer sticky while entity sweep lost the leader — keep chasing.
        limit = (
            _STICKY_PARTY_POSE_OFF_UI_SEC
            if view.entity is None
            else _STICKY_PARTY_POSE_SEC
        )
        if age > limit:
            return
        sticky_mid = rt.sticky_leader_map_id
        local = rt.local_map_id
        if (
            sticky_mid is not None
            and local is not None
            and int(sticky_mid) != int(local)
        ):
            return
        view.tile = sticky
        if view.map_id is None and sticky_mid is not None:
            view.map_id = int(sticky_mid)
        src = str(view.source or "").strip()
        view.source = f"{src}+sticky" if src else "party_sticky"

    def set_external_target(
        self,
        *,
        track_id: Optional[int] = None,
        ent: str = "",
    ) -> None:
        from dataclasses import replace

        self.config = replace(
            self.config,
            external_target_id=track_id,
            external_target_ent=ent,
        ).clamped()

    def status(self) -> dict[str, Any]:
        snap = self.runtime.status_dict()
        snap["config"] = {
            "enabled": self.config.enabled,
            "leader_name": self.config.leader_name,
            "leader_ent": self.config.leader_ent,
            "leader_guid": self.config.leader_guid,
            "leader_track_id": self.config.leader_track_id,
            "follow_tiles": self.config.follow_tiles,
            "stop_tiles": self.config.stop_tiles,
            "assist_leash_tiles": self.config.assist_leash_tiles,
        }
        snap["decision_history"] = list(self.decision_history)
        return snap

    def _record_decision(self, intent: Any) -> None:
        action = getattr(intent, "action", None)
        action_name = getattr(action, "value", None) or str(action or "")
        self.decision_history.append(
            {
                "at": time.time(),
                "tick": int(self.runtime.tick),
                "kind": str(self.runtime.last_kind or ""),
                "reason": str(self.runtime.last_reason or ""),
                "action": str(action_name),
                "target_id": getattr(intent, "target_id", None),
                "leader_name": str(self.runtime.leader_name_seen or ""),
                "leader_dist": self.runtime.leader_dist,
                "leader_source": str(self.runtime.leader_source or ""),
                "leader_hp": self.runtime.leader_hp,
                "leader_mp": self.runtime.leader_mp,
                "leader_ent": str(self.runtime.leader_ent or ""),
                "leader_guid": str(self.runtime.leader_guid or ""),
                "leader_farming": bool(self.runtime.leader_farming),
                "leader_target": str(self.runtime.leader_target_name or ""),
                "assist_track_id": self.runtime.assist_track_id,
                "assist_src": str(self.runtime.assist_src or ""),
                "assist_name": str(self.runtime.assist_name or ""),
            }
        )

    def decide(self, game_state: Any) -> Any:
        """Same contract as ``DecisionManager.decide`` → one ActionIntent."""
        self.runtime.tick += 1
        cfg = self.config.clamped()
        self.config = cfg

        player = getattr(game_state, "player", None) if game_state else None
        dead = self._is_dead(player)
        origin = self.world_origin
        origin_ok = origin is not None and hasattr(origin, "x")

        # Sticky party-memory identity first so ent/guid track survives farming.
        party_block = party_member_block(
            getattr(game_state, "last_party", None) if game_state else None,
            str(cfg.leader_name or ""),
        )
        if party_block is not None:
            self.config = bind_leader_from_party(cfg, party_block)
            cfg = self.config

        view = resolve_leader(
            game_state,
            cfg,
            origin=origin,
            local_map_id=self.runtime.local_map_id,
        )
        self._apply_sticky_party_pose(view)
        leader = view.entity
        if leader is not None:
            self.config = bind_leader_identity(cfg, leader)
            cfg = self.config
        if view.name:
            self.runtime.leader_name_seen = view.name
        self.runtime.leader_source = view.source
        self.runtime.leader_hp = view.hp
        self.runtime.leader_mp = view.mp
        self.runtime.leader_map_id = view.map_id
        self.runtime.leader_ent = view.ent or cfg.leader_ent
        self.runtime.leader_guid = view.guid or cfg.leader_guid
        self.runtime.leader_track_id = (
            view.track_id
            if view.track_id is not None
            else cfg.leader_track_id
        )
        self.runtime.leader_farming = bool(view.farming)
        self.runtime.leader_entity_visible = leader is not None
        self.runtime.leader_same_map = bool(view.same_map)
        self.runtime.leader_target_name = str(view.target_name or "")
        self.runtime.leader_target_guid = str(view.target_guid or "")
        self.runtime.leader_target_ent = str(view.target_ent or "")

        leader_tile = view.tile if view.present else None
        leader_dist: Optional[int] = None
        if leader_tile is not None and origin_ok:
            try:
                from app._03_world.space.world_coords import tile_chebyshev

                leader_dist = tile_chebyshev(
                    int(origin.x),
                    int(origin.y),
                    int(leader_tile[0]),
                    int(leader_tile[1]),
                )
            except Exception as exc:
                _log.debug("leader tile failed: %s", exc)
                leader_tile = None
                leader_dist = None

        self.runtime.leader_dist = leader_dist

        # Heal / buff / potion sides via solo helpers — never retreat/escape/tree.
        from .loot import party_loot_ownership_filter

        loot_own = (
            party_loot_ownership_filter(cfg)
            if (not dead and not bool(self.runtime.paused))
            else None
        )
        if (
            not dead
            and not bool(self.runtime.paused)
            and game_state is not None
            and self._nav_blackboard is not None
        ):
            from .loot import arm_party_loot_side

            support = apply_party_support(
                game_state,
                self._nav_blackboard,
                allow_buffs=True,
            )
            # Side F4 only when leader is not fighting (same gate as primary loot).
            if loot_own is not None and not bool(view.farming):
                try:
                    arm_party_loot_side(
                        game_state,
                        self._nav_blackboard,
                        ownership_filter=bool(loot_own),
                    )
                except Exception as exc:
                    _log.debug("party loot side failed: %s", exc)
            if support is not None:
                from app._02_state.enums import ActionType

                act = getattr(support, "action", None)
                if act is ActionType.HEAL:
                    self.runtime.last_kind = MemberKind.HEAL.value
                elif act is ActionType.BUFF:
                    self.runtime.last_kind = MemberKind.BUFF.value
                else:
                    self.runtime.last_kind = "support"
                self.runtime.last_reason = str(
                    getattr(support, "reason", "") or self.runtime.last_kind
                )
                self.runtime.approach_goal = None
                self.runtime.chasing = False
                self._record_decision(support)
                return support
            # Potions / F4 loot stay on blackboard.side_intents for the executor.
            need_potion = False
        else:
            need_potion = self._need_potion(player, cfg)

        threat = None
        if cfg.defend_self and game_state is not None:
            threat = resolve_self_defender(game_state, origin=origin)

        leader_in_ui = leader is not None
        assist_obj = None
        assist_src = "none"
        # Assist only when the leader is in the current UI (entity sweep).
        if leader_in_ui and game_state is not None:
            assist_obj, assist_src = pick_assist_target(
                game_state,
                leader_proxy_for_assist(leader, cfg, view),
                cfg,
                origin=origin,
            )
        self.runtime.assist_track_id = (
            int(getattr(assist_obj, "track_id", 0) or 0) if assist_obj else None
        )
        self.runtime.assist_src = assist_src
        if assist_obj is not None:
            self.runtime.assist_name = str(
                getattr(assist_obj, "species_name", None)
                or getattr(getattr(assist_obj, "identity", None), "name", None)
                or getattr(assist_obj, "label", None)
                or ""
            )
        else:
            self.runtime.assist_name = ""
        # Prefer concrete assist name; fall back to contested/etview target label.
        if not self.runtime.assist_name and self.runtime.leader_target_name:
            self.runtime.assist_name = self.runtime.leader_target_name

        leader_present = (
            view.same_map
            and leader_tile is not None
            and leader_dist is not None
        )
        # Only when both MapSubsystem and PartySubsystem ids are known and differ.
        leader_other_map = (
            not view.same_map
            and view.map_id is not None
            and self.runtime.local_map_id is not None
        )

        need_combat_step = False
        close_in_tile = None
        if assist_obj is not None:
            if not assist_in_attack_range(game_state, assist_obj):
                need_combat_step = True
                close_in_tile = assist_monster_tile(assist_obj, origin)

        leader_stopped = self._leader_looks_stopped(
            leader_tile=leader_tile if leader_present else None,
            farming=bool(view.farming),
        )

        result = decide_policy(
            PolicyInput(
                paused=bool(self.runtime.paused),
                dead=dead,
                origin_ok=origin_ok,
                leader_present=leader_present,
                leader_dist=leader_dist if leader_present else None,
                chasing=bool(self.runtime.chasing),
                need_potion=need_potion,
                self_threat=threat is not None,
                assist_ready=assist_obj is not None,
                config=cfg,
                leader_in_ui=leader_in_ui,
                leader_other_map=leader_other_map,
                leader_farming=bool(view.farming),
                leader_stopped=leader_stopped,
                need_combat_step=need_combat_step,
            )
        )
        self.runtime.chasing = result.chasing
        reason = result.reason
        if result.kind is MemberKind.ASSIST:
            reason = f"{reason} src={assist_src}"
        if result.kind is MemberKind.CLOSE_IN:
            reason = f"{reason} src={assist_src}"
        if view.source and result.kind is MemberKind.FOLLOW:
            reason = f"{reason} via={view.source}"

        # Abort sticky loot when movement / combat / defend must win.
        if (
            result.kind
            in (
                MemberKind.FOLLOW,
                MemberKind.CLOSE_IN,
                MemberKind.ASSIST,
                MemberKind.JOIN_MAP,
                MemberKind.DEFEND,
                MemberKind.WAIT,
                MemberKind.STOP,
            )
            and self._nav_blackboard is not None
        ):
            from .loot import clear_party_loot_sticky

            clear_party_loot_sticky(self._nav_blackboard)

        # Loot only when idle HOLD, leader not farming, settled within stop_tiles.
        can_loot_now = (
            result.kind is MemberKind.HOLD
            and not bool(view.farming)
            and leader_dist is not None
            and int(leader_dist) <= int(cfg.stop_tiles)
        )
        if (
            can_loot_now
            and loot_own is not None
            and game_state is not None
            and self._nav_blackboard is not None
        ):
            from .loot import try_party_hold_loot

            try:
                loot_intent = try_party_hold_loot(
                    game_state,
                    self._nav_blackboard,
                    ownership_filter=bool(loot_own),
                    max_tiles=max(4, int(cfg.stop_tiles) + 2),
                )
            except Exception as exc:
                _log.debug("party hold loot failed: %s", exc)
                loot_intent = None
            if loot_intent is not None:
                self.runtime.last_kind = "loot"
                self.runtime.last_reason = str(
                    getattr(loot_intent, "reason", "") or "loot"
                )
                self.runtime.approach_goal = None
                self._record_decision(loot_intent)
                return loot_intent

        party_xy = (
            _party_game_xy(party_block) if isinstance(party_block, dict) else None
        )
        dest_map = view.map_id
        if dest_map is None and isinstance(party_block, dict):
            try:
                dest_map = int(party_block.get("map_id"))
            except (TypeError, ValueError):
                dest_map = None

        use_world_nav = False
        route_detail = ""
        # Continue an in-flight WORLD_NAV follow/join until it finishes.
        if self._join_nav.active and result.kind in (
            MemberKind.FOLLOW,
            MemberKind.JOIN_MAP,
            MemberKind.WAIT,
        ):
            use_world_nav = dest_map is not None
        elif result.kind is MemberKind.JOIN_MAP and dest_map is not None:
            use_world_nav = True
            route_detail = "leader_other_map"
        elif (
            result.kind is MemberKind.FOLLOW
            and dest_map is not None
            and party_xy is not None
            and leader_dist is not None
        ):
            walk_cost = estimate_walk_cost(leader_dist) or int(leader_dist)
            choice = choose_follow_route(
                game_state,
                walk_cost=walk_cost,
                dest_map=int(dest_map),
                dest_game_x=int(party_xy[0]),
                dest_game_y=int(party_xy[1]),
            )
            route_detail = choice.reason
            use_world_nav = choice.mode == "world_nav"

        if use_world_nav and dest_map is not None:
            dest_x = dest_y = None
            if party_xy is not None:
                dest_x, dest_y = int(party_xy[0]), int(party_xy[1])
            intent = self._join_nav.tick(
                game_state,
                self._nav_blackboard,
                dest_map=int(dest_map),
                dest_x=dest_x,
                dest_y=dest_y,
                reason=(
                    "party_join_leader"
                    if result.kind is MemberKind.JOIN_MAP
                    else "party_follow_world_nav"
                ),
            )
            # Distinguish other-map join vs same-map scroll/TP follow in the UI.
            if result.kind is MemberKind.JOIN_MAP:
                self.runtime.last_kind = "join_map"
            else:
                self.runtime.last_kind = "follow_nav"
            detail = str(getattr(intent, "reason", "") or reason)
            if route_detail:
                detail = f"{detail} | {route_detail}"
            goal = None
            self.runtime.approach_goal = None
        else:
            # Local walk / hold / assist — abort any open WORLD_NAV session.
            self._join_nav.clear()
            self.runtime.last_kind = result.kind.value
            intent, goal, detail = intent_for_kind(
                result.kind,
                reason=reason,
                game_state=game_state,
                origin=origin,
                leader_tile=leader_tile,
                config=cfg,
                previous_goal=self.runtime.approach_goal,
                rng=self._rng,
                defend_id=(
                    int(getattr(threat, "track_id", 0) or 0)
                    if threat is not None
                    else None
                ),
                assist_id=self.runtime.assist_track_id,
                close_in_tile=close_in_tile,
            )
            if route_detail and result.kind is MemberKind.FOLLOW:
                detail = f"{detail} | {route_detail}"
            if result.kind in (MemberKind.FOLLOW, MemberKind.CLOSE_IN):
                self.runtime.approach_goal = goal
            elif result.kind in (
                MemberKind.HOLD,
                MemberKind.ASSIST,
                MemberKind.DEFEND,
                MemberKind.JOIN_MAP,
            ):
                self.runtime.approach_goal = None

        self.runtime.last_reason = detail or reason
        self._record_decision(intent)
        _log.debug(
            "party member tick=%s kind=%s reason=%s",
            self.runtime.tick,
            self.runtime.last_kind,
            self.runtime.last_reason,
        )
        return intent

    @staticmethod
    def _is_dead(player: Any) -> bool:
        if player is None:
            return False
        if getattr(player, "alive", True) is False:
            return True
        try:
            hp = getattr(player, "hp", None)
            if hp is not None and int(hp) <= 0:
                return True
        except (TypeError, ValueError):
            pass
        try:
            if float(getattr(player, "hp_ratio", 1.0) or 1.0) <= 0.0:
                return True
        except (TypeError, ValueError):
            pass
        return False

    @staticmethod
    def _need_potion(player: Any, cfg: PartyMemberConfig) -> bool:
        if not cfg.use_hp_potion or player is None:
            return False
        try:
            ratio = float(getattr(player, "hp_ratio", 1.0) or 1.0)
        except (TypeError, ValueError):
            return False
        return ratio <= float(cfg.potion_hp_ratio)

    def _leader_looks_stopped(
        self,
        *,
        leader_tile: Optional[tuple[int, int]],
        farming: bool,
        settle_sec: float = 0.7,
    ) -> bool:
        """True when leader pose is stable and not fighting (settle to stop_tiles)."""
        scratch = self.runtime.scratch
        now = time.time()
        if farming or leader_tile is None:
            scratch.pop("leader_tile_seen", None)
            scratch.pop("leader_tile_seen_at", None)
            return False
        tile = (int(leader_tile[0]), int(leader_tile[1]))
        prev = scratch.get("leader_tile_seen")
        if prev != tile:
            scratch["leader_tile_seen"] = tile
            scratch["leader_tile_seen_at"] = now
            return False
        seen_at = float(scratch.get("leader_tile_seen_at") or now)
        return (now - seen_at) >= float(settle_sec)


__all__ = ["PartyMemberManager"]
