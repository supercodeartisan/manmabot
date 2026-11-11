# Party edge cases

Each case is one branch that changes the tick's action or the next tick's state. The normal path is in [PARTY_CODE_TO_ACTION.md](PARTY_CODE_TO_ACTION.md). Who runs that path is in [PARTY_RUNTIME.md](PARTY_RUNTIME.md). Constants below are the ones in the current tree.

| Name | Value | Where |
|---|---|---|
| Invite retry | 20 s | `INVITE_EVERY_S` |
| Invite forming clock | 10 min, fixed at first arm | `START_WAIT_S` |
| Leave confirm | 10 s of confirmed absence | `LEFT_CONFIRM_S` |
| Combat may block chat | 60 s, then the line is typed | `COMBAT_HOLD_MAX_S` |
| Rally stand | 180 s from `note_arrived` | `MEMBER_WAIT_S` |
| Rally arrival radius | 7 tiles | `ARRIVE_TILES` |
| Leader "at the mark" | 1 tile | `_at_rally_point` |
| Point box / turret leash | 2 tiles, a 5×5 | `POINT_BOX_TILES`, `LEASH_TILES` |
| Turret stand | 1 tile, a 3×3 | `STAND_TILES` |
| Unpinned anchor forget | 40 tiles | `ANCHOR_FORGET_TILES` |
| Follow click | 2, extend 3 on a straight open line | `FOLLOW_CLICK_TILES`, `FOLLOW_EXTEND_TILES` |
| Side-slot arrival | 0 (that tile) | `ARRIVAL_TOLERANCE` |
| Stand-slot arrival | 1 (the 3×3) | `STAND_ARRIVE_TILES` |
| Catch-up enter / exit | 4 / 1 | `CATCH_UP_ENTER_TILES`, `CATCH_UP_EXIT_TILES` |
| Leader still / moving sample | 0.7 s, sample gap 30 s | `_leader_looks_stopped`, `_MOTION_GAP_S` |
| Join replan | 24 tiles, same map | `_REPLAN_TILES` |
| Supply near / stand wait | 3 tiles / 8 s | `_NEAR`, `STAND_WAIT_S` |
| Leader loot radius | 7 tiles, on screen | `LOOT_MAX_TILES` |

## 1. Roster and invite

**I1. Party tab off.** `_party_enabled` is false. No server, no invites, no rally. The process is the solo driver.

**I2. Role is not `leader`.** `bot_controller` rewrites it to `member` before the driver choice. A profile value `mage` or `shopkeeper` does not select those brains. The seat is applied later from the roster row.

**I3. Leader, empty roster.** `_party_server_on` is true, so the leader driver runs. `_party_leader_on` is false: no setup, no `/초대`, no rally, no turret. `begin` is not called.

**I4. Blank name, duplicate name, this character's own name.** `roster_invite_names` drops blanks, drops a second copy by case-fold, and drops the leader's own name. That name is never typed and never put in the rally expected set.

**I5. `enabled` false.** The row is not invited and is not required. Missing the key means enabled.

**I6. `required` false (Party tab Wait unchecked).** The name is still invited (I5 permitting). It is not in `roster_required_names`, so it is not in `LeaderStartRally.expected`. `Rally.ready` can become true while this person is absent. The 3 minute stand does not wait for them. Missing `required` means required.

**I7. No required names at all.** `PartyInviter` is constructed already in state `formed`. Rally `begin` sees an empty expected set, logs, and stays `off`. The leader farms without a stand. Invites for non-required names still run.

**I8. Memory read failed.** `action_party_snapshot` returns None when `world` is None or `party_read_ok` is false. `memory_in_party` is None. Setup does not type `파티탈퇴` and does not type `/초대`. State stays `memory_unknown` until a later tick reads in or out. `last_party` from an older frame is not used as this read.

**I9. In a party, but this name, the leader name, or the leader flag is missing.** `needs_leave` is false. No `파티탈퇴`. An empty self name or an empty leader name is enough to block the leave.

**I10. This character is the confirmed in-game leader.** No `파티탈퇴`. Names already listed are not invited. A websocket beep is sent. Names absent from memory are still invited.

**I11. This character is in a party led by someone else, and the read is confirmed.** Setup types `파티탈퇴`, waits 1 second, then arms the inviter. If the chat send fails, state is `leave_failed` and setup returns false. Later ticks do not invent a second leave from that failed arm.

**I12. `invite_accept` and the Y key are not a join.** `PartyInviter.observe` joins a name only from the leader's party memory, or from a member report while this read is unknown. A popup accept alone leaves the row unjoined, so `/초대` can be sent again after 20 seconds.

**I13. Memory unknown while a join was already confirmed.** `observe` does not clear `joined_at` and does not start `out_since`. A blind tick cannot mark someone as left.

**I14. Memory unknown and the row was never joined.** A fresh member report (`reported(name)`) marks the row joined with source `member memory`. The same tick clears `out_since` on every row.

**I15. Confirmed read, name missing, joined less than 10 seconds ago in that absence.** The row stays joined. `out_since` holds the first missing tick. No re-invite yet.

**I16. Confirmed absence for 10 seconds.** `_mark_left` clears joined, join source, and `last_at`, increments `left`, and logs that invites start again. The next due tick may type `/초대` immediately because `last_at` was cleared.

**I17. Required member leaves after the party was `formed`.** If the 10 minute deadline is still ahead, state returns to `forming`. If the deadline has passed, state is `open`: invites continue, and `late` is set only on the transition out of `forming`.

**I18. The 10 minute clock does not move.** `deadline` is `started_at + START_WAIT_S` at the first arm. A reconnect, a rejoin, or a new socket does not extend it.

**I19. Policy not acked, or the member's popup is held.** `LeaderInvites._ready` is false. `due` omits the name. `last_at` is not written, so the 20 second clock does not start. Other names are not frozen by one popup.

**I20. Socket dropped.** `awaiting_fresh` makes `_leader_policy_acked` false until a new `member_state`. No `/초대` for that name. `InviteAccepter` is not reset. A frame from an older leader session is ignored by `member_states.note`.

**I21. Previous tick was combat.** Actions in `COMBAT_ACTIONS` (`attack`, potions, `heal`, `buff`, `hp_to_mp`) block the line. The block lifts after 60 seconds even if combat continues, then one due line is typed.

**I22. Previous tick was dialog or movement magic.** `UNSAFE_ACTIONS`: `shop_run`, `shop_stop`, `gate`, `teleport`, `use_talking_scroll`, `return_to_mother_tree`, `respawn`, `dismiss_level_up`. `can_send` is false. `last_at` is not consumed. The line waits for a safe previous action.

**I23. Chat send returns failure.** `last_at` was already set. `failed` increments. The next try is 20 seconds later, not the next tick.

**I24. Two names are due.** One line per tick. The name with `last_at is None` wins, otherwise the oldest `last_at`.

**I25. Manual invite or Y this tick.** `hold_chat` or `skip_accept` skips the automatic line or the automatic Y. Joins are still observed.

**I26. `PartyInviter.hunt_active` does not hold the walk.** `forming` means a required name is out and the 10 minutes are not over. The leader still calls `_begin_leader_start_rally` as soon as the inviter object exists. The walk to the mark is not delayed by this flag. The flag is for the invite machine and the monitor.

## 2. Rally clocks

**R1. Expected set empty.** `begin` stays `off`. No stand.

**R2. `begin` while not `off`.** Ignored. A second Start in the same process does not reset the stand.

**R3. `travel` and the current pose passed to `begin`.** Deleted. The walk goal is the schedule mark from `prepare`, not the tile where `begin` ran.

**R4. Invite deadline during `await_mark`.** `update` calls `skip`. State becomes `done`. `left_behind` is whoever is not in `arrived` (often everyone, because the point was never armed). The next `prepare` farms. There is no 3 minute stand. This is the 10 minute forming clock, not `MEMBER_WAIT_S`.

**R5. Invite deadline during `waiting`.** Ignored. The stand runs to ready or to 180 seconds.

**R6. Arrival while a world-nav session is still active.** The `waiting` branch runs before the travel-active return. Open travel is dropped. The tick does not keep walking the route.

**R7. Pose within 1 of the mark, state still `await_mark`.** `note_arrived` arms the local rally body and enters `waiting`. Members are not sent the tile.

**R8. Pose 2 or more tiles from the mark center.** Not arrived. `_arm_travel` continues. The 5×5 turret box is a different test and is not the arrival test.

**R9. `note_arrived` when state is not `await_mark`.** No-op. A second arrival does not restart the 180 second clock. `_wait_started` is set once.

**R10. Same tick, everyone already inside 7 tiles.** `prepare` sets `party_rally_wait` and `waiting`. The following `update` sets `done`. `decide` still emits `IDLE` `party rally wait`. The next tick's `prepare` clears the flag and farms. One idle tick is the release.

**R11. A member is connected and outside 7 tiles.** `note_positions` does not add them. `ready` stays false. The leader keeps emitting `IDLE` until 180 seconds or until the tile enters the radius. A socket without a tile does not release the leader.

**R12. The leader's own party row.** `note_positions` skips `is_leader`. The leader does not count as their own arrival.

**R13. Report `arrived` for a different order tag.** `_report_at_rally` rejects it. A report counts when its tile is inside 7, or when `arrived` is true and `order` equals this rally's tag.

**R14. 180 seconds with someone missing.** `skip` sets `done` and `left_behind` to the sorted missing names. The next `prepare` farms. Invites for those names continue under section 1. Their follow target becomes the leader's live tile, not the mark.

**R15. `update` when `_want` is None.** Returns before ready and before the timer. Current `note_arrived` always sets `_want` first. A `waiting` state reached without `_arm` would stand until something else sets `_want`. `hold_at` is still accepted by `update` and is not entered by `note_arrived`.

**R16. Pose missing on the tick after R10.** `prepare` returns before `party_rally_wait = False`. The flag stays true. That tick idles again. The farm walk waits for a tick that has a pose.

**R17. No marks on the row, but the pose is on the row's map.** `_inside` is true. `goal_nav()` is None, so `_arrival_point` is the live pose, gap 0. `await_mark` becomes `waiting` on that tile. The stand happens where the leader is, not at a saved dot.

**R18. Schedule minutes during the stand.** `note_inside` and `note_mark` are called with `holding=True`. Both clocks pause. The 180 seconds are not farm time and not mark time.

**R19. `should_hold`.** Always false. A teleporter step on the way to the mark does not gain a member wait.

## 3. Leader schedule, turret, loot

**S1. Row time is 0 minutes.** `due` is true as soon as `elapsed >= 0`. The first inside tick can `advance` to the next row.

**S2. Last row.** `advance` sets `finished` and returns false. The leader stays on that row.

**S3. Outside the current mark.** `note_inside` / `note_mark` get `inside=False` and pause. A later mark that contains the pose does not count. `inside_current_nav` is the current mark only.

**S4. A one-tile rect.** `shape` is not `point`, so `place_at` returns `area`. Turret stays off. Only `shape == point` is a turret.

**S5. A point's 5×5 overlaps an area rect.** `place_at` returns `point`. The dot wins.

**S6. Body outside the 5×5 after the point routine has started.** `_point_routine_held` is true, so open world-nav is dropped and a new route is not armed. `_pin_point_anchor` keeps turret. `party.turret_leash` emits `TRAVELING` to the dot when the body is outside 2 tiles.

**S7. `_finish_point_target` says the outside monster is alive.** `prepare` calls `_farm` instead of `_arm_travel`. The same tick's leash then clears a target whose tile is outside the 5×5 and emits the walk home. That monster is not attacked on the outside tick. A target still inside the box is kept, and the attack resumes after the body re-enters.

**S8. Point arrival callback with the wrong reason, a missing origin, a gap above 2, or an unknown pack.** `_on_point_arrival` returns false and does not arm turret. Reason must be `party_schedule`.

**S9. Turret scratch on, anchor pinned.** `ANCHOR_FORGET_TILES` (40) applies only to an unpinned anchor. The party point path sets `pinned` true, so a long walk does not drop that dot.

**S10. Turret on, nothing to fight, body inside the 3×3.** `party.turret_idle` emits `IDLE` and clears search hops. `farm.search` does not click.

**S11. Leader loot is not the farm rect.** `party_leader_no_loot` forces `continue_or_start_loot` to pass `farm=None` even when the caller asked for `restrict_to_farm=True`. A pile is taken when it is on screen and within `LOOT_MAX_TILES` (7). An off-screen pile is refused. The standing side-F4 in `arm_loot_side_intent` returns immediately for this flag. Solo mage spell-aim is also off for this scratch.

**S12. Plan failure.** `_arm_travel` sets `_retry_at` to now + 5 seconds and emits no new session. If the goal is already satisfied, it returns without the retry stamp.

**S13. World-nav phase `done`, `fail`, or `idle`.** `_travel_active` is false. The next inside tick may `_clear_travel` and farm.

**S14. Survival in front of the stand.** Death, emergency teleport, HP, MP, and return-vitals sit before `party.rally_wait`. A retreat tick replaces the idle stand. The stand flag remains for the following tick if `prepare` sets it again.

## 4. Member follow

**F1. Paused or dead.** Policy `STOP`. Intent `IDLE`. Dead is `alive` false, `hp <= 0`, or `hp_ratio <= 0`.

**F2. Need heal.** `HEAL` even during catch-up and even when the origin is missing.

**F3. Need buff during catch-up.** The buff waits. Policy falls through. Catch-up is latched at slot distance ≥ 4 and stays until the slot is within 1. A missing slot keeps the previous latch.

**F4. Need potion.** `USE_HP_POTION` before follow, including during catch-up.

**F5. Origin missing.** After heal, buff, and potion: `IDLE` `waiting_origin`. No follow click.

**F6. `defend_self` and a threat.** `DEFEND` before join and before follow. The shot still has to pass `engage_like_solo`. A blocked line or an avoided species becomes `IDLE`.

**F7. Both map ids known and different.** `JOIN_MAP`. One id missing is not `leader_other_map`. The member waits or follows on the current map instead of scrolling.

**F8. Leader absent, same unknown map.** `IDLE` `leader_missing`.

**F9. Assist target exists but is outside attack range.** `need_combat_step` is true, so policy does not return `ASSIST`. The member walks the formation slot. They do not path to the monster.

**F10. Assist target in range, and not deferred.** `engage_like_solo` emits `ATTACK` on a clear line. Leader sources `leader_attack`, `leader_strike`, and `external` ignore the species blacklist. Self-defense does not. A closed line does not pick another monster.

**F11. Assist stays first.** A new assist starts while catch-up is latched and while the leader is moving, including off the slot. Out of attack range still follows. An already-running attack is a later combat question.

**F12. Stale leader pose.** `IDLE` `leader_pose_stale`. The sticky tile is stored and is not copied back onto the view, so it cannot become the click goal.

**F13. Leader tile just changed.** `_leader_is_moving` is true. `_leader_looks_stopped` is false on that sample. `leader_stepped` is true, so `hold_follow_click` is false and a new `TRAVELING` click is sent even if the body is already walking.

**F14. Same leader tile, body moving, hop still toward the slot and more than 1 tile ahead.** `IDLE` `follow_in_transit`. No second click. A hop that is only 1 tile ahead does not hold. A new click is sent.

**F15. Straight open line, not a trail seat.** The hop may extend one tile, still inside 3 of the member and closer to the slot. A trail seat never extends. A turn, a blocked tile, or a hop that would pass the slot does not extend.

**F16. On a side slot.** Distance 0 holds (`ARRIVAL_TOLERANCE` 0). One tile off follows at once.

**F17. On a stand slot.** Distance ≤ 1 holds (`STAND_ARRIVE_TILES`). The member may sit on a neighbor of the center.

**F18. No slot.** `_slot_hold` returns None. The leader-distance band is used. At or inside `stop_tiles`: `HOLD` / `IDLE`. Farther, with the leader stopped: `FOLLOW`. With the leader walking, distance ≥ `stop_tiles + 1` follows. Integer tiles never sit strictly between `stop` and `stop + 1`, so the chasing hysteresis in `follow_kind` does not get a gap.

**F19. `follow_tiles` does not delay the start.** The comment in `follow_kind` is the live rule. Being one tile outside `stop_tiles` is enough to follow. `decide_policy` also passes `leader_farming=False` into `follow_kind`, because the farming case already returned above it.

**F20. No terrain or no path.** `IDLE` `no_terrain` or `no_path`. A follow `no_path` clears `approach_goal` so the next tick may pick another tile.

**F21. Leader movement does not cancel member loot.** Stopped means the same fresh tile for 0.7 seconds. The first sample of a tile is not stopped. A gap over 30 seconds is not a continued sample: stopped becomes false, and `_leader_is_moving` treats the gap as movement. That flag still moves the formation slot. Loot stays armed when the seat may loot and the kind is `HOLD` or `FOLLOW`. Assist and the survival kinds clear sticky loot. Follow does not.

**F22. Sample says the leader is farming.** Outside `assist_leash_tiles`: `FOLLOW`. Inside: the slot, else follow outside `stop_tiles`, else `HOLD`. Turret yard rejoin is earlier: inside the leash and outside the yard is `FOLLOW` `turret_rejoin_yard`.

## 5. Join map

**J1. Invite popup or old party memory.** `hold_join_map` is set from `InviteAccepter.blocks_join_map`. `FOLLOW` and `JOIN_MAP` become `WAIT` `invite_before_join`. An in-flight `WorldNavSession` is cleared. No scroll.

**J2. Policy leader name empty, or different from the memory leader.** `memory_leader_confirmed` is false. Same replacement, reason `party_leader_unconfirmed`. A leftover party row is not a walk or a scroll.

**J3. Confirmed leader, other map, pose missing.** `IDLE` `join_map_waiting_pose`. No session.

**J4. Plan fails.** Session dropped. `IDLE` `join_map_fail <error>`.

**J5. In-flight join, one missed memory read.** `party_read_ok` false keeps the previous `target_key`. The route is not retargeted and not cancelled by that single miss.

**J6. Same map, leader coordinate moves by 24 or more.** The session is re-armed. Under 24, the old goal stays.

**J7. Map id changes.** Re-arm even if the xy delta is small.

**J8. Phase `done`.** Session cleared. `IDLE` `join_map_arrived`. The next tick can follow locally.

**J9. Phase `fail`.** Session cleared. `IDLE` `join_map_fail`.

**J10. Retreat while a join is active.** Critical escape returns first. Supply pickup and shopkeeper duty are skipped because `joining_map()` or last kind `retreat` sets `leaving`.

## 6. Mage, loot, identity

**M1. Class is mage.** Assist target is cleared before policy. No `ASSIST` attack. List heal may replace the decision after policy.

**M2. List heal does not replace `STOP`, `DEFEND`, `POTION`, or a catch-up.** The mage walks, stops, potions, or defends. A buff during catch-up already waited at F3.

**M3. Roster role `mage` is not the class test.** `seat_role` comes from the roster. `is_mage(game_state)` comes from the character. A fighter rostered as mage does not clear assist. A mage rostered as member still clears assist and can list-heal.

**M4. Seat `unknown`.** No shopkeeper duty. `seat_role_for_name` returns `unknown` for a blank role, a missing name, and the party boss, who is not a roster row.

**M5. Not on the policy roster.** Policy is not applied. `gather` and `recovery` are cleared. Follow distances stay the member's own.

**M6. New leader session id.** Overlay cleared, formation reset. A socket reconnect does not do this. The member keeps the overlay and waits for a fresh `member_state`.

**M7. Leader loot versus member loot.** The leader uses S11. A member uses `party_loot_ownership_filter`. `random_loot` with ownership refused uses the closest-looter filter. A supply pile reserved for someone else is refused. Member loot stays open while the leader looks moving (F21). Assist still comes first.

## 7. Supply

**U1. Rally not `done`.** `leader_supply_action` is not called. The leader does not pick up or stand for a drop during `await_mark` or `waiting`.

**U2. Leader leaving the hunt.** Retreat mode, `mother_tree_trip`, an HP-safe scroll, `post_retreat` world-nav, or a pose map different from the hunt map. Supply action is skipped. The hunt decision runs, and that decision may itself be the retreat.

**U3. Claim `clear`, or guid and name disagree.** `claim_names_me` is false when `clear` is set. When both sides have a guid, the guid decides and a matching name with a different guid is not this seat.

**U4. Pickup on the wrong map.** `_pickup_claim` returns None. No walk toward a claim on another map.

**U5. Pile is adena, wrong item, or wrong quantity.** Skipped. The pile must be within 2 tiles of the claim tile.

**U6. Body within 2, pile matched.** `PICKUP`.

**U7. Body within 3, pile not on screen yet, claim not seen.** `IDLE` `supply pickup`. Combat lock is dropped.

**U8. Body within 3, pile was seen, now gone.** Returns None. Hunt or follow resumes. The idle does not stick after a successful pickup.

**U9. Body farther than 3.** `TRAVELING` to the claim tile.

**U10. Hold, body still walking.** `SHOP_STOP` (Esc) a limited number of times, otherwise `IDLE` `supply hold`. The stand is not confirmed while walking, so a new search does not start.

**U11. Hold, shopkeeper already dropping.** Combat and search cleared. `IDLE` `supply receive`.

**U12. Body moves 2 tiles or changes map after the stop.** `leader_hold_displaced` cancels the hold. The function returns None and the hunt decision runs.

**U13. Shopkeeper, supply closed, or a join-map active.** `tick_shopkeeper_duty` returns None. Follow and combat run.

**U14. Buy chain finished.** `_tick_join` walks to the leader's party-memory game coordinate on the leader's map. A sticky same-map tile is not that coordinate and is cleared while the maps differ. Within 3 tiles on the same map, the join ends and duty returns None.

**U15. No leader pose for the join.** `IDLE` `join leader no pose`.

**U16. Drop stand moved, or 8 seconds with no confirmed stand.** `cancel_supply_delivery`. Duty returns None. Follow resumes.

**U17. Urgent self care during supply.** Potion, self heal, or an in-range defense returns before the pickup and before the hold. A shop trip is not cleared by that care.

## 8. Chained scenarios

**C1. Required member's socket drops during the walk to the mark.** I20 blocks new `/초대` until a fresh `member_state`. The leader does not stop walking (I26, R3). At the mark, R11 keeps the `IDLE` stand until that member's party-memory tile is inside 7, or until R14 at 180 seconds.

**C2. Everyone is inside 7 on the arrival tick, then the next pose read fails.** R10 idles the arrival tick and sets `done`. R16 idles one more tick because the flag was not cleared. The farm click waits for a pose.

**C3. The 10 minute invite clock ends while the leader is still walking.** R4 sets rally `done` with no stand. The next `prepare` farms from wherever the route has reached. Invites continue (I17 / open). This is a different outcome from standing 180 seconds at the mark.

**C4. Non-required member is the only one missing at the mark.** I6. `ready` does not include them. R10 releases on the next tick if every required name is inside 7.

**C5. Leader steps one tile while the member is mid-hop.** F13 sends a new 2-tile click on that read. F14 does not, on a read where the leader tile is unchanged.

**C6. Member is 4 tiles off the slot when a monster comes into range.** F3 latches catch-up. F11 defers the new assist. The click is `TRAVELING` to the slot until the slot is within 1. Heal and potion still win (F2, F4). Buff and list heal wait (F3, M2).

**C7. Mage, monster in range, not catching up.** M1 clears the target. The action is list heal or follow, not `ATTACK`, unless F6 `DEFEND` applies.

**C8. Point hunt, leader pulled 3 tiles outside by a hit.** S6 drops world-nav. S7 will not finish an outside monster. The action is `TRAVELING` back to the dot. Members still follow the live tile (their policy `leader_mode` updates only on a later ingest).

**C9. Leader sees an on-screen adena 6 tiles outside the farm rect.** S11 allows it, because the leader path clears the farm filter. A solo hunter on the same column would refuse it. The leader still refuses the pile when it is off screen or farther than 7.

**C10. Shopkeeper finishes buying while the recipient is retreating.** U2 on the leader side, and a member report with kind `retreat`, puts that name in the away set. The drop is not walked. U16 then cancels if the stand never confirms. The shopkeeper returns to follow.

**C11. Blind party read during a cross-map join.** J5 keeps the route. J1 or J2, if the popup opens or the leader name stops matching, clears it instead. One missed read and an invite popup are different branches.
