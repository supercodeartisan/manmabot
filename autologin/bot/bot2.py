"""Bot v2 - same launcher flow as bot.py (proven), new engine from the
agreement dialog onward (gameflow.GameFlow).

Why: bot.py works well up to the agree click. From there it relied on heavy
OCR of DirectX content plus blind step timeouts - the source of most
failures. GameFlow replaces that segment with multi-scale anchor matching,
window-ratio clicks, click verification, a hard time budget, and full
Interception-driver input.

Usage:  python bot2.py [path\\to\\purple_login.json]
"""
import logging
import os
import sys
import threading
import time

import ctypes
import ctypes.wintypes

from auth_relaunch_state import (
    clear_auth_relaunch_state,
    load_auth_relaunch_state,
)
from base import Bot, Phase
from devicetag import backup_device_tag
from gameflow import GameFlow, GameFlowError
from uilang import LANGS

log = logging.getLogger("bot2")

class Bot2(Bot):
    def __init__(self, config_path: str):
        super().__init__(config_path)
        self.flow = None
        hint = self.cfg.get("language")
        if hint in LANGS:
            self.lang = hint
        self._shake_after_relaunch = False
        # AUTH_CHOICE close+relaunch budget (default 2 per session).
        self._auth_relaunch_count = 0
        self._auth_relaunch_used = False  # True when count >= auth_relaunch_max
        # Survive controller killing bot2 after intentional AUTH LC close.
        load_auth_relaunch_state(self)
        if self._shake_after_relaunch or self._auth_relaunch_count:
            log.info("startup: restored AUTH state shake=%s count=%d used=%s",
                     self._shake_after_relaunch,
                     self._auth_relaunch_count,
                     self._auth_relaunch_used)
        # Prefer saved credential/launcher ratios only as last-resort locate.
        # Screen classify + template match gate every click (purple_gate_clicks).
        store = getattr(self, "positions", None)
        if (store is not None
                and bool(self.cfg.get("purple_force_size", True))
                and not getattr(self, "_purple_fixed_fallback_done", False)):
            from positions import MODE_FIXED
            if store.purple_mode != MODE_FIXED:
                log.info("Purple shell: purple_mode %s -> fixed "
                         "(force_size + familiar layout)", store.purple_mode)
                store.purple_mode = MODE_FIXED
        if self._try_attach_running_purple():
            decision = self._classify_attached_purple()
            if decision == "FIND_LINEAGE":
                self._mark_purple_logged_in()
                self.phase = Phase.FIND_LINEAGE
                self.phase_start = time.time()
                log.info("startup: Purple already logged in (%dx%d)",
                         self.purple.rect.width, self.purple.rect.height)
            else:
                self._purple_logged_in = False
                self.phase = Phase.WAIT_LOGIN_FORM
                self.phase_start = time.time()
                log.info("startup: Purple attached but needs login (%dx%d) -> %s",
                         self.purple.rect.width, self.purple.rect.height,
                         decision or "WAIT_LOGIN_FORM")
        # person detector for the character-select screen (used by GameFlow)
        if not hasattr(self, "_person_detector") or self._person_detector is None:
            try:
                from vision.person_detector import PersonDetector
                model = self.cfg.get("yolo_model", "") or \
                    os.path.join(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__))),
                        "data", "yolov8n.onnx")
                self._person_detector = PersonDetector(model)
                log.info("person detector ready for character select")
            except Exception as e:
                self._person_detector = None
                log.warning("person detector unavailable: %s", e)

    # ------------------------------------------------------------------
    # launcher discovery/launch hardening
    # ------------------------------------------------------------------
    def find_purple(self) -> bool:
        if super().find_purple():
            if self.purple and self.purple.rect.width >= 900:
                return True
            if self._restore_hidden_purple():
                return True
            return self.purple is not None and self.purple.valid
        return self._restore_hidden_purple()

    def launch_purple(self):
        """Launch the Purple UI. Purple.exe carries a requireAdministrator
        manifest, so a plain CreateProcess from a medium-integrity shell
        fails with WinError 740 - route through ShellExecute (os.startfile)
        which shows the UAC consent prompt instead. Backs off when the user
        cancels the prompt."""
        if self._try_attach_running_purple():
            log.info("attached to running Purple (skipping elevated launch)")
            return
        if self._purple_process_running() or self._any_purple_window_exists():
            log.info("skip elevated launch: Purple already present")
            return
        try:
            super().launch_purple()
            return
        except OSError as e:
            if getattr(e, "winerror", None) != 740:
                raise
        if time.time() - getattr(self, "_elev_launch_at", 0.0) < 30.0:
            return                      # user recently cancelled - back off
        log.info("Purple.exe requires elevation; requesting via ShellExecute")
        self._elev_launch_at = time.time()
        try:
            os.startfile(self.game_path)   # UAC prompt on the user's screen
        except Exception as e:
            log.warning("elevated launch declined/failed: %r", e)

    def run_pipeline(self, max_seconds: float = 600.0):
        """Staged remodel runner (S0–S7). Enabled with cfg use_pipeline=true.

        Existing Phase.tick paths remain the default until stages are fully
        cut over; this runner orchestrates them and centralizes exceptions.
        Returns ``success``, ``failed``, ``timeout``, or ``cancelled``.
        """
        from pipeline import PipelineContext, PipelineRunner

        lang_policy = str(self.cfg.get("lang_policy") or "L0").strip().upper() or "L0"
        # Keep bot.cfg in sync so GameFlow.__init__ sees the same policy.
        self.cfg["lang_policy"] = lang_policy
        # Forced familiar shell size → fixed Purple clicks are valid again.
        # Exception: after a fixed stall, stay on dynamic for this session.
        store = getattr(self, "positions", None)
        if store is not None:
            if (bool(self.cfg.get("purple_force_size", True))
                    and not getattr(self, "_purple_fixed_fallback_done", False)):
                from positions import MODE_FIXED
                if store.purple_mode != MODE_FIXED:
                    log.info("pipeline: purple_mode -> fixed (force_size)")
                    store.purple_mode = MODE_FIXED
            if not bool(self.cfg.get("position_dict_writable")):
                store.set_writable(False)

        ctx = PipelineContext(
            bot=self,
            cfg=dict(self.cfg or {}),
            lang_policy=lang_policy,
            purple_logged_in=bool(getattr(self, "_purple_logged_in", False)),
            auth_relaunch_used=bool(getattr(self, "_auth_relaunch_used", False)),
            auth_relaunch_count=int(getattr(self, "_auth_relaunch_count", 0) or 0),
            shake_armed=bool(getattr(self, "_shake_after_relaunch", False)),
        )
        runner = PipelineRunner(ctx)
        t0 = time.time()
        log.info("pipeline start order=%s lang_policy=%s purple_mode=%s",
                 runner.order, ctx.lang_policy,
                 getattr(store, "purple_mode", "?"))
        outcome = "timeout"
        while time.time() - t0 < max_seconds:
            if getattr(self, "_shutdown_requested", False):
                log.info("pipeline stop: shutdown requested")
                outcome = "cancelled"
                break
            result = runner.tick()
            if runner.failed:
                log.error("pipeline FAILED at %s: %s",
                          result.stage_id, result.message)
                try:
                    from base import Phase
                    self._set_phase(Phase.ERROR)
                except Exception:
                    pass
                outcome = "failed"
                break
            if runner.finished:
                log.info("pipeline FINISHED: %s",
                         (result.message if result else "done"))
                outcome = "success"
                break
        else:
            log.warning("pipeline timeout after %.0fs", max_seconds)
            outcome = "timeout"
        try:
            self._cleanup()
        except Exception:
            pass
        return outcome

    # ------------------------------------------------------------------
    def do_game_login(self):
        """Game phase: keep the window healthy, run security splash exactly
        like bot.py (it works), then hand everything from the agreement
        dialog on to GameFlow."""
        # stop-file kill switch (create D:\login\STOP to shut the bot down)
        stop_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "STOP")
        if os.path.exists(stop_file):
            log.warning("STOP file detected - shutting down")
            try:
                os.remove(stop_file)
            except OSError:
                pass
            self.request_shutdown()
            return

        # --- window find / re-target (same semantics as bot.py) -----------
        if not self.game or not self.game.valid:
            if self.find_game():
                self._ensure_fresh_flow()
            else:
                now = time.time()
                lost_at = getattr(self, "_game_lost_at", 0.0)
                if lost_at == 0.0:
                    self._game_lost_at = now
                elif now - lost_at > 60:
                    if not self._game_process_alive():
                        log.warning("game process gone; restarting launch flow")
                        self._restart()
                        return
                    self._game_lost_at = now
                time.sleep(0.3)
                return
        else:
            self._game_lost_at = 0.0
            if not self._is_real_game(self.game.hwnd):
                real = self._real_game_hwnd()
                if real is not None:
                    log.info("re-targeting to real game window")
                    self.game = type(self.game)(real)
                    self._ensure_fresh_flow()

        self._ensure_fresh_flow()
        if self.flow is None:
            return
        try:
            state = self.flow.tick()
        except GameFlowError as e:
            log.error("GameFlow failed: %s", e)
            self.flow.release()
            self._set_phase(Phase.ERROR)
            return
        if getattr(self.flow, "restart_requested", False):
            # flow closed the game and restarted the launch phase; drop the
            # engine so a fresh one starts with the next game window
            self.flow = None
            return
        if state == "INGAME" and self.flow.done:
            log.info("IN GAME - login complete")
            self.flow.release()
            clear_auth_relaunch_state(self)
            backup_device_tag(self.session_backup_dir)
            self._set_phase(Phase.DONE)

    def _ensure_fresh_flow(self):
        """Start the engine on a new game window; replace it after a
        퍼플간편인증 restart."""
        if self.flow is None or getattr(self.flow, "restart_requested",
                                        False):
            self.flow = None
            self._start_flow()

    def _start_flow(self):
        try:
            self.flow = GameFlow(self, lang=self.lang)
        except GameFlowError as e:
            log.error("cannot start GameFlow: %s", e)
            self._set_phase(Phase.ERROR)


def _is_elevated() -> bool:
    """True when this process runs with a high-integrity (elevated) token.

    Purple.exe and the game it launches are ELEVATED (requireAdministrator).
    Windows UIPI silently blocks every window manipulation (SetWindowPos,
    ShowWindow, z-order, messages) from a medium-integrity process on a
    high-integrity window - so without elevation the bot can never bring
    the game window to the top. Running elevated removes the whole class
    of failures (and makes the Purple UAC prompt unnecessary)."""
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated() -> bool:
    """Re-exec this script elevated (one UAC prompt), with all output
    redirected to a log file the non-elevated shell can read - an elevated
    console closes instantly on a crash and its traceback would be lost.
    The --elevated-relaunch marker prevents infinite relaunch loops."""
    if "--elevated-relaunch" in sys.argv:
        return False
    try:
        shell32 = ctypes.WinDLL("shell32")
        here = os.path.dirname(os.path.abspath(__file__))
        out_log = os.path.join(here, "bot2_elev_out.log")
        # Frozen: this process IS the bundled exe, so the relaunch target is
        # the exe itself and the script slot becomes the '--bot2' dispatch
        # marker (a bare script path would be ignored by the frozen app).
        if getattr(sys, "frozen", False):
            target = "--bot2"
        else:
            target = os.path.abspath(sys.argv[0])
        rest = [a for a in sys.argv[1:] if a != "--bot2"]
        params = " ".join('"%s"' % a for a in [target] + rest)
        params += ' --elevated-relaunch'
        cmd = ('/c ""%s" %s > "%s" 2>&1"'
               % (sys.executable, params, out_log))
        ret = shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 0)
        return ret > 32
    except Exception as e:
        log.warning("elevation failed: %r", e)
        return False


def _acquire_single_instance():
    """One bot2 process at a time. A second instance pastes the email again."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    k32.CreateMutexW.argtypes = [
        ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    k32.SetLastError(0)
    handle = k32.CreateMutexW(None, True, "Global\\HEBOT_BOT2_SINGLE")
    if k32.GetLastError() == 183:
        log.error("another bot2 is already running; this instance will exit")
        return None
    return handle


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # file log: the elevated instance runs in its own console, so persist
    # its output where the (non-elevated) shell can read it
    here = os.path.dirname(os.path.abspath(__file__))
    _fh = logging.FileHandler(os.path.join(here, "bot2_run.log"),
                              mode="a", encoding="utf-8")
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)

    def _hook(exc_type, exc_value, exc_tb):
        logging.getLogger("bot2").critical("unhandled exception",
                                           exc_info=(exc_type, exc_value,
                                                     exc_tb))
    sys.excepthook = _hook

    from supervisor_io import (
        cancel_requested,
        parse_supervisor_args,
        publish_run,
    )

    flags = parse_supervisor_args(
        sys.argv[1:],
        default_config=os.path.join(here, "purple_login.json"),
    )
    cfg_path = flags.config
    if not _is_elevated():
        if flags.elevated_relaunch:
            log.warning("elevated relaunch did not gain elevation "
                        "(UAC declined?) - continuing without")
        elif flags.no_self_elevate:
            log.info("supervisor asked not to self-elevate; continuing")
        else:
            log.info("bot is not elevated; requesting elevation (one UAC "
                     "prompt) - required to control the elevated game "
                     "window")
            if _relaunch_elevated():
                return 0
            log.warning("continuing WITHOUT elevation - game-window focus "
                        "will rely on Alt+Esc input fallback")
    lock = _acquire_single_instance()
    if lock is None:
        return publish_run(flags, state="failed", detail="another bot2 is already running")
    bot = None
    outcome = "failed"
    detail = ""
    try:
        bot = Bot2(cfg_path)

        def _watch_cancel() -> None:
            while not getattr(bot, "_shutdown_requested", False):
                if cancel_requested(flags.cancel_path):
                    log.info("supervisor cancel file present; shutting down")
                    bot.request_shutdown()
                    return
                time.sleep(0.2)

        if flags.cancel_path:
            threading.Thread(
                target=_watch_cancel, name="bot2-cancel", daemon=True
            ).start()
        if bot.cfg.get("use_pipeline"):
            log.info("use_pipeline=1 — staged PipelineRunner (S0–S7)")
            outcome = bot.run_pipeline(max_seconds=flags.timeout) or "failed"
        else:
            bot.run(max_seconds=flags.timeout)
            outcome = "success" if bot.phase == Phase.DONE else (
                "cancelled" if getattr(bot, "_shutdown_requested", False)
                else "failed"
            )
        detail = "pipeline %s" % outcome
    except Exception as exc:
        log.exception("bot2 crashed")
        outcome = "failed"
        detail = str(exc)
        if bot is not None:
            try:
                bot._cleanup()
            except Exception:
                pass
    code = publish_run(flags, state=outcome, detail=detail)
    return code


if __name__ == "__main__":
    raise SystemExit(main() or 0)
