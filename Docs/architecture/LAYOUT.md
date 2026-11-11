# Project layout

## Top-level

| Folder | Role | Runtime? |
|---|---|---|
| `Engine/` | Bot pipeline + session/settings/shop/hotbar glue | Yes |
| `UserData/` | Operator UI customize only (see `USERDATA_POLICY.md`) | Yes (read/write) |
| `Drivers/` | `Interception/` + `SignedDriver/` (signeddrv.sys / WinNotify) | Install / start |
| `UI/` | Operator UI (`ui` package) | Yes |
| `Docs/` | Documentation by topic | No |
| `Tools/` | Calibration / experiment tools | Optional |
| `Research/` | Research dumps (Extra_data, reference images) | No |
| `Others/` | Legacy maps copy, build leftovers, archived starters | No |
| `python/` | Bundled interpreter | Yes |

## Engine packages (find by intent)

```
Engine/app/           perception(read) → world(merge) → _02_state → decision → action
Engine/app/_01_perception/  sensors API only (tick + on-demand; Tools via same API)
Engine/app/_02_state/       GameState / Player / WorldObject / BattleArea / enums
Engine/app/_03_world/       merge/ + space/ + catalog/ + debug/ (no flat shims)
Engine/app/_04_decision/    sticky modes + ladders (see DECISION_HIERARCHY.md)
Engine/app/_05_action/      clicks + window geometry (4:3 bounds, optional preview grab)
                        # SLOT_IDS / SKILL_KEYS re-export from settings.spell_defaults
Engine/app/_06_party/       party leader schedule, member decide, invite, supply
                        # live callers: PartyLeaderManager, PartyMemberManager
                        # brains/ is not the session caller (see PARTY_RUNTIME.md)
Engine/session/       BotController, paths, probes, elevate, drivers
                        # world_nav_inject: normalize_routine + map overlays → blackboard
Engine/settings/      profile / schedule / accounts / farm overlays (UserData I/O)
                        # spell_defaults.SLOT_IDS = role catalog 정본
Engine/shop/          live NPC behaviors + runtime + slots/
Engine/hotbar/        live hotbar inspect/match + icons (+ icons_unique/zh_names.json)
Engine/i18n/          strings + localized names
Engine/login/         autologin_service adapter → Engine/autologin/
Engine/autologin/     full Purple/game login product tree
Engine/config/        YAML tunables
Engine/data/maps/     fixed map packs
Engine/data/npc_behaviors.yaml   buy / sell / warehouse / teleporter catalog
Engine/data/cursors/  cursor template PNGs
Engine/data/world*/   world graph / transitions
Engine/data/catalog/  skills / hotbar role map / icon catalog
                        # + list/ (monster/item/spell dumps; was analysis/list)
                        # more calibration assets may move here (see USERDATA_POLICY.md)
Engine/analysis/      memory modules: registry, src, data, core, dll (see ANALYSIS_MODULES.md)
Engine/manmabot_v1/   DEPRECATED shim (raises ImportError)
```

See also `Engine/PACKAGES.txt`.

## Drivers

```
Drivers/Interception/          input filter installer + .sys
Drivers/SignedDriver/
  signeddrv.sys                kernel memory driver (service WinNotify)
  load_signeddrv.ps1           start / stop / remove / status
```

Live bot starts SignedDriver through `session.monitor_launch.driver_script_path()`
→ `Drivers/SignedDriver/load_signeddrv.ps1`.  
`Engine/analysis/load_signeddrv.ps1` is a thin forwarder for old paths.

## Dependency rules

1. `UI → Engine → UserData / Drivers`
2. `Tools` may import Engine for experiments (`Tools/shopping`, `Tools/hotbar_tool`, …)
3. `Engine` must not import `UI`
4. `Research` is never on the live import path

## Docs topics

- `Docs/architecture/` — layout, `ANALYSIS_MODULES.md` (live memory path), `MEMORY_READ_CANON.md` (older listener DLLs), `USERDATA_POLICY.md`, `LOGIC_OVERVIEW.md`, `DECISION_HIERARCHY.md`, `DECISION_STEPS.md`, `ISSUE_idle_livelock.md`, `SENSOR_PRE_TIDY.md` (pre-sensor split; docs-only). Party: `PARTY_RUNTIME.md` (who runs), `PARTY_CODE_TO_ACTION.md` (intent to click), `PARTY_EDGE_CASES.md` (branches). `PARTY_MEMBER_ANALYSIS.md` and `PARTY_MEMBER_MVP.md` record the 2026-10-13 request and what of it is live.
- `Docs/decision/` — decision change log
- `Docs/combat/` — combat design / CODEX notes
- `Docs/prompt/` — master prompt + fragments
- `Docs/status/` — TODO / implementation status
