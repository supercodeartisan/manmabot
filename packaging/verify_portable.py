"""Quick checks for release/portable/ManmabotV1 after Stage 1."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"


def main() -> int:
    if not PORTABLE.is_dir():
        print(f"missing portable folder: {PORTABLE}", file=sys.stderr)
        return 1
    errors: list[str] = []
    for required in (
        PORTABLE / "run.py",
        PORTABLE / "Bot_Manmabot.bat",
        PORTABLE / ".portable",
        PORTABLE / "README.txt",
        PORTABLE / "Engine",
        PORTABLE / "UI" / "ui_qt",
        PORTABLE / "Drivers" / "SignedDriver" / "signeddrv.sys",
    ):
        if not required.exists():
            errors.append(f"missing required: {required.relative_to(PORTABLE)}")

    for forbidden_name in ("Tools", "Research", "Docs", "Others"):
        if (PORTABLE / forbidden_name).exists():
            errors.append(f"forbidden dir present: {forbidden_name}")

    if list(PORTABLE.glob("Tool_*")):
        errors.append("Tool_*.bat must not ship")
    if (PORTABLE / "Bot_Manmabot_Debug.bat").exists():
        errors.append("Bot_Manmabot_Debug.bat must not ship")
    if (PORTABLE / "UserData" / "accounts.json").exists():
        errors.append("UserData/accounts.json must not ship")
    if list(PORTABLE.rglob("*.c")) or list(PORTABLE.rglob("*.h")):
        errors.append("C/H sources must not ship")

    dlls = list((PORTABLE / "Engine" / "analysis").rglob("*.dll"))
    if len(dlls) < 8:
        errors.append(f"expected analysis DLLs, found {len(dlls)}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"OK — portable checks passed ({PORTABLE})")
    print(f"  analysis_dlls={len(dlls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
