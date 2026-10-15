# Party member: analysis of the existing solo bot

Date: 2026-10-13
Status: analysis and proposed design, not implemented or tested in-game.

## Purpose and evidence

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

The user subsequently narrowed the initial MVP to following one leader and helping that leader farm. See [the isolated MVP proposal](PARTY_MEMBER_MVP.md).

## Architecture recommendation

Preserve reusable perception and action mechanisms but isolate party decisions from the solo decision columns. Add explicit party state for full party functionality. The largest change is what the member is allowed to decide independently, rather than the physical input mechanism.

No implementation changes were made for this analysis.
