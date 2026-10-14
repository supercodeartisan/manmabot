"""Thin Bot_ManmabotV1.exe entry: always run live ``run.py`` with bundled Python.

Prefer project sources over any frozen UI build.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    root = _root()
    run_py = root / "run.py"
    pythonw = root / "python" / "pythonw.exe"
    python = root / "python" / "python.exe"
    frozen = root / "Others" / "ManmabotV1.frozen.exe"
    if not frozen.is_file():
        frozen = root / "ManmabotV1.frozen.exe"
    exe = pythonw if pythonw.is_file() else python
    if run_py.is_file() and exe.is_file():
        os.chdir(str(root))
        os.execv(str(exe), [str(exe), str(run_py), *sys.argv[1:]])
    if frozen.is_file():
        os.chdir(str(root))
        os.execv(str(frozen), [str(frozen), *sys.argv[1:]])
    sys.stderr.write(
        f"Manmabot launcher: missing run.py/python under {root}\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
