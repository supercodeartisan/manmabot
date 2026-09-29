live_tracking — patch rediscovery only (not used by the bot)

The bot reads entities via analysis/entities/print_state.dll.
iscr + 2-speed polling already live there. Do not run this tool
alongside Manmabot (signeddrv is one instance).

After an LC.exe patch (game running, driver started):
  build_entlocate.bat
  entlocate.exe --write
    → updates ../entities/entity_offsets.txt
      (MGR, ACTOR_VFT, VFT_PRES_B, DEATH_VFT, DEADBODY_VFT, ACT_VFT)
  restart Manmabot

Without --write it only prints the found RVAs.
