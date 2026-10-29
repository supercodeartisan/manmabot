# Analysis modules

The bot reads Lineage Classic memory through the memory-team tree in `Engine/analysis`. Hunt, retreat, login, and click decisions are unchanged. They still receive the same player, entity, bag, hotbar, buff, UI, shop, and party snapshots.

`MEMORY_READ_CANON.md` describes the older listener DLLs (`realtime_monitor`, `print_state`, `attacks_me`, and the matching offset files). Those binaries now live under `Engine/analysis/old` and are not loaded.

## Layout

`Engine/analysis` keeps four folders from a dist drop, plus the DLLs this repo builds:

| Folder | Role |
|---|---|
| `registry/` | `LC930_REGISTRY.txt`. Single source for addresses. Includes `region_table.tsv`. |
| `src/` | Module sources (`charread`, `enttrack`, `map`, `bodyact`, and the rest). |
| `core/` | Shared reader (`lcore.h`, `lcreg.h`, `lcapi_adapter.c`, `signeddrv_client.c`). |
| `data/` | Name and string tables the modules open. |
| `dll/` | Built module DLLs. The bot loads these. |
| `old/` | Previous listener DLLs and offset tables. Not used at runtime. |

The host sets `LCAPI_ROOT` to `Engine/analysis` before a DLL loads. `lcreg.h` uses that so `registry/` and `data/` resolve without moving the process working directory. Each module still reads memory only through `signeddrv` (`WinNotify`).

## What runs

`Engine/app/_01_perception/lc_session.py` loads `Engine/analysis/dll/<name>.dll` and keeps the latest text sample. `lc_view.py` turns that text into the dicts `PerceptionSensors` already stored. World merge and decision code were not edited for this switch.

| Bot need | Module | Snapshot the bot still uses |
|---|---|---|
| HP, MP, level, exp, position | `charread` | player block (`hp`, `maxHp`, `mp`, `maxMp`, `pos`, `x`, `y`) |
| Map id and region name | `map` | `player.mapId`, `mapIdOk`, `zone` |
| Nearby entities | `enttrack` | `print_state` (`entities`, `client_w`, `client_h`) |
| Who is attacking me | `enttrack` | `attacks_me` rows whose `tgt` is MyPlayer |
| Contested monsters | `enttrack` | `contested` rows claimed by another player or summon |
| Stand / walk | `bodyact` | `body_pose.read_action` vft ids |
| Bag | `inventory` | `items` (`id`, `count`, `kind`, `name`) |
| Hotbar | `hotbar` | `slots` |
| Shop lists | `shop` | `buy` / `sell` |
| Buffs | `buff` | `buffs` (`name`, `remain`) |
| UI windows | `uidialogmon` | `windows` / `open` |
| Party | `party` | `leader`, `members`, `in_party`, `subs_ok` |

Map id comes from the `map` module: MapSubsystem, then the registry `MAP_ID_OFF`. A missing subsystem is `mapIdOk = 0`, so map 0 is not treated as Talking Island.

`enttrack` class names are renamed where the bot's tables differ: `Summon` becomes `SummonedMonster`, `NPC` becomes `InteractiveNPC`. Screen position is `iscr` as `{x, y}`. World cell is `{cx, cy}`.

Stand and walk still compare the registry vfts (`VFT_BREATHACT`, `VFT_MOVINGACT`, `VFT_MOVINGBACK`). `bodyact` supplies the live ids. `read_vitals` and `read_progress` use the `charread` sample.

## Next dist drop

Copy only these four folders from the memory-team dist into `Engine/analysis`, overwriting what is there:

- `registry`
- `src`
- `data`
- `core`

Leave `dll/` and `old/` in place. Do not replace the whole `analysis` directory.

Then:

1. If `src` or `core` changed, run `Engine\analysis\build_bot_modules.bat`. A registry-only copy does not need a rebuild. The script compiles the ten DLLs with VS 2022 Build Tools (`vcvars64`) and links `user32.lib` for `enttrack`.
2. Restart the bot. Each module reads `registry/LC930_REGISTRY.txt` when its thread starts.

Built DLLs: `charread`, `map`, `enttrack`, `bodyact`, `inventory`, `hotbar`, `shop`, `buff`, `uidialogmon`, `party`.

## Not changed

Decision, retreat, login, loot, and click code still call the same perception fields. The first sample after a cold start can lag by about one and a half seconds per module while the DLL attaches. Later ticks use the sample the module already pushed.
