"""Post-Stage-2 import smoke test using the portable embeddable Python."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"


def main() -> int:
    if not PORTABLE.is_dir():
        print(f"missing {PORTABLE}", file=sys.stderr)
        return 1

    engine = PORTABLE / "Engine"
    ui = PORTABLE / "UI"
    sys.path[:0] = [str(PORTABLE), str(engine), str(ui)]

    errors: list[str] = []

    bot2 = PORTABLE / "Engine" / "autologin" / "bot" / "bot2.py"
    if not bot2.is_file():
        errors.append("keep script missing: Engine/autologin/bot/bot2.py")
    if not (PORTABLE / "run.py").is_file():
        errors.append("keep script missing: run.py")

    # Compiled modules should load as extension modules.
    checks = [
        ("session.paths", "app_root"),
        ("app._02_state.gamestate", None),
        ("settings.profile", None),
        ("i18n.strings", None),
        ("ui.operator_coordinator", None),
        ("ui_qt.app", None),
    ]
    for mod_name, attr in checks:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            loader = type(getattr(mod, "__loader__", None)).__name__
            print(f"OK import {mod_name} loader={loader}")
            if attr and not hasattr(mod, attr):
                errors.append(f"{mod_name} missing attr {attr}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"import {mod_name}: {exc}")

    # RBF-001: player_monitor must resolve realtime_monitor_reader via package
    # import even when the .py was stripped after Nuitka compile.
    try:
        import os

        os.environ.setdefault("MANMABOT_ROOT", str(engine))
        from session.player_monitor import reader_module

        mon_mod = reader_module()
        loader = type(getattr(mon_mod, "__loader__", None)).__name__
        print(f"OK player_monitor.reader_module loader={loader}")
        if not callable(getattr(mon_mod, "shared_monitor", None)):
            errors.append("player_monitor reader missing shared_monitor()")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"player_monitor reader load (RBF-001): {exc}")

    pyds = list((PORTABLE / "Engine").rglob("*.pyd")) + list((PORTABLE / "UI").rglob("*.pyd"))
    print(f"pyd_count={len(pyds)}")
    if len(pyds) < 200:
        errors.append(f"expected many .pyd files, found {len(pyds)}")

    # Decision logic sources should mostly be gone.
    decision_py = list((PORTABLE / "Engine" / "app" / "_04_decision").rglob("*.py"))
    decision_py = [p for p in decision_py if p.name != "__init__.py"]
    print(f"decision_non_init_py={len(decision_py)}")
    if decision_py:
        errors.append(
            "decision .py still present: "
            + ", ".join(p.name for p in decision_py[:8])
        )

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("OK — Stage 2 import smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
