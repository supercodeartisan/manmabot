"""Request UAC and relaunch Supply Practice elevated (enter_chat / Interception)."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().parent / "run_supply_practice.py"


def _pick_python() -> Path:
    for name in ("pythonw.exe", "python.exe"):
        cand = REPO / "python" / name
        if cand.is_file():
            return cand
    exe = Path(sys.executable).resolve()
    sibling = exe.with_name("pythonw.exe")
    if sibling.is_file():
        return sibling
    return exe


def main() -> int:
    exe = _pick_python()
    if not exe.is_file():
        print(f"Python not found (tried {exe})")
        return 1
    if not SCRIPT.is_file():
        print(f"Missing {SCRIPT}")
        return 1
    params = f'"{SCRIPT}"'
    # ShellExecuteW runas — avoids PowerShell Start-Process -LiteralPath
    # (missing on Windows PowerShell 5.1).
    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe),
            params,
            str(REPO),
            1,
        )
        or 0
    )
    if rc <= 32:
        print(
            f"Elevation failed (ShellExecute={rc}). "
            "Accept the UAC prompt, or right-click Tool_Supply_Practice.bat "
            "→ Run as administrator."
        )
        try:
            input("Press Enter to close…")
        except EOFError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
