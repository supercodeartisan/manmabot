"""Party member brain — decide one ActionIntent per tick (solo DecisionManager peer)."""
from __future__ import annotations

import logging
import random
from typing import Any, Optional

from .assist import pick_assist_target, resolve_self_defender
from .config import PartyMemberConfig
from .intents import intent_for_kind
from .leader import bind_leader_identity, resolve_leader
from .policy import MemberKind, PolicyInput, decide_policy
from .state import MemberRuntime

_log = logging.getLogger("party.member")


class PartyMemberManager:
    """Independent member loop: follow leader + assist leader's fight.

    Only used when the session enabled party-member mode (Hunt UI checkbox).
    Solo ``DecisionManager`` is never called from here.
    """

    def __init__(self, config: PartyMemberConfig | dict | None = None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)
        self.runtime = MemberRuntime()
        self.world_origin: Any = None
        self._rng = random.Random()

    def configure(self, config: PartyMemberConfig | dict | None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)

    def pause(self) -> None:
        self.runtime.paused = True

    def resume(self) -> None:
        self.runtime.paused = False

    def set_world_origin(self, origin: Any) -> None:
        self.world_origin = origin

    def set_local_map_id(self, map_id: Optional[int]) -> None:
        self.runtime.local_map_id = (
            int(map_id) if map_id is not None else None
        )

    def set_external_target(
        self,
        *,
        track_id: Optional[int] = None,
        ent: str = "",
    ) -> None:
        cfg = self.config
        self.config = PartyMemberConfig(
            enabled=cfg.enabled,
            leader_name=cfg.leader_name,
            leader_ent=cfg.leader_ent,
            leader_track_id=cfg.leader_track_id,
            follow_start_tiles=cfg.follow_start_tiles,
            follow_stop_tiles=cfg.follow_stop_tiles,
            approach_tiles=cfg.approach_tiles,
            assist_leash_tiles=cfg.assist_leash_tiles,
            potion_hp_ratio=cfg.potion_hp_ratio,
            use_hp_potion=cfg.use_hp_potion,
            defend_self=cfg.defend_self,
            assist_leader_strikes=cfg.assist_leader_strikes,
            external_target_id=track_id,
            external_target_ent=ent,
        ).clamped()

    def status(self) -> dict[str, Any]:
        snap = self.runtime.status_dict()
        snap["config"] = {
            "enabled": self.config.enabled,
            "leader_name": self.config.leader_name,
            "leader_ent": self.config.leader_ent,
            "follow_start_tiles": self.config.follow_start_tiles,
            "follow_stop_tiles": self.config.follow_stop_tiles,
            "assist_leash_tiles": self.config.assist_leash_tiles,
        }
        return snap

    def decide(self, game_state: Any) -> Any:
        """Same contract as ``DecisionManager.decide`` → one ActionIntent."""
        self.runtime.tick += 1
        cfg = self.config.clamped()
        self.config = cfg

        player = getattr(game_state, "player", None) if game_state else None
        dead = self._is_dead(player)
        origin = self.world_origin
        origin_ok = origin is not None and hasattr(origin, "x")

        view = resolve_leader(
            game_state,
            cfg,
            origin=origin,
            local_map_id=self.runtime.local_map_id,
        )
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

        need_potion = self._need_potion(player, cfg)
        threat = None
        if cfg.defend_self and game_state is not None:
            threat = resolve_self_defender(game_state, origin=origin)

        assist_obj = None
        assist_src = "none"
        # Assist needs a visible leader entity (strike / external target).
        if leader is not None and game_state is not None:
            assist_obj, assist_src = pick_assist_target(
                game_state, leader, cfg, origin=origin
            )
        self.runtime.assist_track_id = (
            int(getattr(assist_obj, "track_id", 0) or 0) if assist_obj else None
        )

        leader_present = (
            view.same_map
            and leader_tile is not None
            and leader_dist is not None
        )

        from .policy import PolicyResult

        if not view.same_map and not dead and origin_ok and not self.runtime.paused:
            # Stay local: potions/defend still ok; do not follow across maps.
            if need_potion:
                result = PolicyResult(MemberKind.POTION, False, "self_potion")
            elif cfg.defend_self and threat is not None:
                result = PolicyResult(MemberKind.DEFEND, False, "defend_self")
            else:
                result = PolicyResult(MemberKind.WAIT, False, "leader_other_map")
        else:
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
                )
            )
        self.runtime.chasing = result.chasing
        self.runtime.last_kind = result.kind.value
        reason = result.reason
        if result.kind is MemberKind.ASSIST:
            reason = f"{reason} src={assist_src}"
        if view.source and result.kind is MemberKind.FOLLOW:
            reason = f"{reason} via={view.source}"

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
                int(getattr(threat, "track_id", 0) or 0) if threat is not None else None
            ),
            assist_id=self.runtime.assist_track_id,
        )
        if result.kind is MemberKind.FOLLOW:
            self.runtime.approach_goal = goal
        elif result.kind in (MemberKind.HOLD, MemberKind.ASSIST, MemberKind.DEFEND):
            self.runtime.approach_goal = None

        self.runtime.last_reason = detail or reason
        _log.debug(
            "party member tick=%s kind=%s reason=%s",
            self.runtime.tick,
            result.kind.value,
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
            hp = player.hp
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


__all__ = ["PartyMemberManager"]
