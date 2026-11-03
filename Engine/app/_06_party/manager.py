"""Party member brain — decide one ActionIntent per tick (solo DecisionManager peer)."""
from __future__ import annotations

import random
import time
from collections import deque
from typing import Any, Optional

from .assist import (
    assist_in_attack_range,
    assist_monster_tile,
    pick_assist_target,
    pick_solo_farm_target,
    resolve_self_defender,
    turret_member_focus,
)
from .config import PartyMemberConfig
from .follow_route import choose_follow_route, estimate_walk_cost
from .follow_field import FollowField, FollowFieldCache, field_radius
from .formation import MemberFormation
from .intents import intent_for_kind, plan_field_follow
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
from .party_log import get_logger as _party_logger
from .support import apply_party_support

_log = _party_logger("member")

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
        # Member's own profile knobs. The leader policy is an in-memory overlay
        # on top; it is never written back to the profile.
        self.base_config = self.config
        self.leader_policy: Optional[dict[str, Any]] = None
        self.runtime = MemberRuntime()
        self.world_origin: Any = None
        self._rng = random.Random()
        self.decision_history: deque[dict[str, Any]] = deque(maxlen=_DECISION_HISTORY)
        self._join_nav = PartyJoinNav()
        self._field_cache = FollowFieldCache()
        self._formation = MemberFormation()
        # Solo DecisionManager blackboard — required for WORLD_NAV join (scroll/gate).
        self._nav_blackboard: Any = None

    def configure(self, config: PartyMemberConfig | dict | None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)
        self.base_config = self.config
        self.leader_policy = None

    def apply_leader_policy(self, policy: dict[str, Any], *, self_name: str = "") -> None:
        """Overlay leader ``party_policy`` on the member's own knobs (temporary)."""
        merged = self.base_config.merge_leader_policy(policy, self_name=self_name)
        self.config = self.config.with_knobs_from(merged)
        self.leader_policy = dict(policy)

    def clear_leader_policy(self) -> bool:
        """Back to the member's own knobs. Returns True when an overlay was active."""
        if self.leader_policy is None:
            return False
        self.config = self.config.with_knobs_from(self.base_config)
        self.leader_policy = None
        return True

    def reset_for_new_leader_session(self) -> None:
        """Leader bot started again: back to own knobs, forget the old leader trail.

        The new policy is applied on top right after (same tick when it arrived
        with the session change).
        """
        self.clear_leader_policy()
        self._formation.reset()
        self.runtime.own_hunt_id = None

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
            "farm_mode": self.config.farm_mode,
            "leader_mode": self.config.leader_mode,
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

        follow_field: Optional[FollowField] = None
        leader_walk_dist: Optional[int] = None
        if (
            leader_tile is not None
            and leader_dist is not None
            and bool(view.same_map)
            and game_state is not None
        ):
            follow_field = self._follow_field(game_state, origin, leader_tile, cfg)
            if follow_field is not None:
                leader_walk_dist = follow_field.walk_distance(
                    (int(origin.x), int(origin.y)), int(leader_dist)
                )
        else:
            self._field_cache.clear()
        self.runtime.leader_walk_dist = leader_walk_dist

        # Retreat HP gate uses the solo survival line. Heal / buff stay in place.
        from .loot import (
            party_closest_looter_filter,
            party_loot_first,
            party_loot_ownership_filter,
        )

        loot_first = party_loot_first(cfg)
        loot_item_ok = None
        if dead or bool(self.runtime.paused):
            loot_own = None
        elif loot_first:
            # Party drops count as own for the closest non-leader, non-wizard.
            loot_item_ok = party_closest_looter_filter(
                game_state, origin, self.runtime.local_map_id
            )
            loot_own = False if loot_item_ok is not None else None
        else:
            loot_own = party_loot_ownership_filter(cfg)
        if (
            not dead
            and not bool(self.runtime.paused)
            and game_state is not None
            and self._nav_blackboard is not None
        ):
            from .loot import arm_party_loot_side

            from .support import party_critical_escape

            escape = party_critical_escape(game_state, self._nav_blackboard)
            if escape is not None:
                self.runtime.last_kind = "retreat"
                self.runtime.last_reason = str(
                    getattr(escape, "reason", "") or "critical retreat"
                )
                self.runtime.approach_goal = None
                self.runtime.chasing = False
                self._record_decision(escape)
                return escape

            support = apply_party_support(
                game_state,
                self._nav_blackboard,
                allow_buffs=True,
            )
            # Side F4 only when leader is not fighting (same gate as primary
            # loot). Solo farm picks up its own drops during fights too.
            if loot_own is not None and (cfg.solo_farm or not bool(view.farming)):
                try:
                    arm_party_loot_side(
                        game_state,
                        self._nav_blackboard,
                        ownership_filter=bool(loot_own),
                        item_ok=loot_item_ok,
                    )
                except Exception as exc:
                    _log.debug("party loot side failed: %s", exc)
            # Potions / F4 loot stay on blackboard.side_intents for the executor.
            need_potion = False
            need_heal, need_buff = self._support_flags(support)
        else:
            support = None
            need_heal = False
            need_buff = False
            need_potion = self._need_potion(player, cfg)

        if not need_heal and not need_buff:
            gather = self._maybe_hunt_gather(game_state, dead=dead)
            if gather is not None:
                return gather

        threat = None
        if cfg.defend_self and game_state is not None:
            threat = resolve_self_defender(game_state, origin=origin)

        leader_in_ui = leader is not None
        assist_obj = None
        assist_src = "none"
        prev_assist_id = self.runtime.assist_track_id
        # Solo farm needs the leader on-screen for leash geometry.
        # Party farm assist uses contested (etview) / print_state via leader proxy.
        if cfg.solo_farm and leader_in_ui and game_state is not None and origin_ok:
            # Solo farm: own nearest target around the leader, not the leader's.
            try:
                assist_obj = pick_solo_farm_target(
                    game_state,
                    origin=origin,
                    leader_tile=leader_tile,
                    leash_tiles=int(cfg.assist_leash_tiles),
                    previous_id=self.runtime.assist_track_id,
                    blackboard=self._nav_blackboard,
                )
            except Exception as exc:
                _log.debug("party solo farm target failed: %s", exc)
                assist_obj = None
            assist_src = "solo_farm" if assist_obj is not None else "none"
        elif (
            not cfg.solo_farm
            and game_state is not None
            and bool(view.same_map)
            and (leader_in_ui or bool(view.guid or cfg.leader_guid or view.name))
        ):
            assist_obj, assist_src = pick_assist_target(
                game_state,
                leader_proxy_for_assist(leader, cfg, view),
                cfg,
                origin=origin,
                blackboard=self._nav_blackboard,
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

        from .farm_yard import (
            clamp_to_yard,
            in_yard,
            tile_from_obj,
            yard_half_extents,
        )

        half_w, half_h = yard_half_extents(
            int(cfg.party_size),
            half_w=cfg.yard_half_w,
            half_h=cfg.yard_half_h,
            scale_with_roster=bool(cfg.yard_scale_with_roster),
        )
        me_tile = (
            (int(origin.x), int(origin.y)) if origin_ok and origin is not None else None
        )
        in_farm_yard = True
        target_in_yard = True
        if cfg.turret_farm and leader_tile is not None:
            in_farm_yard = in_yard(
                me_tile, leader_tile, half_w=half_w, half_h=half_h
            )
            tgt_tile = tile_from_obj(assist_obj, origin)
            if tgt_tile is None and close_in_tile is not None:
                tgt_tile = close_in_tile
            target_in_yard = (
                True
                if tgt_tile is None
                else in_yard(tgt_tile, leader_tile, half_w=half_w, half_h=half_h)
            )
            if close_in_tile is not None and target_in_yard:
                close_in_tile = clamp_to_yard(
                    close_in_tile, leader_tile, half_w=half_w, half_h=half_h
                )

        # Turret, leader idle: hunt inside the yard. A mob already started is
        # finished after the leader begins an attack, then assist takes over.
        # Loot, when the leader is idle and this member has not swung yet,
        # is chosen later and does not set ``own_hunt_id``.
        self._turret_own_pending = None
        if (
            cfg.turret_farm
            and not cfg.solo_farm
            and leader_tile is not None
            and game_state is not None
            and origin_ok
        ):
            own_obj = None
            own_ok = False
            own_id = self.runtime.own_hunt_id
            if own_id is not None:
                own_obj = game_state.get_object(int(own_id))
                own_tile = tile_from_obj(own_obj, origin)
                from app._06_party.assist import _assist_target_live

                own_ok = bool(
                    _assist_target_live(game_state, own_obj)
                    and own_tile is not None
                    and in_yard(own_tile, leader_tile, half_w=half_w, half_h=half_h)
                )
            yard_id = None
            yard_obj = None
            if not view.farming:
                def _in_this_yard(obj: Any) -> bool:
                    tile = tile_from_obj(obj, origin)
                    return tile is not None and in_yard(
                        tile, leader_tile, half_w=half_w, half_h=half_h
                    )

                try:
                    yard_obj = pick_solo_farm_target(
                        game_state,
                        origin=origin,
                        leader_tile=leader_tile,
                        leash_tiles=int(cfg.assist_leash_tiles),
                        previous_id=own_id,
                        blackboard=self._nav_blackboard,
                        contains=_in_this_yard,
                    )
                except Exception as exc:
                    _log.debug("turret own hunt failed: %s", exc)
                    yard_obj = None
                if yard_obj is not None:
                    yard_id = int(getattr(yard_obj, "track_id", 0) or 0) or None
            focus, keep = turret_member_focus(
                leader_farming=bool(view.farming),
                own_id=own_id,
                own_still_ok=own_ok,
                yard_id=yard_id,
            )
            if focus == "own_finish" and own_obj is not None:
                assist_obj = own_obj
                assist_src = "own_finish"
                self.runtime.own_hunt_id = keep
            elif focus == "yard" and yard_obj is not None:
                assist_obj = yard_obj
                assist_src = "turret_own"
                self._turret_own_pending = keep
                if self.runtime.own_hunt_id is not None:
                    self.runtime.own_hunt_id = keep
            else:
                self.runtime.own_hunt_id = None
            if assist_obj is not None and focus in ("own_finish", "yard"):
                self.runtime.assist_track_id = int(
                    getattr(assist_obj, "track_id", 0) or 0
                ) or None
                self.runtime.assist_src = assist_src
                tgt_tile = tile_from_obj(assist_obj, origin)
                target_in_yard = tgt_tile is not None and in_yard(
                    tgt_tile, leader_tile, half_w=half_w, half_h=half_h
                )
                if not assist_in_attack_range(game_state, assist_obj):
                    need_combat_step = True
                    close_in_tile = assist_monster_tile(assist_obj, origin)
                    if close_in_tile is not None and target_in_yard:
                        close_in_tile = clamp_to_yard(
                            close_in_tile,
                            leader_tile,
                            half_w=half_w,
                            half_h=half_h,
                        )
                else:
                    need_combat_step = False
                    close_in_tile = None
        elif not cfg.turret_farm or cfg.solo_farm:
            self.runtime.own_hunt_id = None

        seat = self._turret_seat_tile(
            cfg,
            leader_tile=leader_tile if leader_present else None,
            half_w=half_w,
            half_h=half_h,
        )
        self.runtime.turret_seat = seat
        assist_sticky = (
            assist_obj is not None
            and prev_assist_id is not None
            and self.runtime.assist_track_id == prev_assist_id
        )
        off_turret_seat = False
        if seat is not None and me_tile is not None and assist_obj is None:
            from .follow import ARRIVAL_TOLERANCE as _SEAT_TOL

            off_turret_seat = (
                max(abs(me_tile[0] - seat[0]), abs(me_tile[1] - seat[1]))
                > _SEAT_TOL
            )

        leader_stopped = self._leader_looks_stopped(
            leader_tile=leader_tile if leader_present else None,
            farming=bool(view.farming),
        )
        # Close on the leader. Behind-slot / cardinal stand / turret seat are
        # not click goals — they walked the member around or past the leader.
        self._update_settle_stand(
            game_state,
            origin,
            leader_tile=None,
            active=False,
            cfg=cfg,
            field=None,
        )
        from .follow import tile_chebyshev

        if origin_ok and leader_tile is not None and self.runtime.approach_goal is not None:
            me = (int(origin.x), int(origin.y))
            goal = self.runtime.approach_goal
            if tile_chebyshev(goal, leader_tile) > tile_chebyshev(me, leader_tile):
                self.runtime.approach_goal = None
        self._formation_trail_tile(
            cfg, leader_tile=leader_tile if leader_present else None
        )
        self.runtime.travel_offset = None
        self.runtime.scratch.pop("travel_lateral", None)
        stand = None

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
                need_heal=need_heal,
                need_buff=need_buff,
                leader_in_ui=leader_in_ui,
                leader_other_map=leader_other_map,
                leader_farming=bool(view.farming),
                leader_stopped=leader_stopped,
                at_settle_stand=None,
                at_travel_spot=None,
                leader_walk_dist=leader_walk_dist if leader_present else None,
                need_combat_step=need_combat_step,
                solo_farm=cfg.solo_farm,
                in_farm_yard=in_farm_yard,
                target_in_yard=target_in_yard,
                assist_sticky=assist_sticky,
                off_turret_seat=off_turret_seat,
                leader_pose_stale="sticky" in str(view.source or ""),
            )
        )
        self.runtime.chasing = result.chasing
        if result.kind is MemberKind.HEAL and support is not None:
            return self._return_support(support, MemberKind.HEAL)
        if result.kind is MemberKind.BUFF and support is not None:
            return self._return_support(support, MemberKind.BUFF)
        reason = result.reason
        if result.kind is MemberKind.ASSIST:
            reason = f"{reason} src={assist_src}"
        if result.kind is MemberKind.CLOSE_IN:
            reason = f"{reason} src={assist_src}"
        if view.source and result.kind is MemberKind.FOLLOW:
            reason = f"{reason} via={view.source}"

        walk_now = leader_walk_dist if leader_walk_dist is not None else leader_dist
        if cfg.solo_farm:
            # Own drops within the follow leash; a pickup walk in progress
            # outranks the stand/spot re-follow until the leash breaks.
            loot_busy = (
                self._nav_blackboard is not None
                and getattr(self._nav_blackboard, "current_item_id", None) is not None
            )
            can_loot_now = (
                walk_now is not None
                and int(walk_now) <= int(cfg.follow_tiles)
                and (
                    result.kind is MemberKind.HOLD
                    or (result.kind is MemberKind.FOLLOW and loot_busy)
                )
            )
            loot_max_tiles = max(4, int(cfg.follow_tiles))
        elif loot_first:
            # Loot before follow: assist / close-in / defend / join still win.
            can_loot_now = walk_now is not None and result.kind in (
                MemberKind.HOLD,
                MemberKind.FOLLOW,
            )
            loot_max_tiles = max(4, int(cfg.follow_tiles))
        else:
            # Party farm: loot when the leader is idle (stopped / not farming)
            # and the member is holding inside the stop band.
            near_stop = False
            if leader_dist is not None and int(leader_dist) <= int(cfg.stop_tiles):
                near_stop = True
            if (
                leader_walk_dist is not None
                and int(leader_walk_dist) <= int(cfg.stop_tiles)
            ):
                near_stop = True
            can_loot_now = (
                result.kind is MemberKind.HOLD
                and not bool(view.farming)
                and bool(leader_stopped)
                and near_stop
            )
            loot_max_tiles = max(4, int(cfg.stop_tiles) + 2)

        # Turret idle, before the first swing: pick up, otherwise self-hunt.
        if (
            cfg.turret_farm
            and not cfg.solo_farm
            and not bool(view.farming)
            and self.runtime.own_hunt_id is None
            and getattr(self, "_turret_own_pending", None)
            and loot_own is not None
        ):
            can_loot_now = True
            loot_max_tiles = max(4, int(cfg.follow_tiles))

        # Abort sticky loot when movement / combat / defend must win.
        if (
            not can_loot_now
            and result.kind
            in (
                MemberKind.FOLLOW,
                MemberKind.CLOSE_IN,
                MemberKind.ASSIST,
                MemberKind.JOIN_MAP,
                MemberKind.DEFEND,
                MemberKind.WAIT,
                MemberKind.STOP,
                MemberKind.HEAL,
                MemberKind.BUFF,
                MemberKind.POTION,
            )
            and self._nav_blackboard is not None
        ):
            from .loot import clear_party_loot_sticky

            clear_party_loot_sticky(self._nav_blackboard)

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
                    max_tiles=loot_max_tiles,
                    item_ok=loot_item_ok,
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

        pending_own = getattr(self, "_turret_own_pending", None)
        if pending_own is not None and self.runtime.own_hunt_id is None:
            self.runtime.own_hunt_id = pending_own

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
            field_plan = None
            if (
                result.kind is MemberKind.FOLLOW
                and stand is None
                and follow_field is not None
                and origin_ok
            ):
                try:
                    field_plan = plan_field_follow(
                        follow_field,
                        origin,
                        stop_steps=max(1, int(cfg.stop_tiles)),
                        previous_goal=self.runtime.approach_goal,
                        previous_hop=self.runtime.follow_hop,
                    )
                except Exception as exc:
                    _log.debug("party field follow failed: %s", exc)
                    field_plan = None
            if field_plan is not None:
                intent, goal, detail, self.runtime.follow_hop = field_plan
            else:
                self.runtime.follow_hop = None
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
                    settle_stand=stand,
                    stand_reason=(
                        "follow_settle" if leader_stopped else "follow_close"
                    ),
                    mid_act=(
                        result.kind
                        in (MemberKind.ASSIST, MemberKind.DEFEND, MemberKind.CLOSE_IN)
                        and prev_assist_id is not None
                        and self.runtime.assist_track_id == prev_assist_id
                    ),
                )
            if result.kind is MemberKind.FOLLOW and detail == "no_path":
                self.runtime.approach_goal = None
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
        kind_now = str(self.runtime.last_kind or "")
        reason_now = str(self.runtime.last_reason or "")
        prev = self.runtime.scratch.get("_party_log_kind_reason")
        cur = (kind_now, reason_now)
        if prev != cur:
            self.runtime.scratch["_party_log_kind_reason"] = cur
            _log.info(
                "tick=%s kind=%s reason=%s",
                self.runtime.tick,
                kind_now or "—",
                reason_now or "—",
            )
        else:
            _log.debug(
                "tick=%s kind=%s reason=%s",
                self.runtime.tick,
                kind_now or "—",
                reason_now or "—",
            )
        return intent

    def decide_survival(self, game_state: Any) -> Any:
        """HP only: wait for the leader socket without follow or combat.

        Crisis retreat and in-place heal/buff/potion sides. No gather, assist,
        or world-nav. ``apply_hp_actions`` is not called except through
        ``party_critical_escape`` at the retreat gate.
        """
        from .intents import idle
        from .support import party_critical_escape

        self.runtime.tick += 1
        self.runtime.chasing = False
        self.runtime.approach_goal = None
        if game_state is not None and self._nav_blackboard is not None:
            escape = party_critical_escape(game_state, self._nav_blackboard)
            if escape is not None:
                self.runtime.last_kind = "retreat"
                self.runtime.last_reason = str(
                    getattr(escape, "reason", "") or "critical retreat"
                )
                self._record_decision(escape)
                return escape
            support = apply_party_support(
                game_state,
                self._nav_blackboard,
                allow_buffs=True,
            )
            if support is not None:
                _heal, need_buff = self._support_flags(support)
                return self._return_support(
                    support,
                    MemberKind.BUFF if need_buff else MemberKind.HEAL,
                )
        intent = idle("waiting_leader_socket")
        self.runtime.last_kind = "wait"
        self.runtime.last_reason = "waiting_leader_socket"
        self._record_decision(intent)
        return intent

    def _rally_yields_to_combat(self) -> bool:
        """Start rally must not block assist when the leader is already fighting.

        Same map + known leader tile + farming (or a live target). Far members
        then follow the fighter; in-leash members assist. Other-map join and
        idle rally waits still walk to the pin. Arrival is not marked here, so
        after the fight the member can finish the last tiles to the rally.
        """
        if not bool(self.runtime.leader_same_map):
            return False
        if self.runtime.leader_dist is None:
            return False
        if bool(self.runtime.leader_farming):
            return True
        return bool(str(self.runtime.leader_target_name or "").strip())

    def _maybe_hunt_gather(self, game_state: Any, *, dead: bool) -> Any:
        """Walk to the leader's rally point unless combat is already happening.

        Recovery is not handled here.
        """
        if dead or self.runtime.paused:
            return None
        try:
            from app._06_party.comms.orders import member_orders
        except Exception:
            return None
        order = member_orders.gather
        if order is None:
            return None
        rally_reason = f"party_rally_{order.get('stage') or 'point'}"
        if member_orders.arrived:
            return None
        try:
            from app._04_decision.world_nav.session import live_pose_from_state
        except Exception:
            return None
        pose = live_pose_from_state(game_state)
        if pose is not None and member_orders.near(pose.map_id, pose.x, pose.y):
            member_orders.mark_arrived()
            self._join_nav.clear()
            self.runtime.last_kind = "hold"
            self.runtime.last_reason = f"{rally_reason}_arrived"
            return None
        if self._rally_yields_to_combat():
            prev = self.runtime.scratch.get("_rally_yield")
            note = (
                f"{rally_reason}_yield_combat "
                f"dist={self.runtime.leader_dist} "
                f"target={self.runtime.leader_target_name or '—'}"
            )
            if prev != note:
                self.runtime.scratch["_rally_yield"] = note
                _log.info("%s", note)
            return None
        self.runtime.scratch.pop("_rally_yield", None)
        try:
            map_id = int(order.get("map_id"))
            dest_x = int(order.get("x"))
            dest_y = int(order.get("y"))
        except (TypeError, ValueError):
            return None
        intent = self._join_nav.tick(
            game_state,
            self._nav_blackboard,
            dest_map=map_id,
            dest_x=dest_x,
            dest_y=dest_y,
            reason=rally_reason,
        )
        self.runtime.last_kind = "join_map"
        self.runtime.last_reason = str(getattr(intent, "reason", "") or rally_reason)
        self.runtime.chasing = False
        self._record_decision(intent)
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
    def _support_flags(support: Any) -> tuple[bool, bool]:
        """``(need_heal, need_buff)`` from a stashed support intent."""
        from app._02_state.enums import ActionType

        act = getattr(support, "action", None) if support is not None else None
        if act is ActionType.BUFF:
            return False, True
        if support is not None:
            return True, False
        return False, False

    def _return_support(self, support: Any, kind: MemberKind) -> Any:
        self.runtime.last_kind = kind.value
        self.runtime.last_reason = str(
            getattr(support, "reason", "") or kind.value
        )
        self.runtime.approach_goal = None
        self.runtime.chasing = False
        self._record_decision(support)
        return support

    @staticmethod
    def _need_potion(player: Any, cfg: PartyMemberConfig) -> bool:
        if not cfg.use_hp_potion or player is None:
            return False
        try:
            ratio = float(getattr(player, "hp_ratio", 1.0) or 1.0)
        except (TypeError, ValueError):
            return False
        return ratio <= float(cfg.potion_hp_ratio)

    def _follow_field(
        self,
        game_state: Any,
        origin: Any,
        leader_tile: tuple[int, int],
        cfg: PartyMemberConfig,
    ) -> Optional[FollowField]:
        """Cached walk field around the leader; bodies (not me/leader) block."""
        try:
            from app._04_decision.nav_config import get_terrain_map

            from .intents import _occupied_tiles

            terrain = get_terrain_map()
            if terrain is None:
                return None
            me = (int(origin.x), int(origin.y))
            bodies = [t for t in _occupied_tiles(game_state, origin) if t != me]
            return self._field_cache.get(
                terrain,
                (int(leader_tile[0]), int(leader_tile[1])),
                field_radius(cfg.follow_tiles),
                bodies,
            )
        except Exception as exc:
            _log.debug("party follow field failed: %s", exc)
            return None

    def _formation_trail_tile(
        self,
        cfg: PartyMemberConfig,
        *,
        leader_tile: Optional[tuple[int, int]],
    ) -> Optional[tuple[int, int]]:
        """Moving mode in a narrow area: this seat's tile on the leader's trail."""
        rt = self.runtime
        if cfg.turret_farm or leader_tile is None:
            self._formation.reset()
            rt.formation = ""
            return None
        try:
            from app._04_decision.nav_config import get_terrain_map

            self._formation.observe(
                get_terrain_map(), (int(leader_tile[0]), int(leader_tile[1]))
            )
            target = self._formation.target(cfg.seat_index)
        except Exception as exc:
            _log.debug("party formation failed: %s", exc)
            rt.formation = ""
            return None
        rt.formation = f"{target.kind}:{target.reason}"
        return target.tile

    def _turret_seat_tile(
        self,
        cfg: PartyMemberConfig,
        *,
        leader_tile: Optional[tuple[int, int]],
        half_w: int,
        half_h: int,
    ) -> Optional[tuple[int, int]]:
        """Radial seat for this roster slot while the leader is in turret mode."""
        if not cfg.turret_farm or cfg.seat_index is None or leader_tile is None:
            self.runtime.turret_seat_bad = None
            return None
        try:
            from app._04_decision.nav_config import get_terrain_map

            from .turret_seat import seat_radius, turret_seat

            bad = self.runtime.turret_seat_bad
            return turret_seat(
                get_terrain_map(),
                (int(leader_tile[0]), int(leader_tile[1])),
                cfg.seat_index,
                int(cfg.party_size),
                radius=seat_radius(half_w, half_h),
                avoid=(bad,) if bad is not None else (),
            )
        except Exception as exc:
            _log.debug("party turret seat failed: %s", exc)
            return None

    def _update_settle_stand(
        self,
        game_state: Any,
        origin: Any,
        *,
        leader_tile: Optional[tuple[int, int]],
        active: bool,
        cfg: PartyMemberConfig,
        field: Optional[FollowField] = None,
    ) -> Optional[tuple[int, int]]:
        """Keep one random cardinal stand per stopped leader tile."""
        rt = self.runtime
        if not active or leader_tile is None or origin is None:
            rt.settle_stand = None
            rt.settle_leader_tile = None
            rt.settle_blocked.clear()
            return None
        tile = (int(leader_tile[0]), int(leader_tile[1]))
        if rt.settle_leader_tile != tile:
            rt.settle_stand = None
            rt.settle_blocked.clear()
            rt.settle_leader_tile = tile
        try:
            from .intents import pick_settle_stand

            rt.settle_stand = pick_settle_stand(
                game_state,
                origin,
                tile,
                cfg,
                previous=rt.settle_stand,
                rng=self._rng,
                exclude=rt.settle_blocked,
                field=field,
            )
        except Exception as exc:
            _log.debug("party settle stand failed: %s", exc)
            rt.settle_stand = None
        return rt.settle_stand

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
            scratch.pop("leader_move_dir", None)
            return False
        tile = (int(leader_tile[0]), int(leader_tile[1]))
        prev = scratch.get("leader_tile_seen")
        if prev != tile:
            if prev is not None:
                try:
                    px, py = int(prev[0]), int(prev[1])
                    dx, dy = tile[0] - px, tile[1] - py
                    if dx or dy:
                        scratch["leader_move_dir"] = (dx, dy)
                except (TypeError, ValueError, IndexError):
                    pass
            scratch["leader_tile_seen"] = tile
            scratch["leader_tile_seen_at"] = now
            return False
        seen_at = float(scratch.get("leader_tile_seen_at") or now)
        return (now - seen_at) >= float(settle_sec)

    def _leader_move_dir(self) -> Optional[tuple[int, int]]:
        """Last leader tile delta (facing while walking); None until first step."""
        raw = self.runtime.scratch.get("leader_move_dir")
        if not isinstance(raw, tuple) or len(raw) != 2:
            return None
        try:
            dx, dy = int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
        if dx == 0 and dy == 0:
            return None
        return (dx, dy)

    def _travel_lateral(self, move_dir: Optional[tuple[int, int]]) -> int:
        """Sticky flank (-1/0/1) for the Reynolds formation slot."""
        scratch = self.runtime.scratch
        raw = scratch.get("travel_lateral")
        if raw in (-1, 0, 1):
            return int(raw)
        # Prefer a slight side so we do not sit on the leader's path.
        choices = (-1, 1, 0)
        lat = int(self._rng.choice(choices))
        scratch["travel_lateral"] = lat
        del move_dir  # reserved for future facing-aware side picks
        return lat


__all__ = ["PartyMemberManager"]
