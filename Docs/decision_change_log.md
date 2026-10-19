# Decision change log

## 2026-10-19 — party brain seats only (no live decide change)

Intent: add four decision-adoption seats under `_06_party/brains` — leader, member (single party bot foundation), mage, shopkeeper.
Shared: none. `PartyMemberManager.decide`, follow, assist, HP, and login stay on the current path. MemberBrain can wrap the existing manager when constructed; session does not call it yet. Leader, mage, and shopkeeper return `ready=False` and no intent.
Affects: new package only.
Consent: user (compose these modules first).
Result: implemented. Not wired into the session.

## 2026-10-17 — settle/loot when leader stops; clearer party WS probe

Intent: with the leader idle, the member kept follow distance and skipped loot because settle required an exact cardinal tile. Hold as soon as distance ≤ stop; settle uses Arrive tolerance; clear a far travel sticky goal on stop; party-farm loot only while `leader_stopped` and near stop. Member WS test TCP-probes first and tells the user to Start the leader bot.
Shared: `follow_kind` (stopped), manager settle/loot, `_start_party_client`, party tab WS test.
Affects: party-member idle settle + loot; WS diagnose UX.
Consent: user ("leader stopped then loot… keeping distance… connection is failing").
Result: implemented.

## 2026-10-18 — shortest walk after a talking-scroll landing

Intent: after the scroll lands on the nearest hub, the walk to the hunt area was following the 32-tile cluster corridor. From the Silver Knight inn that corridor leaves by the south door, while the tile path through the north door is shorter.
Shared: the world-nav walk whose previous step is a talking scroll. That walk's hops use the tile path. Other walks keep the cluster corridor. The inn south wall seal stays. Login, combat, and HP stay as they are.
Affects: the walk from a talking-scroll landing to the hunt area. At the inn the route leaves through (666, 1248).
Consent: user (after landing on the nearest hub, take the shortest way to the hunting area).
Result: implemented. Not run in game.

## 2026-10-18 — reopen the Silver Knight inn north exit

Intent: the north opening (666, 1248) is white on nav.png. The load path was marking it unstandable, so a walk out of the inn could use only the south gap.
Shared: mainland terrain load only. (666, 1248) stays walkable. The south wall y=1256, x=656–669 except (660, 1256), stays unstandable. Login, combat, and HP stay as they are.
Affects: the walk out of the Silver Knight inn. The shorter route to the hunt area leaves through (666, 1248).
Consent: user (reopen that north tile, keep the south wall seal).
Result: implemented. Not run in game.

## 2026-10-18 — seal the Silver Knight inn wall

Intent: after a talking scroll into the inn, the first hop clicked the south wall. Those cells are white tiles with a north fence, and the load path was clearing that fence, so both the white-tile path and the click check treated the wall as an open door.
Shared: mainland terrain load only. The south edge y=1256, x=656–669 except (660, 1256), and the north hole (666, 1248), become unstandable. The earlier fence clear on (668, 1256) and (669, 1256) is removed. Scroll to the inn, login, combat, and HP stay as they are.
Affects: the walk out of the Silver Knight inn. The exit that remains is (660, 1256).
Consent: user (seal that wall, keep the south gap, close the north hole).
Result: implemented. Not run in game.

## 2026-10-18 — inn door, nearest unstick hub, world-nav return

Intent: the Silver Knight inn door is open in game and fenced on the walk map, so a walk from the inn hub never crosses it. A confined escape on the mainland always scrolls to the Giran teleporter. After that landing, the same map is treated as already on the hunt map, so the return walks with enter-farm and does not arm world nav.
Shared: mainland fence tiles (668, 1256) and (669, 1256) opened when the pack loads. `farm_return_scroll_spot` for mainland now picks the talking-scroll hub nearest the active farm; Talking Island stays on 마법서 상인, and a dungeon floor still uses the fixed mainland row. After that mainland escape scroll lands outside the farm, `begin_world_nav` reason `unstick_return` runs instead of enter-farm. That arrival does not reset the routine stay clock.
Affects: walks out of the Silver Knight inn, confined-escape scroll target on the mainland, and the return after that scroll. Login, combat, and HP selection stay as they are.
Consent: user (open the inn door on the walk map; mainland confined scroll to the hub nearest the current hunt area; after that scroll lands outside the farm, re-arm world nav even on the same map so the return can use a talking scroll).
Result: implemented. Not run in game.

## 2026-10-17 — talking-scroll row returns to the hunt button

Intent: the missed row click on the customer PC was a second mouse, ChangZhi Virtual Mouse. Disabling that device made the hunt button work. The row click goes back to `move_and_click`, the same packet as ground and attack clicks. The autologin `click` path used only for that row is removed.
Shared: `_use_talking_scroll` only. `MouseController.click`, hover, the wheel, and the login flow stay as they are.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (revert the scroll row to the hunt button packet; the extra mouse device was the cause).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — talking-scroll row closes the login driver after the click

Intent: the scroll row uses autologin's click. After a real login, that context is destroyed and `restore_desktop_input` drops the topmost flag and lifts stuck keys so the mouse works outside the game. The row click was reopening the hunt devices without that restore, and the desktop mouse was lost again.
Shared: `click_scroll_row` only. Before `shutdown` the login filter is set to none. Then `restore_desktop_input`, then `prepare_capture`, then the hunt filter is set to none. `MouseController.click` and the login flow stay as they are.
Affects: the moment after a talking-scroll row click. Other clicks stay as they are.
Consent: user (the post-login driver close was missing after the scroll row, and the outside-window mouse loss came back).
Result: implemented. Portable `mouse` module rebuilt.

## 2026-10-17 — talking-scroll row calls the autologin click

Intent: a hand click and autologin both select the talking-scroll row on the customer PC. The hunt button does not. Writing a homemade 20-byte stroke through the hunt device was rejected (`fallback hunt button` in v1.log). The row now calls `Engine/autologin/bot/win/interception.py` `click`, the same function autologin uses. Hunt closes its devices for that click and opens them again afterwards.
Shared: `click_scroll_row` and `_use_talking_scroll` only. `MouseController.click`, hover, the wheel, attack, ground, gate, shop, and the login flow stay on their current paths. If the autologin click cannot run, the row falls back to `move_and_click`.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (only the scroll row; keep every other mouse path unchanged; hand click and autologin already work).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — talking-scroll row uses the login button stroke

Intent: on one 1920x1080 laptop the cursor sits on the talking-scroll row and the wheel scrolls, and the hunt button still does not select the row. That row click now sends the same classic stroke login uses (button in `state`, absolute position), on the first mouse slot that accepts it. The devices already opened for hunt are reused. A second driver context is not opened.
Shared: `click_scroll_row` and `_use_talking_scroll` only. `MouseController.click`, hover moves, the wheel, attack, ground, gate, shop, and login stay on their current paths. If the login stroke cannot be written, the row falls back to `move_and_click`.
Affects: the talking-scroll list row. Other clicks stay as they are.
Consent: user (login stroke for the scroll row only; keep every other mouse path unchanged).
Result: implemented. Portable `mouse` and `controller` modules rebuilt.

## 2026-10-17 — button stroke carries the click pixel

Intent: the relative button stroke still did not select the talking-scroll row on the customer PC. The cursor sat on the row and the wheel scrolled. Login clicks already put the target pixel in an absolute button stroke, and that is the packet this PC accepts.
Shared: `_send_button`, `_click_in_place`, `MouseController.click`, `_click_until_walk`, `hold`. A button release with no pixel uses the current cursor so it does not jump to the origin. Wheel, scroll UV, and login stay as they are.
Affects: talking-scroll rows, ground hops, attack clicks, map gates, and shop clicks.
Consent: user (absolute pixel inside the button stroke, then rebuild `mouse.cp314-win_amd64.pyd`).
Result: implemented. Portable pyd rebuilt after this entry.

## 2026-10-17 — click at the cursor, not at screen origin

Intent: a talking-scroll row click moves the cursor onto the row, then the button packet was an absolute move to (0, 0). On the other laptop the list scrolled and the cursor sat on the row, and the character never left. Button presses now use a relative (0, 0) stroke, the same shape as the wheel.
Shared: `MouseController.click`, `_click_until_walk`, `hold`, `release`, and the button lift in `release_capture`. `move_to`, wheel count, scroll UV, and arrival wait stay as they are. Login clicks stay on `Engine/autologin/bot/win/interception.py`, which already sends the button with the target coordinate.
Affects: talking-scroll rows, ground hops, attack clicks, map gates, and shop clicks. Keys and the wheel are unchanged.
Consent: user (relative button packet in mouse.py for every MouseController click; leave the installed interception package and login path alone).
Result: implemented in `Engine/app/_05_action/mouse.py`. Portable `mouse.cp314-win_amd64.pyd` rebuilt for the customer folder. Not yet tried on the laptop where the row click missed.

## 2026-10-17 — hide the autologin console

Intent: the main program stays windowed, and the autologin child no longer opens a console that sits on screen until login finishes. Purple login, clicks, elevation, and the status file the UI already shows stay the same.
Shared: `AutoLoginService.run` launch only. `bot2` is still `python.exe` with `--no-self-elevate`. When this process is already admin, the child gets `CREATE_NO_WINDOW` and its stdout/stderr go to `UserData/autologin_runs/<id>/console.log`. When it is not admin, the UAC child is `pythonw.exe` with `SW_HIDE`. `bot2_run.log` is unchanged.
Affects: the window the operator sees during Start login. Login steps, shop, movement, combat, and HP are unchanged. The startup UAC prompt for the main program still appears.
Consent: user (hide the autologin console; keep autologin working fully).
Result: implemented. Not yet run against a live Purple login.

## 2026-10-17 — startup memory warm imports on the main thread

Intent: portable ZF.exe was crashing about 0.5s after the admin relaunch because the startup thread imported compiled modules while the main thread was still importing the UI. Elevation, WinNotify start, and the in-process memory attach stay the same call (`warm_memory_at_startup(wait_snapshot=False)` on the `signeddrv-start` thread).
Shared: `prepare_runtime`. The schedule window's later warm is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`, and login clicks stay as they are.
Affects: process start only. The driver and memory reader still start before the operator uses the window. The warm modules are initialized on the main thread first so the worker does not initialize them again.
Consent: user (stop the crash and keep the current startup, workflow, and features).
Result: portable `elevate` module rebuilt. `ZF.exe` stayed up with a window and no access violation.

## 2026-10-17 — member sends player status every 10s

Intent: the member bot connects to the leader address and sends the live player (hp, mp, position, map id, alive, level) every 10 seconds. Follow and combat stay as they are. The leader still farms solo and still sends only critical decisions.
Shared: none. New client start/stop sits next to the leader socket in the worker. The send runs after the world snapshot, before the member decision, and only while member logic is on.
Affects: member websocket traffic and a host field on the party member panel.
Consent: user (client sends current player status with a 10s heartbeat).
Result: implemented.

## 2026-10-17 — leader sends critical solo decisions

Intent: the leader bot keeps the solo farm. It does not run party follow. After a solo decision, teleport, return, talking scroll, gate, shop, and respawn are copied onto the party socket once per change. Attack, loot, heal, and walk ticks are not sent. Member follow is unchanged.
Shared: none. The hook is after `decision.decide` in the bot loop, and only when the role is leader.
Affects: leader websocket traffic. Solo actions stay the ones decide already chose.
Consent: user (verify sending the leader's critical decisions; leader farms solo; only the member uses party logic).
Result: implemented.

## 2026-10-17 — party role selector and leader socket

Intent: the Party tab has two roles, party member and party leader, on both sections. Leader shows this PC's LAN address and the socket port. When the bot runs as leader, the existing party WebSocket server listens on that port until the bot stops. A temporary client window monitors messages and both sides' status. Member follow, assist, loot, combat, retreat, HP, and login are unchanged. Selecting leader turns member follow off so this PC does not also chase a leader.
Shared: none of `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`. New path is `BotController._start_party_socket` / `_stop_party_socket` around the existing worker. The member gate reads `party_role` and skips member mode when it is leader.
Affects: party tab settings, and a listening socket while a leader bot is running.
Consent: user (party member / party leader select, show IP and port, start the websocket with the leader bot, temporary client UI).
Result: implemented.

## 2026-10-17 — smooth party follow via Reynolds leader-following + Arrive

Intent: travel follow was not smooth — random/exact travel tiles repathing every leader step caused jitter and reverse walks. Replace with Craig Reynolds leader following (GDC'99): formation slot behind the leader with a light lateral flank, Arrive tolerance (hold within 1 tile of the slot), and a sticky absolute goal (keep click target while the ideal drifts ≤2 tiles). HOLD keeps the sticky goal so the next chase reuses it.
Shared: `formation_slot_offset`, `sticky_goal_tile`, `ARRIVAL_TOLERANCE` / `STICKY_GOAL_SLACK`, `FollowField.pick_travel_offset` (formation), manager travel wiring + HOLD sticky keep (all `_06_party`). Assist, settle cardinals, WORLD_NAV, solo, HP, login unchanged.
Affects: party-member travel follow only.
Consent: user ("still not smoothly following, give me the best algorithm. web search… and use").
Result: implemented. Sources: Reynolds steering (leader following / Arrive), formation sticky goal / zLookAhead practice.

## 2026-10-17 — restore contested_mobs capture for party assist (89bd676)

Intent: etview showed the leader's AttackAction target, but the member never assisted. Live `capture_tick` had stopped loading/capturing `contested_mobs.dll` (and `attacks_me`), so `last_contested_mobs` stayed empty. Assist had been rewired to print_state `atk`/`tgt`, which often misses the same row etview sees. Restore the 89bd676 path: init combat readers, capture contested+attacks every tick, prefer contested rows for `leader_attack_rows`, keep print_state as fallback.
Shared: `PerceptionSensors._init_combat_readers` / `capture_tick`, `leader_attack_rows` (contested first). Policy assist gate and resolve-live-only stay as they are.
Affects: party-member assist target discovery (and `last_attacks_me` for strike assist). Solo contested filter still uses print_state. Movement, HP, login unchanged.
Consent: user ("etview shows target… never assist… check 89bd676… at that time it worked").
Result: implemented.

## 2026-10-17 — mage casts only after an attack (knife) cursor like elf

Intent: mage targeting pressed the spell key first and hunted for a `spell` cursor on a cross, so it often clicked empty ground. Elf finds `arrow`/`fist`/`sword` on the monster body ring and clicks. Mage now uses that same ring: hover until an attack cursor is on the body, press the spell key, then click that pixel only when the cursor is `spell`. Miss → reject / Esc, no grind on empty pixels. Elf `attack_click_search` is unchanged.
Shared: `find_attack_aim_point`, `mage_cast_at_point`, `MageCombatStrategy.attack` (mage only). `object_attack_screen_points` is reused read-only.
Affects: mage spell casts. Hunt attack mode ranged/melee for mage still uses elf/knight strategies from the prior change.
Consent: user (knife-first mage aim; do not change elf).
Result: implemented.

## 2026-10-17 — party assist from print_state; mage retarget; mage ranged = bow

Intent: (1) Party farm assist was not attacking the leader's monster. Assist read `last_contested_mobs`, but the live tick never fills that DLL snapshot — contested claims for solo already come from print_state `atk`/`tgt`. Assist now builds the leader's target from the same print_state Player AttackAction, with the DLL as a fallback only. Policy assists when that target is resolved inside the assist leash, even if the old `leader_farming` flag is late. Assist also runs with a party-guid proxy when the leader entity is off-screen. Soft give-up / blacklist ids are skipped so a failed cast can retarget. (2) Mage casts that miss the cursor used to Esc and re-aim the same sticky target without `mid_act`, so every tick re-pressed the skill and clicked the same area. Party ASSIST/DEFEND now set `mid_act` while the assist track_id is unchanged; after `CURSOR_VERIFY_FAIL_GIVE_UP` cursor rejects the blackboard give-up is honored and assist picks another monster. (3) Hunt Attack mode was stored in the UI but ignored by combat. Mage + `magic` keeps spell cast; mage + `ranged` uses the elf bow strategy; mage + `melee` uses knight clicks. Spell-range filters and mage MP-cast probes apply only when `uses_spell_aim()` is true.
Shared: `leader_attack_rows` / strike resolve (print_state), `pick_assist_target` (blackboard exclude), party policy assist gate, `attack(..., mid_act)`, `player_mode.ATTACK_MODE` / `uses_spell_aim`, `combat_strategy_for(attack_mode)`, combat_query/target_selector spell-range gates, profile `attack_mode`, task_runtime + ActionExecutor wiring. Solo farm, retreat, HP, and login stay as they are aside from the spell-range gate when attack mode is not magic.
Affects: party-member assist and farming; mage (and only mage) combat strategy and target range when Attack is Ranged/Melee/Magic.
Consent: user ("must retarget… farm as range with bow… check deeply assist… contradiction… check and fix").
Result: implemented. Print_state leader atk→monster resolves to `leader_attack`; policy returns ASSIST without `leader_farming`. Files compile. Full combat_strategy import was not run here (this Python has no numpy).

## 2026-10-17 — party member farming method: solo farm / party farm

Intent: the Party tab has a "Farming method" choice. Party farm (default) is the existing logic: the member only attacks what the leader attacks or strikes. Solo farm keeps the same follow and stop logic, but the member picks its own nearest target. It uses the solo `list_attackable` gates: species allow/deny, monsters claimed by another player, line of attack, mage range, and the give-up/blacklist set. The target must be within `assist_leash_tiles` of the leader and on screen. The member keeps its target while it is alive and in range, and fights it whether the leader is fighting or not. When the leader walks past the leash, follow wins. Solo farm loots its own drops (ownership gate on) within `follow_tiles` of the leader, including during fights. A pickup walk in progress is not cut by the stand/spot re-follow until the leash breaks.
Shared: `PartyMemberConfig.farm_mode`, `pick_solo_farm_target`, `PolicyInput.solo_farm`, `party_loot_ownership_filter` (solo → own drops), and the manager loot gate (all in `_06_party`). Profile `party_farm_mode`, settings bag, `task_runtime`, schedule export, and the `bot_controller` config build. Solo `_04_decision` is read only (`list_attackable`, `excluded_target_ids`, `is_avoided_for_state`). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login stay as they are.
Affects: party members in solo farm mode only. Party farm decisions and loot gates are unchanged. In solo farm, the Party loot random/role controls are disabled because they do not apply.
Consent: user ("implement solo farm / party farm selection … party mode is current logic").
Result: implemented. Checks pass. Config normalizes to party/solo. In solo, with the leader idle and a target in the leash, the result is ASSIST (or CLOSE_IN when out of range). Past the leash it is FOLLOW. Party mode with the same input still follows. The profile round trip works. The Qt tab compiles; it was not run here because PySide6 is missing from this Python.

## 2026-10-17 — party member travels on a random side of the leader

Intent: the member no longer trails behind a walking leader. While the leader walks, the member keeps one random tile around the leader as an offset that moves with it. The tile can be on any side and within `follow_tiles − 2` walk steps (2 at F=4). The member walks to that tile and holds on it. Each leader step moves the tile, so the member moves with the leader at once. A new random offset is picked each time the leader starts walking again, or when the tile is blocked, occupied, or has no path. The stopped stand is unchanged: random up, down, left, or right at S walk steps.
Shared: `FollowField.pick_travel_offset`, `travel_band`, `follow_kind(at_travel_spot)`, `PolicyInput.at_travel_spot`, `plan_follow_intent(stand_reason)` (all in `_06_party`). Solo code, combat, the HP path, login, and UI stay as they are.
Affects: party member travel follow. The walk-path click (`plan_field_follow`) is now only used when no spot is free around the leader. Combat assist, the combat leash, and world-nav stay as they are.
Consent: user ("member bot don't need to be behind of leader, move and stop around randomly").
Result: implemented. Checks pass. With F=4, offsets cover all 8 sides within 2 steps. A valid offset is kept, and a blocked one is re-rolled. The policy follows until the member is on the spot, then holds.

## 2026-10-17 — party member follow and stop use walk steps

Intent: the member's follow (`follow_tiles`) and stop (`stop_tiles`) bands count real walk steps to the leader, not Chebyshev distance. A wall or body between them no longer reads as "close". One bounded reverse BFS from the leader tile (`follow_field.py`) gives the member's steps and the path down to the leader. Travel clicks pick a hop on that path with `select_click_waypoint`, with no A*. The field is cached by leader tile, window, terrain, and nearby bodies. Window radius is `2×F+2` (min 8, max 24). Measured cost is about 1 ms at F=4 and about 5.6 ms at the cap. A cache hit costs under 1 µs.
Shared: `build_follow_field`, `FollowFieldCache`, `plan_field_follow`, `pick_settle_stand` (field filter), `PolicyInput.leader_walk_dist` (all in `_06_party`). The pathfinding code is read only (`select_click_waypoint`, `waypoint_to_content`, `TerrainMap.can_step`). Solo `_04_decision`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login, and UI stay as they are.
Affects: party member travel and settle only. The combat leash, assist, close-in, world-nav route choice, and the loot gate keep Chebyshev. A member that is unreachable inside the window counts as past the window, and its click falls back to the old A* follow. A settle stand must be within S walk steps. While a click is still more than 1 tile away, the member does not click again until the goal moves.
Consent: user ("implement walkable distance following only for this member bot").
Result: implemented. Checks pass. Through a wall the Chebyshev distance is 4 but the walk is 12 steps, and the member follows around the wall end. Tiles behind a body in a 1-wide corridor are unreachable. On open ground, walk steps equal Chebyshev distance.

## 2026-10-17 — party member keeps the follow distance and settles beside the leader

Intent: while the leader walks, the member stays within `follow_tiles` (UI F). It starts chasing 2 tiles before F (`TRAVEL_LEAD_TILES`) and keeps walking while it is farther than `stop_tiles`. Before this change it waited until it was already past F, so the 1–2 s reaction lag let the gap grow past F. When the leader stops (0.7 s settle, unchanged), the member picks one random tile up, down, left, or right of the leader at distance `stop_tiles` (UI S). It keeps that tile until the leader moves again. The old behavior stood on whichever tile was nearest the member, which meant behind the leader.
Shared: `follow_kind`, `choose_settle_stand`, `pick_settle_stand`, `plan_follow_intent`, `PartyMemberManager._update_settle_stand` (all inside `_06_party`). Solo `_04_decision`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login, UI, and party sensors stay as they are.
Affects: party member follow only. Combat assist, the combat leash, join-map, world-nav follow, and loot gates are unchanged. If a stand is occupied, the member picks another one. If a stand has no path, it is blocked until the leader moves. If no cardinal tile is walkable, the member falls back to the `stop_tiles` radius.
Consent: user ("implement", after the scope was limited to `_06_party`).
Result: implemented. Pure checks pass: with F=4 and S=1, travel chases at a distance of 2 or more. The settle stand is always one of the four cardinal tiles, and it stays locked unless occupied.

## 2026-10-17 — avoidance uses the memory monster class

Intent: movement avoidance treats a print_state `Monster` or `SummonedMonster` as a body even when the species filter typed it OTHER. Attack, loot, and target selection keep the species filter.
Shared: `collect_body_tiles`. Handoff `classification` is stored as `memory_class`. `object_type_from_classifiers` stays as it is.
Affects: travel, search, and loot hops, and the click-line check. Players and NPCs still use object type. The blacklist still only blocks attacks.
Consent: user (memory class for avoidance only; keep species identification everywhere else).
Result: implemented. An uncatalogued memory monster stays OTHER and is still an avoid tile. A resolved species stays MONSTER.

## 2026-10-17 — page-cache readers installed in this tree

Intent: bring the memory-project readers into this tree and rebuild the DLLs the bot loads. Decision, movement, combat, and HP action code stay as they are.
Shared readers: `pgcache.h`, `print_state.c`, `realtime_monitor_full.c`, `inventory_listen.c`, `hotbar_listen.c`, `nametable.c`, `shop_listen.c`, `lcore.h`, `buff_listen.c`, `uidialog_listen.c`.
Consent: user (apply the memory-project read changes together and rebuild).
Result: sources match that tree. DLLs rebuilt and loaded. Live snapshots returned print_state 13 entities at player (33457, 32782) HP 119/157, monitor the same pose with mapId 4, inventory 43 named items, hotbar 24 slots, buff 2, uidialog 5 windows. Shop subsystem was found; buy and sell lists were empty while the shop window was closed.

## 2026-10-17 — one-snapshot page cache on the live readers

Intent: cut driver calls inside one snapshot. The same bytes are still read every tick. Owner/target, fast PRES, bag counts, buff remain, UI open state, and map id stay live. The nested PRES child walk is gone; a slot vft or that object's +0x10 still resolves PRES.
Shared readers: `pgcache.h` under `rm`/`readMem` in `print_state.c`, `realtime_monitor_full.c`, `inventory_listen.c`, `hotbar_listen.c`, `nametable.c`, `shop_listen.c`, `lcore.h` (buff and uidialog). Subsystem vft reuse on the actor grid, bag, hotbar, and shop. `$id` strings are remembered after the first resolve. Inventory heap name scan and `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: how many IOCTLs a tick spends. Decision fields, tick order, and poll clocks are unchanged. A PRES that existed only behind a child pointer no longer gets coordinates.
Consent: user (minimize IOCTL without changing decision performance; the per-call leftovers in the monitor, bag, and buffs are in scope).
Result: implemented in the readers above.

## 2026-10-16 — mage cast clicks the center of the spell range

Intent: after the mage spell key, probe a screen cross through the monster and click the midpoint of the pixels whose cursor is `spell`. A locked fight reuses that center while it still reads `spell`. `spell_disable` and `spell_out_range` stay rejected.
Shared: `mage_spell_cross_points`, `spell_range_center`, `mage_cast_click_search`, `MageCombatStrategy.attack`. The cross is centered on the same 0.2-screen-up body point as melee, with arms at 0.40 and 1.10 screen tiles. `object_attack_screen_points`, knight/elf/royal clicks, loot, travel, retreat, and HP stay as they are.
Affects: mage attack casts. One cast hovers the cross (about 0.2 s) before the click, inside the 0.50 s cast gap. A `spell` pixel past a non-spell gap is left out, so a neighbor on an outer arm does not pull the center. A cast with no `spell` pixel still cancels with Esc. A monster that walks off the locked center is measured again.
Consent: user (go, after the mage spell-center proposal).
Result: implemented.

## 2026-10-16 — paused schedule update reaches the running logic

Intent: Alt+A pause, then "update schedule", copies that schedule onto the live profile and the worker re-applies the Start configure path before the next decision tick. Resume uses the new settings. A running bot still does not apply. Map, routine, or farm-list changes restart the routine cursor and the in-farm timer. Stay-time and HP edits keep that timer.
Shared: `publish_paused_task`, `install_profile_runtime`, `restart_paused_routine`, `_consume_paused_settings`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `apply_inplace_hp_support`, and login clicks stay as they are. Account, character class, the memory monitor, and the perception capture still change only on stop/start.
Affects: hunt, travel goal, return, loot, shop restock, HP potion/heal/escape thresholds, teleport, farm rotation, and routine after a paused update. The character stays where they are. A route change makes the next resume walk the new goal.
Consent: user (apply paused schedule updates to the running logic; keep account, class, and capture on stop/start).
Result: implemented. Qt and classic "update current" both publish while paused.

## 2026-10-16 — dungeon cursor lock requires a clear line

Intent: a dungeon world-nav attack cursor locks the monster under the probe only when the straight line is clear. A line that blocks later releases that lock with the existing dungeon wall skip, without a give-up cooldown.
Shared: `monster_under_travel_cursor`, `cursor_engage_target`, `continue_or_start_combat` dungeon-wall skip. The nearest monster stays the cursor target; a blocked line does not substitute another monster within 3 tiles. `can_engage_target` on the normal list, attacks_me, path cap, field wall detour, and travel clicks that need a normal cursor stay as they are.
Affects: dungeon hunting during a world-nav walk. A fenced sprite no longer keeps the attack clicks. A clear-line cursor lock still fights ahead of ground loot. One-tick line flicker can drop the lock and allow one ground hop before screen combat reselects.
Consent: user (apply the proposed gate; check it does not disturb other dungeon attack paths).
Result: implemented.

## 2026-10-16 — stay on the goal dungeon floor

Intent: when the hunt goal is a dungeon floor, the planner does not expand a transition whose destination map differs once the search node is already on that floor. Entering the floor, and ladders used while the node is still short of the goal floor, stay.
Shared: `WorldNavPlanner.plan` transition expansion. `Transition.from_floor` / `to_floor` copy the cell `floor`. Gate circle, NPC teleporter settle, scroll, combat, retreat, HP, and login stay as they are.
Affects: world-nav plans whose goal map is a dungeon floor. A same-floor point goal no longer detours through the next floor via a ladder beside the entrance. A deeper-floor goal still climbs. A retreat whose goal is town can still leave. If the entrance and the patrol are not connected by a walk on that floor, the plan fails.
Consent: user (dungeon movement only; cover the same detour in other dungeons; do not collide with other logic).
Result: implemented.

## 2026-10-16 — dungeon hunt walk locks the monster under the attack cursor

Intent: a Talking Island dungeon world-nav hop whose probe shows an attack cursor stops the ground-click ring and fights that on-screen monster until the existing sticky release. A blocked terrain line does not drop this lock.
Shared: `ActionExecutor._search` / `_arm_dungeon_cursor_engage` (reason `world nav walk` and dungeon only). `monster_under_travel_cursor`, `farm_loot_or_combat` cursor branch, `continue_or_start_combat` dungeon-wall skip. `can_engage_target` still filters the candidate list. `travel_click` still requires a normal cursor. Shop, return, field walks, `arrow_lack`, contested, blacklist, and give-up cooldown do not arm the lock.
Affects: dungeon hunting while a world-nav walk is in progress. Ground loot waits until that kill ends. Field wall detour, patrol, and shop travel keep sliding off an attack cursor.
Consent: user (analyze conflicts, then implement this handoff).
Result: implemented.

## 2026-10-15 — attacks_me reads the entity cell, not a (0,0) placeholder

Intent: an attacker row carries the same world cell print_state reads from the entity. A failed read omits `world` instead of publishing cell (0, 0).
Shared: `attacks_me.c` `readEntCell` / `pushActor` / `emitActorTail`. Offsets `off_ent_cell_x` / `off_ent_cell_y` come from `settings_print_state.json`. `sync_attacks_me_force_targets` only gained a cell log; match, sticky, LOS, and ring click are unchanged.
Affects: which monster `attacked_me` latches onto. A row with no cell is skipped by the existing missing-world path.
Consent: user (fix the cell read in attacks_me only; do not filter the symptom in combat).
Result: implemented. `attacks_me.dll` rebuilt after this source.

## 2026-10-15 — memory reads follow dist batching, this project's clocks

Intent: cut repeated driver reads of the same bytes. Fixed anchors, one-block field reads, vft subsystem cache, action-block fingerprints, and pointer chunks. Tick timing, HP, pose, map id, and print_state fast PRES stay on every call. attacks_me and contested structure sweeps use the print_state roster clock (100ms, or a move over 8 tiles) and return the previous JSON in between.
Shared readers: `realtime_monitor_full.c`, `lcore.h`, `lbuff.h`, `attacks_me.c`, `contested_mobs.c`, `print_state.c` `findPres`, `uidialog_listen.c`. Decision, movement, combat, and HP action code stay as they are.
Affects: live memory reads. Attack and contested lists can be up to 100ms old. The monitor DLL does not start the 64KB heap scan, so its `entities` array is empty; clicks still come from print_state. Buffs come from `BuffListBase`.
Consent: user (apply only the call reductions; keep this project's timing; reconsider locking the entity sweep to the decision tick).
Result: implemented. Canon: `Docs/architecture/MEMORY_READ_CANON.md`. DLLs rebuilt.

## 2026-10-15 — ignore named adena at or below a UI qty

Intent: when the schedule loot checkbox is on, named adena with loot_qty <= the entered value is not approached. Unnamed piles are not subject to this gate. Adena already within pickup range is still F4'd, including side pickup. Default is off, and the spin shows 10.
Shared: `small_adena_ignored`, `list_lootable` (main path only), loot sticky when out of range, pending re-approach.
Affects: loot approach in hunt, retreat, and farm entry. Feet F4, combat aim, retreat movement, login, and HP stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 2, plus the later feet-F4 and unnamed-name amendments.
Result: implemented. `Others/tests/test_ground_loot.py`.

## 2026-10-15 — main loot contrib floor is 50

Intent: main-intent MINE loot requires contrib above 50. 50 is rejected, 51 is allowed. FREE and side F4 are unchanged.
Shared: `LOOT_CONTRIB_MIN`, `loot_ownership_allowed`.
Affects: hunt main-intent approach and pickup. Combat, retreat, login, and HP stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 3.
Result: implemented. `Others/tests/test_ground_loot.py`.

## 2026-10-15 — attack aim starts 0.2 tiles screen-up

Intent: the attack cursor's first point and the 0.1-tile ring center move from the iscr feet point to 0.2 tiles screen-up. Ring radius, cursor pass score, and give-up rules stay as they are.
Shared: `content_screen_up`, `object_attack_screen_points`, `ATTACK_AIM_SCREEN_UP_TILES`.
Affects: knight, elf, and mage attack aim. Loot clicks and movement clicks stay as they are.
Consent: user. Procedure: `D:\md\pending_specs.md` section 1.
Result: implemented. `Others/tests/test_attack_cursor_search.py`.

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
