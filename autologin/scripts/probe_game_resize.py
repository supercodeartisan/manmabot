"""Probe whether SetWindowPos can force the LC game window size.

Run elevated while Lineage Classic is open:

  python scripts/probe_game_resize.py
  # or
  Start-Process python -ArgumentList scripts\\probe_game_resize.py -Verb RunAs

Tries an arbitrary size (900x700) then the familiar dialog size (816x639).
"""
from __future__ import annotations

import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))

from win.winwindow import WindowFinder, WinWindow  # noqa: E402


def main():
    try:
        elev = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        elev = False
    print("elevated=%s" % elev)

    hwnd = None
    for h, title, cls, rc in WindowFinder._enum_top_level():
        w, hh = rc.right - rc.left, rc.bottom - rc.top
        if w < 400 or hh < 300:
            continue
        if cls == "GLFW30" or (title and "Lineage" in title):
            hwnd = h
            print("found hwnd=%s title=%r class=%s size=%dx%d at (%d,%d)"
                  % (h, title, cls, w, hh, rc.left, rc.top))
            break
    if not hwnd:
        print("NO_GAME_WINDOW — start LC then re-run elevated")
        return 2

    win = WinWindow(hwnd)
    r0 = win.rect
    print("before %dx%d" % (r0.width, r0.height))

    def try_size(w, h, tag):
        ok = win.resize(w, h, left=r0.left, top=r0.top)
        r = win.rect
        matched = abs(r.width - w) <= 12 and abs(r.height - h) <= 12
        print("%s: SetWindowPos=%s now=%dx%d matched=%s"
              % (tag, ok, r.width, r.height, matched))
        return matched

    arb = try_size(900, 700, "arbitrary_900x700")
    fam = try_size(816, 639, "familiar_816x639")
    # restore original
    win.resize(r0.width, r0.height, left=r0.left, top=r0.top)
    r = win.rect
    print("restored %dx%d" % (r.width, r.height))
    print("RESULT arbitrary=%s familiar=%s elevated=%s"
          % (arb, fam, elev))
    if not elev and not (arb or fam):
        print("HINT: UIPI likely blocked resize — re-run as Administrator")
        return 1
    return 0 if (arb or fam) else 3


if __name__ == "__main__":
    raise SystemExit(main())
