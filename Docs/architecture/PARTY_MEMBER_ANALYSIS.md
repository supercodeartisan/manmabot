# Party member: the 2026-10-13 request, against the live loop

Date of the request: 2026-10-13. Updated 2026-11-10 against the live call path.

The live party loop is not this proposal. Read these first:

- [Who runs a tick](PARTY_RUNTIME.md)
- [Which function emits which action](PARTY_CODE_TO_ACTION.md)
- [Branches](PARTY_EDGE_CASES.md)

The sections below are the original request. They are not a specification of the current code. The table after this paragraph is the difference that matters.

| 2026-10-13 request | Live code |
| --- | --- |
| A future member must not use solo departure | `party_critical_escape` runs the retreat column (mother tree, talking scroll, safe zone) from the party recovery overlay. After HP recovers, a solo `post_retreat` walk back to a hunt map is dropped so the member follows the leader. |
| Low HP must not leave on its own | A retreat at the party retreat threshold does leave. Potion and self heal run first, inside `urgent_self_survival`. |
| Assist the leader, then a protection queue (finish A, then B) | One target per tick. Out of attack range, the member walks the formation slot and does not path to the monster. There is no finish-A-then-B queue. |
| No cross-map travel in the first version | `PartyJoinNav` plans a world-nav route to the leader's party-memory map and coordinate. An invite popup or an unconfirmed leader name clears that route. |
| Leader handles loot; member does not | A member loots when the leader has stood on one tile for 0.7 s and the policy kind is hold or follow. The leader loots an on-screen pile within 7 tiles and does not use the farm rect. |
| No leader bot, no invites, no supply | The leader process is `PartyLeaderManager`. Invites, the rally stand, the shopkeeper buy/drop, and mage list heal are live. `brains/LeaderBrain.adopt` is not the caller. |
| Stationary mode blocks every move | A point mark arms the leader turret (5×5 walk-back, 3×3 stand). Members learn that on a later policy ingest as `leader_mode=turret`. Area marks stay a moving hunt. |
| Death reports and waits | A dead member policy returns `IDLE`. The member loop does not run `survival.death`, so it does not emit `RESPAWN` from that column. |

No claim below this heading is evidence that the behavior shipped.

## Purpose and evidence (2026-10-13)

The project's existing documents describe the solo bot. They are the baseline for deciding what a future party member must keep, replace, or disable. Party requirements come from the user's requested behavior, not from an existing implemented party specification.

Read the following together with current code; older roadmap/status documents do not establish implemented behavior:

- [Logic overview](LOGIC_OVERVIEW.md)
- [Decision hierarchy](DECISION_HIERARCHY.md)
- [Decision steps](DECISION_STEPS.md)
- [Recent decision changes](../decision_change_log.md)
- [Detailed decision history](../decision/decision_change_log.md)
- [Actual decision columns](../../Engine/app/_04_decision/steps/columns.py)

## Current solo workflow

```text
Start session
  -> Read profile and schedule
  -> Read character, monsters, inventory, buffs and map
  -> Travel to the configured hunting location
  -> Choose recovery / retreat / shop / buff / fight / loot / search
  -> Execute keyboard or mouse input
  -> Read the result and repeat
```

The five persistent modes are FARMING, TRAVELING, RETREATING, SHOPPING and WORLD_NAV. Inside each mode, ordered decision steps run until the first applicable step wins. Ordinary island farming evaluates survival, retreat, shopping and navigation before combat and loot. Potions and nearby pickup can also be side intents.

The engine pipeline is session -> perception -> world update -> GameState -> DecisionManager/Blackboard -> ActionIntent -> ActionExecutor -> feedback.

The solo bot independently maintains its own farming cycle. A party member must instead maintain its assigned contribution to the party.

## Keep, replace, or disable

| Situation | Existing solo behavior | Proposed full party-member behavior |
| --- | --- | --- |
| Low HP | Recovery can lead to teleport, safe travel or mother-tree retreat | Keep local recovery; request healing/protection; do not independently leave at the solo threshold |
| Low MP | Can start safe recovery/retreat | Report low MP, prioritize essential spells, follow party recovery policy |
| Monster attacks self | Can immediately replace current target with an attacker | Report threat and follow party protection priorities |
| Another member attacked | Self-protection logic is insufficient | Track attacker and protect the member according to policy |
| Target dies | Select another suitable local target | Select leader target, queued protection target, or another party-permitted target |
| No monsters | Search, patrol, move deeper, or eventually return | Follow leader in moving mode; hold assigned position in stationary mode |
| Stuck | Some recovery paths move or teleport | Only use movement allowed by party policy; report failure |
| Low supplies | Independent shop trip | Request supplies; leave only on an assigned resupply task |
| Heavy inventory | Independent selling | Report capacity and apply party handling policy |
| Nearby loot | Main or side pickup | Collect permitted loot or needed supplies under distribution policy |
| Schedule changes | Individual routine advances | Move to assigned destination under party schedule |
| Death | Solo respawn/recovery | Report death, apply respawn setting, and rejoin |
| Leader goes to town | No complete party response | Configured remain/follow/pause/replacement-leader behavior |

Reuse sensing, inventory checks, potion use, attack execution, pathfinding, map transitions and shop mechanisms where appropriate. Replace the authority to invoke them: having a teleport or shopping capability does not authorize independent departure.

## Conflicts requiring explicit changes

### Multiple departure paths

HP, MP, idle return, confined escape and retreat paths appear in multiple modes. Recent changes also allow selling before HP retreat under a weight condition. Disabling a single farming teleport check is insufficient. The full member policy must govern all departure paths, including travel and shopping.

Required low-HP behavior: local recovery and a party help request, without independent departure. Any future emergency escape is a separately configured policy, not an inherited solo default.

### Healing during combat and recipient selection

`Engine/app/_04_decision/behaviors/mode_actions.py::emit_heal` currently blocks healing while attacking. Urgent party healing must be able to interrupt damage. `Engine/app/_05_action/controller.py::_heal` presses the assigned skill without the explicit party-recipient selection required here.

Party healing requires recipient identity, fresh HP data, thresholds, range checks, recipient targeting and cast verification. Additional HP sliders alone are insufficient.

### Party-aware target eligibility

`Engine/app/_04_decision/combat_query.py::contested_mob_cells` and ordinary target filtering need party awareness. A leader attacking a monster must not disqualify that monster as another player's claim. Unrelated-player claims retain their configured treatment.

### Protection queue versus immediate switching

`Engine/app/_04_decision/behaviors/combat.py::prefer_attacked_me_sticky` can switch immediately. The requested full-party rule is: attack A -> observe B attacking mage -> queue B -> finish A -> revalidate B -> attack B. Urgent healing is separate and may interrupt the healer before A dies.

### Stationary mode applies to all movement

Disabling patrol alone does not prevent attack chase, loot approach, unstick movement or return flows. Stationary mode must constrain every movement source and must not chase out-of-range targets.

### Pickup selection versus pickup execution

The action controller uses F4 pickup. `Engine/app/_04_decision/loot_sides.py` can bypass ordinary ownership filtering. Selecting one item in decision logic does not guarantee F4 picks only that item. Assigned loot and exact supply quantities need pickup verification, and side pickup must obey the same policy.

### Party EXP is not target-death evidence

The current `EXP_KILL_RELEASE_ENABLED` flag is false. Keep EXP-based target release disabled: another party member's kill can award EXP without the local target dying.

## Proposed full member workflow

1. Observe/report HP, MP, position, inventory, target and attackers; receive fresh party information.
2. Validate current leader, assignment, hunting mode, destination, duties and loot permissions.
3. Perform allowed local recovery, request protection and perform urgent assigned healing.
4. Process leader changes, town behavior, regrouping, death recovery and scheduled movement.
5. Follow within configured distance or hold the assigned position.
6. Perform assigned buffs and routine healing.
7. Fight under assist/protection policy and movement constraints.
8. Collect permitted loot, verify inventory changes and report deficits.
9. Wait when no permitted action exists; never fall through to solo patrol, shopping or retreat.

## Full feature scope versus first MVP

Full scope includes membership, follow/hold, assist, protection, healing/buffs, controlled loot, supply requests, leader replacement, death/rejoin, schedules and optional courier duties. This is not the scope of the initial MVP.

The user subsequently narrowed the initial MVP to following one leader and helping that leader farm. See [the isolated MVP note](PARTY_MEMBER_MVP.md). The live loop is wider than that note. Use the three party documents linked at the top.

## Architecture recommendation (2026-10-13)

Preserve reusable perception and action mechanisms but isolate party decisions from the solo decision columns. Add explicit party state for full party functionality. The largest change is what the member is allowed to decide independently, rather than the physical input mechanism.

No implementation was made for the 2026-10-13 analysis. The implementation that exists now is the live loop linked at the top of this file, not a completion of every row in the proposal.
