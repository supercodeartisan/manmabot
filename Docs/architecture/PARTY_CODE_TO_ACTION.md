# Party: code to action

This is the action report for the live party loop. Each section names the function that decides, the `ActionType` or chat line it returns, and what `ActionExecutor.execute` then does with the mouse and keyboard.

Who owns the tick is [PARTY_RUNTIME.md](PARTY_RUNTIME.md). Branches that change the action are [PARTY_EDGE_CASES.md](PARTY_EDGE_CASES.md).

Traced from the current tree. The short index is `Docs/architecture/PARTY_RUNTIME.md`. This file is the procedure.

Primary sources:

- `Engine/session/bot_controller.py` — `_run_bot_loop` around the party block, invite, rally, supply
- `Engine/app/_06_party/manager.py` — `PartyMemberManager._decide_party`
- `Engine/app/_06_party/intents.py` — the member `ActionIntent` builders
- `Engine/app/_06_party/leader_manager.py` — `prepare`, `_arm_travel`, `_farm`
- `Engine/app/_06_party/leader_rally.py` — `note_arrived`, `update`
- `Engine/app/_06_party/invite.py` — `LeaderInvites`
- `Engine/app/_06_party/arrow_duty.py` — shopkeeper duty and leader supply
- `Engine/app/_06_party/assist.py` — `engage_like_solo`
- `Engine/app/_06_party/support.py` — retreat and self care
- `Engine/app/_06_party/join_map.py` — `PartyJoinNav.tick`
- `Engine/app/_05_action/controller.py` — `ActionExecutor.execute`

## 1. The only object the game sees

Nothing in the party package clicks. A tick ends as one `ActionIntent` plus optional `blackboard.side_intents`. `ActionExecutor.execute` (`controller.py`) is the only click and key path.

`execute` always drops the mouse first, except an `IDLE` tick while the executor is not already holding a button. `IDLE` then calls `_idle`, which is `pass`. A party stand is the absence of a click.

| `ActionType` | Executor method | What the character does |
|---|---|---|
| `IDLE` | `_idle` | No key, no click. A walk already in progress in the game client continues until something else cancels it. |
| `TRAVELING` | `_travel` → `_search` | Ground click at `destination`. Member follow builds that point from a hop at most `FOLLOW_CLICK_TILES` (2) tiles away. A straight open line may extend one more tile, and the click must stay inside `FOLLOW_EXTEND_TILES` (3). |
| `ATTACK` | `_combat.attack` | Class combat on `target_id`. Mage casts. Melee and bow use their timed click. `mid_act` keeps the previous press through this tick. |
| `PICKUP` | loot cadence | Pickup on `target_id`. |
| `HEAL` | `_heal` | Hotbar spell, then a click. Party-list heal sets `click_x` / `click_y` to the party-window row, not the body. |
| `BUFF` | `_buff` | Hotbar buff. A party-list buff uses the same click fields. A missing click is a no-target cast. |
| `USE_HP_POTION`, `USE_MP_POTION`, `USE_DEPOISON` | potion methods | Hotbar key for that item. |
| `SHOP_STOP` | `_shop_stop` | One Esc, then 0.25 s. This is how a supply recipient cancels an auto-walk. |
| `SHOP_RUN` | `_shop_run` | Shop or NPC-teleporter behavior named by `shop_behavior_id`. |
| `USE_TALKING_SCROLL` | `_use_talking_scroll` | Talking scroll. |
| `GATE` | `_gate` | Gate click. The session writes the result back with `apply_gate_result`. |
| `RETURN_TO_MOTHER_TREE` | `_return_to_mother_tree` | Mother-tree return. |
| `TELEPORT` | `_teleport` | Teleport spell. |
| `SEARCHING` | `_search` | Ground click for a hunt search hop. Leader columns emit this. Member follow does not. |
| `RESPAWN` | `_respawn` | Death respawn. |

Side intents run in the same `execute` call:

- A `PICKUP` side runs before the primary action.
- Potion sides run on a thread beside a mouse primary (attack, travel, pickup). On a keyboard or idle primary they run first.

Chat is not an `ActionIntent`. `LeaderInvites._say` calls `deliver_chat`, which types one line through `app._05_action.chat.send_chat_line`. That shares the keyboard with the action, so the invite tick refuses to type on the same tick as combat, a potion, a heal, a buff, an NPC dialog, or a teleport, unless a due invite has already waited `COMBAT_HOLD_MAX_S` (60 s).

## 2. Who produces the intent

`_run_bot_loop` assigns one producer.

| Process | Producer | Intent source |
|---|---|---|
| Member, including mage and shopkeeper seats | `PartyMemberManager.decide` | Built in `_decide_party` and `intents.py`. The solo column does not run. |
| Leader | `leader_supply_action`, else `PartyLeaderManager.decide` → `DecisionManager.decide` | Solo mode column, after `prepare` has set mode and scratch flags. |
| Solo | `DecisionManager.decide` | Solo routine. No party flags. |

`BrainRole` and `make_brain` are not called from this loop. A mage seat is the member producer with `is_mage(game_state)` true. A shopkeeper seat is the same producer with `config.seat_role == "shopkeeper"`.

## 3. Leader procedure, in call order

The block is `bot_controller.py` after pause, paralysis, and live-origin gates. Each numbered step is one call. Later steps see what earlier steps wrote.

### 3.1 Once: `_run_leader_party_setup`

Runs on the first tick after Start, only when `_party_leader_on()` (party enabled, role `leader`, roster has a name).

1. Build `LeaderInvites` from `profile.party_roster`.
2. `LeaderInvites.start` reads party memory.
   - Memory unknown: no `파티탈퇴`, no `/초대`. Later ticks retry in `LeaderInvites.tick`.
   - This character is in a party and is not that party's leader: type `파티탈퇴`, wait 1 second, then arm the inviter. A failed send leaves state `LEAVE_FAILED` and returns false.
   - This character already leads the in-game party: no leave. A websocket beep is sent. Names already in memory are not invited. Missing names still are.
3. `start` publishes the party policy once.

No hunt click on this setup call. The hunt click is step 3.9.

### 3.2 `_drain_party_chat`

Runs a queued monitor Invite or Y+Enter on the same chat path. If the drained kind is `invite`, step 3.3 sets `hold_chat=True` and does not type a second line.

### 3.3 `_leader_invite_tick` → `LeaderInvites.tick`

One step. Joins and leaves are observed even when no line is typed.

A line is typed only when all of these hold:

- The inviter exists and is still inviting.
- Party memory is readable.
- `hold_chat` is false.
- `action_allows_chat(last_action)` is true (the previous tick was not an NPC dialog or a teleport).
- `_combat_allows` is true (the previous tick was not in `COMBAT_ACTIONS`, or the due invite has waited 60 s).
- `PartyInviter.due` has a name. A name is due when it is not joined, its policy ack matches the current policy id, its invite popup is not held, and `INVITE_EVERY_S` (20 s) has passed since its last line.

The line is `/초대 <name>` via `invite_command`. One name per tick, the one least recently invited. A delivered line increments that row's `invites`. A failed send increments `failed` and waits another 20 s.

`START_WAIT_S` is 10 minutes. It is the invite object's deadline, passed into `LeaderStartRally.begin`. It does not stop invites. After it, missing names are marked late and invites continue. During rally state `waiting`, `LeaderStartRally.update` ignores this deadline. The 3 minute stand is `MEMBER_WAIT_S` and is a different clock.

### 3.4 `_begin_leader_start_rally`

Only when `start_rally.state == "off"`, the roster has a required name, and `LeaderInvites` exists. It does not wait for sockets.

`begin` stores the expected names and the invite deadline, then sets state `await_mark`. The arguments `travel` and `pose` are deleted inside `begin`. The walk target is not the current tile. It is the schedule mark, armed later by `prepare`.

Empty expected set: `begin` logs and stays `off`. The leader still farms.

### 3.5 `PartyLeaderManager.prepare`

Clears `scratch["party_rally_wait"]` at the start of every prepare that has a pose.

| Condition | Calls | Mode / flag | Action this tick |
|---|---|---|---|
| No schedule row, or no live pose | return | unchanged | The later `decide` uses whatever mode was already set. |
| `await_mark` and Chebyshev distance to the mark ≤ 1 | `note_arrived` | state becomes `waiting` | No click from this call. |
| state `waiting` | drop open world-nav, `note_inside` / `note_mark` with `holding=True`, `_mount`, return | `party_rally_wait = True`. Schedule minutes do not accrue. | `decide` hits `party.rally_wait` and emits `IDLE` reason `party rally wait`. |
| World-nav session phase is not done/fail/idle, and the point routine is not held | return | session kept | `world_nav.drive` emits the next route step. |
| `await_mark` and not yet within 1 tile | `_arm_travel` | `WORLD_NAV` via `ensure_world_nav_mode` | Same. The goal is `point_goal` at the mark center, or `map_goal` if the nav conversion fails. |
| Inside an area mark, rally not waiting | `_apply_place("moving")`, maybe advance the row, else `_farm` | `WORLD_NAV` → `FARMING` | Farming column: engage, enter, search. |
| Inside a point mark | `_apply_place("turret", anchor=center)` | `hunt_mode = turret` | After step 3.6, turret leash / idle replace search. |
| Point routine already held, body outside the 5×5 | `_pin_point_anchor`, `_farm` | turret stays on | `party.turret_leash` emits `TRAVELING` back to the dot. |

`_arm_travel` builds a `WorldNavSession` with reason `party_schedule`. Plan failure sets a 5 second retry and emits nothing new. While the session is active, `prepare` returns before `_farm`, so the leader does not switch to `FARMING` mid-route.

`_on_point_arrival` is the schedule callback for reason `party_schedule`. If the pose is inside `POINT_BOX_TILES` (2) of a point mark, it sets turret and calls `set_party_turret` before the farming handoff on that same tick.

`note_arrived` calls `_arm(STAGE_START, point)` then `_enter_waiting`. `_arm` stores a rally message on the local `Rally` and logs the point. `Rally.arm` does not transmit it. `repeat_if_members_joined` returns false. Members never receive the tile.

### 3.6 Turret scratch

`set_party_turret(blackboard, _leader_turret_on(), map_id, anchor)`.

`_leader_turret_on` is true only when `hunt_mode == "turret"`. That is a point mark, not a saved profile switch. An area mark forces `moving` and clears the anchor.

The scratch leash is clamped to 1..4. The constant used by the steps is `LEASH_TILES = 2` (5×5) and `STAND_TILES = 1` (3×3).

### 3.7 Talking-scroll arrival

`apply_talking_scroll_arrival` runs for the leader because `party_brain` is `None`. It updates landing state. It is not the hunt click.

### 3.8 `_drain_party_reports` → `LeaderStartRally.update`

Feeds socket reports into `Rally.note_report` and party memory into `Rally.note_positions`.

`note_positions` adds a non-leader member whose party-memory tile is within `ARRIVE_TILES` (7) of the armed point. A connected socket outside that radius is not arrived.

While state is `waiting`:

- `ready` (every expected name is in `arrived`) sets `done` and logs `all members here, continue to the hunt`.
- Elapsed ≥ `MEMBER_WAIT_S` (180 s) calls `skip`, which sets `done`, fills `left_behind`, and logs the missing names.
- Otherwise it logs the missing names every `WAIT_LOG_EVERY_S` (5 s).

`update` does not emit an intent. The effect is on the next `prepare` (or, if `done` lands after `prepare` on this same tick, on the next tick's `prepare`). See section 5.

### 3.9 The intent

`_party_hunt_open` is true only when rally state is `done`. Until then `leader_supply_action` is not called.

When hunt is open and the leader is not supply-away (not retreating, not on a mother-tree trip, not on a return scroll, not on a `post_retreat` walk, and still on the hunt map):

1. `leader_supply_action` may return an intent. That intent is the tick. `DecisionManager.decide` does not run.
2. Otherwise `leader_brain.decide` is `DecisionManager.decide`.

`leader_supply_action` order:

| Check | Intent |
|---|---|
| `party_critical_escape` | The retreat column's intent: mother tree, talking scroll, safe scroll, or the shop-before-retreat trip. |
| `urgent_self_survival` | HP potion, else self `HEAL`, else `ATTACK` if a threat is already inside hold-ground reach and the shot line is open. A chase is not started here. |
| This leader is the named supply claim | `PICKUP` when a matching non-adena pile is within 2 tiles of both the body and the claim tile. `IDLE` reason `supply pickup` while within `_NEAR` (3) and the pile is not on screen yet. `TRAVELING` toward the claim tile otherwise. |
| This leader is the named supply hold | While still walking: `SHOP_STOP` (Esc) a few times, else `IDLE` `supply hold`. After the stop is confirmed: in-place hunt via `supply_wait_intent`. If the body then moves 2 tiles or changes map, the function returns `None` and the hunt decision runs. |

### 3.10 What `DecisionManager.decide` emits for the leader

The mode set by `prepare` selects the column. First non-`None` step wins. Party steps and the actions they produce:

**`party.rally_wait`** (`mode_ticks._step_party_rally_wait`), present on `WORLD_NAV` after return-vitals, and on both farming columns after return-idle.

- Flag clear: return `None`. Later steps run.
- Flag set: `ActionType.IDLE`, priority 0.45, reason `party rally wait`. Executor idles. `nav.world`, `world_nav.drive`, `unstick.confined`, `farm.search`, and turret steps do not run. Survival steps in front of it still can potion, retreat, or emergency-teleport.

**World-nav drive**, when the flag is clear and a `WorldNavSession` is active. `session.tick` writes one of:

- `TRAVELING` for a walk step.
- `USE_TALKING_SCROLL` for a scroll step.
- `GATE` for a gate step.
- `SHOP_RUN` with `shop_kind="teleporter"` for an NPC teleporter step (`session.py` around the `NPC_TP_START` emit).
- `IDLE` while waiting on a pack, a landing, or a failed plan.

`should_hold` on `LeaderStartRally` returns false. The route is not paused at the first teleporter to wait for members.

**Farming column**, after `_farm` has switched `WORLD_NAV` to `FARMING`:

- `farm.engage` → `farm_loot_or_combat(..., restrict_to_farm=True)`. On a solo hunter that keeps the farm rect: a pile outside the rect is not selected, and a pile inside the rect, within 3 tiles of the edge, or within 2 tiles of the body still is. The party leader sets `party_leader_no_loot`, and `continue_or_start_loot` then passes `farm=None`, so the rect is not applied. The leader takes an on-screen pile within `LOOT_MAX_TILES` (7) and refuses an off-screen pile. The emitted action is still `ATTACK`, a `TRAVELING` approach, or `PICKUP`.
- `party.turret_leash`, only when turret scratch is on and the body is outside the 5×5: `TRAVELING` to the anchor, reason `party turret return to anchor x,y`. Targets outside the box are cleared first, so `farm.engage` does not take them.
- `party.turret_idle`, when turret is on, `farm.engage` returned nothing, and the body is outside the 3×3: `TRAVELING` back to the dot. Inside the 3×3: `IDLE` reason `party turret wait on anchor`. Search hops are cleared, so `farm.search` does not click.
- `farm.enter` walks back into the rect when the body has left it.
- `farm.search` emits `SEARCHING` when no turret idle claimed the tick.

`scratch["party_leader_no_loot"]` is set when the leader driver is built. It is what clears the farm rect inside `continue_or_start_loot`. The leader radius is the on-screen `LOOT_MAX_TILES` (7). `arm_loot_side_intent` returns immediately for this flag, so the leader does not take the standing side F4. Detail is case S11 in [PARTY_EDGE_CASES.md](PARTY_EDGE_CASES.md).

### 3.11 After the intent

`_leader_party_tick` drains reports a second time, so a report can finish the rally after the intent was chosen. It publishes recovery on the tick `mother_tree_trip` becomes `cast` (map and tile of the leader). It publishes policy, including the live `hunt_mode` as `leader_mode`. It publishes supply hold and stand.

`publish_decision` sends the intent that was just chosen. Members do not execute that message as their own click. Their next tick reads orders, then runs their own `decide`.

## 4. Member procedure, in call order

### 4.1 Before `decide`

`_member_party_tick(send=False)`:

- No socket: local invite accept (Y on the popup) unless this tick's chat queue already accepted. Then set the join hold. Return.
- Socket present: ingest orders, apply a new leader session by clearing the policy overlay and the formation, take a beep, and if this name is on the roster call `apply_leader_policy`. A name not on the roster has `gather` and `recovery` cleared.
- Policy overlay replaces `seat_role` via `seat_role_for_name`. Movement distances (`follow_tiles`, `stop_tiles`, `approach_tiles`, `assist_leash_tiles`) and `farm_mode` stay this profile's. `leader_mode`, loot seat, yard, supply counts, and heal percents come from the leader.
- Hello, invite accept, join hold, beep-if-already-in, and one `member_state` from the previous decision.

`_maybe_hunt_gather` returns `None`. A rally message does not become a walk goal. The comment in `manager.py` states that follow uses the leader row's live tile once party memory says this character is in the party.

### 4.2 `decide` early returns

These return before follow. The intent is final for the tick.

| Order | Function | When | Intent |
|---|---|---|---|
| 1 | `party_critical_escape` | HP at or under the retreat threshold, or mode is already `RETREATING` / sell-before-retreat `SHOPPING` | Retreat column: mother tree, talking scroll, safe zone, or that shop trip. After HP recovers, a solo `post_retreat` world-nav is cleared and mode returns to `FARMING`, so the next ticks follow the leader instead of walking back to a solo hunt map. |
| 2 | `urgent_self_survival` | HP potion side, else self heal, else an in-range defense shot | `USE_HP_POTION`, `HEAL`, or `ATTACK`. No buff and no party-list heal. A shop trip is not cleared. |
| 3 | `tick_supply_pickup` | `supply_drop` names this seat, and the seat is not joining or already retreating | `PICKUP`, `IDLE` `supply pickup`, or `TRAVELING` to the drop tile. Adena is ignored. The pile must match item and quantity and sit within 2 tiles of the claim tile. |
| 4 | `recipient_hold_intent` | `supply_hold` names this seat and the drop claim does not | While walking: `SHOP_STOP` or `IDLE` `supply hold`. While the shopkeeper is dropping: `IDLE` `supply receive` and combat is cleared. |
| 5 | `_opening_shopkeeper_heal` | `seat_role == "shopkeeper"` and a party heal is urgent | `HEAL` or `BUFF`. Supply hold is expired. |
| 6 | `tick_shopkeeper_duty` | same seat, and the function does not return `None` | See section 6. `None` falls through into follow and combat. |

Then `apply_party_support` stashes a self `HEAL` or `BUFF` and arms potion sides. Those sides ride `execute` even when the primary intent is follow. The stash is returned later only if policy picks `HEAL` or `BUFF`.

### 4.3 Target, then policy, then the click

Assist selection:

- `farm_mode == "solo"` (`config.solo_farm`): nearest monster around the leader, inside `assist_leash_tiles`. The leader must be on screen.
- Otherwise: the leader's target (`pick_assist_target`), then `resolve_member_help_target` if that is empty.
- `mage_skips_party_assist`: if `is_mage(game_state)`, the target is wiped. Policy cannot return `ASSIST`.

Formation: `choose_formation_goal`.

- Leader moving: seat 0 on the leader's right, next seat on the left. A trail tile is used only when that side has no free tile. Kind is `side` or `trail`.
- Leader stopped, or `turret_farm`: a 5×5 grid for up to five people, 7×7 for more. The leader tile is never a slot. Kind is `stand`.
- Arrival tolerance for a `stand` slot is `STAND_ARRIVE_TILES` (1). Other slots use `ARRIVAL_TOLERANCE` (0), so the member is on that tile or still walking.

`decide_policy` returns one `MemberKind`. The first match wins. Section 4 of `PARTY_RUNTIME.md` lists the predicates. The kind becomes an intent here:

| Kind | Builder | Action |
|---|---|---|
| `STOP`, `WAIT`, `HOLD` | `idle` | `IDLE`. No click. |
| `POTION` | `potion` | `USE_HP_POTION`. |
| `HEAL` / `BUFF` | `_return_support` when a stash exists | The stashed `HEAL` or `BUFF`. If the stash is missing, `intent_for_kind` emits `IDLE`. |
| `DEFEND` with a track id | `attack`, or `engage_like_solo` when the threat object is still in hand | `ATTACK`, or `IDLE` `assist_species` / `assist_no_shot` / `assist_blocked`. |
| `ASSIST` with a track id | `engage_like_solo` | Solo combat tick on that one monster. Leader-target sources `leader_attack`, `leader_strike`, `external` ignore the species blacklist. Self-defense does not. A blocked line does not retarget. A clear line clicks. |
| `JOIN_MAP` or a far `FOLLOW` | `PartyJoinNav.tick` | World-nav intent. See below. |
| `FOLLOW` with a formation tile | `plan_slot_hop` | `TRAVELING` toward the slot, hop ≤ 2. On the slot: `IDLE` `at_slot`. Same goal while the body is moving and the leader tile did not change: `IDLE` `follow_in_transit`, unless the leader stepped, in which case a new click is sent. |
| `FOLLOW` with a walk field and no slot | `plan_field_follow` | `TRAVELING` down the field, same 2-tile hop and the same hold-click rule. |
| `FOLLOW` with neither | `plan_follow_intent` | `TRAVELING` toward a stand tile within `approach_tiles` of the leader, or `IDLE` `no_path` / `no_terrain` / `at_approach`. |

`engage_like_solo` writes through `continue_or_start_combat`. The returned object is `blackboard.intent`. That is the same combat emitter solo uses, pointed at a monster the party already chose.

Loot, when this seat may loot and the kind is `HOLD` or `FOLLOW`. A moving leader does not close it:

- `arm_party_loot_side` puts a `PICKUP` on `side_intents`. `execute` runs that pickup before the primary.
- `try_party_hold_loot` can also return a loot intent as the primary and skip the follow click.
- Assist, defend, join, heal, buff, potion, wait, and stop call `clear_party_loot_sticky`. Follow does not.

Join nav (`PartyJoinNav.tick`):

- Used when the kind is `JOIN_MAP` and both map ids are known and differ, or when `choose_follow_route` says the walk cost should be a world-nav route, or when a join session is already active and the kind is follow, join, or wait.
- Suppressed while an invite popup is holding (`suppress_join_while_invite`) and while the memory leader name does not match the policy leader (`suppress_unconfirmed_leader`). An open session is cleared. No scroll.
- `session.begin` plans to `point_goal(map, x, y)` from the party-memory game coordinate, or `map_goal` if the coordinate is missing.
- The tick returns that session's intent: walk, scroll, gate, or teleporter `SHOP_RUN`. Phase `done` or `fail` returns `IDLE` (`join_map_arrived` or `join_map_fail ...`).
- One missed party-memory read does not retarget an in-flight join. The previous `target_key` is kept.

After `decide`, if the socket exists, `_member_state_report` sends this tick's `last_kind` and supply fields. `_member_party_tick(send=True)` then calls `send_status` with the live pose. That is a socket message, not a click.

## 5. Same-tick timing that changes the action

These are the places where the action on tick N is not the state at the end of tick N.

**Rally release.** `prepare` runs before the first `update`. On the arrival tick, `prepare` can set `waiting` and `party_rally_wait`. The following `update` can set `done` because everyone is already within 7 tiles. `decide` still sees the flag, so the action is `IDLE` `party rally wait`. The next tick's `prepare` clears the flag, calls `_farm`, and the action becomes the farming column.

**Second drain.** `_leader_party_tick` drains again after `decide`. A report that arrives in that window changes rally state for the next tick only.

**Policy.** `leader_mode` is published after the leader's action. A member applies it on a later ingest, inside `send=False`, before that member's `decide`. The member's action on the leader's turret tick still uses the previous `leader_mode`.

**Member state.** `send=False` reports the previous decision. The call after `decide` reports the kind just chosen. A shopkeeper that reads `member_state` sees the new kind on the next leader drain, which may be the second drain of this same leader tick or the first drain of the next one.

**Invite versus combat.** The invite line looks at `last_action`, which is the previous tick's intent. A combat tick delays `/초대` by up to 60 s. The combat click itself is not delayed by the invite.

## 6. Shopkeeper actions

`tick_shopkeeper_duty` returns `None` when supply is closed, when a join-map is active, or when no one is short. Follow and combat then run as a normal member.

When it returns an intent:

| Duty | Function | Action |
|---|---|---|
| Buy | `_tick_buy` → `tick_shop_trip` | The shop-trip column: walk, `SHOP_RUN`, buy keys. Scratch `party_shopkeeper_arrow` and `party_pin_shop_behavior` mark this blackboard as the shopkeeper trip. Quantity is `supply_fill_qty(own, keep, buy)`. |
| Next buy in a chain | `_tick_buy` again | Same, for the next item that is still short and affordable. |
| Chain finished | `_tick_join` | Walk to the leader's party-memory game coordinate on the leader's map. Within `_NEAR` (3) on the same map, the join ends and the function returns `None` so follow resumes. No pose: `IDLE` `join leader no pose`. |
| Drop planned | `_tick_drop` | Until beside the member: the approach intent. On arrival: one `IDLE` `supply drop`, then `step_ground_drop` drags the stack. The drag lands at `(-1, -1)` from the shopkeeper. The shopkeeper's stand tile is that drop tile shifted back by the same offset. |
| Not close enough to drop | `_approach_until_close` | `TRAVELING` toward the recipient. |
| Recipient has not published a stand | `_wait_for_stand` | `IDLE` while the recipient's stop tile is unconfirmed. |
| Stand moved, or 8 s (`STAND_WAIT_S`) with no stand | `cancel_supply_delivery` | Returns `None`. Follow resumes. |

The recipient's matching actions are in section 4.2 rows 3 and 4. The leader can be the recipient: `leader_supply_action` uses the same pickup and hold functions.

## 7. Scenarios as ticks

### 7.1 Forming the party

Leader Start, roster `A` (member) and `B` (shopkeeper). Neither is in the in-game party. Both sockets connect during the walk.

| Tick | Leader action | Member action |
|---|---|---|
| 1 | Setup publishes policy. Memory says not in a party. No leave. State `await_mark`. `prepare` calls `_arm_travel`. Intent: first world-nav step, usually `TRAVELING` or a scroll if the mark is on another map. | No policy yet. `decide` waits (`IDLE` `leader_missing` or `waiting_origin`) until party memory has a leader. Invite accept types Y if a popup is up. |
| 2+ while walking | Invite tick types `/초대 A` on the first tick that A has acked policy, A's popup is not open, and the previous action was not combat. Twenty seconds later `/초대 B` if B is the older due name. World-nav keeps emitting walk, scroll, gate, or teleporter `SHOP_RUN`. `should_hold` does not stop the route. | After ingest, seat is `member` or `shopkeeper`. If the leader map differs, `JOIN_MAP` starts `PartyJoinNav` and the intent is that route's step. Same map: `FOLLOW` emits `TRAVELING` hops of 2 tiles toward the formation slot. |
| Arrival | Pose within 1 of the mark. `note_arrived`. `party_rally_wait`. Intent: `IDLE` `party rally wait`. No search click. No 13 s confined scroll, because that step is after the wait step. | Still following the live leader tile. They are not given the mark coordinate. |

### 7.2 Everyone is already at the mark

`update` on the arrival tick sees both names in party memory within 7 tiles. State becomes `done` before `decide`. The intent is still `IDLE` `party rally wait` because `prepare` set the flag first.

Next tick: `prepare` clears the flag, `_farm` sets `FARMING` for an area mark or leaves turret armed for a point mark. The intent is `farm.engage` (`ATTACK` / loot) or, on a point with nothing in the box, `IDLE` `party turret wait on anchor`.

### 7.3 One member is missing for 3 minutes

`update` keeps state `waiting`. Every leader tick emits `IDLE` `party rally wait`. Potions and retreat still run, because those steps are in front of the wait step. Invites continue every 20 s for the missing name.

At 180 s from `_wait_started`, `skip` sets `done` and `left_behind`. Next `prepare` farms. The late member's follow is unchanged: their `decide` still clicks toward the leader's live tile.

The 10 minute invite deadline does not fire this skip. It can skip `await_mark` only before the leader has arrived.

### 7.4 Area hunt and a point hunt

Area mark: `hunt_mode` is `moving`. Policy `leader_mode` becomes `moving` on the next publish. Members' `turret_farm` is false. They use the moving formation (side, then trail). The leader's `farm.search` may emit `SEARCHING`.

Point mark: `hunt_mode` is `turret`. Leader outside the 5×5 emits `TRAVELING` to the dot and does not search. Inside the 3×3 with no target emits `IDLE`. Members receive `leader_mode=turret` on a later tick. Their policy then rejoins the yard (`FOLLOW` reason `turret_rejoin_yard`) when they are inside the assist leash but outside the yard. The yard rejoin is a member `TRAVELING` hop, not the leader's turret step.

### 7.5 Mage in the fight

Class is mage, so `is_mage` is true.

- Assist target is cleared. No `ATTACK` from assist.
- Self heal and buff still return from `apply_party_support` when policy says `HEAL` or `BUFF`.
- Otherwise `_party_list_heal` can replace the decision with `HEAL` or `BUFF` whose click is the party-list row (`list_heal` / `list_support`).
- `STOP`, `DEFEND`, and `POTION` are not replaced. A formation catch-up (`returning`) is not replaced, so the mage walks back to the slot first.
- `DEFEND` still attacks a monster on this mage if `defend_self` is on.

### 7.6 Arrows

Hunt is open (rally `done`). A member report shows arrows under `member_arrow_min`. The shopkeeper's `tick_shopkeeper_duty` selects a buy. The shopkeeper's intent becomes the shop trip (`SHOP_RUN` and the walk into that shop). Other members keep follow and assist.

When the buy chain finishes, `_tick_join` walks the shopkeeper to the leader's game coordinate. Within 3 tiles, duty returns `None` and the shopkeeper follows like other members until a drop is planned.

The drop publishes a hold for the short member. That member's next `decide` returns `SHOP_STOP` while the body is moving, then `IDLE` `supply hold`. The leader, if the leader is the short character, does the same inside `leader_supply_action` and does not start a new search. The shopkeeper, once beside them, idles one tick (`supply drop`) and then ground-drags. The recipient's pickup is `TRAVELING` until the pile is within 2 tiles, then `PICKUP`.

### 7.7 Retreat during a hunt

Member HP crosses the retreat threshold. `party_critical_escape` returns before follow. The intent is the retreat column (mother tree, talking scroll, or safe zone, according to the party recovery overlay). `execute` presses that key or click. When HP recovers, a solo walk back to the hunt map is discarded. The following tick follows the leader's live tile.

The leader's own retreat is the survival steps in front of `party.rally_wait` and in front of `farm.engage`. During the 3 minute stand those steps still run. A retreat intent from them replaces the idle stand for that tick.

## 8. What is deliberately not an action

- `LeaderBrain.adopt` returns no intent. The session never calls it.
- `workflow.py` labels the monitor. It does not type, walk, or finish the rally.
- `Rally.arm` stores the mark on the leader process. No member walk is created from it.
- `should_hold` returns false. The world-nav route does not gain a wait step.
- A socket connection without a tile inside 7 of the mark does not set `ready` and does not change the leader's `IDLE`.
- `unknown` seat role does not enter `tick_shopkeeper_duty`.
