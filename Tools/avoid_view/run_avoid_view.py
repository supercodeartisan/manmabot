"""Launch the avoidance map. Does not start the bot."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from avoid_view.gui import AvoidView
import tkinter as tk


def main() -> int:
    root = tk.Tk()
    AvoidView(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
