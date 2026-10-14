# Autologin (portable)

Purple → Lineage Classic auto-login **with GUI**.  
Copy this entire folder anywhere. Uses **system Python** (already installed with packages) — no local `.venv`.

## Layout

```
autologin/
  main.py                 # GUI entry
  launcher_config.json
  run_ui.cmd / run_ui_as_admin.cmd
  run_bot.cmd
  run_live_as_admin.cmd / run_live_x3_as_admin.cmd
  ui/  launcher/  bot/  scripts/
  requirements.txt        # pip install -r (into system Python if needed)
```

## Run GUI

```bat
run_ui_as_admin.cmd
```

Or:

```bat
set PYTHONPATH=%CD%;%CD%\bot
python main.py
```

## Notes

- Install deps once into ManmabotV1's bundled Python:

```bat
cd ..\ManmabotV1
python\python.exe -m pip install -r requirements-autologin.txt
```

Or from this folder:

```bat
..\ManmabotV1\python\python.exe -m pip install -r requirements.txt
```
- Interception **kernel driver** must be installed OS-wide
- Prefer Administrator (UIPI)
- `bot\data\f.onnx` captcha model: optional; CAPTCHA solve stays disabled until later
- Config assets are relative under `bot/`
- Current Purple install default: `PurpleLauncher.exe` + `2.26.907.25\Purple.exe`
