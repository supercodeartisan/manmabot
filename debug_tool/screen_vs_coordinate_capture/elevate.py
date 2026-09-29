"""Request UAC and relaunch this folder's run.py as Administrator."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "run.py"


def find_python() -> Path:
    exe = Path(sys.executable).resolve()
    if exe.suffix.lower() == ".exe":
        sibling = exe.with_name("pythonw.exe")
        if sibling.is_file():
            return sibling
        if exe.is_file():
            return exe
    for root in (HERE, *HERE.parents[:5]):
        for name in ("pythonw.exe", "python.exe"):
            cand = root / "python" / name
            if cand.is_file():
                return cand
    return exe


def main() -> int:
    exe = find_python()
    if not exe.is_file():
        print(f"Python not found (tried {exe})")
        return 1
    if not SCRIPT.is_file():
        print(f"Missing {SCRIPT}")
        return 1
    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe),
            f'"{SCRIPT}"',
            str(HERE),
            1,
        )
    )
    if rc <= 32:
        print(
            f"Elevation failed (ShellExecute={rc}). "
            "Accept the UAC prompt, or right-click run.bat → Run as administrator."
        )
        try:
            input("Press Enter to close…")
        except EOFError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
