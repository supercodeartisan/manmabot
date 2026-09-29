"""Request UAC and relaunch Shopping Practice elevated (for memory pipe)."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve().parent / "run_shopping_practice.py"


def main() -> int:
    pyw = ROOT / "python" / "pythonw.exe"
    py = ROOT / "python" / "python.exe"
    exe = pyw if pyw.is_file() else py
    if not exe.is_file():
        print(f"Bundled Python not found under {ROOT / 'python'}")
        return 1
    if not SCRIPT.is_file():
        print(f"Missing {SCRIPT}")
        return 1
    # Quote the script path so spaces / parentheses survive ShellExecute.
    params = f'"{SCRIPT}"'
    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe),
            params,
            str(ROOT),
            1,
        )
    )
    if rc <= 32:
        print(
            f"Elevation failed (ShellExecute={rc}). "
            "Accept the UAC prompt, or right-click the bat → Run as administrator."
        )
        try:
            input("Press Enter to close…")
        except EOFError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
