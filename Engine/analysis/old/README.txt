After an LC.exe server patch — edit TXT/JSON only. Do not rebuild C
unless the reader itself changed.

Shared chain (copy the same MGR / holder into every file that lists them):
  MGR          CharacterData / entity / inventory / hotbar manager RVA
  HOLDER_OFF   usually 0xD0
  SUBLIST_BEG / SUBLIST_END

1) Character (HP/MP/stats)
   Edit:  analysis/char_offsets.txt          ← wins
          analysis/offsets.json              ← must exist; PlayerBase HUD fallback
   Tool:  none (paste new MGR / CD_VFT / field offs)
   DLL:   analysis/realtime_monitor.dll

2) Entities (mobs / names / world / iscr)
   Edit:  analysis/entities/entity_offsets.txt          ← wins
          analysis/entities/settings_print_state.json   ← fallback + projection
   Keys:  MGR, ACTOR_VFT, ENT_VFT_SET, VFT_PRES_B,
          OFF_LIVE_U/V, OFF_A_U/V, INTERP_MS, SLOW_MS, PLAYER_*
   Tool:  live_tracking/entlocate.exe --write
          (writes entities/entity_offsets.txt; LC.exe + driver required)
   DLL:   analysis/entities/print_state.dll
   JSON:  entities[] + screen (raw B) + iscr (A→B lerp)

3) Inventory (bag names / counts / shop ids)
   Edit:  analysis/inventories/inventory_offsets.txt    ← wins (incl. MSG_*)
          analysis/inventories/offsets.json             ← must exist
   Tool:  inventories/build_invsync.bat && invsync.exe
          (LC.exe running, signeddrv started)
   DLL:   analysis/inventories/inventory_listen.dll
   Do not feed inventory.exe JSON into the bot (id schema differs).

4) Hotbar (24 slots, F1–F3 × F5–F12)
   Edit:  analysis/Hotbar/skill_offsets.txt             ← wins
          inventories/inventory_offsets.txt             ← item names + counts
   Tool:  Hotbar/build_skilllocate.bat && skilllocate.exe
          then inventories/invsync.exe if names/counts break
   DLL:   analysis/Hotbar/hotbar_listen.dll
   Names: SPELL  "힐(4/0)" → name="힐"  (N/M is level/cost, not cooldown)
          ITEM   nametable + inventory uid count
   Roles: manmabot_v1/data/hotbar_role_map.csv  (kr_name → bot role)

Restart Manmabot after any TXT/JSON change.
C rebuild is only needed if you change a .c file.
