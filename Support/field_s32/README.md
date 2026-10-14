# Field `.s32` sources (not for distribution)

Offline input for Talking Island / mainland nav prebuild.

| Pack id | Folder | Typical source |
|---------|--------|----------------|
| `talking_island` | `Support/field_s32/talking_island/` | `D:\map_0` |
| `mainland` | `Support/field_s32/mainland/` | `D:\map_4` |

**Do not ship this tree with the bot.** Runtime uses only:

- `Engine/data/maps/<pack>/nav.png`
- `Engine/data/maps/<pack>/nav_prebuild/` (includes `edge_*.npy`)
- pack `meta.yaml` / area YAMLs

Older PNGs / drafts live under `Engine/data/maps/<pack>/legacy/` (optional; not required at runtime).

## Rebuild (edge + fence)

Use the **field edge** builder only. Do **not** run `Build_Nav_Prebuild.bat` on these packs — that PNG-only path refuses edge packs (and would otherwise strip fences).

```text
Tools\nav\Build_Field_Edge_Packs.bat
Tools\nav\Build_Field_Edge_Packs.bat --only talking_island
Tools\nav\Build_Field_Edge_Packs.bat --only mainland
```

Dungeon / non-edge packs still use `Tools\nav\Build_Nav_Prebuild.bat`.
