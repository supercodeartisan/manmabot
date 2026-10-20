# Isolated party-member MVP

Date: 2026-10-13
Status: v1 member brain implemented under ``Engine/app/_06_party/`` (follow / assist / hold). Session enables via profile ``party_member_enabled`` + ``party_leader_name``.

## Objective

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
