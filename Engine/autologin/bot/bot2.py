"""Thin keep-script: autologin spawns this file by path.

Implementation lives in ``bot2_core`` (Nuitka ``.pyd`` in customer builds).
"""
from __future__ import annotations

from bot2_core import Bot2, main

__all__ = ["Bot2", "main"]


if __name__ == "__main__":
    raise SystemExit(main() or 0)
