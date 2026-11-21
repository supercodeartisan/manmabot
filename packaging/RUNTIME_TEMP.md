# Runtime TEMP / pack wiring (Phase 1)

## Flow

```text
run_entry.main
  → wipe_stale_analysis_temps()
  → ensure_packed_assets()
       → data.pack     → load_pack_files (MMB2|MMBA) → asset_store.mount_bytes
       → analysis_text → load_pack_files → %TEMP%/manmabot_an_<128bit>/ + overlay
  → RealtimeMonitorReader(default_offsets_path) → absolute TEMP …/registry/offsets.json
```

## Rules

- No public `decrypt(path, cek)` API — CEK only via `AuthorizedSession` / `Mmb2Reader`.
- Dev plain `Engine/data` → data pack skipped.
- No analysis pack → overlay cleared; readers use `Engine/analysis`.
- MMB2 requires `UserData/license/{ticket,envelope}.json` + trusted kid (seller keygen) unless tests pass `session=` into `load_pack_files`.
- Login / move / combat / HP / party **decision** logic unchanged.

## Multi-instance

Each process creates its own `manmabot_an_*` with `owner.pid` + lock. Stale dirs (dead pid) are wiped; live dirs are protected.
