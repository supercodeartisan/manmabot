# Decision change log

## 2026-10-16 — party travel/stop bands + combat close-in + loot gate

Intent: mode-aware follow — travel leash (`follow_tiles`), settle to `stop_tiles` when leader pose is stable, combat assist with short close-in when out of range, loot only when leader not farming and within stop band.
Shared: `policy` (`leader_farming` / `leader_stopped` / `CLOSE_IN`), `assist_in_attack_range`, `plan_close_in_intent`, Party tab follow+stop spins, profile/runtime. Solo DecisionManager farming columns unchanged.
Affects: party-member follow/assist/loot only.
Consent: user (“implement” after band design).
Result: travel vs stop vs combat step-in; loot gated off mid-fight.

## 2026-10-16 — party follow single 3-tile + no synthetic assist cast

Intent: logs showed follow re-clicking ~5×/s on the same tile, and mage_attack skill-press with no live monster (synthetic/off-screen assist) → cursor thrash. Follow uses one threshold (default 3): farther → follow, else assist/hold. No start/stop hysteresis. Assist only live local monsters; mage Esc after failed aim search.
Shared: `follow_kind` / `PartyMemberConfig.follow_tiles`, `plan_follow_intent` (idle in-transit / at approach), `assist` (no combat synthetics), `mage.py` Esc on aim fail, Party tab one spin. Solo DecisionManager farming columns unchanged except safer mage Esc.
Affects: party follow smoothness; party assist; mage cast cancel on miss.
Consent: user (check 10min logs; no start/stop; follow if out of 3; improve following; cursor rush / no target skill).
Result: single follow distance; live-only assist; cast aim thrash cancelled.

## 2026-10-16 — party loot roles + Party tab (Item right)

Intent: Party settings live in their own tab (right of Item). Random loot ON → every member may loot nearby drops (no ownership gate). Random OFF → `loot_role` none vs responsible (ownership gate on). Side F4 while near; primary approach only on HOLD.
Shared: `UI/ui_qt/editors/party_tab.py`; Hunt party card removed; `app._06_party.loot` + `PartyMemberConfig.random_loot` / `loot_role`; profile / task_runtime / BotController. Solo DecisionManager farming columns unchanged.
Affects: party-member HOLD loot + side pickup; schedule Party tab.
Consent: user (“go” after random ON all / OFF role architecture).
Result: Party tab wired; loot gates applied in member decide.

## 2026-10-16 — party heal/buff via solo helpers (no retreat)

Intent: party member uses solo heal skill + buff + potion sides; never retreat / mother-tree / escape.
Shared: `app._06_party.support.apply_party_support` → `emit_heal` / `maybe_cast_buff` / `arm_potion_side_intents` with `retreat_starters=False`. `BotController` always passes blackboard side_intents in party mode. Solo DecisionManager columns unchanged.
Affects: party-member primary HEAL/BUFF before follow/assist; potion sides parallel.
Consent: user (“go” after approach choice: party brain owns call site, reuse solo helpers).
Result: heal/buff/potions on; retreat paths not called.

## 2026-10-16 — party follow: shortest of walk vs WORLD_NAV (scroll/TP)

Intent: when the leader teleports far, member was only TRAVELING (blind walk). Pick the cheaper of local walk vs WORLD_NAV (talking scroll / TP / gate).
Shared: `app._06_party.follow_route.choose_follow_route`, `PartyMemberManager` FOLLOW → `PartyJoinNav` when WORLD_NAV wins (`follow_nav`). Solo DecisionManager unchanged.
Affects: party-member FOLLOW when dist ≥ 24 and scroll/TP beats walk.
Consent: user (must use winner of shortest path, not blind walk).
Result: same-map long chase can scroll/TP; short chase still walks.

## 2026-10-16 — fix: party follow idle (game xy → nav) + OFF_UI banner

Intent: screenshot showed kind=follow action=idle while leader OFF_UI with party xy ~32k. Follow A* uses nav tiles; party xy was raw game → no_path/idle. Banner did not show IN_UI/OFF_UI or SAME_MAP.
Shared: `_party_tile` → `game_to_nav`; Party monitor `[OFF_UI|SAME_MAP]` + `why=`. Solo unchanged.
Affects: party-member same-map FOLLOW travel intent; Party etview status line.
Consent: user (see UI — not finding / never showing not in UI).
Result: party pose converted to nav; banner shows OFF_UI/SAME_MAP and follow fail reason.

## 2026-10-16 — fix: lose leader must still FOLLOW (party pose)

Intent: when the entity sweep loses the leader, the member was HOLD/WAIT and never chased. Drive movement from PartySubsystem pose; UI only gates assist.
Shared: `decide_policy` (off-UI → always FOLLOW), sticky pose 15s/45s, `BotController` always `set_local_map_id` on live mapId. Solo unchanged.
Affects: party-member off-UI chase + same-map detection.
Consent: user (check and fix — lose leader never follows).
Result: off-UI always follows party/sticky tile; local mapId updates every tick.

## 2026-10-16 — party UI detect → off-UI follow → other-map WORLD_NAV join

Intent: detect whether the leader is in the current UI (entity sweep); if not, go to PartySubsystem xy; if other map, WORLD_NAV (scroll/gate/teleporter) to leader map near their pose, then resume follow/assist.
Shared: `app._06_party.policy` (`leader_in_ui` / `JOIN_MAP`), `join_map.PartyJoinNav` + session Blackboard stash, `PartyMemberManager`, `BotController` join-path scroll/gate/TP. Solo DecisionManager farming columns untouched.
Affects: party-member only — assist requires leader in UI; other-map no longer WAIT.
Consent: user (“alright, go” after scope including other-map teleport).
Result: off-UI same-map FOLLOW; other-map join via WorldNavSession; then follow/assist.

## 2026-10-16 — off-screen follow via PartySubsystem xy/mapId

Intent: when the party leader leaves the local UI/entity sweep, the member still follows using `party_listen` / realtime_party pose (xy + mapId), not screen entities.
Shared: `app._06_party.leader.resolve_leader` (prefer PartySubsystem tile), `PartyMemberManager._apply_sticky_party_pose` (3s sticky on 0,0 glitch). Solo DecisionManager untouched.
Affects: party-member FOLLOW when leader is off-screen; WAIT on other mapId (unchanged).
Consent: user (“implement” after Ask-mode off-screen follow confirm).
Result: party xy is follow truth; brief missing/0,0 reads reuse last same-map pose.

## 2026-10-16 — Party button opens etview-style overlay

Intent: Party toolbar button shows etview.exe core UI (BitBlt underlay + circle/cross markers + ATK orange line / red X) combined with party status/decisions.
Shared: `session.etview_probe` (print_state + contested), `ui_qt.debug.party_etview.PartyEtView`, `PartyMonitorWindow` splitter. Solo DecisionManager untouched.
Affects: Party monitor window only.
Consent: user (bring etview core into Party button UI).
Result: Party window = etview canvas (leader ring + ATK target) over live capture + existing party panel.

## 2026-10-16 — party assist knows leader ATK target (etview)

Intent: party UI/module monitor the leader the way etview does — AttackAction owner→tgt — and assist that monster (not only “farming” with no who).
Shared: `app._06_party.assist` (`describe_leader_target`, materialize off-screen contested tgt), `leader` / `manager` / `state` target fields; Party monitor TARGET line. No solo DecisionManager.
Affects: party-member ASSIST when leader is attacking; Debug/Party banner shows target name/guid.
Consent: user (check etview; fix assist who-target).
Result: contested leader row → local or synthetic WorldObject; UI shows `ATK → name`.

## 2026-10-16 — sticky leader ent/guid track + UI leader highlight

Intent: keep tracking the party leader via sticky `ent`/`guid`/`track_id` whether farming or idle; show farming/visible/off-screen state in Party monitor.
Shared: `app._06_party.leader` / `manager` / `state` / `config`; Party monitor banner only. No solo DecisionManager changes.
Affects: party-member reacquire + assist proxy when entity blinks; Debug/Party UI leader highlight.
Consent: user (ent-track while farming; highlight leader status).
Result: implemented.

## 2026-10-16 — party assist tracks leader attack (contested_mobs)

Intent: when the party leader is attacking a monster, the member assists that mob (not only mobs hitting the leader).
Shared: `app._06_party.assist` only — `resolve_leader_attack_target` + `pick_assist_target` order `leader_attack` then `leader_strike`. No sensor/DecisionManager/UI changes.
Affects: party-member ASSIST when near leader and `assist_leader_strikes` is on.
Consent: user (leader attack tracking; never touch other modules).
Result: implemented.

## 2026-10-16 — party member uses memory leader (no typed name)

Intent: Hunt UI no longer asks for leader character name. Party-member Start needs only the checkbox; after join, `party_listen` supplies the game party leader.
Shared: `party_member_block` / `resolve_leader`, `BotController` `party_mode`, `task_runtime` party apply, Hunt tab party card. Solo decide path unchanged.
Affects: party-member enable and leader resolve only.
Consent: user (remove leader name; get leader from memory after join).
Result: implemented.

## 2026-10-16 — party-member sensor for leader stats (solo unchanged)

Intent: when Hunt UI “Run as party member” is on, read PartySubsystem via an independent `party_listen` sensor and use leader name/HP/MP/xy/mapId for follow when the leader entity is not nearby. Solo Start never loads the party DLL and never calls `PartyMemberManager`.
Shared: `PerceptionSensors.capture_tick(party=…)`, `PartyListenReader`, `resolve_leader` / `LeaderView`, `PartyMemberManager.decide`. Solo `DecisionManager`, retreat, shop, HP columns, login, and world-nav stay as they are.
Affects: party-member follow when the leader is out of entity range (memory coords); wait on other mapId; assist still requires a visible leader entity.
Consent: user (party logic must not affect current solo; only after UI party-member check).
Result: implemented. Build `Engine/analysis/party/build_party_listen_dll.bat` before live reads.

## 2026-10-14.8 — search hops use plan_body_click + 0.1s reclick

Consent: user asked for phase 1+2 on search hops only.

Intent: farm search keeps ``next_leg`` coverage goals; each hop click uses ``plan_body_click``. Standing body re-clicks the hop ~0.1s (``classify_ground_reclick``). Coverage visit counts on ``search_leg_goal`` arrival.

Shared: `emit_search_hop`, `plan_body_click`, `collect_body_tiles`, blackboard `search_leg_goal` / `search_click_at`.

Affected: farming SEARCHING hops only. Travel/loot/combat unchanged. LEG_TICKS / unstick timers unchanged.

## 2026-10-14.7 — until_walk re-clicks re-check cursor

Consent: user agreed to apply cursor verify on until_walk re-clicks.

Intent: after a NORMAL travel hop verify, mid-loop re-clicks must not fire if the cursor becomes attack/dialog. Stops further clicks with `how=cursor`. Pose-pulse unchanged.

Shared: `MouseController.click(cursor_ok=...)` / `_click_until_walk`, `verified_click` gate for `until_walk`.

Affected: SEARCHING / TRAVELING / loot-approach / unstick ground hops via `travel_click`. Attack/loot single clicks unchanged.

## 2026-10-14.6 — remove ground-click until_walk budget

Consent: user asked to remove only the 0.4s budget.

Intent: restore 10/11 contract — ground hops keep clicking until body stand/walk (or unread 1s). The 10/14 `GROUND_CLICK_BUDGET_S=0.4` early exit caused post-kill search holds with no walk started. Pose-pulse during execute stays.

Shared: `MouseController._click_until_walk` only.

Affected: SEARCHING / TRAVELING / loot-approach / unstick ground hops. Attack clicks unchanged. Execute pose-pulse unchanged.

## 2026-10-14.5 — field map hygiene (no accidental edge wipe)

Consent: user asked to remove traps from the TI/mainland map cleanup audit.

Intent: refuse PNG-only prebuild on packs that already have `edge_*.npy`; document `Build_Field_Edge_Packs.bat` as the only field rebuild; quarantine stale `Others/maps` TI/mainland images; field-view downsample uses majority vote; `is_game_walk_clear` uses `can_step` so fence edges close client polylines on travel-click paths too.

Shared: `build_nav_prebuild.py`, `is_game_walk_clear`, `field_terrain._kinds`, Support README, Others TI/mainland `legacy/`.

Affected: field rebuild ops, field-view wall dots, `select_click_waypoint` / travel clicks that use `is_game_walk_clear`. ActionExecutor unchanged.

## 2026-10-14.4 — field travel uses body-avoid hop (plan_body_click)

Consent: user agreed to apply the same guide→interim→hop plan as dungeon patrol / ti_edge_nav to general field `emit_travel_hop`, without changing ActionExecutor or cursor search.

Intent: every travel hop always calls `plan_body_click` (empty bodies when `state` is missing). Patrol-only `skip_blocked_patrol_point` on no-click; other purposes hold + IDLE and retry. `click_clear` / avoidance BFS use `terrain.can_step` so field N/E fences close the client polyline.

Shared: `_follow_body_click` / `emit_travel_hop`, `click_clear`, avoidance `_bfs`.

Affected: field travel, enter-farm, shop walk, world_nav walk. Patrol/loot already on the same API. Cursor search, reclick timers, unstick 360° unchanged.

## 2026-10-14.3 — body action vfts for the 10.14.2 client

Consent: user asked to match every RVA used to detect the character's action to the current patch.

Intent: `ActionComponent+0xC0` and `ActorController+0x58` class RVAs follow live RTTI. Walk is `MovingAction` `0x11E0590`, walk-back `0x11E0548`. Turn, spell, pickup, shop, commands, and the other body labels move with them. Stand, attack, death, damaged, and effect were already on this image. Decision branches are unchanged.

Shared: `body_pose.py` `BODY` / `CMD` / `MOVE_VFTS`, registry action keys, `action_timeline.py`, `interact_watch.py`, `probe_my_anim.c`.

Affected: action view, `body_is_moving`, ground-click stop, travel reclick, loot hop hold.

## 2026-10-14 — LOS blocked by N/E fence edges between open tiles

Consent: user agreed that attack LOS must fail when neighboring open tiles on the segment cannot step across a fence.

Intent: `line_of_sight_clear` still requires intermediate walkable cells, and now also requires an open shared edge (`_los_step_open` / bit0 N/E) between every consecutive segment pair. Goal tile may stay non-walkable; the edge into it is still checked.

Shared: `line_of_sight_clear`, `_los_step_open` → `attack_line_clear`, dungeon/field engage filters that use it.

Affected: target selection when a fence sits on the Chebyshev LOS polyline.

## 2026-10-14 — LOS blocked by N/E fence edges between open tiles

Consent: user agreed that attack LOS must fail when neighboring open tiles on the segment cannot step across a fence.

Intent: `line_of_sight_clear` still requires intermediate walkable cells, and now also requires an open shared edge (`_los_step_open` / bit0 N/E) between every consecutive segment pair. Goal tile may stay non-walkable; the edge into it is still checked.

Shared: `line_of_sight_clear`, `_los_step_open` → `attack_line_clear`, dungeon/field engage filters that use it.

Affected: target selection when a fence sits on the Chebyshev LOS polyline.

## 2026-10-14 — TI/mainland fence_bw packs + edge portal prebuild

Consent: user asked to replace Talking Island and mainland map packs with fence_bw_4x display, prebuild portal graphs like ti_edge_nav (`can_step`), keep `.s32` only under `Support/field_s32` (not shipped), and defer avoidance-hop transplant. map_4 coverage is sufficient.

Intent: Deployable packs ship `*_fence_bw_4x.png` + `nav_prebuild` (including optional edge npy). Fine A* / portal neighbors use N/E fences when edge layers are present. Dungeon packs unchanged. Body-avoid hop policy unchanged.

Shared: `edge_layers`, `TerrainMap.can_step` / `block_n`/`block_e`, `build_portal_graph`, `build_and_save_edge_prebuild`, `Tools/nav/build_field_edge_packs.py`.

Affected: talking_island and mainland travel pathfinding and map-editor/debug terrain image. `.s32` rebuild input only in Support.

## 2026-10-14.2 — client rebuild read addresses

Consent: user said the client was patched again, `D:\dist` was replaced, and this project's memory reads should follow it.

Intent: RVAs and vfts move to registry v9 (`MODULE_SIZE` 0x3F5F000, globals +0x10, RTTI rebind). Structure offsets and poll periods stay.

Shared readers: registry, `char_offsets.txt`, `entity_offsets.txt`, inventory/hotbar files, `offsets.json`, `body_pose.py` (stand/attack/death/effect), `shop_listen.c`.

Affected: live reads. Walk/turn/spell/command vfts are not in the new registry; those body labels stay on the previous image. Decision logic is unchanged.

## 2026-10-14 — avoid radius 10 + farthest guide hop click

Consent: user asked to set the avoid window to 10 tiles, and to check/fix dungeon movement still clicking only Chebyshev neighbors.

Intent: `AVOID_RADIUS` 7→10 (21×21 window). When the interim waypoint fails hop/clear, `choose_body_click` keeps the **farthest** legal guide tile inside `max_hop`, not the first neighbor. Empty-body `plan_avoidance_click` also requires hop/region/clear before returning the waypoint.

Shared: `AVOID_RADIUS`, `plan_avoidance_click`, `choose_body_click`, `_farthest_guide_click`. Dungeon patrol/travel/loot that call `plan_body_click`.

Affected: avoidance hop distance and body window. Field travel that still uses `plan_travel_click` / `select_click_waypoint` is unchanged (already farthest). Tool `ti_edge_nav` imports the same radius.

## 2026-10-14 — 10.14 client read addresses

Consent: user asked to replace this project's memory read addresses with `D:\dist` after the client update, and to leave bot logic and poll periods alone.

Intent: module RVAs and vft values move to the 2026-10-14 registry. Structure offsets (`MapIdOff` 0x718, holder/subs, PRES_B, stat decode) stay. Poll intervals stay.

Shared readers: registry, `char_offsets.txt`, `entity_offsets.txt`, inventory/hotbar offset files, `offsets.json` map vft, `body_pose.py` action vfts, `shop_listen.c`.

Affected: live memory reads (map, player, entities, HP, buff, UI, hotbar, inventory, shop). Decision, movement, and combat branches are unchanged.

## 2026-10-14 — dead source actors still mark a drop OTHER

Consent: user asked the bot loot claim to follow the etview result, using only this project's code.

Intent: a zero-contrib pile is OTHER while a source actor whose guid sits within the last-hit window is still in the sweep, including a corpse. Dead actors are kept for that test and left out of the JSON roster. FREE or contrib above 30 is unchanged.

Shared: `print_state.c` sweep retention and JSON emit. Live monster and item lists stay the same.

Affected: `own` on a pile whose source body is still in memory.

## 2026-10-14 — log item claim when loot is chosen

Consent: user asked to record item state when a pile is chosen, so the next log can be analyzed.

Intent: one `loot decide` line with name, guid, own, contrib, and whether the main ownership gate would allow it. Selection rules are unchanged. Side F4 logs `gate=skip` and does not repeat the same id and claim every tick.

Shared: `begin_loot_item`, `arm_loot_side_intent`.

Affected: loot log only.

## 2026-10-14 — skip other players' monsters by guid

Consent: user asked to match contested mobs by id, not world cell.

Intent: a new engage drops a monster only when contested `guid` equals `memory_guid`. A monster with no guid stays eligible. World cells are not a claim.

Shared: `contested_mob_guids`, `is_contested_monster`, `list_attackable`, `describe_attackable_filter_skips`. Sticky combat and attacks-me force still bypass this list.

Affected: new targets chosen by `nearest_attackable` on farm and in dungeons.

Result: implemented. `test_attack_filter.py`. Confirm on the next bot log line `contested guid filter`.

## 2026-10-14 — skip a patrol point after 10s with no click

Consent: user asked to leave a patrol midpoint when a guide exists but living bodies leave no click for 10 seconds.

Intent: the clock starts on the first such plan for that midpoint. A click, a missing guide, or a new goal clears it. At 10 seconds the next midpoint becomes the travel goal. A missing terrain path still uses the old failure path.

Shared: `emit_travel_hop` for patrol, `skip_blocked_patrol_point`. Loot, field travel, and combat selection are unchanged.

Affected: dungeon patrol only, and only while the click cannot be chosen.

## 2026-10-14 — dungeon loot path 15, ignore blacklisted attackers

Consent: user asked for both dungeon-only changes.

Intent: a new dungeon loot pick requires an A* route of at most 15 steps. Combat new picks stay at 30. In a dungeon a species-blacklisted monster that attacks is not engaged and an existing lock on that species is dropped. Outside dungeons the attacks-me bypass stays.

Shared: `list_lootable` path cap, `list_attacked_me_targets`, `nearest_attacks_me_force`, `continue_sticky_combat`. Field loot Chebyshev cap and field self-defense are unchanged.

Affected: which piles a dungeon walks to, and whether a blacklisted species pulls the character into a fight.

## 2026-10-14 — dungeon patrol and loot walk around living bodies

Consent: user agreed the patrol/loot scope, then set the loot goal to the pile tile and required a 0.1s reclick while the body is not walking.

Intent: dungeon patrol and loot approach use the interim waypoint and the avoidance click. The hop still arrives at the click tile. A body that is not walking gets that same click again every 0.1s. No safe click waits and retries; a missing terrain path still uses the old failure path.

Shared: `plan_body_click`, `emit_travel_hop` when purpose is patrol, `tick_loot_item` walk. `plan_travel_click` stays for field travel, shop, retreat, and unstick. Combat and loot choice order is unchanged. Pickup range is unchanged.

Affected: dungeon patrol clicks and the walk onto a loot pile. A blocked click no longer waits 2s on those two walks.

## 2026-10-13 — a diagonal gap stays open unless both shoulders are walls

Consent: user stated the client rule. Two living bodies, or a living body beside a real wall, do not close the diagonal. It closes only when both shoulders are real walls.

Intent: avoidance clicks and the window search use the same shoulder test as terrain `diagonal_open`. Stepping onto a living body or a wall is still refused.

Shared: `click_clear`, avoidance `_bfs`. Travel hop selection does not call these. `is_game_walk_clear` and `select_click_waypoint` are unchanged.

Affected: avoid-view click choice when a shoulder is a living body. A tile with a living body on it is still not a click.

## 2026-10-13 — ground click walks the diagonal, then the axis

Consent: user confirmed on the client that the walk is diagonal first in tile coordinates, then the leftover axis, and asked to update every dependent check.

Intent: `game_client_walk_tiles` emits that order. Equal `|dx|` and `|dy|` stay a pure diagonal. `(0,0)→(5,2)` is `(1,1) (2,2) (3,2) (4,2) (5,2)`.

Shared: `is_game_walk_clear`, `is_click_valid`, `click_clear`, avoidance clicks, and the avoid-view orange line.

Affected: which travel hops are allowed, and loot or combat ground-click clearance. Attack range still uses the straight line.

## 2026-10-12 — recast Teleport to Mother until the World Tree blessing

Consent: user agreed the plan, then added that recovered HP ends the retreat even when the blessing is still absent.

Intent: one Teleport to Mother press is not arrival. While this retreat is open and HP is under 95%, a buff read 2 seconds after the press with no 세계수의 가호 (strId 993) presses the skill again if MP can pay the 10 cost. MP below that waits. An untrusted buff snapshot waits. HP at or above 95% leaves without the aura.

Shared: `_tick_mother_tree_retreat`, `_hold_until_world_tree_blessing`, `world_tree_blessing_active`, `finish_retreat` (drops `mother_tree_cast_at`). Every mother-tree entry already uses this tick: HP-threshold retreat, post-land, teleport fallback, post-respawn, dungeon GUI.

Affected: standing at the tree before the aura is confirmed. Heal and Body to Mind run after the blessing is on, or after the skill can no longer be used. Shop, `begin_retreat`, buff read, and the key press are unchanged.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — sticky yields to a monster that has attacked me

Consent: user asked to implement the agreed attacked-me latch. A monster that has once attacked stays latched after the attack row drops. Sticky switches immediately when it has not attacked me, or when a latched monster has a lower known level.

Intent: `attacked_me` is set from `attacks_me` and cleared on death, bait, list removal, or a MapSubsystem mapId change. Synthetics that exist only for the current attack row still end when that row ends. Same level keeps the current sticky. Unknown level ranks after every known level. The previous target is not given up.

Shared: `sync_attacks_me_force_targets`, `prefer_attacked_me_sticky`, `begin_engage`, `rebind_sticky_target`, `note_attacked_me_map`.

Affected: farm engage, travel engage, and world-nav walk combat. Heal still waits while the new sticky is alive. Loot still waits while that lock is held.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — HP retreat sells first when weight is at least 50%

Consent: user asked to sell before an HP-threshold retreat when the weight gauge is at least 50%, and to retreat immediately when it is below 50%.

Intent: the retreat decision checks weight once. At or above 50%, the existing sell queue runs, and the HP retreat starts when that queue ends. Below 50%, an open shop trip is dropped and retreat starts on that tick. Exactly 50% sells first.

Shared: `apply_hp_actions`, `clear_shop_trip`, `arm_sell_before_hp_retreat`. While that sell is running, HP retreat and heal do not take the tick. Death drops the pending sell and uses the respawn retreat. The 70% overweight sell while HP is still above the retreat gate is unchanged. MP retreat, idle return, and post-respawn retreat do not use this weight check.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — heal is decided only in decision, and waits out an attack

Consent: user asked to fix the heal filters that action was refusing, and to hold heal while the character is attacking.

Intent: action presses a heal key it was given. The MP 20% reserve no longer drops heal. Mother-tree MP, the heal slot switch, and a missing hotbar cell stay in decision. A living sticky target blocks heal until that target is dead or the lock is gone.

Shared: `emit_heal`, `maybe_heal_after_teleport`, `heal_press_slot`, `_can_heal_now`, `ActionExecutor._press_assigned_skill` / `_heal`.

Affected: hunting, retreat, and post-teleport heal. Retreat threshold and HP potions are unchanged. Other spells still keep their action-side mana checks.

Live result: unit tests. Needs a bot restart.

## 2026-10-12 — shops.yaml removed

Consent: user said the stall list can be deleted.

Intent: merchant places, dialog clicks, warehouse, and teleporters stay in `Engine/data/npc_behaviors.yaml`. `Engine/data/maps/shops.yaml` is gone, and nothing writes it back.

Shared: `tick_shop_trip` (a missing behavior id clears the trip), `seed_behaviors` (no longer reads a stall list). Shop List editor removed with the file.

Affected: arrow recover travel that used the stall list. Buy, sell, warehouse, and teleporter trips that have an NPC behavior are unchanged.

Live result: file deleted. Needs a bot restart.

## 2026-10-12 — NPC catalog leaves the maps folder

Consent: user asked to move the shopping catalog out of map-folder replaces and rename it, because it holds buy, sell, warehouse, and teleporter behaviors. The restored file stays as-is.

Intent: live load and every editor save `Engine/data/npc_behaviors.yaml`. A missing file is copied once from `Engine/data/maps/shopping_behaviors.yaml`, then from `UserData/shopping_behaviors.yaml`.

Shared: `shop.behaviors.BEHAVIORS_PATH`, Shopping Practice, NPC click-offset calibrator.

Affected: shop, sell, warehouse, and teleporter trips read the new file. Trip choice, clicks, and HP are unchanged.

Live result: the restored catalog (32260 bytes) was moved. Needs a bot restart so the new path is loaded.

## 2026-10-12 — weight gate uses the decoded percent

Consent: user confirmed 0x300 is the current weight percent and told us to use it for the weight gate. The plain pair at 0x3AC/0x3B0 stays on screen only.

Intent: sell and adena-only loot compare `inventory.weight_ratio`, filled from decoded WEIGHT (0x300) / 100. A noisy cur/max pair cannot open or block that gate.

Shared functions: `bag_weight_ratio`, `player_from_snapshot`, monitor `weightPct`.

Affected: sell trip (70% default), adena-only loot (30% default). Retreat, combat, and HP are unchanged.

Live result: needs a bot restart so the new monitor DLL is loaded.

## 2026-10-11 — every ground click repeats until the walk starts

Consent: user confirmed the scope. The post-kill arm is removed because it also caught the next attack click.

Intent: a ground hop repeats every 0.1s while the body is busy, and stops when the body stands or walks. Search, travel, retreat, unstick, and the walk up to a pile all go through `travel_click`.

Shared functions: `travel_click`, `Mouse.click(until_walk=True)`. `clickgap` only records again.

Unchanged: attack, gate, shop, talking-scroll row, death-screen restart, F4, login. One click when already standing or walking. Unreadable body stops after 1s.

Live result: unit tests updated. Needs a bot restart.

## 2026-10-11 — an attack is blocked only by the straight line

Consent: user confirmed the scope. The client walk polyline is not an attack gate.

Intent: a monster is attackable only when the straight line to it has no blocked tile between the two, and the monster is inside click range. Field and dungeon use that same rule.

Shared function: `can_engage_target`. `list_attackable` and sticky combat call it. A blocked line on the field falls through to the existing wall detour. Dungeon sticky release is unchanged.

Unchanged: travel, search, and loot still use `is_game_walk_clear`. The dungeon new-target path-length cap stays.

Live result: unit tests updated. In-game shot past a tree is pending.

## 2026-10-11 — retreat off the hunt map returns through world nav

Consent: user asked to fix it now. World nav owns the return to the last farm or dungeon.

Intent: after mother tree, teleport, or a scroll, do not walk the saved patrol cell on the map just landed on.

Shared functions: `finish_retreat`. A walk saved during `traveling` still resumes when the character is still on the hunt map. Shop resume and `post_respawn` are unchanged.

Affected modes: retreat finish, then world nav (`post_retreat`). Same-map patrol resume stays a local walk.

Live result: pending an in-game test.

## 2026-10-11 — local clicks around alive bodies

Consent: implement the discussed subplan. A* remains the guide. A 15×15 BFS replaces the next click when a nearby living body blocks the straight walk.

Intent: travel, search, and loot hops stop walking into players, NPCs, and monsters that are near the bot.

Shared functions: `collect_body_tiles`, `plan_avoidance_click`, `click_clear`, `apply_avoidance`. Called from `emit_travel_hop`, `emit_search_hop`, and the loot approach. Body tiles are refreshed once per `decide()`.

Unchanged: global A*, combat clicks, `try_movement_unstick`. A window with no safe click still falls through to that sweep.

Affected modes: travel, search, loot, and any mode that walks through those hops (retreat, shop walk, world-nav walk).

Live result: removed from the bot on 2026-10-12. The walk was failing hops with ``avoid_blocked``.

## 2026-10-12 — avoidance walk removed from the bot

Consent: remove the tested avoidance walk from the main project. Integrate a plan only after the experiment shows it performs.

Intent: travel, search, and loot click the guide waypoint again. A nearby living body no longer replaces that click, aborts the hop, or fails the hop.

Shared functions no longer called by the bot: `collect_body_tiles`, `plan_avoidance_click`, `click_clear`, `apply_avoidance`. `decide()` no longer refreshes body tiles. `avoidance.py` stays for the avoid-view tool.

Unchanged: global A*, combat clicks, `try_movement_unstick`, the 2-second reclick, the 1-tile hop arrival.

Affected modes: travel, search, loot, and any mode that walks through those hops.

Live result: code removed. In-game walk after restart is pending.
