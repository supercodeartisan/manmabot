# Decision change log

## 2026-10-19 — revive retreat keeps the dungeon routine clock

Intent: dying and reviving was the one retreat that still started the dungeon row clock at zero on the way back. A revive retreat now freezes that clock the same way as a world-tree retreat, and the hunt-floor return resumes the saved seconds.
Shared: `hold_dungeon_routine_clock`. Arrival and floor-route release already resume a held clock, including `post_respawn`. Field rows still start a new count when a revive return arrives.
Affects: dungeon routine duration after death. Time from the revive retreat until the hunt floor is not counted.
Consent: user (keep the timer in the revive case too).
Result: implemented. Not run in game.

## 2026-10-19 — log the cell and walk line on each travel click

Intent: the player cell at a travel click was not logged, so 77 of 147 arrival pairs could not be classed as a continued client walk. Each real travel click now records the player cell, the click it replaces, the new click, the distance, both client polylines, whether the old line is a prefix, and whether the body is moving. One later line says whether the body stopped within 0.7s.
Shared: `_emit_click` and `_follow_body_click`. The click tile, the arrival rule, and avoidance are unchanged. A held hop (`mid_act`) does not add a click line.
Affects: travel log volume on dungeon patrol, floor walks, and field hops. No change to where the character walks.
Consent: user (log P, W, C, dist, both client paths, prefix, moving, and click time before changing the click timing).
Result: implemented. Not run in game.

## 2026-10-19 — dungeon routine clock pauses for a retreat

Intent: a dungeon row is one routine. Leaving it for the world tree was zeroing that clock when the hunt floor was reached again, and the time away was either discarded or still counted. The clock now freezes when a retreat starts on a dungeon row, including a revive retreat, and resumes from the saved seconds when the character is back on that hunt floor. The first arrival on a new row still starts at zero.
Shared: `hold_dungeon_routine_clock`, `release_dungeon_routine_clock`, `begin_retreat`, `_finish_dungeon_floor_route`, and world-nav arrival. `_resume_stay_clocks` does not resume a held routine clock while the bot is running. Field rows, combat, movement, HP recovery, and the farm-area stay clock are unchanged.
Affects: the routine duration of a dungeon row across mother-tree, teleport, scroll, and revive retreats. Time away from the hunt floor is not counted. A return whose reason is `post_retreat`, `post_shop`, `after_shop`, `hunt_map`, or `unstick_return` also keeps the clock when it was not held.
Consent: user (dungeon routine timer is saved and pause/resume on world-tree retreat, return, and revive).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse deposit does not match the bag

Intent: an open deposit window was labeled retrieve when one displayed name differed from the bag (`펫 목걸이 [LV.5 용맹펫]` versus `펫 목걸이`), so the visit closed without storing. The open warehouse list is the deposit list. Rows absent from the keep list are stored. Adena is still skipped by name.
Shared: `writeStoreJson` mode and `execute_calibrated_sell` `read_sell_tab`. Merchant sell, the keep list, and the one-attempt warehouse stop stay as they are.
Affects: the warehouse keeper only. A list read while the retrieve tab is showing would store those rows too.
Consent: user (the open window is the deposit window; store rows that are not on the keep list; no bag comparison).
Result: implemented. The open deposit window read `open=1 mode=deposit` with 28 rows. Keep-list names stayed; the other rows, including 양초, are the deposit set. Adena was not on this list.

## 2026-10-19 — warehouse list reads the project DLL and registry

Intent: the warehouse visit loaded `Engine/analysis/NPC_conv/storewin.dll`, which looked upward for `registry\LC930_REGISTRY.txt` and never found it, so every snapshot returned `error: attach`. The visit now passes `Engine/analysis/lc930/registry/LC930_REGISTRY.txt` into `storewin_snapshot`. The window-slot offsets that file was missing are written there. `D:\dist\bin\storewin.dll` is no longer a fallback.
Shared: `storewin_reader.default_dll_path`, `default_registry_path`, and `storewin_load_reg`. Sell clicks, the keep list, and the one-attempt warehouse stop are unchanged.
Affects: the warehouse keeper list read only. Merchant sell still uses `shop_listen`.
Consent: user (yes; DLL and offsets stay in the project).
Result: implemented. With the warehouse window closed, the project DLL and project registry returned `open=0 mode=closed` and no attach error, the same result as the registry beside the build. The previous project DLL had returned `error: attach`. Restart the bot so it loads this DLL; the running process still has the old file mapped.

## 2026-10-19 — attack sight visits every cell a 1-tile fence crosses

Intent: the first attack click could land on a monster behind a one-cell fence because the sight line sampled with `round` and a diagonal step passed when only one shoulder was open. The shot now blocks when the segment touches a blocked cell, and a diagonal step needs both shoulders. A new target needs a memory nav tile. A sticky already within 2 tiles still uses the screen tile. After a dungeon fence release, that id stays out of the new-target list for 2 seconds.
Shared: `tiles_on_segment`, `line_of_sight_clear`, and `_los_step_open` in `dungeon.py`. `line_of_sight_clear` is only reached from `attack_line_clear`. Movement keeps `diagonal_open` (one open shoulder still walks). `list_attackable`, `list_attacked_me_targets`, and `nearest_attacks_me_force` drop a monster with no memory tile. `continue_or_start_combat` waits on a far sticky that has no memory tile, and `note_wall_fence_block` feeds `excluded_target_ids`.
Affects: new target choice, sticky attack continuation, and dungeon self-defense sight. Walking, loot clicks, shop, potions, retreat, and login are unchanged.
Consent: user (yes to this scope).
Result: implemented. Sight cases checked in a local script. Not run in game.

## 2026-10-19 — straight travel hops click onward while still walking

Intent: a world-nav hop stopped about half a second at every 5-tile click because the next tile was chosen only at arrival. On a straight client walk line the farther guide tile is clicked while the body is still moving, two tiles before that arrival.
Shared: `emit_travel_hop` and `_straight_extend_waypoint`. Arrival stays `_near_tile` / `travel_arrive_tiles` (1). The hop cap stays `travel_max_hop` (field 5, dungeon 3). Stuck time still resets only when the standing tile changes. An open door or the final goal stops the extension so door retarget and step completion stay as they are. Loot and search keep their own follow functions.
Affects: field world nav, farm entry, retreat, and dungeon patrol when the current guide does not turn. Corners still wait for arrival. Screen engage, loot, and mother-tree heals still interrupt the walk.
Consent: user (straight-line extend only, keep every existing workflow).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse keeper finishes after one attempt

Intent: after the warehouse keeper ran once, a failed storewin read (retrieve, closed, or no snapshot) closed the window and clicked the same NPC again. One `give_goods` attempt now ends that step whether the list read succeeded or not. Merchant sell still retries only on success.
Shared: `ActionController._shop_run`. `execute_calibrated_sell` and storewin are unchanged. A store behavior id (`give_goods` / `store_*`) sets `shop_ok` after the attempt returns, so `advance_sell_trip` runs the same path as a successful deposit. Sell, buy, and teleporter still require `ok`.
Affects: the warehouse stop after an overweight or pre-retreat sell. The following step is unchanged: retreat when this trip was sell-then-retreat, otherwise the post-shop return. A failed open still leaves the keeper.
Consent: user (finish the warehouse once the attempt is done, not according to the result).
Result: implemented. Not run in game.

## 2026-10-19 — give-up list lasts 4 seconds

Intent: a given-up monster stayed off the target list for 160 decision ticks, which is not a fixed time. The skip is now 4 seconds of wall clock.
Shared: `give_up_target` stores `time.time()`. `active_give_up_ids` drops rows older than `GIVE_UP_COOLDOWN_SECONDS` (4). `excluded_target_ids` and sticky rebind (`_living_same_species`) both use that set. Cursor-reject 4 seconds, the session blacklist, and loot abandon stay separate. The old `give_up_cooldown_ticks` setting is ignored.
Affects: farming, travel combat, dungeon patrol, and retreat's "enemy nearby, do not loot" check, whenever a target is given up (combat blocked, max engage, scarecrow level). After 4 seconds that id can be chosen again. A monster that is still inside the 4 seconds is still skipped, including one that is attacking.
Consent: user (the give-up cooldown must be 4 seconds, not 160 ticks).
Result: implemented. Not run in game.

## 2026-10-19 — an open door is crossed by the next path tile

Intent: a normal cursor on a tile beside an open door left the character on the near side of the fence. When this hop's guide passes through an open door, the click is the next guide tile after that door, one step past the usual hop cap when that step is what clears the doorway. If that tile is outside the click region or the line is closed, the hop does not substitute a side tile. A door cursor on the far tile tries the following guide tile. A closed door is still clicked once. A not-permitted door stays a wall.
Shared: `select_click_waypoint`, `plan_body_click`, and the travel click probe in `_search`. Combat, loot, HP, and login clicks stay as they are.
Affects: patrol, dungeon floor hops, and other ground hops whose guide crosses an open door.
Consent: user (yes; click the tile beyond the open door).
Result: implemented. Retarget check passed. Not run in game.

## 2026-10-19 — door cursor opens only a closed door

Intent: a door cursor on an open door was still clicked, which shut the door, while the nav map kept treating the tile as open. A door cursor now clicks only when the live door state is `close`, and that click is once so the repeat does not shut it again. `open` and `unknown` skip that point and try another tile in the hop ring. `not_permitted` is a wall for pathfinding even when the map tile is white.
Shared: `travel_click` ground hops (`_search`), the first `cursor_ok` check in `_click_until_walk`, and `TerrainMap.is_walkable` via the live door-wall set. Combat, loot, HP, and login clicks are unchanged.
Affects: travel, patrol, and loot-approach hops in dungeons and on the field. `print_state` must be rebuilt so entity rows carry `door`; until that DLL is loaded, a door cursor has no `close` state and is not clicked.
Consent: user (click the door only when it is close; pass through when open; treat not_permitted as a wall).
Result: implemented. Policy and wall-tile check passed. `Engine/analysis/entities/print_state.dll` rebuilt (newer than `print_state.new.dll`, so the loader uses it). Not run in game. Restart the bot so the new DLL loads.

## 2026-10-19 — a floor-route exit keeps the outside door

Intent: leaving during a dungeon floor walk flipped mapId while xy was still the inside cell. The next `hunt_map` plan measured that cell against the outside door and took a talking scroll plus a paid teleporter. The world-nav walk correction did not run, because this walk is the floor route.
Shared: `_drive_dungeon_floor_walk` calls the existing `_remember_stale_exit_landing` when the live map is no longer the walk step's map. The next world-nav arm still uses that outside landing once. The 50-tile door check is unchanged.
Affects: a floor-route walk that steps through a known exit, then `hunt_map` replans. Same-map floor walks, shop scrolls, HP retreat scrolls, and combat stay as they are.
Consent: user (yes; portable rebuild later).
Result: implemented. Check passed for map 1 `(32669,32802)` onto map 0: landing `(32478,32851)`, scroll off. A start at the goods shop `(32642,32949)` still scrolls. Not run in game. Portable not rebuilt.

## 2026-10-19 — Holy Weapon presses its hotbar key twice

Intent: one press of Holy Weapon only raised the round skill cursor, so the buff never landed and the character could not attack. Weapon buffs already use a second key tap (`power_up` / `CAST_DOUBLE`). Checked buffs with that role now take the same second tap. Shield and other single-press buffs stay one tap. Heal and teleport are unchanged.
Shared: `_press_catalog_buff` only. `_press_assigned_skill` is not used for this path.
Affects: checked Holy Weapon, Enchant Weapon, and the other weapon-buff names on that role, during hunt, travel, and dungeon buff ticks.
Consent: user (one press leaves the skill cursor; it needs the second press).
Result: implemented. Not run in game.

## 2026-10-19 — warehouse visit follows the store-after-sell box

Intent: the warehouse keeper ran whenever leftovers remained outside the keep list. Visit `give_goods` only when equipment `store_after_sell` is checked. The box defaults to checked. Unchecked ends the sell trip after the four merchants.
Shared: `advance_sell_trip`, `STORE_AFTER_SELL` via schedule → profile → `configure_decision`. Sell clicks, buy, HP, login, and combat stay as they are.
Affects: the warehouse stop after an overweight or pre-retreat sell.
Consent: user (visit only if the box is checked; checked by default).
Result: implemented. Not run in game.

## 2026-10-19 — checked buffs recast from the magic table

Intent: auto-use on the individual magic table chooses which lasting buffs are kept up. When the live buff is missing or has 10 seconds or less left, the matching hotbar key is pressed, one skill at a time, in priority order. MP still has to clear the reserve. Heal, teleport, attack magic, and the haste potion stay on their existing paths.
Shared: `due_buff`, `maybe_cast_buff`, `_maybe_support_spells` (call site unchanged). `apply_hp_actions`, `maybe_heal_after_teleport`, and `try_unstick_teleport` are unchanged. Armor and weapon buffs no longer fire from the old role order unless that skill is checked.
Affects: hunt, travel, and dungeon ticks that allow buffs. A checked skill that is not on the hotbar is skipped. Potions, login, and selling stay as they are.
Consent: user (yes).
Result: implemented. Resolver and due-buff check passed. Not run in game.

## 2026-10-19 — warehouse deposit reads storewin

Intent: `give_goods` was clicking with the merchant sell list. The warehouse window list comes from storewin. Only the deposit tab is used. Rows outside the keep list are stored with the same scroll flicks, cursor hold, and 0.2–0.5s click gap as the four merchants. Adena is skipped by name. A retrieve list is not clicked. The four merchants still use shop_listen, and the warehouse stay last.
Shared: `storewin_snapshot`, `storewin_reader`, `execute_calibrated_sell` when `action` is store. Buy, HP, login, and combat stay as they are.
Affects: the warehouse stop at the end of an overweight or pre-retreat sell. A scroll that rewrites the window vector was not checked in game; the reader walks the full slot vector (the sample was 29 rows).
Consent: user (yes).
Result: implemented. `storewin.dll` built and loaded; with the game closed the snapshot returns `mode=closed`. Not run in game.

## 2026-10-19 — sell item clicks wait 0.2–0.5s; scroll leaves the cursor

Intent: item-row clicks used a fixed 0.5s before and after the quantity. Each sell-row click now waits a random 0.2–0.5s, then the quantity is typed with no second wait. The sell-list wheel no longer moves the cursor to the scroll point; it stays on the last item clicked. Buy still moves to its scroll point.
Shared: `execute_calibrated_sell`, `_scroll_list(move=False)` on the sell path only. Confirm, buy, keep list, and the 5/6/7 flick size stay as they are.
Affects: overweight sell, pre-retreat sell, and warehouse deposit (same sell function).
Consent: user (0.2–0.5s between item clicks; cursor stays on the last item while scrolling).
Result: implemented. Not run in game.

## 2026-10-19 — sell list flicks 5, 6, or 7 rows

Intent: after the first screen, the sell dialog advanced one row at a time and clicked one item. Each later flick now rolls 5, 6, or 7 rows, then clicks the rows that came into view. A row already clicked is left alone when it is still on screen. The flick shortens at the bottom of the list so the click stays on the right row.
Shared: `sell_scroll_clicks`, `execute_calibrated_sell`. Warehouse deposit uses that function, so it flicks the same way. Keep list, Adena skip, the four-NPC shuffle, buy, HP, login, and combat stay as they are.
Affects: overweight sell and the pre-retreat sell, and warehouse deposit.
Consent: user (scroll 5, 6, or 7 rows, chosen at random).
Result: implemented. Plan check passed for chunks 5, 6, and 7, including a short list and keep-list gaps. Not run in game.

## 2026-10-19 — shuffle the four sell NPCs; one sell dialog selects every row

Intent: the four merchants were always visited in a fixed order, and each sell confirm closed the window after one scroll page. Visit those four in a random order. In one open Sell tab, scroll through every row outside the keep list, then confirm once. The warehouse keeper stays after the four, and only when the bag still holds something outside the keep list.
Shared: `shop_trip._shuffled_sell_ids` (used by `_begin_sell_queue` and `arm_sell_before_hp_retreat`). `execute_calibrated_sell` and `sell_scroll_clicks`. `give_goods` is still appended in `advance_sell_trip`. The keep-list filter, Adena skip, buy path, HP, login, and combat stay as they are. Warehouse deposit uses the same sell function, so it also selects every row before one confirm.
Affects: overweight sell trips and the pre-retreat sell. A scroll that clears already selected rows would drop those rows; this path does not reopen the shop to finish them. Rows past 80 are left for the next merchant or the warehouse.
Consent: user (yes).
Result: implemented. Scroll-click plan checked (first seven rows need no wheel; later rows scroll only the extra notches). Not run in game.

## 2026-10-19 — low HP heals in place, teleports once while hit

Intent: at the retreat HP, a character who was not being attacked still left for the world tree, and a character who was being attacked did not teleport before that. Heal and teleport could also be pressed below 20 MP on the unstick path and at the key itself.
Shared: `apply_hp_actions`. At or under the retreat row, a monster or summon whose attack targets the character teleports once when that skill can spend mana. The same drop does not teleport again until HP rises above the retreat row; the world tree, talking scroll, then teleport ladder runs instead. With nobody attacking, and heal able to spend mana, the combat lock is released and heal stays in place, including while the heal key is cooling. Dungeon and field hunting share this. Heal and every teleport refuse known MP below 20 at the decision and at the key press. Unstick keeps its percent reserve on top of that floor. The mother-tree mana floor stays. Potions, the 95% safe-zone fill, world-tree 40/80 recharge, and the fallback ladder stay as they are.
Affects: field and dungeon HP recovery at the retreat percent. Stuck escape will not teleport below 20 MP.
Consent: user (yes, keep every other behavior).
Result: implemented. Not run in game.

## 2026-10-19 — a stuck gate click steps aside once

Intent: a dungeon door click that did not move the character still waited 5 seconds twice on the same tile. Bodies on the entrance were never sidestepped during that wait.
Shared: `run_gate_click` returns `gate stuck pose unchanged` when mapId and the tile are both unchanged for the full 5 second land wait, and does not take the second ring from that tile. A moved tile or a flipped mapId still finishes that wait and may take the second ring. World nav and the dungeon floor route then emit one existing body-avoid hop (`emit_gate_sidestep` / `plan_body_click`, one tile) and the same gate click once more. A second stuck click fails the transition as before. The first cut was 1 second; the user set it to 5 seconds before any game run.
Affects: world-nav map transitions and dungeon floor gate clicks. Shop, HP retreat, talking scroll, NPC teleporter, and combat engage stay as they are.
Consent: user (yes).
Result: implemented at 5 seconds. Gate-watch check passed (unchanged tile is stuck at 5s; at 1s it still waits; a moved tile and a flipped mapId keep waiting). Not run in game.

## 2026-10-19 — near a dungeon door, world nav walks and clicks

Intent: a hunt that slipped out next to the dungeon door still took a talking scroll to a town hub when the click point was more than 10 tiles away. The 50-tile door check already dropped the NPC teleporter.
Shared: `WorldNavPlanner.plan`. When `near_goal_ground_enter` is true (50 tiles, the same check that drops the NPC teleporter), talking-scroll edges are omitted for that plan. The walk to the `ground_enter` and the click stay. A separate 10-tile or 15-tile scroll radius was tried and removed; the user kept 50. Farther starts, same-map plans, shop scrolls, HP retreat scrolls, and the in-dungeon floor route are unchanged.
Affects: world-nav returns that begin within 50 tiles of the goal map's ground door. A blocked walk still fails that plan instead of scrolling.
Consent: user (yes; 50 tiles, no separate 10 or 15).
Result: 50-tile check restored. Planner check passed (30 tiles: walk+click, scroll and NPC teleporter off; 80 tiles: both on). Not run in game.

## 2026-10-19 — exit replan starts at the outside door

Intent: leaving a dungeon flipped mapId while xy was still the inside cell, so the 50-tile door check measured about 200 tiles and took a talking scroll plus a paid teleporter.
Shared: a world-nav walk that leaves its map (`left map during walk` / `walk on wrong map`). When the live xy is within 5 tiles of that exit's inside cell, the next plan starts at the exit's outside landing, once. The existing 50-tile check then drops the talking scroll and the NPC teleporter. A start that is not on that inside cell is unchanged.
Affects: the replan after a world-nav walk steps through a known exit. Same-map walks, shop scrolls, HP retreat scrolls, and in-dungeon floor clicks stay as they are.
Consent: user (yes).
Result: implemented. Check passed for the 12:08 pose `(32811,32723)` leaving map 7: landing `(32728,32928)`, scroll off. `(33055,32342)` keeps the scroll. Not run in game.

## 2026-10-19 — safe-zone retreat heals and drinks until hunt resume

Intent: with the world tree unavailable, heal and potions stopped at the Recovery-tab percents while the character still waited until 95% HP to leave the safe zone.
Shared: `apply_inplace_hp_support` and the HP-potion side intent. On an HP retreat that is not a mother-tree trip, both continue until `HP_ALMOST_FULL_RATIO` (95%). Heal still requires enough MP to cast. A heal cast on that tick skips the potion. Hunting keeps the tab percents. Mother-tree recharge keeps its 40% / 80% band.
Affects: the wait after an HP retreat to a safe zone or teleport landing. MP retreats and return-to-town retreats are unchanged.
Consent: user (yes).
Result: implemented. Not run in game.

## 2026-10-19 — cursor reject skips that monster for 4 seconds

Intent: a clipped monster failed the attack cursor, the sticky lock kept aiming at it, then the id sat on the 160-tick give-up list. After the body walked fully on screen the character still ignored it.
Shared: `note_cursor_verify_fail` for monsters. Five rejected attack cursors in a row on the same id clear the sticky lock and record that id in `cursor_reject_until` for 4 seconds. An accepted cursor clears that streak. `excluded_target_ids` hides the id from the next attack choice, including a monster that has attacked me. Item cursor misses, dungeon wall release, and the 160-tick give-up for abandon / max engage / combat blocked stay as they are.
Affects: farming, travel combat, and dungeon patrol whenever an attack click is rejected. A monster released this way can be chosen again after 4 seconds. Other monsters can be chosen during those 4 seconds.
Consent: user (yes; 4 seconds instead of 160 ticks; exclude only after 5 cursor rejects in a row).
Result: implemented. Not run in game.

## 2026-10-19 — pause freezes the routine and hunt-area clocks

Intent: both stay clocks were wall time, so a pause still burned the row and the hunt area. The countdown kept falling, and a long pause advanced the row on resume.
Shared: `RoutineCursor` elapsed time and `farm_time` sampling. Pause, auto-pause, a minimized window, a missing game window, and a paralyzed cursor commit the open segment and hold it. Resume continues from those seconds. The short wait for a live position at start still counts. Stop still drops both clocks, and the next start is the first row at zero. Arrival reset, return trips that keep the row clock, the Moving label, login, combat, and HP stay as they are.
Affects: the routine-row countdown and the hunt-area stay, on screen and in the expiry check.
Consent: user (yes, freeze both clocks on pause and continue on resume).
Result: implemented. Not run in game.

## 2026-10-19 — off a dungeon floor, world nav starts again

Intent: a dungeon hunt resumed on the mainland (world tree) kept the old floor patrol and fought there. The hunt-map check treated every mainland tile as the dungeon return town, because that town is the Giran teleporter row and its geography is the whole mainland pack.
Shared: `_maybe_scroll_to_hunt_map` no longer returns early for that town. Off the scheduled floor, and not on another floor of the same complex, it still calls `begin_world_nav` with reason `hunt_map`. `on_dungeon_return_town` is removed. `finish_retreat` and `begin_world_nav` stay as they are.
Affects: travel and farming while a dungeon row is active and the live pack is not that dungeon. A pause/resume at the world tree, and any other mainland tile, arms world nav back to the dungeon. Another floor of the same complex still uses the floor route. Shop trips, scroll-arrival waits, and an already armed world nav stay blocked. Field hunts are unchanged.
Consent: user (ok, remove the return-town skip; do not add a separate resume path).
Result: implemented. Not run in game.

## 2026-10-18 — one stair goal per floor, and start inside the dungeon

Intent: dungeon floor walks were a new travel every 3 tiles, so the character stopped at each one. A start already on the scheduled floor (or another floor of that same complex) still planned world nav back to the entrance and scrolled to town.
Shared: `steps_from_segments` now emits one WALK, the stair cell, then the existing gate step. `emit_travel_hop` still cuts that walk into 3-tile clicks and sends the next click when a hop arrives. `arm_world_nav` reads the live MapSubsystem map before planning. The scheduled floor marks arrival and loads that floor's patrol. Another listed floor of the same complex sets the hunt id and returns to farming so the floor route starts there. A field, another dungeon, or an entrance-floor row still plans world nav. `begin_travel`, the gate executor, avoidance, and `DUNGEON_MAX_HOP_TILES` stay as they are.
Affects: every deeper-floor dungeon row at Start and while climbing. Entrance-floor rows and field hunts keep the previous arm. Patrol click length is unchanged.
Consent: user (ok, after the log analysis of the 3-tile stops and the Gludio F3 restart).
Result: implemented. Floor calculator checks passed (one walk per floor, F1 goal unchanged). Not run in game.

## 2026-10-18 — dungeon floors above the entrance use a calculated route

Intent: a hunt scheduled on a deeper dungeon floor still enters through the existing world-nav gate, then walks logical cells to that floor. The cells come from the shared floor calculator. Travel, avoidance, combat, and the gate click stay on the current executors.
Shared: `goal_for_entry` stops world nav on the complex entrance when the row is a deeper floor. `_on_world_nav_arrived` and the already-there arm do not load that floor's terrain or start its clock until the live map is the scheduled floor. `_maybe_scroll_to_hunt_map` does not re-arm world nav while the live pack is a listed floor of that same complex. `finish_retreat` resumes the floor route in that case and still world-navs from anywhere else. `_step_dungeon_off_floor` idles only for an entrance-floor hunt; a deeper floor calls `begin_travel` for each logical cell and `ActionType.GATE` for a `floor` link. `apply_gate_result` records that gate outcome with the existing land check. Travel engage during the walk is the same `farm_loot_or_combat` patrol travel already uses.
Affects: dungeon rows whose floor is deeper than the ground entrance (Gludio F2 and below). An entrance-floor row (Gludio F1) keeps the previous world-nav goal, gate, terrain load, and patrol. Field hunts, login, HP, and unstick are unchanged. `patrol.yaml` is not written.
Consent: user (add in-dungeon floor travel; use only the route coordinates; keep existing movement, avoidance, and attack).
Result: implemented. Checked with the floor calculator (F1 goal unchanged, F2/F3 step order, family mismatch, failed gate does not advance). Not run in game.

## 2026-10-18 — finished world nav does not keep the first hunt area

Intent: after a talking-scroll walk into the second hunt area, the session ended but `travel_purpose` stayed `world_nav`. The stay clock then watched the first checked area, so the second area's minute froze and the character never left for the third.
Shared: `_on_world_nav_arrived`, `_drop_world_nav_session`, and `clear_world_nav_run` clear that purpose. `trip_destination_farm` follows a world-nav trip only while the session exists; afterward the clock uses `farm_area_index`. The area-list "Moving" flag does the same. Walk target, combat, and HP stay as they are.
Affects: the hunt-area countdown after a world-nav arrival on Talking Island and the mainland, and the move to the next checked area when that minute ends.
Consent: user (yes, clear the purpose so the timer keeps the current area).
Result: implemented. Not run in game. A `nav` line `world nav purpose cleared` is written when the leftover purpose is dropped.

## 2026-10-18 — checked user areas stay on the hunt list

Intent: a map reload was replacing the checked hunt areas with the shipped pack `farms.yaml`. Areas drawn only in the user file (mainland 구역 7, 구역 8) stayed checked in the dialog but were missing from the running hunt list and its timer.
Shared: `ensure_navigation_for_pack_id`, after `configure_navigation_for_map`. When the live pack is the active battle row, the checked overlay rects are loaded again. A break row, a dungeon, or a different map does not get those rects. The tour is cleared only when that name list changes. Stay clock, walk target, combat, and HP stay as they are.
Affects: the hunt list and area timer on Talking Island and the mainland after Start and after a map sync. Unchecked shipped areas are not put back on the list.
Consent: user (yes, keep the checked user areas when the map reloads).
Result: implemented. Not run in game. A `nav` line `checked farms remounted` lists the names.

## 2026-10-18 — hunt-area stay no longer waits for the center

Intent: after the edge-start change, the countdown still began when the walk reached the area center. World-nav arrival loads the hunt row and was still calling `reset_farm_timer` for reasons such as `start` and `same_map_routine`. Until that arrival the clock also followed the loaded farm slot, not the rectangle the walk is entering.
Shared: `sample_farm_presence` times the trip's destination rectangle once the live map matches that pack. `apply_routine_entry_runtime` resets the stay on a new row, and on arrival only when that farm has not already started. The area-list clock highlights that destination while the trip is outside (`Moving`) and counts down after the tile is inside the rect. The walk target stays the center. `is_inside_active_farm` is unchanged for empty-area and yield checks.
Affects: the hunt-area countdown on the way into a Talking Island or mainland area, including the first walk after Start and a same-map routine change. Login, combat, and HP stay as they are.
Consent: user (timer should start as soon as the character enters the hunting area; reported that it still waited for the center).
Result: implemented. Not run in game. `farm stay start` logs the farm name and the nav tile of the first inside sample.

## 2026-10-18 — hunt-area stay starts at the rectangle edge

Intent: the stay clock was zeroed when world nav or the next-farm walk arrived at the area center, so the countdown began only after that point.
Shared: `reset_farm_timer` no longer runs on next-farm arrival or on `farm_area` world-nav arrival. It runs when the tour advances and when a new routine row loads its farms. `sample_farm_presence` still adds time only inside the active rectangle. The area timer shows the countdown once the character is inside, and `Moving` only while the trip is still outside that rectangle.
Affects: the hunt-area stay on Talking Island and the mainland, including the walk from the edge to the center. Login, combat, and HP stay as they are. The walk target is still the center.
Consent: user (timer should start as soon as the character enters the hunting area).
Result: implemented. Not run in game. A `nav` line `farm stay start` is written on the first inside sample of a fresh stay.

## 2026-10-18 — field same-map moves use world nav

Intent: a routine-row change or a hunt-area change on Talking Island or the mainland should use the same world-nav plan as a map change, including a talking scroll when that costs less. A failure of that trip must not skip the routine row.
Shared: `take_next_routine_if_due` for packs `talking_island` and `mainland` arms reason `same_map_routine`. `_try_farm_upkeep` on those packs arms reason `farm_area` toward `farm_area_index`. `goal_for_entry` reads that index for `farm_area`. Arrival keeps the index and starts the farm stay clock; the row clock is not reset. Other maps keep the old same-map rule. Cross-map failure still calls `_fail_skip`.
Affects: travel between hunt areas and between routine rows on Talking Island and the mainland. Dungeon floors, login, combat, and HP stay as they are.
Consent: user (yes; log those trips; only the two field maps).
Result: implemented. Not run in game. On failure the `nav` log and `[world_nav] STATE=FIELD_NAV_FALLBACK` record reason, error, and `via=walk` or `via=retry`. The row stays. Arm and arrival log `field world nav ...`.

## 2026-10-18 — return to the farm area that was left

Intent: after retreat or a shop trip, the walk back used the first checked farm. The character should return to the area index they left, including a Mother Tree or shop landing.
Shared: `goal_for_entry` and `apply_routine_entry_runtime` for reasons `post_retreat`, `post_shop`, `after_shop`, `hunt_map`, and `unstick_return`. The index is saved once in `begin_retreat`, `begin_shopping`, `tick_shop_trip`, and before a scroll/Mother Tree map reload. A new routine row still starts at the first checked area. Break rows still walk to the first checked rest area. Login, combat, and HP stay as they are.
Affects: the walk home from town, the world tree, and a shop, and the farm index after that arrival. A changed schedule row does not reuse the old index.
Consent: user (yes, that return scope).
Result: implemented. Not run in game.

## 2026-10-18 — confined episode log

Intent: a 13 s stay inside Chebyshev radius 3 does not say whether the character was against a wall or weaving. The next log needs the path from that window.
Shared: `note_confined_progress` still fires at 13 s / radius 3. It now keeps one episode and writes a `nav` line when the 13 s elapse (`kind=fire`) and when the character leaves the bubble (`kind=leave`). Combat and shopping still clear the clock without a line. Teleport, the talking scroll, and the radius stay as they are.
Affects: island and travel confined logging only. The line carries anchor, cell, elapsed, stepped distance, distinct cells, waypoint start/now/changes, verified click tile and its changes, moving 1/0/unread ticks, closed click lines, and body-avoidance hops.
Consent: user (add the episode summary, leave the gate).
Result: implemented. Not run in game.

## 2026-10-18 — travel hop does not arrive across a fence

Intent: a hop waypoint one tile away counted as arrived by Chebyshev distance alone. Standing on the near side of a fence completed the hop without crossing.
Shared: `_near_tile` in `travel.py`. Same tile is still arrived. Chebyshev 1 is arrived only when `can_step` opens that edge. No terrain map keeps the distance check. `travel_arrived`, farm arrive radius, patrol, loot, login, combat, and HP stay as they are.
Affects: every travel hop (world nav, shop, retreat). A character against a fence keeps that hop and clicks it again.
Consent: user (yes, this hop-complete check).
Result: implemented. Not run in game.

## 2026-10-18 — drop the 3-standstills-in-20s escape

Intent: three separate 5-second stops inside 20 seconds no longer skip the nearby clicks. A pocket is already the 7×7 / 13 s clock. One stop is already the nearby-click sweep.
Shared: `try_movement_unstick`. Low HP still skips the sweep and teleports or uses the talking scroll. The 13 s bubble, the radius-3 clicks, and the radius-2 escalate ring stay. Login, combat, and the HP gate stay as they are.
Affects: travel, search, and loot walks inside a farm. A third stop more than 3 tiles from the last one now clicks nearby tiles instead of leaving immediately.
Consent: user (remove the 20-second, 3-stop rule).
Result: implemented. Not run in game.

## 2026-10-18 — confined bubble radius 5 → 3

Intent: a 20×18 world window makes Chebyshev radius 5 an 11×11, more than half the view. Radius 3 is a 7×7. One field hop of 5 tiles leaves it, so local search no longer counts as confined. 13 seconds stays.
Shared: `note_confined_progress` / `try_confined_escape`. Nearby-click radius 3, the radius-2 escalate ring, the enter-farm radius-5 ring, hop cap 5, and the 13 s clock stay. Dungeon still disables this escape. Login, combat, and HP stay as they are.
Affects: island and travel confined escape. A character who moves 4 or more tiles from the anchor restarts the 13 s clock. Weaving inside the 7×7 for 13 s still teleports or uses the talking scroll.
Consent: user (keep 13 seconds, change 5 to 3).
Result: implemented. Not run in game.

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
