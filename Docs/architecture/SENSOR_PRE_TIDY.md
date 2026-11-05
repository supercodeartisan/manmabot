# Sensor pre-tidy (before package split)

Status: planning only. No runtime moves yet.  
Goal: freeze contracts, classify `Engine/analysis`, plan catalog home.  
Out of scope: Interception merge, GameState `last_*` removal, decision/HP/combat edits.

## 1. Intended layers (target)

| Layer | Owns | Does not own |
| --- | --- | --- |
| Sensor (observe) | DLL + offsets/registry/settings; `capture_*` | Catalogs, GameState, Interception |
| Catalog / data | `list` dumps, species overlays | Memory reads |
| World merge | Buffer → typed + sticky world stats | Opening DLLs |
| Decision | Reads GameState | Sensor JSON shapes (eventually) |
| Actuator | Interception / mouse / key | Authority memory reads |

Sensor and Interception are siblings under the input layer — not one package.

## 2. Runtime sensor assets (today)

| Module | DLL | Settings / offsets |
| --- | --- | --- |
| player | `analysis/realtime_monitor.dll` | `offsets.json` (+ `char_offsets.txt`, `zone_table.json` in C) |
| entities | `analysis/entities/print_state.dll` | `settings_print_state.json`, `entity_offsets.txt` |
| attacks_me | `analysis/combat_attack/attacks_me.dll` | `settings_attacks_me.json` |
| contested | `analysis/combat_attack/contested_mobs.dll` | `settings_contested_mobs.json` |
| inventory | `analysis/inventories/inventory_listen.dll` | `offsets.json`, `inventory_offsets.txt` |
| hotbar | `analysis/Hotbar/hotbar_listen.dll` | `skill_offsets.txt` (+ inv names) |
| buff | `analysis/lc930/buff/buff_listen.dll` | `lc930/registry/LC930_REGISTRY.txt` |
| uidialog | `analysis/lc930/uidialog/uidialog_listen.dll` | same registry |
| shop | `analysis/NPC_conv/shop_listen.dll` | beside DLL |

Python entry: `app/_01_perception` readers + `PerceptionSensors`.

## 3. Catalogs (not sensors)

| Today | Planned |
| --- | --- |
| `Engine/data/catalog/list/` | **done** (moved from `analysis/list`) |
| `_03_world/catalog/species_*.json` | optionally `Engine/data/catalog/` later |
| `game_catalog.py` / `zh_convert.py` | stay under `_03_world/catalog/` (path root only) |

Used for: species name→key/level, items (sell/HP), spell MP costs, UI pickers.  
Do not place under a future Sensor tree.

## 4. Must-not-break invariants

- mapId: MapSubsystem path only (`mgr → holder → subs → vft → MapIdOff`)
- Farm click roster: `print_state` entities (monitor `entities` empty in bot DLL)
- Vitals: monitor then print_state HP/MP overlay; mid-execute pose may refresh and patch print player xy
- `force_attacks_me` liveness: still in `last_attacks_me` (not in print_state)
- Buff: `last_buff` with `cache>0` and empty `buffs` → timer fallback (false empty)
- Partial ticks: hotbar/inventory/attacks caches — do not clear sticky fields when a sensor is skipped
- Uidialog: mid-act poll via `capture_uidialog` / `uidialog_gate` (shop OPEN wait)
- Packaging: DLLs on disk; offset text may come from `analysis_text.pack` at run

## 5. `Engine/analysis` classification

| Path | Tag |
| --- | --- |
| `realtime_monitor.dll`, `offsets.json`, `char_offsets.txt` | RUNTIME |
| `entities/print_state*.dll`, settings + `entity_offsets.txt` | RUNTIME |
| `combat_attack/attacks_me.dll`, `contested_mobs.dll`, settings | RUNTIME |
| `inventories/inventory_listen.dll`, offsets TXT/JSON | RUNTIME |
| `Hotbar/hotbar_listen*.dll`, `skill_offsets.txt` | RUNTIME |
| `lc930/buff` / `uidialog` DLLs, `registry/LC930_REGISTRY.txt` | RUNTIME |
| `NPC_conv/shop_listen.dll` | RUNTIME |
| `list/` | moved → `Engine/data/catalog/list/` |
| `*.c`, `*.h`, `build_*.bat` | BUILD |
| `probe_*`, `entlocate`, `invsync`, `skilllocate`, combat scratch `.py` | RESEARCH |
| `*.jsonl`, probe outs, scratch dumps | IGNORE |
| `lc930/docs`, README | RESEARCH / docs |
| `load_signeddrv.ps1` | LEGACY forwarder (prefer `Drivers/SignedDriver`) |

## 6. Baseline tests (before any move)

Ran 2026-10-16 with `PYTHONPATH=Engine;UI`, `MANMABOT_ROOT=Engine`.

| Scope | Result |
| --- | --- |
| `test_game_catalog.py` | all pass (list/ catalogs) |
| `test_localized_names.py` | all pass |
| `test_hp_actions.py` | all pass (uses item catalog) |
| Full `Others/tests` (ignore 3 legacy collect-broken) | **564 passed**, 20 failed, 3 collect-ignored |

Catalog-related failures in the full run (pre-existing, not from this doc):

- `test_mother_tree_mana_reserve.py::test_expensive_live_spell_blocked_only_when_mother_tree_on`
- `test_memory_entities.py::test_decision_rows_are_memory_only` (hold semantics; file had IndentationError — import indent fixed so suite can collect)

Other failures (combat/UI/schedule/unstick/etc.) are unrelated to catalog path; treat as known noise for the list/ move.

Collect-ignored (stale imports / wrong trees): `test_autologin_pipeline`, `test_game_geom`, `test_server_lookup`.

**Gate for step 3 (list move):** `test_game_catalog` + `test_localized_names` + `test_hp_actions` must still all pass after retarget.

**Post-move gate (2026-10-16):** those three suites still all pass.  
`test_mother_tree_mana_reserve` still has the one pre-existing fail (mana reserve logic, not path).

## 7. Pre-tidy order (safe → later)

1. This doc — done
2. Classify only (table above) — done
3. Baseline tests (section 6) — done
4. Move `analysis/list` → `data/catalog/list` + retarget loaders — done
5. Optional: relocate RESEARCH out of `analysis`
6. Stop. Sensor package split is a separate project

## 8. Explicitly not now

- Delete or replace `GameState.last_*`
- Seal sensors so action never re-reads
- Rename `_01_perception` / move DLLs into the app tree
- Decision / HP / combat / login logic changes

## See also

- `Docs/architecture/LAYOUT.md`
- `Docs/architecture/LOGIC_OVERVIEW.md`
- `Docs/architecture/MEMORY_READ_CANON.md`
