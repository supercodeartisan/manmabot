# lc930 — vendored memory_stand_dist (9.30)

Single-source registry + in-process readers for Manmabot.

| Path | Role |
|---|---|
| `registry/LC930_REGISTRY.txt` | Offsets / poll keys (SSOT) |
| `registry/region_table.tsv` | mapId+cell → region names |
| `data/data_string.csv…` | Buff / name strID → KR |
| `dungeon/` | Static portal / floor data |
| `core/` | `lcore.h` / `lcreg.h` / signeddrv |
| `buff/buff_listen.dll` | Active buffs JSON (`extra`/`lbuff.h` BuffSubsystem map walk) |
| `core/lbuff.h` | Shared buff engine from `E:\Lineage\extra` |
| `uidialog/uidialog_listen.dll` | Dialog open/closed JSON (stand BFS + RESCAN) |
| `docs/buff.md` | Buff read spec (no recast) |
| `docs/uidialog.md` | Dialog open/closed + Esc/gate |

Build: `build_new_readers.bat`

Python:

- Each `capture_tick` sync-reads buff + uidialog (parallel threads, no cache)
- → `GameState.player.buffs` / `last_uidialog`
- Esc unexpected OPEN; 3s OPEN gate for shop/storage/teleporter/talking scroll

Buff: every poll walks BuffSubsystem `unordered_map` (no BFS).
