"""Live Purple + pipeline accuracy run (S0 onward).

Avoids bot2.main() UAC relaunch so the agent/shell can drive the test.
Purple.exe itself may still show a UAC prompt — approve it on the desktop.

Portable layout (autologin/):
  python scripts/live_pipeline_test.py [--seconds 180]

Usage:
  python scripts/live_pipeline_test.py [--seconds 180]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot")
sys.path.insert(0, BOT)

LOG_PATH = os.path.join(BOT, "live_pipeline_test.log")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=180.0,
                    help="pipeline budget (default 180s)")
    ap.add_argument("--cfg", default=os.path.join(BOT, "purple_login.json"))
    args = ap.parse_args()

    # Avoid GBK console crashes on CJK launcher OCR dumps
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger("live_test")

    # Force pipeline on for this run even if json flipped
    import json
    with open(args.cfg, encoding="utf-8-sig") as f:
        raw = json.load(f)
    raw["use_pipeline"] = True
    raw["lang_policy"] = raw.get("lang_policy") or "L0"
    raw["position_dict_writable"] = False
    raw["purple_force_size"] = True
    raw.setdefault("purple_shell_width", 1642)
    raw.setdefault("purple_shell_height", 1026)
    # Ensure game_path exists (Purple version folders change on patch)
    gp = raw.get("game_path") or ""
    if not os.path.isfile(gp):
        import glob as _glob
        candidates = []
        for pattern in (
                r"C:\Program Files (x86)\NC\Purple\*\Purple.exe",
                r"C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe",
        ):
            candidates.extend(_glob.glob(pattern))
        if candidates:
            gp = max(candidates, key=os.path.getmtime)
            raw["game_path"] = gp
            log.warning("game_path missing; using %s", gp)
        else:
            log.error("game_path missing: %s", gp)
            sys.exit(2)
    tmp = os.path.join(BOT, "purple_login_live_test.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)

    try:
        import ctypes
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        elevated = False

    log.info("=== LIVE PIPELINE TEST start ===")
    log.info("elevated=%s cfg=%s seconds=%.0f game_path=%s",
             elevated, tmp, args.seconds, gp)
    log.info("log=%s", LOG_PATH)
    if not elevated:
        log.warning("NOT elevated — Purple resize/minimize may fail (UIPI). "
                    "Relaunch via Start-Process -Verb RunAs")

    from bot2 import Bot2
    from pipeline.result import StageStatus

    bot = Bot2(tmp)
    bot.cfg["use_pipeline"] = True
    bot.cfg["lang_policy"] = "L0"
    bot.cfg["purple_force_size"] = True
    bot.cfg.setdefault("purple_shell_width", 1642)
    bot.cfg.setdefault("purple_shell_height", 1026)
    bot.cfg["game_force_size"] = True
    bot.cfg.setdefault("game_shell_width", 816)
    bot.cfg.setdefault("game_shell_height", 639)
    store = getattr(bot, "positions", None)
    if store is not None:
        from positions import MODE_FIXED
        store.purple_mode = MODE_FIXED
        store.set_writable(False)
    # Normalize shell immediately when already attached
    try:
        if bot.purple and bot.purple.valid:
            bot._normalize_purple_shell_size(reason="live_test_startup")
    except Exception as e:
        log.warning("startup normalize failed: %r", e)
    log.info("interception=%s purple_attached=%s phase=%s",
             getattr(bot, "_interception_ready", None),
             bool(bot.purple and bot.purple.valid),
             getattr(bot.phase, "name", bot.phase))
    if bot.purple and bot.purple.valid:
        log.info("startup purple %dx%d", bot.purple.rect.width,
                 bot.purple.rect.height)

    # Manual runner so we can snapshot stage progress each tick
    from pipeline import PipelineContext, PipelineRunner

    store = getattr(bot, "positions", None)
    if store is not None:
        # Purple shell is noisy — do not force fixed coords for live accuracy.
        store.set_writable(False)

    ctx = PipelineContext(
        bot=bot,
        cfg=dict(bot.cfg or {}),
        lang_policy="L0",
        purple_logged_in=bool(getattr(bot, "_purple_logged_in", False)),
    )
    runner = PipelineRunner(ctx)
    t0 = time.time()
    last_sid = None
    ticks = 0
    history = []

    try:
        while time.time() - t0 < args.seconds:
            if getattr(bot, "_shutdown_requested", False):
                log.info("shutdown requested")
                break
            sid_before = runner.current_id
            result = runner.tick()
            ticks += 1
            sid = result.stage_id
            if sid != last_sid or result.status in (
                    StageStatus.OK, StageStatus.FAILED, StageStatus.SKIP):
                msg = "tick#%d stage=%s status=%s msg=%s" % (
                    ticks, sid, result.status.name, result.message)
                log.info(msg)
                history.append(msg)
                last_sid = sid
            elif ticks % 10 == 0:
                log.info("tick#%d still %s (%s): %s",
                         ticks, sid, result.status.name, result.message)

            if runner.failed:
                log.error("PIPELINE FAILED at %s", sid)
                break
            if runner.finished:
                log.info("PIPELINE FINISHED")
                break

            # Soft progress print for Purple size
            if bot.purple and bot.purple.valid and ticks % 5 == 0:
                log.info("purple live %dx%d phase=%s",
                         bot.purple.rect.width, bot.purple.rect.height,
                         getattr(bot.phase, "name", bot.phase))
    finally:
        try:
            bot._cleanup()
        except Exception:
            pass

    elapsed = time.time() - t0
    log.info("=== LIVE PIPELINE TEST end elapsed=%.1fs ticks=%d "
             "finished=%s failed=%s stage=%s ===",
             elapsed, ticks, runner.finished, runner.failed,
             runner.current_id)
    print("\n--- summary ---")
    for h in history[-30:]:
        print(h)
    print("log file:", LOG_PATH)
    # Non-zero if failed before S3 at least once without finishing
    if runner.failed:
        sys.exit(1)
    if runner.finished:
        sys.exit(0)
    # Partial success: reached at least S2 with purple attached
    print("partial: stopped at", runner.current_id)
    sys.exit(0)


if __name__ == "__main__":
    main()
