import logging
import os
import sys
import tkinter as tk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])


def _run_bot2_cli():
    """Frozen dispatch: <exe> --bot2 <config> runs the bundled bot as this
    same exe instead of spawning a separate python.exe."""
    if not getattr(sys, "frozen", False):
        return False
    err_log = None
    try:
        from launcher.auto_login import bot_dir, bot2_entry
        bot2_path = bot2_entry()
        err_log = os.path.join(bot_dir(), "bot2_dispatch.log")
        if not os.path.isfile(bot2_path):
            raise FileNotFoundError(bot2_path)
        sys.path.insert(0, bot_dir())
        args = [bot2_path]
        args += [a for a in sys.argv[1:] if a != "--bot2"]
        sys.argv = args
        import runpy
        runpy.run_path(bot2_path, run_name="__main__")
        return True
    except Exception:
        import traceback
        try:
            with open(err_log or os.devnull, "a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            traceback.print_exc()
        return True


if __name__ == "__main__":
    os.system("")
    if "--bot2" in sys.argv and _run_bot2_cli():
        sys.exit(0)
    if "--selftest" in sys.argv:
        import ui.selftest
        sys.exit(ui.selftest.main())

    from launcher.elevate import ensure_elevated_or_continue
    elev = ensure_elevated_or_continue()
    if elev == "relaunched":
        # Elevated child owns the UI; exit the medium-integrity parent.
        sys.exit(0)

    root = tk.Tk()
    from ui.main_window import MainWindow
    app = MainWindow(root)
    if elev in ("declined", "skipped"):
        # Surface a soft warning once the UI is up (do not block).
        try:
            app.warn_not_elevated()
        except Exception:
            pass
    root.mainloop()
