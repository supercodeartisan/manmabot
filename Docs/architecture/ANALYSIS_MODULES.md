# Analysis modules

Live memory reads go through the memory-team tree in `Engine/analysis`. Decision, retreat, login, and click code were not edited. They still read `PerceptionBuffer` and `GameState` the same way. This note is the current path. `MEMORY_READ_CANON.md` describes the older listener DLLs and offset files under `Engine/analysis/old`.

## Where the tick reads

`PerceptionSensors.capture_tick` in `Engine/app/_01_perception/sensors.py` still fills one buffer per tick:

1. Player (`RealtimeMonitorReader`)
2. Entities (`PrintStateReader`)
3. Attackers (`AttacksMeReader`) and contested mobs (`ContestedMobsReader`)
4. Bag on every tick. Hotbar when asked, or about once a second.
5. Buffs and UI windows every tick.
6. Party only when `capture_tick(party=True)`.

`Engine/app/_03_world/merge/apply_perception.py` copies that buffer into `GameState`. That merge was not changed.

Each reader is a thin class on `ModuleReader` (`lc_session.py`). It loads `Engine/analysis/dll/<name>.dll`, keeps the latest text sample, and `lc_view.py` turns the text into the old snapshot shape.

| Reader | DLL | Sample interval | Dict the rest of the bot uses |
|---|---|---|---|
| `realtime_monitor_reader.py` | `charread.dll`, and `map.dll` for map id | 100 ms, map 200 ms | `player`: `hp`, `maxHp`, `mp`, `maxMp`, `level`, `expPct`, `pos`, `x`, `y`, `mapId`, `mapIdOk`, `zone` |
| `print_state_reader.py` | `enttrack.dll` | 100 ms, sweep 400 ms | `print_state`: `entities`, `client_w`, `client_h`, `player` |
| `attacks_me_reader.py` | same `enttrack` sample | same | `attacks_me` / `strikes`: Monster or SummonedMonster whose `tgt` is MyPlayer |
| `contested_mobs_reader.py` | same `enttrack` sample | same | `contested`: monster claimed by another player, or by a summon that is not mine |
| `inventory_listen_reader.py` | `inventory.dll` | 500 ms | `items`: `id`, `count`, `kind`, `name` |
| `hotbar_listen_reader.py` | `hotbar.dll` | 400 ms | `slots` |
| `shop_listen_reader.py` | `shop.dll` | 400 ms | `buy`, `sell` |
| `buff_listen_reader.py` | `buff.dll` | 300 ms | `buffs`: `name`, `remain` |
| `uidialog_listen_reader.py` | `uidialogmon.dll` | 200 ms | `windows`, `open` |
| `party_listen_reader.py` | `party.dll` | 300 ms | `leader`, `members`, `in_party`, `subs_ok` |

`body_pose.py` is outside the tick buffer. Travel, unstick, search hops, and loot hops still call `body_is_moving()`. That function still returns `True`, `False`, or `None`. The live ids come from `bodyact.dll` (50 ms) through `read_action()`. The stand/walk/attack numbers it compares against are loaded at import from `registry/LC930_REGISTRY.txt` (`VFT_BREATHACT`, `VFT_MOVINGACT`, `VFT_MOVINGBACK`). `read_vitals()` and `read_progress()` use the `charread` sample. Decision code does not call those two; HP actions use the player block on the tick buffer.

A missing module sample stays “unread.” Map id is unread when `mapIdOk` is 0, so map 0 is not treated as Talking Island. The id is MapSubsystem plus registry `MAP_ID_OFF`, read by `map.dll`.

`enttrack` names are renamed in `lc_view.py` so the existing class tables match: `Summon` becomes `SummonedMonster`, `NPC` becomes `InteractiveNPC`. Screen position is `iscr` as `{x, y}`. World cell is `{cx, cy}`.

The bag used to refresh about once a minute. `inventory.dll` now updates about every 500 ms, and the tick takes that latest sample. Potion and arrow counts can change sooner. The rules that spend them are the same.

The first call for a module waits up to 1.5 seconds for a sample. Later ticks use the sample already pushed.

## Analysis tree

| Folder | Role |
|---|---|
| `registry/` | `LC930_REGISTRY.txt`, plus `region_table.tsv`. Addresses live here. |
| `src/` | Module sources the DLLs are built from. |
| `core/` | `lcore.h`, `lcreg.h`, `lcapi_adapter.c`, `signeddrv_client.c`. |
| `data/` | Name tables the modules open. |
| `dll/` | The ten DLLs the bot loads. |
| `old/` | Previous listener DLLs and offset tables. Not loaded. |

`lc_session.py` sets `LCAPI_ROOT` to `Engine/analysis` before a DLL loads. `core/lcreg.h` uses that so `registry/` and `data/` resolve without moving the process working directory. Reads go through `signeddrv` (`WinNotify`).

`registry_apply.py` is not run on startup. `body_pose` only parses the registry file to bind the stand/walk ids.

## Next dist drop

Copy `registry`, `src`, `data`, and `core` from the memory-team dist into `Engine/analysis`. Leave `dll/` and `old/` in place. Do not replace the whole `analysis` directory.

1. If `src` or `core` changed, run `Engine\analysis\build_bot_modules.bat`. A registry-only copy does not need a rebuild. The script uses VS 2022 Build Tools (`vcvars64`) and links `user32.lib` for `enttrack`.
2. Restart the bot. Each module reads `registry/LC930_REGISTRY.txt` when its thread starts.

Built DLLs: `charread`, `map`, `enttrack`, `bodyact`, `inventory`, `hotbar`, `shop`, `buff`, `uidialogmon`, `party`.
