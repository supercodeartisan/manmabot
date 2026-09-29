"""Config loading with DPAPI password decryption (reuses purple_login.json)."""
import base64
import ctypes
import json
import os
import sys
from pathlib import Path

_DPAPI_CRYPT = 0x01  # CRYPTPROTECT_UI_FORBIDDEN

# Default paths (can be overridden by config or environment).
# Portable layout: assets live under bot/data and bot/win relative to this file.
DEFAULT_BASE_DIR = Path(__file__).parent
DEFAULT_INTERCEPTION_DLL = DEFAULT_BASE_DIR / "win" / "interception.dll"
DEFAULT_YOLO_MODEL = DEFAULT_BASE_DIR / "data" / "yolov8n.onnx"
DEFAULT_CAPTCHA_MODEL = DEFAULT_BASE_DIR / "data" / "f.onnx"
DEFAULT_CLICK_MAP = DEFAULT_BASE_DIR / "data" / "recorded_clicks.json"
DEFAULT_SESSION_BACKUP_DIR = DEFAULT_BASE_DIR / "purple_session_backup"
DEFAULT_DEBUG_DIR = DEFAULT_BASE_DIR
DEFAULT_CHARACTER_DIR = DEFAULT_BASE_DIR / "data" / "character"
DEFAULT_GAME_PATHS = [
    os.path.expandvars(r"%PROGRAMFILES(x86)%\NC\Purple\PurpleLauncher.exe"),
    os.path.expandvars(r"%PROGRAMFILES(x86)%\NC\Purple\Purple.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Purple\Purple.exe"),
    r"C:\Program Files (x86)\NC\Purple\2.26.907.25\Purple.exe",
    r"C:\Program Files (x86)\NC\Purple\2.26.907.20\Purple.exe",
]


def _dpapi_unprotect(encoded: str) -> str:
    blob = base64.b64decode(encoded)
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]
    in_blob = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob), ctypes.c_void_p))
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    local = ctypes.windll.kernel32.LocalFree
    local.argtypes = [ctypes.c_void_p]
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, _DPAPI_CRYPT, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return data.decode("utf-8")
    finally:
        local(out_blob.pbData)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    # Plaintext password field is preferred (easy to edit the JSON directly).
    pw = cfg.get("password", "")
    if not pw:
        enc = cfg.get("password_enc") or ""
        try:
            pw = _dpapi_unprotect(enc)
        except Exception:
            pw = ""
    cfg["password"] = pw

    # Resolve configurable paths with defaults
    base_dir = Path(cfg.get("base_dir", DEFAULT_BASE_DIR))

    # Resolve any RELATIVE path entry against base_dir (login_beta) so the
    # config files can use portable relative paths. Absolute entries (e.g. a
    # stale D:\... path from the origin template) are left untouched.
    def _resolve(k, fallback):
        v = cfg.get(k)
        if v:
            p = Path(v)
            if not p.is_absolute():
                v = str(base_dir / p)
        else:
            v = str(fallback)
        cfg[k] = v

    _resolve("interception_dll", DEFAULT_INTERCEPTION_DLL)
    _resolve("yolo_model", DEFAULT_YOLO_MODEL)
    _resolve("captcha_model", DEFAULT_CAPTCHA_MODEL)
    _resolve("click_map", DEFAULT_CLICK_MAP)
    _resolve("session_backup_dir", DEFAULT_SESSION_BACKUP_DIR)
    _resolve("debug_dir", DEFAULT_DEBUG_DIR)
    _resolve("character_dir", DEFAULT_CHARACTER_DIR)
    cfg.setdefault("game_paths", list(DEFAULT_GAME_PATHS))
    # If game_path is missing/invalid, try known install locations.
    gp = cfg.get("game_path") or ""
    if not gp or not os.path.isfile(gp):
        for cand in cfg.get("game_paths") or []:
            if cand and os.path.isfile(cand):
                cfg["game_path"] = cand
                break

    return cfg


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "purple_login.json")
    if os.path.exists(p):
        c = load_config(p)
        print(f"userID={c.get('userID') or c.get('username')}")
        print(f"password_len={len(c.get('password') or '')}")
        print(f"game_path={c.get('game_path')}")
    else:
        print(f"no config at {p}")
