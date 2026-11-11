# Party runtime: roles and the tick

Traced from the live call path on 2026-11-10. This document records what the session actually calls. It does not treat an unwired class as a running role.

With this file: [code to action](PARTY_CODE_TO_ACTION.md), [edge cases](PARTY_EDGE_CASES.md). The 2026-10-13 request is [PARTY_MEMBER_ANALYSIS.md](PARTY_MEMBER_ANALYSIS.md) and [PARTY_MEMBER_MVP.md](PARTY_MEMBER_MVP.md). Column ids are in [DECISION_STEPS.md](DECISION_STEPS.md).

Evidence lives in:

- `Engine/session/bot_controller.py` — `_run_bot_loop`, the party gates, and the per-tick party block
- `Engine/app/_06_party/manager.py` — `PartyMemberManager.decide`
- `Engine/app/_06_party/leader_manager.py` — `PartyLeaderManager`
- `Engine/app/_06_party/leader_rally.py` — `LeaderStartRally`
- `Engine/app/_06_party/brains/` — seat contract, not the live caller
- `Engine/app/_06_party/policy.py` — `decide_policy`
- `Engine/app/_06_party/config.py` — `merge_leader_policy`
- `Engine/websocket/party_orders.py` — `seat_role_for_name`, `Rally`
- `Engine/app/_04_decision/behaviors/party_turret.py` — leader point hunt

Scenarios, the message catalog, and the test lock list are separate documents.

## 1. Three live drivers

`_run_bot_loop` builds exactly one driver. The three branches are exclusive.

| Condition | Object stored | Who calls `decide` |
|---|---|---|
| `party_cfg.enabled` | `PartyMemberManager` as `party_brain` | `party_brain.decide` |
| else `_party_server_on()` | `PartyLeaderManager` as `leader_brain` | `leader_brain.decide` → `DecisionManager.decide` |
| else | solo `DecisionManager` plus the solo routine cursor | `decision.decide` |

`party_cfg.enabled` is `party_member_enabled` and `party_role != "leader"`. A profile role other than `leader` is rewritten to `member` before that test. Mage and shopkeeper are not session roles.

The gates underneath that choice:

| Method | True when |
|---|---|
| `_party_enabled` | `profile.party_enabled` |
| `_party_server_on` | party enabled and role is `leader` |
| `_party_leader_on` | server on and the roster has at least one named seat |
| `_leader_turret_on` | leader on and `PartyLeaderManager.hunt_mode == "turret"` |

A leader with an empty roster still takes the leader driver (`_party_server_on`), but invite, rally, and turret stay off (`_party_leader_on` is false). `LeaderStartRally.begin` also stays off when the expected name set is empty.

The leader driver sets `scratch["party_leader_no_loot"] = True` and arms `PartyLeaderSchedule` from `profile.party_routine`. It does not install `routine_cursor` and does not read `profile.routine`. The solo driver does the opposite: it installs the solo routine and calls `begin_world_nav`.

## 2. The brain package is not the live caller

`app/_06_party/brains/` defines `BrainRole` (`leader`, `member`, `mage`, `shopkeeper`) and `make_brain`. `DecisionBrain.adopt` is specified to return one `AdoptedDecision` and to do no socket or click I/O.

The session never calls `make_brain` or `adopt`.

| Class | What `adopt` does | Live caller |
|---|---|---|
| `LeaderBrain` | returns `ready=False`, reason `leader_brain_unwired` | `PartyLeaderManager` |
| `MemberBrain` | calls `PartyMemberManager.decide` | the session calls that manager directly |
| `MageBrain` | same manager call | same |
| `ShopkeeperBrain` | same manager call | same |

A mage seat and a shopkeeper seat are `PartyMemberManager` with a different `seat_role`. They share `decide`, `decide_policy`, follow, loot, and the supply prefix. The seat changes which branches inside that function return early.

## 3. Who owns which state

### Leader process

Owns the socket server, the roster, the invite machine, the start rally, the party schedule, and the hunt blackboard.

| State | Owner | Written by |
|---|---|---|
| `LeaderInvites` | session `_party_invites` | `_run_leader_party_setup` once, then `_leader_invite_tick` |
| `LeaderStartRally` | session `_start_rally` | `_begin_leader_start_rally`, `prepare` via `note_arrived`, `drain_leader_reports` via `update` |
| `PartyLeaderSchedule` | `PartyLeaderManager.schedule` | `arm` from `party_routine`; `prepare` advances marks and minutes |
| `hunt_mode`, `turret_anchor` | `PartyLeaderManager` | `_apply_place`, `_on_point_arrival`, `_pin_point_anchor` |
| `scratch["party_turret"]` | leader blackboard | `set_party_turret` each tick from `hunt_mode` |
| `scratch["party_rally_wait"]` | leader blackboard | `prepare` |
| `scratch["party_leader_no_loot"]` | leader blackboard | set once when the leader driver is built. `continue_or_start_loot` then ignores the farm rect and keeps an on-screen pile within 7 tiles |
| party policy body | session, then socket | `_leader_party_policy_kwargs` / `_publish_party_policy` |
| member reports, policy acks, invite accepts | `comms` stores | `drain_leader_reports` |

`hunt_mode` is not a saved profile choice. `_apply_place` sets `turret` when the current mark's shape is `point`, and `moving` when the mark is an area. `leader_mode` in the published policy is that live `hunt_mode`. Members read it back as `config.leader_mode`, and `turret_farm` is `leader_mode == "turret"`.

A point hunt uses Chebyshev radius 2 (`POINT_BOX_TILES`, `LEASH_TILES`): the dot plus two tiles, a 5×5. Standing without a click uses radius 1 (`STAND_TILES`): a 3×3. `party.turret_leash` walks back when the leader is outside the 5×5 and drops targets outside that box. `party.turret_idle` stands inside the 3×3 after `farm.engage` finds nothing. Those steps are no-ops unless `set_party_turret` left the scratch on. Only the leader column runs them.

### Member process

Owns one `PartyMemberManager`: leader view, follow, assist, formation slot, loot side, and supply runtime. It does not own the hunt schedule and it does not call `DecisionManager.decide`.

The leader identity used for follow comes from party memory (`resolve_leader` / `bind_leader_from_party`). The socket does not set that identity. The session log at arm time says the socket is reports and orders only.

`seat_role` starts as `mage` when `profile.character` is `mage`, otherwise `member`. After a rostered policy arrives, `merge_leader_policy` replaces it with `seat_role_for_name`. That function returns `member`, `mage`, or `shopkeeper` only when the roster row's `role` is one of those three. A blank role, a missing name, or the party boss (who is not a roster row) becomes `unknown`. The same merge keeps this process's own `follow_tiles`, `stop_tiles`, `approach_tiles`, `assist_leash_tiles`, and `farm_mode`. Loot seat, yard, supply thresholds, heal percents, and `leader_mode` come from the policy.

`unknown` does not select shopkeeper duty. Shopkeeper duty runs only when `seat_role == "shopkeeper"`.

### Shared blackboard on a member

The member is given the session `Blackboard` (`set_nav_blackboard`) so join-map can emit scroll and gate intents, and so heal, buff, potion, and loot side intents have a cooldown store. The comment on `executor.execute` states that this blackboard is not a solo mode column. The member action is the intent returned by `PartyMemberManager`. Side intents on that blackboard still ride the executor.

### Shopkeeper and mage, as branches

Shopkeeper, inside `PartyMemberManager._decide_party`, after self-care and before follow:

1. If this seat is the named recipient of `supply_hold`, stand or pick up.
2. If `seat_role == "shopkeeper"`, an urgent party heal can preempt the duty.
3. `tick_shopkeeper_duty` may return the shop or supply action. `None` falls through into follow and combat.
4. `arrow_duty` is the module that sets `party_pin_shop_behavior` and `party_shopkeeper_arrow` on that seat's blackboard.

Mage, still inside the same function:

- `mage_skips_party_assist` is `is_mage(game_state)`. When it is true, the assist target is cleared before `decide_policy`, so the policy does not choose `ASSIST`.
- After policy, if the kind is not `STOP`, `DEFEND`, or `POTION`, and the member is not in a formation catch-up, `_party_list_heal` can replace the decision with a party heal or buff.
- `mage_support_skills` is this character's own map. `merge_leader_policy` does not replace it. `mage_heal_pct` does come from the leader policy.

A character class of mage and a roster role of mage are two different inputs. The class clears assist and opens list heal. The roster role is what the policy overlay stores on `seat_role`.

## 4. One tick, before any party work

`_run_bot_loop` reaches the party block only after all of these have passed:

1. Perception and memory sync. A member stores the MapSubsystem id with `set_local_map_id` on every successful sync.
2. Pause. Stay clocks freeze. No decide, no act.
3. Cursor paralysis. The executor drops the mouse once. No decide, no act.
4. Live origin and live map id, until `session_ready_deadline`.

Then the party block. After the action is chosen, both drivers share `executor.execute`, gate feedback, shop bag marking, and preview publish. A member never enters the solo world-nav pause check; that check is guarded by `party_brain is None`.

## 5. Leader tick

Order inside the party block when `leader_brain` is set. `start_rally` exists only when `_party_leader_on()`.

1. **Once per Start.** `_run_leader_party_setup` builds `LeaderInvites` from `party_roster`. It publishes policy through the invite object's callback. It does not type `/초대` itself.
2. **Chat.** `_drain_party_chat`.
3. **Invite.** `_leader_invite_tick`. One invite line can be typed on this tick. A chat kind of `invite` holds the automatic line.
4. **Rally arm.** If `start_rally.state == "off"` and `_leader_may_begin_start_rally`, call `_begin_leader_start_rally`. That is allowed as soon as the invite object exists and the roster has a required name. It does not wait for sockets or for the invite window. `begin` moves `off → await_mark` and stores the invite deadline. `travel` is true when the leader is neither on the selected map nor inside the target dungeon. The current `begin` deletes `travel` and `pose`; the walk target is the schedule mark, not the current tile.
5. **Schedule.** `PartyLeaderManager.prepare`.
6. **Turret flag.** `set_party_turret` from `_leader_turret_on()` and `turret_anchor`. `party_help_open` is set on the leader scratch.
7. **Talking-scroll arrival** runs here because `party_brain` is `None`.
8. **Reports, before the hunt decision.** `_drain_party_reports` → `drain_leader_reports` → `LeaderStartRally.update`.
9. **Supply or hunt.** `leader_supply_action` runs only when `_party_hunt_open` and the leader is not supply-away. Hunt is open only when rally `state == "done"`. If supply returns an action, that action is the tick. Otherwise `leader_brain.decide` is `DecisionManager.decide`, which runs the mode column (`WORLD_NAV`, `FARMING_ISLAND`, or `FARMING_DUNGEON`).
10. **Publish, after the action.** `_leader_party_tick` drains reports a second time, publishes recovery on the first `mother_tree_trip == "cast"`, publishes policy, shop reports, and supply hold/stand. `publish_decision` sends the action that was just chosen.

`prepare`, while a row and a live pose exist:

1. Clears `party_rally_wait`.
2. If state is `await_mark` and the pose is within 1 tile of the mark, `note_arrived`. That arms the local rally body and enters `waiting`. The body is not sent to members (`Rally.arm` stores it; `repeat_if_members_joined` returns false).
3. If state is `waiting`, sets `party_rally_wait`, drops open travel, pauses schedule clocks with `holding=True`, mounts the row, and returns. It does not call `_farm`.
4. Otherwise an active world-nav session returns early, or a pending walk to the mark calls `_arm_travel`.
5. Inside the mark, `_apply_place` selects turret or moving. Due row time or due mark time arms the next walk. Otherwise `_farm` switches `WORLD_NAV` to `FARMING`.

`LeaderStartRally.update` while `waiting`:

- `Rally.ready` (every expected name is in `arrived`) sets `done` on this call.
- At `MEMBER_WAIT_S` (180 seconds) `skip` sets `done` and records `left_behind`.
- The invite `deadline` does not apply in `waiting`. It can still skip `await_mark` before arrival.

`arrived` is filled by `note_report` or by `note_positions`: a non-leader party-memory member within `ARRIVE_TILES` (7) of the armed point. A connected socket whose tile is outside that radius does not satisfy `ready`.

### Same-tick lag on the leader

`prepare` runs before the first `update`. The arrival tick can enter `waiting` and set `party_rally_wait`. The following `update` can see every member already in range and set `done`. `decide` still sees the flag, so `party.rally_wait` returns `IDLE` and the column does not walk. The next tick's `prepare` clears the flag and `_farm` switches to `FARMING`.

`_leader_party_tick` drains again after `decide`. A report that arrives between the two drains can finish the rally only after the action for this tick was already chosen.

Policy publish is also after `decide`. Members observe the new `leader_mode` on a later ingest, not inside this leader decision.

`_party_hunt_open` is false until rally `done`. Supply pickup at the leader is therefore off during `await_mark` and `waiting`.

## 6. What the leader column does with party flags

`DecisionManager.decide` is the hunt. Party-specific steps inside it:

| Step | Column | Effect when the flag is set |
|---|---|---|
| `party.rally_wait` | `WORLD_NAV` after return vitals; `FARMING_ISLAND` and `FARMING_DUNGEON` after return-idle | `IDLE` "party rally wait". Shop, nav, confined unstick, and search do not run |
| `party.turret_leash` | farming columns, before `farm.engage` | outside the 5×5, walk to the dot; exclude outside targets |
| `party.turret_idle` | farming columns, after `farm.engage` | no target: stand in the 3×3; search does not run |

Survival steps stay in front of `party.rally_wait`. Potions and retreat still win over the stand.

`TRAVELING` has neither step. The walk to the mark is allowed to move.

## 7. Member tick

Order when `party_brain` is set. Leader setup, invite typing, rally, and `DecisionManager.decide` do not run.

1. `_member_socket_pending`.
2. `_member_party_tick(..., send=False)`.
3. `party_brain.decide`.
4. If the socket client exists, `_member_state_report` again, so the report includes this tick's kind.
5. `_member_party_tick(..., send=True)` calls `send_status` (buffs and items at the live pose).
6. Monitor publish with note `decide`.

`send=False`, when the client exists:

- Restores a dropped socket and nudges `member_state`.
- `ingest_orders`.
- A new leader session id clears the policy overlay and the formation (`reset_for_new_leader_session`). A socket reconnect does not.
- Takes a beep.
- If this character is on the policy roster, `apply_leader_policy`. A new policy id is acked.
- If this character is not on the roster, `gather` and `recovery` are cleared.
- Hello, invite accept (unless this tick's chat already accepted), join hold, beep-if-already-in, and one `member_state` from the previous decision.

`send=False` with no client still accepts a local invite popup and sets the join hold. It does not ingest orders.

Talking-scroll arrival runs on a member only while `joining_map()` is true (`PartyJoinNav` active, or last kind `join_map` / `follow_nav`).

### Member `decide` order

`_decide_party` is one intent. The first hit returns.

1. Bind the leader from `last_party`, then `resolve_leader`. Sticky pose is recorded and is not copied back onto the view.
2. Build the loot filter. A reserved supply pile is refused. Critical retreat returns immediately. Urgent self survival returns next and can expire a supply hold.
3. Supply pickup, or the recipient hold, when this seat is the named holder and is not joining or already retreating.
4. Shopkeeper urgent party heal, then `tick_shopkeeper_duty`, only for `seat_role == "shopkeeper"`.
5. `apply_party_support` for self heal, buff, and potion flags. Potions also stay on `side_intents`.
6. Hunt gather while heal and buff are not required.
7. Optional self-defend target.
8. Assist target: solo-farm nearest around the leader, or the leader's target, or a member-help target. Then a mage clears that target.
9. Formation slot from `choose_formation_goal` (seat index, party size, trail, terrain, occupied tiles).
10. `decide_policy`.
11. Heal or buff support returns. A mage list-heal can replace any kind except `STOP`, `DEFEND`, `POTION`, and a formation catch-up.
12. Loot is armed only when the leader looks stopped, this seat is allowed to loot, and the kind is `HOLD` or `FOLLOW`. A moving leader clears sticky loot. Assist, defend, and join stay ahead of loot.
13. The kind is turned into one follow, assist, defend, join, wait, or stop intent.

`decide_policy` itself, first match:

1. `STOP` if paused or dead.
2. `HEAL`, then `BUFF` (a buff waits while catching the slot), then `POTION`.
3. `WAIT` if the world origin is missing.
4. `DEFEND` if `defend_self` and a threat exists.
5. `JOIN_MAP` if the leader map id and the local map id are both known and differ.
6. `WAIT` if the leader is absent.
7. `ASSIST` when a target exists, no combat step is required, and hunt is not deferred. Hunt is deferred while catching the slot, and while the leader is moving and this seat is off the slot.
8. `WAIT` if the leader pose is stale.
9. Turret yard rejoin (`FOLLOW`) when `turret_farm` and this seat is inside the assist leash but outside the yard.
10. While the leader is farming: follow outside the assist leash; otherwise the formation slot; otherwise follow outside `stop_tiles`; otherwise `HOLD`.
11. While the leader is traveling: the formation slot, then the follow/stop band (`follow_tiles` / `stop_tiles`).

## 8. Monitor workflow is not the tick

`app/_06_party/workflow.py` builds the leader monitor rows Server → Connect → Policy → Confirm → Invite → Rally → Hunt, and the per-member rows Connect → Policy → Invite → Accept → Party → Rally/Follow. Those functions only label a snapshot. They do not invite, walk, or finish the rally. Rally and Hunt stay `off` in that view while connect or policy is still open, even if `LeaderStartRally` has already moved.

## 9. Boundaries that the tick relies on

- Members follow the leader's live party-memory tile. They are not sent the rally point.
- The leader's hunt action is the solo decision column, with party scratch flags in front of search and confined unstick.
- A member's hunt action is `PartyMemberManager`, with the shared blackboard used only as a side channel.
- Supply at the leader starts after rally `done`. Supply on a member can run as soon as a hold or duty is ingested, because that prefix is inside `decide`, before follow.
- `LeaderBrain` is not on this path. Wiring `adopt` later has to replace `PartyLeaderManager` / `PartyMemberManager` in `_run_bot_loop`, or it will not run.
