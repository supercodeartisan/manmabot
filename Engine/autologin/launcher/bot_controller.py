import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

logger = logging.getLogger(__name__)

# LC crash watchdog: when the claimed LC.exe game dies, the
# controller tears the whole session down and relaunches the auto-login flow
# from scratch, up to MAX_LC_RESTARTS times with a cooldown between cycles.
_LC_IMAGE_NAMES = ("lc.exe", "lineage.exe", "lineageclassic.exe")
_MAX_LC_RESTARTS = 3
_LC_RESTART_COOLDOWN = 2.5

_single_instance_blocked = set()
_single_instance_lock = threading.Lock()

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.TerminateProcess.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                    ctypes.POINTER(wintypes.DWORD)]
k32.GetExitCodeProcess.restype = wintypes.BOOL


def is_alive(pid):
    if not pid:
        return False
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = wintypes.DWORD(0)
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return ok and code.value == 259


def kill_process(pid):
    if not pid:
        return
    h = k32.OpenProcess(0x001F0FFF, False, pid)
    if h:
        k32.TerminateProcess(h, 1)
        k32.CloseHandle(h)
    os.system(f"taskkill /F /PID {pid} >nul 2>&1")
    os.system(f"taskkill /F /T /PID {pid} >nul 2>&1")


def image_pids(image_name):
    try:
        out = os.popen(
            f'tasklist /FI "IMAGENAME eq {image_name}" /FO CSV /NH'
        ).read()
        pids = set()
        for line in out.splitlines():
            parts = [x.strip('"') for x in line.split('","')]
            if len(parts) >= 2 and parts[0] and parts[1].isdigit():
                if parts[0].lower() == image_name.lower():
                    pids.add(int(parts[1]))
        return pids
    except Exception:
        return set()


def close_all_purple():
    """Kill leftover Purple.exe / PurpleLauncher.exe."""
    killed = []
    for name in ("Purple.exe", "PurpleLauncher.exe"):
        for pid in list(image_pids(name)):
            kill_process(pid)
            killed.append(pid)
    return killed


class BotAccount:
    """UI-controlled auto-login session.

    The launcher UI starts bot2.py directly. Purple is launched and driven
    by the login bot — there is no svchost hollowing or bot_loader injection.
    """

    def __init__(self, account_idx, purple_path, on_log=None, account=None,
                 auto_login=False, record_tag=False, exclusive_purple=False):
        self.idx = account_idx
        self.purple_path = purple_path
        self.on_log = on_log
        self.account = account or {}
        self.auto_login = auto_login
        self.record_tag = record_tag
        self.exclusive_purple = exclusive_purple
        self.login_bot = None

        self.purple_pid = None
        self.config_path = None
        self.state = "idle"
        self._image_name = os.path.basename(purple_path or "Purple.exe")
        self._pre_purple_pids = set()
        self.unlock_done = threading.Event()
        self.lc_pid = None
        self.lc_restarts = 0

        self._stop_event = threading.Event()
        self._thread = None

    def _log(self, msg):
        text = f"[Bot {self.idx}] {msg}"
        logger.info(text)
        if self.on_log:
            self.on_log(text)

    def start(self, reset_restarts=True):
        with _single_instance_lock:
            _single_instance_blocked.discard(self.idx)
        if reset_restarts:
            self.lc_restarts = 0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, kill_purple=False):
        self._stop_event.set()
        if self.login_bot is not None:
            self._log("Stopping auto-login bot...")
            self.login_bot.stop()
            self.login_bot = None
        if kill_purple and self.purple_pid and self.exclusive_purple:
            self._log("Terminating Purple.exe...")
            kill_process(self.purple_pid)
        if self.config_path and os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception:
                pass
        self.purple_pid = None
        self.lc_pid = None
        self.state = "idle"

    def _run(self):
        try:
            self._run_inner()
        finally:
            self.unlock_done.set()

    def _run_inner(self):
        if not self.auto_login and not self.record_tag:
            self._log("No account credentials; auto-login not started")
            self.state = "error"
            return

        self.state = "starting"
        self._pre_purple_pids = self._image_pids(self._image_name)
        self._log("Starting auto-login bot (UI control — no process injection)")
        self.unlock_done.set()

        self._start_auto_login()
        if self.login_bot is None or self.login_bot.state == "error":
            self.state = "error"
            return

        if self._stop_event.is_set():
            self.state = "stopped"
            return

        self._wait_for_purple(timeout=120.0)

        if self._stop_event.is_set():
            self.state = "stopped"
            return

        if self.state in ("timeout", "error"):
            self._log(f"Bot {self.idx} failed during startup (state: {self.state})")
            self.stop()
            return

        self.state = "running"
        if self.purple_pid:
            self._log(f"Purple.exe detected (PID: {self.purple_pid})")
        else:
            self._log("Auto-login running (Purple will be launched by the bot)")

        while not self._stop_event.is_set():
            if self._watch_lc():
                return
            if self.login_bot is not None and not self.login_bot.is_alive():
                self._log("auto-login bot exited")
                self.login_bot = None
                self.state = "bot_exited"
                break
            if not self.purple_pid:
                self._refresh_purple_pid()
            time.sleep(1)

        if self.state in ("running", "purple_dead", "lc_failed", "bot_exited"):
            self._log(f"Bot {self.idx} stopped (state: {self.state})")
            self.stop(kill_purple=False)

    def _watch_lc(self):
        """LC crash watchdog. Returns True when a full restart was triggered."""
        if not self.auto_login or self._stop_event.is_set():
            return False
        if self.lc_pid is None:
            lc = self._claim_lc()
            if lc:
                self.lc_pid = lc
                self._log(f"LC game detected (PID: {self.lc_pid}); watching for exit")
            return False
        if is_alive(self.lc_pid):
            return False
        self._log(f"LC game exited (PID: {self.lc_pid})")
        self.lc_pid = None
        if self.lc_restarts >= _MAX_LC_RESTARTS:
            self._log(f"LC crashed {_MAX_LC_RESTARTS} time(s); giving up")
            self.stop(kill_purple=False)
            self.state = "lc_failed"
            return True
        self.lc_restarts += 1
        self._log(f"LC crashed — restarting auto-login "
                  f"(attempt {self.lc_restarts}/{_MAX_LC_RESTARTS})")
        self._restart_for_lc()
        return False

    def _claim_lc(self):
        """Return an LC.exe pid owned by our Purple session, if any."""
        if not self.purple_pid:
            self._refresh_purple_pid()
        if not self.purple_pid:
            return None
        for name in _LC_IMAGE_NAMES:
            for pid in sorted(self._image_pids(name)):
                if self._is_descendant_of(pid, self.purple_pid):
                    return pid
        return None

    def _is_descendant_of(self, pid, ancestor):
        if not pid or not ancestor:
            return False
        seen = set()
        cur = pid
        for _ in range(10):
            if not cur or cur in seen:
                return False
            seen.add(cur)
            if cur == ancestor:
                return True
            cur = self._get_parent_pid(cur)
        return False

    def _restart_for_lc(self):
        self._log("restarting auto-login for game relaunch (keeping Purple)")
        if self.login_bot is not None:
            self.login_bot.stop()
            self.login_bot = None
        self.lc_pid = None
        time.sleep(_LC_RESTART_COOLDOWN)
        self._start_auto_login()
        if self.login_bot is None or self.login_bot.state == "error":
            self.state = "error"
            return
        self._refresh_purple_pid()
        self.state = "running"

    def _start_auto_login(self):
        try:
            from launcher.auto_login import (
                load_base_config, write_config, LoginBot)
        except Exception as e:
            self._log(f"[login] module unavailable: {e}")
            self.state = "error"
            return
        try:
            base = load_base_config()
            cfg_path = write_config(self.account, self.purple_path,
                                    index=self.idx, base_config=base,
                                    record_tag=self.record_tag)
            self.config_path = cfg_path
            bot = LoginBot(self.idx, None, cfg_path,
                           on_log=self.on_log, record_tag=self.record_tag)
            if bot.start():
                self.login_bot = bot
            else:
                self.state = "error"
        except Exception as e:
            self._log(f"[login] failed: {e}")
            self.state = "error"

    def _image_pids(self, image_name):
        return image_pids(image_name)

    def _refresh_purple_pid(self):
        current = self._image_pids(self._image_name)
        new_pids = current - self._pre_purple_pids
        if new_pids:
            self.purple_pid = sorted(new_pids)[-1]
            return
        if self.exclusive_purple and current:
            self.purple_pid = sorted(current)[-1]

    def _wait_for_purple(self, timeout=120.0):
        """Best-effort: note when Purple.exe appears (bot2 launches it)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._stop_event.is_set():
                return
            if self.login_bot is not None and not self.login_bot.is_alive():
                self._log("auto-login bot exited before Purple appeared")
                self.state = "error"
                return
            self._refresh_purple_pid()
            if self.purple_pid:
                return
            time.sleep(0.5)
        # Not fatal — bot2 may still be launching Purple on a later tick.
        self._log("Purple.exe not detected yet; bot continues in background")

    def _get_parent_pid(self, pid):
        try:
            import subprocess
            ps_cmd = (
                f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}")'
                '.ParentProcessId'
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5)
            out = result.stdout.strip()
            if out.isdigit():
                return int(out)
        except Exception:
            pass
        return None
