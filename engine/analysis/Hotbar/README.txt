Hotbar — LC.exe 24-slot memory reader (T4)

Bot (no C rebuild if only TXT changes):
  hotbar_listen.dll      loaded by Manmabot
  skill_offsets.txt      HSD / map / slot fields (this file wins)
  ../inventories/inventory_offsets.txt
                         MSG_* names + ITEM_* join for counts

After a server patch (LC.exe running, driver started):
  1) build_skilllocate.bat && skilllocate.exe
     → writes skill_offsets.txt (MGR, HSD_VFT/IDX/ADJ)
     HSD_IDX is decimal. All other keys are hex (0x optional).
  2) ..\inventories\invsync.exe
     → name table / inventory join (if item names or counts break)
  3) If MGR moved, also copy it into char_offsets.txt,
     entities/entity_offsets.txt, inventories/inventory_offsets.txt
  4) restart Manmabot

Slot map (memory slot 0–23):
  0–7   = F1, F5–F12     (user 1–8)
  8–15  = F2, F5–F12     (user 9–16)
  16–23 = F3, F5–F12     (user 17–24)

JSON name:
  SPELL  name="힐"  label="힐(4/0)"   — (N/M) is level/cost, not cooldown
  ITEM   name from nametable, count from inventory uid
  STALE  leftover name, no count
  EMPTY  empty slot

Do not use skill.exe JSON in the bot (old schema).
Roles stay in manmabot_v1/data/hotbar_role_map.csv.
