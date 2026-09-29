inventories/ — bot bag reader + patch rediscovery

Bot (no C rebuild if only TXT/JSON change):
  inventory_listen.dll   loaded by Manmabot
  inventory_offsets.txt  structure + MSG_* (this file wins)
  offsets.json           must exist; ItemEntity* keys are fallback only

After a server patch (LC.exe running, driver started):
  build_invsync.bat
  invsync.exe            writes inventory_offsets.txt in this folder
  If MGR moved, copy it into ../char_offsets.txt,
  ../entities/entity_offsets.txt, ../Hotbar/skill_offsets.txt
  restart Manmabot

Do not use inventory.exe JSON in the bot (id schema is different).
JSON id from inventory_listen is ITEM_CFG (+0x30).
See ../README.txt for character / entity / hotbar files.
