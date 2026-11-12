# Decision change log

<<<<<<< HEAD
## 2026-11-11 — a missed party-list cast clears the spell cursor

Intent: A party-list buff or heal presses the skill key once, then clicks the row only after the spell cursor is up. When that wait misses, or a later walk still sees the circle, Esc runs first. If the circle remains, a right-click lands inside the game view. The walk click waits until the cursor is no longer a spell circle. The skill key is not pressed again.
Shared: `cancel_spell_aim`. Party-list heal and buff call it when the aim wait misses. The travel hop calls it and skips the ground click while the circle remains. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party mage follow after a buff or heal, and any walk that already cancelled a leftover spell circle, including a solo mage cast miss.
Consent: user ("yes" after the stuck spell cursor).
Result: `Engine/app/_05_action/tests/test_spell_aim_hold.py`. Not run in game.

## 2026-11-11 — a missing party heal stays on

Intent: The party mage screen shows 힐 checked when `mage_0` was never saved. The caster now uses that same rule. `mage_0: false` is the only save that turns 힐 off. Opening the party support table writes `mage_0: true` when the key is absent, so the file matches the checkbox. 실드 left in an older save is still skipped.
Shared: `checked_skill_ids`. The party table writes the default through `_write_support_magic`. Solo magic, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party mage heal and buff selection. A profile that saved another party spell without ever saving 힐 starts healing.
Consent: user ("yes, please update").
Result: `Engine/settings/tests/test_party_mage_support.py`, `UI/ui_qt/editors/tests/test_party_workspace.py`. Not run in game.
=======
## 2026-11-11 — party hunt keeps its mark, and party clicks miss player sprites

Intent: After a map reload, the party leader's hunt rect is the party mark again, not the solo yaml farm. A point stays its 5×5. Inside that mark the leader does not walk toward the solo area. Outside it, the return walk uses the mark. During a party session, a click is not placed on a memory player's center or on any of the eight tiles that touch it. Solo clicks still avoid only living centers. Monster neighbors stay clickable.
Shared: `PartyLeaderManager._mount`, `click_bodies` (travel, loot approach, search), and the party follow hop. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader after a talking scroll lands, and party move, follow, loot approach, and search while another player is beside the click. Solo hunting is unchanged.
Consent: user (the neighbor exclusion is party-only; the farm-edge walk must be fixed; do it on a new branch).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`, `Engine/app/_04_decision/tests/test_party_click_ring.py`. Not run in game.
>>>>>>> origin/main

## 2026-11-11 — after the rally stand the leader walks

Intent: A party start route still uses an NPC teleporter or a talking scroll to reach the meet tile. The stand is on the landing of the last of those steps. After that stand, the same route's remaining steps are walks, and a new party route armed before the leader is inside the farm does not use a talking scroll or an NPC teleporter. A walk-only route still stands on the tile where the plan was made.
Shared: `LeaderStartRally.on_plan` / `should_hold`, `WorldNavSession._pause_for_rally` (solo leaves the hook empty), and `PartyLeaderManager._arm_travel`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader from the hunt route being planned until the leader is inside the farm. Members still follow the leader's live tile, so they meet at the landing.
Consent: user (once the party has gathered at the rally, the leader must not take a teleport or a talking scroll again).
Result: `Engine/app/_06_party/tests/test_leader_rally.py`, `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-11 — a party walk that already started is not dropped at 24 tiles

Intent: Drop a party walk only when the body has never stood on that walk's start. A start the body has already reached stays until the goal, including after the body walks more than 24 tiles away. A start that is still another map, or more than 24 tiles away on the same map, waits 1 second and then the route is dropped and planned from the live tile. The first second still covers the gate pose lag.
Shared: `PartyLeaderManager._party_walk_from_far` and `_release_stale_party_walk`. Solo world-nav, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader's walk after a talking scroll, and any later party walk whose start the body has already reached.
Consent: user (create a branch and apply the start-tile rule).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.
## 2026-11-11 — party supply no longer handles depoison potions

Intent: Remove the depoison row from the party supply tables, and stop the shopkeeper from buying or dropping it. HP and silver arrows stay.
Shared: `_supply_specs` and the party supply tables. Solo depoison purchase, heal, follow, and the HP and arrow rows are unchanged.
Affects: party shopkeeper supply only. A member short on antidote is no longer a supply recipient.
Consent: user ("remove 해독물약 as well in the party mode").
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`, `UI/ui_qt/editors/tests/test_party_workspace.py`. Not run in game.

## 2026-11-11 — party supply no longer handles mana potions

Intent: Remove the mana-potion row from the party supply tables, and stop the shopkeeper from dropping or buying it. HP, depoison, and silver arrows stay.
Shared: `_supply_specs` and the party supply tables. Solo MP potion use, heal, follow, and the other supply rows are unchanged.
Affects: party shopkeeper supply only. A mage who is short on blue potions is no longer a supply recipient.
Consent: user ("파티모드에서 마나물약항목은 없애버리자").
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`, `UI/ui_qt/editors/tests/test_party_workspace.py`. Not run in game.

## 2026-11-11 — a drop with no hop releases the hold after 8 seconds

Intent: On a same-map supply drop, eight seconds without an emitted hop clears the hold through the existing stand timeout. A hop, or arrival on the exact drop tile, clears that wait. A walk that keeps emitting hops is not cut at 8 seconds. The potion is still dropped only from the exact tile.
Shared: `_beside_member` and `cancel_supply_delivery`. The clock is `walk_idle_since`, so `tick_shopkeeper_duty` still zeroes `since` on a planned tick. Buy, pickup, the leader party-row recheck, and a cross-map walk are unchanged.
Affects: the shopkeeper's drop for the party leader and for any other recipient, once the stand is already planned and the shopkeeper is on that map.
Consent: user ("yes" after the no-click wait was the remaining freeze).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-11 — a leader supply drop does not wait forever on an unread party row

Intent: When the supply recipient is the party leader, drop on the already confirmed stand if that leader's party row has no tile, is `0,0`, or does not convert to a nav tile. A live nav tile that matches the stand still drops, and a passed check leaves the `supply drop held` label. One tile still retargets. Two or more tiles, or a map that converts somewhere else, still cancels. A different map id that still projects onto the stand still waits, on its own 8 second clock, then the existing stand timeout. That clock is not the walk clock.
Shared: `_leader_drop_recheck`, `_apply_leader_drop_recheck`, and the held-label rewrite in `_beside_member`. `tick_shopkeeper_duty`, `leader_supply_stand`, buy, pickup, and a drop for anyone who is not the party leader are unchanged.
Affects: the shopkeeper's drop when the recipient is the party leader. Other members still drop from the published stand with no party-row recheck.
Consent: user (proceed with the proposed plan; asked to confirm the leader-only scope).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-11 — the stand grid waits until the leader tile has been still for 2 seconds

Intent: Keep the side line while the leader tile is still changing, or has been still for less than 2 seconds. A 0.7 second sample gap no longer switches the member onto the 5×5 stand cell. When a new walk slot's first hop would step farther from the leader, that tick keeps the previous slot. A leader who has been still for 2 seconds, and turret, still use the stand grid.
Shared: `_leader_looks_stopped` for the formation slot only (`FORMATION_STAND_SETTLE_S`), `choose_formation_goal`, and `closing_slot` before `plan_slot_hop`. The 0.7 second follow-band flag, loot, assist, heal, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: every party member's walking follow. After a real stop, the walk to the stand cell starts at 2 seconds instead of 0.7.
Consent: user ("yes, let's update" after the 2 second cases).
Result: `Engine/app/_06_party/tests/test_formation_goal.py`. Not run in game.

## 2026-11-11 — party replans after a scroll land; pause time is not confined

Intent: A party route built on the pre-land tile is dropped once the live tile has stayed more than 24 tiles away for 1 second, and the next plan uses the landing. No new party route starts while a talking scroll landing is still open. The 13 s confined clock counts decide ticks only, so a hotkey pause does not fire a talking scroll. Solo world-nav's gate wait is unchanged.
Shared: `PartyLeaderManager._arm_travel`, `_release_stale_party_walk`, and `note_confined_progress`. `WorldNavSession._start_walk`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader's route after a talking scroll, and the confined escape on solo farming, solo travel, and world-nav walks.
Consent: user (fix the land wait on the party only; fix the pause clock for solo and party).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`, `Engine/app/_04_decision/tests/test_confined_clock.py`. Not run in game.

## 2026-11-10 — member order is assist, then loot, then follow

Intent: A party member attacks when an assist target is in range, then picks up, then follows. A leader step and a seat catch-up no longer cancel that attack or that pile. Heal, a potion, and self-defense stay first. A buff still waits while the member is walking back to the seat.
Shared: `decide_policy`, `party_may_start_loot`, `party_should_drop_loot`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Leader hunt and leader loot are unchanged.
Affects: party member assist, loot, and follow. Solo hunt is unchanged.
Consent: user ("go" — assist, then loot, then follow).
Result: `Engine/app/_06_party/tests/test_close_follow.py`, `Engine/app/_06_party/tests/test_party_loot.py`. Not run in game.

## 2026-11-10 — rally meet tile is the first teleporter, or the current tile

Intent: The party meets where the 2026-11-03 rule said. A route with an NPC teleporter or a talking scroll stands on the departure tile of the first of those steps, then continues that same route. A walk-only route stands on the tile where the plan was made. If that tile is already inside the farm and the route has no teleporter, the leader hunts from there after the stand instead of walking to the area center. The 3-minute stand and the immediate leave when every expected member is within 7 tiles stay.
Shared: `LeaderStartRally.on_plan` / `should_hold`, `WorldNavSession.tick` before a ready step, and `PartyLeaderManager.prepare`. Solo world nav has no rally hook. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader's start, from the hunt route being planned until the stand ends.
Consent: user (fix like above; if already in the farming area, stand on the current tile).
Result: `Engine/app/_06_party/tests/test_leader_rally.py`, `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — rally stand starts on the walk-arrival tick

Intent: When the party leader's walk to the rally mark finishes, stand on that tick. The same tick used to switch to farming and click into the farm before `party_rally_wait` existed. The 3-minute stand and the immediate leave when everyone is there are unchanged.
Shared: `PartyLeaderManager._on_rally_walk_arrived`, called from world-nav arrival before the farming handoff. `prepare`, `note_arrived`, and `party.rally_wait` are the same stand. Solo world-nav arrival, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader's first arrival at the rally mark.
Consent: user (fix this).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.
## 2026-11-10 — a mage heals during catch-up when the cast is in range

Intent: While a mage is walking back to the formation slot, still cast a party heal that is already in range and under the leader's heal percent. A buff, a walk toward someone farther out, loot, and a new attack wait until the slot.
Shared: `mage_list_heal_request` and `_party_list_heal` (`cast_only`, `heals_only`). `formation_returning`, follow clicks, loot, assist, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: a mage party member who is 4 or more tiles off the slot, until that member is within 1 tile. A mage-class shopkeeper on the same member tick gets the same in-range heal.
Consent: user ("yes" after the catch-up gate skipped heals during the goblin fight).
Result: `Engine/app/_06_party/tests/test_close_follow.py`, `Engine/app/_06_party/tests/test_mage_support.py`. Not run in game.

## 2026-11-10 — party leader stands at the rally until the roster is there

Intent: After the party leader reaches the rally mark, stand there. If every expected member is at that mark, walk into the farming area immediately. If someone is still missing, leave when 3 minutes have passed. The invite window does not cut this stand short. Members are not sent the rally tile.
Shared: `LeaderStartRally.note_arrived` / `update`, `PartyLeaderManager.prepare`, and the new `party.rally_wait` step on the world-nav and farming columns. Survival, potions, and retreat still run. The stand stops the column before the hunt walk and the confined scroll. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader's start, between arriving at the rally mark and entering the farm.
Consent: user (전원이 모이면 그 즉시로 이동하라. 우의 기능을 구현하라).
Result: `Engine/app/_06_party/tests/test_leader_rally.py`, `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.
## 2026-11-10 — a member stand keeps its confirmed flag

Intent: The recipient's settled stop tile reaches the shopkeeper. `member_state` already carried the tile and now also carries `confirmed`, which the leader requires before it republishes `supply_stand`.
Shared: `_member_live_view`. The stand wait, the drop, follow, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: a party member who is told to stand for a supply drop. The leader's own stand still comes from the local pose.
Consent: user ("how to resolve it?" after the mage stand never reached the shopkeeper).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — hunt loot stays inside the active farm

Intent: While hunting, do not walk to adena whose tile is outside the active farm. The same rule applies to every farm area, using whichever rect is current. A pile inside the rect, within 3 tiles of its edge, or already within 2 tiles of the character is still taken. The walk back into the rect no longer starts that outside pile again.
Shared: `_step_farm_engage`, `_enter_farm_if_needed`, and field enter/patrol in `_step_travel_engage`. World-nav walks, dungeon-floor travel, newbie training, retreat loot, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: farming on every active area, and the return walk after stepping outside that area. A party leader's on-screen radius is unchanged.
Consent: user (do not pick adena outside the farming area; all areas).
Result: `Engine/app/_04_decision/tests/test_farm_loot_bounds.py`. Not run in game.
## 2026-11-10 — shopkeeper joins the leader after the buy list

Intent: After the supply buy list finishes, the shopkeeper walks to the leader's party-memory map and game coordinate. That pose is used on any map. A same-map body within 3 tiles ends the join. A missed read keeps the route already started. The route holds while the leader stays inside 24 tiles, then aims at the new coordinate.
Shared: `_tick_join`. `try_unstuck_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Buys, drops, follow, and solo shops are unchanged.
Affects: the shopkeeper's walk back to the leader after a finished party supply purchase.
Consent: user ("yes" — return to the leader wherever they are after successful shopping).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — follow clicks again when the leader tile changes

Intent: On the party-memory read where the leader tile changes, the member clicks toward the new slot even while already walking. The click stays at most 2 tiles. The same leader tile still keeps a click that aims at the slot and is more than one tile ahead.
Shared: `hold_follow_click` in `plan_slot_hop` and `plan_field_follow`. A mage heal step does not pass the leader-step flag, so that walk is unchanged. Formation seats, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member local follow while the leader is walking.
Consent: user (apply that update).
Result: `Engine/app/_06_party/tests/test_close_follow.py`. Not run in game.

## 2026-11-10 — party follow click returns to two tiles

Intent: Put the party follow click back to 2 tiles. A straight open line may still chain one tile, and that chain stops at 3.
Shared: `FOLLOW_CLICK_TILES` and `FOLLOW_EXTEND_TILES`. The mage heal step uses the same hop, so it is 2 tiles again. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member local follow, and a mage walking toward an on-screen member who is outside heal range.
Consent: user (change it back to 2 tiles).
Result: `Engine/app/_06_party/tests/test_close_follow.py`. Not run in game.

## 2026-11-10 — party follow click is four tiles

Intent: A party member's follow click walks up to 4 tiles. Two tiles was too short. A straight open line may chain one more tile only while the click stays inside those 4.
Shared: `FOLLOW_CLICK_TILES` in `plan_slot_hop`, `plan_field_follow`, and the settle/approach hops. The mage's on-screen heal step uses the same slot hop, so that walk is also 4 tiles. Dungeon travel keeps its own 3-tile hop. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member local follow, and a mage walking toward an on-screen member who is outside heal range.
Consent: user (make the follow click 4 tiles; 2 is too short).
Result: `Engine/app/_06_party/tests/test_close_follow.py`. Not run in game.

## 2026-11-10 — seat-wait leftovers removed

Intent: Delete the unused seat wait. The leader tick already never turned it on.
Shared: `FormationLagWatch`, `test_formation_lag.py`, `ideal_side_tile`, `allowed_side_tiles`, and the `party.hold_ground` step (`party rally wait members`) are gone. `hold_ground_reach` stays for a standing shot. The 5×5 / 7×7 stand, the side-line walk, turret hunting, and the enter-chat DLL are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader travel and a moving hunt. Nothing in the running bot called this wait.
Consent: user (delete the leftovers; they are unused).
Result: not run in game. Restart the bot to load it.

## 2026-11-10 — leader does not stand for a member seat

Intent: Remove the seat wait that stopped the leader while members were off their side tiles. Arrival at the mark still starts the hunt. A member stands in the 5×5, or the 7×7 from six people, once the leader has been still for the usual 0.7 seconds, including turret. Walking follow stays the side line.
Shared: the leader tick no longer calls the seat watch. `set_party_hold` stays off. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader travel and a moving hunt. The leader no longer idles with `party rally wait members` for a seat gap. Member seats and turret hunting are unchanged.
Consent: user (remove that wait; it is not main's; keep the 5×5 / 7×7 stand).
Result: not run in game.

## 2026-11-10 — turret uses the solo hunt distance

Intent: A monster at a party point uses the solo farm's click distance. On screen is in range. Off screen uses the solo click tiles. A mage in spell aim also uses the solo spell range. The 5×5 still limits walking and piles. It does not cut an on-screen shot down to 8 tiles.
Shared: `step_party_turret_leash` calls `in_attack_click_range`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: which monsters a party leader shoots from a point. Solo hunt is unchanged.
Consent: user (use the solo bot's hunt distance as-is).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — turret shot from the stand

Intent: An elf or mage who is already inside the turret box hunts a monster within the standing shot, even when that monster's tile is outside the 5×5. A monster past that shot stays out. Piles stay inside the 5×5. A party member's attack is not treated as another player having claimed the monster. A stranger's attack still is.
Shared: `step_party_turret_leash`, `contested_mob_guids`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: a party leader standing on a point, and new engages while a party member is already hitting a monster. Solo hunt without a party roster is unchanged.
Consent: user (the leader is not hunting while monsters are nearby).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — arrived turret is the hunt

Intent: After a party point is arrived, the turret module is the hunt. The 5×5 is the farthest a monster or a pile may be, for every class, including an elf mob that is on screen. A step outside that box walks back through the turret. It does not open a world-nav route, and that route's loot does not run. The 3×3 is still the stand. The walk to the point, before arrival, still uses world nav.
Shared: `step_party_turret_leash`, `PartyLeaderManager.prepare`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The 13 s pocket stays off for that same routine.
Affects: a party leader who has arrived at a point, including an elf, a fight that would leave the 5×5, and ground loot past the box. Solo hunt and an area mark are unchanged. Before arrival, a fight outside the box still finishes and then the route to the point starts.
Consent: user ("완벽하게 해결하고" — use the turret module for the hunt; the 5×5 is the maximum move, not a moving hunt).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — turret routine turns off the 13 s pocket

Intent: After the leader arrives at a party point, loot and the walk back onto that dot must not fire the 13 s confined scroll. The pocket stays off until that mark's time ends and the schedule leaves it. The walk to the point, before arrival, still uses the pocket.
Shared: `_maybe_confined_escape` reads `party_turret_routine`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Emergency HP teleport is unchanged.
Affects: a party leader who has already arrived at a point, including the short world-nav walk back onto that dot. Solo hunt and an area mark are unchanged.
Consent: user (once the turret area is arrived, unlock the 13 s stuck for that routine time, then fix).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — seat, route, and the leader's real stop

Intent: A member is on the seat only on this tick's reading: inside 1 tile, and still inside 2. Past 2 tiles, or a missing pose, is scored again. The party walks only when every companion in the wait has that fresh reading. Two seconds without getting closer is not blocked by itself. Blocked means a measured route is not getting shorter. The leader's in-flight step is allowed to finish. The seat center locks once, on the tile where the leader has actually stood, and the facing from the start of the wait stays. Members use that same center. Ten seconds still does not start the walk, and a seat is re-picked at most twice.
Shared: `FormationLagWatch`, `route_steps`, `policy_message`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: when a party wait ends, and which tile the side seats use after the leader stops. Turret is unchanged.
Consent: user ("보완하세요" — do not latch READY for the whole wait, do not call a detour blocked, and lock the anchor on the confirmed stop).
Result: `Engine/app/_06_party/tests/test_formation_lag.py`. Not run in game.

## 2026-11-10 — a party wait ends when the formation is back

Intent: One late member no longer starts their own 10 second give-up. The leader opens one wait for the companions who are already walking together, and walks only when each of them has a fresh reading inside the allowed seat. A pose that drops stays unknown. Ten seconds, or a member who is not actually closing, starts a short seat re-pick. If that still fails, the leader keeps standing and shows that a hand is needed. Survival actions stay in front of that hold. At 4 tiles the next leader hop that would widen the gap is withheld. The member click stays 2 tiles, or 3 on a straight line.
Shared: `FormationLagWatch`, `emit_travel_hop`, `policy_message`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader travel and a moving hunt, and one member seat re-pick while the leader is recovering the line. Turret is unchanged. A shopkeeper, a confirmed shop visit, and another map stay out of the wait.
Consent: user ("이 대로 구현하라" — party-level departure, 10 seconds as recovery rather than abandonment, keep an unread companion, and limit the leader's next hop from 4 tiles).
Result: `Engine/app/_06_party/tests/test_formation_lag.py`. Not run in game.

## 2026-11-10 — one member is waited for at most ten seconds

Intent: The leader stands for one late member for at most 10 seconds. There is no second or third wait. Another member still has their own 10 seconds. Reaching 1 tile still clears that member. The side line stays through that wait, and a hunt stop uses the standing grid only after the same 10 seconds.
Shared: `FormationLagWatch` only. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: how long a party leader stands for one member who is off their seat.
Consent: user (the three 8-second waits are too long; the maximum is 10 seconds per player).
Result: `Engine/app/_06_party/tests/test_formation_lag.py`. Not run in game.

## 2026-11-10 — a missed seat can be waited for again

Intent: One failed 8 second wait does not close the seat. That member gets two more waits, 2 seconds apart, while they are still off the seat. Another member keeps their own waits. Reaching 1 tile clears that member. After three tries only that member is left behind. While a wait is on, the side line stays the side line, and members hear that on the party policy. A hunt stop that lasts 8 seconds still uses the standing grid. The first hold tick, if the body is still walking, clicks the current tile once and drops the open hop.
Shared: `FormationLagWatch`, `set_party_hold`, `step_party_hold_ground`, `policy_message`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The 6, 4, 1, and 2–3 tile numbers stay.
Affects: party leader waits on the way to a hunt and during a moving hunt, and the member formation during that wait. Turret is unchanged.
Consent: user ("검사해보고 수정하라" — keep a limited retry after 8 seconds, do not change the walking formation into the standing grid during the wait, and check that the hold actually stops the body).
Result: `Engine/app/_06_party/tests/test_formation_lag.py`. Not run in game.

## 2026-11-10 — formation wait and catch-up before a new hunt

Intent: While the party is walking together, one required member off their own seat holds the leader. Before the seats have closed, that hold starts immediately. After they have closed, it starts when a member stays at least 6 tiles off the seat for 0.3 seconds. Eight seconds without a return lets the leader walk, marked degraded, until the seats close again. A member 4 tiles off their seat walks back before a new hunt, loot, or buff, and stays on that walk until within 1 tile. A potion, self heal, and self-defense still come first. While the leader is moving, being off the allowed seat also waits on a new assist. A follow click stays 2 tiles. On an open straight line it chains one tile farther before that click ends. A trail seat does not chain.
Shared: `set_party_hold`, `FormationLagWatch`, `decide_policy`, `plan_slot_hop`, `plan_field_follow`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Turret hunting does not use this hold. A shopkeeper and a member on another map are not required.
Affects: party leader travel and moving hunt, and member follow versus a new attack or loot. Solo hunt is unchanged.
Consent: user ("check and implement this" — early leader wait on seat error, member return ahead of a new hunt, and chain the follow click before it ends).
Result: `Engine/app/_06_party/tests/test_formation_lag.py` and `test_close_follow.py`. Not run in game.

## 2026-11-10 — one near radius for leader loot and member self loot

Intent: `farm.loot_max_tiles` is the distance a party leader notices an on-screen pile and the distance that leader walks to it. Every other member loots their own piles inside that same radius. Hunt, assist, heal, and defend stay ahead of that loot. The responsible member uses `farm.loot_engage_max_tiles` and also picks up a colleague's pile.
Shared: `party_leader_pile_ok`, `party_loot_radius`, `party_loot_ownership_filter`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader farm loot, and member loot while the leader is standing. Solo engage range stays `loot_engage_max_tiles`. Members still do not loot while the leader is moving.
Consent: user ("하라" — link the hardcoded leader loot range and the move range into one flexible value; other members self-loot inside it under hunt and assist; the responsible member is wider and takes colleagues' piles).
Result: `Engine/app/_06_party/tests/test_party_loot.py`. Not run in game.

## 2026-11-10 — leader loots 7 tiles; responsible takes party piles

Intent: A party leader picks up an on-screen pile within 7 tiles, after the current fight and a member who is being hit, and before a new hunt. A member whose loot role is responsible picks up every party pile, including a colleague's, not only a pile this character claimed. Random loot still goes to the closest eligible member. Standing F4 side loot stays off for the leader.
Shared: `continue_or_start_loot`, `party_loot_ownership_filter`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader farm loot, and a responsible member while the leader is standing. Solo loot range is unchanged. Members still do not loot while the leader is moving.
Consent: user ("하라" — leader loots on-screen within 7 tiles; the responsible member loots colleagues' piles too).
Result: `Engine/app/_06_party/tests/test_party_loot.py`. Not run in game.

## 2026-11-10 — point arrival arms turret before enter-farm

Intent: When a party-point walk ends and the body is inside that dot's 5×5, turret turns on before the same tick's farming column. The previous mark's enter-farm click does not run. An area arrival, and a landing outside the 5×5, stay on the old path.
Shared: `_on_world_nav_arrived`, `_on_point_arrival`, `set_party_turret`. `farm.enter` already returns when turret is on. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader tick that arrives on a map point. Area marks, solo world nav, and the 13 s escape outside turret are unchanged.
Consent: user ("그렇게 해라" — arm turret on point arrival inside the 5×5, before the farming handoff).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — mage hit jumps the queue; other hits wait

Intent: A monster hitting a mage member replaces the fight already in progress, for the leader and for a member. A monster hitting any other member waits until that fight ends, then is taken before a new hunt. The leader still finishes through the sticky lock. A member keeps the mob already started, then helps the colleague.
Shared: `choose_help_target`, `farm_loot_or_combat`, member target pick in `PartyMemberManager`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader hunt order, and party member assist when a colleague is being hit. Mage members still do not take an assist target. Helping the monster a member is attacking stays after this.
Consent: user ("그대로 적용해서 깨끗하게 구현하라" — finish the current mob, then help a member who is hit; a mage who is hit comes before that hunt).
Result: `Engine/app/_06_party/tests/test_colleague_help.py`. Not run in game.

## 2026-11-10 — stand hold is a 3×3; leader finishes then helps

Intent: A member standing near the leader holds anywhere inside the 3×3 around their seat. A walking side slot still moves when it is one tile off. When a party member is being hit, the leader finishes the monster already in the fight, then attacks the monster that is hitting that member. Mage-only help no longer cuts the current fight short.
Shared: `_slot_hold`, `plan_slot_hop`, `farm_loot_or_combat`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: member stand while the leader is still or in turret. Leader help after the current kill ends.
Consent: user ("고치라" — the exact seat becomes a 3×3; the leader finishes the current monster, then helps a member who is under attack).
Result: `Engine/app/_06_party/tests/test_formation_goal.py`. Not run in game.

## 2026-11-10 — party elf hunts at the solo click range

Intent: An elf in a party, leader turret or member assist, keeps a monster when the solo attack-click range does. The turret box does not add two tiles on top of that range. Melee and mage turret boxes stay as they are.
Shared: `in_attack_click_range`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: elf leader turret target filter, and elf member assist range while spell aim is the global attack mode.
Consent: user ("수정하라" — party elf hunt range matches solo, reuse that check).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-10 — stand grid is 5×5, or 7×7 from six people

Intent: When the leader is standing, and during turret, members take seats in a 5×5 around the leader. From six people, including the leader, that box is a 7×7. The walking side line is unchanged.
Shared: `stand_radius`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The turret 13 s skip already returns before that escape.
Affects: member stand while the leader is still, and member seats during turret.
Consent: user ("let's redefine" — minimum 5×5, maximum 7×7 by member count).
Result: `Engine/app/_06_party/tests/test_formation_goal.py`. Not run in game.

## 2026-11-09 — turret stands inside the 3×3 and skips the 13 s scroll

Intent: On a turret dot, a leader already inside the 3×3 around that tile stands there. The center tile is not clicked again. The 13 s / 3-tile talking-scroll escape does not run while turret is on. Area hunts, world-nav walks, and every other confined escape stay as they are.
Shared: `party.turret_idle` and `_maybe_confined_escape`. `farm.enter` does not pull a turret leader off the point. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader turret after the fight ends, and the confined scroll only while that turret flag is on.
Consent: user ("check and fix" — inside the 3×3 do not walk onto the one tile; the 13 s escape is off for turret only).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-09 — party HP potion uses the solo row; turret waits on the dot

Intent: A party leader and a party member drink the HP potion on the same recovery row the solo bot uses. The party 50% potion line is not a drink threshold. On a turret dot, the leader may walk inside the 5×5 to a live monster. With no target, the leader stands on that dot and does not search tile to tile.
Shared: `line_for` no longer returns a potion ratio. Potion enable, hotbar, and the no-blackboard member check read the solo HP-potion row. `party.turret_idle` walks to the dot when the tile is not the anchor, and farm search does not run while turret is on. Heal, retreat, `try_unstick_escape`, `begin_retreat`, and login clicks are unchanged.
Affects: party leader and party member HP potion. Party leader turret after a fight ends. Area marks and solo hunt search are unchanged.
Consent: user ("Fix" — party uses the solo HP potion setting and pattern; turret may walk inside the 5×5, and with no target idles on the pointed dot).
Result: `Engine/app/_06_party/tests/test_leader_care.py` and `test_leader_routine.py`. Not run in game.
## 2026-11-10 — a party member is whoever this read's control block confirms

Intent: A name left in a Party vector slot is not a member. The slot counts only when this read's `_Rep` vft is `PARTY_VFT_RC_PLAYER`. A failed read of the header or of a slot stays unknown: no leave and no `/초대`. A confirmed read that does not list a name drops that name after the existing 10 second leave confirm. While the leader read is unknown, the monitor may still show the previous join or the member's own fresh report.
Shared: `lp_slot_live`, `lp_read_batch`, `LeaderInvites.observe`, `_party_session_snapshot`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Follow, hunt, retreat, loot, and HP are unchanged.
Affects: party invite skip, the monitor JOINED mark, and leave. Both clients need the rebuilt `party.dll`.
Consent: user ("안전하게 수정하라" — count only a slot whose `_Rep` vft matches, and do not treat a failed read as "not in a party").
Result: `Engine/app/_06_party/tests/test_party_membership.py`. Not run in game.

## 2026-11-10 — a party leader starts as the account class

Intent: A party-leader start copies the selected account's class onto the profile before the bot runs. Elf hunts ranged, mage hunts with magic, and knight or royal hunts in melee. The schedule row for that same account stores the same class. A party member start does not do this. The roster seat the leader assigns stays a seat, not a character class.
Shared: `apply_account_character`, `_sync_party_leader_character`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Solo start, party-member start, follow, and HP lines are unchanged.
Affects: the party leader's hunt attack mode and whether that PC is treated as a mage.
Consent: user ("yes" — party boss task character follows that account's character type).
Result: `Engine/settings/tests/test_attack_mode.py`. Not run in game.

## 2026-11-10 — a party-list cast waits for the spell cursor

Intent: A party-list heal or buff presses its key once, then clicks the member row only after the spell cursor is up. The wait is at most one second. If the cursor never appears, that click is skipped so the row select does not leave the circle for the next ground hop. Shield, greater haste, and decrease weight are no longer party-support spells. A saved check for one of those three is ignored. Haste, weapon buffs, blessed armor, dexterity, might, berserker, and the recovery spells stay. Solo self-buffs still cast shield, greater haste, and decrease weight on the mage.
Shared: `wait_party_spell_aim`, `_party_list_buff`, `_heal`, `choose_party_support`, `_buff_ids`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, `due_buff`, `maybe_cast_buff`, `cancel_spell_aim`, and login clicks are unchanged. Hunt, retreat, loot, and HP potion order are unchanged.
Affects: a class mage in party-member mode, on a party-list heal and on a party-list buff.
Consent: user ("yes" — click the party row only after the spell cursor is up, and drop shield, greater haste, and decrease weight from party support).
Result: `Engine/app/_06_party/tests/test_mage_support.py`, `Engine/app/_05_action/tests/test_spell_aim_hold.py`. Not run in game.

## 2026-11-10 — a leftover party row is not a follow goal

Intent: Join and follow use the party-memory leader only when that name is the connected leader's policy `leader_name`. An empty policy name does not match, so the member waits instead of scrolling toward the row that is already in the Party vector at startup. While an invite popup is open, or Y was sent and memory still names someone else, same-map follow waits too. A confirmed name still joins that pose, including a scroll hop when the maps differ.
Shared: `memory_leader_confirmed`, `suppress_unconfirmed_leader`, `suppress_join_while_invite`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Hunt, retreat, loot, and HP potion order are unchanged.
Affects: party-member follow and cross-map join.
Consent: user ("yes" — do not join or follow until the memory leader matches the policy name, and also stop same-map follow while the invite is unresolved).
Result: `Engine/app/_06_party/tests/test_invite_accept.py`. Not run in game.

## 2026-11-10 — an open party invite is answered, and join waits for that inviter

Intent: An open party-invite confirm gets Y even when party memory already says this character is in a party. The join is confirmed only after the popup has closed and the memory leader name is the inviter on that popup. Until then the member does not start or continue a cross-map join, so a leftover leader pose is not a scroll goal. Invites from someone other than the connected leader's policy name are still left alone.
Shared: `InviteAccepter.tick`, `blocks_join_map`, `suppress_join_while_invite`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Hunt, retreat, loot, and HP potion order are unchanged.
Affects: party-member invite accept, and cross-map join toward the party leader.
Consent: user ("yes" after the plan: Y from the open popup, policy leader name only for who is ours, no join_map until memory leader matches that inviter).
Result: `Engine/app/_06_party/tests/test_invite_accept.py`. Not run in game.

## 2026-11-10 — party arrow supply counts silver arrows only

Intent: The existing arrow supply row is silver arrows. A member's normal arrows do not fill that row, a normal-arrow pile does not satisfy the claim, and the drop takes a silver-arrow stack. The shop for that row is the silver-arrow shop. The UI buy count, the per-person give count, who is skipped, and the order after MP stay as they are. Solo arrow restock still follows the solo buy checkboxes.
Shared: `report_arrow_count`, `bag_supply_counts`, `rows_with_expected`, `supply_pile_matches`, `shops_arrow_id`, `party_shop_buy_qty`, `supply_drop._kind_tables`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. HP, depoison, MP, the configured buy count, the 12-tile approach, Esc, the stop check, the nav stand, and solo shop quantities are unchanged.
Affects: party supply of the arrow row, including the shop the shopkeeper opens for it and the stack they drop. The party supply table labels that row 은화살.
Consent: user ("일반화살, 은화살 두개로 가를 필요 없이 은화살만 보는걸로 하자. 일반화살은 무시하고.").
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`, `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — a supply buy is the configured shop count

Intent: A party supply purchase buys the UI buy count for that item. The sum of each member's shortage does not raise it, and a bag under the shopkeeper reserve does not raise it either. Spare above the reserve is still dropped first. A bag under the reserve, or a reserve with nothing left while someone is short, is what starts the shop. Adena still limits the count, and MP is still not bought. The per-person drop count and solo shop quantities stay as they are.
Shared: `planned_buy_qty`, `supply_fill_qty`, `party_shop_buy_qty`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Supply choice, the 12-tile approach, the drop gesture, Esc, the stop check, MP and arrow rules, solo hunt, and Brain wiring are unchanged.
Affects: how many HP potions, depoison potions, or arrows the shopkeeper types at the party supply shop.
Consent: user ("예" — buy the UI amount, do not add up party shortages or fill the reserve in that same count).
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-10 — a party mage casts checked support spells on other members

Intent: The party-screen checks are the only spells this mage casts on other members. An empty save keeps heal. Single-target heals use the strongest checked spell on the hotbar (full, greater, extra, heal). Heal all is used only when two or more other members are under the heal line and inside 9 tiles; one member uses a single heal, and heal all alone does not cover that one member. Cure and remove curse run only when a fresh buff report shows poison or a curse. Resurrection clicks a 0% row. Buffs recast when the remain is missing or at or under 10 seconds. A report newer than 20 seconds is the remain. Otherwise the mage counts from the click plus the catalog duration. Three reports after a cast that still lack the buff park that pair for 30 seconds. Death or a map change clears that member's clock. Weapon spells keep bless, then enchant, then holy. Speed keeps greater haste, then haste. Shield, blessed armor, dexterity, might, decrease weight, and berserker each stand alone. One cast per tick, after self retreat, potion, self heal, in-range defense, and self buff. The leader sends buff and ailment rows to every connected member. The shopkeeper supply bundle stays with the shopkeeper. A mage shopkeeper still interrupts a shop only for an in-range heal at the character's own heal line.
Shared: `choose_party_support`, `_party_list_heal`, `publish_party_buffs`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Solo magic, self buffs, assist, and other classes are unchanged.
Affects: a class mage in party-member mode, and the leader's 10-second buff forward.
Consent: user ("ok, great, let's implement" after the checked-spell, remain, heal-order, and leader-relay plan).
Result: `Engine/app/_06_party/tests/test_mage_support.py`. Not run in game.

## 2026-11-10 — a supply drop is planned on the map pack's nav tile

Intent: `supply_stand` keeps the coordinates it received. Those coordinates become a nav tile only when this map's pack says so: a point on the nav grid is already nav, and a point that lands on that grid after subtracting the pack origin is a game tile. Both readings, or neither, do not pick a tile. The drop neighbor is chosen on that nav tile. The party-list recheck no longer cancels only because its map number differs. The same map confirms the tile: the same tile drops, one tile retargets, two or more tiles cancel. A party row that is a real tile on another map, and not on the stand map, cancels. Anything else waits, and the hold stays.
Shared: `plan_supply_drop`, `_leader_drop_recheck`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Supply choice, the 12-tile approach, buy quantity, Esc, the stop check, the 8-second timeout, the 6-second pause, MP and arrow rules, solo hunt, and Brain wiring are unchanged.
Affects: the shopkeeper's drop tile for a confirmed stand, including a leader stand on Talking Island.
Consent: user (convert the received stand with that map's pack, do not trust a differing party map by itself, defer when the latest tile is not confirmed, cancel a confirmed map change or a two-tile move, retarget only a one-tile move on the same map).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — Talking Island map 0 is a real supply stand

Intent: Map id 0 is the Talking Island map, so a stopped live tile there is confirmed and sent. A pose that was not read is still not a stand, and tile `0,0` is still not a stand. The half-second settle, Esc retries, 8-second timeout, 6-second pause, two-tile cancel, and 12-tile approach stay as they are. The shopkeeper already accepts map 0 on the drop tile.
Shared: `leader_hold_displaced`, `leader_supply_stand`, `_publish_supply_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Supply choice, the 12-tile approach, buy quantity, the drop gesture, solo hunt, MP and arrow rules, and Brain wiring are unchanged.
Affects: a supply stand while the recipient is on Talking Island.
Consent: user (keep map id 0 as a real map, still drop tile 0,0 and an unread map, and do not change Esc, the settle time, the timeout, the pause, the two-tile cancel, or the 12-tile approach).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — a supply stand waits until the live tile has been still

Intent: While a hold is unconfirmed and the body is still walking, Esc is pressed again only at a half-second gap, and at most three times. A stop or a survival action sends no further Esc. The party log records each press, the stop that follows, and a walk that is still moving after the last press. The stand is confirmed only when the live map is not 0 and that live tile has stayed still, with the body not walking, for half a second. One stopped sample does not confirm. `supply_stand` carries that live map and tile. Party memory and `map_id` 0 are not sent. Before confirmation a coordinate change only updates the latest tile. After confirmation, two tiles or a map change cancels even if the drop was announced. One tile still retargets at drop time. The 8-second timeout and the 6-second pause stay.
Shared: `recipient_hold_intent`, `leader_hold_displaced`, `leader_supply_stand`, `_publish_supply_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Supply choice, the 12-tile approach, buy quantity, the drop gesture, solo hunt, MP and arrow rules, and Brain wiring are unchanged.
Affects: the party member, including the leader, who receives a supply hold, from the moment the hold starts until `supply_stand` is sent.
Consent: user (limited Esc retries only while still moving, half-second live-tile confirmation, send the live map and tile, keep the post-stop two-tile cancel and the one-tile drop retarget, keep the 8s timeout and 6s pause).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — a supply stand is sent only after the walk has stopped

Intent: A hold stops the ground click already in progress, and `supply_stand` is sent only after the body is stopped on the same tile a second time. Until that confirmation, a two-tile change updates the latest coordinate and does not cancel. After confirmation, two tiles or a map change still cancels. The shopkeeper drops only from a confirmed stand for the current attempt id. A stand-moved cancel and a stand timeout both wait out the existing short pause before the same person and item are tried again. Critical retreat, a potion, and urgent self-heal stay first, and a survival action that changes the tile still cancels the hold.
Shared: `leader_hold_displaced`, `leader_supply_stand`, `recipient_hold_intent`, `_stand_left`, `_publish_supply_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Supply choice, the 12-tile approach, buy quantity, solo hunt, MP and arrow rules, and Brain wiring are unchanged.
Affects: the party member, including the leader, who receives a supply hold, and the shopkeeper's drop anchor.
Consent: user (halt the in-progress ground move, send supply_stand only after a real stop, update coordinates before confirmation, apply the two-tile and map cancel only after confirmation, use only a confirmed stand for the current attempt, and pause a retry after stand moved or a failed stop).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — a supply hold stays up, and the recipient hunts in place until the drop

Intent: Once the shopkeeper is within 12 tiles, that hold stays for the same person and item even if the next step is outside 12 again. The recipient stops new search and chase, and attacks only a monster already in reach, until the shopkeeper announces the drop. The announce is one tick beside the recipient before the ground gesture, and it is published on the same hold id with `dropping`. That tick clears combat so they can receive. A finished drop, the 8-second stand timeout, a two-tile departure after the body stops, or a map change returns the hunt to normal. Critical retreat, a potion, and urgent self-heal still come first.
Shared: `tick_shopkeeper_duty`, `_tick_drop`, `recipient_hold_intent`, `leader_supply_action`, `_publish_supply_hold`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Solo hunt, buy quantity, MP and arrow rules, and Brain wiring are unchanged.
Affects: a party member, including the leader, who is the recipient of a supply drop.
Consent: user (keep the hold and supply the short member; while waiting, hunt in place without moving; stop hunting when the drop starts; return to normal when the supply ends).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — confirmed self name, and the leader stands before the supply tile

Intent: A nearby party leader or another member is not this character's name. The print-state or client-memory name is used, and a name that is not on the roster is seat `unknown`, so shopkeeper, mage-list heal, assist, and loot do not run. A supply hold for the leader still lets critical retreat, a potion, and urgent self-heal go first. Only a hold requested after the shopkeeper is within 12 tiles stops new attacks and chase. The stand tile is the party-memory coordinate after the body has stopped, not the tile where the hold arrived. Walking before that stop updates the latest tile and does not cancel. After the stop, two tiles or a map change cancels as before, and one tile still retargets the drop. Cancel, a finished drop, or the stand timeout clears the hold and the hunt decision runs again. Hold ids and attempt numbers are unchanged.
Shared: `self_name_from_party`, `seat_role_for_name`, `leader_hold_displaced`, `leader_supply_stand`, `_publish_supply_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Solo hunt, buy quantity, MP and arrow rules, other members' hold rules, and Brain wiring are unchanged.
Affects: which seat a member applies from the leader policy, and a party leader who is the supply recipient.
Consent: user ("두 문제를 함께 수정" — confirmed self name, unknown seat, leader stands only after a 12-tile hold, stand coordinates after the body stops).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — a one-tile leader step retargets the drop

Intent: A map change, or a move of two tiles or more, still clears the supply hold. A one-tile difference does not. Immediately before the drop, the stand tile is compared with the leader's live party-memory tile. When those differ by one tile, the drop is aimed at the live tile and the gesture does not run on the old square.
Shared: `_leader_drop_recheck`, `_tick_drop`, `plan_supply_drop`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The two-tile hold cancel, solo hunt, solo shop, buy quantity, MP and arrow rules, and Brain wiring are unchanged.
Affects: a supply drop whose recipient is the party leader and whose live tile is one step off the confirmed stand.
Consent: user ("두 칸 기준은 홀드 취소 조건으로 유지하더라도, 실제 드롭 좌표는 최신 위치와 일치해야 합니다").
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — role priority clashes, without a new party architecture

Intent: The leader's critical retreat stays first. Urgent self care (potion, self heal, in-range defense) runs before a supply hold or pickup, and a hold whose tile moves is cleared so a new hold can be taken. A class mage who is also the shopkeeper casts an in-range urgent party heal before a buy or a drop; routine heals, buffs, town, and the scroll stay on the existing shop trip. A purchase that is still buying keeps going. Once that purchase is finished, leftover shop travel does not block the walk back to the leader. A supply target is chosen by guid when one exists. A duplicated name, or two nearby rows and no name, is not guessed from coordinates. The start rally already opens the hunt when the leader reaches the mark, so the old "wait for members" tests now expect that.
Shared: `leader_supply_action`, `cancel_supply_delivery`, `_opening_shopkeeper_heal`, `release_finished_party_shop`, `stable_self_identity`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Solo hunt, solo shop quantities, the 10s report, MP and arrow rules, and Brain wiring are unchanged.
Affects: the leader while named on a supply hold, a mage shopkeeper, the shopkeeper after a finished buy, and who a supply hold is allowed to name.
Consent: user ("역할별 행동 우선순위에서 발생하는 충돌만 먼저 수정" — leader survival before hold, urgent party heal only, finished shop must not block join, stable supply identity, and judge the rally tests).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`, `test_leader_rally.py`, and `test_leader_pose_fresh.py`. Not run in game.

## 2026-11-09 — a hold still expires during survival, and a blocked drop can end

Intent: While the shopkeeper repeats a survival action, the stand wait keeps its clock. At 8 seconds the existing hold clear runs, so the recipient is released, and the survival action still owns the tick. A blocked ground drop retries a few times. After that the same clear releases the hold, skips that member briefly, and follow runs again.
Shared: `expire_supply_hold`, `_tick_drop`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The 10s report, buy quantity, MP and arrow rules, mage class versus seat, and Brain wiring are unchanged.
Affects: a shopkeeper who is waiting on a stand and then drinks, heals, or defends, and a drop gesture that stays blocked.
Consent: user ("두 가지 예외만 먼저 보완" — hold expiry during survival, and limited recovery for arrow drop blocked).
Result: `Engine/app/_06_party/tests/test_supply_hold.py` and `Engine/app/_06_party/tests/test_supply_drop_flow.py`. Not run in game.

## 2026-11-09 — one town trip covers the party shortfall

Intent: Spare above the reserve is still dropped before another town trip. A buy that refills an empty reserve also includes the party's shortage, and a bag with no spare left buys that shortage in one trip, capped at 999. MP stays a drop because no shop behavior exists. ShopkeeperBrain and MageBrain return the manager's existing decision. The session still calls PartyMemberManager.decide. Solo shop quantities stay on the solo path.
Shared: `planned_buy_qty`, `party_supply_need`, `choose_supply_duty`, `next_supply_buy`, `ShopkeeperBrain.adopt`, `MageBrain.adopt`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the shopkeeper's next buy size when the party is short. Follow, assist, heal, and solo shops are unchanged.
Consent: user ("yes, let's proceed" — phase 3, and keep working solo and party logic working).
Result: `Engine/app/_06_party/tests/test_arrow_supply.py` and `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — supply counts and roles stay current, and the party log says so

Intent: MP still goes to the roster mage seat, and also to a class mage whose seat is not mage. Arrows skip that same set. Party heal and melee assist stay on the character class. After a drop, the shopkeeper adds that quantity onto the count the current report still shows, until a different report arrives. While walking to a recipient, a changed live tile replaces the previous goal. The same party log records the phase-1 care, stand timeout, drop shift, and shop-approach reset.
Shared: `mp_recipient_names`, `remember_delivered`, `rows_with_expected`, `_approach_until_close`, `release_care_pose`, `cancel_supply_delivery`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The 10s report interval, buy quantity, MP shop purchase, and Brain wiring are unchanged.
Affects: who receives MP and arrows, the next supply choice after a drop, and the shopkeeper's approach tile.
Consent: user ("okay, let's implement 2차기능들 too" and add logs for phase 1 and phase 2).
Result: `Engine/app/_06_party/tests/test_supply_hold.py` and `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — survival before supply, and a delivery that can end

Intent: Urgent self care (HP potion, self heal, in-range defense) runs before a supply hold, a shop buy, or a drop. Buffs and party heals stay where they were. A survival action does not delete the shop trip. If that action moved or teleported the body, the shop NPC approach and the drop tile are checked again. Waiting for a stop tile times out, the existing hold clear tells the other side, and that member is skipped briefly. The next attempt has its own hold id, so the old stop tile cannot open it. When the stand has no empty neighbor, the shopkeeper steps to a safe adjacent tile and measures again, a few times, then clears the hold and goes back to hunting.
Shared: `urgent_self_survival`, `tick_shopkeeper_duty`, `release_care_pose`, `cancel_supply_delivery`, `choose_drop_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. The 10s report, MP and arrow rules, mage class versus seat, buy quantity, and Brain wiring are unchanged.
Affects: every party member's self care before supply, and the shopkeeper's wait, shift, and cancel.
Consent: user ("네, 제안한 1차 범위로 진행해 주세요" — survival first, resume the shop, stand timeout, per-attempt state, limited empty-tile retries).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — supply waits out a join, and the stand tile is the live one

Intent: While a world-nav join is still walking off a scroll, the shopkeeper does not start a buy or a drop. A failed approach click hands the tick back to follow. A new leader session closes supply. The hunt map follows the leader while they are hunting. The stand sent with the hold is the recipient's current party-memory tile; their own stopped tile replaces it when it arrives. The approach walks to that live tile when party memory has it.
Shared: `tick_shopkeeper_duty`, `_approach_until_close`, `MemberOrders._drop_orders`, `_party_hunt_open`, `_publish_supply_stand`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: shopkeeper supply during and after a map join, and the stand the leader publishes.
Consent: user ("yes" — the four edges plus an instant stand tile).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — shopkeeper reads hunt_open from party_reports

Intent: A `party_reports` frame sets `MemberOrders.supply_open` from the leader's `hunt_open`. The shopkeeper supply tick stays closed until that flag is true.
Shared: `MemberOrders.ingest` for `party_reports` only. `tick_shopkeeper_duty` already returns None while the flag is false, so the join walk continues. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: shopkeeper supply after the leader publishes `hunt_open`.
Consent: user ("yes" — move the `supply_open` assignment above `continue`).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — a recipient stands only when the shopkeeper is close

Intent: On the hunt map the recipient keeps hunting and following while the shopkeeper is farther than 12 tiles. The stand notice is sent only inside that distance. The shopkeeper walks toward the latest report until then, and does not chase another map.
Shared: `tick_shopkeeper_duty` and `_approach_until_close`. The hold, the empty-neighbor drop, and pickup after the notice are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party supply approach on the hunt map.
Consent: user ("yes" — do not stand while the shopkeeper is far; stand only when close).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — supply waits until the hunt mark, and skips anyone who has left

Intent: The shopkeeper does not buy, hold, or drop until the leader start rally is done. A recipient who is retreating or whose map is not the hunt map is left out, and an open hold for them is cleared. On the hunt map, distance does not change the stand: the recipient waits and the shopkeeper walks.
Shared: `tick_shopkeeper_duty` reads `supply_open` and `supply_ok`. The leader stamps those on `party_reports`. The leader tick and member `decide` skip supply while leaving the hunt. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party supply before the mark, and any recipient on a retreat or another map.
Consent: user ("예" — close supply before rally and while retreating or off the hunt map).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-09 — a supply recipient stands beside the drop

Intent: When the shopkeeper has stock and chooses who to supply, that person stops on the tile they are on when the notice arrives. The drop lands on an empty neighbor, not on the body. Until the drop notice arrives they attack only a monster already in reach. The drop notice stops that attack and picks the pile up. After the pile is taken, or the shopkeeper cancels, hunt and search run as before.
Shared: `tick_shopkeeper_duty` publishes `supply_hold` and walks to the confirmed stand. `supply_wait_intent` and `_pickup_claim` run before hunt on the leader tick and in member `decide`. `choose_drop_stand` picks the neighbor. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader and any member named on a supply hold, and the shopkeeper walking to that stand.
Consent: user ("yes" after the empty-neighbor stand and immediate pickup).
Result: `Engine/app/_06_party/tests/test_supply_hold.py`. Not run in game.

## 2026-11-10 — shopkeeper drop waits for each gesture before the next

Intent: Beside the leader, the shopkeeper opens the inventory, re-reads the already chosen arrow slot, Shift-drags, and types the give count only after the quantity prompt is visible. A supply notice is published only after that arrow's bag count falls by the requested amount. The same failure does not repeat without a pause, and follow does not resume until the drop is confirmed.
Shared: `_maybe_dismiss_ui` allows `Inventory` only while `party_supply_drop.active` is set. Solo and every other party action still pass an empty allow list. Shop buy, the approach, item-id choice, give count, drop-tile formula, and the notice fields are unchanged.
Affects: the shopkeeper's ground drop after it is already next to the short member.
Consent: user (the supply-drop stabilization task).
Result: `Engine/app/_06_party/tests/test_supply_drop_flow.py`. Not run in game.

## 2026-11-10 — shopkeeper drop walk converts report xy to nav tiles

Intent: A same-map arrow drop walks to the short member's nav tile. Report xy stays game coordinates for a different-map world-nav walk.
Shared: `game_to_nav` inside `_beside_member` after the other-map branch. Follow, pickup claims (already nav), shortage math, unstick, and solo travel are unchanged.
Affects: shopkeeper drop approach on the member's map. An off-map goal no longer reaches `start_travel`.
Consent: user (the coordinate-conversion task, apply if no side effect).
Result: `test_same_map_drop_converts_game_xy_before_travel` passed with the existing arrow-supply tests. Not run in game.

## 2026-11-09 — supply pickup matches the notified count

Intent: The member named on a supply drop picks up the pile only when its ground count equals the notified count. An unread ground count still uses the name and the tile. Other seats still leave that tile alone by location.
Shared: `supply_pile_qty_ok` inside `_pickup_claim`. The drop, the leader relay, follow, and ordinary loot are unchanged.
Affects: the named member and the leader when the leader is the recipient.
Consent: user ("ye4s" after the pickup-count proposal).
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — a party mage steps into heal range on the same screen

Intent: When another member is under the mage heal percent, on the same map, inside the clickable view, and farther than 9 tiles, the mage walks toward a stand 9 tiles from that member. Each click is the usual follow hop, at most two tiles. Once inside 9 tiles the existing list heal runs. A member outside the clickable view is left to follow. Self heal, self buff, a potion, and self-defense still come first.
Shared: `heal_screen_step` chooses the stand. `PartyMemberManager._party_list_heal` emits `plan_slot_hop` with kind `heal_step` and clears an open map-join for that tick. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member mage ticks where the due member is on screen and out of heal range. Other classes and the party leader's farm columns are unchanged.
Consent: user ("let's implement that then" — walk a little toward an on-screen member who is outside heal range).
Result: unit check in `Engine/app/_06_party/tests/test_hud_heal.py`. Not run in game.

## 2026-11-09 — follow click uses the member-to-slot delta

Intent: On a party-memory read, the next click is a step from the member toward this read's formation slot. The slot is beside or behind the leader, never the leader tile. Delta zero does not click. A hop that still lies on that delta is kept while the body is walking. A delta whose direction changed, or a hop that would pass the slot, clicks the latest tile immediately. The hop stays at most two tiles.
Shared: `plan_slot_hop` and `plan_field_follow` only. Leader loot, retreat, HP, and login clicks are unchanged.
Affects: party-member local follow. Repeated reads with the same delta do not restart the step. A leader turn starts a new click on that read.
Consent: user ("implement" after the same-tick delta proposal).
Result: `Engine/app/_06_party/tests/test_close_follow.py`. Not run in game.

## 2026-11-09 — a one-tile leader step moves the member at once

Intent: When the leader's party-memory tile changes by one tile, the member's side slot moves with it on that read, and a member one tile off that slot walks. The slot is no longer kept for a one-tile drift, and standing one tile off the slot is no longer a hold.
Shared: the side-slot sticky in `choose_formation_goal`, `ARRIVAL_TOLERANCE`, `_slot_hold`, and `plan_slot_hop`. Leader loot, retreat, HP, and login clicks are unchanged.
Affects: party-member follow while a formation slot exists, including the stand grid after the leader has been still. A one-tile miss now clicks. The click is still at most two tiles.
Consent: user ("리더가 1칸만 움직여도 그 즉시로 따라가게 해야해").
Result: `Engine/app/_06_party/tests/test_formation_goal.py`. Not run in game.

## 2026-11-09 — moving hunt keeps the side line ahead of the trail

Intent: While the leader is walking on a moving hunt, a member stands on the side line first. The single-file trail is used only when that member's side tiles are blocked.
Shared: `choose_formation_goal` only. The stopped stand grid, turret yard, leader loot, retreat, HP, and login clicks are unchanged.
Affects: party-member follow while the leader's tile is still changing. A free tile beside the leader keeps the member there. A one-tile corridor still falls back to the trail. A leader who turns around swaps left and right.
Consent: user ("yes" — side line first, trail second, during moving-hunt walk).
Result: `Engine/app/_06_party/tests/test_formation_goal.py`. Not run in game.

## 2026-11-09 — party members keep their solo recovery lines

Intent: The party leader no longer has a support-and-protection page. Each character uses the heal, potion, retreat, mother tree, talking scroll, and safe-zone values already set on the solo screens. The mage line for healing other members stays, on the page now named 파티운영.
Shared: party `decide` and the leader brain no longer install `PartyRecovery`. `apply_party_support` is called without a leader heal or potion ratio, so the solo threshold is used. Follow, combat, supply, and the mage party-list heal are unchanged.
Affects: party leader menu, and every party seat's own recovery.
Consent: user (remove the whole support section; members use solo settings; keep mage heal-others on the hunt page and rename that page).
Result: `UI/ui_qt/editors/tests/test_party_workspace.py` and `Engine/app/_06_party/tests/test_leader_care.py`. Not run in game.

## 2026-11-09 — leader hunts in the 5×5 around a map dot

Intent: On a party-map point, the leader hunts anywhere in the 5×5 centered on that dot and is not pulled back to the center. Stepping outside that box keeps the current monster until it is finished, then the leader walks back to the dot. A new monster outside the box is not started.
Shared: party leader schedule place check, the turret anchor, and `party.turret_leash` / `party.turret_idle`. The anchor is the dot's nav tile, the same space as `world_origin`. A point's farm rect is that 5×5. Area marks, member follow, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader turret while the current row has a map dot. Leaving the box pauses the row timer. An in-flight walk back keeps going until it finishes.
Consent: user (move smoothly in the 5×5; outside the box, finish the current target, then return).
Result: `Engine/app/_06_party/tests/test_leader_routine.py`. Not run in game.

## 2026-11-08 — leader drops the fight when a mage member is hit

Intent: While this bot is the party leader, a monster whose attack target is a mage party member is taken before the current sticky fight, attacks-me, loot, and helping whatever another member is attacking. Solo hunting does not set `party_help_open`.
Shared: `farm_loot_or_combat` only, and only when `party_help_open` is set. `begin_engage` switches the lock and does not give the previous target up. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader hunt. Member assist order is unchanged.
Consent: user (from the leader, once a mage member is attacked, that help is priority one and must happen).
Result: not run in game.

## 2026-11-08 — help the monster a party member is attacking

Intent: Read each member's current attack target from the party line `atk`. A member attacks that monster only when the leader has no assist target. The leader attacks it only after the current fight and anything attacking the leader are finished, and after loot.
Shared: `farm_loot_or_combat` checks `party_help_open`, set only while this bot is the party leader. Solo hunting does not set the flag. `engage_like_solo` still ignores the species list only for the leader's own target. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member assist fallback and party-leader hunt after a kill.
Consent: user (recognize the attacking monster and implement; help is below leader assist; the leader helps after its own fight).
Result: not run in game. `PARTY_JOIN_ACTOR=1` is read by the existing `party.dll`; the DLL was not rebuilt.
## 2026-11-09 — party recovery uses the party window, including before a policy

Intent: While a character is in a party, heal, HP potion, retreat, mother tree, talking scroll, and safe zone follow the party support page. Before a leader policy arrives, the party defaults are used (heal 70, potion 50, mage list-heal 80, retreat 30, mother tree on with HP≥85/MP≤80 and heal HP≤40/MP≥80, talking scroll on, safe zone on). The mage's own heal and potion, and the leader's own character, use those same lines. After a member finishes recovery they follow the leader and do not walk back to the hunt. Solo recovery is unchanged when the party overlay is absent.
Shared: `action_threshold`, `_hp_action_enabled`, `_hp_recovery_allowed`, heal/potion availability, `elf_uses_mother_tree`, `talking_scroll_available`, mother-tree HP/MP bands, and `_can_safe_now` read the overlay only while a party tick has installed it. Solo callers never install it. `party_critical_escape` still drops the post-retreat hunt return.
Affects: party leader 지원 page, party-member self-heal, potion, and retreat, mage self-heal and list-heal, and the leader's own hunt recovery while party leader mode is on.
Consent: user ("정책이 정식 오기전에는 파티전에서의 기정값들을 사용해야 해", "이들의 회복도 파티창의 설정값들을 써야 해", "파티 전용 칸을 만들어서 그 파티전용 설정값들에 의해 회복절차를 타야 해. 회복이 끝나면 사냥터로 돌아가지 않고 파티장 따라가는것은 좋아").
Result: `Engine/app/_06_party/tests/test_leader_care.py` and the party workspace UI test. Not run in game.

## 2026-11-09 — supply shops continue before the leader return

Intent: After the shopkeeper buys one supply item, later rows are bought on the same outing when the keeper is still short and Adena covers at least one. Order stays HP, antidote, then arrows. A row whose remembered price is more than Adena is skipped. When no later row needs a visit, the shopkeeper returns to the leader. An in-progress shop is not replaced by a new choice. Solo shops still return to the farm.
Shared: `next_supply_buy` and the party supply success path in `apply_cursor_verify_feedback`. Solo shop completion still calls `mark_post_shop_return`. Follow, heal, and combat are unchanged.
Affects: shopkeeper HP, antidote, and arrow purchases.
Consent: user (after HP, continue to later items when they must be bought and Adena allows; return to the leader when there is nowhere else to go).
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — one supply shop trip fills the keeper reserve

Intent: A party supply buy no longer purchases only the boss "사는 수" and walks back to buy the same item again. One trip buys enough to reach the keeper reserve, and at least the boss buy count. The shop list price is read before the quantity is typed. Adena buys as many as it covers. A learned price blocks another walk while Adena cannot pay for one. Solo shop quantities are unchanged. The shop field still stops at 999.
Shared: `supply_fill_qty` / `party_shop_buy_qty` for the party supply pin, and `execute_calibrated_buy` only while `party_shopkeeper_arrow` is set. Follow, heal, and solo buys are unchanged.
Affects: shopkeeper HP, antidote, and arrow purchases.
Consent: user (buy enough to reach the reserve on the first trip; if Adena is short, buy as many as the price allows).
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — leader sets party heal and potion lines

Intent: The party leader support page sets three lines. Non-mage members self-heal and drink an HP potion at those percents. The mage list-heal uses the leader's line instead of a fixed 80. Until a policy arrives, each member keeps their solo lines and the mage list stays at 80. The unused "HP danger emergency assist" card is removed. Mage self-heal, solo recovery, and the retreat line stay as they are.
Shared: `apply_party_support` and `_side_hp_potion` gain an optional ratio. Solo callers omit it, so solo heal and potion lines are unchanged. `party_critical_escape` is unchanged.
Affects: party leader 지원 page, party-member self-heal and HP potion, and mage party-list heal.
Consent: user ("좋다. 실현하자") after the leader-line proposal, then "긴급 지원은 필요없어" and the mage 80% line must be set by the leader. Defaults: member heal 70, potion 50, mage list heal 80.
Result: `Engine/app/_06_party/tests/test_leader_care.py` and the party workspace UI test. Not run in game.

## 2026-11-09 — shopkeeper also supplies three potions

Intent: The shopkeeper still supplies arrows, and now also HP potions, antidote, and blue MP potions on the same 10-second report. Order is HP, antidote, MP, then arrows. A short shopkeeper buys one item and returns before the next. HP and antidote go to every seat except the shopkeeper. MP goes only to the roster mage and is not bought, because no shop behavior exists. Arrows still skip the mage. Each drop keeps the shopkeeper reserve and uses the boss give count. Solo shop quantities stay on solo trips.
Shared: `choose_supply_duty`, `step_ground_drop` stack choice, and `_emit_shop_run` quantity only while `party_shopkeeper_arrow` is set. Follow, heal, combat, and solo buys are unchanged.
Affects: party boss 마을 및 보급, the shopkeeper drop and shop pin, and the member pickup of that pile.
Consent: user ("yes") after the potion-supply plan. Defaults: HP 10/20/10/20, antidote 1/2/1/5, MP 5/10/5/10.
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — hunt item tab paints armor first

Intent: Opening the hunt item list was decoding every catalog icon on the UI thread. The table now opens on the 갑옷 category. Names, allow flags, and categories for the whole catalog are filled before the first paint so a save still writes every pickup name. Icon decode runs off the UI thread, armor rows first, then the rest without adding those rows.
Shared: hunt item table paint only. Pickup mode, `item_pickup_names`, and loot choice are unchanged.
Affects: the hunt Items tab. Other categories show when the user changes the category filter. A category the user already picked is kept across reload.
Consent: user ("yes") after the armor-first proposal.
Result: not run in game.

## 2026-11-09 — shopkeeper arrow drop skips the mage seat

Intent: The shopkeeper still reads the 10-second party bag reports and drops arrows to the first member under the boss threshold. A roster row whose role is mage is no longer a drop target. The party boss is not on that roster, so the boss stays eligible. An unknown name is not treated as mage.
Shared: `pick_arrow_duty` only. Buy quantity, follow, heal, and solo shop are unchanged.
Affects: the shopkeeper's ground drop choice.
Consent: user ("yes") after the mage-seat exclusion proposal.
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-08 — party boss sets arrow give and buy counts

Intent: The party boss supply page already set when a member or the shopkeeper is short. It now also sets how many arrows are dropped to a short member, and how many the shopkeeper buys on one trip. A drop still leaves the shopkeeper reserve. Solo equipment arrow quantity stays the solo shop quantity.
Shared: `pick_arrow_duty` drop size, and `_emit_shop_run` only while `party_shopkeeper_arrow` is set on an arrow behavior. Sell, potions, follow, assist, and solo arrow buy are unchanged.
Affects: party boss 마을 및 보급, and the shopkeeper member that receives the policy.
Consent: user ("yes") after the two-count proposal. Defaults: give 100, buy 200.
Result: `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game.

## 2026-11-09 — loot blink does not hand the tick to search

Intent: A ground pile that drops out of one memory sweep and returns with a new track id used to clear loot, so the next farm tick clicked the search route the other way. The same GUID, item kind, and world cell now keep the loot walk for up to 2 seconds. A new track id replaces `current_item_id` only. The approach hop stays.
Shared: `continue_or_start_loot` only. `TrackIds.prune`, `clear_search_hop`, adena-over-other-item, F4 await, combat sticky, attacks-me, and search route planning are unchanged. Search hop flags `search_hop_active` and `search_waypoint` are cleared without resetting the 5 s unstick sweep. A bag gain, a dead row, a deleted row with no twin, an F4 pause, or 2 seconds without the same pile releases immediately.
Affects: field and dungeon loot when the locked pile blinks. Search runs again only after that release returns None.
Consent: user agreed to the branch-only proposal and the eight extra constraints, then "응. 다시 진행해."
Result: `Engine/app/_04_decision/tests/test_loot_track_hold.py` — 7 passed. Not run in game.

## 2026-11-09 — respawn without Mother Tree heals at the spawn tile

Intent: After revive, an elf with Teleport to Mother still goes to the tree, recovers, then world-navs back to the hunt. A character without that spell used to talking-scroll to a wheel-0 NPC and heal there, then scroll again to the hunt entrance. They now heal on the spawn tile until the existing 95% retreat exit, then the same `post_respawn` world nav runs.
Shared: `arm_post_respawn_retreat` only. The Mother Tree branch and the no-scroll walk-to-safe branch are unchanged. `begin_retreat`, `apply_inplace_hp_support`, `finish_retreat`, field HP safe-zone scrolls, and login clicks are unchanged.
Affects: death revive when Mother Tree is unavailable and a talking scroll is equipped. Field low-HP retreat still scrolls.
Consent: user ("그대로 수정해줘") after the branch-only proposal.
Result: not run in game.

## 2026-11-08 — party shopkeeper supplies arrows

Intent: The roster shopkeeper buys arrows with the existing solo arrow shop when their own count is under the party boss threshold, and drops the shortfall beside a member who is under the member threshold. After the shop, world nav uses the leader's live tile as the goal, including on the same mainland or Talking Island map. The leader does not start an arrow shop while that shopkeeper socket is up, and does not count the shopkeeper as lagging during shop or supply. A dropped socket ends that exclusion immediately and lets the leader's existing arrow shop run. Random closest-member loot stays selectable. Party looters use the boss pickup mode and weight line. The short member picks up the dropped pile.
Shared: `needs_arrow_buy` returns false only when scratch `party_arrow_shop_covered` is set. `choose_shopping_behavior` returns `party_pin_shop_behavior` only when that scratch is set and no shop is already sticky. `apply_cursor_verify_feedback` skips `mark_post_shop_return` only while `party_shopkeeper_arrow` is set. `continue_or_start_loot` and the leader no-loot scratch are unchanged. Sell, HP potion, depoison, HP retreat, login, and combat target choice are unchanged.
Affects: party leader policy and the 마을 및 보급 / 아이템 및 루팅 pages, the shopkeeper member, party loot mode, and the area-hunt line watch. Solo without a party leader is unchanged.
Consent: "좋다. 기능구현을 시작하자. 현재 존재하는 다른 로직과 워크플로는 모두 보존하여야 한다."
Result: unit tests in `Engine/app/_06_party/tests/test_arrow_supply.py`. Not run in game. A ground drop does not click when `Engine/data/supply/inventory_grid.json` is missing or the bag row has no slot.
## 2026-11-08 — party list heal presses once, then clicks

Intent: A party-list heal was pressing the heal key twice and only then clicking the member row. The second press clears the target cursor, so the other member's HP does not rise. A list heal now presses once and clicks that row. A self heal still double-presses.
Shared: `ActionExecutor._heal` / `_press_assigned_skill` only. `apply_hp_actions`, follow, and assist are unchanged.
Affects: mage party-list heal. Solo self heal is unchanged.
Consent: user (the other member's HP did not rise after the heal attempt; resolve that).
Result: not run in game.

## 2026-11-08 — party assist ignores the solo species blacklist

Intent: A party member attacks the monster the leader is attacking even when that species is on the solo blacklist. Self-defense still uses the list. Solo hunting is unchanged.
Shared: `engage_like_solo` gains `ignore_species`. The party member calls it for assist only. `is_avoided_for_state`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member assist.
Consent: user (remove the solo blacklist from party members; always attack the leader's monster).
Result: not run in game.

## 2026-11-08 — leader no longer waits for party members

Intent: Remove every leader stand that exists only because a member has not arrived. The leader still walks to the rally mark, then hunts. Invites keep going.
Shared: `set_party_hold` is cleared every leader tick. Rally arrival no longer enters `waiting`. `LeaderStartRally.should_hold` stays false. The leader-ops spin "가까운 파티원 대기" is gone. Line-lag and nearest-member holds are gone. Member follow, assist, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader hunt after Start, and the leader 사냥 운영 page.
Consent: user (delete the wait-for-members logic from the UI through the decision).
Result: the first start after the removal crashed (`organize_hold` was still read). That leftover read is gone. Not run in game after the fix.

## 2026-11-08 — leader walks to the rally point as soon as the party starts

Intent: Party start arms the rally immediately and the leader walks to the mark. The invite window no longer stands the leader before that walk finishes. The stand at the mark, after arrival, is unchanged.
Shared: `_leader_may_begin_start_rally` and the forming half of `set_party_hold`. Rally wait after arrival, member follow, assist, the post-rally distance hold, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader movement from Start until the leader reaches the mark.
Consent: user (on party start, go to the rally point first; checked against the live log).
Result: not run in game.

## 2026-11-08 — leader distance hold starts after the rally

Intent: The nearest-member stand uses the leader form distance only after the start rally state is `done`. Before that, including the walk to the mark and the rally wait, that stand stays off.
Shared: `_leader_near_hold` only. Rally wait, member follow, assist, solo hunt, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader movement before the start rally finishes.
Consent: user (distance keeping starts only once they have rallied; it must not run before that).
Result: unit checks only. Not run in game.

## 2026-11-08 — leader walks to the rally point before waiting

Intent: During the start rally the leader keeps walking to the hunt mark's center. Entering the rectangle does not start the wait or cancel that walk. The wait starts when the leader is within one tile of that point. Members are still not sent the tile; they follow the leader.
Shared: `PartyLeaderManager.prepare` only. `set_party_hold` still stands once the rally state is `waiting`. Member follow, assist, solo hunt, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader movement from the moment the start rally is armed until the leader reaches the mark point.
Consent: user (fix the rally so the leader goes to the rally point, then members follow).
Result: unit checks only. Not run in game.
## 2026-11-08 — party list heal uses nav tiles

Intent: A mage heals another member, including the party boss, from the party list when that member's `hp_pct` is under 80. The distance check was comparing PartySubsystem world coordinates to the nav tile the follower already uses, so a neighbor looked farther than 9 tiles and the cast never started.
Shared: `in_heal_reach` / `heal_targets` only. Self `apply_hp_actions`, follow, assist, and loot are unchanged. The party log records a `list heal:` line when that note changes (cast, closed list, mp, range, missing row).
Affects: mage party-list heal. Solo heal is unchanged.
Consent: user (resolve the missed heal and log the party decision).
Result: unit check for a raw party position against a nav tile. Not run in game.

## 2026-11-08 — leader waits for the nearest member

Intent: The party leader stands when the nearest same-map member is farther than the leader-page distance. That distance is the form value (`party.near_tiles` → `party_near_tiles`). 5 is only the value when the form is empty. Every known member on another map also waits. A failed party-memory read keeps the previous answer. No readable member does not start a wait.
Shared: existing `set_party_hold` only, OR'd with the area line-hold and rally/invite hold. `LeaderLineWatch`, member formation, assist, solo hunt, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-leader movement while the nearest member is past the setting. The half-party 30-tile area wait is unchanged.
Consent: user (stand when the nearest member is about 5 tiles away; put the distance on the leader page; default 5; keep other behavior untouched).
Result: unit checks only. Not run in game.

## 2026-11-08 — party formation slots are the walk goal

Intent: A moving member walks to a side-by-side slot (right, then left, then farther). A narrow trail tile replaces that line. A stopped leader, including a standing fight, uses a 3×3 grid for up to five followers and a 5×5 grid for more. The click is a hop of at most 2 tiles toward that absolute tile. Leader pose stays a successful memory read. No websocket pose.
Shared: `choose_formation_goal`, `decide_policy` when `slot_dist` is set, `plan_slot_hop`. Distance-to-leader hold remains only when no slot is supplied. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Assist still fires when the leader's mob is in range.
Affects: party member follow and hold. Solo hunt is unchanged.
Consent: user (implement the guide's formations; memory pose, not websocket).
Result: unit checks only. Not run in game.

## 2026-11-08 — leader pose comes from this tick's memory read

Intent: Follow and stop use the PartySubsystem pose only when this frame's memory read succeeded. A failed read keeps the old snapshot for diagnostics and does not refresh its time or sequence. No websocket leader pose.
Shared: `apply_perception_buffer`, `resolve_leader`, `_apply_sticky_party_pose`, `_leader_is_moving`. The cached tile is not copied back onto the live view. An in-flight map join keeps its last armed destination across one missed read. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party member follow, leader moving/stopped, and join retarget. Solo hunt is unchanged.
Consent: user (fix position judgment from memory; do not use the guide's websocket pose).
Result: unit checks only. Not run in game.

## 2026-11-08 — leader forwards party reports to the shopkeeper

Intent: Every `HEARTBEAT_S` the leader sends the latest member `report` frames plus its own report (same `build_report` shape) to the roster shopkeeper only.
Shared: follow, combat, heal, and loot are unchanged. `MemberOrders.party_reports` holds the bundle on the shopkeeper. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader send and the shopkeeper member mailbox. Other members do not receive the bundle.
Consent: user (send every member report, including the leader, to the shop member, on the report interval, using the same variable).
Result: not run in game.

## 2026-11-07 — party assist uses the solo shot line

Intent: A member still attacks the monster the leader is attacking. The click now goes through the solo combat tick, so a fence or a closed tile holds or detours instead of shooting through it.
Shared: `continue_or_start_combat`, `attack_line_clear`, `begin_engage`. Follow, heal, and loot are unchanged. The member does not pick a different monster.
Affects: party member assist and self-defense. Solo hunt is unchanged.
Consent: user asked to check and fix assist so it uses solo attack logic.
Result: not run in game.

## 2026-11-08 — party assist reuses the solo shot gate

Intent: A party member clicked the leader's monster through the inn wall. Target choice stays the party picker. The click is refused when solo's locked-target gate says the shot is closed.
Shared: `intent_for_kind` for `ASSIST` calls `assist_shot_gate`, which calls `sticky_target_alive` and `can_engage_target`. A closed line or a click-range miss becomes idle and keeps the same id for the next party tick. No new target, no wall detour. `list_attackable`, follow, loot, defend, and the solo attack path are unchanged.
Affects: party member assist clicks (`leader_attack`, `leader_strike`, external, `own_finish`, solo-farm assist). Self-defense still emits its own attack.
Consent: user (keep party target selection, reuse the solo attack check immediately before the click).
Result: unit tests in `Engine/app/_06_party/tests/test_assist_shot_gate.py`. Not run in game.

## 2026-11-08 — safe-zone scroll waits until HP is almost full

Intent: After a talking-scroll landing with no heal and no potion, the retreat ended as soon as HP crossed the retreat line (30%). The character scrolled back to the hunt with the bar still near a third.
Shared: `resume_hunt_above_retreat_limit` stays quiet while that HP-safe scroll is in flight or its landing is confirmed (`hp_safe_regen`). `retreat_exit_ready` then uses `is_almost_full_hp` (95%). A scroll that times out never sets the mark, so the 30% exit remains in the hunt. `begin_retreat`, `apply_hp_actions`, mother-tree, MP retreat, and login clicks are unchanged.
Affects: HP retreats that land on a wheel-0 safe-zone scroll. Return to the hunt waits for 95%, including when heal exists but MP is under 20. Walking to a safe area without the scroll still leaves at the retreat line.
Consent: user (wait at the safe zone until HP reaches 95%, without colliding with the other retreat exits).
Result: not run in game.

## 2026-11-07 — party mage skips a dead or out-of-reach member

Intent: A party mage does not press heal for another member at 0% HP, on another map, or farther than 9 tiles (Chebyshev). The next living member under 80% HP who is inside that reach is still chosen. Self heal, self buff, a potion, and self-defense stay ahead of the list heal.
Shared: `heal_targets` / `in_heal_reach` in `hud_heal.py`. `PartyMemberManager._party_list_heal` passes the mage tile and map, and emits nothing when that pose is missing. Attack `MAGE_SPELL_RANGE` stays 10. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member mage list heals only. Other classes, solo mage, and the party leader's farm columns are unchanged.
Consent: user (skip dead and out of heal reach; heal reach base is 9).
Result: unit check in `Engine/app/_06_party/tests/test_hud_heal.py`. Not run in game.

## 2026-11-07 — party mage clicks the list row to heal

Intent: After a party mage picks another member under 80% HP, the heal key is pressed and that member's left-list row is clicked. The lowest percent is first. Self heal, self buff, a potion, and a monster that is hitting this mage still come first. Assist stays off for a mage.
Shared: `PartyMemberManager._party_list_heal` emits the click. `ActionExecutor._heal` clicks only when the intent carries client pixels and the heal key was pressed. Key-only heals stay a key press. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party-member mage ticks that are not self-heal, self-buff, potion, or self-defense. Other classes do not take this click. The party leader's own farm columns are unchanged.
Consent: user (party mage clicks the chosen left-list row; assist for a mage stays off except when this mage is attacked).
Result: unit check in `Engine/app/_06_party/tests/test_hud_heal.py`. Not run in game.

## 2026-11-07 — a mage party member does not assist

Intent: A party member whose character is a mage does not take an assist target. Knight, elf, and royal members still assist the leader. Follow, hold, heal, buff, and potions stay. `defend_self` still fights a monster that is hitting this mage.
Shared: `PartyMemberManager.decide` drops the chosen target after `pick_assist_target`, solo-farm pick, and turret own-hunt, when `mage_skips_party_assist` is true. `pick_assist_target`, `pick_solo_farm_target`, `turret_member_focus`, and `decide_policy` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party member assist for a mage, including leader attack, leader strike, solo-farm targets, and turret own-hunt. A sticky assist ends on the next tick. The party leader's own farm columns are unchanged.
Consent: user (mage party members do not assist; other classes still assist; defend when this mage is attacked stays).
Result: unit check in `Engine/app/_06_party/tests/test_mage_skips_assist.py`. Not run in game.

## 2026-11-07 — a stuck mage spell circle is clicked or cancelled

Intent: Once the cast circle is on a monster, that pixel finishes the cast. `spell_out_range` and `spell_disable` cancel the circle and do not count as the 4-second cursor drop. Walking keeps cancelling: Esc, then one right-click on the current pixel if the circle remains.
Shared: `find_attack_aim_point`, `MageCombatStrategy.attack`, `cancel_spell_aim`, and the travel click loop. Elf, knight, and royal weapon aim, spell range, heal, teleport, party, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. A fist or sword miss still drops the target after five rejects.
Consent: user (click a live spell circle; cancel an out-of-range circle without dropping the target; Esc then right-click while walking).
Result: unit check in `Engine/app/_05_action/tests/test_spell_aim_hold.py`. Not run in game.

## 2026-11-07 — solo mage attack spells rotate one press each

Intent: A solo mage in spell mode casts each checked attack spell once, in priority order, then repeats. A tick that never presses the key keeps the same spell.
Shared: `solo_mage_attack_fields` picks the due cell. `note_solo_mage_attack_pressed` advances only after `MageCombatStrategy` presses that key. `continue_or_start_combat` still only adds the hotbar fields. Buffs, party, other classes, spell range, cursor aim, cast gap, heal, teleport, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the attack key of a solo spell-mode mage. One spell on the hotbar still repeats. No checked spell on the bar still uses `mage_attack`.
Consent: user (checked attack magic, one cast each, in order; advance only after the key press).
Result: unit check in `Engine/app/_04_decision/tests/test_solo_mage.py`. Not run in game.

## 2026-11-07 — schedule attack mode follows the account class

Intent: A mage account was stored with `hunt.attack_mode` `ranged`, so spell buffs and cast never ran. The account class now chooses the hunt method: mage `magic`, elf `ranged`, knight and royal `melee`. A saved hunt value no longer overrides that.
Shared: `attack_mode_for_character`. `apply_runtime_settings` writes that value onto the profile. `profile_snapshot` and schedule save stamp the same value. `combat_strategy_for` is unchanged: only a mage is remapped by the mode. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the next start of a mage schedule uses the spell path. An elf schedule stays on bow clicks. Knight and royal combat strategies still ignore `attack_mode`.
Consent: user (mage account runs mage workflow; a ranged class stays ranged).
Result: unit check in `Engine/settings/tests/test_attack_mode.py`. Not run in game.

## 2026-11-07 — walk component stamp is not refreshed on launch

Intent: A bot launch was rewriting every `walk_components/meta.json` when `nav.png` mtime differed and the bytes did not. The hash already accepts that file, so the launch no longer writes a new `source_mtime_ns`.
Shared: `try_load_components` and `load_or_build_components` still load a matching cache. `_write_component_cache` still runs when the cache is missing or the bytes differ. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: map load of white-tile component ids. A copied `nav.png` with the same hash is read and left on disk as-is. A changed `nav.png` still rebuilds the cache, including `source_mtime_ns`.
Consent: user (stop unnecessary `source_mtime_ns` updates).
Result: not run in game. The next launch should leave existing `walk_components/meta.json` files unmodified when `nav.png` bytes match.

## 2026-11-07 — solo mage casts checked buffs before the next target

Intent: A solo mage in spell mode uses the individual magic table. Checked lasting buffs go out in priority order before a new fight, and only after memory shows the effect above the existing 10s remain. A live sticky target keeps being attacked. Checked attack spells on the hotbar replace the cast key in the same order; a missing hotbar cell is skipped, and no checked attack spell on the bar keeps `mage_attack`. Three presses that never produce the buff park that skill for 30s. MP at or under the reserve does not wait on the buff.
Shared: `maybe_cast_buff` is unchanged and still used for other classes and for a party leader (`party_leader_no_loot`). `continue_or_start_combat` only adds hotbar fields when `solo_mage_active`. `MageCombatStrategy` presses that cell when the intent carries one, otherwise `mage_attack`. Heal, teleport, spell range, cursor aim, cast gap, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: solo mage spell-mode buff step and the attack key. Party member, party leader, elf, knight, and royal stay on the previous buff and `mage_attack` paths.
Consent: user (solo mage only; checked skills in priority; buff before a new target; memory remain; retry cap; hotbar miss skips; keep range, cursor, interval, heal, teleport, and party).
Result: unit tests in `Engine/app/_04_decision/tests/test_solo_mage.py`. Not run in game.

## 2026-11-07 — solo selector turns the party switch off

Intent: The party checkbox is hidden. 솔로봇 must hunt the solo schedule. Party runs only after 파티봇 and a role choice.
Shared: `set_master_enabled` is the old `party.enabled` flag. Opening the party page no longer checks it. Choosing 파티장 or 파티원 checks it. 솔로봇 and both solo start paths uncheck it before the profile overlay. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: solo start, schedule handover, and party start. A saved leader role no longer arms the party brain while 솔로봇 is selected.
Consent: user (the selector replaces the checkbox; party runs after leader or member is chosen).
Result: not run in game. The next solo start should log `enabled=OFF` and use the solo schedule.

## 2026-11-06 — exp mirror moved to the live BSS double

Intent: exp percent stayed 0 while the character window was closed, because `ExperiencePct64` still pointed at `0x1644BF0`.
Shared: the registry key and `offsets.json` now use `0x1641B00`. That slot has the level qword at -8 and the lagging double at -0x10. The monitor DLL already reads this key at startup. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the income-bar exp percent and the `exp=` field on sticky release. A process that already loaded the monitor keeps the old address until it starts again.
Consent: user (read exp from memory with the character window closed).
Result: one live hit, level 12, moving double 66.951386, twin 68.786915. The pair did not move during a 3s idle sample. Not run through a bot restart.
## 2026-11-06 — Hangul invite treats a Chinese IME as not Hangul

Intent: `IME_CMODE_NATIVE` is also the Chinese IME's 中 mode. A game thread on `0804`, `0404`, or `zh-HK` must not be logged as `hangul=on`, and jamo must not be sent into that IME.
Shared: `ec_ensure_hangul_mode` reads the game thread language after the Korean layout request. A Chinese layout gets one more Korean request. If it is still Chinese, the line stops with `ime=zh-CN` (or `zh-TW` / `zh-HK`) and `hangul=off`. The 한/영 key runs only when the layout is Korean. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party invite lines that contain Hangul while the game input is a Chinese IME.
Consent: user (check the Chinese IME as well).
Result: `enter_chat.dll` rebuilt. Not run in game. The leader process must be restarted.

## 2026-11-06 — Hangul invite follows the language bar, not only HKL 0412

Intent: The first `/초대` lines reported success while Korean did not compose. After the language bar was cycled between Korean and English (United States), the same keys composed. Thread layout `0412` is both 한 and 영, so the prepare step treated English as ready.
Shared: `ec_ensure_hangul_mode` in `ec_hangul.c` selects the installed ko-KR input processor, asks the game window for that layout, and reads the conversion mode back. It presses the 한/영 key once only when the mode still reads as 영. A confirmed 영 after that press aborts the line. An unreadable mode is left untoggled and logged as `hangul=?`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Invite-accept Y still forces English.
Affects: party invite lines that contain Hangul, and any other `ec_run` text with Hangul.
Consent: user (make the Hangul switch follow whichever input the language bar is on).
Result: `enter_chat.dll` rebuilt. Not run in game. The leader process must be restarted. The invite log now includes `hkl=.... hangul=on|off|?`.

## 2026-11-06 — Hangul invite switches the game IME before the jamo keys

Intent: `/초대` reported `chars=11 keys=13` while the syllables never composed. The jamo keys were already on Interception. `ffa920b` (2026-11-03) had replaced the layout switch with one `PostMessage` and a 120ms sleep, and it no longer retried `한` mode after focusing the game.
Shared: `ec_hangul_prepare` in `Engine/app/_06_party/enter_chat/src/ec_hangul.c` is the 2026-11-02 path again. It focuses the game, attaches to the game thread, and waits until layout `0412` sticks. If the default IME window does not enter `IME_CMODE_NATIVE`, it focuses the game and asks once more. A failed layout switch returns `EC_E_IME` and sends no jamo. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party invite lines that contain Hangul, and any other `ec_run` text with Hangul. Invite-accept Y still forces English and does not use this path.
Consent: user (restore the Hangul switch and record it in the docs and the enter_chat README).
Result: `enter_chat.dll` rebuilt from this source. Not run in game. The leader process must be restarted to load the new DLL.

## 2026-11-06 — two extra offset names removed

Intent: `entities/settings_print_state.json` and `inventories/inventory_offsets.txt` were second names for the registry copies. Drop those names without rebuilding a DLL.
Shared: `attacks_me` keeps cell offsets from `registry/settings_attacks_me.json`. `hotbar_listen` falls back to `registry/inventory_offsets.txt`. `print_state.dll` and `analysis/char_offsets.txt` stay. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: attacks cell overlay and hotbar item-name offsets. Both still read the registry file.
Consent: user (remove only the two names that do not need a rebuild).
Result: the two names and their empty folders are gone. Registry copies remain. Not run in game.

## 2026-11-06 — analysis folder reduced to the live readers

Intent: `Engine/analysis` held both the live listen modules and the old lcapi modules. Keep the files the bot opens, and keep the recovered listen sources so a later rebuild can write the same DLL names.
Shared: In-process sources moved from `analysis/old` to `analysis/src/listen`. Their build scripts write `analysis/dll`. `lc_session` starts `party` only. Stair list path is `analysis/data/dungeon/floors_entrances.txt`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party roster still uses `dll/party.dll`. Player, bag, shop, buff, dialog, attacks, and warehouse still use the listen DLLs and `registry/`. Three names stay outside the six folders because the current DLLs open them: `char_offsets.txt`, `entities/settings_print_state.json`, `inventories/inventory_offsets.txt`.
Consent: user (clean the analysis directory as discussed).
Result: unused lcapi DLLs, exes, and sources removed. `storewin_build.dll` has no C source. Listen sources were not recompiled. Not run in game.

## 2026-11-06 — vitals no longer read the charread sample

Intent: The income bar and action view still decoded HP, level, and exp from the charread module text. That module is not started.
Shared: `body_pose.read_vitals` and `read_progress` read the `player` block from the live `realtime_monitor` snapshot. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the income bar level and exp, and the action-view HP line.
Consent: user (update every remaining old memory read).
Result: not run in game.

## 2026-11-06 — remaining readers open dll and bin

Intent: The player monitor, bag UI, shop debug, dialog watch, and contested probe still started the old module DLLs. Optional exe launchers still looked beside `analysis/` and in `inventories/`.
Shared: Those imports now open `dll/realtime_monitor.dll`, `inventory_listen.dll`, `hotbar_listen.dll`, `shop_listen.dll`, `buff_listen.dll`, `uidialog_listen.dll`, `attacks_me.dll`, and `contested_mobs.dll`, with settings from `registry/`. `realtime_monitor_full.exe` and `inventory_listen.exe` are launched from `analysis/bin`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the UI player chip, bag and equipment reads, shop debug rows, dialog watch, and the contested probe.
Consent: user (open the memory modules from the sample folders).
Result: imports resolve to `dll/` and `bin/`. Not run in game.

## 2026-11-06 — storewin and party readers use dll and registry

Intent: Warehouse and party registry routes still opened `NPC_conv` and `lc930`. Those reads should use the same `dll/` and `registry/` folders as the other memory readers.
Shared: `storewin_reader` opens `dll/storewin_build.dll` and `registry/LC930_REGISTRY.txt`. `dll/storewin.dll` stays the lcapi module. `party_listen_reader` still starts `dll/party.dll`; its registry helper now uses `registry/LC930_REGISTRY.txt`. `registry_apply` no longer copies that file into `lc930` or `party`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: warehouse window list, and where a party registry overlay would be written.
Consent: user (match memory modules and reader routes to the folder structure).
Result: `storewin_build.dll` loads and exports `storewin_snapshot`. Not run in game.

## 2026-11-06 — analysis runtime files follow the module folders

Intent: Keep every current analysis file, and place the bot's runtime pieces in the same folders as `11-4analysis`: DLLs in `dll/`, programs in `bin/`, offset tables in `registry/`.
Shared: The listen and print_state readers, `body_pose`, and `registry_apply` now open those paths. `dll/party.dll` and `registry/LC930_REGISTRY.txt` stay. Hard links remain at `char_offsets.txt`, `offsets.json`, `entities/settings_print_state.json`, `entities/entity_offsets.txt`, and `inventories/inventory_offsets.txt` because those DLLs also open the old relative names. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: where player, entity, bag, hotbar, shop, buff, dialog, and attacker files are loaded from.
Consent: user (match the 11-4 folder shape and update the reader paths).
Result: readers load the DLLs from `dll/`. Not run in game.

## 2026-11-06 — dialog reader uses the live registry

Intent: The talking-scroll open check always timed out. The dialog DLL looked for `analysis/lc930/registry/LC930_REGISTRY.txt`, which this branch does not have, and the constructor returned without an error.
Shared: `fix_uidialog_listen_reader` and `fix_buff_listen_reader` now pass `analysis/registry/LC930_REGISTRY.txt`. That file already has `UIDLG_WIN_TalkingScroll`. A missing DLL or registry is written on the perception error list. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: talking-scroll, shop, storage, and buff open checks.
Consent: user (point the dialog reader at the registry that exists).
Result: not run in game.

## 2026-11-06 — party ticks use the solo memory readers

Intent: A party session should read player, map, entities, bag, hotbar, buffs, dialog, attacks, and contested the same way a solo session does. The party roster stays on the current party module.
Shared: `PerceptionSensors` always loads `realtime_monitor.dll`, `print_state.dll` with HP/MP/level left on the snapshot, and the fix inventory, hotbar, shop, buff, dialog, attacks, and contested DLLs. It calls `session.stop()` so charread, map, enttrack, bodyact, and the other module loops are not started. `capture_tick(party=True)` still starts `party.dll` through `PartyListenReader`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. Raspberry input is unchanged.
Affects: party leader and member HP, map id, bag, hotbar, buffs, dialog, and attacker samples. Party roster, follow tile, and leader stats stay on the party module.
Consent: user (party memory reading matches solo; keep the current party roster read).
Result: not run in game.

## 2026-11-06 — solo memory uses the single-version readers

Intent: The module pause made every hunt tick wait about half a second, so the character stood between clicks. Solo memory should be the same in-process reads as `fix/single-version`, and that pause comes out.
Shared: `PerceptionSensors(party_modules=False)` loads `realtime_monitor.dll` (MapSubsystem `0x1228960`, `MapIdOff` `0x718`), `print_state.dll` with HP/MP/level left on the snapshot, and the fix inventory, hotbar, shop, buff, dialog, attacks, and contested DLLs. It calls `session.stop()` so charread, map, enttrack, bodyact, and the other module loops are not started. `body_pose.read_action` stays the direct slot read. Party sessions still construct the module readers and still drop print_state vitals so charread remains their HP source. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Raspberry input is unchanged.
Affects: solo HP, map id, bag, hotbar, buffs, dialog, and attacker samples. Party hunt keeps the module path.
Consent: user (solo memory matches the single branch; remove the pause; leave party modules).
Result: not run in game. The pause no longer wraps `print_state_snapshot`.

## 2026-11-06 — print_state snapshot parks the module loops

Intent: The solo click should be taken while `print_state.dll` is the only driver read, which is how `fix/single-version` builds `iscr`. On this branch the charread, map, inventory, hotbar, buff, dialog, shop, and party loops stay inside `lcapi_run` across that call.
Shared: `LcSession.exclusive_read` parks each live module at its next sample boundary (0.6s cap) around `PrintStateReader.snapshot`. HP, MP, and level still come from charread on the other ticks. Map, inventory, hotbar, buffs, shop, dialog, and party stay on their modules. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Raspberry input is unchanged.
Affects: entity click points, and tick length when a module is mid-sample (up to 0.6s). A module that misses the cap keeps its current read.
Consent: user (pause the module loops only for the print_state snapshot so the click frame matches the single branch).
Result: not run in game.

## 2026-11-06 — body slot is read directly, enttrack stays off solo ticks

Intent: Solo hunt should follow the same body pose and entity snapshot as `fix/single-version`. The bodyact module kept the last action across empty samples, so a ground click waited until stop (428 clicks). enttrack was also polling beside `print_state` on every solo tick.
Shared: `body_pose.read_action` now walks ActionComponent+0xC8 the same way as fix. `read_vitals` and `read_progress` still use charread. `capture_tick` starts the enttrack attacks/contested readers only when `party=True`. Solo attackers still come from the print_state `atk` / `tgt` fields. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Inventory, hotbar, map, buffs, shop, dialog, party, and the raspberry input stay on their current paths.
Affects: ground-click waits (search, loot hop, wall detour) and the solo perception tick. Party assist still receives `last_contested_mobs`.
Consent: user (match the single-branch body read and keep enttrack off the solo snapshot; leave the other modules).
Result: not run in game.

## 2026-11-06 — entity clicks use the print_state DLL

Intent: Farm clicks should use the same screen point as `fix/single-version`. Rewriting `enttrack` `iiso` with the print_state formula still left the cursor on `fist` at 0.737 and `arrow` on the ground. The entity frame now comes from `print_state.dll`, `settings_print_state.json`, and `entity_offsets.txt` (`ANCHOR_DV=0`).
Shared: `PrintStateReader.snapshot` is the only new call. `entities_to_handoff` still reads `iscr`. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. HP, MP, and level are stripped from the print_state player object so charread stays the vital source. Map id still comes from the map module. Inventory, hotbar, buffs, shop, dialog, and party stay on their modules.
Affects: monster and item click points, and the on-screen test that uses those points.
Consent: user (click coordinates from the single-branch print_state snapshot; keep the other memory modules).
Result: the DLL loads and exports `print_state_snapshot`. Not run in game.

## 2026-11-06 — attack click uses print_state's anchor 0

Intent: The working `print_state` click is not the registry's `ANCHOR_DV=24`. `settings_print_state.json` and `entity_offsets.txt` on `fix/single-version` both set `ANCHOR_DV=0`, and the offsets file is loaded last. The 24-pixel shift put the cursor above the sprite, so the probe saw `fist` at 0.737 and then an `arrow` on the ground.
Shared: `lc_view._click_iscr` still rewrites `iscr` from `iiso`, with the same `PPS` and `VP_DX` / `VP_DY`. Anchor stays 0. The client width and height come from the live LC window, which is the rectangle `print_state` projects into. A row with no iso uses the cell fallback `du=48*(dx+dy)`, `dv=24*(dx-dy)`. Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Map id is unchanged.
Affects: farm attack and loot clicks that use memory `iscr`.
Consent: user (fix the click pixel so it matches the single-branch point).
Result: 800×600, one tile east, the click is y=224. Not run in game.

## 2026-11-06 — attack click uses the print_state screen anchor

Intent: A monster click should land on the body, where the attack cursor matches, the same way `print_state` places `iscr` on `fix/single-version`. enttrack was centering the iso delta on the viewport and leaving out `ANCHOR_DV`.
Shared: `lc_view._entity_rows` rewrites `iscr` from each row's `iiso` and the registry anchor (`REF_W`, `REF_H`, `PPS`, `VP_DX`, `VP_DY`, `FEET_*`, `ANCHOR_*`). Cursor labels, the 0.98 score, `loot_hop`, and `combat` are unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. Map id is unchanged.
Affects: farm attack and loot clicks that use memory `iscr`. A row with no interpolated iso keeps the module point.
Consent: user (align the click point with the single-branch screen anchor; leave the cursor rule).
Result: 800×600, one tile east, the click is y=212 instead of the viewport y=224. Not run in game.

## 2026-11-06 — body pose stays, and address fallbacks match the registry

Intent: Solo loot and monster clicks on this branch should see the same body pose and entity classes as `fix/single-version`, while the `analysis/dll` modules, `lc_session`, and `LC930_REGISTRY.txt` stay the reader. The registry already has Breath `0x11E0550`, monster `0x11E1240`, item `0x11E1198`, and `AC_ACTION_OFF` `0xC8`. A bodyact sample is empty on ticks where the pose did not change, and that empty text was replacing the last real row, so stand/walk read as missing.
Shared: `body_pose.read_action` still returns the bodyact pair, and `loot_hop._body_settled_for_f4` and the ground-click repeat still consume it. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks were not edited. `party_leader_no_loot`, turret, and rally wait were not edited. Map id still comes from the map module and `offsets.json`, not from these fallbacks.
Affects: loot F4 and ground clicks once a body row has been seen. Entity and action fallbacks in `lcore.h` and `body_pose.py` match the registry when a key is missing. The loaded DLLs already apply the registry at startup, so those header defaults take effect on the next DLL build.
Consent: user (keep the memory-module structure; align fallbacks and the pose feed; do not change loot, combat, movement, retreat, or HP decisions).
Result: empty bodyact samples keep the last row. Baked labels use the registry RVAs. Not run in game.

## 2026-11-05 — merge main, keep party analysis and raspberry

Intent: Bring main onto this branch again. Party, the cleaned analysis module, and the Raspberry Pi input stay on this branch. Solo bot changes take main.
Shared: `arm_loot_side_intent` still skips loot when `party_leader_no_loot` is set, and it keeps main's sticky-loot guard. `body_pose` still reads the analysis registry. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks were not edited by hand.
Affects: solo loot, world nav, and shops follow main. Party, analysis DLLs, and Raspberry input stay as they are on this branch.
Consent: user (remerge; party, analysis, and raspberry win; solo bot takes main).
Result: merge resolved that way. Not run in game.

## 2026-11-04 — turret hunting is the party-map point

Intent: The turret/moving combo is not a setting. The leader turrets only while standing on a point marked on the party map. The anchor is that point. An area is a moving hunt. Travel and a map-only row are not turret. Members hear the same mode through party policy. Lag wait runs only inside an area. Rally wait still holds the hunt; when it ends on a point, turret turns on.
Shared: `set_party_turret`, `step_party_turret_leash`, `step_party_turret_idle`, `PartyLeaderManager.prepare`, `party_policy` `leader_mode`, `_leader_line_hold`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged. A member's solo farm setting stays its own.
Affects: party leader hunt at a mark, member yard while the leader is on a point, and the party tab.
Consent: user (remove the turret switch; a map point is always turret).
Result: party schedule unit test passed. Not run in game.

## 2026-11-04 — party leader does not loot; members follow the loot policy

Intent: The party leader never picks up. Members loot only from the leader policy. Random loot: the closest member except the leader and the wizard takes the party drop, and a name tie goes to the earlier name. Random off: a roster row marked responsible takes its own drops; none still takes nothing. Members do not loot while the leader is moving. Follow-versus-loot priority is gone. A member's solo farm setting does not change who loots.
Shared: `continue_or_start_loot` and `arm_loot_side_intent` skip loot when `party_leader_no_loot` is set. Solo start does not set that flag. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: party leader farming and member pickup. Solo loot is unchanged.
Consent: user (leader must not loot; members follow leader policy; drop the priority setting).
Result: party loot policy test passed. Not run in game.

## 2026-11-04 — item $id names prefer the Korean table

Intent: hotbar and bag item names use the Korean column of `item_name_kr.csv` for a `$mid`, the same order as 11_04 `hotbar_930`. `desc*` / `string*` / empty cells fall through to the memory string. Spell text on the slot is unchanged.
Shared: `itemNameKr` in the hotbar nametable and `inventory_listen` `msgNameStatic`. HP potion matching, hotbar roles, and bag name checks read those names. Movement, combat selection, retreat, and login are unchanged.
Affects: hotbar item labels and inventory `name`. A Chinese account still receives the Korean item column. Shop and storage readers still use the memory string.
Consent: user (apply the 11_04 Korean item-name lookup to this project).
Result: table copied to `Engine/analysis/data/item_name_kr.csv`. `hotbar_listen.dll` and `inventory_listen.dll` rebuilt. Lookup checked for 아데나, 체력 회복제, 가죽 재킷, 해독제, 말하는 두루마리. Not run in game.

## 2026-11-04 — memory offsets synced to 11_04 registry v36

Intent: point the existing memory readers at the 2026-11-04 client anchors. Read order, struct offsets, and decision code stay as they are.
Shared: `LC930_REGISTRY.txt` (129 keys), `char_offsets.txt`, `entity_offsets.txt`, `offsets.json` (`MapSubsystemVftRva`, `PosXAbs`/`PosYAbs`), inventory and hotbar tables, `body_pose.py` action vfts, `shop_listen.c` anchors. `STAT_*` fields are +0x20. `K_MUL`/`K_XOR`, `MAP_ID_OFF` 0x718, `AC_ACTION_OFF` 0xC8, and `ST_BLOCK` are unchanged. `STRINGS_CSV` path and `UI_BFS_*` stay. `EntCtrl*` in `offsets.json` was not remapped.
Affects: position, map id, HP/stats, entities, inventory, hotbar, buff, shop, body pose. Movement, combat, retreat, loot, and login logic are unchanged. Chat line layout and the EXP mirror global are unchanged. Party registry copies were not on the live path and were left as v35.
Consent: user (apply the constant-only update; do not change read logic).
Result: constants written. `shop_listen.dll` must be rebuilt before shop reads the new anchors. Other readers load the tables at startup. Not run in game.

## 2026-11-03 — party leader schedule is separate from the solo routine

Intent: When a party leader starts, the hunt map, mark, and row minutes come from `party_routine` only. The solo routine cursor is not installed and `profile.routine` is not read. The existing travel session still walks one party destination. On arrival the party marks are mounted as this session's farm. Rally wait starts at that mark.
Shared tools left in place: `DecisionManager.decide`, `goal_for_entry`, `apply_routine_entry_runtime`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks. Solo start still installs `profile.routine`.
Affects: party leader travel, hunt zone, row timer, and where the start rally waits.
Consent: user (independent party schedule, separated from solo).
Result: party schedule and rally unit tests passed. Not run in game.

## 2026-11-03 — party assist uses the solo hunt range

Intent: A member attacks from the current tile when the solo hunt range already reaches the monster. Bow and melee use the on-screen click range. Spells use the mage cast range. Out of that range, the member follows the leader and does not walk up to the monster.
Shared: `assist_in_attack_range`, `decide_policy`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, and the 2/3 follow band stay as they are.
Affects: party member assist, including turret and solo-farm targets. Solo `DecisionManager` combat is unchanged.
Consent: user (help in place when in hunt range; follow when not).
Result: out-of-range policy test passed. The unused walk-to-monster path (`CLOSE_IN`, `plan_close_in_intent`) was removed on review. Not run in game.

## 2026-11-03 — members follow the leader tile, not a rally pin

Intent: The leader still walks to the static meet point and waits. The rally tile is no longer sent to members. A member follows the leader's live party-memory tile once `in_party` is true, whether or not a rally frame arrives.
Shared: `Rally.arm`, `MemberOrders.ingest`, `PartyMemberManager._maybe_hunt_gather`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, assist order, and the 2/3 follow band stay as they are.
Affects: party start. The leader still finishes the wait from party-memory positions within 7 tiles, or after the existing timeout.
Consent: user (remove the rally destination message; members follow from memory).
Result: rally no-send test passed. Not run in game.

## 2026-11-03 — member follow stays within one tile of the stop band

Intent: While the leader is walking, the member starts at 3 tiles and holds at 2. `follow_tiles - 2` no longer delays the start. A follow click is at most 2 tiles. A fresh party pose uses that same band on screen or off. The 15s/45s sticky tile is not a follow goal.
Shared: `follow_kind`, `decide_policy`, `plan_field_follow`, `plan_follow_intent`. Assist still runs before follow. Heal, buff, leader line hold, and movement cancel stay as they are. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks stay as they are.
Affects: party members following a leader. A follow click can no longer hop 5 tiles. Solo travel hop length is unchanged.
Consent: user (go).
Result: close-follow test passed. Not run in game.

## 2026-11-03 — party rally is a static point before the farm

Intent: The party meets at one fixed tile, then goes to the farm. A walk-only route uses the leader's current tile. A route with an NPC teleporter or a talking scroll uses the departure tile of the first of those steps. The point is not moved to the teleport landing.
Shared: `LeaderStartRally.on_plan`, `LeaderStartRally.should_hold`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, and `PartyMemberManager.decide` stay as they are. A member still pathfinds to the announced tile.
Affects: the leader's start rally. After the wait, the existing route continues to the farm. The 10 minute wait is unchanged.
Consent: user (update with the rally rule above).
Result: rally point test passed. Not run in game.

## 2026-11-03 — turret members hunt while the leader is idle

Intent: While turret is on and the leader is not attacking, members hunt inside the yard or loot. When the leader attacks, a member finishes the mob already started, then assists.
Shared: `PartyMemberManager.decide`, `turret_member_focus`, `pick_solo_farm_target`. The elf leader zone stays leash plus attack range. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, and solo `DecisionManager` stay as they are.
Affects: turret party members. Moving hunt is unchanged.
Consent: user (go).
Result: focus rule test passed. Not run in game.

## 2026-11-02 — party leader decide is its own module

Intent: The party leader was the solo bot plus the solo schedule. The leader tick now goes through `PartyLeaderManager`, and that module installs `party_routine` only. Solo `DecisionManager` and `profile.routine` are unchanged.
Shared: session Start branches on role. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `PartyMemberManager.decide` stays as it is.
Affects: a party leader Start. A solo Start and a member Start keep their current routine.
Consent: user (update).
Result: party routine arm test passed. Not run as a live leader Start.

## 2026-11-02 — party monitor stop/start no longer re-enters a memory DLL

Intent: Stop with the party monitor open, then Start, killed the process. The monitor's next poll cleared the module stop and called `lcapi_run` again while that DLL was still leaving the previous run.
Shared: `LcSession.stop` / `ensure`. A new run starts only after that module's thread has returned. The monitor BitBlt keeps full 64-bit GDI handles. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party monitor left open across Stop and Start.
Consent: user (fix perfectly).
Result: session overlap test passed. Not run as a live stop/start.

## 2026-11-02 — invite Y falls back to SendInput when no keyboard slot accepts

Intent: The member log showed the popup, then `slots rejected` and no Y. PostMessage is not a press the popup reads, so a missing Interception slot must use a real SendInput scancode for Y and for the Enter after it.
Shared: `ec_sendinput_press`. Enter is still skipped when that press fails. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite Y on a PC whose Interception slots reject the probe. The member bot must load this DLL.
Consent: user (Y is never pressing).
Result: DLL rebuilt. Not run on the member PC.

## 2026-11-02 — Y uses a live keyboard slot; a missed key does not press Enter

Intent: The invite popup closed because Y never reached the game and Enter still dismissed it. A `/초대` line was logged as typed when the strokes went to whichever window was in front.
Shared: `ec_ic_open` keeps the first keyboard slot whose key-up send returns 1. `ec_run` skips Enter when any key failed, and Escape-closes a chat line it had opened. A line is a failure when the game is not the foreground window. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. The 20s invite clock is unchanged.
Affects: party `/초대` and invite Y. The running bot keeps the old DLL until it is restarted.
Consent: user (update).
Result: DLL rebuilt. Not run as a party join.

## 2026-11-02 — reconnect resumes from game memory, not a new invite

Intent: A member socket drop is not a failed party join. On reconnect the leader waits for a new `member_state` before another `/초대`. A name already in party memory stays joined. `InviteAccepter` keeps watching the popup across the drop and does not press Y until the policy names the inviter.
Shared: `MemberStates.hold_until_fresh` on the dropped socket id. `LeaderInvites` 20s clock and `InviteHold` stay. Reconnect wait is 2s plus jitter, capped at 15s. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `PartyMemberManager.decide` is unchanged.
Affects: one member's invite gate and the monitor words (RECONNECTING / ACCEPTING / IN PARTY). Other members and the leader hunt are not reset.
Consent: user (recover the interrupted step from game state after reconnect).
Result: not run in game.

## 2026-11-02 — party monitor Invite / Y focuses the game

Intent: Invite from the monitor typed only after the user clicked the game. The monitor is the foreground window, so the worker's later `SetForegroundWindow` is refused.
Shared: the Invite and Y+Enter clicks call `bring_game_to_front` on the UI thread before the queued `deliver_chat` / `type_accept_key`. Always-on-top is dropped until that action finishes. The worker focuses again at the start of the same drain. Automatic invites still use `deliver_chat` → `ec_run`; automatic Y still uses `type_accept_key`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party monitor buttons only.
Consent: user (focus the game automatically; confirm the buttons share the bot path).
Result: not run in the UI.

## 2026-11-02 — Stop disarms the schedule before the next poll

Intent: Stop was restarting the game and opening the party monitor. The Qt shell disarmed the schedule on a queued signal, so the schedule poll still saw an armed session in the STOPPED state and called Start.
Shared: `userStopped` now runs `_disarm_schedule` directly inside `coordinator.stop`, before `_halt` returns. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: Stop button and the stop hotkey. Party forming still does not switch the bot to solo.
Consent: user (Stop starts the game again and the party monitor opens).
Result: not run in the UI.

## 2026-11-02 — party memory unknown, join is memory, one chat queue

Intent: A failed party read must not invite or leave. Popup close after Y is not a join. Monitor Invite / Y+Enter must not type beside the automatic invite.
Shared: `memory_in_party` is True / False / None. `needs_leave` requires this name, the leader name, and a confirmed in-party read. `reported_joined` uses fresh member party memory only. `InviteAccepter` goes `waiting_memory` then `joined`. `PartyChatQueue` is drained once per worker tick; that tick skips the matching automatic line. Forming deadline is not moved on reconnect. Hunt waits only for roster rows with Wait checked (default on). On unchecks a name. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader invite and leave, member accept, party monitor buttons, Party tab roster, when forming holds the hunt.
Consent: user (implement the party invite/maintain corrections).
Result: not run in game. Discovery approval and a second rally for late members are not in this change. Restart the bot to load it.

## 2026-11-01 — invite accept is Y then Enter

Intent: The invite popup accepts only when Y is followed by Enter. Y alone does not confirm.
Shared: `type_accept_key` now calls `GameChat.send("y", open_chat=False, press_enter=True)`. One `ec_run` types physical Y, then physical Enter, while English is still held. Chat is not opened. The monitor button is the same call. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept, and the party monitor Y+Enter button.
Consent: user (Y and Enter are both required).
Result: not run in game.

## 2026-11-01 — party monitor can type /초대 and Y

Intent: From the party monitor, send one invite line and press Y through the same bot path as Start (`send_chat_line` / `type_accept_key` → `ec_run`).
Shared: `PartyMonitorWindow` name field, Invite button (`invite_command` → `deliver_chat`), Y button (`type_accept_key`). Both run off the UI thread. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: the party monitor window only. Leader invite timing and member popup accept are unchanged.
Consent: user (run these from the invite monitor, including Y).
Result: not run in the UI yet.

## 2026-11-01 — invite Y uses the same ec_run as the admin exe

Intent: Member Y still switched the IME from Python while the bot window was in front, then fell back to the hunt keyboard. The popup needs one physical Y with the game in front and the IME in English.
Shared: ASCII-only `ec_run` (`y`, no chat open, no Enter) focuses the game, clears 한글 mode, sends the key, holds English 150 ms, then restores the previous mode. `type_accept_key` is only that call. The hunt Y fallback is gone. `/초대` still uses 한 mode. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept. A lone ASCII chat line takes the same English path.
Consent: user (Y must match the admin exe).
Result: DLL rebuilt (`BUILD_OK`). Not run in game. Restart the bot so it loads the new DLL.

## 2026-11-01 — bot invite keeps the game in front and switches 한

Intent: The bot is already elevated, but `/초대` still followed the Windows input language. The admin exe does not, because it is a fresh process that is allowed to take the foreground and the game thread applies the Korean layout. The bot window takes focus back during the typing sleep.
Shared: `ec_force_foreground` unlocks foreground (`AllowSetForegroundWindow` / `LockSetForegroundWindow`) before `SetForegroundWindow`. `ec_hangul_prepare` loads layout 0412 without activating it on the caller thread, then `SendMessageTimeout` of `WM_INPUTLANGCHANGEREQUEST` on the game thread, and retries 한 mode once after focusing the game. `ec_run` puts the game in front again before the layout switch, before each character, and before the final Enter. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: every `ec_run` caller (bot party invite / leave, member Y via `GameChat.send`, and both CLIs). Hunt keyboard and Pico are unchanged.
Consent: user (bot must have the same effect as the admin exe; bot is already admin).
Result: DLL rebuilt (`BUILD_OK`). Not run in game. The running bot keeps the old DLL until it is restarted.

## 2026-11-01 — member runs from party memory with no websocket

Intent: Follow and combat must run from party memory when the leader socket is down or was never configured. The socket stays optional and only carries policy and rally.
Shared: member worker no longer calls `decide_survival` while the socket is pending. Missing leader IP no longer stops the worker. `PartyMemberManager.decide` is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member Start. Not-in-party still waits inside `decide` (`leader_missing`) until party memory shows a leader. Leader path unchanged.
Consent: user (client must work from memory reads with no websocket).
Result: not run in game.

## 2026-11-01 — member already in party does not wait on the socket

Intent: Party memory already showed `in_party` with leader 매력여기사, but the member stayed on `decide_survival` (`waiting_leader_socket`) until `192.168.9.27:8765` connected. Follow should start from the in-game party; the socket is only for policy and rally.
Shared: worker gate around `_member_socket_pending`. Still HP-only when party memory does not say in-party. `PartyMemberManager.decide` itself is unchanged. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member Start when already in an in-game party and the leader socket is still connecting. Not-yet-joined members still wait. Leader path unchanged.
Consent: user (if the client is already in the party, enter it; do not keep waiting).
Result: not run in game.

## 2026-11-01 — party frame checks before workflow

Intent: Bad party frames must not book an invite, a policy ack, or a member order.
Shared: `frame_check` drops non-objects, unknown types, control characters, names over 16, a member frame that says it is the leader, a hello whose name does not match `from`, and a leader policy/rally with missing fields. Unnamed `from=member` still stays Unidentified and is not invited. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party socket ingest only.
Consent: user (put checks in so errors do not get through).
Result: not run in game.

## 2026-11-01 — member name from MyPlayer entity

Intent: The member hello had no character name because `PlayerState` has no name field. The enttrack snapshot already has a `MyPlayer` row with `name`.
Shared: `_player_chat_name` reads that row first. Party monitor shows it as Self. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: party hello / member_state sender name and the monitor label. Hunt targeting is unchanged (`MyPlayer` stays off the click list).
Consent: user (read MyPlayer and display it).
Result: not run in game.

## 2026-11-01 — P0 member discovery (hello, pending, empty-roster listen)

Intent: Add a discovery layer in front of the existing party workflow. Unknown sockets must not be dropped; empty roster must still listen. Hunt brains stay as they are.
Shared: `_party_server_on` (listen) vs `_party_leader_on` (invite/rally/turret). `MemberDiscovery` keeps unmatched hellos as PENDING/UNIDENTIFIED/CONFLICT. Matched names still go through `member_states` / invite / rally. Members without a roster seat do not overlay policy or consume rally. No `UNKNOWN` name, no `try_unstick_escape` / `begin_retreat` / `apply_hp_actions` / login changes.
Affects: leader socket start (empty roster listens, workflow waits). Member hello after a real `identity.name`. Party monitor Discovery metric. Approve/reject UI is P1.
Consent: user (discovery layer P0 spec).
Result: not run in game.

## 2026-11-01 — dungeon hop matches the 2026-10-19 click

Intent: a dungeon hop within one tile drops that click and plans the next one on the same tick. Two tiles out, while the body is walking, the click moves farther only when the line stays straight. The route-cell chain is not used.
Shared: `emit_travel_hop`. The field branch already used this near-tile and straight-extend rule, so its clicks stay the same. `choose_body_click`, loot, combat, and HP are unchanged.
Affects: dungeon patrol and other dungeon travel hops. A bend waits until the click is within one tile. The dungeon hop cap stays 3.
Consent: user (dungeon movement and patrol clicks match 2026-10-19 commit 2f76607; do not change the shared click picker or adena loot).
Result: implemented in `travel.py`. Not run in game.

## 2026-11-01 — item F4 press matches the 2026-10-19 range

Intent: press F4 when the pile is within one tile, on that tick, with no stand sample and no 0.4s gap before a repeat. This is the press rule in commit `2f76607`.
Shared: none. Dungeon travel, combat, retreat, the approach hop, and how long a listed pile is held are unchanged. `loot_awaiting_memory_gone` still releases a ghost after three presses and 8 seconds, not after the old 0.8 seconds. A side F4 still does not run while attack, travel, or search owns the tick.
Affects: the first loot F4 and a retry while the pile is still within one tile. Distance 2 still walks. A pile that leaves that range is approached again. Small named adena outside the range is still not walked back to.
Consent: user (make only the item-loot F4 press rule identical to the October 19 version; do not touch anything else).
Result: implemented in `loot_hop.py`. Not run in game.

## 2026-10-31 — invite accept Y uses the same enter_chat ec_run as /초대

Intent: `ec_press_key` is not in enter_chat.dll 1.0.0, so member Y could not use the invite typing module. User asked to use the same API as inviting.
Shared: `type_accept_key` calls `GameChat.send("y", open_chat=False, press_enter=False)` under English IME. DLL `ec_run` sends ASCII via Interception when Hangul IME is not active (so Y is a physical key; mixed `/초대` names stay WM_CHAR). Hunt Y remains the fallback. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite Y. Leader `/초대` Hangul path unchanged.
Consent: user (use the inviting enter_chat API for Y).
Result: not run in game.

## 2026-10-31 — member assist beats follow

Intent: Single member walked to the leader (`follow_off_ui` / turret yard / `follow_combat_near`) and only then assisted. Assist must win over moving.
Shared: `decide_policy` takes ASSIST/CLOSE_IN as soon as `assist_ready`, before any FOLLOW, and without the assist-leash gate. Out of range is CLOSE_IN to the mob, not FOLLOW to the leader. HP / defend / join-map stay above. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member combat vs follow. Follow still runs when there is no assist target. Assist leash still gates turret yard rejoin and `follow_combat_leash`.
Consent: user (just make assist higher than moving).
Result: not run in game.

## 2026-10-31 — member follow closes on the leader, no reverse to a behind-slot

Intent: Single member did not stop within `stop_tiles` when the leader stopped, and sometimes walked the opposite way. Follow was walking to a Reynolds behind-slot, a random cardinal stand, or the turret ring seat — never "arrive near the leader and hold".
Shared: `follow_kind` is a rubber-band on distance to the leader (close until `stop_tiles`, no slot/stand). Manager FOLLOW uses field descent toward the leader; behind-slot / trail / turret seat are not click goals. Turret ring `FOLLOW turret_seat` removed (yard rejoin stays). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member follow / idle hold only. Multi-member turret spread no longer walks to a ring seat; they hold inside `stop_tiles`.
Consent: user (stop reversing; leader stops → member reaches stop_tiles).
Result: not run in game.

## 2026-10-31 — member Y reached the bot UI, not the invite popup

Intent: Member log showed `Y key pressed #1/#2/#3` then `Y FAILED: popup still open`. `_press()` returning "" only meant hunt `key_down("y")` did not throw. Interception/pico keys go to the foreground window; the bot UI was in front, so Y never hit LC. `enter_chat.dll` in this tree is 1.0.0 with no `ec_press_key`, so the DLL path never runs. First policy contact also `reset()` the accepter mid-press, starting a second 3-press cycle.
Shared: hunt Y now AttachThreadInput-focuses LC and does not send Y unless the game is in front; the traffic line records `hunt|enter_chat`, backend, IME. First-contact session no longer resets `InviteAccepter`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept only.
Consent: user (check Y pressed 3× popup still open).
Result: not run in game.

## 2026-10-31 — member invite Y without enter_chat.dll

Intent: The member saw the invite popup (uidialog confirm parse works) but Y failed: `enter_chat.dll not found` on `D:\ManmabotV1_final_final_final\...` (that tree has no built DLL). Accept must still press Y via the hunt keyboard.
Shared: `accept.type_accept_key` tries enter_chat `ec_press_key`, then hunt `key_down("y")` with English IME. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite accept only.
Consent: user (client accept failing).
Result: not run in game.

## 2026-10-31 — uidialog confirm text reaches invite accept; chat typed logs IME

Intent: Member never saw the in-game invite popup. `uidialogmon` already prints Yes/No confirm text, but `lc_view.uidialog()` kept only window labels, so `invite_popup.party_invite` always got an empty `confirm` list. Leader `typed` also hid IME/char counts, so a Hangul `/초대` that went out as jamo still looked successful.
Shared: `lc_view.parse_uidialog_text` fills `confirm` from status `msg=` and `[+] CONFIRM` lines; sensors accept a snapshot that has `confirm`. `deliver_chat` logs `chars`/`keys`/`ime` on success and fails when `failed>0`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: member invite Y (popup pattern). Leader invite log detail only.
Consent: user (fix uidialog confirm parse + DLL typed honesty).
Result: not run in game.

## 2026-10-31 — leader start wait 10 min

Intent: The forming window before hunt (all joined → formed, else late + keep inviting) was 5 min. User asked for 10 min so a multi-member roster has more time to connect, ACK, and arrive.
Shared: `invite.START_WAIT_S` and `leader_rally.WAIT_TIMEOUT_S` (fallback when no invite deadline). Rally still uses the same start-wait deadline. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader hold/rally/hunt start time with a named roster. Invites still have no cut-off after the window.
Consent: user (set start wait to 10 mins).
Result: not run in game.

## 2026-10-31 — empty roster does not start leader party

Intent: With no member names, the leader still armed the party (websocket listen, session, rally hooks, monitor pipeline). Party must not start at all until the roster has at least one name; the bot hunts solo.
Shared: `_party_leader_on` now requires `_leader_roster_ready`. `_start_party_socket` / `_ensure_party_log` / nav hooks / invite setup all follow that gate. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks, hunt loop stay as they are.
Affects: leader Start with an empty Party-tab roster. Named roster unchanged.
Consent: user (empty roster must not start party).
Result: not run in game.

## 2026-10-31 — leader workflow: rally/hunt not done while connect is waiting

Intent: The party monitor listed Server → Connect → Policy → Invite → Rally → Hunt as a sequence, but an empty roster skipped rally to ``done`` and the phase became hunting, so Rally/Hunt went green while Connect/Policy/Invite were still waiting. With a roster, start rally also began on the first tick.
Shared: `leader_workflow` later steps stay off/wait until connect has members; `LeaderStartRally.begin` with no names stays ``off`` (does not `skip()` to ``done``); `_leader_may_begin_start_rally` waits for a member socket and for the invite start-wait to finish (or the party to form). Forming still uses the existing hold-ground window so the leader does not full-hunt while inviting. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader party monitor badges; when start rally begins. Empty roster: leader still farms; Rally/Hunt stay off. Named roster: Rally starts after connect + invite window, still bounded by the same start-wait deadline.
Consent: user (rally/hunt active while connect/policy/invite waiting).
Result: not run in game.

## 2026-10-31 — loot F4 on the matching tile, dungeon keeps a live click

Intent: press F4 on the tick the live tile equals the pile, with no ground click on that tick, and stop reissuing a dungeon walk click just because the next route cell changed.
Shared: none. `try_unstick_escape`, combat, retreat, and the field branch of `emit_travel_hop` are unchanged. `f4_allowed` still requires a stand unless this loot press set `_loot_f4_match` for that id, so a side F4 during another action does not fire while walking. The 0.4s gap remains only between retries in `try_finish_pending_pickup`. A walkable pile at Chebyshev 1 does not match.
Affects: sticky loot approach and the dungeon hop while a click is already active. Mainland and Talking Island travel still extend only on a straight line. After three failed presses the pile is walked again. A listed pile still holds the character until it leaves, the bag rises, or the give-up cap.
Consent: user (adena: loot_hop approach only, F4 when the live tile matches, no stand or 0.4s on that press, hold until the pile is gone, no F4 at distance 1 while moving; dungeon: travel.py dungeon branch only, new click only when the current line is blocked or that direction cannot continue).
Result: implemented. Checked by a local decision simulation, not by a game log. A portable exe built before this change does not include it.

## 2026-10-31 — world nav uses the 13 s confined teleport

Intent: a world-nav walk that stays inside 3 tiles for 13 seconds uses the hotbar teleport, or the talking scroll when teleport cannot fire, then plans again from the landing to the same routine row.
Shared: `WORLD_NAV` column and `_maybe_world_nav_confined`. `try_confined_escape` / `try_unstick_teleport` are unchanged, so island and travel escapes stay as they are. The clock runs only in `walk` and `gate_approach`. Scroll, settle, NPC teleporter, and gate click reset it. A hunt-edge arrival is left to `world_nav.drive`. Dungeon maps still disable unstick. After the cast, the live plan is dropped and the mode stays `WORLD_NAV` until the pose leaves that bubble (or 12 seconds pass), then `request_world_nav` uses the same reason. The old step list is not resumed. A mainland scroll's `unstick_scroll_return` flag is cleared here so farming does not idle on it afterward.
Affects: world-nav walks and gate approaches, including the Talking Island walk from the magic-book merchant. Shop, retreat, combat selection, HP, and login are unchanged. A sticky fight still clears the clock. A second standstill after the new plan can teleport again.
Consent: user (add the 13-second teleport to world nav, then continue the trip that was in progress; stop first if that would break the existing route).
Result: implemented. Not run in game.

## 2026-10-31 — account server language picks teleporter clicks again

Intent: account management server language `zh-CN` must select the Chinese dialog rows. On 2026-10-22 teleporter ids were switched from that account locale to the profile game language, which stays `ko`, so a Chinese account still clicked `teleport_gludin`.
Shared: `configure_decision` copies `shop_locale` (the account locale) into the live click language. `resolve_world_nav_teleporter_ids` and the recover-arrow shop points read that language. Buy/sell ids already used `shop_locale`. Movement, combat, HP, and login are unchanged. A missing `_ch` row still uses the Korean row.
Affects: world-nav NPC teleporter dialogs, including Gludin. A Korean account keeps the Korean rows. The profile field `game_language` on disk is not rewritten; the session log line `click language=` is the value the clicks use.
Consent: user (account server language Chinese must use the Chinese settings, as it did before the 2026-10-22 split).
Result: implemented. A config with `shop_locale=zh` and `game_language=ko` selects `teleport_gludin_ch`. The reverse selects `teleport_gludin`. Not run in game. The profile file still says `game_language=ko`.

## 2026-10-31 — exp percent comes from the LoadingBar, not the BSS mirror

Intent: the income bar and the monitor `expPct` follow charread. Read the HudCharacterInfo LoadingBar float (CharacterData chain, then the UI window). Use ExperiencePct64 only when that bar is missing and the double is a real 0–100 percent. Do not replace the mirror RVA.
Shared: `body_pose.read_progress`, `realtime_monitor_full.c` `readHudExp`. `EXP_KILL_RELEASE_ENABLED` stays false, so a real percent does not release a sticky target. Movement, combat clicks, loot, HP, and login are unchanged.
Affects: the hourly exp rate and the monitor field. A running process keeps the old reader until it starts again.
Consent: user (wire the income bar and monitor expPct to the LoadingBar; keep the mirror as the fallback).
Result: implemented. Live `read_progress` and a new monitor snapshot both returned level 15 and 25.1605%. A process that already loaded the previous DLL keeps that image until it starts again.

## 2026-10-31 — F4 only after a stop, and a listed pile is not dropped at 0.8s

Intent: press pickup only when the character is on the pile and standing. Do not press during a walk or an attack. Keep the pile until it leaves the world or the bag count rises, instead of releasing it 0.8s after F4 and letting patrol walk away. A failed press rechecks the tile. A side F4 does not run while attack, travel, search, or sticky loot owns the tick.
Shared: `tick_loot_item`, `try_finish_pending_pickup`, `loot_awaiting_memory_gone`, `mark_loot_clicked`, `f4_allowed`, `arm_loot_side_intent`, `controller._loot`. Combat clicks, travel hops, and `ExperiencePct64` are unchanged. Sticky combat can still preempt loot. After three standing F4s the tile is walked again. A pile still listed 8s after several F4s is released so a ghost does not pin the character.
Affects: hunt loot and the pickup that used to run beside an attack or a patrol click. Movement geometry and attack selection are unchanged.
Consent: user (fix the F4 loot path from the log; do not touch the exp address; keep movement and combat impact small).
Result: implemented. Not run in game.

## 2026-10-30 — member heal/buff on the policy ladder; HP while waiting for the leader socket

Intent: Item 7 was two ladders, not a broken heal. Live heal/buff returned from `apply_party_support` before gather/policy, while `decide_policy` never emitted HEAL/BUFF and `intent_for_kind` idled those kinds. Unify: stash support, skip gather when heal/buff is needed (heal still beats the start rally), policy emits HEAL/BUFF first, manager returns the stash. Item 10: leftover `WorldNavHooks` cleared at `_worker` start (party-off Start already cleared them); `merge_leader_policy` imports `comms.orders` not `websocket.party_orders`; member Start enters the bot loop and runs HP-only (`decide_survival`) until the leader socket connects. There is no 60 s connect timeout — 30 s is log cadence. Empty leader IP still fails immediately.
Shared: `decide_policy` / `PolicyInput.need_heal`/`need_buff`; `PartyMemberManager.decide` / `decide_survival`; `BotController._start_party_client` / `_member_socket_pending`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `apply_party_support` and `party_critical_escape` still own in-place HP and the retreat gate.
Affects: party members only (policy order, start-rally vs heal, first-connect wait). Leader and solo decide paths are unchanged. After the first connect, a socket drop still farms on the last policy.
Consent: user (item 7 policy order + item 10 leftover hooks / import boundary / HP before connect).
Result: not run in game.

## 2026-10-30 — exp-rise kill release is off

Intent: stop treating a level or exp rise as a kill. The sticky monster stays the attack target until a memory death signal drops it.
Shared: `EXP_KILL_RELEASE_ENABLED` in `sample_kill_progress`. While false, a rise only writes a clickgap log. It does not call `_release_sticky_for_kill`, add `exp_kill_ids`, or clear `_attack_aim_lock`. Memory omission, bait, the 2-tile dead window, and `finish-gone` still end the attack.
Affects: farm and dungeon engage, including `finish_kill`. Loot, movement, HP, and login do not use this switch. A kill with no exp still waits for the row to leave the list, as it already did.
Consent: user (turn off the exp-rise stop-attack path so it does not run).
Result: flag set false. Not run in game.

## 2026-10-30 — memory constants moved to registry v35 (26.10.27.2001)

Intent: readers use `D:\dist_10_28` registry v35. Same chains (mgr → holder → vft subsystem, map id at MapSubsystem+0x718, encoded CharacterData status). Moved RVAs and the two shifted fields only.
Shared: `LC930_REGISTRY.txt`, `char_offsets.txt`, `entity_offsets.txt`, `offsets.json`, inventory/hotbar tables, `body_pose` action vfts. Action pointer is ActionComponent+0xC8. Door frame is +0xE0. `char_offsets` `ST_BLOCK` stays 0. HP decode, move/attack labels, and login clicks are unchanged.
Affects: map id, cell xy, entity class, buffs, inventory, hotbar, shop list, body stand/walk. `not_permitted` no longer matches door gfx 0x8009.
Consent: user (apply the folder’s updated offset constants without breaking the running project).
Result: constants written. Rebuilt `print_state.dll`, `realtime_monitor.dll`, `shop_listen.dll`, `attacks_me.dll`, `contested_mobs.dll`. Buff, dialog, inventory, and hotbar still read their tables at startup. Not run in game.

## 2026-10-29 — start rally yields to combat on the member

Intent: A live rally order must not keep the member walking to the pin while the leader is already fighting a few tiles off it. Crisis retreat and in-place heal/buff still run first. After the fight the member can finish the rally walk (arrival is not marked on yield).
Shared: `PartyMemberManager._maybe_hunt_gather` / `_rally_yields_to_combat`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are. `apply_party_support` still runs before gather.
Affects: party members during the start rally only. Solo and leader hold-ground are unchanged.
Consent: user (item 4, rally before assist).
Result: not run in game.

## 2026-10-29 — unnamed policy ack books each member by client_id

Intent: Two member bots that start together both send `from=member` before they know their character name. The leader used to keep that ack only when exactly one roster name was still unconfirmed, so `/초대` never went out.
Shared: `PolicyAcks.note` / `MemberStates.note` / `InviteAccepts.note` bind `client_id` to the next free roster name in order. Member Start makes one 8-hex id and puts it on `policy_ack`, `member_state`, and `invite_accept`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader invite gate when two or more members connect before they are in the in-game party.
Consent: user (policy ACK name matching).
Result: not run in game.

## 2026-10-29 — already-formed party skips /초대, socket beep

Intent: On party Start, read party memory first. If this character is already in a party, do not type `/초대` (or `파티탈퇴` when identity is unknown). Connect the websocket and send a `beep` test frame instead. Missing roster names are still invited.
Shared: `invite.already_in_party` / `LeaderInvites.start` seed-from-memory; `accept.InviteAccepter` ignores the popup while `in_party`; wire type `beep`. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: leader setup and member invite-accept at Start. Rally / hunt after that is unchanged.
Consent: user (after leftover-leader-hooks fix; “go on” for already-organized skip-invite + beep).
Result: not run in game.

## 2026-10-29 — leftover leader role does not run party hooks

Intent: Enable party off means a solo Start. A saved `party_role=leader` must not install rally hooks, hold-ground, invites, policy, or decision publish.
Shared: `BotController._party_leader_on` (requires `party_enabled` and role leader). `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, login clicks stay as they are.
Affects: Start when the Party checkbox is off. A previous leader role in the schedule no longer waits on `party.hold_ground`.
Consent: user (fix leftover leader hooks first; party-already-formed skip-invite is next).
Result: not run in game.

## 2026-10-28 — hunt input: toolbar choice is not replaced by a schedule

Intent: choosing Interception on the toolbar must be the hunt transport. A schedule apply was able to write `input_backend` back onto the profile.
Shared: schedules no longer store or apply `input_backend` / `pico_com` / `pico_baud`. The choice is saved with the app state. Start logs `Hunt input:`.
Affects: which transport the next hunt start opens. Click/key behavior unchanged.
Consent: user reported Interception was selected and the start still opened the Pico.
Result: the 05:56 start logged `Pico data COM was not found` before the 05:57 save of `interception`. Not re-run after this change.

## 2026-10-22 — hunt input: live data COM only, shown as a label

Intent: choosing Raspberry Pi should read the plugged-in data port. A saved COM must not stay selected, including the REPL.
Shared: `find_pico_data_port` is the hunt port. `resolve_pico_port` ignores a saved name. `MANMABOT_PICO_COM` still overrides. Toolbar and driver dialogs show that port as a label.
Affects: which COM the next hunt start opens. Click/key behavior unchanged.
Consent: user asked to drop the port selector and the remembered COM, and to detect when Raspberry Pi is selected.
Result: not run as a hunt session. A scan of the plugged-in board is what produced COM5 earlier; that number is not stored in the code.

## 2026-10-22 — hunt input: Detect COM button on the main toolbar

Intent: the COM box can keep a saved port that is still plugged in, including the REPL. Users need one button that writes the data port.
Shared: toolbar `Detect COM` calls `find_pico_data_port` and saves `pico_com`. Visible only while Raspberry Pi is selected. Stopped sessions only.
Affects: which COM the next hunt start opens. Click/key behavior unchanged.
Consent: user asked for a detect button on the bot control UI.
Result: live ports at the time of the request were COM4 (`x.0`, REPL) and COM5 (`x.2`, data). The button selects COM5.

## 2026-10-22 — hunt input: Pico data COM is filled from Windows

Intent: plugging the Pico should not require typing a COM name, and a saved name that disappeared after a different USB socket should be replaced.
Shared: `find_pico_data_port` / `resolve_pico_port` (vendor `0x2E8A` or `0x239A`, hardware id `x.2`, same as the Pico lab scripts). A saved COM that is still in the Windows list is kept. Toolbar, driver dialogs, and `prepare` use that. `MANMABOT_PICO_COM` still overrides.
Affects: which serial port hunt input opens. Click/key behavior unchanged.
Consent: user asked to auto-get the COM and combine it with a manual choice.
Result: not run against a plugged-in board.

## 2026-10-22 — hunt input: Interception or Pico, chosen in the driver window

Intent: farm clicks and keys can use either the Interception driver or the Pico HID board. Both stay available. Login and party chat keep Interception.
Shared: `app._05_action.input_backend` (`InterceptionHuntInput`, `PicoHuntInput`). `MouseController` / `KeyboardController`, talking-scroll wheel, and shop scroll call it. Profile `input_backend`, `pico_com`, `pico_baud` (trial `other`). Driver setup (Qt and Tk) radios plus data COM. `bot_input_released` drops devices only when the farm path holds Interception, so a Pico session does not close COM for chat.
Affects: hunt mouse, keyboard, and scroll transport. Untouched: decision, retreat, HP, login `win.interception`, enter_chat DLL.
Side effect candidates: Pico aim adds a short cursor check before each click; pointer acceleration is off while a Pico hunt session is open and restored on Stop; a failed Pico open stops the farm loop; Interception hunt behavior matches the previous device bind.
Consent: user asked to implement both input modules on the control UI for hunting.
Result: not run on hardware in this change.

## 2026-10-22 — party: start order free (leader / members any order), per-member invites, leader member picker

Intent: only 1:1 tested so far, but real runs have several accounts. The start order was strict: a member stopped if the leader socket was not up within 60 s, and the leader invited only inside a 15 min window from its own Start (late members, or members that left the party, were never invited again). The leader monitor summed all members into one line. User asked for free start order and a member selector to manage members one by one.
Shared:
- Member start (`BotController._start_party_client`): waits for the leader socket with no timeout (30 s log lines, `watch_member` between, Stop cancels); the bot loop is not entered until connected (no movement / combat / HP while waiting — same as the old 60 s wait). Only an empty leader IP still stops with `party_ws_unreachable` (text updated EN/KO/ZH). Snapshot `start_wait` → yellow monitor note.
- `invite.PartyInviter` per member, no cut-off: `START_WAIT_S` = 5 min (was the 15 min window) only bounds the leader's wait before the hunt; states forming → formed | open. Missing at 5 min = `late` (still invited); no `excluded`. Leave detection: joined member whose `member_state` says "not in this party" (fresh, memory readable — `MemberStates.out_of_party`) while the leader memory does not list it, for `LEFT_CONFIRM_S` 10 s → invited again (`left` count).
- `LeaderInvites`: policy re-sent whenever the socket count rises (also after a drop); no `/초대` right after a combat action (`COMBAT_ACTIONS`: attack, potions, depoison, heal, buff, hp_to_mp) unless a due invite waited `COMBAT_HOLD_MAX_S` 60 s; NPC / gate / teleport rule unchanged.
- `leader_rally.WAIT_TIMEOUT_S` 5 min; deadline = start wait end. `comms.ingest.drain_leader_reports`: after the start rally is done, the rally point is not repeated to new sockets — late members follow the leader (existing follow / join_map, no new movement code).
- `member_state` gains `live` (bot state, map/xy from `live_pose_from_state`, hp/mp, brain kind/reason, rally stage/arrived) — rides along, not counted as a change. Name falls back to `_player_chat_name` before the policy is applied. `MemberStates.unnamed_recent` flags frames that could not be booked.
- Monitor: roster rows get `state` (offline / policy_wait / inviting / accepting / late / late_offline / joined / following / ready / not_arrived), `live`, `late`, `left`, per-member `steps` (`workflow.roster_member_steps`). Dashboard: member list with state colours + detail pane (steps, last report, bot, map/XY, HP/MP, brain, invites, left/late, frames mentioning that member); overview table kept; PHASE "START WAIT", INVITE "OPEN".
Affects: party leader invite timing (continues while hunting; delayed by combat), leader start wait (15 → 5 min), member Start (never times out). Untouched: `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, member follow / assist / loot, login, solo decisions, mapId source.
Side effect candidates: a member left running with no leader waits forever (shown yellow); continuous turret combat delays invites up to 60 s; slow-loading members miss the rally and follow instead; an "out" report racing a real join is held 10 s before re-invite.
Consent: user picked wait_forever / per_member / 5 min fixed / list+detail / combat gate "no_combat" / go "all".
Result: party tests 245 OK (2 skipped); new `test_party_free_order.py`, `test_party_invite_setup.py` rewritten (it still expected `/파티` and `POLICY_WAIT_S`), two stale `test_party_rally` cases fixed (recovery frame `from: leader`, drain test profile). Offscreen dashboard render checked with 3 members (hunting / late inviting / late offline) + unnamed warning. Not run live yet.

## 2026-10-22 — party: level-triggered leader↔member sync (`member_state`) + party memory fixed for 26.10.18.2

Intent: live run (leader `party-20261022-052750.log`, member 04:27:55–04:28:50 member clock): the member really joined after Y, but both monitors showed failed / in progress. Causes: (1) party memory blind on both PCs — the party reader used its own stale registry copy (BUILD 26.10.16.1), anchoring failed, `world.last_party` = None (`count=None` in every "Party wait" line), so "in party" was read as "no"; (2) nothing told the leader the member joined — invite notices were fire-and-forget and the leader retyped `/초대` every 20 s while the member was still in its 30 s wait. The user asked for a correct sync/ack system for bots that start at different times, using party memory to confirm the join.
Shared:
- Party memory: `party_listen_reader.default_registry_path` = lc930 registry (same anchors as every other reader) + new `analysis/party/registry/PARTY_SEC17.txt` (party keys only; vfts +0xB5E0, the shift of MAPSUBS and SHOP). `party_listen.c` reports `subs_ok` (PartySubsystem vft found — works outside a party); reader auto-calibrates once over known patch deltas when false. Sensors treat `subs_ok:false` as unknown (None), not "no party". New `analysis/party/build.bat`, `tools/probe_party_vft.py`. Start log: "Party memory: OK / calibrated / PartySubsystem not found".
- Protocol (`app/_06_party/sync.py`): member sends `member_state` every 2 s and on change (session, applied policy id, own party memory, last invite id + accept phase). Leader `MemberStates` keeps the latest per roster name (stale after 7 s, other session ignored); its `policy_id` confirms the policy (legacy `policy_ack` still accepted). `InviteGate`: invite notice resent (same id) every 3 s up to 3× until the member state echoes it; no new `/초대` while the member reports `waiting`/`pressed` for the last id (max 60 s). `PartyInviter.observe` counts a join from leader memory OR the member's report (in party, party leader = this leader).
- `InviteAccepter`: ignores a repeated `invite_id`; `phase`; party memory None → join "unverified" instead of "missed".
- `MemberOrders.ingest` reads `session` only from `from == "leader"` frames (the server relays member frames to every client).
- Monitor: member steps add Sync; Accept / In party use phase and show "unknown" when party memory is unreadable. Leader Connect shows "k/n reporting state", Invite shows joins by member report and holds. Roster In party: YES (source) / NO (red only when both memories are readable) / ?.
Affects: party leader invite timing (fewer `/초대` repeats; retype right after a missed accept), member accept (dedupe), party join detection. Movement, combat, HP, login, solo decisions untouched. Side effect candidate: if the auto-calibrated vft were wrong in a way that still matches PartySubsystem, party member names could read wrong — RC / RC_PLAYER are still checked per member.
Wire: leader and member must run this build together (new `member_state`; an old member still works through `policy_ack` but gives no join report). Deploy to both PCs: Python files, `analysis/party/registry/PARTY_SEC17.txt`, `analysis/lc930/registry/LC930_REGISTRY.txt`, rebuilt `analysis/party/party_listen.dll`.
Consent: user request ("build very successful communication system … recognize the party creation on the memory reading and send ack, and check this on the leader side. fix and implement correctly").
Result: offline simulation (member starts 10 s late, first notice dropped, leader memory blind, member memory readable from 40 s): notice resent at 13 s and accepted, Y at 43.5 s, leader "joined — member report" at 44 s, one `/초대` typed in total. Without the join, `/초대` retyped only after the member reported `missed`. `party_listen.dll` rebuilt. Live party memory check not done (UAC prompt for the elevated probe was cancelled).

## 2026-10-22 — party: invite accept Y as a physical key (typed `y` was ignored)

Intent: live test (leader 05:14–05:16, member clock ≈1 h 3.4 s behind): 4 invites typed, 4 notices received, Y "typed" OK twice (enter_chat status OK), but party memory never showed a join. An ASCII `y` goes out as `WM_CHAR`; the popup only reacts to a key event.
Shared: `accept.type_accept_key` → `GameChat.press_key(0x15)` → enter_chat `ec_press_key` (same typing module, Interception key down/up, needs DLL 1.1.0). `InviteAccepter` logs 5 s after Y whether party memory shows the join (`join_missed` on the monitor Accept step).
Affects: member invite accept only; 30 s delay unchanged. Open: whether the popup stays open 30 s while the leader re-invites every 20 s — the 5 s join check tells.
Consent: fixes the agreed accept path (popup key Y) under the user's "use the invite sender's typing module".
Result: simulated: one scancode 0x15 press at 30 s; join check logs a miss. DLL 1.1.0 export loads. Not run in game.

## 2026-10-22 — party: invite accept 30 s after the notice, typed Y, logic moved to `_06_party`

Intent: user asked for a 30 s wait after the leader's invite notice, Y through the same typing module as the leader's `/초대`, and less party code in `bot_controller`.
Shared: new `app/_06_party/accept.py` `InviteAccepter` (`on_notice` / `tick` / `status` / `reset`): Y via `send_chat_line("y", open_chat=False, press_enter=False)` (enter_chat; ASCII goes as `WM_CHAR`). A repeat notice while one is queued keeps the first due time (the leader repeats every 20 s). No press if party memory shows a join by then. New `app/_06_party/workflow.py` (`leader_workflow` / `member_workflow`) — moved out of `bot_controller`. Controller keeps one hook `_member_invite_accept`. Python wrappers for `ec_press_key` removed (the DLL export stays, unused).
Affects: member invite accept only (timing 0.8 s → 30 s, key path physical scancode → typed `y`). Side effect candidate: if the popup only reacts to a key event and not to `WM_CHAR`, Y does nothing — then switch `type_accept_key` back to a physical key. Supersedes the 0.8 s / scancode part of the entry below.
Consent: user request.
Result: simulated: no press at 29.9 s, one `y` at 30 s despite a 20 s repeat notice; no press when joined meanwhile. Not run in game.

## 2026-10-22 — party: member auto-accepts the invite (Y) on a leader socket notice

Intent: the leader's `/초대` reached the game but the member never accepted. Nothing on the member read the [Yes]/[No] popup (enter_chat only types; no popup / chat memory sensor exists). Now the leader tells the member over the socket right after typing, and the member presses Y.
Shared: new wire type `party_invite` (`to`, `invite_id`, `session`) from `LeaderInvites.tick` after a typed `/초대 <to>` (`announce_invite` → `party_orders.publish_invite`). `MemberOrders` keeps the latest notice (`take_invite`); dropped on a new leader session. Controller `_queue_member_invite_accept` / `_member_invite_accept_tick`: press Y 0.8 s after the notice, once per notice. Skipped when party memory already says in a party, or when the notice names another roster name than this character (an unconfirmed local name never vetoes). Key: new `enter_chat` export `ec_press_key` (ABI 1.1.0, Interception only, no message/SendInput fallback) → `GameChat.press_key` / `press_game_key`, under the same `bot_input_released` handoff as chat.
Affects: member only, in the member tick before `decide`. One Y key press per leader invite (every 20 s until party memory shows the join). Side effect candidate: if the popup is not open (closed by hand, refused, late), Y reaches the game as a plain key. Leader invite timing unchanged. Monitor: member Workflow step `Accept`; leader Invite step counts accept notices. Wire: leader and member run this build together; the member PC needs the rebuilt `enter_chat.dll` 1.1.0.
Consent: user chose Y, socket notice only (no OCR), and approved the scope.
Result: simulated: notice → Y after the delay (scancode 0x15), skip when already in party / addressed to another roster name; DLL export loads and rejects a bad hwnd. Not run in game.

## 2026-10-22 — party: leader session id; member resets on a new leader run

Intent: every leader Start is a new party run. The member cannot tell from the socket alone whether the leader restarted (a reconnect looks the same), so the leader stamps a run id on every frame and the member starts its party state over when the id changes, then takes the new leader settings.
Shared: `websocket.party_orders.new_leader_session` / `leader_session` (8-hex id, made at leader Start in the run loop). `leader_decisions.publish_body` adds `session` to every leader frame (policy, rally, recovery, decision). `MemberOrders.ingest`: a new `session` drops gather / recovery / policy / arrived before the frame is read; `take_session_change()` reports it once. Controller `_reset_member_for_leader_session`: `PartyMemberManager.reset_for_new_leader_session()` (policy overlay off → own profile knobs, formation trail cleared), policy apply signature and ack records cleared, so the new policy is applied and confirmed (`policy_ack`) as on a fresh member start. At every Start both roles clear `member_orders` and `policy_acks`.
Affects: member party state only, on the first leader frame of a new run (first contact counts too). A member reconnect to the same leader run keeps everything. Rally walking toward an old gather point stops; the new run's rally replaces it. Join-map world nav in progress and solo decision state are not touched. Wire: leader and member must run this build together.
Consent: user asked that a newly started leader resets all member party logic to the leader's new settings.
Result: simulated: same-id resend keeps orders, a new id drops the old rally/arrived and applies the new policy (turret → moving). Monitor shows the session id on the Server (leader) / Connect (member) step. Not run in game.

## 2026-10-22 — enter_chat: probe the Interception keyboard slot (fixes `/초대` "failed: text")

Intent: Hangul in chat lines is sent only through Interception. `ec_ic_open` always used keyboard slot 1 (`interception_is_keyboard` is only a range check). On this PC the keyboard is slot 2 (autologin probe: `keyboard=2 mouse=12`); slot 1 returns 0 strokes, so every Hangul key of `/초대 번개공격` failed while `/`, space, and Enter went through fallbacks → `EC_E_TEXT` with no message.
Shared: `ec_keyboard.c ec_ic_open` now probes slots 1–10 with a key-UP of scancode 0x04 (no-op, same probe as `autologin/bot/win/interception.py`) and keeps the first slot that accepts; none → `EC_E_INTERCEPTION`. `EC_E_TEXT` now reports "N of M character(s) failed (keyboard slot X)".
Affects: every `send_chat_line` caller (party invite / leave). Mouse, login input, and decisions are unchanged.
Consent: user asked to find and fix why the party invite failed.
Result: live probe on this PC: slot 1 → 0, slot 2 → 1, slot 3 → 1. DLL rebuilt (BUILD_OK; the loaded copy was renamed to `bin/enter_chat.old.dll`, picked up after the bot restarts). Not run in game.

## 2026-10-22 — party start: invite only after the member confirms the policy (`policy_ack`); `/초대`; monitor workflow

Intent: the leader start runs in order: socket server → member sockets connect → `party_policy` sent → each member applies it (temporary overlay) and answers `policy_ack` → only then `/초대 <name>` for that roster name → rally → hunt. The in-game invite command is `/초대 <name>` (was `/파티 <name>`, which the game does not accept).
Shared: `invite.PartyInviter.tick(ready=…)` skips names that have not confirmed (no invite, no retry clock). `invite.LeaderInvites(policy_acked=…)` replaces the "all sockets or 20 s" shortcut; `POLICY_WAIT_S` is removed. `deliver_chat` turns an exception (e.g. missing `enter_chat.dll`) into a failed send instead of an uncaught invite-tick error, and posts typed / FAILED lines to the monitor. `websocket.party_orders`: `party_policy` now carries `policy_id` (hash of the knobs), new `policy_ack` frame, `PolicyAcks` / `policy_acks` (cleared by `reset_orders` and at Start). `comms.ingest.drain_leader_reports` books acks (a member that does not know its name yet sends `member`; booked to the only unconfirmed roster name). Member `_member_party_tick` acks every applied policy frame (leader resends every 5 s). `party_monitor_snapshot` adds `session.workflow` (leader 7 steps, member 6) and roster `policy_acked` / `invite_failed`.
Affects: leader party invites only. A member bot without this build never confirms, so it is never invited until it is updated (wire: leader and member must be deployed together). Rally, hunt, combat, HP, movement, and login are unchanged. Party monitor: left dashboard keeps its width (right column fixed ~420–640 px, wrapping badge rows), Workflow card on top, log split into leader messages (top) and member messages (bottom).
Consent: user asked for this workflow (socket → policy → member response → invite) and the `/초대` command; hard ACK (no timeout) as described.
Result: logs 03:48 and 04:03 showed `/파티` then `/초대` "typed" while the main log had `Party invite tick failed: enter_chat.dll not found` every 20 s — `Engine/analysis/enter_chat/bin` was never built after the move. Rebuilt with `build.bat` (BUILD_OK, DLL loads). Gate simulated: no invite before ack, invite right after, stale `policy_id` rejected, failed chat counts as failed. Monitor rendered offscreen. Not run in game.

## 2026-10-22 — Chinese game language uses the new `_ch` teleporters

Intent: Shopping Practice now has Chinese dialog rows for the three new field teleports (`teleport_giran_dragonvalley_ch`, `teleport_silver_desertoasis_ch`, `teleport_woodbeck_desertoasis_ch`). Starting with the UI game language set to Chinese still planned the Korean ids, because teleporter selection followed account `SHOP_LOCALE` (often `ko`) instead of game language.
Shared: `resolve_world_nav_teleporter_ids`. Omitted locale now reads `get_game_language()` (set from the profile at Start). `zh` still prefers `<base>_ch` and falls back to the Korean row only when `_ch` is missing. An explicit `locale=` argument is unchanged. Buy/sell ids still follow account shop locale. Combat, HP, and login are unchanged.
Affects: every world-nav NPC teleporter, including the older dungeon gates that already have `_ch` rows. Korean game language keeps the Korean ids even when the account server locale is Chinese.
Consent: user (“게임 언어를 중국어로 선택하고 프로젝트를 실행시킬때 정상동작하도록 구현해줘”).
Result: with game language `zh`, the three `_ch` ids are selected and the Korean twins are not. With `ko`, the reverse. Not run in game.

## 2026-10-22 — world-nav: same-map talking scroll competes on cost

Intent: Farm on mainland Dragon Valley from another mainland tile planned as walk~560 to Giran NPC then field TP. User expected talking-scroll to the Giran hub (cheaper). Planner had `allow_scroll = … and not same_map`, so scroll never entered the cost graph on same map.
Shared: `ready/planner.py` — drop the same-map ban; keep `not near_entrance`. Meta-search already compares `scroll_cost_tiles` vs walk.
Affects: same-map world-nav (scroll vs walk vs field TP). Cross-map and near-entrance behavior unchanged.
Consent: user (“같은 맵이라도 비용계산해서 싼쪽으로… 수정해줘”).
Result: implemented; replay start(33961,33257)→farm picks scroll→giran hub→field TP.

## 2026-10-22 — wire teleport_giran_dragonvalley into world-nav (goal filter + zh)

Intent: User added `teleport_giran_dragonvalley` (field_land, world_nav) in Shopping Practice. Engine already loaded the link, but (1) zh locale looked up missing `_ch` and dropped it, (2) planner treated any dungeon_gate shutter as a 15-tile blink, so Gludin→dungeon7 beat Giran→Dragon Valley on paths to map 30.
Shared: `filter_teleporter_links_for_goal` / `dungeon_gate_serves_goal` (dungeon_gate only if dest serves goal map via floor_ladder); `resolve_world_nav_teleporter_ids` falls back to Korean base when `_ch` absent; YAML `teleport_giran_dragonvalley_ch` (same land/adena; recalibrate zh option UV in the tool).
Affects: world-nav teleporter selection. Buy/sell/combat/HP/login unchanged. Giran→53 dungeon_gate still plans.
Consent: user (“shopping practice로 추가… 엔진에서 정확히 동작하려면… 고칠거 있음 고쳐”).
Result: from Giran NPC → map30 uses field_land; unrelated shutters no longer steal DV routes; zh resolves `_ch`.

## 2026-10-22 — NPC teleporter field_land (mainland region TP, e.g. Giran → Dragon Valley)

Intent: Shopping Practice / world-nav already model dungeon shutter TPs (`destination_dungeon` → nearest `ground_enter`). User needs same dialog flow for village teleporters that land on another mainland field (same mapId, new xy; e.g. Giran option → Dragon Valley for 187 adena) without walking from the village.
Shared: `ShoppingBehavior.teleport_kind` (`dungeon_gate` | `field_land`) + `land_map_id`/`land_world`; Behaviors editor Teleport kind + Land map/xy + Fill land from memory; `list_land_map_choices`; `npc_teleporters` field links; planner allows same-map field TP only (dungeon_gate still off-map); session settle waits near planned land and retargets next walk (no gate rewrite).
Affects: world-nav plan/execute for teleporters; Shopping Practice Behaviors tab; probe catalog labels. Buy/sell/login/combat/HP unchanged. Existing dungeon_gate YAML rows keep working (kind defaults to dungeon_gate).
Consent: user (“엔진의 연결부문에까지 제대로 구현… 다른 영향이 없게”).
Result: implemented. No sample field_land row added to yaml — calibrate per destination in the tool.

## 2026-10-22 — ivory tower land cell, and no entrance ring after the map flips

Intent: a click that already entered ivory tower floor 1 counts as landed at `(32763, 32902)`. A second entrance ring does not run once the live map is the destination, so the cursor stays off the desktop corner. When the live cell is outside the planned interior, the following walk starts at the live cell.
Shared: `ground_enter:oren-ivory` `to`. `dest_entry_pose` / `run_gate_click` / `_one_gate_attempt`. `note_gate_result` calls `retarget_walk_from_after_gate` when the landed cell differs from the planned interior and the next walk still starts there. `gate_land_watch`, combat, HP, and login are unchanged.
Affects: every world-nav and dungeon-floor gate click. A landing within 24 tiles of the planned interior still succeeds as before. A dest-map pose still within 24 of the entrance or the pre-click cell fails the gate with `dest map with source xy` and does not advance. A dest-map pose outside both neighborhoods succeeds and, when the next walk's `from` is the planned interior, that `from` moves to the live cell and its stored polyline is dropped. Floor routes share the same click helper, so they also stop the ring and accept that landing by map id.
Consent: user agreed to this scope (fix the ivory tower interior cell, and do not circle the entrance once the destination map is live).
Result: both edge files use interior `(32763, 32902)`. The 02:44 pose `(32763, 32902)` classifies as landed against that cell, and as relocated against the old `(32765, 32866)`. A dest map still sitting on `(34041, 32156)` classifies as stale. Not run in game.

## 2026-10-22 — ivory tower floor 1 cursor centers on (34041, 32155)

Intent: after the Oren teleporter lands in front of ivory tower floor 1, the dungeon-entrance cursor circles `(34041, 32155)` on the mainland. The previous center was `(34041, 32158)`.
Shared: edge `world_nav:ground_enter:oren-ivory` `from` only. `run_gate_click` still circles that cell. Teleporter clicks, gate rewrite, and the portal rows `tmo:4:127` / `tmo:4:128` stay as they are.
Affects: world-nav entry into ivory tower floor 1 (`teleport_oren` / `teleport_oren_ch`, destination map 75). A landing at `(34041, 32158)` is still within the 5-tile approach, so the circle starts without an extra walk. Combat, HP, and login are unchanged.
Consent: user asked to move the entrance cursor to mainland `(34041, 32155)` and circle there.
Result: both the live `map_transitions.json` edge and the provider `30_edges_ground_enter.json` now use `(34041, 32155)`. Not run in game.

## 2026-10-22 — unread body pose no longer freezes a loot hop

Intent: a loot hop whose body slot stays unread must not treat that as "still walking" for the rest of the process. The same live tile for 0.8s follows the standing path and repeats the ground click. A tile that is still changing keeps the click. The reader itself retries a failed module/player walk instead of caching the failure, and opens WinNotify shared.
Shared: `body_pose._ensure` / `read_action` / `body_is_moving`; `loot_hop._loot_click_still_open` and the `tick_loot_item` hold. `classify_ground_reclick`, `try_movement_unstick`, and dungeon `unstick_disabled` are unchanged. A failed read is still None, not standing.
Affects: loot approach on a dungeon and on the field. Travel and search still hold while the slot is unread. While the slot reads a real walk, the hop holds as before. One missed sample during a walk waits out the 0.8s window before a reclick. If the live tile is frozen while the character is actually walking and the slot is unread, that reclick can cancel the step.
Consent: user agreed this scope (recover the pose read; loot uses the live tile when the read stays empty; do not change the reclick classifier or dungeon unstick).
Result: pose open no longer sticks after a failed base walk, and a loot hop at a still tile reclicks while the slot is unread. Not run in game.

## 2026-10-22 — a nearby body no longer pulls a loot click off the item line

Intent: when the guide toward an item is clear, the hop click stays on that line. A living body inside the 10-tile window moves the click aside only when it, or a wall, actually closes the guide hop.
Shared: `choose_body_click`. It now takes `_farthest_guide_click`, then `_adjacent_guide_step`, and calls `plan_avoidance_click` only when those two have no click. `plan_body_click`, `click_clear`, and `unstick nearby` are unchanged.
Affects: loot approach, world-nav hops, and farm search, because they all click through `plan_body_click`. A monster standing off the line no longer bends the 5-tile hop. A monster or wall on the line still steps aside. The 5-second nearby sweep still runs when the tile does not change.
Consent: user agreed this scope for the main tree and the release they ran (`release\portable\ZF`).
Result: on an open field, adena 292's off-line body `(3,-7)` now clicks `(612,1211)` on the item line; the old click was `(612,1206)`. Adena 324's body six tiles north now clicks `(368,1259)` on the item line. A body standing on that hop still steps aside (`(612,1206)` and `(368,1255)`). Release pyd and `SHA256SUMS.txt` updated in `release\portable\ZF`, and the same two files replaced in `release\ManmabotV1.zip`. Not run in game.

## 2026-10-22 — teleporter door swap also moves the inside walk start

Intent: after the silver-knight teleporter lands nearer the other training-dungeon floor-1 door, the inside walk starts at that door's landing cell. The character then walks to the first patrol point. Standing still on `world nav wait land xy` after a successful mapId 4→25 entry ends.
Shared: `retarget_walk_from_after_gate`, called from `_rewrite_next_gate_from_live_pose`. The gate rewrite still picks the nearest `ground_enter`. `_start_walk` still waits until live xy is within 24 tiles of the walk's `from`. Combat, HP, login, and patrol order are unchanged.
Affects: world-nav trips whose teleporter step is followed by a gate and then a walk on the destination map. Training dungeon floor 1 is the case in `v77.log`: planned door `tmo:4:85` interior `(32738, 32805)`, live door `tmo:4:88` interior `(32808, 32810)`. A walk whose `from` is not the replaced gate's old interior is left as planned. The stored A* polyline for that one walk is dropped because it started at the other door; the hop still paths from the live cell to the same goal.
Consent: user agreed to this change after the v77 review.
Result: retarget checked on the v77 step pair (walk `from` moves to `(32808, 32810)`, a same-door plan stays put, a walk that does not start at the old interior stays put). Not run in game.

## 2026-10-21 — an attacked-me lock stays until that monster is dead

Intent: while the current sticky has attacked me and is still alive, a lower known level does not take the lock. When the lock is empty, the lowest known level is engaged, then held the same way. A sticky that has not attacked me still yields immediately. Who attacked first is the monster already on the lock; monsters that appear in the same scan are still ordered by known level. Unknown level still ranks after every known level. The previous target is not given up.
Shared: `prefer_attacked_me_sticky`. `attacked_me_rank` still orders an empty lock. `list_attacked_me_targets`, `rebind_sticky_target`, dungeon wall release, cursor reject, species-filter idle, bait, map change, and the exp-kill release stay.
Affects: farm engage, travel engage, and world-nav walk combat. Heal still waits while the living sticky is held, so a higher-level first attacker delays heal. Loot still waits. Field wall detour still holds the lock. A dungeon shot line that closes still drops the lock, and the next empty-lock choice is the lowest known level that can be shot.
Consent: user agreed after the review (keep the monster already being attacked until it dies; then take attacked-me monsters from weakest, each until death).
Result: the lower-level steal is gone. Not run in game.

## 2026-10-21 — silver knight teleporter lands at desert dungeon floor 1

Intent: a trip to training dungeon floor 1 uses the silver knight village teleporter the same way Gludin and Giran do. Talking scroll to 은기사 마을/텔레포터, click that NPC, land in front of a floor-1 door, then the existing cursor check enters. The long walk from the village to `(32950, 33502)` or `(32970, 33511)` is no longer the planned approach.
Shared: `teleport_silver` and `teleport_silver_ch` `destination_dungeon` is 25 (사막 던전 1층). The existing NPC-teleporter link, shop click, and gate rewrite are unchanged. Gludin (7) and Giran (53) are unchanged.
Affects: world nav into training dungeon floor 1, and any deeper desert floor whose world-nav stop is that entrance. A character already within 50 tiles of a floor-1 door still walks and clicks it. Combat, HP, and login are unchanged.
Consent: user (use the silver knight teleporter to reach desert dungeon floor 1, the same way the village teleporters reach Gludin and Giran).
Result: both behaviors now name map 25. That map's mainland doors are 130 and 126 tiles from the NPC `(33080, 33385)`, inside the 400-tile link. The old value 7779 is the PC clone and has no mainland door, so the planner scrolled to the village and walked. Not run in game.

## 2026-10-21 — path refusal logs P, M, and the closed tile together

Intent: one path refusal can be replayed from a single line. The line names the character tile, the monster tile the shot used, the closed tile, the live MapSubsystem id, and the loaded pack. The sampled tile list is debug only.
Shared: `attack_line_refusal_text` reads `attack_line_block` and `tiles_on_segment`. `describe_attackable_filter_skips` still returns the same summary and, when asked, fills that line. The dungeon sticky release uses the same line. `tiles_on_segment`, `diagonal_open`, `attack_line_clear`, and `can_engage_target` are unchanged.
Affects: screen-combat skip logs and a dungeon sticky release when the shot line is closed. Who is attacked, give-up, and blacklist stay the same. Field shots, travel, loot, and HP are unchanged.
Consent: user asked for this line before the next hunt, and said not to change the segment or diagonal rules until a real case shows a walk-blocked tile that the game still lets an arrow cross.
Result: the line is written. Not run in game.

## 2026-10-21 — dungeon attack skip logs the closed nav tile

Intent: when a straight shot is refused, the combat log names the first nav tile or fence that closed it. Who can be attacked stays the same.
Shared: `los_block_label` (same walk as `line_of_sight_clear`). `describe_attackable_filter_skips` appends `@block=(x,y)` or `@fence=(x,y,N|E)` on a path skip. The dungeon sticky release log `wall/fence — dungeon skip` includes that same label. `attack_line_clear` and `can_engage_target` still return the same yes or no.
Affects: dungeon screen-combat skip lines, and dropping a dungeon sticky because the shot line closed. Field shots, travel, loot, and HP are unchanged.
Consent: user agreed this scope (log the blocking tile only; do not change the engage decision).
Result: label added on both logs. Checked against a small grid: a black middle tile, two closed diagonal shoulders, and a north fence match the old clear/blocked result. Not run in game.

## 2026-10-21 — dungeon teleport with no heal or potion goes to the world tree

Intent: after one escape teleport off Talking Island and the mainland, HP still under the operator retreat percent, heal blocked by the existing MP floor, and no HP potion, start the existing Mother Tree trip instead of waiting for 95%. When HP is already above that retreat percent but still under 95%, and neither heal nor a potion can run, leave the retreat and resume the hunt. Heal or potion still fills to 95% everywhere. Scroll landings keep the 50% mother-tree check. A mother-tree trip still stands until 95%.
Shared: `maybe_mother_tree_before_passive_wait`, `retreat_exit_ready`, `begin_retreat(use_mother_tree=True)`, `finish_retreat`. `apply_hp_actions`, `apply_inplace_hp_support`, the one under-fire teleport, and potion sides are unchanged.
Affects: HP retreat after the escape teleport has landed, and any HP retreat that can no longer heal or drink. MP retreat, return retreat, and recharge at the tree stay on their current exits.
Consent: user agreed both gates (dungeon post-teleport mother tree; resume hunt above the retreat percent when heal and potion cannot run).
Result: both gates added. Not run in game.

## 2026-10-21 — a filtered species is attacked only while it is hitting me

Intent: a species the operator filter skips is never chosen, and an existing lock on it is dropped, unless its AttackAction targets the character this tick. One earlier hit is not enough. Allowed species still keep the attacked-me latch and finish-kill.
Shared: `sync_attacks_me_force_targets` (`attacking_me_now`), `species_filter_blocks_target`, `list_attacked_me_targets`, `rebind_sticky_target`, `_living_same_species`. `nearest_attackable` still skips every filtered species. Session target blacklist and give-up stay.
Affects: field and dungeon engage. A filtered monster that stops attacking is released the same tick, including a 2-tile rematch onto another of that species. A filtered monster that is attacking can still take the lock.
Consent: user asked to make sure a blacklist monster is not attacked when it is not attacking the character.
Result: current-tick flag added and idle filtered targets released. Not run in game.

## 2026-10-21 — dungeon fights a blacklisted species that is attacking

Intent: in a dungeon, a monster whose AttackAction targets the character is engaged even when the operator species filter would otherwise skip it. A blacklisted species that is not attacking stays off the normal attack list. Field self-defense was already this way.
Shared: `monster_hitting_me`, `list_attacked_me_targets`, `nearest_attacks_me_force`, `continue_sticky_combat`. `_dungeon_ignores_blacklisted_attacker` is gone. Session target blacklist (`blacklisted_target_ids`), give-up, dungeon line of sight, and the dungeon path cap stay. `nearest_attackable` still skips a blacklisted species that has not attacked.
Affects: dungeon hunt and patrol engage, and HP retreat while under attack. A blacklisted attacker can take the sticky lock and make `monster_hitting_me` true, so the one teleport-under-fire attempt can run. Field loot and field combat are unchanged.
Consent: user agreed this scope (dungeon attackers bypass the species blacklist; non-attackers stay filtered; session blacklist and give-up stay).
Result: filters removed. Not run in game.

## 2026-10-21 — body reader finds MyPlayer on the current entity list

Intent: ground clicks repeated the same screen point for a full second because the body slot read failed. The character walked past adena, so the in-range F4 never ran. Walk and stand class ids were already current. The player object was still looked up with the previous manager, actor list, and MyPlayer id.
Shared: `body_pose._find_my_player` / `read_action`. Manager, actor vft, and MyPlayer come from `entity_offsets.txt` (`0x16ED640`, `0x11E9430`, `0x11EC4C8`). The click-until-walk loop, loot approach, and F4 press are unchanged.
Affects: ground-click stop, travel reclick, and loot hop hold. A readable walk stops the repeat. A readable stand lets the next loot tick correct or press F4 once the tile is within one. Combat clicks, potions, and login do not read this slot.
Consent: user (update it so the approach-then-F4 workflow works).
Result: finder reads the live entity table. A live read returned walk `0x11EB7B8` and move command `0x11EBA50`. The approach-then-F4 path was not replayed in a hunt.

## 2026-10-21 — world nav reuses white-tile component ids

Intent: the first world-nav plan was flooding the mainland once per hub inside the decision tick, so the character stood for about 20 seconds after the startup buffs. The route itself was a scroll plus a 155-tile walk.
Shared: `WalkService.same_component`, `label_walk_components`, `shared_walk_service`, `WorldNavPlanner` (one shared walk service), `_warm_walk_components` on map load. White-tile 4-connected ids are stored beside `nav.png` as `walk_components/`. They are not `nav_prebuild/labels.npy`. Ground A* still runs on the chosen walk. The 80,000-cell optimistic flood remains only when those ids cannot be built.
Affects: the first world-nav plan after Start, and later plans in the same process. Live hops, combat, loot, and HP still use the fence-aware prebuild.
Consent: user (prepare the static map once and reuse it; do not change the route).
Result: closed yards and blocked corners match a finished flood. The logged plan no longer lands at 은기사 마을/여관. Exact white-tile ids allow 은기사 마을/허수아비 수련장, then a 106-tile walk (cost 116). The old 155-tile inn walk (cost 165, 27.8s) was a false wall left by the 80,000-cell flood. That 106-tile A* matches a fresh PNG grid. Map load reads the component files and the NPC catalog. After that the same plan is about 0.4s, and a repeat is about 0.2s. Not run in game.

## 2026-10-21 — body and command class RVAs follow bodyact

Intent: the live body reader was still on the 10.14 class numbers. bodyact on the current client reads stand as `VFT_BREATHACT` `0x11EB4D8`. Copy that table into the bot and the action monitors.
Shared: `body_pose.py` `BREATH_VFT` / `MOVE_VFTS` / `BODY` / `CMD`, `action_timeline.py`, `interact_watch.py`, `probe_my_anim.c` defaults, print_state attack-action default. Walk is still MovingAction, walk-back is still MovingBackAction. Decision branches are unchanged.
Affects: `body_is_moving`, ground-click stop, travel reclick, loot hop hold, action view labels.
Consent: user (if bodyact is the accurate one, bring its constants into the project).
Result: constants written. Shop, default, fixed-frame, npc-state, and zap-wand have no bodyact key, so those old numbers were dropped. Not run in game.

## 2026-10-21 — memory readers follow the 26.10.20.2001 registry

Intent: point the live readers at the current client using `D:\dist` registry RVAs. HP/MP/level come from CharacterData (`STAT_*`), world position from `PLAYER_X`/`PLAYER_Y`. The retired HUD block is not used. Dialog watch list stays the existing six windows.
Shared: offset files, `lc930` registry RVAs, `shop_listen.c` anchors, and the print_state/realtime_monitor vital decode. Decision, login, movement, combat, and potion code are unchanged.
Affects: every live memory read (player, entities, bag, hotbar, buffs, dialogs, shop).
Consent: user (update the readers so the project runs on the current game, using how dist reads the fields whose constants were not refreshed).
Result: constants written. `print_state.new.dll`, `realtime_monitor.new.dll`, and `shop_listen.new.dll` built; the live copies were locked, and the readers load the newer image. Not run in game.

## 2026-10-21 — ant cave floors 2–8 use their own mainland doors

Intent: ant cave floors 2 through 8 are entered at their own mainland doors, the same way talking island dungeon floor 1 is found and entered. Floor 9 stays without a mainland door.
Shared: `needs_floor_route` treats `ant_cave_dungeon_F2` through `F8` as direct field doors. World nav keeps the goal on that floor's map, skips interior ladders, and uses that floor's mainland ground-enter cells. `plan_floor_steps` is not used for these floors. Floor 1 and other dungeon stairs are unchanged.
Affects: a hunt set to ant cave floor 2, 3, 4, 5, 6, 7, or 8. The walk goes to that floor's mainland cell and the existing gate clicks it. Combat, HP, and login are unchanged.
Consent: user (connect floors 2–8 with the database entrance cells, the same way talking island dungeon floor 1 is entered, then verify each link from the mainland).
Result: from mainland `(33092, 33407)` with scroll and NPC teleports off, each floor plan is one field walk and that floor's own door. Floor 2 `(32912, 33223)` → `(32799, 32754)`, floor 3 `(32789, 33256)` → `(32776, 32730)`, floor 4 `(32845, 33292)` → `(32787, 32794)`, floor 5 `(32836, 33171)` → `(32795, 32744)`, floor 6 `(32796, 33189)` → `(32796, 32741)`, floor 7 `(32926, 33249)` → `(32800, 32781)`, floor 8 `(32757, 33205)` → `(32769, 32803)`. Not run in game.

## 2026-10-21 — route chaining stays inside dungeons

Intent: the route-cell chain belongs on dungeon walks only. Field travel keeps the straight-line extend and still waits for arrival on a bend.
Shared: `emit_travel_hop`. A dungeon hop calls `_chain_route_click`. A field hop calls `_straight_extend_waypoint` when the body is walking and two tiles from the click. Loot, search, combat, HP, and login are unchanged.
Affects: dungeon patrol and dungeon floor walks. Field travel, farm entry, and retreat use the straight-line extend again.
Consent: user (this direction, and only inside a dungeon).
Result: implemented. The route-click check still passes. Not run in game.

## 2026-10-21 — travel chains the next clear route cell while walking

Intent: dungeon walks stopped at every bend, and stopped for up to 5 seconds where a corridor narrows, because the next click was issued only on a straight line or after the current click had finished.
Shared: `emit_travel_hop` and `_next_route_click`. While a hop is active the live tile clicks the farthest route cell whose client walk is still clear, including a turn. A closed door stays the click. An open door still clicks the tile just past the doorway. The click does not pass the goal. A sidestep off the route stays until a route cell is clear again. The 5 second unstick remains only when no route cell and no sidestep exist. Hop caps stay dungeon 3 and field 5. Loot, search, combat, HP, and login are unchanged.
Affects: field travel, farm entry, retreat, and dungeon patrol. A straight hall still walks in hops of at most that cap. A bend clicks the next clear cell as soon as the live tile can walk it. A narrow bend shortens to 2 or 1 tile instead of waiting.
Consent: user (chain the next clear route cell from the live tile, including turns, and do not wait out the 5 second unstick on a wall).
Result: implemented. A local route-click check passed for a straight hop, a corner that clips, a one-tile shorten, a body on the path, and the goal limit. Not run in game.

## 2026-10-21 — training dungeon return walks back through each yard

Intent: from floor 4 the way to 은기사 마을 leaves floor 3 at `(32806, 32814)` onto `(32880, 33512)`, enters floor 2 at `(32910, 33503)`, leaves floor 2 at `(32802, 32816)` onto `(32927, 33516)`, enters floor 1 at `(32950, 33502)`, and leaves floor 1 at `(32809, 32810)` onto `(32970, 33512)`, then walks to the village.
Shared: five `floor` rows in `floors_entrances.txt`, each using that direction's own cell. `plan_floor_steps` still stops on the goal floor. World nav skips a same-map walk when the nav grid's walk ends before the other cell. A mainland floor walk that is still open after 2000 cells is not a door yard.
Affects: a walk from floor 4 to a mainland point, and a floor route from floor 4 down to floor 1. Floor 2, 3, and 4 hunts that start on floor 1 still use the forward doors. A talking scroll can still skip the walk. Combat, HP, and login are unchanged.
Consent: user (leave floor 3 into its yard, enter floor 2, leave by the other exit, enter floor 1, leave by the field exit, and walk to the village, using the database cells the same way as the earlier doors).
Result: with the scroll off, the plan is stair to floor 3, `(32806, 32814)` → `(32880, 33512)`, walk to `(32910, 33503)` → floor 2 `(32733, 32813)`, walk to `(32802, 32816)` → `(32927, 33516)`, walk to `(32950, 33502)` → floor 1 `(32738, 32805)`, walk to `(32809, 32810)` → `(32970, 33512)`, then 126 tiles to `(33092, 33407)`. The forward floor 4 route is unchanged. Not run in game.

## 2026-10-21 — world-tree return waits until mapId and xy match

Intent: after Teleport to Mother, the return plan was sometimes armed while absolute xy was already the world tree and MapSubsystem mapId was still the hunt floor. That sample is same-map, so the planner walked, and a dungeon id was treated as already on the floor.
Shared: `arm_world_nav` defers while xy is outside that mapId's nav image, and on `post_retreat` while mapId is still the departure dungeon floor and xy jumped more than 40 tiles. `_dungeon_live_pack` does not report the floor when xy is outside its image. The first Teleport to Mother press in a retreat stores the departure pose; a recast does not replace it. `finish_retreat` and the planner `same_map` rule are unchanged.
Affects: the world-nav arm after a mother-tree retreat. A shop return or hunt re-entry whose xy is outside the live map image waits the same way. Mainland hunts share mapId 4 with the tree, so they still plan on that tick. Combat, potions, login, and an in-progress walk are unchanged.
Consent: user (defer the return until mapId and xy name the same map).
Result: implemented. A local image-bounds check passed for mainland versus a dungeon floor. Not run in game.

## 2026-10-21 — training dungeon floors stay in one line

Intent: floor 1's courtyard `(32950, 33503)` cannot walk straight into the floor 3 door. The route goes through floor 2, out to `(32910, 33504)`, then into floor 3 `(32807, 32813)`, then the existing stair to floor 4.
Shared: `dungeon_floor_route` now keeps mainland steps on one world tile, and may enter the mainland again when the next yard is a different place. `plan_floor_steps` callers are unchanged. Door rows already in `floors_entrances.txt` were not edited.
Affects: training dungeon floor 3 and 4 routes. A floor 2 hunt still stops at `(32803, 32815)`. Other dungeon stairs are one tile per cell already. Combat, HP, and login are unchanged.
Consent: user (the linked doors are one line, so the first courtyard must not enter floor 3 directly).
Result: from floor 1 the floor 4 route is courtyard `(32927, 33515)` → floor 2 `(32803, 32815)` → `(32732, 32814)` → mainland `(32910, 33504)` → `(32880, 33511)` → floor 3 → `(32723, 32742)` → floor 4 `(32799, 32798)`. The direct walk from `(32950, 33503)` to `(32880, 33511)` has no path. Not run in game.

## 2026-10-21 — routine timer counts only inside the hunt zone

Intent: the left routine countdown starts when the character enters the hunt zone, pauses outside that zone and while the project is paused, and returns to the full duration on Stop. Reaching the zone center must not wipe time already counted from the edge.
Shared: `RoutineCursor` no longer starts in `from_entries`, `advance`, or `mark_arrived`. `sample_routine_zone_clock` opens and closes it. `_resume_stay_clocks` no longer resumes the row clock. `_routine_clock_from_board` shows "Moving" until the battle row is inside its zone.
Affects: the routine row duration. Travel, time outside the selected rectangles, and pause do not consume those minutes. A field revive keeps the saved seconds instead of starting at zero. Dungeon retreat still holds the clock, and time off the hunt floor is not counted. Break rows still count while the project is deciding, including the walk to a rest spot. The per-area farm stay clock is unchanged. Combat, movement, HP, and login are unchanged.
Consent: user (proceed with the timer rules from the prior analysis).
Result: implemented. A local sampler check passed. Not run in game.

## 2026-10-21 — second courtyard door enters training dungeon floor 3

Intent: from mainland `(32910, 33504)` the character walks to `(32880, 33511)` and the existing cursor check enters training dungeon floor 3 `(32807, 32813)`.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: floor routes that use this door. A start on `(32910, 33504)` walks to the door and gates into floor 3. A floor-3 hunt that begins on floor 1 walks the coarse mainland grid from the first courtyard `(32950, 33503)` straight to this same door. Floor 4 then continues on the existing floor-3 stair `(32723, 32742)`. The floor-2 arrival route is unchanged. Combat, HP, and login are unchanged.
Consent: user (walk from `(32910, 33504)` to `(32880, 33511)` and enter floor 3).
Result: the router emits that walk and a floor gate `(32880, 33511)` → `(32807, 32813)`. Mainland walk on the coarse grid is 8 cells. Not run in game.

## 2026-10-21 — training dungeon floor 2 other exit to the mainland

Intent: floor 2 `(32732, 32814)` is a floor gate out to mainland `(32910, 33504)`. The character walks to that cell and the existing cursor check clicks it.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: a floor route that must leave floor 2 through this door. The floor-1 to floor-2 arrival route is unchanged and still stops at `(32803, 32815)`. Combat, HP, and login are unchanged.
Consent: user (connect this exit the same way: walk to the cell, cursor check, click).
Result: from floor 2 `(32803, 32815)` the route is one walk to `(32732, 32814)` and a floor gate to mainland `(32910, 33504)`. The landing nav cell is walkable. Not run in game.

## 2026-10-21 — courtyard door enters training dungeon floor 2

Intent: the courtyard cell `(32927, 33515)` is a floor gate into training dungeon floor 2 `(32803, 32815)`. A character who has left floor 1 into the courtyard walks to that door and the existing cursor check enters floor 2.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. One `floor` row was added in `floors_entrances.txt`.
Affects: a floor-2 hunt that is already inside this dungeon. The planned steps are a walk on floor 1, the courtyard gate, a walk across the courtyard, then the floor-2 gate. Floor 3 and 4 still have no route from floor 1. Floor 1 hunting, combat, HP, and login are unchanged.
Consent: user (connect the courtyard to floor 2 the same way as the floor-1 courtyard gate).
Result: from floor 1 `(32808, 32810)` the route is walk `(98, 166)`, gate `(32738, 32806)` → mainland `(32950, 33503)`, walk mainland nav `(119, 346)`, gate `(32927, 33515)` → floor 2 `(32803, 32815)`. Both gates are floor gates. A route to floor 3 still fails. Not run in game.

## 2026-10-21 — training dungeon floor 1 exits into the courtyard

Intent: on training dungeon floor 1, the exit `(32738, 32806)` is a floor gate into the walled courtyard `(32950, 33503)`. The character walks to that cell and the existing cursor check uses it, the same way a stair is used.
Shared: `plan_floor_steps`, `_plan_dungeon_floor_session`, `_drive_dungeon_floor_walk`, and `_drive_dungeon_floor_transition` are unchanged. The new row is a `floor` link in `floors_entrances.txt`. Mainland `meta.yaml` now has `raw_map: "4"` so that list's name `아덴 대륙` resolves to the mainland pack.
Affects: floor-route search that starts on training dungeon floor 1. Floor 1 hunting, mainland travel, combat, HP, and login are unchanged. The courtyard's floor 2 door is not part of this link.
Consent: user (yes to this floor-1 courtyard gate only).
Result: the router sees `사막 던전 1층 (32738, 32806)` → `아덴 대륙 (32950, 33503)` as a floor gate. The walk from the field landing `(32808, 32810)` to that exit is 71 tiles. A route onward to floor 2 still does not exist, so a floor-2 hunt does not leave through this door. Not run in game.

## 2026-10-20 — exp rise releases sticky attack and the aim pixel

Intent: when level or exp rises while a monster is stuck as the current target, drop that sticky before rebind and do not click the last attack pixel again. The 30px cursor nudge is unchanged.
Shared: `sample_kill_progress` / `_release_sticky_for_kill` (`EXP_KILL_RELEASE_ENABLED` on). `excluded_target_ids` already hides that id until it leaves the monster list. `ActionExecutor._drop_killed_attack_aim` clears `_attack_aim_lock` for that id. `rebind_sticky_target` and `attack_click_search` are not reordered.
Affects: farm and dungeon engage, including `finish_kill`. Loot, the next monster, and search run on that tick only after the sticky attack no longer owns it. A kill that grants no exp still waits until the row leaves the list. An exp gain from something other than this kill also releases a held sticky.
Consent: user (release sticky on exp rise and invalidate the aim lock; do not add a cursor nudge).
Result: implemented. Not run in game.

## 2026-10-20 — Windawood floor 2 door, inner castle gate, ice floor 2 stair

Intent: Windawood Castle Dungeon 2F is entered at its own mainland door `(32551, 33478)`, not by climbing from floor 1. The inner castle is a gate from floor 1 `(32811, 32722)` to `(32742, 32789)`. Ice Queen 2F stays on the floor-1 stair `(32726, 32861)` → `(32755, 32870)`.
Shared: `needs_floor_route` treats only `windawood_castle_dungeon_F2` as its own field door. Edges `tmo:23:1` and `tmo:29:1` are live `floor_ladder` gates, so the existing cursor check runs them. Desert floors and other passages stay as they were.
Affects: world nav into these three maps, then patrol after arrival. Combat, HP, and login are unchanged.
Consent: user (connect these three first; do not also switch the desert floors).
Result: floor-2 no longer redirects to floor 1. Inside floor 1, the walk to the inner-castle gate is 139 tiles. Ice floor 2 plans as one walk plus a gate-compatible stair. A plan from Woodbec to either Windawood field door still fails A*: those door tiles sit in a 303-tile pocket walled off from the mainland field. Not run in game.

## 2026-10-20 — a closed door on the path is opened like an entrance

Intent: when this hop must cross a closed door, the cursor goes to that door's memory tile and circles the way a dungeon entrance is found. The first exact door cursor is clicked once.
Shared: `closed_door_before_click` and the travel click in `_search`. `sweep_click_closed_door` uses the entrance ring sizes and step. Open-door retarget, `not_permitted` walls, and the single door click stay. The entrance ESC, 20s retry, and map wait are not used.
Affects: travel, patrol, and loot-approach hops whose guide reaches a `close` door. Combat, HP, and login clicks are unchanged. A missed door cursor still uses the existing ground hop.
Consent: user (use the entrance cursor sweep on a closed door the path must cross, if that adds no other behavior).
Result: implemented. Guide check passed. Not run in game.

## 2026-10-20 — revert post-upload travel, attack aim, and cursor dump

Intent: keep only the income-bar runtime label. The uncommitted travel, attack re-aim, and cursor-reject dump from after `2f76607` go back to that commit.
Shared: `emit_travel_hop`, `retry_travel_hop_from_fresh` (removed), `attack_click_search`, `KnightCombatStrategy.attack`, `note_cursor_probe`. The income bar in `live_income_bar.py` stays.
Affects: world nav, farm entry, retreat, dungeon walks, attack clicks, and cursor probes. Those paths match the uploaded build again. `사슬 갑옷` is back on the keep list.
Consent: user (restore every post-upload change except the runtime next to gained adena).
Result: working tree restored to `2f76607` except `UI/ui_qt/shell/live_income_bar.py`. Not run in game.

## 2026-10-21 — party invites in one module (`_06_party/invite.py`)

Request: "파티초대를 한개의 모듈로 정리하라". Refactor only, behaviour unchanged.

`setup.py` (PartyInviter, roster names, leave check) and `chat_commands.py` (`/파티 `, `파티탈퇴`) are merged into `invite.py` and deleted. The invite glue that lived in `bot_controller` (`_send_party_chat`, `_party_ws_clients`, `_INVITE_UNSAFE_ACTIONS`, `POLICY_BEFORE_INVITE_WAIT_S`, the per-tick policy / socket / action checks, the "Party setup:" log) moved into `invite.LeaderInvites` (`start`, `tick`, `info`, `deadline`) with `deliver_chat`, `action_allows_chat`, `POLICY_WAIT_S`, `UNSAFE_ACTIONS`. The controller keeps the profile gate + party probe in `_run_leader_party_setup`, a one-line `_leader_invite_tick`, and holds `self._party_invites` (snapshot and rally deadline read it). The "Party setup:" log line now lists the names actually invited (self skipped).

Result: party suites 221 passing (2 skipped); new `LeaderInvitesTests`.

## 2026-10-21 — party start: 15 min invite + rally window, /파티 every 20 s, exclusions; member socket error text

Consent: user ("초대를 15 분시간을 크게 잡고 20초간격으로 초대를 보내 … 15분후에도 연결되지 않는 성원에 대해서는 배제하고 그 상태를 파티 모니터에 보여주어야 한다", "15분안에 파티초대 및 집결을 완결하고 그 후에는 사냥터에로의 진입"); AskQuestion: invites run in parallel with travel; error shown in status line + log + monitor; go = yes.

**Invites** (`_06_party/setup.PartyInviter`, replaces blocking `configure_party_from_roster`). Setup once: publish policy, `/탈퇴` if in someone else's party, arm the inviter. Each tick (`bot_controller._leader_invite_tick`): one `/파티 <name>` at most, every 20 s per roster name not in party memory; stops for a name once it is listed. First invites wait for all member sockets or 20 s (policy before invite, no longer blocking). A tick is skipped when the previous action was `shop_run` / `shop_stop` / `gate` / `teleport` / `use_talking_scroll` / `return_to_mother_tree` / `respawn` / `dismiss_level_up` (chat must not hit an NPC dialog or a teleport). Window 15 min from setup → names still missing are excluded; a late join clears the exclusion.

**Rally** (`LeaderStartRally.begin(deadline=)`): the same deadline. At the deadline the rally ends in any state (await_plan / hold_at / waiting), records `left_behind`, and the leader goes on to the hunt. Without a deadline the old 15 min from wait start still applies (tests).

**Monitor**: leader session `phase` {forming | rally | hunting, remaining_s, excluded, not_arrived}; roster rows add invites / invite age / state (pending · invited · joined · ready · not_arrived · excluded). Dashboard: PHASE badge, INVITE `n/m JOINED|FORMED|EXPIRED`, roster Invites + Status columns.

**Member socket error**: `party_ws_unreachable` text (EN/KO/ZH) in the header status; `start_error` in the party monitor note (red); log line unchanged.

Shared: `set_party_hold` path unchanged (rally waiting only). Not touched: member logic, turret / moving, combat, HP. Side effects: while the leader travels, invite lines are typed between steps; a teleport/NPC step skips that tick's invite.

Left as is (by request): member invite accept (not automated), member `recovery` handling, explicit party end / leave.

Result: implemented. Tests: `test_party_invite_setup` rewritten (inviter interval, join stop, window/exclusion, late join, unsafe action skip, leave first), `test_party_rally` shared-deadline tests; party suites 216 passing (2 skipped).

## 2026-10-21 — moving mode: member single-file trail in narrow areas; leader waits for lagging members

Consent: user — member "yes" (moving mode, NARROW → trail tile); leader "반수이상의 성원들이 뒤떨어지면 잠간기다리라, 6타일은 너무 작이 30 타일정도로 하라 그리고 파티장 대면부에서 타일개수를 설정하게 하라".

**Tactics cleanup** — `tactics/teleport_sync.py` and `tactics/stagger.py` deleted; `focus_fire` stays library-only. New `_06_party/formation.py` composes `terrain_kind` + `trail`.

**Member** (`manager._formation_trail_tile`): moving mode only (`leader_mode != turret`), leader on the same map. `MemberFormation` records the leader tile each tick and reads the area (re-read every 2 leader tiles, hysteresis). While the leader walks (not stopped, not farming) and the area is NARROW and the member has a roster seat, the FOLLOW goal is the trail tile `spacing 2 × (seat+1)` behind the leader (sticky, `stand_reason=follow_trail`) instead of the formation slot. OPEN / no seat / no reading → existing travel slot. Not touched: turret seat, settle stand (leader stopped), combat, loot, join_map. Status: `runtime.formation`.

**Leader** (`bot_controller._leader_line_hold` → `set_party_hold`): party on + role leader + `party_leader_mode == moving` + start rally not waiting. `LeaderLineWatch` records the leader's `world_origin`; followers come from party memory (`world.last_party`, non-leader rows; other map = behind; no tile = ignored). Lag = max(Chebyshev, steps behind on the leader trail). When half or more known members lag more than `party_lag_tiles` (default 30, 5–100) the leader holds via the existing `party.hold_ground` (counterattack in reach, else IDLE) for at most 8 s, then walks on for 6 s before it may wait again. Any terrain. Shared path: `set_party_hold` (same flag as the start rally; rally takes priority).

**Setting** — `party_lag_tiles` (profile, task_runtime, schedule, settings bag `party.lag_tiles`), Party tab leader card spin box "뒤처짐 대기 (타일)" (enabled in Moving), i18n EN/KO/ZH. Monitor: leader MODE badge `MOVING ⏸` + "Line wait" metric.

Side effects: a member that disconnects from party memory is ignored; a member on another map (e.g. shopping) counts as behind and causes 8 s waits every 14 s until it returns. While waiting the leader does not search for new mobs.

Result: implemented. Tests: `test_party_formation` (majority rule, corner lag by trail steps, other map, setting, timeout/cooldown, party rows, member trail in manager); party suites 207 passing (2 skipped).

## 2026-10-21 — turret: leader anchor, member CLOSE_IN out of yard, radial seats; member loot/assist import fix

Consent: user ("터렛에서 대상이 야드 밖이면 HOLD → CLOSE_IN and return naturally", "터렛모드에서 리더가 중심이 돼서 사냥을 조직한다. 선택된 사냥지점을 떠나지 않고 거의 그 자리에서 사냥한다. 1-2 타일의 움직임은 감수한다", "tactics", "구현할것은 구현하고 수정할것은 수정하라").

**Leader turret** (new `app._04_decision.behaviors.party_turret`). Session arms it each tick via `set_party_turret` only when party on + role leader + `party_leader_mode == turret` + start rally not waiting. Anchor = first tile inside the active farm (or first hunt tile when no farm rect), stored per live mapId; dropped if >40 tiles away.
- `party.turret_leash` (island + dungeon columns, right before `farm.engage`): monsters farther than leash 2 (+ reach for ranged) from the anchor and items farther than 2 are written to scratch; `excluded_target_ids` now unions them (empty unless turret is armed). Sticky target / item outside the zone is released. Leader >3 tiles from the anchor walks back unless its current target is within reach.
- `party.turret_idle` (right after `farm.engage`): nothing to do → walk back (>1 tile) or IDLE on the anchor; `farm.enter` / `farm.search` / `dungeon.patrol` do not run.
- Shared function touched: `excluded_target_ids` (one extra set, empty for solo / moving). Not touched: `farm_loot_or_combat`, survival, retreat, shop, world nav (all run before the turret steps).

**Member turret** (`decide_policy`, `manager`): target outside the yard → CLOSE_IN (unclamped) instead of HOLD. Yard rejoin is skipped while a fight is in progress (`assist_sticky` = same target as last tick, or target inside the yard); after it ends the member walks back. A member already outside the yard ignores a new outside-yard target and rejoins first.

**Tactics** — `tactics.radial` wired: new `turret_seat.py`. Policy carries roster order → `seat_index_for_name` → `PartyMemberConfig.seat_index`. In turret, a member with no target walks to its ring seat (`fan_slots` full ring, radius ≤2 inside the yard, `resolve_slot` for blocked / no-sight tiles) — reason `turret_seat`; the seat also replaces the random settle stand as the FOLLOW goal. Moving mode unchanged. Other tactics (trail, stagger, teleport_sync, focus_fire) still library-only.

**Bug fix** — `_06_party/loot.py` and `assist.py` imported the removed `GIVE_UP_COOLDOWN_TICKS` and called `excluded_target_ids(bb, ticks)`. The ImportError was swallowed: member primary hold-loot (`try_party_hold_loot`) never ran and assist / solo-farm skip sets were always empty. Now `excluded_target_ids(bb)`.

Side effects: leader in turret ignores far ranged attackers it cannot reach from the zone (members still fight them inside their leash); a farm with no mobs near the anchor means the leader waits instead of searching. Monitor: leader MODE badge `TURRET ⚓` + "Turret anchor" metric.

Result: implemented. Tests: new `test_party_turret` (anchor, zone exclusions, leash, idle, per-map anchor, assist skip regression) + policy/seat tests; party suites 194 passing (2 skipped without LC.exe). Full discover: 15 pre-existing errors unrelated (missing `game_geom`/`gameflow`/`pipeline` modules, stale `GIVE_UP_COOLDOWN_TICKS` / `on_dungeon_return_town` imports in tests, account store env).

## 2026-10-21 — member party: require leader socket at Start, watch + reconnect during party

Consent: user (wait 60s at Start; while disconnected keep farming on the last policy; implement).

Intent: a member with party enabled must not run without the leader's socket. During the party a drop must reconnect.

Start (`BotController._worker` → `_start_party_client`): member + party on → start client, `PartyComms.wait_member_connected(MEMBER_CONNECT_WAIT_S=60, stopped=stop_event)`. No client (empty Leader IP) or timeout → log + party event, `stop(reason="party_ws_unreachable")`, bot loop never runs (no login / movement). Leader and solo bots unaffected. User Stop during the wait aborts it.

During party (`_member_party_tick`, read phase): `PartyComms.watch_member` logs drop #n / reconnected after Ns, and restarts the client IO thread if it died (throttled 5s). `PartyClient` already retries every 2s. Behaviour while down is unchanged: follow/fight via in-game memory + last policy overlay.

Monitor: socket snapshot adds `drops` / `restarts` / `down_s` and state `reconnecting`; dashboard WS badge shows `RECONNECTING #n`.

Side effects: member started before the leader now stops after 60s; wrong Leader IP stops the member instead of farming alone. Watch only runs inside the in-game loop (during login the client still auto-retries).

Result: implemented. Tests: `test_party_member_link` (new) + party suites, 140 run, all passing (2 skipped without LC.exe). Fixed `test_party_invite_setup` fixture missing `_party_comms` (broken by the earlier policy-before-invite change). Live check against a local `PartyServerWatchdog`: gate False with no server, True once up; stop server → drop #1 → reconnected ~1s after restart.

## 2026-10-21 — split farming method: leader turret / moving, member party / solo

Consent: user ("team leader option: turret and moving (이동). Member side: party and solo. Fix related codes").

Intent: the leader picks `leader_mode` (`turret` default, `moving`) and sends it in `party_policy`. Each member picks its own `farm_mode` (`party` default, `solo`), which the leader no longer overrides. `PartyMemberConfig.turret_farm` now reads `leader_mode == "turret"`, so the yard rules apply to both party and solo members while the leader is in turret mode (before: solo skipped the yard). In moving mode there is no yard: party = assist + close-in, solo = own target, as before.

Shared: `decide_policy` combat branch merged (yard rejoin → assist / close-in / hold-out-of-yard). Reasons kept: `assist`, `close_in`, `solo_farm`, `solo_close_in`, with a `turret_` prefix in turret mode. Profile: `party_farm_mode` (party|solo, default party; old `turret` → party), new `party_leader_mode` (turret|moving). Party tab: leader card = Turret / Moving combo; member panel = Party / Solo combo. Dashboard: MODE + FARM badges.

Not changed: the leader's own hunt routine is the same in turret and moving (it only steers members). A leader "hold the spot" behaviour for turret would need a separate change.

Result: implemented. Party policy / member / monitor tests: 84 run, all passing (2 skipped without LC.exe).

## 2026-10-21 — follow / stop / assist are member settings

Consent: user ("따라가기 / 정지 / 어시스트 — these for member bot").

Intent: movement distances are tuned per member bot (class range differs), so the leader no longer sends them. `policy_message` drops `follow_tiles` / `stop_tiles` / `approach_tiles` / `assist_leash_tiles`. `merge_leader_policy` always keeps the member's own values, even if an older leader still sends them. The Party tab moves the three spin boxes from the leader card to the member panel.

Leader policy now carries farm method, loot mode / priority, roster seats + loot, and party size (yard).

Result: implemented. `test_party_farm_policy.py` has 10 tests, all passing.

## 2026-10-21 — party policy sent before invite; member overlay is temporary

Consent: user ("send the profile settings to each member before the party invite… temporarily merge… solo must use origin profile… implement this cleanly").

Intent: the leader pushes `party_policy` before the first `/파티`, waiting up to 20 s (`POLICY_BEFORE_INVITE_WAIT_S`) for roster members to connect over WebSocket and re-sending to each newcomer. The periodic 5 s resend still covers late members. On the member, the policy is an in-memory overlay: `PartyMemberManager.base_config` keeps the member's own knobs, `apply_leader_policy` merges on top, `clear_leader_policy` restores them. Leader identity and member-only knobs (potion ratio, defend) survive. The overlay is re-applied when the policy or the member's own name changes.

Shared: `_run_leader_party_setup` (new pre-invite step), `_send_party_policy_before_invite`, `_apply_member_party_policy`, `PartyMemberConfig.with_knobs_from`. The profile is never written, so a solo run (party off, no `party_brain`) always uses the member's original profile.

Side effects to watch: leader invites can start up to 20 s later when members are not connected.

Result: implemented. `test_party_farm_policy.py` has 10 tests, all passing. Not yet run in game.

## 2026-10-21 — turret farm default + leader party_policy

Consent: user ("implement… base farming mode… main setting… team leader… roster roles… looting solo/responsible… farming method global").

Intent: member base farm is turret (yard assist around the leader). Leader owns global farm method, loot mode, follow knobs, and roster seats (mage default; shopkeeper optional). Leader broadcasts `party_policy`; members `merge_leader_policy` (per-name seat + loot).

Shared: `farm_yard.py`, `PartyMemberConfig.merge_leader_policy`, `policy` turret branch, `party_orders.policy_message` / `MemberOrders.policy`, `PartyComms.publish_policy`, `BotController` publish/apply. UI Party tab: farm/loot on leader; roster Role+Loot; member WS-only. Profile/task_runtime default `party_farm_mode=turret`.

Affects: party member decide (turret yard), leader ticks (policy publish). Solo hunt / HP / login unchanged.

Result: implemented. `Others/tests/test_party_farm_policy.py` added.

## 2026-10-20 — party `comms/` facade (wire unchanged)

Intent: all party WebSocket I/O goes through `app._06_party.comms` so session and behaviour modules do not import `websocket.party_orders` / leader ticks directly.
Shared: new `comms/` (`PartyComms`, `orders`, `link`, `publish`, `ingest`, `status`). `leader_rally` / `manager` import `comms.orders`. `BotController` socket lifecycle and leader/member ticks use `PartyComms`. JSON envelope and body `type`s unchanged. Invite chat still `_05_action.chat` (not socket).
Affects: party session glue only. Combat, HP, login, solo decide columns unchanged.
Consent: user ("go on" after README modularization plan).
Result: implemented. README §4 updated. Party unit tests to verify.

## 2026-10-20 — invite retry: 30 s × up to 3 after each failed `/파티`

Intent: when an invite line fails, wait 30 s and try again, up to 3 retries (`INVITE_RETRIES` / `INVITE_RETRY_S`), then move to the next roster name.
Shared: `configure_party_from_roster` only. Leave still has no retry (failed leave stops invites).
Consent: user ("실패하면 30초 간격으로 최대 3번까지 다시 시도").
Result: implemented. Invite unit tests cover all-fail retries and success on the 3rd try.

## 2026-10-20 — invite all names; rally wait 15 min; elf hold = solo click range

Intent: three corrections to the party leader start path.
1. Invite: a failed `/파티` line no longer stops the rest — every roster name is attempted; only a failed `파티탈퇴` still stops (cannot invite as non-leader).
2. Rally wait: if not everyone has arrived after 15 minutes, the leader skips the rally and continues to the hunt (`LeaderStartRally.WAIT_TIMEOUT_S`).
3. Hold-ground elf reach: use solo `ATTACK_CLICK_TILES` (default 8) instead of a hardcoded 6.
Shared: `configure_party_from_roster`, `LeaderStartRally.update` / `_enter_waiting`, `hold_ground_reach`. Combat/HP/login paths otherwise unchanged.
Consent: user ("i have to send all", "time out is 15 mins", elf = solo range).
Result: implemented. Invite / rally / hold-ground unit tests updated.

## 2026-10-20 — party rally wait: hold ground and hit back only at attackers

Intent: while the leader waits for the roster (start rally, both the no-travel wait and the wait on the teleport landing), potions keep working and the leader fights only monsters attacking it, from its current tile. No chase, no loot, no wall detour or unstick, no new non-attacker targets.
New step `party.hold_ground` (`app._04_decision.behaviors.hold_ground`), placed right after `survival.return_vitals` in the WORLD_NAV, FARMING_ISLAND, FARMING_DUNGEON and TRAVELING columns. It is a no-op unless blackboard scratch `party_hold_ground` is set. When set: ATTACK the nearest monster from `nearest_attacks_me_force` if it is within reach (melee 1 tile, elf 6, mage in spell mode `MAGE_SPELL_RANGE`) and `can_engage_target` holds; otherwise drop the target and emit IDLE "party rally wait members". Steps after it (shop trip, return-on-idle, routine duration, nav, spells, farm, world-nav drive) do not run during the wait.
Shared: reuses `nearest_attacks_me_force`, `can_engage_target`, `begin_engage`, `note_attack_attempt`, `clear_loot_hop` read-only/as-is; `continue_or_start_combat`, `farm_loot_or_combat`, `try_combat_wall_detour`, `try_combat_blocked_unstick`, HP functions are not changed. `bot_controller` sets the flag every tick from `LeaderStartRally.waiting` (leader only) and freezes the routine/farm clocks during the wait; the old gate that skipped decide during the no-travel wait is removed, so decide (and survival) now runs then. `LeaderStartRally.waiting_before_route` removed.
Affects: party leader during the start rally only. Solo and members: the flag is never set, so the new step does nothing.
Side effects to watch: an attacker beyond reach (ranged monster for a melee leader) is not fought and keeps hitting; survival (potion, emergency teleport, return on vitals) still wins and can move the leader off the rally tile. Elf reach follows solo `ATTACK_CLICK_TILES`. Survival handoffs to RETREATING/SHOPPING leave the hold columns (those columns have no hold step).
Consent: user (fight = new guard "팀장을 공격하는 몬스터만 제자리에서 반격, 추격·루팅 없음"; start wait = same as landing wait).
Result: implemented. `Others/tests/test_party_hold_ground.py` and `test_party_rally.py` pass. Not run in game.

## 2026-10-20 — party start rally on the last teleport landing (replaces the town rally and NPC-click wait)

Intent: on the first hunt trip after party start, the leader gathers the roster where the route needs it.
- No teleport on the way (already on the hunt map / in the target dungeon, or a walk-only world-nav plan): send the leader's tile (`rally` stage `start`) and wait there.
- Teleport on the way (NPC teleporter or talking scroll): when the plan exists, send the planned landing of the last teleport (stage `planned`), travel without waiting at the NPC, then send the real landing tile (stage `landed`) and wait before the next step.
Waits for every roster member, or 15 minutes (see later entry). Later trips (recovery return, schedule change) do not rally.
Shared: `websocket.party_orders` — one `rally` message with `stage`; `hunt_move`, `town_rally`, `npc_click_allowed`, `note_hunt_plan` removed. New `app._06_party.leader_rally.LeaderStartRally`. `WorldNavHooks.allow_npc_teleport` replaced by `hold_at_step(step_i, pose)`, checked in the `ready` phase before each step (solo: unset, no effect). Member reports tag `order` as `rally:<stage>`.
Affects: party leader first hunt trip, party member gather. Solo world nav, combat, HP, retreat, loot, and login are unchanged.
While holding inside world nav the WORLD_NAV survival steps (HP, emergency) still run; combat does not (world-nav combat runs only in the walk phase). The no-travel start wait skips decide, as the town rally did. In-place fighting during the wait: see the hold-ground entry above.
Consent: user (logic confirmed: planned+actual landing, NPC and scroll count as teleport, NPC-click wait removed, fight in place while waiting, first trip only; "진행").
Result: implemented. `Others/tests/test_party_rally.py` passes. Not run in game.

## 2026-10-20 — party start town rally on the leader's tile (superseded the same day)

Intent: at party start, before leaving for the hunt, the leader sends `town_rally` (`map_id`, `x`, `y` = its own tile) and stands until every roster member is within 7 tiles. Then the normal solo routine (hunt travel, NPC rally) starts. The hunt NPC rally keeps waiting for everyone, as before.
Shared: `websocket.party_orders` — `HuntRally` became `Rally` (`town_rally` and `hunt_rally` instances), new `note_positions` / `missing`; `MemberOrders.hunt` became `gather` and accepts both orders. Member reports carry `order`, so an `arrived` for one gather does not count for another. Member `_maybe_hunt_gather` walks to either point (`party_town_rally` / `party_hunt_rally` reasons). Leader report drain moved to `_drain_party_reports` (both rallies). Leader loop gate after the invite setup skips decide while waiting.
Arrival counts from a member report or from the in-game party list position (town rally only).
Affects: party leader start, party member gather. Solo, combat, HP, retreat, loot, and login are unchanged.
Side effects to watch: no timeout (user chose to wait for everyone), so a roster member who never logs in keeps the leader standing; the leader does not decide (and so does not fight) while waiting at start. An exception in the rally skips it and leaves for the hunt.
Consent: user (town rally at party start, on the leader's tile, wait for all; "이 범위로 진행").
Result: implemented. `Others/tests/test_party_rally.py` passes. Not run in game.

## 2026-10-20 — leader party invite types through the enter_chat module

Intent: the leader's Start invite (`/파티 <name>`, `파티탈퇴` to leave) typed nothing or broke Hangul through the old `InputRouter` paste path. The tested `enter_chat` DLL now types each line: Hangul as 2-beolsik jamo keys through Interception and the Korean IME, other characters as `WM_CHAR`, Enter to open and send. No clipboard, no SendInput.
Layout: native source + `bin/enter_chat.dll` in `Engine/analysis/enter_chat/`; Python output module `app._05_action.chat` (`native` binding, `handoff`, `sender.GameChat`); party lines in `app._06_party.chat_commands`; `app._06_party.setup` holds only the leave/invite flow and takes `send_line(line) -> bool`.
Shared: `mouse.release_capture` / `prepare_capture` run around each typed line, because the DLL opens its own Interception context. Only `_run_leader_party_setup` sends chat; move, combat, HP, retreat, loot, login, and member logic are unchanged.
Behaviour change: the first undelivered line (no LC window, focus, IME, elevation) is logged with the DLL status and stops the remaining invites. `send_game_chat` is removed.
Side effects to watch: the bot holds no mouse/keyboard for about 1–2 s per line at leader Start; LC is brought to the foreground and the input language is switched to Korean for the line, then restored.
Consent: user ("migrate this into this project as a new module for chatting, and use this in party logic to invite the members").
Result: implemented. `Others/tests/test_game_chat.py` and `test_party_invite_setup.py` pass, including a real-DLL dry run (`/파티 번개공격` = 8 chars, 17 keys). Not run in game yet.

## 2026-10-20 — standalone party tactics package (not wired)

Intent: add formation, movement, and focus-fire logic as independent modules under `Engine/app/_06_party/tactics/`: open-field vs narrow-dungeon classification, open-field fan slots with sight-line slot repair and pace, dungeon single-file trail with corner/lag hold for the leader, leader-jump regroup with staggered delays, focus-fire allocation with overkill prevention, and per-member volley delays. A random teleport scroll lands on a random tile, so regroup defaults to `rejoin`; repeated random teleport is opt-in for small maps.
Shared: none. Nothing imports `tactics`; follow, assist, loot, HP, retreat, login, and decide are unchanged.
Affects: nothing at runtime until wired.
Consent: user ("impl" these logics as independent modules).
Result: implemented. `Others/tests/test_party_tactics.py`, 37 tests pass. Not run in game.

## 2026-10-19 — dedicated party session log

Intent: open `Engine/logs/party-YYYYMMDD-HHMMSS.log` when party is enabled, separate from `bot-*.log`. Channels: setup (invite), session (wait/farm), member (kind changes), join (cross-map), socket (WS + local chat).
Shared: logging only. Follow, assist, HP, login, and decide paths unchanged. Member kind lines log at INFO only when kind/reason changes.
Affects: diagnosis files for party Start.
Consent: user ("go" after confirming party log system was missing).
Result: implemented. Unit tests in `Others/tests/test_party_log.py`. First live Start created no `party-*.log` because open ran before `install_profile_runtime` (party_enabled still False). Open moved to after profile apply + leader setup/socket entry.

## 2026-10-19 — party log open after profile apply

Intent: party log file was missing while Party invite still ran.
Shared: `_ensure_party_log` only. Decide/move/combat unchanged.
Affects: when `party-*.log` is created.
Consent: user (cannot see party log while doing party).
Result: implemented.

## 2026-10-19 — same-map world nav walks instead of a talking scroll

Intent: on Talking Island the character was already on map 0, and world nav still opened a talking scroll toward the pet manager. The list never opened (`opened=False`), then every tick idled on `world nav scroll land` and never walked or hunted.
Shared: `WorldNavPlanner.plan` `allow_scroll`. Cross-map scrolls, NPC teleporters, combat, and HP are unchanged.
Affects: a goal on the map the character is already on (farm routine, same-map shop). That trip walks. A goal on another map still uses the talking scroll.
Consent: user (check the log and fix; the bot is in the world and never decides).
Result: implemented. Replay of map0 (32323,32965) → (32384,33068) is one walk of 103 tiles. Not run in game.

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

## 2026-10-19 — party wait logs until farm start

Intent: keep the party websocket monitor log (do not clear it on connect). Until follow/farm actually starts, write a wait line every 2.5s: in_party, party-memory leader, xy, map, seen name, dist, kind, reason, socket state. Leader Start also logs the roster and that `/초대` is in-game chat after the world is ready, not the WS local test. Member Start says follow uses party_listen, not the socket.
Shared: none. Follow, invite commands, and combat are unchanged.
Affects: party leader and member session logs until the first farm/follow action.
Consent: user (member never found the leader; invites not seen; leave the log until farm start).
Result: implemented. Not run in game.

## 2026-10-19 — leader roster invite at bot start

Intent: when the leader bot starts, open the party socket first, then type the in-game party commands for the roster table. Leave with `파티탈퇴` if this character is already in a party and is not the in-game leader. Invite each table name with `/초대 <name>` + Enter. Names already in the party, and this character, are skipped. Empty table does nothing.
Shared: none. Solo farm, member follow, `begin_retreat`, and HP lines are unchanged. Chat uses the existing Interception paste path (`InputRouter`).
Affects: party leader only, once per Start, after live origin/mapId and before the first farm decide.
Consent: user (socket first, then invites from the party table).
Result: implemented. Not run in game.

## 2026-10-19 — party loot priority (loot first / follow first)

Intent: a party-farm member can choose loot first or follow first on the party tab. Loot first: when assist, close-in, defend, join-map, wait, and stop are not needed (policy is HOLD or FOLLOW), the member walks to party drops and picks them up within the follow distance, then follows. Party adena and items are treated as its own (no ownership gate), but only the closest eligible member takes each pile. Eligible = party list members except the leader and the wizard; the local wizard never takes them. Ties go to the lower name so every client picks the same looter. Follow first keeps the earlier loot timing and the Random / Role rules.
Shared: `try_party_hold_loot`, `find_party_pickup_range_loot`, `arm_party_loot_side` gained an optional item filter (default unchanged). Side F4 on loot first still only while the leader is not fighting. Solo farm, `begin_retreat`, and the retreat HP line are unchanged.
Affects: party-farm member loot vs follow order when `party.loot_priority` = `loot`. Default `follow` = unchanged behavior.
Caveat: the wizard class id from the party list is assumed to be 3 (Lineage order). Not confirmed against live memory.
Consent: user (closest member except leader and mage loots; UI loot/follow priority; implement).
Result: implemented. Not run in game.

## 2026-10-19 — party member uses the solo retreat line at the HP gate

Intent: when a party member's HP is at or under the solo retreat threshold, call that same survival line so an elf goes to the mother tree and any other class takes the talking-scroll landing (teleport only if the scroll cannot). Follow, hunt-NPC walk, and buffs wait until that trip ends. After HP recovers, the solo hunt-map world nav is not run; the member follows the leader again.
Shared: called, not edited — `apply_hp_actions`, `tick_retreating`, `tick_shopping`, `begin_retreat`.
Affects: party member only, and only at the retreat HP gate or while that retreat or its pre-retreat sell is in progress.
Consent: user (in that situation, call that line and escape).
Result: implemented. Not run in game.

## 2026-10-19 — party hunt NPC and mother-tree orders

Intent: the moment the leader's route picks an NPC teleporter, tell members (`type` `hunt_move`, `from` `leader`, the NPC map and xy). The leader stands on that NPC until those members report they are there, then the existing teleporter click runs. A mother-tree recovery decision sends `type` `recovery` immediately. Members do not act on `recovery`. Members who receive `hunt_move` walk to that NPC, then send buffs and the item list (`type` `report`).
Shared: `WorldNavSession.begin` calls an optional plan hook; `_start_npc_teleporter` waits only when that hook is installed (leader process). Solo leaves the hooks empty, so the click is unchanged. `begin_retreat` is not edited.
Affects: party leader world-nav NPC click, party member follow while a hunt order is active, party socket payloads.
Consent: user (send the NPC and mother-tree decision at once; members gather, report, then the group goes on; leave mother-tree behavior for later).
Result: implemented. Not run in game.

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

## 2026-10-21 — schedule Start keeps the schedule character and routine

Consent: user asked to fix it on `impl/party-leader-logic` without touching single-bot logic and keeping party logic as is.

Intent: on Start, `_overlay_party_from_editor` re-applied the Party tab through a bare `ScheduleTask`. Its default `character="mage"` and empty routine overwrote the schedule just applied by `apply_task`. The schedule (elf, area_6 60 min) then ran as mage with `routine (0 entries)`, and the trial file was saved that way.

Change: only `UI/ui_qt/shell/schedule_shell.py` `_overlay_party_from_editor`. It applies the Party tab to a copy of the profile and copies back `party_*` fields only. `apply_runtime_settings` and the `ScheduleTask` defaults are unchanged.

Affected modes: main-window Start and scheduled login Start. Single-bot decision, movement, combat and HP code are unchanged. Party values are the same as before, checked for party off, leader on and member on.

Live result: pending. The next Start log should read `character=elf` and the routine should have 1 entry.

## 2026-10-21 — party wait log only when party is on

Consent: user asked to stop the `Party wait` log while party is off.

Change: `_log_party_until_farm` in `Engine/session/bot_controller.py` returns early when `profile.party_enabled` is false. The function is log only. Decisions, movement and the party socket are unchanged. With party on, the log is the same as before.

## 2026-10-22 — party invite accept from the in-game popup

Consent: user asked to read the invite dialog like `uidialogmon_930.c`, press Y when the text is a party invite, send an ack to the leader over the socket, drop the leader's invite notice and the member's 30 s wait, use the dist registry keys, and hold the IME in English for Y. User accepted that both PCs must run the same version (socket format changes).

Intent: the member accepts on what it sees on screen, not on a socket notice, and the leader counts the member joined once Y closed the popup.

Change:
- `uidialog_listen.c` (DLL rebuilt) lists open Yes/No confirms (`HudChatLayoutPCImpl` chat confirm panel + popup classes) under `confirm` with the text; registry keys `CHATCONFIRM_*` / `UICONFIRM_CLASSES` / `POPUP_VIS_OFF` copied from the dist registry. Popups are not added as `UIDLG_WIN_*`, so the Esc window gate does not close them.
- Member: `_06_party/invite_popup.py` matches the Korean invite text (파티 + 초대합니다 + 승낙; any 거래 text is never an invite) and the inviter name. `accept.InviteAccepter` rewritten: Y at once, again after 2 s if the popup is still open (max 3), accepted = popup closed after Y, then `invite_accept` to the leader (3 sends, one `accept_id`). A popup from someone other than the policy `leader_name` is left alone. Phase `left` once party memory showed the join and lost it for 10 s.
- Y: `GameChat.press_key(english=True)` clears 한글 mode on the game's default IME window (`WM_IME_CONTROL`) for the key and restores it after.
- Socket: `party_invite` / `publish_invite` / `take_invite` removed; new `invite_accept` frame (member → leader); policy carries `leader_name`.
- Leader: no notice and no `InviteGate`. `InviteHold` holds a new `/초대` while the member reports the popup open (max 30 s). Joined = leader party memory, or `sync.reported_joined` (member accepted the popup, or its own party memory). The 20 s `/초대` retry and the start wait are unchanged.

Affected modes: party member invite accept, leader invite/joined bookkeeping and the party monitor. Single-bot logic and the rally, follow, combat and HP code are unchanged.

Side effects to watch: a popup closed by its own timeout right after Y counts as accepted; a member restarted after an accept is not joined until it accepts or its memory shows the party. When the leader name cannot be read at setup, the member accepts any invite popup.

Live result: popup reading verified on a trade popup (ask 252). Invite accept and IME switch pending a live run on both PCs.

## 2026-11-12 — party dungeon plan drives patrol and point stages

Intent: A party dungeon row with `dungeon_plan` hunts that list in saved order. Each patrol uses its own waypoints and `duration_s`. Each point uses the existing stationary walk and starts `stay_s` on arrival. The row's `duration_minutes` still ends the visit. A row without `dungeon_plan` keeps the old mark walk.
Shared: `PartyLeaderSchedule` plan cursor, `PartyLeaderManager._drive_dungeon_plan`, and the dungeon patrol arrival hook. Solo `patrol.yaml`, `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader while the current row has a dungeon plan. Field hunts, legacy patrol-only rows, solo dungeon patrol, and party members are unchanged.
Consent: user (implement the dungeon_plan runtime, keep legacy rows, do not rewrite solo patrol).
Result: `Engine/app/_06_party/tests/test_leader_dungeon_plan.py`. Not run in game.

## 2026-11-12 — a dungeon plan is not blocked by the retreat return walk

Intent: After a retreat, the existing world-nav return was resumed before the dungeon plan tick, so that walk could keep the legacy mark and skip the active patrol or point. A plan row now still runs its stage tick, and a return walk that is not the current point's own walk is dropped.
Shared: `PartyLeaderManager.prepare` and `_drop_plan_conflicting_walk`. Legacy rows still leave an active party walk alone. `try_unstick_escape`, `begin_retreat`, `apply_hp_actions`, and login clicks are unchanged.
Affects: the party leader only while the current row has a dungeon plan.
Consent: user (audit the plan runtime and fix confirmed defects in that scope).
Result: `Engine/app/_06_party/tests/test_leader_dungeon_plan.py`. Not run in game.

## 2026-11-12 — dungeon plan return request and map grid

Intent: `finish_retreat` only sets `need_world_nav`. The next world-nav tick armed that return before the plan hop. A plan that is on its own map now clears that request. On another map, or when the entry names another pack or game map id, the saved tile is not published as a hop.
Shared: `PartyLeaderManager._drop_plan_conflicting_walk` and `_plan_map_identity_ok`. Retreat policy, `begin_retreat`, and solo patrol are unchanged.
Affects: the party leader only while the current row has a dungeon plan.
Consent: user (final review of the plan runtime; fix confirmed defects in that scope).
Result: `Engine/app/_06_party/tests/test_leader_dungeon_plan.py`. Not run in game.