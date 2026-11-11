# Party member loop

Date of the first note: 2026-10-13. Updated 2026-11-10 to the live caller.

The session does not call `DecisionBrain.adopt`. A member, mage, or shopkeeper process calls `PartyMemberManager.decide`. A leader process calls `PartyLeaderManager.prepare`, then either `leader_supply_action` or `DecisionManager.decide`. Enablement is `party_member_enabled` with `party_role != "leader"`. The leader identity used for follow comes from party memory after the policy overlay, not from a typed `party_leader_name` alone.

Procedure, actions, and branches:

- [PARTY_RUNTIME.md](PARTY_RUNTIME.md)
- [PARTY_CODE_TO_ACTION.md](PARTY_CODE_TO_ACTION.md)
- [PARTY_EDGE_CASES.md](PARTY_EDGE_CASES.md)

## What this note asked for, and what runs now

The 2026-10-13 MVP was follow, assist, and hold, with cross-map, invites, healing, supply, and a leader bot deferred. The live member tick is larger. Order inside `_decide_party`, first return wins:

1. Critical retreat (`party_critical_escape`): mother tree, talking scroll, or safe zone.
2. Urgent self care: HP potion, self heal, or an in-range defense shot.
3. Supply pickup, or the recipient hold (`SHOP_STOP` while walking, then `IDLE`).
4. Shopkeeper heal and `tick_shopkeeper_duty` when `seat_role == "shopkeeper"`.
5. Self heal / buff stash and potion side intents.
6. Assist only when a target is already in attack range and hunt is not deferred. A mage class clears that target. Out of range, the member walks the formation slot.
7. `JOIN_MAP` or a far follow opens `PartyJoinNav`.
8. Otherwise follow a formation slot with a click of at most 2 tiles, or hold.

Loot is on when the kind is hold or follow and this seat may loot. A moving leader does not clear it. Assist does.

Death in this loop is `IDLE` (`STOP`). This loop does not run the solo `survival.death` column.

## Modules that the session actually uses

```text
Engine/app/_06_party/
  manager.py            PartyMemberManager.decide
  leader_manager.py     PartyLeaderManager.prepare / decide
  leader_rally.py       3 minute stand, or leave when Rally.ready
  leader_schedule.py    party_routine marks, not profile.routine
  invite.py             /초대 and 파티탈퇴
  policy.py             MemberKind ladder
  intents.py            ActionIntent builders
  follow.py             2-tile click, hold while the leader tile is unchanged
  formation_goal.py     side, trail, or stand slot
  join_map.py           WorldNav to the leader pose
  assist.py             engage_like_solo
  support.py            retreat and urgent self care
  arrow_duty.py         shopkeeper buy, drop, recipient hold
  brains/               contract only; session does not call adopt
Engine/session/bot_controller.py
  _run_bot_loop         chooses the one driver
Engine/websocket/party_orders.py
  Rally, seat_role_for_name, policy bodies
```

`brains/LeaderBrain.adopt` returns `ready=False`. Wiring it later does nothing until `_run_bot_loop` calls it.

## Still not a live party behavior

These were deferred in 2026-10-13 and are still not what the tick does:

- A protection queue that finishes monster A before it accepts B.
- Automatic leader transfer.
- Kick.
- The member loop emitting `RESPAWN` from `survival.death`.
- A rally tile sent to members. They follow the leader's live party-memory tile.

## Acceptance scenarios from 2026-10-13

1. Leader walks: member follow clicks at most 2 tiles and does not aim at the leader tile when a formation slot exists. A leader step on that read clicks again.
2. Leader attacks A, and A is in range: the member assists A. Out of range, the member walks the slot instead of approaching A.
3. Leader moves during combat, and this member is off the slot: a new assist waits until the member is back on the slot.
4. Leader on another map, both map ids known, policy name matches: the member world-navs. The 2026-10-13 "wait, no scroll" rule is not the live rule.
5. Low HP at the retreat threshold: the member can leave (mother tree, scroll, or safe zone). Potion and self heal still come first. The 2026-10-13 "no retreat" rule is not the live rule.
6. Leader target changes: the next assist selection uses the new target. A blocked shot does not pick a different monster.
7. Pause: policy `STOP` is `IDLE`. The executor drops the mouse when the action is not `IDLE` or a button is held.
8. Solo mode: `party_leader_no_loot` is not set, and `PartyMemberManager` is not constructed.

Unit tests under `Engine/app/_06_party/tests/` lock the branches they name. They are not an in-game acceptance pass.

## Original MVP text (2026-10-13)

The rest of this file is the original note. Where it disagrees with the sections above, the sections above are the live loop.

### Objective as written then

Follow one selected team leader and help kill the leader's target. Keep the member close enough to participate in the same farming activity. The leader may be human-controlled or an existing solo bot; a new leader bot is not a prerequisite.

User-confirmed direction: small follow-and-help MVP, implemented as an entirely separate module within the current project. The detailed defaults below are recommendations, not implemented or finalized settings.

## Minimal behavior

- Select a leader by character name; resolve and retain a validated runtime identity.
- Follow on the same map using walkable positions near the leader, never deliberately selecting the leader's occupied tile.
- Use separate follow-start and follow-stop distances to avoid movement oscillation.
- Assist only a freshly confirmed monster target of that leader. Do not select arbitrary nearby monsters as a substitute.
- Revalidate target existence and identity before attacking. Disengage when the leader moves beyond the follow leash; catching up takes priority over continued farming.
- Retain configured self HP/MP potions and antidote where supported. Low HP does not invoke solo teleport, mother-tree retreat or shopping.
- When the leader is missing, information is stale, or the map changes: stop new combat/movement, show the reason and reacquire. Cross-map travel is outside the first version.
- On member death: stop and report. Automatic respawn/rejoin is deferred.
- Start, pause and stop must work during movement and combat; release held input on cancellation.

## Loot boundary

Recommended first milestone: the member follows and attacks while the leader handles loot. This avoids delaying the core MVP for pickup ownership and F4 behavior.

A subsequent small increment can permit nearby pickup while the leader is idle and within the follow leash. It must not chase distant drops or keep looting when the leader moves. Exact designated/random loot distribution and supply pickup quantities remain out of scope.

## Decision order

```text
Read local world and selected leader
  -> Stopped, paused, dead or invalid local data? Stop issuing actions
  -> Leader missing/stale/on another map? Wait and reacquire
  -> Allowed self-recovery needed? Use local recovery
  -> Outside follow-start distance? Follow until within follow-stop distance
  -> Fresh leader target and attack remains within leash? Assist
  -> Otherwise hold near leader
```

Input execution must be bounded and cancellable so the next observation can revise the decision. Self recovery does not authorize departure.

## Separate module

Implemented layout:

```text
Engine/app/_06_party/
  config.py         # PartyMemberConfig
  state.py          # MemberRuntime
  leader.py         # resolve leader by name/ent
  follow.py         # hysteresis + approach tile
  assist.py         # external target or leader-strike proxy
  policy.py         # pure decide ladder
  intents.py        # ActionIntent builders
  manager.py        # PartyMemberManager.decide
```

Enable (single path): Party tab (right of Item) → Run as party member → Start applies bag to profile. Loot: `random_loot` / `loot_role`.


Keep an independent entry point, configuration namespace, runtime state and decision loop. Do not call the solo DecisionManager or enter its farming/retreat/shop columns. Avoid shared mutable solo decision globals. Never allow solo and member loops to control the same game session concurrently.

Reuse suitable low-level memory readers, map/path queries and input primitives through narrow adapters. Inspect dependencies before reuse: existing high-level action code can carry solo assumptions or unbounded waits. Separate module does not require copying the entire engine; native drivers and established read/input mechanisms can remain shared dependencies.

## Existing prototype

`Tools/follow_player/follow_logic.py` and `follow_session.py` contain a follow-and-hunt prototype. Its logic includes distance-based follow/hunt/hold and preference for monsters attacking self or the followed player. That is useful reference material but is not equivalent to assisting the leader's current target. Do not assume it already satisfies the MVP.

## First technical validation

Confirm that available observations reliably identify the selected leader's current monster target. Seeing monsters attacking the leader is not equivalent. Use a stable entity identity, fresh observations and explicit invalidation. If the existing readers cannot expose the leader's target reliably, add the smallest required observation or leader-state interface before claiming exact assist works.

## Deferred features

Party invite/kick, new leader bot, auto leader transfer, full party roster synchronization, targeted healing/buff rotation, protection queue, courier, buying/selling, item distribution, independent schedules, cross-map following, automatic respawn/rejoin and stationary-position configuration.

## Acceptance scenarios

1. Leader walks: member follows without standing on the leader or oscillating at the threshold.
2. Leader attacks A: member assists A rather than an unrelated nearby B.
3. Leader leaves during combat: member stops chasing A and catches up.
4. Leader becomes unobservable or changes map: member waits visibly; no blind roaming.
5. Low HP: configured local potion recovery works without solo teleport/shop/retreat.
6. Leader switches targets or target dies: member drops invalid/stale targeting and follows current validated intent.
7. Pause/stop during input: actions terminate promptly and held input is released.
8. Solo mode: existing behavior is unaffected by adding the separate module.

Use pure decision tests and recorded/mock observations first, then controlled in-game follow/assist trials. Do not claim in-game acceptance from unit tests alone.
