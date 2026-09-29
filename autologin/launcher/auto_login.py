"""Auto-login bridge: generates a per-account purple_login_<n>.json for the
login bot and spawns bot2.py as a subprocess.

The UI is the control surface: it starts/stops the login bot directly.
Purple is launched and driven by bot2.py — no svchost hollowing or
bot_loader injection.
"""
import json
import logging
import os
import subprocess
import sys
import time

from .bot_controller import is_alive, kill_process

logger = logging.getLogger(__name__)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Repository root (parent of src/). The virtualenv and other source-only
# dev artifacts live here; the bundled folders (bot/, loader/) live under src/.
_REPO_ROOT = os.path.dirname(_ROOT_DIR)


def _ensure_onefile_data(exe_dir):
    """Onefile extraction lives in a temporary _MEIPASS dir that dies with
    the process - the GUI writes its config, the bot writes login configs
    and run logs, and the bot subprocess must share those files. So seed a
    persistent '<exe_dir>/_data' copy of the readonly bundle data on first
    run and route all runtime paths there."""
    data_root = os.path.join(exe_dir, "_data")
    try:
        os.makedirs(data_root, exist_ok=True)
        import shutil
        meipass = getattr(sys, "_MEIPASS", None) or os.path.dirname(exe_dir)
        bot_dst = os.path.join(data_root, "bot")
        if not os.path.isdir(bot_dst):
            bot_src = os.path.join(meipass, "bot")
            tmp = bot_dst + ".tmp"
            if os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(bot_src, tmp)
            os.replace(tmp, bot_dst)
        cfg_dst = os.path.join(data_root, "launcher_config.json")
        if not os.path.isfile(cfg_dst):
            cfg_src = os.path.join(meipass, "launcher_config.json")
            if os.path.isfile(cfg_src):
                shutil.copyfile(cfg_src, cfg_dst)
        return data_root
    except Exception as e:
        logger.warning("onefile data seed failed (%r); using temp bundle", e)
        return getattr(sys, "_MEIPASS", exe_dir)


def _app_root():
    """Writable directory that contains bot/, loader/, launcher_config.json.

    Source: the src/ tree (source layout keeps all bundled folders under
    src/).
    Frozen onedir: the _internal bundle dir (writable on disk).
    Frozen onefile: a persistent <exe_dir>/_data dir seeded from the temp
    extraction (the TEMP_MEIPASS copy is destroyed on exit, so the GUI
    config, bot config handoff and run logs must live somewhere stable).
    """
    if not getattr(sys, "frozen", False):
        return _ROOT_DIR
    exe_dir = os.path.dirname(sys.executable)
    internal = os.path.join(exe_dir, "_internal")
    if os.path.isdir(internal):
        return internal                     # onedir: data is right there
    return _ensure_onefile_data(exe_dir)    # onefile: seed persistent copy


def bot_dir():
    return os.path.join(_app_root(), "bot")


def bot2_entry():
    return os.path.join(bot_dir(), "bot2.py")


def _launcher_config_path():
    return os.path.join(_app_root(), "launcher_config.json")

# region key -> (game ui language, ocr language)
REGION_LANG = {
        "Taiwan": ("zh-TW", "zh-TW"),
        "Korea": ("ko", "ko"),
        "Japan": ("ja", "ja"),
        "Hong Kong": ("zh-TW", "zh-TW"),
        "China": ("zh-CN", "zh-CN"),
}
DEFAULT_LANG = ("ko", "ko")


def _login_bot_dir():
    return bot_dir()


# assets that we prefer to resolve inside the bot/data folder (config.py
# already defaults to these, but a base config may carry stale absolute
# paths that would override them)


def _resolve_asset_path(cfg, key, rel):
    """Point a config path at data/<rel> when that file/folder exists locally,
    else fall back to the inherited/configured value."""
    local = os.path.join(bot_dir(), "data", rel)
    if os.path.exists(local):
        cfg[key] = os.path.join("data", rel)   # RELATIVE; load_config resolves to bot/base_dir
        return True
    return False


def apply_local_asset_paths(cfg):
    """Point model/DLL/map paths at their RELATIVE location inside bot/
    where the files exist, so a stale absolute path from the origin template
    never points at a missing file. Relative paths are resolved against the
    bot base_dir by config.load_config."""
    pairs = [
        ("interception_dll", "interception.dll"),
        ("yolo_model", "yolov8n.onnx"),
        ("captcha_model", "f.onnx"),
        ("click_map", "recorded_clicks.json"),
        ("character_dir", "character"),
    ]
    for key, filename in pairs:
        _resolve_asset_path(cfg, key, filename)
    # Prefer win/interception.dll (loaded by win.interception by default).
    win_dll = os.path.join(bot_dir(), "win", "interception.dll")
    if os.path.isfile(win_dll):
        cfg["interception_dll"] = os.path.join("win", "interception.dll")
    cfg.setdefault("session_backup_dir", "purple_session_backup")
    cfg.setdefault("debug_dir", ".")
    return cfg


def build_config(account, game_path, index=1, base_config=None, record_tag=False):
    """Build the per-account login config dict for one account.

    The launcher account is the SINGLE source of truth for credentials:
    userID/password/region/server ALWAYS come from the account row. The
    base_config (merged 'login' section of launcher_config.json) supplies the
    bot's game words, page positions, models and other non-credential settings.

    account: {id, pw, region, server}
    game_path: path to the Purple.exe we launched (always per-instance)
    base_config: optional base from launcher_config.json 'login' section
    record_tag: if True, bot runs in monitor-only mode to capture device tag
    """
    cfg = dict(base_config or {})
    if record_tag:
        cfg["record_tag"] = True

    # --- credentials ALWAYS from the launcher account ----------------------
    cfg["userID"] = (account.get("id") or "").strip()
    cfg["password"] = account.get("pw", "")

    # --- region / language: derived from the account region if not set -----
    if not (cfg.get("language") and cfg.get("ocr_lang")):
        lang = DEFAULT_LANG
        region = account.get("region") or ""
        if region in REGION_LANG:
            lang = REGION_LANG[region]
        cfg.setdefault("language", lang[0])
        cfg.setdefault("ocr_lang", lang[1])

    cfg["game_path"] = game_path
    cfg["character_number"] = int(cfg.get("character_number")
                                  or account.get("character_number") or 1)
    cfg["base_dir"] = bot_dir()
    mode = (account.get("click_mode") or cfg.get("click_mode") or "dynamic")
    mode_l = str(mode).lower()
    if mode_l in ("hybrid", "split"):
        cfg["click_mode"] = "hybrid"
        cfg.setdefault("purple_click_mode", "dynamic")
        cfg.setdefault("game_click_mode", "fixed")
    elif mode_l.startswith("fix"):
        cfg["click_mode"] = "fixed"
    else:
        cfg["click_mode"] = "dynamic"
    if cfg.get("purple_click_mode"):
        cfg["purple_click_mode"] = str(cfg["purple_click_mode"]).lower()
    if cfg.get("game_click_mode"):
        cfg["game_click_mode"] = str(cfg["game_click_mode"]).lower()
    cfg.setdefault("position_dict", os.path.join(bot_dir(), "position_dict.json"))

    # --- server select: prefer the account's server if given --------------
    server = (account.get("server") or "").strip()
    if server:
        words = cfg.setdefault("words", {})
        words["server_name"] = [server]

    apply_local_asset_paths(cfg)
    return cfg


def write_config(account, game_path, index=1, base_config=None, record_tag=False):
    """Serialize one account's config to bot/purple_login_<index>.json
    and return its path."""
    cfg = build_config(account, game_path, index=index,
                       base_config=base_config, record_tag=record_tag)
    path = os.path.join(bot_dir(), f"purple_login_{index}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return path


def load_base_config():
    """Return the bot's base settings from the merged launcher_config.json
    ('login' section). This is the single source of bot settings; there is no
    separate purple_login.json base anymore."""
    if not os.path.isfile(_launcher_config_path()):
        return {}
    try:
        with open(_launcher_config_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        base = dict(cfg.get("login") or {})
        if cfg.get("click_mode"):
            base.setdefault("click_mode", cfg["click_mode"])
        if cfg.get("purple_click_mode"):
            base.setdefault("purple_click_mode", cfg["purple_click_mode"])
        if cfg.get("game_click_mode"):
            base.setdefault("game_click_mode", cfg["game_click_mode"])
        if "use_pipeline" in cfg:
            base.setdefault("use_pipeline", cfg["use_pipeline"])
        if cfg.get("lang_policy"):
            base.setdefault("lang_policy", cfg["lang_policy"])
        if cfg.get("position_dict"):
            base.setdefault("position_dict", cfg["position_dict"])
        if "position_dict_writable" in cfg:
            base.setdefault("position_dict_writable",
                            cfg["position_dict_writable"])
        if "require_elevation" in cfg:
            base.setdefault("require_elevation", cfg["require_elevation"])
        for k in ("purple_force_size", "purple_shell_width",
                  "purple_shell_height", "purple_shell_size_tol",
                  "purple_fixed_timeout_sec",
                  "game_force_size", "game_shell_width",
                  "game_shell_height", "game_shell_size_tol",
                  "game_click_geom",
                  "auth_relaunch_max"):
            if k in cfg:
                base.setdefault(k, cfg[k])
            if k in (cfg.get("login") or {}):
                base[k] = cfg["login"][k]
        return base
    except Exception:
        return {}


def _bot_interpreter():
    """Executable used to run the login bot.

    Frozen: the bot runs inside THIS exe via the '--bot2' dispatch, so the
    interpreter IS the exe itself (same bundled runtime, models, OCR deps).
    Source / portable: always use the same python that launched the UI
    (system or active env). Do NOT hunt a sibling repo venv — portable
    packages expect an already-installed Python with deps.
    """
    return sys.executable


def wait_until_ready(config_path, timeout=30.0):
    """Poll until bot2.py has produced its run log (best-effort signal the
    process actually started)."""
    run_log = os.path.join(bot_dir(), "bot2_run.log")
    end = time.time() + timeout
    while time.time() < end:
        if os.path.isfile(run_log):
            return True
        time.sleep(0.5)
    return False


class LoginBot:
    """Spawns and supervises one bot/bot2.py process for an account.

    The login bot is itself UAC-self-elevating; it drives the Purple window
    to log in and start the game. We just own the child process lifecycle
    and tie its liveness to our account's running state.
    """

    def __init__(self, account_index, purple_pid, config_path,
                 on_log=None, record_tag=False):
        self.index = account_index
        self.purple_pid = purple_pid  # optional; bot2 launches Purple itself
        self.config_path = config_path
        self.on_log = on_log
        self.record_tag = record_tag
        self.proc = None
        self.state = "idle"

    def _log(self, msg):
        text = f"[Bot {self.index}][login] {msg}"
        logger.info(text)
        if self.on_log:
            self.on_log(text)

    def start(self):
        if not os.path.isfile(bot2_entry()):
            self._log(f"login bot entry missing: {bot2_entry()}")
            self.state = "error"
            return False
        try:
            if getattr(sys, "frozen", False):
                # Frozen: the bot runs in THIS exe via the --bot2 dispatch.
                cmd = [sys.executable, "--bot2", self.config_path]
            else:
                cmd = [_bot_interpreter(), bot2_entry(), self.config_path]
            if self.record_tag:
                cmd.append("--record-tag")
            self.proc = subprocess.Popen(cmd)
            self.state = "spawned"
            self._log(f"auto-login started (pid={self.proc.pid}, record_tag={self.record_tag})")
            return True
        except Exception as e:
            self._log(f"failed to start auto-login: {e}")
            self.state = "error"
            return False

    def stop(self):
        self.state = "stopped"
        if self.proc and self.proc.poll() is None:
            kill_process(self.proc.pid)
        self.proc = None

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None
