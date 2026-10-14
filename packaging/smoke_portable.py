"""Local checks for the customer folder. Does not log in or start the game.

Run with the portable interpreter, after unpack_customer_data.py and before
Stage 4. Do not launch the bot UI before checksums.

    release\\portable\\ManmabotV1\\python\\python.exe packaging\\smoke_portable.py
"""
from __future__ import annotations

import sys
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"
ENGINE = PORTABLE / "Engine"


def main() -> int:
    errors: list[str] = []
    if not PORTABLE.is_dir():
        print(f"ERROR: missing {PORTABLE}", file=sys.stderr)
        return 1

    expected = Path(sys.executable).resolve()
    bundled = (PORTABLE / "python" / "python.exe").resolve()
    if expected != bundled:
        errors.append(f"run this with {bundled}, not {expected}")

    sys.path[:0] = [str(PORTABLE), str(ENGINE), str(PORTABLE / "UI")]

    try:
        import cv2

        print(f"OK cv2 {cv2.__version__}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cv2 import failed: {exc}")

    data = ENGINE / "data"
    pack = ENGINE / "data.pack"
    analysis = ENGINE / "analysis_text.pack"
    skills = data / "catalog" / "skills_names.json"
    if pack.exists():
        errors.append("Engine/data.pack must be removed after unpack")
    if not data.is_dir():
        errors.append("Engine/data directory is missing")
    elif not skills.is_file():
        errors.append(f"missing {skills}")
    else:
        is_json = skills.read_text(encoding="utf-8")[:1] == "{"
        print(f"OK skills_names.json bytes={skills.stat().st_size} json={is_json}")
    maps = list((data / "maps").rglob("meta.yaml")) if (data / "maps").is_dir() else []
    if not maps:
        errors.append("no map meta.yaml under Engine/data/maps")
    else:
        print(f"OK map meta files={len(maps)}")
    if not analysis.is_file():
        errors.append("missing Engine/analysis_text.pack")
    else:
        print(f"OK analysis_text.pack bytes={analysis.stat().st_size}")

    for banned in ("Tools", "Research", "Docs", "Others"):
        if (PORTABLE / banned).exists():
            errors.append(f"customer folder contains {banned}")
    run_py = PORTABLE / "run.py"
    if not run_py.is_file():
        errors.append("run.py missing")
    else:
        run_text = run_py.read_text(encoding="utf-8")
        # Thin keep-script dispatches to session.run_entry (.pyd); older builds
        # called ensure_packed_assets inline in run.py.
        if "run_entry" not in run_text and "ensure_packed_assets" not in run_text:
            errors.append(
                "run.py must import session.run_entry or call ensure_packed_assets"
            )
        else:
            print("OK run.py keep-script entry")
    try:
        from session import run_entry

        if not callable(getattr(run_entry, "main", None)):
            errors.append("session.run_entry.main missing")
        else:
            print("OK session.run_entry.main importable")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"session.run_entry import failed: {exc}")
    bot2 = ENGINE / "autologin" / "bot" / "bot2.py"
    if not bot2.is_file():
        errors.append("bot2.py was compiled away; keep_scripts.txt must keep it")
    else:
        bot2_text = bot2.read_text(encoding="utf-8")
        if "bot2_core" not in bot2_text and "class Bot2" not in bot2_text:
            errors.append("bot2.py must import bot2_core or define Bot2")
        else:
            print("OK bot2.py kept as a script")
    bot2_core = list((ENGINE / "autologin" / "bot").glob("bot2_core*.pyd"))
    bot2_core_py = ENGINE / "autologin" / "bot" / "bot2_core.py"
    if not bot2_core and not bot2_core_py.is_file():
        errors.append("missing bot2_core (.pyd or .py)")
    else:
        print(f"OK bot2_core present pyd={bool(bot2_core)}")

    try:
        from PySide6.QtCore import Qt
        from ui_qt.widgets.flow_layout import FlowLayout

        ok = FlowLayout().expandingDirections() == Qt.Orientations(0)
        print(f"OK flow_layout zero={ok}")
        if not ok:
            errors.append("FlowLayout.expandingDirections is not Qt.Orientations(0)")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"flow_layout check failed: {exc}")

    if errors:
        print("SMOKE FAILED", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
