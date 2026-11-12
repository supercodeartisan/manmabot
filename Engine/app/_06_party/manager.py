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
from .follow import FOLLOW_STUCK_S, FOLLOW_UNSTICK_MEMORY
from .follow_route import choose_follow_route, estimate_walk_cost, estimate_walk_steps
from .follow_field import FollowField, FollowFieldCache, field_radius
from .formation import MemberFormation
from .formation_goal import (
    advance_heading,
    choose_formation_goal,
    closing_slot,
    nearer_lateral,
    signed_lateral,
)
from .intents import (
    intent_for_kind,
    plan_field_follow,
    plan_follow_unstick,
    plan_leader_hop,
    plan_slot_hop,
)
from .join_map import (
    PartyJoinNav,
    memory_leader_confirmed,
    suppress_join_while_invite,
    suppress_unconfirmed_leader,
)
from .leader import (
    LeaderView,
    _party_game_xy,
    bind_leader_from_party,
    bind_leader_identity,
    leader_proxy_for_assist,
    party_member_block,
    resolve_leader,
)
from .policy import MemberKind, PolicyInput, decide_policy, formation_returning
from .state import MemberRuntime
from .party_log import get_logger as _party_logger
from .support import apply_party_support

_log = _party_logger("member")


def mage_skips_party_assist(game_state: Any) -> bool:
    """A mage party member follows and defends. It does not take an assist target."""
    if game_state is None:
        return False
    from app._04_decision.mode_control import is_mage

    return is_mage(game_state)


def mage_list_heal_request(
    returning: bool, kind: MemberKind
) -> Optional[tuple[bool, bool]]:
    """``(cast_only, heals_only)`` for a mage's party-list support this tick.

    Catch-up asks only for a heal that can be cast from here. A buff, and a
    walk toward someone outside that range, wait until the slot. Stop, defend,
    and a potion do not ask.
    """
    if kind in (MemberKind.STOP, MemberKind.DEFEND, MemberKind.POTION):
        return None
    if returning:
        return (True, True)
    return (False, False)

_DECISION_HISTORY = 20
# A gap longer than this is not continued stationary evidence.
_MOTION_GAP_S = 30.0
# Follow ticks further apart than this do not add up to a stuck follow.
_FOLLOW_STUCK_GAP_S = 1.0
# Side line stays until the leader tile has been still this long.
FORMATION_STAND_SETTLE_S = 2.0


def _terrain_or_none() -> Any:
    try:
        from app._04_decision.nav_config import get_terrain_map

        return get_terrain_map()
    except Exception:
        return None


def _sample_age(now: float, seen_at: Any) -> Optional[float]:
    """Age of a successful sample. None on a clock change or a long gap."""
    try:
        then = float(seen_at)
    except (TypeError, ValueError):
        return None
    if then > now:
        return None
    age = now - then
    if age > _MOTION_GAP_S:
        return None
    return age


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
        # Same window without bodies: walls and fences only. Stand and leash read it.
        self._walk_cache = FollowFieldCache()
        self._walk_cost_memo: Optional[tuple[tuple[int, int, int, int], float, Optional[int]]] = None
        self._formation = MemberFormation()
        # Solo DecisionManager blackboard — required for WORLD_NAV join (scroll/gate).
        self._nav_blackboard: Any = None

    def configure(self, config: PartyMemberConfig | dict | None) -> None:
        self.config = PartyMemberConfig.from_mapping(config)
        self.base_config = self.config
        self.leader_policy = None

    def apply_leader_policy(self, policy: dict[str, Any], *, self_name: str = "") -> None:
        """Overlay leader ``party_policy`` on the member's own knobs (temporary)."""
        merged = self.base_config.merge_leader_policy(
            policy, self_name=self_name, resolve_seat=True
        )
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
        scratch = getattr(blackboard, "scratch", None)
        if isinstance(scratch, dict):
            scratch["party_player_ring"] = True
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
        """Remember the last live memory pose. Never copy it back onto ``view``."""
        rt = self.runtime
        if not view.same_map:
            rt.sticky_leader_tile = None
            rt.sticky_leader_map_id = None
            rt.sticky_leader_pose_at = 0.0
            return
        if not view.fresh or view.tile is None:
            return
        rt.sticky_leader_tile = view.tile
        rt.sticky_leader_map_id = view.map_id
        rt.sticky_leader_pose_at = time.monotonic()

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

    def note_travel_click_failed(self, failed: bool) -> None:
        """Previous travel click had no ground cursor. The next hop may click."""
        self.runtime.scratch["follow_click_failed"] = bool(failed)

    def _follow_hop_age(self) -> Optional[float]:
        """Seconds since the last follow click. None when no clock is running."""
        if self.runtime.follow_hop is None or self.runtime.follow_hop_at <= 0:
            return None
        return time.monotonic() - float(self.runtime.follow_hop_at)

    def _store_follow_hop(self, hop: Any, intent: Any) -> None:
        """Keep the hop. A new travel click restarts the one-second walk clock."""
        from app._02_state.enums import ActionType

        tile = None
        if isinstance(hop, tuple) and len(hop) == 2:
            tile = (int(hop[0]), int(hop[1]))
        self.runtime.follow_hop = tile
        clicked = getattr(intent, "action", None) is ActionType.TRAVELING
        if tile is None or not clicked:
            if tile is None:
                self.runtime.follow_hop_at = 0.0
            return
        self.runtime.follow_hop_at = time.monotonic()

    def decide(self, game_state: Any) -> Any:
        """Same contract as ``DecisionManager.decide`` → one ActionIntent.

        Heal, potions, retreat, and the retreat methods stay on each
        character's solo settings. The leader mage-heal line is separate.
        """
        return self._decide_party(game_state)

    def _decide_party(self, game_state: Any) -> Any:
        self.runtime.tick += 1
        self.runtime.duty_phase = "follow"
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
        walk_field: Optional[FollowField] = None
        leader_walk_dist: Optional[int] = None
        if (
            leader_tile is not None
            and leader_dist is not None
            and bool(view.same_map)
            and game_state is not None
        ):
            follow_field = self._follow_field(game_state, origin, leader_tile, cfg)
            walk_field = self._walk_field(leader_tile, cfg)
            if walk_field is not None:
                leader_walk_dist = walk_field.walk_distance(
                    (int(origin.x), int(origin.y)), int(leader_dist)
                )
        else:
            self._field_cache.clear()
            self._walk_cache.clear()
        self.runtime.leader_walk_dist = leader_walk_dist

        # Retreat HP gate uses the solo survival line. Heal / buff stay in place.
        from .loot import (
            party_closest_looter_filter,
            party_loot_ownership_filter,
        )

        loot_item_ok = None
        if dead or bool(self.runtime.paused):
            loot_own = None
        else:
            loot_own = party_loot_ownership_filter(cfg)
            if bool(cfg.random_loot) and loot_own is False:
                loot_item_ok = party_closest_looter_filter(
                    game_state, origin, self.runtime.local_map_id
                )
                if loot_item_ok is None:
                    loot_own = None
            if loot_own is not None and self._nav_blackboard is not None:
                self._nav_blackboard.scratch["party_loot_pickup"] = cfg.loot_pickup
                self._nav_blackboard.scratch["party_loot_weight"] = (
                    int(cfg.loot_weight_pct) / 100.0
                )
                from .arrow_policy import pile_reserved
                from .comms.orders import member_orders
                from .loot import stable_self_identity

                me = ""
                if origin_ok:
                    me, _me_guid = stable_self_identity(
                        getattr(game_state, "last_party", None),
                        (int(origin.x), int(origin.y)),
                        self.runtime.local_map_id,
                        player=getattr(game_state, "player", None),
                        print_state=getattr(game_state, "last_print_state", None),
                    )
                claim = member_orders.supply_drop
                if isinstance(claim, dict):
                    base_ok = loot_item_ok

                    def _leave_supply(item: Any, _base=base_ok, _claim=claim, _me=me) -> bool:
                        if pile_reserved(
                            item, origin, _claim, _me, self.runtime.local_map_id
                        ):
                            return False
                        return True if _base is None else bool(_base(item))

                    loot_item_ok = _leave_supply
        if (
            not dead
            and not bool(self.runtime.paused)
            and game_state is not None
            and self._nav_blackboard is not None
        ):
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

            from .arrow_duty import expire_supply_hold, note_care_pose, release_care_pose
            from .support import urgent_self_survival

            release_care_pose(self._nav_blackboard, game_state)
            care = urgent_self_survival(
                game_state,
                self._nav_blackboard,
                origin if origin_ok else None,
            )
            if care is not None:
                note_care_pose(self._nav_blackboard, game_state)
                expire_supply_hold(self)
                self.runtime.last_kind = "support"
                self.runtime.last_reason = str(
                    getattr(care, "reason", "") or "self care"
                )
                _log.info(
                    "care before supply action=%s reason=%s",
                    getattr(getattr(care, "action", None), "value", None)
                    or getattr(care, "action", None)
                    or "—",
                    self.runtime.last_reason,
                )
                self._record_decision(care)
                return care

            from .arrow_duty import (
                claim_names_me,
                recipient_hold_intent,
                remember_supply_stand,
                tick_shopkeeper_duty,
                tick_supply_pickup,
            )
            from .comms.orders import member_orders
            from .loot import stable_self_identity

            seat_name = ""
            seat_guid = ""
            if origin_ok:
                seat_name, seat_guid = stable_self_identity(
                    getattr(game_state, "last_party", None),
                    (int(origin.x), int(origin.y)),
                    self.runtime.local_map_id,
                    player=getattr(game_state, "player", None),
                    print_state=getattr(game_state, "last_print_state", None),
                )
            leaving = self.joining_map() or str(self.runtime.last_kind or "") == "retreat"
            hold = None if leaving else member_orders.supply_hold
            if claim_names_me(hold, seat_name, seat_guid):
                from .arrow_duty import _hold_confirmed, leader_hold_displaced

                left = leader_hold_displaced(
                    self._nav_blackboard, game_state, hold
                )
                if _hold_confirmed(self._nav_blackboard, hold):
                    remember_supply_stand(
                        self.runtime, hold, origin, self.runtime.local_map_id
                    )
                else:
                    self.runtime.supply_stand = None
                if left:
                    hold = None
            else:
                self.runtime.supply_stand = None
            picked = None if leaving else tick_supply_pickup(
                self, game_state, self_name=seat_name, self_guid=seat_guid
            )
            if picked is not None:
                self._record_decision(picked)
                return picked
            drop = member_orders.supply_drop
            if claim_names_me(hold, seat_name, seat_guid) and not claim_names_me(
                drop, seat_name, seat_guid
            ):
                waited = recipient_hold_intent(
                    game_state, self._nav_blackboard, hold, tracked=True
                )
                self.runtime.last_kind = "supply"
                self.runtime.last_reason = "supply hold"
                self._record_decision(waited)
                return waited
            if str(cfg.seat_role or "") == "shopkeeper":
                party_heal = self._opening_shopkeeper_heal(
                    game_state, origin if origin_ok else None
                )
                if party_heal is not None:
                    expire_supply_hold(self)
                    self.runtime.last_kind = "support"
                    self.runtime.last_reason = str(
                        getattr(party_heal, "reason", "") or "urgent party heal"
                    )
                    _log.info(
                        "urgent party heal before supply reason=%s",
                        self.runtime.last_reason,
                    )
                    self._record_decision(party_heal)
                    return party_heal
                duty = tick_shopkeeper_duty(self, game_state, self_name=seat_name)
                if duty is not None:
                    self._record_decision(duty)
                    return duty

            support = apply_party_support(
                game_state,
                self._nav_blackboard,
                allow_buffs=True,
            )
            # Side pickup waits until we know the leader is standing.
            # Potions stay on blackboard.side_intents for the executor.
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
            if assist_obj is None:
                from .assist import resolve_member_help_target
                from .loot import _self_row_name

                seat = ""
                if origin_ok and origin is not None:
                    seat = _self_row_name(
                        getattr(game_state, "last_party", None),
                        (int(origin.x), int(origin.y)),
                        self.runtime.local_map_id,
                    )
                helped = resolve_member_help_target(
                    game_state,
                    getattr(game_state, "last_party", None),
                    self_name=seat,
                    origin=origin,
                )
                if helped is not None:
                    assist_obj = helped
                    assist_src = "member_help"
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

        need_combat_step = (
            assist_obj is not None
            and not assist_in_attack_range(game_state, assist_obj)
        )

        from .farm_yard import (
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
            if tgt_tile is None:
                tgt_tile = assist_monster_tile(assist_obj, origin)
            target_in_yard = (
                True
                if tgt_tile is None
                else in_yard(tgt_tile, leader_tile, half_w=half_w, half_h=half_h)
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
                need_combat_step = not assist_in_attack_range(
                    game_state, assist_obj
                )
        elif not cfg.turret_farm or cfg.solo_farm:
            self.runtime.own_hunt_id = None

        if game_state is not None:
            from .assist import _assist_target_live, choose_help_target
            from .loot import _self_row_name

            current_fight = None
            for tid in (prev_assist_id, self.runtime.own_hunt_id):
                if tid is None:
                    continue
                try:
                    obj = game_state.get_object(int(tid))
                except Exception:
                    obj = None
                if _assist_target_live(game_state, obj):
                    current_fight = obj
                    break
            seat_name = ""
            if origin_ok and origin is not None:
                seat_name = _self_row_name(
                    getattr(game_state, "last_party", None),
                    (int(origin.x), int(origin.y)),
                    self.runtime.local_map_id,
                )
            helped, help_src = choose_help_target(
                game_state,
                getattr(game_state, "last_party", None),
                self_name=seat_name,
                origin=origin,
                current=current_fight,
                pending=assist_obj,
                pending_src=assist_src,
            )
            switched = helped is not assist_obj or help_src != assist_src
            if switched:
                assist_obj = helped
                assist_src = help_src
                if help_src in ("mage_help", "member_under_attack"):
                    self.runtime.own_hunt_id = None
                    self._turret_own_pending = None
                self.runtime.assist_track_id = (
                    int(getattr(assist_obj, "track_id", 0) or 0)
                    if assist_obj is not None
                    else None
                )
                self.runtime.assist_src = assist_src
                if assist_obj is not None:
                    self.runtime.assist_name = str(
                        getattr(assist_obj, "species_name", None)
                        or getattr(
                            getattr(assist_obj, "identity", None), "name", None
                        )
                        or getattr(assist_obj, "label", None)
                        or ""
                    )
                    need_combat_step = not assist_in_attack_range(
                        game_state, assist_obj
                    )
                    if cfg.turret_farm and leader_tile is not None:
                        tgt_tile = tile_from_obj(assist_obj, origin)
                        if tgt_tile is None:
                            tgt_tile = assist_monster_tile(assist_obj, origin)
                        target_in_yard = (
                            True
                            if tgt_tile is None
                            else in_yard(
                                tgt_tile,
                                leader_tile,
                                half_w=half_w,
                                half_h=half_h,
                            )
                        )
                else:
                    need_combat_step = False
                    self.runtime.assist_name = ""

        if mage_skips_party_assist(game_state):
            assist_obj = None
            assist_src = "none"
            need_combat_step = False
            self.runtime.assist_track_id = None
            self.runtime.assist_src = "none"
            self.runtime.assist_name = ""
            self.runtime.own_hunt_id = None
            self._turret_own_pending = None

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
        )
        formation_stopped = self._leader_looks_stopped(
            leader_tile=leader_tile if leader_present else None,
            settle_sec=FORMATION_STAND_SETTLE_S,
        )
        leader_moving = self._leader_is_moving(
            leader_tile if leader_present else None
        )
        self._update_settle_stand(
            game_state,
            origin,
            leader_tile=None,
            active=False,
            cfg=cfg,
            field=None,
        )
        from .follow import tile_chebyshev, unit8
        from .intents import _occupied_tiles

        form_leader = leader_tile if leader_present else None
        form_forward = self._leader_move_dir()
        scratch = self.runtime.scratch
        anchor = (
            cfg.formation_anchor_x is not None
            and cfg.formation_anchor_y is not None
            and cfg.formation_anchor_dx is not None
            and cfg.formation_anchor_dy is not None
        )
        if cfg.formation_hold and anchor:
            form_leader = (int(cfg.formation_anchor_x), int(cfg.formation_anchor_y))
            form_forward = (
                int(cfg.formation_anchor_dx),
                int(cfg.formation_anchor_dy),
            )
        elif leader_present and bool(scratch.get("leader_stepped")):
            heading, pending, run, committed = advance_heading(
                scratch.get("formation_heading"),
                scratch.get("formation_heading_pending"),
                int(scratch.get("formation_heading_run") or 0),
                form_forward,
            )
            if heading is not None:
                scratch["formation_heading"] = heading
            else:
                scratch.pop("formation_heading", None)
            if pending is not None:
                scratch["formation_heading_pending"] = pending
                scratch["formation_heading_run"] = int(run)
            else:
                scratch.pop("formation_heading_pending", None)
                scratch.pop("formation_heading_run", None)
            latched = scratch.get("formation_lateral")
            if (
                committed
                and heading is not None
                and isinstance(latched, int)
                and latched != 0
                and form_leader is not None
                and me_tile is not None
            ):
                scratch["formation_lateral"] = nearer_lateral(
                    form_leader, heading, latched, me_tile
                )
            if heading is not None:
                form_forward = heading
        elif scratch.get("formation_heading") is not None:
            form_forward = scratch.get("formation_heading")
        trail_tile = self._formation_trail_tile(cfg, leader_tile=form_leader)
        held = bool(formation_stopped or cfg.turret_farm)
        bodies: set[tuple[int, int]] = set()
        if game_state is not None and origin_ok:
            try:
                bodies = {
                    t
                    for t in _occupied_tiles(game_state, origin)
                    if me_tile is None or t != me_tile
                }
            except Exception:
                bodies = set()
        if cfg.formation_reform:
            self.runtime.scratch.pop("formation_slot", None)
            self.runtime.scratch.pop("formation_heading", None)
            self.runtime.scratch.pop("formation_heading_pending", None)
            self.runtime.scratch.pop("formation_heading_run", None)
            self.runtime.scratch.pop("formation_lateral", None)
        prev_form = str(self.runtime.formation or "")
        prev_kind = prev_form.split(":", 1)[0]
        prev_slot = self.runtime.scratch.get("formation_slot")
        formed = choose_formation_goal(
            form_leader,
            forward=form_forward,
            seat=cfg.seat_index,
            followers=max(1, int(cfg.party_size)),
            stopped=held,
            trail_tile=None if held else trail_tile,
            terrain=_terrain_or_none(),
            occupied=bodies,
            previous=None if cfg.formation_reform else prev_slot,
            previous_leader=self.runtime.scratch.get("formation_leader"),
            lateral=(
                None
                if cfg.formation_reform
                else self.runtime.scratch.get("formation_lateral")
            ),
        )
        previous_tile = None
        if isinstance(prev_slot, tuple) and len(prev_slot) == 2:
            previous_tile = (int(prev_slot[0]), int(prev_slot[1]))
        hop = None
        if (
            not held
            and origin_ok
            and leader_tile is not None
            and formed.tile is not None
            and previous_tile is not None
            and previous_tile != formed.tile
        ):
            try:
                _intent, _goal, _detail, hop = plan_slot_hop(
                    origin,
                    formed.tile,
                    previous_goal=self.runtime.approach_goal,
                    previous_hop=self.runtime.follow_hop,
                    kind=formed.kind,
                    leader_moved=bool(self.runtime.scratch.get("leader_stepped")),
                    state=game_state,
                )
            except Exception as exc:
                _log.debug("party slot probe failed: %s", exc)
                hop = None
        formed = closing_slot(
            held=held,
            previous=previous_tile,
            previous_kind=prev_kind,
            chosen=formed,
            origin=(int(origin.x), int(origin.y)) if origin_ok else None,
            hop=hop if isinstance(hop, tuple) else None,
            leader=leader_tile,
        )
        slot_tile = formed.tile
        if slot_tile is not None and leader_tile is not None:
            self.runtime.scratch["formation_slot"] = slot_tile
            self.runtime.scratch["formation_leader"] = (
                int(leader_tile[0]),
                int(leader_tile[1]),
            )
            frame = form_forward if isinstance(form_forward, tuple) else None
            if (
                formed.kind == "side"
                and frame is not None
                and len(frame) == 2
                and form_leader is not None
            ):
                recovered = signed_lateral(form_leader, frame, slot_tile)
                if recovered is not None:
                    self.runtime.scratch["formation_lateral"] = recovered
                    if self.runtime.scratch.get("formation_heading") is None:
                        faced = unit8(frame)
                        if faced != (0, 0):
                            self.runtime.scratch["formation_heading"] = faced
        elif not leader_present:
            self.runtime.scratch.pop("formation_slot", None)
            self.runtime.scratch.pop("formation_leader", None)
            self.runtime.scratch.pop("formation_heading", None)
            self.runtime.scratch.pop("formation_heading_pending", None)
            self.runtime.scratch.pop("formation_heading_run", None)
            self.runtime.scratch.pop("formation_lateral", None)
        self.runtime.formation = (
            f"{formed.kind}:{formed.reason}" if formed.kind != "none" else ""
        )
        self.runtime.travel_offset = slot_tile
        slot_dist = None
        if slot_tile is not None and me_tile is not None:
            slot_dist = tile_chebyshev(me_tile, slot_tile)
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
                leader_pose_stale=bool(leader_tile is not None and not view.fresh),
                slot_dist=slot_dist,
                slot_arrive=1 if formed.kind == "stand" else 0,
                leader_moving=leader_moving,
                catch_up=bool(self.runtime.scratch.get("catch_up")),
            )
        )
        returning = formation_returning(
            slot_dist, latched=bool(self.runtime.scratch.get("catch_up"))
        )
        self.runtime.scratch["catch_up"] = returning
        self.runtime.chasing = result.chasing
        if result.kind is MemberKind.HEAL and support is not None:
            return self._return_support(support, MemberKind.HEAL)
        if result.kind is MemberKind.BUFF and support is not None:
            return self._return_support(support, MemberKind.BUFF)
        if mage_skips_party_assist(game_state):
            request = mage_list_heal_request(returning, result.kind)
            if request is not None:
                cast_only, heals_only = request
                listed = self._party_list_heal(
                    game_state,
                    origin if origin_ok else None,
                    cast_only=cast_only,
                    heals_only=heals_only,
                )
                if listed is not None:
                    from app._02_state.enums import ActionType

                    kind = (
                        MemberKind.BUFF
                        if getattr(listed, "action", None) is ActionType.BUFF
                        else MemberKind.HEAL
                    )
                    return self._return_support(listed, kind)
        reason = result.reason
        if returning and result.kind is MemberKind.FOLLOW:
            reason = f"catch_up {reason}"
        if result.kind is MemberKind.ASSIST:
            reason = f"{reason} src={assist_src}"
        if view.source and result.kind is MemberKind.FOLLOW:
            reason = f"{reason} via={view.source}"

        # Assist already won above. Hold and follow yield to a pile.
        # A moving leader and a seat catch-up do not cancel that pile.
        from .loot import party_loot_radius, party_may_start_loot, party_should_drop_loot

        can_loot_now = party_may_start_loot(
            result.kind.value, allowed=loot_own is not None
        )
        loot_max_tiles = party_loot_radius(cfg) if can_loot_now else 0
        if (
            can_loot_now
            and game_state is not None
            and self._nav_blackboard is not None
        ):
            from .loot import arm_party_loot_side

            try:
                arm_party_loot_side(
                    game_state,
                    self._nav_blackboard,
                    ownership_filter=bool(loot_own),
                    item_ok=loot_item_ok,
                )
            except Exception as exc:
                _log.debug("party loot side failed: %s", exc)

        if (
            party_should_drop_loot(result.kind.value, allowed=loot_own is not None)
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

        party_fresh = (
            game_state is not None
            and getattr(game_state, "party_read_ok", None) is True
        )
        party_xy = (
            _party_game_xy(party_block)
            if party_fresh and isinstance(party_block, dict)
            else None
        )
        dest_map = view.map_id if party_fresh else None
        if (
            not party_fresh
            and self._join_nav.active
            and self._join_nav.target_key is not None
        ):
            # One missed memory read does not retarget an in-flight join.
            old_map, old_x, old_y = self._join_nav.target_key
            dest_map = old_map
            if old_x is not None and old_y is not None:
                party_xy = (int(old_x), int(old_y))

        use_world_nav = False
        route_detail = ""
        hold_join = bool(getattr(self.runtime, "hold_join_map", False))
        policy_name = ""
        if isinstance(self.leader_policy, dict):
            policy_name = str(self.leader_policy.get("leader_name") or "")
        confirmed = memory_leader_confirmed(policy_name, view.name)
        if hold_join:
            result = suppress_join_while_invite(
                result, self._join_nav, hold=True
            )
        elif not confirmed:
            result = suppress_unconfirmed_leader(
                result, self._join_nav, confirmed=False
            )
        if result.reason in ("invite_before_join", "party_leader_unconfirmed"):
            reason = result.reason
        # Continue an in-flight WORLD_NAV follow/join until it finishes.
        # An open invite, or a party row that is not the policy leader, does not scroll.
        if hold_join or not confirmed:
            pass
        elif self._join_nav.active and result.kind in (
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
            walk_cost = self._follow_walk_cost(
                origin, leader_tile, int(leader_dist), walk_field
            )
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
            self.runtime.scratch.pop("follow_stuck", None)
        else:
            # Local walk / hold / assist — abort any open WORLD_NAV session.
            self._join_nav.clear()
            self.runtime.last_kind = result.kind.value
            field_plan = None
            if (
                result.kind is MemberKind.FOLLOW
                and leader_tile is not None
                and origin_ok
            ):
                try:
                    field_plan = plan_leader_hop(
                        origin,
                        leader_tile,
                        previous_hop=self.runtime.follow_hop,
                        click_failed=bool(
                            self.runtime.scratch.get("follow_click_failed")
                        ),
                        hop_age_s=self._follow_hop_age(),
                        state=game_state,
                    )
                except Exception as exc:
                    _log.debug("party leader hop failed: %s", exc)
                    field_plan = None
            elif (
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
                        leader_moved=bool(self.runtime.scratch.get("leader_stepped")),
                        state=game_state,
                    )
                except Exception as exc:
                    _log.debug("party field follow failed: %s", exc)
                    field_plan = None
            if (
                result.kind is MemberKind.FOLLOW
                and leader_tile is not None
                and origin_ok
            ):
                try:
                    escape = self._follow_stuck_escape(
                        origin, leader_tile, walk_field, game_state
                    )
                except Exception as exc:
                    _log.debug("party follow unstick failed: %s", exc)
                    escape = None
                if escape is not None:
                    field_plan = escape
            else:
                self.runtime.scratch.pop("follow_stuck", None)
            if field_plan is not None:
                intent, goal, detail, hop = field_plan
                self._store_follow_hop(hop, intent)
            else:
                self._store_follow_hop(None, None)
                combat_obj = None
                if result.kind is MemberKind.ASSIST:
                    combat_obj = assist_obj
                elif result.kind is MemberKind.DEFEND:
                    combat_obj = threat
                if (
                    combat_obj is not None
                    and game_state is not None
                    and self._nav_blackboard is not None
                ):
                    from .assist import engage_like_solo

                    intent = engage_like_solo(
                        game_state,
                        self._nav_blackboard,
                        combat_obj,
                        reason=reason,
                        ignore_species=(
                            result.kind is MemberKind.ASSIST
                            and self.runtime.assist_src
                            in ("leader_attack", "leader_strike", "external")
                        ),
                    )
                    goal = None
                    detail = str(getattr(intent, "reason", "") or reason)
                else:
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
                        settle_stand=stand,
                        stand_reason=(
                            "follow_settle" if leader_stopped else "follow_close"
                        ),
                        mid_act=(
                            result.kind
                            in (MemberKind.ASSIST, MemberKind.DEFEND)
                            and prev_assist_id is not None
                            and self.runtime.assist_track_id == prev_assist_id
                        ),
                    )
            if result.kind is MemberKind.FOLLOW and detail == "no_path":
                self.runtime.approach_goal = None
            if route_detail and result.kind is MemberKind.FOLLOW:
                detail = f"{detail} | {route_detail}"
            if result.kind is MemberKind.FOLLOW:
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

    def _maybe_hunt_gather(self, game_state: Any, *, dead: bool) -> Any:
        """Rally pins are not member goals.

        Once party memory says this character is in the party, follow uses the
        leader row's live tile. A rally message does not change that.
        """
        del game_state, dead
        return None

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

    def _mage_list_heal_pct(self) -> int:
        """Leader line for healing other members."""
        return int(self.config.mage_heal_pct)

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

    def _note_list_heal(self, text: str) -> None:
        """Write a party-log line when the list-heal note changes."""
        prev = self.runtime.scratch.get("_list_heal_note")
        if prev == text:
            return
        self.runtime.scratch["_list_heal_note"] = text
        _log.info("list heal: %s", text)

    def _opening_shopkeeper_heal(self, game_state: Any, origin: Any) -> Any:
        """In-range urgent party heal for a mage who is also the shopkeeper.

        A walk toward the patient, a buff, and a routine list heal stay on
        the later tick. Town, a scroll, and a stall keep the shop trip.
        """
        if str(self.config.seat_role or "") != "shopkeeper":
            return None
        try:
            mage = mage_skips_party_assist(game_state)
        except Exception:
            mage = False
        if not mage:
            return None
        from .support import shop_floor_blocks_party_heal, urgent_list_heal_pct

        if shop_floor_blocks_party_heal(self._nav_blackboard):
            return None
        pct = urgent_list_heal_pct()
        if pct is None:
            return None
        return self._party_list_heal(
            game_state, origin, cast_only=True, below=pct, heals_only=True
        )

    def _party_list_heal(
        self,
        game_state: Any,
        origin: Any,
        *,
        cast_only: bool = False,
        below: Optional[int] = None,
        heals_only: bool = False,
    ) -> Any:
        """Checked support for another member: heal, cure, resurrection, or a buff."""
        if game_state is None:
            self._note_list_heal("skip no game")
            return None
        party = getattr(game_state, "last_party", None)
        hud = getattr(game_state, "last_party_hud", None)
        if not isinstance(party, dict) or not isinstance(hud, dict):
            self._note_list_heal("skip no party memory")
            return None
        if hud.get("open") is False:
            self._note_list_heal("skip party list closed")
            return None
        board = self._nav_blackboard
        heal_ready = True
        try:
            from app._04_decision.mode_control import mp_ratio
            from app._04_decision.spells import can_cast_spell, slot_ready

            if not can_cast_spell(game_state, role="heal", blackboard=board):
                ratio = mp_ratio(game_state)
                if ratio is None:
                    self._note_list_heal("skip mp unknown")
                else:
                    self._note_list_heal(f"skip mp {int(float(ratio) * 100)}%")
                return None
            if board is not None and not slot_ready(board, "heal", urgent=True):
                heal_ready = False
        except Exception as exc:
            self._note_list_heal(f"skip heal gate {exc}")
            return None
        if heals_only and not heal_ready:
            self._note_list_heal("skip heal slot not ready")
            return None
        if origin is None or self.runtime.local_map_id is None:
            self._note_list_heal("skip no pose")
            return None
        self_name = ""
        self_guid = ""
        try:
            from .loot import stable_self_identity

            self_name, self_guid = stable_self_identity(
                party,
                (int(origin.x), int(origin.y)),
                self.runtime.local_map_id,
                player=getattr(game_state, "player", None),
                print_state=getattr(game_state, "last_print_state", None),
            )
        except Exception:
            self_name = ""
            self_guid = ""
        from settings.party_mage_support import checked_skill_ids

        from .intents import list_support, plan_slot_hop
        from .mage_support import choose_party_support, remember_cast

        ledger = self.runtime.scratch.get("party_mage_ledger")
        if not isinstance(ledger, dict):
            ledger = {"maps": {}, "spells": {}}
            self.runtime.scratch["party_mage_ledger"] = ledger
        try:
            from .comms.orders import member_orders

            reports = list(getattr(member_orders, "party_buffs", None) or [])
        except Exception:
            reports = []
        heal_line = int(below) if below is not None else self._mage_list_heal_pct()
        choice, note = choose_party_support(
            party.get("members"),
            hud.get("slots"),
            self_guid=self_guid or None,
            self_name=self_name,
            here=(
                getattr(origin, "x", None),
                getattr(origin, "y", None),
                self.runtime.local_map_id,
            ),
            checked=checked_skill_ids(self.config.mage_support_skills),
            hotbar=getattr(game_state, "last_hotbar", None),
            reports=reports,
            ledger=ledger,
            below=heal_line,
            cast_only=bool(cast_only),
            heals_only=bool(heals_only),
            allow_heals=bool(heal_ready),
        )
        if choice is None:
            self._note_list_heal(note or "skip support")
            return None
        if choice.get("kind") == "step":
            self._note_list_heal(note)
            try:
                intent, goal, detail, hop = plan_slot_hop(
                    origin,
                    choice["goal"],
                    previous_goal=self.runtime.approach_goal,
                    previous_hop=self.runtime.follow_hop,
                    kind="heal_step",
                    state=game_state,
                )
            except Exception as exc:
                self._note_list_heal(f"skip step {exc}")
                return None
            self._join_nav.clear()
            self._store_follow_hop(hop, intent)
            self.runtime.approach_goal = goal
            self.runtime.chasing = False
            self.runtime.last_kind = "heal_step"
            self.runtime.last_reason = str(detail or "heal_step")
            self._record_decision(intent)
            return intent
        self._note_list_heal(note)
        spell = str(choice.get("spell") or "")
        if spell in ("heal", "heal_all") and board is not None:
            try:
                from app._04_decision.spells import mark_slot_used

                mark_slot_used(board, "heal")
            except Exception:
                pass
        if spell == "buff":
            try:
                remember_cast(
                    ledger,
                    int(choice.get("guid") or 0),
                    int(choice.get("skill_id") or 0),
                    time.time(),
                )
            except Exception:
                pass
        if board is not None:
            try:
                board.magic_last_cast = time.time()
            except Exception:
                pass
        from app._02_state.enums import ActionType

        action = ActionType.BUFF if spell == "buff" else ActionType.HEAL
        if spell == "heal_all":
            text = "heal all"
        elif spell == "heal":
            dist = choice.get("dist")
            dist_bit = f" dist={int(dist)}" if dist is not None else ""
            text = (
                f"list heal {choice.get('name')} hp={int(choice.get('hp_pct') or 0)}"
                f"{dist_bit}"
            )
        else:
            dist = choice.get("dist")
            dist_bit = f" dist={int(dist)}" if dist is not None else ""
            text = f"{spell} {choice.get('label')} {choice.get('name')}{dist_bit}"
        return list_support(
            text,
            action=action,
            click_x=choice.get("click_x"),
            click_y=choice.get("click_y"),
            hotbar_box=choice.get("box"),
            hotbar_key=choice.get("key") or None,
        )

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
        """Same drink line as solo: the recovery HP-potion row, not the party 50%."""
        del cfg
        from app._04_decision import player_mode as pm
        from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

        if not pm.USE_HP_POTION or player is None:
            return False
        try:
            ratio = float(getattr(player, "hp_ratio", 1.0) or 1.0)
        except (TypeError, ValueError):
            return False
        actions = pm.HP_ACTIONS or normalize_hp_actions(None)
        threshold = action_threshold(actions, "hp_potion")
        if threshold is None:
            return False
        return ratio <= float(threshold)

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

    def _walk_field(
        self,
        leader_tile: tuple[int, int],
        cfg: PartyMemberConfig,
    ) -> Optional[FollowField]:
        """Walk steps to the leader through walls and fences. Bodies do not block,
        so a crowd beside the leader does not make the member walk off."""
        try:
            from app._04_decision.nav_config import get_terrain_map

            terrain = get_terrain_map()
            if terrain is None:
                return None
            return self._walk_cache.get(
                terrain,
                (int(leader_tile[0]), int(leader_tile[1])),
                field_radius(cfg.follow_tiles),
            )
        except Exception as exc:
            _log.debug("party walk field failed: %s", exc)
            return None

    def _follow_walk_cost(
        self,
        origin: Any,
        leader_tile: Optional[tuple[int, int]],
        leader_dist: int,
        walk_field: Optional[FollowField],
    ) -> int:
        """Walk cost the scroll and TP compare against: walk steps, not Chebyshev.

        Inside the field window the steps are exact. Beyond it, a windowed A*
        is measured about every two seconds. Too far to measure keeps Chebyshev.
        """
        cheb = max(0, int(leader_dist))
        if leader_tile is None or origin is None:
            return estimate_walk_cost(cheb) or cheb
        me = (int(origin.x), int(origin.y))
        if walk_field is not None and walk_field.reached(me):
            return walk_field.walk_distance(me, cheb)
        key = (me[0] // 2, me[1] // 2, int(leader_tile[0]) // 2, int(leader_tile[1]) // 2)
        now = time.monotonic()
        memo = self._walk_cost_memo
        if memo is not None and memo[0] == key and now - memo[1] < 2.0:
            steps = memo[2]
        else:
            steps = None
            try:
                from app._04_decision.nav_config import get_terrain_map

                terrain = get_terrain_map()
                if terrain is not None:
                    steps = estimate_walk_steps(
                        terrain, me, (int(leader_tile[0]), int(leader_tile[1]))
                    )
            except Exception as exc:
                _log.debug("party walk cost failed: %s", exc)
                steps = None
            self._walk_cost_memo = (key, now, steps)
        if steps is None:
            return estimate_walk_cost(cheb) or cheb
        return max(cheb, int(steps))

    def _follow_stuck_escape(
        self,
        origin: Any,
        leader_tile: tuple[int, int],
        walk_field: Optional[FollowField],
        game_state: Any,
    ) -> Any:
        """Following, yet on the same tile for ``FOLLOW_STUCK_S``: one escape click.

        The clock runs on the body's tile only. A new tile, or another kind than
        follow, starts it again. Each try remembers its tile so the next one
        picks a different open tile.
        """
        now = time.monotonic()
        me = (int(origin.x), int(origin.y))
        st = self.runtime.scratch.get("follow_stuck")
        # A heal, potion, or supply tick in between is not time spent following.
        gap = now - float(st.get("last") or 0.0) if isinstance(st, dict) else None
        if (
            not isinstance(st, dict)
            or st.get("tile") != me
            or gap is None
            or gap > _FOLLOW_STUCK_GAP_S
        ):
            tried = (
                list(st.get("tried") or [])
                if isinstance(st, dict) and st.get("tile") == me
                else []
            )
            self.runtime.scratch["follow_stuck"] = {
                "tile": me,
                "since": now,
                "last": now,
                "tried": tried,
            }
            return None
        st["last"] = now
        if now - float(st.get("since") or now) < FOLLOW_STUCK_S:
            return None
        walk_steps = walk_field.member_steps if walk_field is not None else None
        picked = plan_follow_unstick(
            origin,
            leader_tile,
            walk_steps=walk_steps,
            tried=st.get("tried") or [],
            state=game_state,
            rng=self._rng,
        )
        st["since"] = now
        if picked is None:
            st["tried"] = []
            _log.info("follow unstick none from=%s leader=%s", me, leader_tile)
            return None
        tried = list(st.get("tried") or []) + [picked[3]]
        st["tried"] = tried[-FOLLOW_UNSTICK_MEMORY:]
        _log.info(
            "follow unstick from=%s hop=%s leader=%s",
            me,
            picked[3],
            leader_tile,
        )
        return picked

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
        settle_sec: float = 0.7,
    ) -> bool:
        """True after continued fresh samples of the same tile.

        A standing fight stays stopped. Combat is not movement.
        """
        scratch = self.runtime.scratch
        now = time.monotonic()
        if leader_tile is None:
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
        age = _sample_age(now, scratch.get("leader_tile_seen_at"))
        if age is None:
            scratch["leader_tile_seen_at"] = now
            return False
        return age >= float(settle_sec)

    def _leader_is_moving(
        self,
        leader_tile: Optional[tuple[int, int]],
        *,
        settle_sec: float = 0.7,
    ) -> bool:
        """True when a fresh sample moved. A missing sample is not movement."""
        scratch = self.runtime.scratch
        if leader_tile is None:
            scratch.pop("leader_walk_tile", None)
            scratch.pop("leader_walk_at", None)
            scratch["leader_stepped"] = False
            return False
        now = time.monotonic()
        tile = (int(leader_tile[0]), int(leader_tile[1]))
        prev = scratch.get("leader_walk_tile")
        scratch["leader_stepped"] = prev != tile
        if prev != tile:
            scratch["leader_walk_tile"] = tile
            scratch["leader_walk_at"] = now
            return True
        age = _sample_age(now, scratch.get("leader_walk_at"))
        if age is None:
            scratch["leader_walk_at"] = now
            return True
        return age < float(settle_sec)

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
