"""Frozen-runtime self-test: imports every module the launcher and the login
bot need, and verifies the bundled path layout resolves the way the frozen
code expects. Run inside the bundled exe via:

    hebot.exe --selftest [out_log]

Results are written to the given log path (a windowed exe has no console).
Exit code is 0 when everything imported, 1 otherwise."""
import os
import sys

STEPS = [
    "cv2",
    "numpy",
    "psutil",
    "onnxruntime",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageGrab",
    "PIL.ImageOps",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media.ocr",
    "winrt.windows.storage",
    "winrt.windows.storage.streams",
    "rapidocr_onnxruntime",
    "launcher.bot_controller",
    "launcher.auto_login",
    "launcher.elevate",
    "bot.win.interception",
    "bot.win.winwindow",
    "bot.win.winocr",
    "bot.input.inputrouter",
    "bot.vision.person_detector",
    "bot.config",
    "bot.gameflow",
    "bot.base",
]


def main():
    args = sys.argv[sys.argv.index("--selftest") + 1:]
    out = args[0] if args else os.path.join(
        os.environ.get("TEMP", "."), "hebot_selftest.log")
    ok = True

    # The bot package uses FLAT imports ("from win import ..", "from config
    # import ..") that only resolve with the bot dir itself on sys.path -
    # exactly what the frozen '--bot2' dispatch does. Mirror that here so
    # 'bot.*' imports succeed in both source and frozen runs.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from launcher.auto_login import bot_dir
    sys.path.insert(0, bot_dir())
    with open(out, "w", encoding="utf-8") as f:
        def log(msg):
            print(msg, file=f)
            f.flush()

        for mod in STEPS:
            try:
                __import__(mod)
                log("OK   %s" % mod)
            except Exception as e:
                ok = False
                log("FAIL %s: %r" % (mod, e))

        try:
            from launcher.auto_login import bot_dir, bot2_entry
            bd = bot_dir()
            be = bot2_entry()
            log("OK   bot_dir    -> %s (exists=%s)" % (bd, os.path.isdir(bd)))
            log("OK   bot2_entry -> %s (exists=%s)" % (be, os.path.isfile(be)))
            if not (os.path.isdir(bd) and os.path.isfile(be)):
                ok = False
        except Exception as e:
            ok = False
            log("FAIL path resolution: %r" % e)

        log("SELFTEST %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1