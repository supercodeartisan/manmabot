# 11-4analysis — LCAPI DLL kit

This tree is **generated from `11_04/dist`** and contains:

- the 29 reader EXEs
- the LCAPI module DLLs (17)
- `src/`, `core/`, `registry/`, `data/`
- `build_all.bat` (EXEs) and `build_bot_modules.bat` (DLLs)

The DLL **exports and calling convention are unchanged**:

```
lcapi_abi_version
lcapi_configure(registry, interval_ms, jitter_ms, count, out_dir)
lcapi_set_params("KEY=VALUE;...")
lcapi_run(sink, ctx, err, err_cap)
```

The sink text format is produced by the original module sources; it is not changed.

## Layout

```
bin/           29 exe + out/
core/          shared headers/driver client
data/          item/message name tables + dungeon/
dll/           *.dll, *.lib, *.exp (no .obj in the shipped kit)
registry/      LC930_REGISTRY.txt, region_table.tsv
src/           module sources + src/api
build_all.bat
build_bot_modules.bat
MANIFEST.txt
```

## Build

```
build_all.bat            :: 29 EXEs -> bin\
build_bot_modules.bat    :: 17 DLLs -> dll\
```

## Loader notes

- Host must be x64.
- `WinNotify` (signeddrv) must be running and the host must be elevated.
- `LC.exe` must be running; attach fails otherwise.
- Pass the **absolute registry path** to `lcapi_configure`. The DLL also resolves
  its own directory (`dll\` -> parent) for `registry/` and `data/`, so it no longer
  depends on the host CWD.
- Output is delivered through the sink; EXE mode writes `bin\out\*_out.txt`.

## Regenerate

From the `11_04` tree:

```
powershell -File tools\make_analysis_from_dist.ps1 -Force
```

Optional:

```
-Dist <path\to\dist> -Out <path\to\11-4analysis> -SkipBuild
```
