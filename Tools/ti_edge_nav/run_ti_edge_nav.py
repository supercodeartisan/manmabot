"""Launch TI edge-nav live avoid tool. Does not touch Engine nav_prebuild."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

import tkinter as tk

from ti_edge_nav.gui import TiEdgeNavView


def main() -> int:
    root = tk.Tk()
    TiEdgeNavView(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
