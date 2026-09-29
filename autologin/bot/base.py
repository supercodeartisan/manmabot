"""Option D state machine: Purple login -> launch LC -> game login.

Every interaction is window-targeted:
  - find windows by process name (Purple.exe / LC.exe)
  - OCR runs on PrintWindow capture of that window only (client coords)
  - clicks use the Interception driver as the primary mouse method, with
    Win32/SendInput as the fallback (foreground SendInput)
"""
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Tuple

from config import load_config
from devicetag import backup_device_tag, restore_device_tag
from input.inputrouter import InputRouter
from win.winocr import (OcrLine, OcrWord, WinOcr, fuzzy_match_label,
                        label_normalize, normalize, _ratio,
                        USERNAME_EMAIL_KEYWORDS, RUN_GAME_KEYWORDS,
                        LINEAGE_CARD_KEYWORDS)
from win.winwindow import Rect, WindowFinder, WinWindow
from captcha import CaptchaSolver, detect_captcha_region
from uilang import LANGS, WINOCR_TAGS, detect_ui_lang, has_cjk, has_hangul
from PIL import Image, ImageDraw
import ctypes
import ctypes.wintypes as wt
import psutil

from win import interception

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

log = logging.getLogger("bot")


class Phase(Enum):
    IDLE = auto()
    FIND_PURPLE = auto()
    WAIT_LOGIN_FORM = auto()
    ENTER_CREDENTIALS = auto()
    WAIT_MAIN = auto()
    FIND_LINEAGE = auto()
    CLICK_PLAY = auto()
    WAIT_GAME = auto()
    GAME_LOGIN = auto()
    DONE = auto()
    ERROR = auto()


# Default game-login sub-steps (can be overridden via config "words").
# agree (step 0) is special: click the FIRST CHARACTER (checkbox at left edge).
# NEW FLOW: 0=agree, 1=page, 2=server, 3=OK, 4=character, 5=OK→DONE
DEFAULT_GAME_STEPS = {
    0: {"words": ["동의합니다", "동의함", "agree", "I agree", "Accept",
                  "동의", "同意", "我同意"],
        "click": "center",
        "exclude": ["안", "동의서", "동의 안", "하지 않",
                    "不同意", "拒絕", "拒绝", "Disagree", "Decline"],
        "label": "agree", "fuzzy": 0.4},
    1: {"words": ["2"], "click": "center", "label": "page 2", "fuzzy": 0.45},
    2: {"words": ["린델", "린델 서버"], "click": "center", "label": "린델", "fuzzy": 0.45},
    3: {"words": ["Ok", "OK", "ok", "확인", "確定", "确定", "確認", "Confirm", "Yes"],
        "click": "center", "label": "OK"},
    4: {"click": "ratio", "label": "character #1", "ratio": (0.215, 0.313)},
    5: {"words": ["Ok", "OK", "ok", "확인", "確定", "确定", "確認", "Confirm"],
        "click": "center", "label": "OK final"},
}

# Labels/buttons can be ko, en, zh-TW, or zh-CN on any step.
MULTI_UI_WORDS = {
    "login": ["로그인", "Login", "Log in", "Sign in", "다음", "Next",
              "登入", "登录", "確定", "确定", "下一步"],
    "lineage_nav": ["Lineage", "Lineage Classic", "Classic", "리니지 클래식",
                    "天堂經典", "天堂经典", "리니지"],
    "lineage_card": ["Lineage Classic", "Lineage classic", "Lineage",
                     "리니지 클래식", "天堂經典", "天堂经典"],
    "start_game": ["运行游戏", "Start Game", "Start", "PLAY", "Play", "게임 시작", "시작",
                   "開始遊戲", "开始游戏", "開始", "开始"],
    "id_field": ["用户名/电子邮箱", "用户名", "电子邮箱",
                 "ID or E-mail", "ID Or E-mail", "ID or e-mail", "ID or email",
                 "ID/E-mail", "ID/E-mail Address", "ID E-mail",
                 "이메일", "電子郵件", "电子邮箱", "電郵"],
}
# Device-verification choice screen (shown when deviceTag is missing). Choosing
# "기기등록" registers this PC and leads to the deviceTag being written after
# login; avoid the "폰 간편 인증" (phone) option. Only acts when the screen
# also contains an "인증" (authentication) header so we never mistake an
# unrelated "등록" text for the button.
DEFAULT_DEVICE_REG = {
    "words": ["기기등록", "기기 등록", "裝置登錄", "裝置註冊", "设备注册",
              "装置登录", "设备登录", "Register device", "Device registration"],
    "avoid": ["폰", "手機", "手机", "phone"],
    "context": ["인증", "간편", "단계", "驗證", "验证", "认证", "authentication",
                "選擇驗證方法", "选择验证方法"],
}
GAME_STEP_TIMEOUT = 90.0
GAME_WAIT_AFTER_SERVER = 5.0

_BOT_DIR = Path(__file__).resolve().parent
LINEAGE_CARD_TM = _BOT_DIR / "data" / "lineage_classic_card.png"
PURPLE_REF_W = 1642.0
PURPLE_REF_H = 1026.0
# Familiar LC login-dialog outer size after splash/security (live + page_positions).
GAME_REF_W = 816
GAME_REF_H = 639
LINEAGE_CARD_TM_THRESH = 0.62
LINEAGE_CARD_SCALE_SWEEP = (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.25)
# After left-nav click the game grid redraws; keep settle short for template/OCR.
# (Fixed/ratio card clicks do not wait this — only vision fallback.)
LINEAGE_CARD_SETTLE_SEC = 0.35
LINEAGE_NAV_PAUSE_SEC = 0.12
LINEAGE_CARD_PAUSE_SEC = 0.12

class Bot:
    # Window titles of the phone/QR login forms must NEVER be treated as the
    # email login form (they contain 'Log in a phone number' etc).
    _NON_EMAIL_LOGIN_TITLES = [
        "phone number", "phone_number", "phone", "qr code", "qr code",
        "휴대폰", "폰", "qr", "手機", "手机", "電話", "二维码",
    ]
    # Placeholder / tab labels for the email ID field (zh-CN / en / ko / zh-TW).
    _ID_EMAIL_LABELS = [
        "用户名/电子邮箱", "用户名", "电子邮箱",
        "ID or E-mail", "ID Or E-mail", "ID or e-mail", "ID or email",
        "ID/E-mail", "ID/E-mail Address", "ID E-mail",
        "이메일", "電子郵件", "电子邮箱", "電郵",
    ]
    LABEL_USERNAME_EMAIL = "用户名/电子邮箱"
    LABEL_RUN_GAME = "运行游戏"
    LABEL_LINEAGE_CARD = "Lineage Classic"
    LABEL_LINEAGE_NAV = "Lineage"
    PURPLE_LABEL_FUZZY = 0.68
    R_LINEAGE_NAV = (0.193, 0.308)
    R_LINEAGE_CARD = (0.42, 0.38)

    def __init__(self, config_path: str):
        self.cfg = load_config(config_path)
        self.username = self.cfg.get("userID") or self.cfg.get("username") or ""
        self.password = self.cfg.get("password", "")
        self.game_path = self.cfg.get("game_path", "")
        ocr_hint = self.cfg.get("ocr_lang") or self.cfg.get("language") or "ko"
        if ocr_hint not in WINOCR_TAGS:
            ocr_hint = "ko"
        ocr_tag = WINOCR_TAGS.get(ocr_hint, "ko")
        self.lang = self.cfg.get("language") if self.cfg.get("language") in LANGS else "ko"
        self.ocr = WinOcr(ocr_tag)
        self._winocr = {ocr_tag: self.ocr}
        try:
            from win.winocr import RapidOcr
            self.rapid_ocr = RapidOcr()
            log.info("RapidOCR available for game window text")
        except Exception as e:
            self.rapid_ocr = None
            log.warning("RapidOCR not available: %s", e)
        self.words_cfg = self.cfg.get("words", {}) or {}
        captcha_model = self.cfg.get("captcha_model", "")
        if not captcha_model or not os.path.exists(captcha_model):
            captcha_model = self.cfg.get("captcha_model", "")
        self.captcha = CaptchaSolver(captcha_model) if captcha_model and os.path.exists(captcha_model) else None
        self.phase = Phase.FIND_PURPLE
        self.purple: Optional[WinWindow] = None
        self.game: Optional[WinWindow] = None
        self.game_step = 0
        self.game_step_deadline = 0.0
        self._step0_retries = 0
        self.phase_start = time.time()
        self.click_map = self._load_click_map()
        self.last_capture_path = None
        self.debug_dir = self.cfg.get("debug_dir", os.path.dirname(os.path.abspath(__file__)))
        self.dry_run = False
        self.learn = False
        self.session_backup_dir = self.cfg.get("session_backup_dir") or self.debug_dir
        self.game_steps = self._build_game_steps()
        self._login_method_attempts = 0
        # Email is entered at most once per login-form instance; reset whenever
        # a fresh login form (or re-targeted window) is detected so a genuine
        # new form gets a fresh single input.
        self._email_entered = False
        self._password_entered = False
        self._purple_logged_in = False
        self._last_id_field_xy = None
        self._last_address_xy = None
        self._next_retries = 0
        self.character_number = int(self.cfg.get("character_number", 1) or 1)
        self._lineage_card_tpl = None  # lazy BGR template; False if missing
        self._purple_watch = None  # lazy PurpleWatcher (screen + fingerprint)
        # Graceful shutdown flag
        self._shutdown_requested = False
        # Restore a good deviceTag before login so machine-registration (SMS)
        # does not re-trigger. Non-destructive: skipped if live value already set.
        restore_device_tag(self.session_backup_dir)
        # Interception driver (device-level unflagged input). Primary mouse
        # method for all clicks; Win32/SendInput is kept as the fallback.
        self._interception_ready = False
        self._use_interception = False
        try:
            if interception.init():
                self._interception_ready = True
                self._use_interception = True
                log.info("Interception driver ready; using as primary mouse input")
        except Exception:
            log.warning("Interception unavailable; falling back to SendInput")

        from positions import PositionStore
        raw_mode = (self.cfg.get("click_mode") or "dynamic")
        pos_path = self.cfg.get("position_dict") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "position_dict.json")
        self.positions = PositionStore(pos_path, raw_mode, cfg=self.cfg)
        # Fixed→dynamic fallback watch (purple_fixed_timeout_sec)
        self._purple_fixed_watch_at = 0.0
        self._purple_fixed_progress = None
        self._purple_fixed_fallback_done = False

    def request_shutdown(self):
        """Request graceful shutdown of the bot."""
        log.info("Shutdown requested, will stop after current tick")
        self._shutdown_requested = True

    def _cleanup(self):
        """Cleanup resources on shutdown."""
        log.info("Cleaning up resources...")
        # Kill any running heavy OCR process
        if hasattr(self, '_heavy_ocr_proc') and self._heavy_ocr_proc is not None:
            try:
                self._heavy_ocr_proc.kill()
            except Exception:
                pass
            self._heavy_ocr_proc = None
        flow = getattr(self, "flow", None)
        if flow is not None:
            try:
                flow.release()
            except Exception:
                pass
        # Release game window topmost if set
        if self.game and self.game.valid:
            try:
                self._release_game_topmost()
            except Exception:
                pass
        try:
            from win import interception
            interception.shutdown()
        except Exception:
            pass
        # Backup device tag on clean shutdown
        try:
            backup_device_tag(self.session_backup_dir)
        except Exception:
            pass

    def _build_game_steps(self) -> dict:
        """Merge config word-list overrides into the default game steps."""
        steps = {}
        for idx, spec in DEFAULT_GAME_STEPS.items():
            s = dict(spec)
            words = self.words_cfg.get(f"game_step_{idx}", None)
            if isinstance(words, list) and words:
                s["words"] = list(dict.fromkeys(list(s.get("words") or []) + words))
            excl = self.words_cfg.get(f"game_step_{idx}_exclude", None)
            if isinstance(excl, list) and excl:
                s["exclude"] = list(dict.fromkeys(list(s.get("exclude") or []) + excl))
            steps[idx] = s
        # Renamed keys: server_page -> step 1, server_name -> step 2.
        page = self.words_cfg.get("server_page", None)
        if isinstance(page, list) and page:
            steps.setdefault(1, {"click": "center", "label": page[0], "words": page})
            steps[1]["words"] = page
        name = self.words_cfg.get("server_name", None)
        if isinstance(name, list) and name:
            steps[2]["words"] = name
            steps[2]["label"] = name[0]
            steps[2]["click"] = "top"
        return steps

    # ---- helpers ------------------------------------------------------
    def _load_click_map(self) -> dict:
        p = self.cfg.get("click_map")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"failed to load click map: {e}")
        return {}

    def _set_phase(self, phase: Phase):
        self.phase = phase
        self.phase_start = time.time()
        if phase == Phase.ENTER_CREDENTIALS:
            self._cred_step = 0
            self._cred_step_deadline = time.time()

    def _mark_purple_logged_in(self):
        self._purple_logged_in = True
        self._normalize_purple_shell_size(reason="logged_in")

    def _purple_shell_target_size(self) -> tuple:
        """Familiar main-shell size used for OCR/ratio consistency."""
        w = int(self.cfg.get("purple_shell_width") or PURPLE_REF_W)
        h = int(self.cfg.get("purple_shell_height") or PURPLE_REF_H)
        return max(900, w), max(600, h)

    def _normalize_purple_shell_size(self, reason: str = "") -> bool:
        """Resize Purple to the familiar fixed shell whenever it is open.

        Skips tiny popups (<700 wide). Requires elevation for reliable
        SetWindowPos against elevated Purple (UIPI). Config:
          purple_force_size (default True), purple_shell_width/height.
        """
        if not bool(self.cfg.get("purple_force_size", True)):
            return False
        if not self.purple or not getattr(self.purple, "valid", False):
            return False
        hwnd = self.purple.hwnd
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.15)
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                time.sleep(0.1)
        except Exception:
            pass
        r = self.purple.rect
        # Tiny phone/QR / splash shells — do not blow them up
        if r.width < 700 or r.height < 500:
            return False
        tw, th = self._purple_shell_target_size()
        tol = int(self.cfg.get("purple_shell_size_tol", 24))
        if abs(r.width - tw) <= tol and abs(r.height - th) <= tol:
            return True
        # Keep top-left on-screen; clamp if off primary work area
        left, top = r.left, r.top
        try:
            # SPI_GETWORKAREA = 48
            wa = wt.RECT()
            user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
            if left + tw > wa.right:
                left = max(wa.left, wa.right - tw)
            if top + th > wa.bottom:
                top = max(wa.top, wa.bottom - th)
            left = max(wa.left, left)
            top = max(wa.top, top)
        except Exception:
            pass
        ok = False
        try:
            ok = bool(self.purple.resize(tw, th, left=left, top=top))
        except Exception as e:
            log.warning("Purple resize error: %r", e)
        r2 = self.purple.rect
        matched = abs(r2.width - tw) <= tol and abs(r2.height - th) <= tol
        if matched:
            log.info("Purple shell normalized %dx%d -> %dx%d (%s)",
                     r.width, r.height, r2.width, r2.height, reason or "ok")
            return True
        log.warning("Purple shell resize incomplete %dx%d (want %dx%d, %s) "
                    "— run elevated if UIPI blocks SetWindowPos",
                    r2.width, r2.height, tw, th, reason or "?")
        return False

    def _game_shell_target_size(self) -> tuple:
        """Familiar LC dialog size (agree / server / char) after splash."""
        w = int(self.cfg.get("game_shell_width") or GAME_REF_W)
        h = int(self.cfg.get("game_shell_height") or GAME_REF_H)
        return max(640, w), max(480, h)

    def _normalize_game_shell_size(self, reason: str = "") -> bool:
        """Force LC.exe to the familiar dialog size (default 816x639).

        Call after 보안설정 / splash — login UI ratios and server table
        geometry were measured on this size. Needs elevation vs elevated LC
        (UIPI). GLFW may fight the size; we verify after SetWindowPos.
        Config: game_force_size (default True), game_shell_width/height.

        Live failure: LC often self-maximizes (1296x999 -> 1936x1056 at
        -8,-8). Must SW_RESTORE before resize or SetWindowPos is ignored.
        """
        if not bool(self.cfg.get("game_force_size", True)):
            return False
        if not self.game or not getattr(self.game, "valid", False):
            return False
        hwnd = self.game.hwnd
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.15)
            # Maximized / Aero-snap: restore first or resize is a no-op.
            zoomed = False
            try:
                zoomed = bool(user32.IsZoomed(hwnd))
            except Exception:
                zoomed = False
            r0 = self.game.rect
            blown = (
                zoomed
                or r0.width >= 1600 or r0.height >= 900
                or r0.left < -4 or r0.top < -4
            )
            if blown:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.15)
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                time.sleep(0.1)
        except Exception:
            pass
        r = self.game.rect
        if r.width < 400 or r.height < 300:
            return False
        tw, th = self._game_shell_target_size()
        tol = int(self.cfg.get("game_shell_size_tol", 16))
        if abs(r.width - tw) <= tol and abs(r.height - th) <= tol:
            # Still push off negative snap origin if needed
            if r.left >= 0 and r.top >= 0:
                return True
        left, top = max(0, r.left), max(0, r.top)
        try:
            wa = wt.RECT()
            user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
            # Prefer a stable on-screen origin — never leave at -8,-8.
            if left < wa.left or top < wa.top or left + tw > wa.right or top + th > wa.bottom:
                left = max(wa.left, min(left, wa.right - tw))
                top = max(wa.top, min(top, wa.bottom - th))
            left = max(wa.left, left)
            top = max(wa.top, top)
        except Exception:
            left, top = max(0, left), max(0, top)
        matched = False
        for attempt in range(3):
            try:
                user32.ShowWindow(hwnd, 9)
            except Exception:
                pass
            try:
                self.game.resize(tw, th, left=left, top=top)
            except Exception as e:
                log.warning("game resize error: %r", e)
                return False
            time.sleep(0.08 + 0.05 * attempt)
            r2 = self.game.rect
            matched = (
                abs(r2.width - tw) <= tol and abs(r2.height - th) <= tol
                and r2.left >= -2 and r2.top >= -2
            )
            if matched:
                log.info("game shell normalized %dx%d@(%d,%d) -> %dx%d@(%d,%d) (%s)",
                         r.width, r.height, r.left, r.top,
                         r2.width, r2.height, r2.left, r2.top,
                         reason or "ok")
                return True
        r2 = self.game.rect
        log.warning("game shell resize incomplete %dx%d@(%d,%d) (want %dx%d, %s) "
                    "— elevated bot required; GLFW may also reject size",
                    r2.width, r2.height, r2.left, r2.top, tw, th, reason or "?")
        return False

    def _purple_fixed_progress_key(self) -> tuple:
        """Coarse progress fingerprint while driving Purple in fixed mode."""
        phase = getattr(self.phase, "name", str(getattr(self, "phase", "")))
        watch = getattr(self, "_purple_watch", None)
        cached = watch.cached() if watch is not None else None
        screen = getattr(getattr(cached, "screen", None), "value", "") or ""
        return (
            phase,
            screen,
            bool(getattr(self, "_email_entered", False)),
            bool(getattr(self, "_password_entered", False)),
            bool(getattr(self, "_purple_logged_in", False)),
            int(getattr(self, "_lineage_nav_clicked", 0) or 0),
            bool(getattr(self, "_lineage_card_clicked", False)),
            bool(getattr(self, "_game", None) and getattr(self.game, "valid", False)),
        )

    def _purple_fixed_timeout_sec(self) -> float:
        return float(self.cfg.get("purple_fixed_timeout_sec", 35.0) or 35.0)

    def _arm_purple_fixed_watch(self):
        """Start / refresh the fixed-stall timer when using fixed Purple clicks."""
        store = getattr(self, "positions", None)
        if not store or not store.is_fixed_purple:
            return
        if getattr(self, "_purple_fixed_fallback_done", False):
            return
        now = time.time()
        prog = self._purple_fixed_progress_key()
        prev = getattr(self, "_purple_fixed_progress", None)
        armed = float(getattr(self, "_purple_fixed_watch_at", 0.0) or 0.0)
        if armed <= 0.0 or prog != prev:
            self._purple_fixed_watch_at = now
            self._purple_fixed_progress = prog

    def _purple_fixed_stalled(self) -> bool:
        """True when fixed mode has made no progress for the timeout window."""
        store = getattr(self, "positions", None)
        if not store or not store.is_fixed_purple:
            return False
        if getattr(self, "_purple_fixed_fallback_done", False):
            return False
        armed = float(getattr(self, "_purple_fixed_watch_at", 0.0) or 0.0)
        if armed <= 0.0:
            self._arm_purple_fixed_watch()
            return False
        prog = self._purple_fixed_progress_key()
        if prog != getattr(self, "_purple_fixed_progress", None):
            self._arm_purple_fixed_watch()
            return False
        return (time.time() - armed) >= self._purple_fixed_timeout_sec()

    def _fallback_purple_to_dynamic(self, reason: str = "") -> bool:
        """Exception path: abandon fixed Purple clicks and use OCR/dynamic."""
        store = getattr(self, "positions", None)
        if store is None:
            return False
        if getattr(self, "_purple_fixed_fallback_done", False):
            return True
        from positions import MODE_DYNAMIC
        prev = store.purple_mode
        store.purple_mode = MODE_DYNAMIC
        self._purple_fixed_fallback_done = True
        self._purple_fixed_watch_at = 0.0
        log.warning(
            "Purple click fallback: %s -> dynamic after %.0fs stall (%s)",
            prev, self._purple_fixed_timeout_sec(), reason or "no progress")
        return True

    def _maybe_fallback_purple_dynamic(self, reason: str = "") -> bool:
        """If fixed clicks stall, switch to dynamic once per session."""
        self._arm_purple_fixed_watch()
        if not self._purple_fixed_stalled():
            return False
        return self._fallback_purple_to_dynamic(reason=reason or "stall")

    def _purple_gate_clicks(self) -> bool:
        """True: only click after the Purple screen is positively classified."""
        return bool(self.cfg.get("purple_gate_clicks", True))

    def _purple_watcher(self):
        w = getattr(self, "_purple_watch", None)
        if w is None:
            from purple_state import PurpleWatcher
            w = PurpleWatcher(self)
            self._purple_watch = w
        return w

    def _read_purple_view(self, force: bool = False, img=None, blob: str = None):
        """Classify the live Purple window. Cached briefly; OCR only on change."""
        from purple_state import (PurpleView, PurpleScreen, classify_blob,
                                  fingerprint_pil, fingerprint_changed)
        w = self._purple_watcher()
        now = time.time()
        if (not force and img is None and blob is None and w.cached() is not None
                and (now - w._at) < w.ttl):
            return w.cached()
        view = PurpleView()
        if self.purple and getattr(self.purple, "valid", False):
            r = self.purple.rect
            view.width, view.height = r.width, r.height
        cap = img
        if cap is None and blob is None and self.purple and self.purple.valid:
            try:
                cap = self.purple.capture_content()
            except Exception:
                cap = None
        if cap is not None:
            view.fingerprint = fingerprint_pil(cap)
            prev = w.cached()
            if (not force and blob is None and prev is not None
                    and prev.screen != PurpleScreen.UNKNOWN
                    and not fingerprint_changed(prev.fingerprint, view.fingerprint)):
                prev.fingerprint = view.fingerprint
                w._at = now
                return prev
        raw = blob
        if raw is None and cap is not None:
            try:
                lines = self._ocr_lines(cap)
                raw = " | ".join(ln.text for ln in (lines or [])[:48])
            except Exception:
                raw = ""
        view.blob = raw or ""
        view.screen = classify_blob(view.blob)
        # Template can promote UNKNOWN / confirm launcher vs login
        if cap is not None and view.screen in (
                PurpleScreen.UNKNOWN, PurpleScreen.LAUNCHER):
            try:
                bgr = self._purple_capture_bgr()
                hit = w.match_screen_template(bgr) if bgr is not None else None
            except Exception:
                hit = None
            if hit:
                screen, tm = hit
                view.screen = screen
                view.template_score = tm.score
                view.template_name = tm.name
                log.info("Purple screen via template %s score=%.3f",
                         screen.value, tm.score)
        w._view = view
        w._at = now
        prev_screen = getattr(getattr(w, "_logged_screen", None), "value", None)
        if prev_screen != view.screen.value:
            log.info("Purple screen=%s w=%s h=%s",
                     view.screen.value, view.width, view.height)
            w._logged_screen = view.screen
        return view

    def _wait_purple_change(self, before_fp: bytes, timeout: float = 3.5) -> bool:
        from purple_state import fingerprint_pil, fingerprint_changed
        if not before_fp:
            time.sleep(min(0.4, timeout))
            self._purple_watcher().invalidate()
            return False
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not self.purple or not self.purple.valid:
                break
            try:
                img = self.purple.capture_content()
            except Exception:
                img = None
            fp = fingerprint_pil(img)
            if fingerprint_changed(before_fp, fp):
                self._purple_watcher().invalidate()
                log.info("Purple view changed (fingerprint)")
                return True
            time.sleep(0.15)
        log.info("Purple view unchanged after %.1fs", timeout)
        return False

    def _wait_purple_screens(self, screens, timeout: float = 6.0,
                             interval: float = 0.22):
        wanted = tuple(screens)
        t0 = time.time()
        view = self._read_purple_view(force=True)
        while time.time() - t0 < timeout:
            if view.screen in wanted:
                return view
            time.sleep(interval)
            view = self._read_purple_view(force=True)
        return view

    def _gated_purple_click(self, key: str, expected=None, cef: bool = False,
                            allow_fixed: bool = True) -> bool:
        """Click a Purple control only when the current screen matches.

        Locate order: template → (caller OCR already ran) → saved ratio.
        """
        from purple_state import expected_screens_for
        expected = expected or expected_screens_for(key)
        view = self._read_purple_view()
        if view.screen not in expected:
            log.info("gated skip %s: screen=%s want=%s",
                     key, view.screen.value,
                     tuple(s.value for s in expected))
            return False
        fp_before = view.fingerprint
        bgr = self._purple_capture_bgr()
        hit = self._purple_watcher().match_control(key, bgr)
        if hit:
            log.info("%s located by template score=%.3f at (%d,%d)",
                     key, hit.score, hit.cx, hit.cy)
            if self.dry_run:
                return True
            if cef:
                self._click_xy_cef(hit.cx, hit.cy, key, use_saved=False)
            else:
                InputRouter.click_client(self.purple, hit.cx, hit.cy)
                self._record_click("purple", key, self.purple, hit.cx, hit.cy)
            self._purple_watcher().invalidate()
            if key not in ("purple_address", "purple_id_field", "purple_password"):
                self._wait_purple_change(fp_before, timeout=2.8)
            return True
        if allow_fixed:
            if key == "purple_address" and self._address_collides_with_next():
                log.info("gated skip fixed purple_address: overlaps Next")
                return False
            if self._try_fixed_click("purple", key, self.purple, cef=cef):
                self._purple_watcher().invalidate()
                if key not in ("purple_address", "purple_id_field", "purple_password"):
                    changed = self._wait_purple_change(fp_before, timeout=2.8)
                    if not changed:
                        log.warning("gated fixed %s: no screen change — likely miss",
                                    key)
                return True
        return False

    def _purple_saved_xy(self, key: str):
        store = getattr(self, "positions", None)
        if not store or not self.purple:
            return None
        return store.client_xy("purple", key, self.purple)

    def _address_collides_with_next(self, max_px: int = 28) -> bool:
        """True when saved Address tab sits on the Next button.

        Live dict recorded purple_address ≈ purple_next (820,388 vs 822,388).
        Clicking Address first therefore submits Next with an empty ID.
        """
        a = self._purple_saved_xy("purple_address")
        n = self._purple_saved_xy("purple_next")
        if not a or not n:
            return False
        return abs(a[0] - n[0]) <= max_px and abs(a[1] - n[1]) <= max_px

    def _login_template_dir(self) -> str:
        from purple_state import DEFAULT_TEMPLATE_DIR
        custom = (self.cfg.get("purple_template_dir") or "").strip()
        if custom:
            if not os.path.isabs(custom):
                custom = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      custom)
            return custom
        return DEFAULT_TEMPLATE_DIR

    def _ensure_login_email_templates(self, force: bool = False) -> bool:
        """Ensure Next (and optional Address) PNGs exist for post-ID clicks.

        The first-click seed is username_email.png (用户名/电子邮箱). Harvest
        only fills missing Next/Address crops; it never replaces that seed.
        """
        from purple_state import harvest_login_email_templates
        directory = self._login_template_dir()
        seed = os.path.join(directory, "username_email.png")
        next_png = os.path.join(directory, "next.png")
        if os.path.isfile(seed) and os.path.isfile(next_png) and not force:
            self._purple_watcher().templates.reload()
            return True
        if os.path.isfile(seed) and not force and not os.path.isfile(next_png):
            force = True
        bgr = self._purple_capture_bgr()
        written = harvest_login_email_templates(bgr, directory)
        if not written or "next" not in written:
            extra = self._harvest_login_templates_via_blue_button(directory)
            written = dict(written or {})
            written.update(extra or {})
        if not os.path.isfile(seed) and not written:
            log.warning("login template harvest failed")
            return False
        if not os.path.isfile(seed) and not (
                os.path.isfile(os.path.join(directory, "id_field.png"))
                or written.get("id_field")):
            log.warning("login template harvest failed (no id field)")
            return False
        self._purple_watcher().templates.reload()
        return True

    def _harvest_login_templates_via_blue_button(self, directory: str) -> dict:
        """Fallback crop using the existing RGB blue-button locator."""
        cap = getattr(self.purple, "capture_content", None)
        img = cap() if callable(cap) else None
        if img is None:
            return {}
        btn = self._locate_blue_button(img, pick="highest")
        if btn is None:
            btn = self._locate_blue_button(img, pick="lowest")
        if btn is None:
            return {}
        try:
            import cv2
            import numpy as np
        except ImportError:
            return {}
        arr = np.array(img.convert("RGB"))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        cx, cy, top, bot, width = btn
        os.makedirs(directory, exist_ok=True)
        written = {}

        def _save(stem, x0, y0, x1, y1):
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            if x1 - x0 < 20 or y1 - y0 < 12:
                return
            path = os.path.join(directory, stem + ".png")
            cv2.imwrite(path, bgr[y0:y1, x0:x1])
            written[stem] = path
            log.info("blue-button harvest %s (%d,%d)-(%d,%d)", stem, x0, y0, x1, y1)

        _save("next", cx - width // 2 - 6, top - 4, cx + width // 2 + 6, bot + 4)
        _save("next_btn", cx - width // 2 - 6, top - 4, cx + width // 2 + 6, bot + 4)
        if not os.path.isfile(os.path.join(directory, "username_email.png")):
            fhgt = max(28, bot - top + 8)
            fy1 = top - 8
            fy0 = fy1 - fhgt
            fx0 = cx - width // 2 - 10
            fx1 = cx + width // 2 + 10
            _save("id_field", fx0, fy0, fx1, fy1)
            _save("email_field", fx0, fy0, fx1, fy1)
            thgt = max(22, fhgt - 8)
            ty1 = fy0 - 6
            ty0 = ty1 - thgt
            tx0 = fx0
            tx1 = fx0 + max(90, int((fx1 - fx0) * 0.62))
            _save("address_tab", tx0, ty0, tx1, ty1)
            _save("email_tab", tx0, ty0, tx1, ty1)
        return written

    def _match_login_control(self, key: str):
        bgr = self._purple_capture_bgr()
        if bgr is None:
            return None
        return self._purple_watcher().match_control(key, bgr)

    def _template_click_login(self, key: str, cef: bool = True) -> bool:
        """First-step locate: template match only. No OCR, no saved ratios.

        Does not require the OCR classifier to say login_email — WinOCR
        often misses Address / ID or E-mail, which is why this step exists.
        """
        hit = self._match_login_control(key)
        if not hit:
            log.info("%s template miss — re-harvest from live window", key)
            if self._ensure_login_email_templates(force=True):
                hit = self._match_login_control(key)
        if not hit:
            log.warning("%s not located by template", key)
            return False
        log.info("%s located by template score=%.3f at (%d,%d)",
                 key, hit.score, hit.cx, hit.cy)
        if self.dry_run:
            return True
        if cef:
            self._click_xy_cef(hit.cx, hit.cy, key, use_saved=False)
        else:
            InputRouter.click_client(self.purple, hit.cx, hit.cy)
            self._record_click("purple", key, self.purple, hit.cx, hit.cy)
        self._purple_watcher().invalidate()
        return True

    def _maybe_click_email_tab(self) -> bool:
        """Click the email/Address tab via template match only."""
        if self._template_click_login("purple_address", cef=True):
            time.sleep(0.2)
            return True
        log.info("Address tab template miss — continue to email field")
        return False

    def _click_email_next(self) -> bool:
        """Click Next via template match of the blue button crop."""
        if self._template_click_login("purple_next", cef=True):
            log.info("Next clicked (template)")
            return True
        log.warning("Next template miss")
        return False

    def _email_ready_for_next(self) -> bool:
        """True when the ID field looks filled enough to press Next.

        Dry-run and a missing capture keep the old path (do not block).
        A visible placeholder with no username on screen means the paste
        missed the field — do not submit empty.
        """
        if self.dry_run:
            return True
        text = (getattr(self, "username", None) or "").strip()
        if not text:
            return False
        cap = getattr(self.purple, "capture_content", None) if self.purple else None
        img = cap() if callable(cap) else None
        if img is None:
            return True
        local = text.split("@")[0]
        try:
            if self._field_contains(img, text):
                return True
            if len(local) >= 3 and self._field_contains(img, local):
                return True
            lines = self._login_lines(img)
        except Exception:
            return True
        if any(self._is_id_or_email_placeholder(ln.text) for ln in lines):
            log.warning("email field still empty (placeholder on form)")
            return False
        return True

    def _enter_email_then_next(self) -> None:
        """Resize → click 用户名/电子邮箱 → paste → Next. Then password as now."""
        from purple_state import PurpleScreen, LAUNCHER_SCREENS
        self._normalize_purple_shell_size(reason="email_step")
        view = self._read_purple_view(force=True)
        past = (PurpleScreen.LOGIN_PASSWORD, PurpleScreen.LOGGING_IN) + LAUNCHER_SCREENS
        if view.screen in past:
            log.info("skip email step: already %s", view.screen.value)
            return
        # Seeded username_email.png is enough for the first click; harvest
        # Next (and optional Address) only if those PNGs are missing.
        directory = self._login_template_dir()
        if not os.path.isfile(os.path.join(directory, "username_email.png")):
            if not self._ensure_login_email_templates(force=True):
                log.warning("cannot harvest login templates — no click")
                return
        else:
            self._purple_watcher().templates.reload()
            if not os.path.isfile(os.path.join(directory, "next.png")):
                self._ensure_login_email_templates(force=True)

        # Same order as password: focus the field, then type, then proceed.
        focused = self._template_click_login("purple_id_field", cef=True)
        if not focused:
            log.warning("用户名/电子邮箱 template miss; not pasting or clicking Next")
            return
        time.sleep(0.25)
        pasted = self._paste_once(self.username, "email")
        time.sleep(0.35)
        if not pasted:
            self._email_entered = False
            log.warning("email not pasted — not clicking Next")
            return
        if not self._email_ready_for_next():
            self._email_entered = False
            log.warning("email field empty after paste — not clicking Next")
            return
        if not self._click_email_next():
            log.warning("Next miss — trying combined email+password form")
            self._enter_combined_login()
            return
        log.info("userID pasted, Next clicked via template — waiting password")
        nxt = self._wait_purple_screens(
            (PurpleScreen.LOGIN_PASSWORD, PurpleScreen.LOGGING_IN)
            + LAUNCHER_SCREENS,
            timeout=6.0)
        if nxt.screen == PurpleScreen.LOGIN_EMAIL:
            log.warning("still LOGIN_EMAIL after Next — will retry")
            self._email_entered = False

    def _retry_email_before_next(self, why: str) -> None:
        """Re-focus and re-paste the email instead of clicking empty Next."""
        if self._next_retries >= 3:
            log.info("password label not on screen yet; not clicking Login")
            return
        self._next_retries += 1
        log.info("%s; re-enter email %s/3", why, self._next_retries)
        self._email_entered = False
        self._enter_email_then_next()

    def _reset_lineage_launch_state(self):
        """Allow Start Game to be clicked again after a game-only relaunch."""
        self._lineage_nav_clicked = 0
        self._lineage_card_clicked = False
        self._lineage_card_attempts = 0
        self._lineage_nav_at = 0.0
        self._launch_failed = 0
        self._last_launch_view = None
        self._game_proc_seen = False
        self._game_proc_logged = False

    def _ensure_purple_visible(self) -> bool:
        """Make the Purple main shell visible and focusable before clicks.

        Elevated Purple ignores ShowWindow from a medium-integrity bot (UIPI).
        Fall back to Interception Alt+Tab cycling, then a best-effort
        ShellExecute of Purple.exe (may show UAC — only when already elevated
        or the user has auto-approve).
        """
        if not self.purple or not getattr(self.purple, "valid", False):
            if not self._try_attach_running_purple():
                return False
        hwnd = self.purple.hwnd
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            self._normalize_purple_shell_size(reason="ensure_visible")
            return True

        # Layer 1: Win32 (works when bot is elevated / same integrity)
        for cmd in (9, 5):  # SW_RESTORE, SW_SHOW
            try:
                user32.ShowWindow(hwnd, cmd)
            except Exception:
                pass
        time.sleep(0.35)
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            try:
                self.purple.activate()
            except Exception:
                pass
            log.info("Purple restored via ShowWindow hwnd=%s", hwnd)
            self._normalize_purple_shell_size(reason="showwindow")
            return True

        # Layer 2: device-level Alt+Tab (surfaces Purple without UIPI)
        if getattr(self, "_interception_ready", False):
            try:
                for _ in range(6):
                    interception.key_down(0x12)  # Alt
                    interception.tap(0x09)       # Tab
                    interception.key_up(0x12)
                    time.sleep(0.45)
                    if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                        log.info("Purple restored via Alt+Tab hwnd=%s", hwnd)
                        self._normalize_purple_shell_size(reason="alt_tab")
                        return True
                    # hwnd may have changed after restore — reattach
                    if self._try_attach_running_purple():
                        hwnd = self.purple.hwnd
                        if user32.IsWindowVisible(hwnd):
                            log.info("Purple reattached visible hwnd=%s", hwnd)
                            self._normalize_purple_shell_size(reason="alt_tab_reattach")
                            return True
            except Exception as e:
                log.warning("Alt+Tab Purple restore failed: %r", e)

        # Layer 3: re-invoke Purple.exe only when already elevated (avoids
        # hanging the agent on an unattended UAC prompt).
        try:
            elevated = bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
        except Exception:
            elevated = False
        gp = getattr(self, "game_path", "") or ""
        if elevated and gp and os.path.isfile(gp):
            try:
                log.info("Purple not visible; re-invoking Purple.exe (elevated)")
                os.startfile(gp)
                time.sleep(2.0)
                if self._try_attach_running_purple():
                    if user32.IsWindowVisible(self.purple.hwnd):
                        self._normalize_purple_shell_size(reason="reinvoke")
                        return True
            except Exception as e:
                log.warning("Purple startfile restore failed: %r", e)

        log.warning("Purple still not visible hwnd=%s (UIPI?). "
                    "Run the bot as Administrator and restore Purple.",
                    hwnd)
        return False

    def _reuse_logged_in_purple(self) -> bool:
        """Find or restore an already-running Purple main shell."""
        if hasattr(self, "_restore_hidden_purple") and self._restore_hidden_purple():
            if self.purple and self.purple.valid and self.purple.rect.width >= 900:
                return True
        if self._find_purple_window():
            if self.purple.rect.width >= 900:
                if not user32.IsWindowVisible(self.purple.hwnd):
                    user32.ShowWindow(self.purple.hwnd, 9)  # SW_RESTORE
                    time.sleep(0.4)
                try:
                    self.purple.activate()
                except Exception:
                    pass
                return True
        if self.find_main_launcher():
            if self.purple.rect.width >= 900:
                if not user32.IsWindowVisible(self.purple.hwnd):
                    user32.ShowWindow(self.purple.hwnd, 9)  # SW_RESTORE
                    time.sleep(0.4)
                try:
                    self.purple.activate()
                except Exception:
                    pass
                return True
        return False

    def _attach_existing_purple(self) -> bool:
        """Prefer a running Purple window over launching a new client."""
        return self._reuse_logged_in_purple()

    def _cfg_words(self, key: str, default: list) -> list:
        """Multilingual defaults UNION config overrides (ko/en/zh-TW/zh-CN)."""
        extra = list(self.words_cfg.get(key) or [])
        built_in = list(MULTI_UI_WORDS.get(key) or [])
        out = []
        for w in list(default) + built_in + extra:
            if w and w not in out:
                out.append(w)
        return out

    def _username_email_keywords(self) -> list:
        return self._cfg_words("id_field", list(USERNAME_EMAIL_KEYWORDS)
                               + list(self._ID_EMAIL_LABELS))

    def _run_game_keywords(self) -> list:
        return self._cfg_words("start_game",
                               [self.LABEL_RUN_GAME, "Start Game", "Start",
                                "PLAY", "Play"] + list(RUN_GAME_KEYWORDS))

    def _lineage_card_keywords(self) -> list:
        return self._cfg_words("lineage_card",
                               [self.LABEL_LINEAGE_CARD, "Lineage classic",
                                "Lineage", "天堂经典", "天堂經典"]
                               + list(LINEAGE_CARD_KEYWORDS))

    def _lineage_nav_keywords(self) -> list:
        return self._cfg_words("lineage_nav",
                               [self.LABEL_LINEAGE_NAV, "Lineage Classic",
                                "Classic", "리니지 클래식", "天堂经典"]
                               + list(MULTI_UI_WORDS.get("lineage_nav", [])))

    def _is_left_nav_rect(self, x: int, y: int, w: int, h: int) -> bool:
        """True when OCR box is in the Purple left sidebar (Lineage nav area)."""
        if not self.purple or not self.purple.valid:
            return False
        r = self.purple.client_rect
        cx = x + max(w, 1) // 2
        return (cx <= int(r.width * 0.30) and 60 <= y <= int(r.height * 0.80))

    def _click_left_lineage_nav(self, label: str = "") -> bool:
        """Click left-sidebar Lineage: fixed (when shell pinned) → ratio."""
        label = label or self.LABEL_LINEAGE_NAV
        store = getattr(self, "positions", None)
        if store and store.is_fixed_purple:
            if self._try_fixed_click("purple", "purple_lineage", self.purple):
                return True
        if self.click_ratio("lineage_nav", self.R_LINEAGE_NAV):
            return True
        return False

    def _text_matches_lineage_card(self, text: str) -> bool:
        if fuzzy_match_label(text, self._lineage_card_keywords(),
                             fuzzy=self.PURPLE_LABEL_FUZZY):
            return True
        t = normalize(text)
        al = self._alnum(text)
        if "lineage" in al and "classic" in al:
            return True
        if "天堂" in t and ("经典" in t or "經典" in t):
            return True
        return False

    def _run_game_visible(self) -> bool:
        if not self.purple or not self.purple.valid:
            return False
        img = self.purple.capture_content()
        if img is None:
            return False
        blob = " ".join(ln.text for ln in self._ocr_lines(img))
        if self._text_matches_run_game(blob):
            return True
        return bool(self.find_lines(self.purple, self._run_game_keywords(),
                                    fuzzy=self.PURPLE_LABEL_FUZZY))

    def _text_matches_username_email(self, text: str) -> bool:
        if fuzzy_match_label(text, self._username_email_keywords(),
                             fuzzy=self.PURPLE_LABEL_FUZZY):
            return True
        al = self._alnum(text)
        t = normalize(text)
        if "address" in al or "adress" in al:
            return True
        if ("email" in al or "e-mail" in t) and "id" in al:
            return True
        return False

    def _text_matches_run_game(self, text: str) -> bool:
        if fuzzy_match_label(text, self._run_game_keywords(),
                             fuzzy=self.PURPLE_LABEL_FUZZY):
            return True
        al = self._alnum(text)
        return any(k in al for k in ("startgame", "statgame", "stargame"))

    def _restart(self):
        """Game-only restart: reuse running Purple, then click Start Game."""
        self.game = None
        self.game_step = 0
        self.game_step_deadline = 0.0
        self._reset_lineage_launch_state()
        if self._try_attach_running_purple():
            self._mark_purple_logged_in()
            log.info("game relaunch: reusing running Purple (%dx%d)",
                     self.purple.rect.width, self.purple.rect.height)
            self._set_phase(Phase.FIND_LINEAGE)
            return
        if self._purple_process_running() or self._any_purple_window_exists():
            self._mark_purple_logged_in()
            log.info("game relaunch: Purple already running; restoring window "
                     "(will not launch a new Purple)")
            self.purple = None
            self._set_phase(Phase.FIND_LINEAGE)
            return
        if getattr(self, "_purple_logged_in", False):
            log.warning("Purple process gone; clearing session login flag")
            self._purple_logged_in = False
        self._set_phase(Phase.FIND_PURPLE)

    def _find_purple_window(self) -> bool:
        """Locate an existing Purple top-level window. Never starts a process."""
        main = WindowFinder.find_by_process(
            ["Purple.exe", "PurpleLauncher.exe"],
            min_width=900, min_height=500)
        if main is None:
            main = WindowFinder.find_by_process(
                ["Purple.exe", "PurpleLauncher.exe"],
                min_width=900, min_height=500, prefer_visible=False)
        if main is not None:
            self.purple = WinWindow(main)
            return True

        hwnd = WindowFinder.find_by_process(["Purple.exe", "PurpleLauncher.exe"],
                                            min_width=200, min_height=200)
        if hwnd is None:
            hwnd = WindowFinder.find_by_title("PURPLE", min_width=200, min_height=200)
            if hwnd is not None:
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                t = title.value.lower()
                skip_kw = ["notepad", "txt", ".json", "config", "login -"]
                if any(kw in t for kw in skip_kw):
                    hwnd = None
        if hwnd is not None:
            login_hwnd = WindowFinder.find_by_process_title(
                ["Purple.exe", "PurpleLauncher.exe"],
                ["log in", "email", "sign in", "登入", "登录", "이메일"],
                min_width=200, min_height=200,
                exclude_title_substrs=self._NON_EMAIL_LOGIN_TITLES)
            if login_hwnd is not None and login_hwnd != hwnd:
                hwnd = login_hwnd
            if self._is_login_form_window(hwnd):
                larger_form = self._find_larger_login_form(hwnd)
                if larger_form is not None:
                    hwnd = larger_form
            self.purple = WinWindow(hwnd)
            return True
        return False

    # ---- window discovery ---------------------------------------------
    def find_purple(self) -> bool:
        if self._try_attach_running_purple():
            return True
        if self._purple_process_running() or self._any_purple_window_exists():
            log.info("Purple already running; waiting for its window "
                     "(will not start a second one)")
            return False
        self.launch_purple()
        return False

    def _purple_process_running(self) -> bool:
        names = {"purple.exe", "purplelauncher.exe"}
        try:
            for p in psutil.process_iter(["name"]):
                if (p.info.get("name") or "").lower() in names:
                    return True
        except Exception:
            pass
        return False

    def _purple_pids(self) -> set:
        pids = set()
        for name in ("purple.exe", "purplelauncher.exe"):
            try:
                for p in psutil.process_iter(["name", "pid"]):
                    if (p.info.get("name") or "").lower() == name:
                        pids.add(p.info["pid"])
            except Exception:
                pass
        return pids

    def _any_purple_window_exists(self) -> bool:
        """True when any top-level window belongs to a Purple process."""
        pids = self._purple_pids()
        if not pids:
            return False
        for hwnd, _title, _cls, rc in WindowFinder._enum_top_level():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                continue
            w = max(0, rc.right - rc.left)
            h = max(0, rc.bottom - rc.top)
            if w >= 200 and h >= 150:
                return True
        return False

    def _restore_hidden_purple(self) -> bool:
        """Restore a hidden/minimized Purple main shell (title PURPLE, >=900px)."""
        pids = self._purple_pids()
        if not pids:
            return False
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(hwnd, lparam):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                n = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip() == "PURPLE":
                    rc = wt.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rc))
                    w = max(0, rc.right - rc.left)
                    h = max(0, rc.bottom - rc.top)
                    found.append((w * h, w, hwnd))
            return True

        user32.EnumWindows(cb, 0)
        wide = [(a, w, h) for a, w, h in found if w >= 900]
        pool = wide if wide else found
        pool.sort(key=lambda t: t[0], reverse=True)
        for _area, _w, hwnd in pool:
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                time.sleep(0.5)
                user32.ShowWindow(hwnd, 5)   # SW_SHOW
            if user32.IsWindowVisible(hwnd):
                self.purple = WinWindow(hwnd)
                try:
                    self.purple.activate()
                except Exception:
                    pass
                log.info("restored hidden Purple window hwnd=%s", hwnd)
                self._normalize_purple_shell_size(reason="restore_hidden")
                return True
        return False

    def _try_attach_running_purple(self) -> bool:
        """Search for a running Purple window before ever starting a new client."""
        if self._restore_hidden_purple():
            self._normalize_purple_shell_size(reason="attach_restore")
            return True
        if self._find_purple_window():
            if self.purple.rect.width >= 900:
                if not user32.IsWindowVisible(self.purple.hwnd):
                    user32.ShowWindow(self.purple.hwnd, 9)
                    time.sleep(0.4)
                try:
                    self.purple.activate()
                except Exception:
                    pass
                self._normalize_purple_shell_size(reason="attach_wide")
                return True
        if self.find_main_launcher():
            self._normalize_purple_shell_size(reason="attach_main")
            return True
        if self._reuse_logged_in_purple():
            self._normalize_purple_shell_size(reason="attach_reuse")
            return True
        return False

    def _goto_purple_phase(self):
        """Lost Purple handle — reattach to running client instead of relaunching."""
        if self._try_attach_running_purple():
            if getattr(self, "_purple_logged_in", False):
                log.info("reattached to running Purple -> game launch flow")
                self._set_phase(Phase.FIND_LINEAGE)
            return
        if self._purple_process_running() or self._any_purple_window_exists():
            log.info("Purple already running; waiting to reattach (not launching new)")
            return
        self._set_phase(Phase.FIND_PURPLE)

    def find_purple_login_form(self, previous_hwnd: int = None) -> bool:
        """Find the Purple login form window (email/password entry), optionally
        excluding a previously known window (e.g. the login-method selection screen).
        
        Note: The login form often loads in the SAME window (content changes in-place),
        so we also accept the previous window if its content has changed to the
        email/password entry form."""
        # First try to find a larger form (450x773) - a NEW window
        larger_form = self._find_larger_login_form(previous_hwnd or 0)
        if larger_form is not None:
            self.purple = WinWindow(larger_form)
            return True
        
        # Fallback: find any login form window, excluding the previous one
        hwnd = WindowFinder.find_by_process_title(
            ["Purple.exe", "PurpleLauncher.exe"], ["log in", "email", "sign in", "password"],
            min_width=300, min_height=400,
            exclude_title_substrs=self._NON_EMAIL_LOGIN_TITLES)
        if hwnd is not None and hwnd != previous_hwnd:
            self.purple = WinWindow(hwnd)
            return True
        
        # Last resort: any visible Purple window that's not the previous one
        hwnd = WindowFinder.find_by_process(["Purple.exe", "PurpleLauncher.exe"],
                                             min_width=300, min_height=400)
        if hwnd is not None and hwnd != previous_hwnd:
            self.purple = WinWindow(hwnd)
            return True
        
        # If we have a previous window, check if its content has changed to the
        # email/password form (same window, new content). Accept it.
        if previous_hwnd is not None:
            try:
                win = WinWindow(previous_hwnd)
                if win.valid and win.visible:
                    img = win.capture_content()
                    if img:
                        # Check if this window now shows the ID/password fields
                        lines = self._ocr_lines(img)
                        text = " ".join(ln.text for ln in lines).lower()
                        if any(kw in text for kw in ["用户名", "电子邮箱", "用户名/电子邮箱",
                                                     "id or e-mail", "id or email",
                                                     "id/e-mail", "ld/e-mail",
                                                     "email", "e-mail", "email address",
                                                     "password", "비밀번호", "이메일",
                                                     "next", "다음", "密码"]):
                            log.info("Login form detected in same window (content changed)")
                            self.purple = win
                            return True
            except Exception:
                pass
        return False

    def _is_login_form_window(self, hwnd: int) -> bool:
        """Check if a window is a login form (small window with 'log in'/'email' in title)."""
        if not hwnd:
            return False
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        title_lower = title.value.lower()
        if any(e in title_lower for e in self._NON_EMAIL_LOGIN_TITLES):
            return False
        return any(kw in title_lower for kw in ["log in", "email", "sign in"])

    def _find_larger_login_form(self, current_hwnd: int) -> Optional[int]:
        """Find a larger login form window (e.g. 450x773 email/password entry form)."""
        best = None
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                continue
            if pname not in ("purple.exe", "purplelauncher.exe"):
                continue
            if hwnd == current_hwnd:
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            if w < 400 or h < 700:  # Look for the larger form (~450x773)
                continue
            title_lower = title.lower()
            if any(e in title_lower for e in self._NON_EMAIL_LOGIN_TITLES):
                continue
            if any(kw in title_lower for kw in ["log in", "email", "sign in"]):
                if user32.IsWindowVisible(hwnd):
                    area = w * h
                    if best is None or area > best[0]:
                        best = (area, hwnd)
        return best[1] if best else None

    def find_main_launcher(self) -> bool:
        """Find the main Purple launcher window (large window, width >= 900).
        Used after login to detect when the main launcher appears."""
        hwnd = WindowFinder.find_by_process(["Purple.exe", "PurpleLauncher.exe"],
                                            min_width=900, min_height=500)
        if hwnd is None:
            hwnd = WindowFinder.find_by_process(
                ["Purple.exe", "PurpleLauncher.exe"],
                min_width=900, min_height=500, prefer_visible=False)
        if hwnd is None:
            hwnd = WindowFinder.find_by_title("PURPLE", min_width=900, min_height=500)
        if hwnd is not None:
            self.purple = WinWindow(hwnd)
            self._normalize_purple_shell_size(reason="find_main")
            return True
        return False

    def debug_enumerate_purple_windows(self):
        """Debug: list all Purple-related windows"""
        log.info("=== Enumerating Purple windows ===")
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                continue
            if pname not in ("purple.exe", "purplelauncher.exe"):
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            vis = user32.IsWindowVisible(hwnd)
            log.info(f"  hwnd={hwnd} title={title!r} class={cls} size={w}x{h} visible={vis} pid={pid.value}")

    def launch_purple(self):
        if self._try_attach_running_purple():
            log.info("attached to running Purple (skipping new launch)")
            return
        if self._purple_process_running() or self._any_purple_window_exists():
            log.info("skip launching Purple: process or window already exists")
            return
        if getattr(self, "_purple_logged_in", False):
            log.info("skip launching Purple: session already logged in")
            return
        paths = [
            self.game_path,
            r"D:\Program Files (x86)\NCSOFT\Purple\PurpleLauncher.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Purple\Purple.exe"),
            os.path.expandvars(r"%PROGRAMFILES(x86)%\NC\Purple\Purple.exe"),
        ]
        for p in paths:
            if p and os.path.exists(p):
                log.info(f"launching Purple: {p}")
                subprocess.Popen([p])
                time.sleep(1.0)
                return
        log.warning("Purple executable not found")

    def _real_game_hwnd(self) -> Optional[int]:
        """Return the hwnd of the REAL game window only: class GLFW30 (the
        game is built on GLFW) or a title containing 'Lineage'. LC.exe also
        owns GameGuard's anti-cheat dummy window (class '$GIVEmeMINT',
        ~1440x759, blank and unresponsive) which must NEVER be targeted."""
        names = {"lc.exe", "lineage.exe", "lineage"}
        best = None
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                continue
            if pname not in names:
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            if w < 200 or h < 150:
                continue
            if cls != "GLFW30" and "lineage" not in title.lower():
                continue
            area = w * h
            vis = 1 if user32.IsWindowVisible(hwnd) else 0
            if best is None or (vis, area) > (best[0], best[1]):
                best = (vis, area, hwnd)
        return best[2] if best else None

    def _is_real_game(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        cn = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cn, 256)
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        return cn.value == "GLFW30" or "lineage" in title.value.lower()

    def find_game(self) -> bool:
        # Only accept the real game window. The GameGuard anti-cheat dummy
        # ($GIVEmeMINT, 1440x759) is larger so naive "largest" selection grabs
        # it; clicking/capturing through its coordinate space misses the real
        # game. Wait for the real window instead.
        hwnd = self._real_game_hwnd()
        if hwnd is not None:
            self.game = WinWindow(hwnd)
            return True
        return False

    # ---- OCR helpers --------------------------------------------------
    def _game_on_top(self) -> bool:
        """True if the game (or same-process child) owns the pixel at center.

        Exact hwnd match is too strict for GLFW/DirectX — WindowFromPoint
        often returns a child; GameGuard splash also belongs to LC.exe.
        """
        if not self.game or not self.game.valid:
            return False
        cx, cy = self.game.rect.center
        top = user32.WindowFromPoint(wt.POINT(cx, cy))
        if not top:
            return False
        if top == self.game.hwnd:
            return True
        GA_ROOT = 2
        root = user32.GetAncestor(top, GA_ROOT) or top
        if root == self.game.hwnd:
            return True
        pid_here = wt.DWORD()
        user32.GetWindowThreadProcessId(root, ctypes.byref(pid_here))
        pid_game = wt.DWORD()
        user32.GetWindowThreadProcessId(self.game.hwnd, ctypes.byref(pid_game))
        return bool(pid_here.value and pid_here.value == pid_game.value)

    def capture_game(self) -> Optional[Image.Image]:
        """Capture the game window for OCR. The game is DirectX/OpenGL-rendered,
        so PrintWindow often returns black. Try PrintWindow first anyway
        (PW_RENDERFULLCONTENT does capture many GPU-composited windows); if it
        is black, force the game to the foreground with a real title-bar click
        (via the Interception driver, immune to the Windows foreground lock)
        and BitBlt its on-screen region."""
        if not self.game or not self.game.valid:
            return None
        img = self.game.capture()
        if img is not None and not self._frame_is_black(img):
            return img
        # PrintWindow came back black (covered or GPU window): put the game on
        # top with a physical title-bar click so the screen BitBlt sees it.
        for attempt in range(4):
            if self._game_on_top() and self.game.visible:
                break
            InputRouter.activate(self.game)
            time.sleep(0.4)
        if self.game.visible and self._game_on_top():
            return self.game.capture_screen()
        log.warning("capture_game: game still not on top after retries; "
                    "PrintWindow fallback (may be black)")
        return self.game.capture()

    def capture_game_fullscreen(self) -> Optional[Image.Image]:
        """Capture the FULL screen via ImageGrab. DirectX game content is
        visible on screen but not via PrintWindow/BitBlt on the window DC.
        Returns (full_screen_image, game_rect) so callers can map coords."""
        if not self.game or not self.game.valid:
            return None
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()  # full screen
            return img
        except Exception as e:
            log.warning("capture_game_fullscreen failed: %s", e)
            return None

    def ensure_game_on_top(self, timeout: float = 10.0) -> bool:
        """Force game window to foreground and keep it there. Returns True if successful."""
        if not self.game or not self.game.valid:
            return False
        start = time.time()
        while time.time() - start < timeout:
            if self._game_on_top() and self.game.visible:
                return True
            self.game.activate()
            time.sleep(0.5)
        return self._game_on_top() and self.game.visible

    @staticmethod
    def _frame_is_black(img) -> bool:
        """True if a frame is (almost) all black — the signature of a
        PrintWindow fallback on a DirectX window or a covered window."""
        if img is None:
            return True
        try:
            small = img.convert("L").resize((80, 45))
            px = list(small.getdata())
            if not px:
                return True
            return sum(px) / len(px) < 4
        except Exception:
            return False

    def winocr_for(self, lang: str):
        """Windows OCR engine for the detected UI language.

        Korean / English / zh-Hans / zh-Hant are different language packs;
        using the Korean engine on a Traditional Chinese splash garbles
        選擇驗證方法. Engines are created lazily and cached.
        """
        tag = WINOCR_TAGS.get(lang) or WINOCR_TAGS.get("en", "en")
        cache = getattr(self, "_winocr", None)
        if cache is None:
            self._winocr = cache = {}
        if cache.get(tag) is not None:
            return cache[tag]
        try:
            eng = WinOcr(tag)
            cache[tag] = eng
            log.info("WinOCR engine ready: %s (%s)", lang, tag)
            return eng
        except Exception as e:
            log.warning("WinOCR %s (%s) unavailable: %r", lang, tag, e)
            cache[tag] = self.ocr
            return self.ocr

    def _ocr_lines(self, img) -> list:
        """RapidOCR (multilingual) plus the WinOCR pack that matches the
        detected UI language (ko / en / zh-TW / zh-CN)."""
        if img is None:
            return []
        lines = []
        seen = set()

        def _add(got):
            for ln in got or []:
                key = (getattr(ln, "text", ""), getattr(ln, "x", 0),
                       getattr(ln, "y", 0))
                if key in seen:
                    continue
                seen.add(key)
                lines.append(ln)

        rapid_blob = ""
        if self.rapid_ocr is not None:
            try:
                got = self.rapid_ocr.recognize(img) or []
            except Exception:
                got = []
            _add(got)
            rapid_blob = "".join(getattr(ln, "text", "") or "" for ln in got)
            detected = detect_ui_lang(rapid_blob)
            if detected:
                self.lang = detected
        if has_hangul(rapid_blob):
            win_lang = "ko"
        elif has_cjk(rapid_blob):
            win_lang = self.lang if self.lang in ("zh-TW", "zh-CN") else "zh-TW"
        else:
            win_lang = detect_ui_lang(rapid_blob) or self.lang or "en"
        skip_ko_on_cjk = (
            has_cjk(rapid_blob) and not has_hangul(rapid_blob)
            and win_lang == "ko")
        if not skip_ko_on_cjk:
            try:
                extra = self.winocr_for(win_lang).recognize(img) or []
            except Exception:
                extra = []
            _add(extra)
            blob2 = "".join(getattr(ln, "text", "") or "" for ln in lines)
            detected2 = detect_ui_lang(blob2)
            if detected2:
                self.lang = detected2
        return lines

    def ocr_lines(self, win: WinWindow) -> List[OcrLine]:
        img = win.capture_content()
        if img is None:
            return []
        if self.last_capture_path:
            try:
                img.save(self.last_capture_path)
            except Exception:
                pass
        return self._ocr_lines(img)

    def find_words(self, win: WinWindow, words: List[str],
                   exact: bool = False, fuzzy: float = 0.0,
                   game: bool = False) -> List[Tuple[str, OcrWord]]:
        img = (self.capture_game() if game else win.capture_content())
        if img is None:
            return []
        if fuzzy > 0:
            hits = []
            for qw, line in self.find_lines(win, words, exact=exact,
                                            fuzzy=fuzzy, game=game):
                if line.words:
                    hits.append((qw, line.words[0]))
                else:
                    hits.append((qw, OcrWord(text=line.text, x=line.x,
                                             y=line.y, w=line.w, h=line.h)))
            return hits
        hits = []
        seen = set()
        engines = [self.rapid_ocr]
        try:
            engines.append(self.winocr_for(self.lang or "en"))
        except Exception:
            engines.append(self.ocr)
        for engine in engines:
            if engine is None:
                continue
            try:
                got = engine.find(img, words, exact=exact) or []
            except Exception:
                got = []
            for item in got:
                w = item[1] if isinstance(item, tuple) else item
                key = (getattr(w, "text", ""), getattr(w, "x", 0), getattr(w, "y", 0))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(item)
        return hits

    def find_lines(self, win: WinWindow, words: List[str],
                   exact: bool = False, fuzzy: float = 0.0,
                   game: bool = False) -> List[Tuple[str, OcrLine]]:
        img = (self.capture_game() if game else win.capture_content())
        if img is None:
            return []
        hits = []
        seen = set()
        engines = []
        if self.rapid_ocr is not None:
            engines.append(self.rapid_ocr)
        engines.append(self.ocr)
        for engine in engines:
            try:
                got = engine.find_lines(img, words, exact=exact, fuzzy=fuzzy) or []
            except Exception:
                got = []
            for item in got:
                ln = item[1] if isinstance(item, tuple) else item
                key = (getattr(ln, "text", ""), getattr(ln, "x", 0), getattr(ln, "y", 0))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(item)
        return hits

    def find_lines_screen(self, words: List[str],
                          fuzzy: float = 0.0) -> List[Tuple[str, OcrLine]]:
        """Full-screen capture + RapidOCR. Returns OcrLine objects with
        SCREEN coordinates (not game-client). Caller must map to client
        coords before clicking."""
        if self.rapid_ocr is None:
            return []
        img = self.capture_game_fullscreen()
        if img is None:
            return []
        return self.rapid_ocr.find_lines(img, words, exact=False, fuzzy=fuzzy)

    def run_heavy_ocr(self, words: List[str]) -> List[dict]:
        """Run heavy OCR (quest_ocr.exe) to find words on screen.
        Returns list of matches with position info from result.json.
        If already running (non-blocking mode), returns None to signal 'wait'."""
        import json
        import subprocess
        import os
        from pathlib import Path
        
        heavy_ocr_dir = Path(__file__).parent / "heavy_OCR"
        quest_file = heavy_ocr_dir / "quest.txt"
        result_file = heavy_ocr_dir / "result.json"
        
        # Non-blocking mode: if process already running, check status
        if hasattr(self, '_heavy_ocr_proc') and self._heavy_ocr_proc is not None:
            proc = self._heavy_ocr_proc
            if proc.poll() is None:
                return None  # signal: still running, caller should wait
            # Process finished — read result
            self._heavy_ocr_proc = None
            return self._parse_heavy_ocr_result(result_file)
        
        # Write words to quest.txt (UTF-8)
        with open(quest_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(words))
        
        # Delete old result so we know when new one is ready
        if result_file.exists():
            result_file.unlink()
        
        # Start quest_ocr.exe in background
        try:
            log.info("Starting heavy OCR (background) for: %s", words)
            proc = subprocess.Popen(
                [str(heavy_ocr_dir / "quest_ocr.exe")],
                cwd=str(heavy_ocr_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            )
            self._heavy_ocr_proc = proc
            return None  # signal: started, check again next tick
        except Exception as e:
            log.error("Failed to start heavy OCR: %s", e)
            return []

    def _parse_heavy_ocr_result(self, result_file: Path) -> List[dict]:
        """Parse quest_ocr.exe result.json into a list of match dicts."""
        import json
        if not result_file.exists():
            return []
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            matches = data.get('matches', [])
            found = []
            for m in matches:
                if m.get('found') and m.get('matches'):
                    for match in m['matches']:
                        bbox = match.get('bounding_box', [0, 0, 0, 0])
                        center = match.get('center', [0, 0])
                        found.append({
                            'word': m['word'],
                            'x': bbox[0],
                            'y': bbox[1],
                            'w': bbox[2],
                            'h': bbox[3],
                            'cx': center[0],
                            'cy': center[1]
                        })
            return found
        except Exception as e:
            log.error("Failed to parse heavy OCR result: %s", e)
            return []

    def _client_wh(self):
        """Live Purple client size. Degenerate GetClientRect (0x0) must not
        clamp detected clicks to (0,0)."""
        rect = self.purple.client_rect if self.purple else None
        rw = int(getattr(rect, "width", 0) or 0)
        rh = int(getattr(rect, "height", 0) or 0)
        if rw <= 1 or rh <= 1:
            r = self.purple.rect if self.purple else None
            rw = int(getattr(r, "width", 0) or 0)
            rh = int(getattr(r, "height", 0) or 0)
        return rw, rh

    def _clamp_client(self, cx: int, cy: int):
        orig = (int(cx), int(cy))
        rw, rh = self._client_wh()
        if rw > 1:
            cx = max(0, min(rw - 1, orig[0]))
        else:
            cx = orig[0]
        if rh > 1:
            cy = max(0, min(rh - 1, orig[1]))
        else:
            cy = orig[1]
        if (cx, cy) == (0, 0) and orig != (0, 0):
            log.warning("client clamp would send (0,0); keeping detected %s "
                        "(client %sx%s)", orig, rw, rh)
            return orig
        return cx, cy

    def _resolve_click(self, space: str, label: str, win, cx: int, cy: int,
                       allow_fixed: Optional[bool] = None):
        """Optionally replace detected client coords with saved ratios.

        When purple_gate_clicks is on, template/OCR coords win — saved ratios
        are only used by _try_fixed_click / _gated_purple_click fallback.
        """
        from positions import canonical_key
        store = getattr(self, "positions", None)
        key = canonical_key(label)
        if not store or not key or win is None:
            return cx, cy
        if allow_fixed is None:
            allow_fixed = not (
                space == "purple" and self._purple_gate_clicks())
        if allow_fixed and store.is_fixed_space(space):
            xy = store.client_xy(space, key, win)
            if xy and xy != (0, 0):
                log.info("fixed-position %s/%s -> client %s", space, key, xy)
                return xy
            log.warning("fixed-position missing %s/%s; using detected (%s,%s)",
                        space, key, cx, cy)
        return cx, cy

    def _record_click(self, space: str, label: str, win, cx: int, cy: int):
        from positions import canonical_key
        store = getattr(self, "positions", None)
        if not store or not store.is_dynamic_space(space) or win is None:
            return
        key = canonical_key(label)
        if key:
            store.record_client(space, key, win, cx, cy)

    def _try_fixed_click(self, space: str, key: str, win, cef: bool = False) -> bool:
        """Click a saved position without locating the control. False if
        not in fixed mode or the key is missing (caller should detect)."""
        store = getattr(self, "positions", None)
        if not store or not store.is_fixed_space(space) or win is None:
            return False
        xy = store.client_xy(space, key, win)
        if not xy:
            return False
        cx, cy = xy
        log.info("fixed-position click %s/%s client=(%s,%s)", space, key, cx, cy)
        if self.dry_run:
            return True
        if cef and win is self.purple:
            cef_x, cef_y = self._cef_point(cx, cy)
            InputRouter.click_cef(win, cef_x, cef_y)
        else:
            InputRouter.click_client(win, cx, cy)
        time.sleep(0.12)
        return True

    def click_word(self, win: WinWindow, word: OcrWord, click: str,
                   label: str = "") -> bool:
        if click == "first_char":
            x = word.x + int(word.w * 0.18)
            y = word.y + word.h // 2
        else:
            x, y = word.center
        space = "game" if (self.game is not None and win is self.game) else "purple"
        x, y = self._resolve_click(space, label or word.text, win, x, y)
        if self.dry_run:
            log.info(f"[dry-run] would click {label or word.text!r} at client ({x},{y})")
            return True
        InputRouter.click_client(win, x, y)
        log.info(f"clicked {label or word.text!r} at client ({x},{y})")
        self._record_click(space, label or word.text, win, x, y)
        return True

    def click_line(self, win: WinWindow, line: OcrLine, click: str,
                   label: str = "") -> bool:
        if click == "first_char":
            x = line.x + int(line.w * 0.18)
            y = line.y + line.h // 2
        else:
            x, y = line.center
        space = "game" if (self.game is not None and win is self.game) else "purple"
        x, y = self._resolve_click(space, label or line.text, win, x, y)
        if self.dry_run:
            log.info(f"[dry-run] would click {label or line.text!r} at client ({x},{y})")
            return True
        InputRouter.click_client(win, x, y)
        r = win.rect
        log.info(f"clicked {label or line.text!r} at client ({x},{y}) "
                 f"[screen=({r.left + x},{r.top + y}) win={r.width}x{r.height}]")
        self._record_click(space, label or line.text, win, x, y)
        return True

    # ---- in-game clicks (Interception first, then UIA, then SendInput) --
    def game_click(self, win: WinWindow, cx: int, cy: int,
                   label: str = "") -> bool:
        """Click at client coords inside `win`. Uses the Interception driver
        first (device-level, unflagged input), then UI Automation
        (accessibility API, not input injection), then falls back to
        SendInput. NC Guard blocks SendInput in the game."""
        if self.dry_run:
            log.info(f"[dry-run] would click {label or ''!r} at client ({cx},{cy})")
            return True
        # Ensure game window is actually on top — Purple (also elevated)
        # often holds the foreground lock and covers the game. Win32
        # activate() alone is unreliable; use interception-level activation.
        self._ensure_game_on_top()
        space = "game"
        cx, cy = self._resolve_click(space, label, win, cx, cy)
        sx, sy = win.client_to_screen(cx, cy)

        # 1. Interception driver (device-level, unflagged) - primary method
        if self._use_interception and self._interception_ready:
            try:
                # Verify game is still on top at the click point; if Purple
                # stole focus, re-activate before clicking.
                pt_hwnd = user32.WindowFromPoint(wt.POINT(sx, sy))
                if pt_hwnd != win.hwnd:
                    self._ensure_game_on_top()
                    sx, sy = win.client_to_screen(cx, cy)
                if interception.click(sx, sy):
                    log.info(f"int-click {label or ''!r} at client ({cx},{cy}) "
                             f"[screen=({sx},{sy})]")
                    self._record_click(space, label, win, cx, cy)
                    return True
                log.warning("interception send failed -> fallback")
            except Exception as ex:
                log.warning("interception click error %r -> fallback", ex)

        # 2. UI Automation (accessibility, not input injection)
        try:
            if InputRouter.click_uia(sx, sy):
                log.info(f"uia-click {label or ''!r} at client ({cx},{cy}) "
                         f"[screen=({sx},{sy})]")
                return True
        except Exception as ex:
            log.warning("UIA click failed: %r", ex)

        # 3. SendInput fallback
        InputRouter.click_client(win, cx, cy)
        log.info(f"clicked {label or ''!r} at client ({cx},{cy})")
        return True

    def game_click_word(self, win: WinWindow, word: OcrWord, click: str,
                        label: str = "") -> bool:
        if click == "first_char":
            x = word.x + int(word.w * 0.18)
            y = word.y + word.h // 2
        else:
            x, y = word.center
        return self.game_click(win, x, y, label)

    def game_click_line(self, win: WinWindow, line: OcrLine, click: str,
                        label: str = "") -> bool:
        if click == "first_char":
            x = line.x + int(line.w * 0.18)
            y = line.y + line.h // 2
        elif click == "top":
            x, y = line.center
            y = line.y + int(line.h * 0.25)
        else:
            x, y = line.center
        return self.game_click(win, x, y, label)

    @staticmethod
    def _alnum(text: str) -> str:
        return "".join(c for c in (text or "").lower() if c.isalnum())

    def _is_purple_login_screen(self, raw: str = None) -> bool:
        """True when the Purple window is the email/QR login form.

        A maximized login window is >= 900px wide, which used to be treated
        as 'already logged in' and skipped credentials."""
        from purple_state import PurpleScreen, classify_blob
        if raw is not None:
            return classify_blob(raw) in (
                PurpleScreen.LOGIN_EMAIL, PurpleScreen.LOGIN_PASSWORD)
        view = self._read_purple_view()
        return view.screen in (
            PurpleScreen.LOGIN_EMAIL, PurpleScreen.LOGIN_PASSWORD)

    # ---- Purple phases ------------------------------------------------
    def _classify_attached_purple(self) -> str:
        """Decide what a just-attached Purple window actually shows.

        Width >= 900 alone is NOT proof of login — cold start can show the
        email/password form inside the main shell. Returns phase name:
        WAIT_LOGIN_FORM | FIND_LINEAGE | (empty = wait/undetermined).
        Unknown content must NOT be treated as the login form — that caused
        blind credential clicks on some PCs.
        """
        from purple_state import PurpleScreen, LOGIN_SCREENS, LAUNCHER_SCREENS
        if not self.purple or not self.purple.valid:
            return ""
        rect = self.purple.rect
        if rect.width < 300 or rect.height < 400:
            return ""
        view = self._read_purple_view(force=True)
        if view.screen in LOGIN_SCREENS:
            log.info("attached Purple %dx%d is %s — not logged in",
                     rect.width, rect.height, view.screen.value)
            return "WAIT_LOGIN_FORM"
        if view.screen in LAUNCHER_SCREENS:
            log.info("attached Purple %dx%d is %s (logged in)",
                     rect.width, rect.height, view.screen.value)
            return "FIND_LINEAGE"
        if view.screen == PurpleScreen.LOGGING_IN:
            log.info("attached Purple %dx%d still logging in — wait",
                     rect.width, rect.height)
            return ""
        if view.screen == PurpleScreen.LOGIN_ERROR:
            log.info("attached Purple %dx%d login error — treat as form",
                     rect.width, rect.height)
            return "WAIT_LOGIN_FORM"
        game_up = False
        alive = getattr(self, "_game_process_alive", None)
        if callable(alive):
            try:
                game_up = bool(alive())
            except Exception:
                game_up = False
        if not game_up:
            log.info(
                "attached Purple %dx%d unclassified, LC not running — login form",
                rect.width, rect.height)
            return "WAIT_LOGIN_FORM"
        if rect.width < 900:
            log.info("attached Purple %dx%d undetermined popup — wait",
                     rect.width, rect.height)
            return ""
        log.info("attached Purple %dx%d content undetermined — wait (no click)",
                 rect.width, rect.height)
        return ""

    def do_find_purple(self):
        if self._try_attach_running_purple():
            rect = self.purple.rect
            decision = self._classify_attached_purple()
            log.info("attached running Purple %dx%d -> classify=%s",
                     rect.width, rect.height, decision or "wait")
            if decision == "FIND_LINEAGE":
                self._mark_purple_logged_in()
                self._set_phase(Phase.FIND_LINEAGE)
            elif decision == "WAIT_LOGIN_FORM":
                self._purple_logged_in = False
                self._set_phase(Phase.WAIT_LOGIN_FORM)
            # else: keep FIND_PURPLE and wait for content to settle
            return
        if self._purple_process_running() or self._any_purple_window_exists():
            log.info("Purple.exe running; restoring window (not launching new)")
            return
        if getattr(self, "_purple_logged_in", False):
            if not self._purple_process_running():
                log.warning("Purple process gone; clearing session login flag")
                self._purple_logged_in = False
        if self.find_purple():
            rect = self.purple.rect
            if rect.width < 900 or rect.height < 500:
                if hasattr(self, "_restore_hidden_purple") and self._restore_hidden_purple():
                    rect = self.purple.rect
            log.info(f"Purple found: {self.purple.title!r} {rect.width}x{rect.height}")
            if rect.width < 300 or rect.height < 400:
                log.warning("Purple window too small, waiting to stabilize")
                return
            decision = self._classify_attached_purple()
            if decision == "FIND_LINEAGE":
                self._mark_purple_logged_in()
                self._set_phase(Phase.FIND_LINEAGE)
            elif decision == "WAIT_LOGIN_FORM":
                self._purple_logged_in = False
                self._set_phase(Phase.WAIT_LOGIN_FORM)
            else:
                self._set_phase(Phase.WAIT_LOGIN_FORM)
        if time.time() - self.phase_start > 60:
            log.error("timed out waiting for Purple")
            self._set_phase(Phase.ERROR)

    def do_wait_login_form(self):
        from purple_state import PurpleScreen, LOGIN_SCREENS, LAUNCHER_SCREENS
        if not self.purple or not self.purple.valid:
            self._goto_purple_phase()
            return
        rect = self.purple.rect
        view = self._read_purple_view()
        if view.screen in LAUNCHER_SCREENS:
            self._mark_purple_logged_in()
            self._set_phase(Phase.FIND_LINEAGE)
            return
        if view.screen == PurpleScreen.LOGGING_IN:
            log.info("login form wait: still logging in")
            return
        if view.screen == PurpleScreen.UNKNOWN:
            game_up = False
            alive = getattr(self, "_game_process_alive", None)
            if callable(alive):
                try:
                    game_up = bool(alive())
                except Exception:
                    game_up = False
            settle = 8.0 if game_up else 1.2
            if time.time() - self.phase_start < settle:
                log.info("login window unclassified (%sx%s); waiting "
                         "(elapsed %.0fs)", rect.width, rect.height,
                         time.time() - self.phase_start)
                return
            if not game_up:
                log.info("unclassified Purple, LC not running — enter credentials")
                self._set_phase(Phase.ENTER_CREDENTIALS)
                return
            log.info("login window still unclassified after wait; not clicking")
            return

        if rect.height < 620:
            if time.time() - self.phase_start < 8:
                log.info("login window still forming (%sx%s), waiting "
                         "(elapsed %.0fs)", rect.width, rect.height,
                         time.time() - self.phase_start)
                return
            log.info("login window small but stable (%sx%s); proceeding",
                     rect.width, rect.height)

        larger = None
        if rect.width < 900:
            larger = self._find_larger_login_form(self.purple.hwnd)
        if larger is not None and larger != self.purple.hwnd:
            log.info("re-targeting to larger login form hwnd=%s", larger)
            self.purple = WinWindow(larger)
            self._purple_watcher().invalidate()

        if view.screen in LOGIN_SCREENS:
            self._set_phase(Phase.ENTER_CREDENTIALS)
            return
        img = self.purple.capture_content()
        if img is None or img.size[0] < 200 or img.size[1] < 200:
            return
        self._set_phase(Phase.ENTER_CREDENTIALS)

    def click_ratio(self, step_name: str, fallback: Tuple[float, float]) -> bool:
        entry = self.click_map.get(step_name)
        if entry and "rx" in entry and "ry" in entry:
            rx, ry = float(entry["rx"]), float(entry["ry"])
        else:
            rx, ry = fallback
        rect = self.purple.client_rect
        cx = int(rect.width * rx)
        cy = int(rect.height * ry)
        cx, cy = self._resolve_click("purple", step_name, self.purple, cx, cy)
        if self.dry_run:
            log.info(f"[dry-run] would click ratio '{step_name}' at client ({cx},{cy})")
            return True
        InputRouter.click_client(self.purple, cx, cy)
        log.info(f"clicked ratio '{step_name}' at client ({cx},{cy})")
        self._record_click("purple", step_name, self.purple, cx, cy)
        return True

    def type_in_client(self, cx: int, cy: int, text: str):
        if self.dry_run:
            log.info(f"[dry-run] would type into client ({cx},{cy}): {text!r}")
            return
        InputRouter.click_client(self.purple, cx, cy)
        time.sleep(0.2)
        InputRouter.select_all()
        time.sleep(0.05)
        InputRouter.type_text(text)
        time.sleep(0.2)

    def _cred_next(self):
        self._cred_step += 1
        self._cred_step_deadline = time.time() + 15

    def _cef_point(self, form_x: int, form_y: int) -> Tuple[int, int]:
        """Translate form-window OCR coords into CEF child client coords.
        Purple's login form renders inside a Chrome_RenderWidgetHostHWND child
        that is offset from the form window's client origin."""
        if not self.purple:
            return form_x, form_y
        off = self.purple.child_offset("Chrome_RenderWidgetHostHWND")
        if off is None:
            return form_x, form_y
        return form_x - off[0], form_y - off[1]

    # Login card is ~962x670 in the dialog, or a centered overlay in a
    # maximized launcher. All Purple-login fallbacks are ratios of THIS
    # card, never of the outer window.
    _CARD_REF_W, _CARD_REF_H = 962, 670
    R_ADDR = (0.500, 0.410)
    R_ID = (0.500, 0.476)
    R_NEXT = (0.500, 0.498)
    R_PASSWORD = (0.500, 0.490)
    R_LOGIN = (0.500, 0.555)

    def _login_card_box(self, img=None):
        """(x, y, w, h) of the login card in window-client / capture pixels."""
        r = self.purple.client_rect
        if img is not None:
            pts = []
            for ln in self._login_lines(img):
                al = self._alnum(ln.text)
                if any(t in al for t in (
                        "email", "password", "qrcode", "phone", "address",
                        "adress", "idoremail", "keepme", "next", "로그인")):
                    if any(b in al for b in ("different", "another", "joinpurple",
                                             "reset", "forgot")):
                        continue
                    pts.append(ln)
            if len(pts) >= 2:
                pad_x = max(16, int(r.width * 0.02))
                pad_y = max(24, int(r.height * 0.04))
                x0 = max(0, min(ln.x for ln in pts) - pad_x)
                y0 = max(0, min(ln.y for ln in pts) - pad_y)
                x1 = min(r.width, max(ln.x + ln.w for ln in pts) + pad_x)
                y1 = min(r.height, max(ln.y + ln.h for ln in pts) + int(pad_y * 1.6))
                if (x1 - x0) >= 220 and (y1 - y0) >= 180:
                    log.info("login card OCR (%s,%s) %sx%s on window %sx%s",
                             x0, y0, x1 - x0, y1 - y0, r.width, r.height)
                    return x0, y0, x1 - x0, y1 - y0
        if r.width <= 1100 and r.height <= 850:
            return 0, 0, r.width, r.height
        fw = min(self._CARD_REF_W, r.width)
        fh = min(self._CARD_REF_H, r.height)
        return (r.width - fw) // 2, (r.height - fh) // 2, fw, fh

    def _form_pt(self, rx: float, ry: float, img=None) -> Tuple[int, int]:
        x0, y0, fw, fh = self._login_card_box(img)
        return int(x0 + rx * fw), int(y0 + ry * fh)

    def _map_form_pt(self, name: str, rx: float, ry: float, img=None) -> Tuple[int, int]:
        entry = (self.click_map or {}).get(name) or {}
        if entry.get("rx") is not None and entry.get("ry") is not None:
            rx, ry = float(entry["rx"]), float(entry["ry"])
        return self._form_pt(rx, ry, img)

    def _locate_blue_button(self, img, min_y: int = 0, max_y: int = None,
                            pick: str = "lowest"):
        """Return (cx, cy, top, bottom, width) of a blue button, or None.
        pick='lowest' is Login; pick='highest' is Next under the ID field."""
        try:
            import numpy as np
            arr = np.array(img).astype(int)
            h, w, _ = arr.shape
            if max_y is None:
                max_y = h
            rows = []
            for y in range(0, h):
                row = arr[y, :, :]
                mask = (row[:, 2] > 55) & (row[:, 2] > row[:, 0] + 8) & \
                    (row[:, 2] >= row[:, 1] - 15)
                cnt = int(mask.sum())
                if cnt > max(20, w // 25):
                    rows.append((y, cnt))
            if not rows:
                return None
            clusters = []
            for y, c in rows:
                if clusters and y - clusters[-1][-1][0] <= 3:
                    clusters[-1].append((y, c))
                else:
                    clusters.append([(y, c)])
            best = None
            for cl in clusters:
                ys = [y for y, _ in cl]
                hgt = max(ys) - min(ys) + 1
                # Window-relative min height skipped the real Login on large
                # launchers (h/40 ≈ 25px on 1026). Keep small form buttons.
                if hgt < 10 or hgt > 90:
                    continue
                top, bot = min(ys), max(ys)
                ymid = (top + bot) // 2
                if ymid < min_y or ymid > max_y:
                    continue
                row = arr[ymid, :, :]
                mask = (row[:, 2] > 55) & (row[:, 2] > row[:, 0] + 8) & \
                    (row[:, 2] >= row[:, 1] - 15)
                xs = [x for x in range(w) if mask[x]]
                if not xs:
                    continue
                cand = ((min(xs) + max(xs)) // 2, ymid, top, bot, len(xs))
                if best is None:
                    best = cand
                elif pick == "highest" and cand[1] < best[1]:
                    best = cand
                elif pick != "highest" and cand[1] > best[1]:
                    best = cand
            return best
        except Exception as e:
            log.warning("blue button locate failed: %s", e)
            return None

    def _click_blue_button(self, img, min_y: int = 0) -> bool:
        """Find the solid blue Login button by pixel color and click its center."""
        best = self._locate_blue_button(img, min_y=min_y)
        if best is None:
            return False
        cx, cy, _top, _bot, width = best
        orig = (cx, cy)
        cx, cy = self._clamp_client(cx, cy)
        store = getattr(self, "positions", None)
        if store and store.is_fixed_purple:
            mapped = self._resolve_click("purple", "blue button", self.purple, cx, cy)
            if mapped and mapped != (0, 0):
                cx, cy = mapped
        if (cx, cy) == (0, 0) and orig != (0, 0):
            cx, cy = orig
        cef_x, cef_y = self._cef_point(cx, cy)
        if self.dry_run:
            log.info(f"[dry-run] would click blue button at CEF ({cef_x},{cef_y})")
            return True
        InputRouter.click_cef(self.purple, cef_x, cef_y)
        log.info(f"clicked blue button at form ({cx},{cy}) width={width} -> CEF ({cef_x},{cef_y})")
        self._record_click("purple", "blue button", self.purple, cx, cy)
        return True

    def _is_address_tab(self, text: str) -> bool:
        if self._text_matches_username_email(text):
            return True
        al = self._alnum(text)
        if not al or "inwith" in al:
            return False
        return "address" in al or "adress" in al

    def _is_id_or_email_placeholder(self, text: str) -> bool:
        """In-field label for username/email — not the Address tab chrome."""
        al = self._alnum(text)
        t = normalize(text)
        if not al or "inwith" in al:
            return False
        if "address" in al or "adress" in al:
            return False
        if any(tok in al for tok in ("phone", "qrcode", "keepme", "joinpurple",
                                     "signup", "resetpassword", "findaccount",
                                     "different", "another")):
            return False
        # English in-field hint (successful login on 1642x1026 used this).
        if ("email" in al or "e-mail" in t) and "id" in al:
            return True
        if any(k in t for k in ("이메일", "電子郵件", "電郵")):
            return True
        # Chinese tab text doubles as placeholder; caller must pick below tab.
        if fuzzy_match_label(text, self._username_email_keywords(),
                             fuzzy=self.PURPLE_LABEL_FUZZY):
            return True
        return False

    def _login_lines(self, img):
        if img is None:
            return []
        lines = list(self._ocr_lines(img) or [])
        try:
            extra = self.ocr.recognize(img) or []
        except Exception:
            extra = []
        seen = {(ln.text, ln.x, ln.y) for ln in lines}
        for ln in extra:
            key = (ln.text, ln.x, ln.y)
            if key not in seen:
                lines.append(ln)
                seen.add(key)
        return lines

    def _find_login_label(self, img, predicate):
        lines = self._login_lines(img)
        hits = [ln for ln in lines if predicate(ln.text)]
        if not hits:
            return None
        hits.sort(key=lambda ln: (ln.y, ln.x))
        return hits[0]

    def _logging_in_screen(self, img=None, blob: str = "") -> bool:
        """True when Purple shows a logging-in overlay (en/ko/zh)."""
        if img is not None:
            blob = " | ".join(ln.text for ln in self._login_lines(img)[:24])
        if not blob:
            return False
        al = self._alnum(blob)
        if "loggingin" in al and "password" not in al:
            return True
        compact = (blob or "").replace(" ", "")
        if any(k in compact for k in ("登录中", "登彔中", "登錄中", "로그인중")):
            if "password" not in al and "密码" not in compact and "密碼" not in compact:
                return True
        return False

    def _click_label_cef(self, line, label: str, save_field: bool = False,
                         top: bool = False):
        cx = line.x + line.w // 2
        if top or getattr(line, "h", 0) > 40:
            cy = line.y + min(10, max(getattr(line, "h", 8) // 6, 4))
        else:
            cy = line.y + max(line.h // 2, 4)
        orig = (cx, cy)
        cx, cy = self._clamp_client(cx, cy)
        mapped = self._resolve_click("purple", label, self.purple, cx, cy)
        if mapped and mapped != (0, 0):
            cx, cy = mapped
        if (cx, cy) == (0, 0) and orig != (0, 0):
            cx, cy = orig
        cef_x, cef_y = self._cef_point(cx, cy)
        log.info("click %s %r at (%s,%s) size=%sx%s cef=(%s,%s)",
                 label, line.text, cx, cy, line.w, line.h, cef_x, cef_y)
        if not self.dry_run:
            InputRouter.click_cef(self.purple, cef_x, cef_y)
            time.sleep(0.4)
        if save_field:
            self._last_id_field_xy = (cx, cy)
        self._record_click("purple", label, self.purple, cx, cy)
        return cx, cy

    def _is_password_label(self, text: str) -> bool:
        """True only for the Password field label — never 'Reset Password'."""
        al = self._alnum(text)
        t = normalize(text)
        if not al:
            return False
        if any(b in al for b in ("reset", "forgot", "findaccount", "address",
                                 "different", "another", "incorrect",
                                 "usernameor")):
            return False
        if any(k in t for k in ("비밀번호", "密碼", "密码", "암호")):
            if any(k in t for k in ("재설정", "찾기", "重置", "忘记")):
                return False
            return True
        # Exact-ish field label. "password" in "resetpassword" is already out.
        if al in ("password", "passwrd", "passwor", "passwd", "passw0rd"):
            return True
        return al.startswith("passw") and len(al) <= 10

    def _password_label_hits(self, img, login_top=None):
        """OCR hits for the Password field. Drops Reset Password, including
        when OCR splits it into a 'Reset' line and a 'Password' line."""
        lines = list(self._login_lines(img) or [])
        reset_boxes = []
        for ln in lines:
            al = self._alnum(ln.text)
            raw = ln.text or ""
            if "reset" in al or "forgot" in al or "재설정" in raw or "重置" in raw:
                reset_boxes.append(ln)
        hits = []
        for ln in lines:
            if not self._is_password_label(ln.text):
                continue
            cy = ln.y + ln.h // 2
            if login_top is not None and cy >= login_top - 6:
                continue
            near_reset = False
            for rln in reset_boxes:
                same_row = abs((rln.y + rln.h // 2) - cy) <= max(18, ln.h)
                beside = abs(rln.x - ln.x) < max(ln.w, rln.w) + 40
                if same_row and beside:
                    near_reset = True
                    break
            if near_reset:
                log.info("skip Password OCR %r (next to Reset Password)", ln.text)
                continue
            hits.append(ln)
        hits.sort(key=lambda ln: (ln.y, ln.x))
        return hits

    def _on_password_form(self, img) -> bool:
        """True on the Password + Login card, not the ID/Next card.

        Reset Password is a footer on BOTH cards, so it is not enough.
        """
        if img is None:
            return False
        if self._password_label_hits(img):
            return True
        if self._find_login_label(img, self._is_address_tab):
            return False
        if self._find_login_label(img, self._is_id_or_email_placeholder):
            return False
        blob = self._alnum(" ".join(
            ln.text for ln in (self._login_lines(img) or [])[:24]))
        prefix = (self.username or "").split("@")[0][:8].lower()
        if prefix and prefix in blob and (
                "anotheraccount" in blob or "loginwith" in blob):
            return True
        return False

    def _find_nc_character(self, img):
        """Bottom-center of the NC mascot/logo on the login card.

        The password label sits directly under that character.
        """
        if img is None:
            return None
        for ln in self._login_lines(img):
            al = self._alnum(ln.text)
            raw = (ln.text or "").strip()
            if "join" in al or "inwith" in al:
                continue
            if al in ("nc", "ncs", "ncsoft") or al.startswith("ncsoft") \
                    or raw.upper() in ("NC", "NCsoft", "NCSOFT"):
                pt = (ln.x + ln.w // 2, ln.y + ln.h)
                log.info("NC mark via OCR %r at %s", ln.text, pt)
                return pt
        det = getattr(self, "_person_detector", None)
        if det is not None and getattr(det, "available", False):
            try:
                import numpy as np
                arr = np.array(img.convert("RGB"))
                hits = det.detect(arr) or []
            except Exception:
                hits = []
            if hits:
                hits.sort(key=lambda d: (d.x2 - d.x1) * (d.y2 - d.y1),
                          reverse=True)
                d = hits[0]
                log.info("NC character person-box (%s,%s)-(%s,%s) conf=%.2f",
                         d.x1, d.y1, d.x2, d.y2, d.conf)
                return d.cx, d.y2
        try:
            import numpy as np
            arr = np.array(img.convert("RGB")).astype(int)
            h, w, _ = arr.shape
            x0, y0, fw, fh = self._login_card_box(img)
            mx = arr.max(axis=2)
            mn = arr.min(axis=2)
            sat = mx - mn
            blueish = (arr[:, :, 2] > 100) & (arr[:, :, 2] > arr[:, :, 0]) & \
                (arr[:, :, 2] > arr[:, :, 1])
            mask = (sat > 40) & (mx < 250) & ~blueish
            # Stay in the upper half of the login CARD. Full-window 0.58 of a
            # 1642x1026 launcher put the blob on Reset Password (~y=551).
            mask[:, :] = False
            y1 = y0 + max(40, int(fh * 0.52))
            mask[y0:y1, x0:x0 + fw] = (sat[y0:y1, x0:x0 + fw] > 40) & \
                (mx[y0:y1, x0:x0 + fw] < 250) & ~blueish[y0:y1, x0:x0 + fw]
            ys, xs = np.where(mask)
            if len(ys) >= 80:
                y2 = int(np.percentile(ys, 90))
                band = (ys >= y2 - 12) & (ys <= y2)
                cx = int(np.median(xs[band])) if band.any() else int(np.median(xs))
                log.info("NC character via color blob cx=%s bottom=%s (card %sx%s)",
                         cx, y2, fw, fh)
                return cx, y2
        except Exception as e:
            log.debug("NC color blob failed: %s", e)
        return None

    def _password_slot_between_nc_and_login(self, img):
        """Password label is below the NC character and above the blue Login.

        Never click Reset Password (footer link under Login).
        Returns (cx, cy, login_top) to click the label, or None.
        """
        nc = self._find_nc_character(img)
        x0, y0, fw, fh = self._login_card_box(img)
        login = self._locate_blue_button(
            img,
            min_y=(nc[1] + 8) if nc and nc[1] < y0 + int(fh * 0.55) else y0,
            max_y=y0 + fh)
        if login is None:
            login = self._locate_blue_button(
                img, min_y=y0, max_y=y0 + fh, pick="lowest")
        login_top = login[2] if login is not None else None
        if login is None:
            lx, ly = self._map_form_pt("purple_login", *self.R_LOGIN, img)
            login_cx, login_top = lx, ly
            login_cy = ly
        else:
            login_cx, login_cy, login_top, _bot, _w = login

        hits = self._password_label_hits(img, login_top=None)
        above = [ln for ln in hits
                 if login_top is None or (ln.y + ln.h // 2) < login_top - 6]
        if not above:
            above = [ln for ln in hits
                     if (ln.y + ln.h // 2) < y0 + int(fh * 0.58)]
        if above:
            ln = above[0]
            cx = ln.x + ln.w // 2
            cy = ln.y + max(ln.h // 2, 4)
            log.info("Password OCR %r between NC(%s) and Login(%s) -> (%s,%s)",
                     ln.text, nc[1] if nc else None, login_top, cx, cy)
            return cx, cy, login_top
        if hits:
            log.info("Password OCR only in Reset zone %s; not clicking it",
                     [(ln.text, ln.x, ln.y) for ln in hits])

        nc_bottom = nc[1] if nc else max(40, (login_top or (y0 + fh // 2)) - max(
            40, int(fh * 0.14)))
        nc_cx = nc[0] if nc else login_cx
        if nc and login_top and nc_bottom >= login_top - 8:
            log.info("NC blob (%s) is below Login(%s); ignoring blob for slot",
                     nc_bottom, login_top)
            nc_bottom = max(y0, login_top - max(40, int(fh * 0.14)))
        gap = max(16, int(fh * 0.072))
        min_gap = max(10, int(fh * 0.033))
        cy = login_top - gap if login_top else (nc_bottom + max(12, int(fh * 0.04)))
        cy = min(cy, login_top - min_gap) if login_top else cy
        cy = max(cy, nc_bottom + max(8, int(fh * 0.015)))
        mapped = self._map_form_pt("purple_password", *self.R_PASSWORD, img)
        cx = login_cx if login is not None else nc_cx
        if nc_bottom < mapped[1] < (login_top - min_gap if login_top else 10**9):
            cy = mapped[1]
            cx = mapped[0]
        if login_top and cy >= login_top - 8:
            log.info("no gap between NC(%s) and Login(%s); not clicking Login yet",
                     nc_bottom, login_top)
            return None
        log.info("Password slot below NC(%s) above Login(%s) -> (%s,%s) card_h=%s",
                 nc_bottom, login_top, cx, cy, fh)
        return cx, cy, login_top

    def _click_xy_cef(self, cx: int, cy: int, label: str,
                      use_saved: Optional[bool] = None):
        orig = (int(cx), int(cy))
        cx, cy = self._clamp_client(cx, cy)
        if use_saved is None:
            use_saved = not self._purple_gate_clicks()
        if use_saved:
            mapped = self._resolve_click(
                "purple", label, self.purple, cx, cy, allow_fixed=True)
            if mapped and mapped != (0, 0):
                cx, cy = mapped
        if (cx, cy) == (0, 0) and orig != (0, 0):
            log.warning("refusing (0,0) click for %s; using detected %s",
                        label, orig)
            cx, cy = orig
        cef_x, cef_y = self._cef_point(cx, cy)
        log.info("click %s at (%s,%s) cef=(%s,%s)", label, cx, cy, cef_x, cef_y)
        if not self.dry_run:
            InputRouter.click_cef(self.purple, cef_x, cef_y)
            time.sleep(0.4)
        self._record_click("purple", label, self.purple, cx, cy)
        return cx, cy

    def _click_next_below_id(self, img):
        """Click Next under the ID field — never the lower blue Login button."""
        last = getattr(self, "_last_id_field_xy", None)
        if last is None:
            last = self._map_form_pt("purple_id_field", *self.R_ID, img)
        fx, fy = last
        hits = []
        for ln in self._login_lines(img):
            al = self._alnum(ln.text)
            raw = ln.text or ""
            if any(b in al for b in ("reset", "forgot", "find", "different",
                                     "another", "keepme", "login")):
                continue
            compact = (raw or "").replace(" ", "")
            if any(k in compact for k in ("登录中", "登彔中", "登錄中", "로그인중")):
                continue
            if not (al == "next" or al.startswith("next")
                    or "다음" in raw or "下一步" in raw or "继续" in raw
                    or raw.strip() in ("确认", "確認")):
                continue
            if ln.y + ln.h < fy - 20:
                continue
            hits.append(ln)
        if hits:
            hits.sort(key=lambda ln: (ln.y, abs((ln.x + ln.w // 2) - fx)))
            return self._click_label_cef(hits[0], "Next")
        # Uppermost blue button in a short band under the ID field (Next).
        # Band is a fraction of the login card, so it does not reach Login
        # when the window is 962x670 or 1920x1040.
        _x0, _y0, _fw, fh = self._login_card_box(img)
        btn = self._locate_blue_button(
            img,
            min_y=fy + max(4, int(0.01 * fh)),
            max_y=fy + max(14, int(0.036 * fh)),
            pick="highest")
        if btn is not None:
            cx, cy, _t, _b, _w = btn
            return self._click_xy_cef(cx, cy, "Next (blue)")
        nx, ny = self._map_form_pt("purple_next", *self.R_NEXT, img)
        # Keep Next below the ID field, but do not clamp into a ~30px band
        # that sits on the input (live miss: 341 vs real Next 388).
        ny = max(ny, fy + max(24, int(0.05 * fh)))
        return self._click_xy_cef(nx if abs(nx - fx) < _fw * 0.25 else fx, ny,
                                 "Next fallback")

    def _on_login_method_screen(self, img) -> bool:
        """True on the stacked ID/E-mail Address | Phone | QR screen,
        before the 'ID or E-mail' input is visible."""
        if self._find_login_label(img, self._is_id_or_email_placeholder):
            return False
        if self._password_label_hits(img):
            return False
        if self._find_login_label(img, self._is_address_tab):
            return True
        lines = self._login_lines(img)
        for ln in lines:
            if ln.y < 60:
                continue
            lt = normalize(ln.text)
            if any(k in lt for k in ("phone", "휴대폰", "手机号", "qr")):
                return True
        return False

    def _login_error_on_screen(self, img) -> bool:
        """Detect a login failure message on the Purple form, e.g.
        'Username or password is incorrect.' (OCR: 'iSusername or password
        iS incorrect.'). The error text is small, so OCR the image upscaled."""
        from PIL import Image as _Image
        if img.width < 600:
            img = img.resize((img.width * 2, img.height * 2), _Image.LANCZOS)
        for ln in self.ocr.recognize(img):
            lt = normalize(ln.text)
            for kw in ("incorrect", "wrong", "잘못", "오류", "실패", "notvalid"):
                if kw in lt:
                    log.info(f"login error text detected: {ln.text!r}")
                    return True
        return False

    def _on_account_login_screen(self, img) -> bool:
        """Detect the password-entry step. It shows a Login/Log in button AND
        an account header like 'Log in with jamesnelson31...' containing our
        email prefix (OCR truncates the '@gmail.com' part)."""
        if not self.username:
            return False
        lines = self.ocr.recognize(img)
        user_prefix = self.username.split("@")[0][:8].lower()

        def has(*words):
            return any(
                normalize(w) in normalize(ln.text)
                for w in words for ln in lines
            )

        if not has("Login", "로그인", "Log in", "Sign in"):
            return False
        return any(user_prefix in normalize(ln.text) for ln in lines)

    def _click_login_method(self, img, method: str):
        """Click a login-method option ('email', 'phone', 'qr')."""
        method_keywords = {
            "email": ["用户名/电子邮箱", "用户名", "电子邮箱",
                      "id/e-mail", "ld/e-mail", "1d/e-mail",
                      "id/email", "ld/email", "1d/email",
                      "id e-mail", "idemail", "ldeemail", "1demail", "ide-mail",
                      "email", "e-mail", "email address", "이메일", "아이디/이메일"],
            "phone": ["phone", "휴대폰", "手机号"],
            "qr": ["qr", "QR코드", "QR"],
        }
        keywords = method_keywords.get(method, [])
        # Fallback for OCR misreading English: "in with" survives as "inwith"
        # even when "Log" is misread as "L09". Filter by other keywords on the
        # same line to distinguish between options.
        exclude_keywords = {
            "email": ["phone", "qr", "휴대폰", "number", "手机号"],
            "phone": ["email", "qr", "이메일"],
            "qr": ["email", "phone", "이메일"],
        }
        excludes = exclude_keywords.get(method, [])
        chrome = ("different", "another", "keepme", "join")
        scored = []
        keywords = self._username_email_keywords()
        for ln in self._login_lines(img):
            lt = self._alnum(ln.text)
            if any(w in lt for w in chrome):
                continue
            matched = fuzzy_match_label(ln.text, keywords,
                                        fuzzy=self.PURPLE_LABEL_FUZZY)
            if matched:
                score = 6 if "用户名" in label_normalize(ln.text) else 4
                scored.append((score, -ln.y, ln))
                continue
            if any(self._alnum(kw) in lt for kw in keywords):
                pass
            elif "inwith" in lt and not any(self._alnum(ex) in lt for ex in excludes):
                pass
            else:
                continue
            score = 1
            if method == "email" and ("address" in lt or "adress" in lt):
                score = 5
            scored.append((score, -ln.y, ln))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if not scored:
            return False
        _score, _y, ln = scored[0]
        cx = ln.x + ln.w // 2
        cy = ln.y + ln.h // 2
        self._click_xy_cef(cx, cy, self.LABEL_USERNAME_EMAIL)
        return True

    def _click_field_near_label(self, img, keywords, fallback, exclude=()):
        """Click just below an OCR label (e.g. 'ID Or E-mail') to focus its
        input field. Returns the client coords clicked, or fallback coords.
        Uses fuzzy line matching because OCR often misreads the label (e.g.
        'ID Or E-mail' -> '[D Or E-mail'). Routes the click to the CEF child
        since the form content is Chromium-rendered."""
        hits = None
        img_used = img
        for _attempt in range(3):
            if _attempt:
                # The form animates for a couple of seconds after opening; a
                # first snap often misses the label. Retry on a fresh frame.
                time.sleep(0.6)
                img_used = self.purple.capture_content()
                if img_used is None:
                    continue
            hits = self.ocr.find_lines(img_used, keywords,
                                       fuzzy=self.PURPLE_LABEL_FUZZY)
            if not hits and self.rapid_ocr is not None:
                hits = self.rapid_ocr.find_lines(
                    img_used, keywords, fuzzy=self.PURPLE_LABEL_FUZZY)
            if hits:
                break
        if hits:
            # Skip lines containing an excluded word (e.g. "reset" for
            # password matching, to ignore the "Reset Password" link).
            hits = [h for h in hits if not any(
                normalize(x) in normalize(h[1].text) for x in exclude
            )]
            # Prefer the topmost label: a field's label sits above its input,
            # and substring matching can otherwise grab a lower link (e.g.
            # "Password" inside "Find ACCOunt7 Reset Password").
            hits.sort(key=lambda t: t[1].y)
            label = hits[0][1] if hits else None
        else:
            label = None
        if label is None:
            # Last-resort: any line that looks like an email/ID field hint.
            # Only matches lines near the top-left (label area), not login-method
            # options like "Log in with an email" which appear as a menu item.
            # Error/hint footers ("Invalid e-mail format.", "Check", "reset",
            # "if you are using...") are explicitly rejected so we never click
            # into an error message thinking it's a field label.
            _skip = ("invalid", "format", "check", "reset", "find", "ifyouare",
                     "if you are", "protected", "recaptcha", "terms", "sign up",
                     "another", "account status", "please check")
            for ln in self.ocr.recognize(img_used):
                lt = normalize(ln.text)
                if any(s in lt for s in _skip):
                    continue
                if "e-mail" in lt or "email" in lt or "id" == lt or "account" in lt \
                        or "用户名" in lt or "电子邮箱" in lt:
                    # Skip lines that look like login-method menu options
                    # ("Log in with an email", "Log in with a phone number").
                    # OCR may misread "Log" as "L09", so check for "inwith"
                    # which survives normalize and OCR errors.
                    if "inwith" in lt:
                        continue
                    if self.purple.rect.width < 700:
                        fw = max(self.purple.rect.width, 1)
                        fh = max(self.purple.rect.height, 1)
                        if ln.x > fw * 0.55 or ln.y > fh * 0.45:
                            continue
                    label = ln
                    break
        if label:
            cx = label.x + label.w // 2
            cy = label.y + max(label.h // 2, 4)
            log.info(f"label {label.text!r} at ({label.x},{label.y}) -> click ({cx},{cy})")
        else:
            cx, cy = fallback
            log.info(f"no label match, using fallback field ({cx},{cy})")
        cx, cy = self._clamp_client(cx, cy)
        cef_x, cef_y = self._cef_point(cx, cy)
        if self.dry_run:
            log.info(f"[dry-run] would click field at CEF ({cef_x},{cef_y})")
            return cx, cy
        InputRouter.click_cef(self.purple, cef_x, cef_y)
        time.sleep(0.4)
        self._last_id_field_xy = (cx, cy)
        self._record_click("purple", self.LABEL_USERNAME_EMAIL, self.purple, cx, cy)
        return cx, cy

    def _paste_once(self, text: str, kind: str):
        """Select-all then paste once. A second call is ignored.

        Two bot processes used to both paste, and Ctrl+V without select-all
        appended a second copy of the email/password.
        """
        flag = "_email_entered" if kind == "email" else "_password_entered"
        if getattr(self, flag, False):
            log.info("skip %s paste; already entered", kind)
            return False
        if not text:
            return False
        setattr(self, flag, True)
        if self.dry_run:
            log.info("[dry-run] would paste %s once", kind)
            return True
        InputRouter.select_all_cef(self.purple)
        pause = 0.04 if getattr(self, "positions", None) and self.positions.is_fixed_purple else 0.08
        time.sleep(pause)
        InputRouter.type_cef(self.purple, text)
        time.sleep(0.12 if pause < 0.06 else 0.25)
        log.info("%s pasted once", "userID" if kind == "email" else "password")
        return True

    def _field_contains(self, img, probe) -> bool:
        """Check whether the on-screen text now contains our typed value."""
        for ln in self.ocr.recognize(img):
            if probe.lower() in ln.text.lower():
                return True
        return False

    def _enter_combined_login(self) -> None:
        """Fill email + password + Login on one Purple page.

        Taiwan/HK main-shell login shows both fields and 登錄 together.
        OCR is often empty there, so use template then saved 1642x1026 ratios.
        """
        if not self.purple or not self.purple.valid:
            return
        if self._password_entered:
            self._wait_for_login_result()
            return
        try:
            self._normalize_purple_shell_size(reason="combined_login")
        except Exception:
            pass
        seed = os.path.join(self._login_template_dir(), "username_email.png")
        focused = False
        if os.path.isfile(seed):
            focused = self._template_click_login("purple_id_field", cef=True)
        if not focused:
            focused = self._try_fixed_click(
                "purple", "purple_id_field", self.purple, cef=True)
        if not focused:
            log.warning("combined login: email field miss")
            return
        self._paste_once(self.username, "email")
        time.sleep(0.2)
        pw = self._template_click_login("purple_password", cef=True) \
            if os.path.isfile(os.path.join(self._login_template_dir(), "password.png")) \
            else False
        if not pw:
            pw = self._try_fixed_click(
                "purple", "purple_password", self.purple, cef=True)
        if not pw:
            log.warning("combined login: password field miss")
            return
        self._paste_once(self.password, "password")
        time.sleep(0.25)
        login = self._template_click_login("purple_login", cef=True) \
            if os.path.isfile(os.path.join(self._login_template_dir(), "login.png")) \
            else False
        if not login:
            login = self._try_fixed_click(
                "purple", "purple_login", self.purple, cef=True)
        if not login:
            log.warning("combined login: login button miss")
            return
        log.info("combined login: credentials submitted")
        self._wait_for_login_result()

    def _enter_password_and_login(self):
        """Click Password (between NC character and Login), paste, then Login.

        Same path as the 10:56 successful login: OCR slot -> paste once ->
        blue Login. Dynamic mode only records the click after it happens.
        """
        pw_img = self.purple.capture_content()
        if pw_img is None:
            return
        slot = self._password_slot_between_nc_and_login(pw_img)
        if slot is None:
            log.info("Password not between NC character and Login; not clicking Login")
            return
        cx, cy, login_top = slot
        self._click_xy_cef(cx, cy, "Password")
        time.sleep(0.25)
        self._paste_once(self.password, "password")
        time.sleep(0.35)
        log.info("now clicking blue Login")

        login_img = self.purple.capture_content()
        if login_img is None:
            return
        min_y = (login_top - 4) if login_top else (cy + 20)
        if self._click_blue_button(login_img, min_y=min_y):
            time.sleep(0.5)
            self._wait_for_login_result()
            return
        login_hits = self.find_words(
            self.purple,
            ["로그인", "Login", "Log in"],
            exact=False,
            game=False,
        )
        if login_hits:
            login_hits = [h for h in login_hits
                          if "different" not in normalize(h[1].text)
                          and "another" not in normalize(h[1].text)
                          and "sign" not in self._alnum(h[1].text)
                          and "inwith" not in self._alnum(h[1].text)
                          and (h[1].y + h[1].h // 2) >= min_y]
        if login_hits:
            login_hits.sort(key=lambda t: t[1].y)
            _, word = login_hits[0]
            self._click_xy_cef(word.x + word.w // 2, word.y + word.h // 2,
                               "Login")
            time.sleep(0.5)
            self._wait_for_login_result()
            return
        log.warning("blue Login not found after password; will retry next tick")
        self._password_entered = False

    def _wait_for_login_result(self):
        """After submitting login, wait for the main Purple launcher. Detect a
        rejected login (e.g. 'Username or password is incorrect.') and report
        it instead of timing out silently."""
        from purple_state import PurpleScreen, LAUNCHER_SCREENS
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.find_main_launcher():
                view = self._read_purple_view(force=True)
                if view.screen in LAUNCHER_SCREENS:
                    log.info("main Purple launcher ready after login: %sx%s (%s)",
                             self.purple.rect.width, self.purple.rect.height,
                             view.screen.value)
                    self._mark_purple_logged_in()
                    self._set_phase(Phase.WAIT_MAIN)
                    return
                if view.screen == PurpleScreen.LOGGING_IN:
                    log.info("Purple still logging in; waiting for main launcher")
                elif view.screen in (
                        PurpleScreen.LOGIN_EMAIL, PurpleScreen.LOGIN_PASSWORD):
                    log.info("wide window is still the login form (%sx%s); waiting",
                             self.purple.rect.width, self.purple.rect.height)
                elif view.screen == PurpleScreen.LOGIN_ERROR:
                    log.error("login rejected by Purple: username or password "
                              "incorrect (check purple_login.json)")
                    self._set_phase(Phase.ERROR)
                    return
                else:
                    log.info("post-login screen=%s; waiting for launcher markers",
                             view.screen.value)
            if self.purple and self.purple.valid:
                err_img = self.purple.capture_content()
                if err_img is not None:
                    log.debug("checking login error on window %sx%s",
                              self.purple.rect.width, self.purple.rect.height)
                    if self._login_error_on_screen(err_img):
                        log.error("login rejected by Purple: username or password "
                                  "incorrect (check purple_login.json)")
                        self._set_phase(Phase.ERROR)
                        return
            if int(time.time()) % 20 == 0:
                self.debug_enumerate_purple_windows()
            time.sleep(0.3)
        view = self._read_purple_view(force=True)
        if view.screen in LAUNCHER_SCREENS:
            log.warning("launcher detected at timeout; proceeding to Lineage find")
            self._mark_purple_logged_in()
            self._set_phase(Phase.FIND_LINEAGE)
            return
        log.warning("main launcher not confirmed after Purple login "
                    "(screen=%s) — not marking logged-in", view.screen.value)
        self._password_entered = False
        self._set_phase(Phase.WAIT_LOGIN_FORM)

    def _fixed_purple_login(self):
        """Drive Purple credentials one confirmed screen at a time.

        Never paste the password until LOGIN_PASSWORD is visible. Saved
        ratios are last-resort locate after the screen is classified.
        """
        from purple_state import PurpleScreen, LOGIN_SCREENS, LAUNCHER_SCREENS
        view = self._read_purple_view(force=True)
        if view.screen == PurpleScreen.LOGGING_IN:
            self._wait_for_login_result()
            return
        if view.screen in LAUNCHER_SCREENS:
            self._mark_purple_logged_in()
            self._set_phase(Phase.FIND_LINEAGE)
            return
        if view.screen == PurpleScreen.LOGIN_ERROR:
            log.error("Purple login error on screen")
            self._set_phase(Phase.ERROR)
            return
        if view.screen == PurpleScreen.UNKNOWN:
            game_up = False
            alive = getattr(self, "_game_process_alive", None)
            if callable(alive):
                try:
                    game_up = bool(alive())
                except Exception:
                    game_up = False
            if not game_up:
                log.info("fixed login: unclassified + LC down — combined login")
                self._enter_combined_login()
                return
            log.info("fixed login: screen unknown — wait (no click)")
            return
        if view.screen == PurpleScreen.LOGIN_EMAIL:
            if self._password_entered:
                self._password_entered = False
            if not self._email_entered:
                self._enter_email_then_next()
            else:
                nxt = self._wait_purple_screens(
                    (PurpleScreen.LOGIN_PASSWORD, PurpleScreen.LOGGING_IN)
                    + LAUNCHER_SCREENS,
                    timeout=4.0)
                if nxt.screen == PurpleScreen.LOGIN_EMAIL:
                    log.warning("gated: email entered but still LOGIN_EMAIL — retry Next")
                    self._email_entered = False
            return
        if view.screen == PurpleScreen.LOGIN_PASSWORD:
            if self._password_entered:
                self._wait_for_login_result()
                return
            if not self._gated_purple_click(
                    "purple_password",
                    expected=(PurpleScreen.LOGIN_PASSWORD,), cef=True):
                log.warning("gated: purple_password miss; using detection")
                self._enter_password_and_login()
                return
            self._paste_once(self.password, "password")
            self._gated_purple_click("purple_login",
                                     expected=(PurpleScreen.LOGIN_PASSWORD,),
                                     cef=True)
            log.info("gated: password pasted, Login clicked")
            after = self._wait_purple_screens(
                (PurpleScreen.LOGGING_IN,) + LAUNCHER_SCREENS,
                timeout=5.0)
            if after.screen in LAUNCHER_SCREENS:
                self._mark_purple_logged_in()
                self._set_phase(Phase.WAIT_MAIN)
                return
            self._wait_for_login_result()
            return
        log.info("fixed login: unhandled screen=%s", view.screen.value)

    def do_enter_credentials(self):
        if not self.purple or not self.purple.valid:
            self._goto_purple_phase()
            return
        if not self.username:
            log.error("no username configured")
            self._set_phase(Phase.ERROR)
            return
        if self._password_entered:
            self._wait_for_login_result()
            return

        store = getattr(self, "positions", None)
        self._maybe_fallback_purple_dynamic(reason="enter_credentials")
        if store and store.is_fixed_purple and store.lookup("purple", "purple_id_field"):
            self._normalize_purple_shell_size(reason="fixed_login")
            if self.purple.rect.width < 900:
                log.info("fixed login waiting for main Purple shell (>=900px wide, "
                         "got %dx%d)", self.purple.rect.width, self.purple.rect.height)
                if self._try_attach_running_purple():
                    return
                if self._purple_process_running() or self._any_purple_window_exists():
                    return
                self._goto_purple_phase()
                return
            self._arm_purple_fixed_watch()
            self._fixed_purple_login()
            return

        img = self.purple.capture_content()
        if img is None:
            return

        # First step: template-match Address / email / Next. Never OCR labels.
        if not self._email_entered:
            self._enter_email_then_next()
            return

        # 3. Password is below the NC character and above the blue Login.
        if store and store.is_fixed_purple and store.lookup("purple", "purple_password"):
            self._enter_password_and_login()
            return
        if not self._on_password_form(img):
            blob = " | ".join(ln.text for ln in self._login_lines(img)[:18])
            if self._logging_in_screen(blob=blob):
                log.info("Logging-in overlay; waiting for main launcher")
                self._password_entered = True
                self._wait_for_login_result()
                return
            self._retry_email_before_next(
                "password form not up yet (ocr=%r)" % blob)
            return
        slot = self._password_slot_between_nc_and_login(img)
        if slot is None:
            blob = " | ".join(ln.text for ln in self._login_lines(img)[:18])
            if self._logging_in_screen(blob=blob):
                log.info("Logging-in overlay; waiting for main launcher")
                self._password_entered = True
                self._wait_for_login_result()
                return
            self._retry_email_before_next(
                "no Password slot between NC and Login (ocr=%r)" % blob)
            return
        self._next_retries = 0
        self._enter_password_and_login()

    def _ratio(self, rx: float, ry: float) -> Tuple[int, int]:
        rect = self.purple.client_rect
        return int(rect.width * rx), int(rect.height * ry)

    def click_login_button(self) -> bool:
        hits = self.find_words(
            self.purple,
            self._cfg_words("login", ["로그인", "Login", "Log in", "Sign in", "다음", "Next"]),
        )
        if hits:
            _w, word = hits[0]
            self.click_word(self.purple, word, "center", label="login")
            return True
        # ratio fallback (recorded login button on the login card)
        cx, cy = self._map_form_pt("purple_login", *self.R_LOGIN)
        cx, cy = self._resolve_click("purple", "login", self.purple, cx, cy)
        if self.dry_run:
            log.info(f"[dry-run] would click login fallback at client ({cx},{cy})")
            return True
        InputRouter.click_client(self.purple, cx, cy)
        log.info(f"clicked login fallback at client ({cx},{cy})")
        self._record_click("purple", "login", self.purple, cx, cy)
        return True

    def do_wait_main(self):
        from purple_state import PurpleScreen, LOGIN_SCREENS, LAUNCHER_SCREENS
        if not self.purple or not self.purple.valid:
            self._goto_purple_phase()
            return
        rect = self.purple.rect
        if rect.width >= 900:
            view = self._read_purple_view(force=True)
            if view.screen in LOGIN_SCREENS:
                self._password_entered = False
                self._set_phase(Phase.WAIT_LOGIN_FORM)
                return
            if view.screen == PurpleScreen.LOGGING_IN:
                return
            if view.screen in LAUNCHER_SCREENS:
                log.info("main launcher ready (%s)", view.screen.value)
                self._mark_purple_logged_in()
                self._set_phase(Phase.FIND_LINEAGE)
                return
            log.info("WAIT_MAIN screen=%s — waiting for launcher markers",
                     view.screen.value)
            return
        if time.time() - self.phase_start > 90:
            log.warning("timeout waiting for main launcher")
            self._set_phase(Phase.ERROR)

    def _launcher_toast_hits(self):
        """Strict profile/promo toast hits — never use fuzzy=0 (matches all)."""
        if not self.purple or not self.purple.valid:
            return []
        try:
            # Require real substring / high fuzzy — fuzzy=0.0 accepts every line.
            hits = self.find_lines(
                self.purple,
                ["profile", "proflle", "set your profile", "set your"],
                exact=False, fuzzy=0.78)
        except Exception:
            return []
        out = []
        w = self.purple.rect.width
        for item in hits:
            ln = item[1] if isinstance(item, tuple) else item
            text = (getattr(ln, "text", "") or "").lower()
            # Reject OCR garbage / unrelated UI (e.g. "Publish")
            if not any(k in text for k in ("profile", "proflle", "set your")):
                continue
            if ln.y < 80:
                continue  # title-bar chrome
            if ln.x <= w * 0.55:
                continue  # toast sits on the right
            out.append(ln)
        return out

    def has_launcher_toast(self) -> bool:
        """True when a profile/promo toast sits over the card area."""
        return bool(self._launcher_toast_hits())

    def dismiss_launcher_toast(self) -> bool:
        """Close Purple popups/toasts that cover the game card."""
        hits = self._launcher_toast_hits()
        for ln in hits:
            pad = max(20, int(self.purple.rect.width * 0.05))
            cx = ln.x + ln.w + pad
            cy = ln.y + ln.h // 2
            InputRouter.click_client(self.purple, cx, cy)
            log.info(f"Dismissed launcher toast '{ln.text}' at ({cx},{cy})")
            time.sleep(0.3)
            return True
        return False

    def _lineage_nav_pause(self) -> float:
        return float(self.cfg.get("lineage_nav_pause_sec", LINEAGE_NAV_PAUSE_SEC))

    def _lineage_card_pause(self) -> float:
        return float(self.cfg.get("lineage_card_pause_sec", LINEAGE_CARD_PAUSE_SEC))

    def _mark_lineage_nav_clicked(self):
        self._lineage_nav_clicked = 1
        self._lineage_nav_at = time.time()

    def _wait_before_lineage_card_template(self) -> None:
        """Purple redraws the game grid after the left-nav click; template
        match on a stale/partial view misses the card. Never use fixed
        purple coords here — launcher chrome is too noisy."""
        nav_at = getattr(self, "_lineage_nav_at", 0.0)
        if nav_at <= 0:
            return
        settle = float(self.cfg.get("lineage_card_settle_sec",
                                    LINEAGE_CARD_SETTLE_SEC))
        elapsed = time.time() - nav_at
        if elapsed >= settle:
            return
        wait = settle - elapsed
        log.info("Lineage Classic: waiting %.1fs for launcher to settle "
                 "before template match", wait)
        time.sleep(wait)

    def _try_lineage_nav(self) -> bool:
        """Click 'Lineage' in the Purple left sidebar once.

        Template / OCR first; saved ratio only after launcher is confirmed.
        """
        from purple_state import LAUNCHER_SCREENS
        if getattr(self, "_lineage_nav_clicked", 0) >= 1:
            return False
        pause = self._lineage_nav_pause()
        if self._gated_purple_click("purple_lineage", expected=LAUNCHER_SCREENS,
                                   allow_fixed=False):
            self._mark_lineage_nav_clicked()
            time.sleep(pause)
            return True
        nav_words = self._lineage_nav_keywords()
        # Prefer line-level OCR: left sidebar often shows a single "Lineage" label.
        line_hits = self.find_lines(self.purple, nav_words,
                                    fuzzy=self.PURPLE_LABEL_FUZZY)
        left_lines = [(qw, ln) for qw, ln in line_hits
                      if self._is_left_nav_rect(ln.x, ln.y, ln.w, ln.h)]
        if left_lines:
            def _nav_score(item):
                qw, ln = item
                al = self._alnum(ln.text)
                score = 0
                if al == "lineage" or qw.lower() == "lineage":
                    score += 100
                if "lineage" in al and "classic" not in al:
                    score += 50
                if "classic" in al:
                    score += 10
                return (score, -ln.y)
            left_lines.sort(key=_nav_score, reverse=True)
            qw, line = left_lines[0]
            self.click_line(self.purple, line, "center",
                            label=self.LABEL_LINEAGE_NAV)
            self._mark_lineage_nav_clicked()
            log.info("Lineage nav clicked (left OCR %r)", line.text)
            time.sleep(pause)
            return True
        hits = self.find_words(self.purple, nav_words,
                                fuzzy=self.PURPLE_LABEL_FUZZY)
        left_hits = [h for h in hits
                     if self._is_left_nav_rect(h[1].x, h[1].y, h[1].w, h[1].h)]
        if left_hits:
            def _word_score(item):
                _qw, word = item
                al = self._alnum(word.text)
                score = 100 if al == "lineage" else (50 if "lineage" in al else 0)
                return (score, -word.y)
            left_hits.sort(key=_word_score, reverse=True)
            _qw, word = left_hits[0]
            self.click_word(self.purple, word, "center",
                            label=self.LABEL_LINEAGE_NAV)
            self._mark_lineage_nav_clicked()
            log.info("Lineage nav clicked (left word OCR %r)", word.text)
            time.sleep(pause)
            return True
        view = self._read_purple_view()
        if view.screen in LAUNCHER_SCREENS:
            log.info("Lineage nav OCR miss; clicking left sidebar ratio")
            if self._click_left_lineage_nav():
                self._mark_lineage_nav_clicked()
                time.sleep(pause)
                return True
        else:
            log.info("Lineage nav skipped: screen=%s", view.screen.value)
        return False

    def _lineage_card_template_path(self) -> str:
        custom = self.cfg.get("lineage_card_template") or ""
        if custom and os.path.exists(custom):
            return custom
        return str(LINEAGE_CARD_TM)

    def _load_lineage_card_template(self):
        """Load the Lineage Classic tile PNG once (BGR for cv2)."""
        cached = getattr(self, "_lineage_card_tpl", None)
        if cached is not False and cached is not None:
            return cached
        if cached is False:
            return None
        try:
            import cv2
        except ImportError:
            log.warning("cv2 unavailable; Lineage Classic template match disabled")
            self._lineage_card_tpl = False
            return None
        path = self._lineage_card_template_path()
        if not os.path.exists(path):
            log.warning("Lineage Classic template missing: %s", path)
            self._lineage_card_tpl = False
            return None
        tpl = cv2.imread(path)
        if tpl is None:
            log.warning("Lineage Classic template unreadable: %s", path)
            self._lineage_card_tpl = False
            return None
        self._lineage_card_tpl = tpl
        log.info("Lineage Classic template loaded (%dx%d) from %s",
                 tpl.shape[1], tpl.shape[0], path)
        return tpl

    def _purple_capture_bgr(self, win: Optional[WinWindow] = None):
        """PrintWindow capture of Purple as OpenCV BGR."""
        win = win or self.purple
        if not win:
            return None
        img = win.capture_content()
        if img is None:
            return None
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None
        arr = np.array(img.convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def _match_lineage_card_template(self, img) -> Optional[dict]:
        """Multi-scale template match for the Lineage Classic game tile."""
        tpl = self._load_lineage_card_template()
        if tpl is None or img is None:
            return None
        try:
            import cv2
        except ImportError:
            return None
        h, w = img.shape[:2]
        x0 = int(w * 0.12)
        y0 = int(h * 0.08)
        roi = img[y0:, x0:]
        base_h = h / PURPLE_REF_H
        base_w = w / PURPLE_REF_W
        cands = {round(base_h * m, 4) for m in LINEAGE_CARD_SCALE_SWEEP}
        cands |= {round(base_w * m, 4) for m in LINEAGE_CARD_SCALE_SWEEP}
        cands.add(1.0)
        best = None
        for s in sorted(cands):
            if s <= 0.05:
                continue
            t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            th, tw = t.shape[:2]
            if th < 8 or tw < 8 or th >= roi.shape[0] or tw >= roi.shape[1]:
                continue
            res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if best is None or mv > best[0]:
                best = (mv, ml, tw, th, s)
        thresh = float(self.cfg.get("lineage_card_tm_thresh",
                                    LINEAGE_CARD_TM_THRESH))
        if best and best[0] >= thresh:
            mx, my = best[1][0] + x0, best[1][1] + y0
            tw, th = best[2], best[3]
            return {"score": float(best[0]), "cx": mx + tw // 2,
                    "cy": my + th // 2, "scale": best[4],
                    "x": mx, "y": my, "w": tw, "h": th}
        if best:
            log.info("Lineage Classic template best=%.3f below thresh=%.2f",
                     best[0], thresh)
        return None

    def _try_click_lineage_card_template(self) -> bool:
        """Click the Lineage Classic tile via OpenCV template matching."""
        if not self.purple:
            return False
        self._wait_before_lineage_card_template()
        img = self._purple_capture_bgr()
        if img is None:
            return False
        m = self._match_lineage_card_template(img)
        if not m:
            return False
        cx, cy = m["cx"], m["cy"]
        label = self.LABEL_LINEAGE_CARD
        cx, cy = self._resolve_click(
            "purple", label, self.purple, cx, cy, allow_fixed=False)
        if self.dry_run:
            log.info("[dry-run] would click %s (template score=%.3f at (%d,%d))",
                     label, m["score"], cx, cy)
            return True
        InputRouter.click_client(self.purple, cx, cy)
        log.info("%s clicked (template match score=%.3f scale=%.3f at (%d,%d))",
                 label, m["score"], m["scale"], cx, cy)
        self._record_click("purple", label, self.purple, cx, cy)
        return True

    def _try_click_lineage_card(self) -> bool:
        """Select the Lineage Classic game card.

        Order: template → OCR → gated fixed (vision first; coords last).
        """
        from purple_state import LAUNCHER_SCREENS
        if self._try_click_lineage_card_template():
            return True
        card_words = self._lineage_card_keywords()
        line_hits = self.find_lines(self.purple, card_words,
                                    fuzzy=self.PURPLE_LABEL_FUZZY)
        if line_hits:
            scored = []
            for _qw, line in line_hits:
                score = line.h
                if self._text_matches_lineage_card(line.text):
                    score += 100
                if line.y > 120 and line.x > self.purple.rect.width * 0.15:
                    score += 50
                scored.append((score, line))
            scored.sort(key=lambda t: -t[0])
            line = scored[0][1]
            self.click_line(self.purple, line, "center",
                            label=self.LABEL_LINEAGE_CARD)
            log.info("%s clicked (OCR %r)", self.LABEL_LINEAGE_CARD, line.text)
            return True
        hits = self.find_words(self.purple, card_words,
                               fuzzy=self.PURPLE_LABEL_FUZZY)
        if hits:
            hits = [h for h in hits
                    if h[1].y > 100
                    and h[1].x > self.purple.rect.width * 0.12]
            if hits:
                hits.sort(key=lambda t: (-t[1].h, -t[1].y))
                _w, word = hits[0]
                self.click_word(self.purple, word, "center",
                                  label=self.LABEL_LINEAGE_CARD)
                log.info("%s clicked (word OCR %r)", self.LABEL_LINEAGE_CARD,
                         word.text)
                return True
        if self._gated_purple_click("purple_lineage_card",
                                    expected=LAUNCHER_SCREENS):
            log.info("%s clicked (gated ratio)", self.LABEL_LINEAGE_CARD)
            return True
        return False

    def _try_click_run_game(self) -> bool:
        """Click 运行游戏 / Start Game: template → OCR → gated ratio.

        Never fire the saved Start ratio unless START_READY is confirmed.
        """
        from purple_state import PurpleScreen
        view = self._read_purple_view()
        if view.screen == PurpleScreen.START_READY:
            if self._gated_purple_click(
                    "purple_start_game",
                    expected=(PurpleScreen.START_READY,)):
                log.info("%s clicked (gated) -> waiting for game",
                         self.LABEL_RUN_GAME)
                return True
        elif view.screen != PurpleScreen.LAUNCHER:
            log.info("Start Game skipped: screen=%s", view.screen.value)
            return False
        run_words = self._run_game_keywords()
        line_hits = self.find_lines(self.purple, run_words,
                                    fuzzy=self.PURPLE_LABEL_FUZZY)
        if line_hits:
            _qw, line = line_hits[0]
            self.click_line(self.purple, line, "center",
                            label=self.LABEL_RUN_GAME)
            log.info("%s clicked -> waiting for game", self.LABEL_RUN_GAME)
            return True
        hits = self.find_words(self.purple, run_words,
                               fuzzy=self.PURPLE_LABEL_FUZZY)
        if hits:
            _w, word = hits[0]
            self.click_word(self.purple, word, "center", label=self.LABEL_RUN_GAME)
            log.info("%s clicked -> waiting for game", self.LABEL_RUN_GAME)
            return True
        return False

    def do_find_lineage(self):
        if not self.purple or not self.purple.valid:
            if self._try_attach_running_purple():
                log.info("FIND_LINEAGE: reattached to running Purple window")
                decision = self._classify_attached_purple()
                if decision == "WAIT_LOGIN_FORM":
                    self._purple_logged_in = False
                    self._set_phase(Phase.WAIT_LOGIN_FORM)
                    return
                if decision == "FIND_LINEAGE":
                    self._mark_purple_logged_in()
                else:
                    log.info("FIND_LINEAGE: reattached but screen undetermined")
                    return
            elif self._purple_process_running() or self._any_purple_window_exists():
                log.info("FIND_LINEAGE: Purple running; waiting to reattach")
                return
            else:
                self._goto_purple_phase()
                return
        # Clicks on a non-visible shell hit whatever is underneath (Cursor,
        # desktop) — restore before nav/card/Start.
        if not self._ensure_purple_visible():
            log.warning("FIND_LINEAGE: Purple not visible; deferring clicks")
            return
        self._maybe_fallback_purple_dynamic(reason="find_lineage")
        # If game process is already running, skip launcher and wait for window
        if self._game_process_alive():
            log.info("game process already running; transitioning to WAIT_GAME")
            self._set_phase(Phase.WAIT_GAME)
            return
        # Guard: a tiny window means it got collapsed/minimized; restore it.
        rect = self.purple.rect
        if rect.width < 400 or rect.height < 400:
            log.warning(f"launcher window tiny ({rect.width}x{rect.height}), restoring")
            self._ensure_purple_visible()
            time.sleep(0.4)
            rect = self.purple.rect
            if rect.width < 400 or rect.height < 400:
                if self._try_attach_running_purple():
                    return
                log.info("FIND_LINEAGE: Purple running; waiting for window restore")
                return
        if not hasattr(self, "_lineage_nav_clicked"):
            self._lineage_nav_clicked = 0
        if not hasattr(self, "_lineage_card_clicked"):
            self._lineage_card_clicked = False
        from purple_state import PurpleScreen, LOGIN_SCREENS, LAUNCHER_SCREENS
        view = self._read_purple_view(force=True)
        if view.blob and getattr(self, "_last_launch_view", None) != view.blob:
            log.info("[launcher] view: %r", view.blob[:400])
            self._last_launch_view = view.blob
        if view.screen in LOGIN_SCREENS:
            log.info("FIND_LINEAGE saw %s; switching to credentials",
                     view.screen.value)
            self._password_entered = False
            self._purple_logged_in = False
            self._set_phase(Phase.WAIT_LOGIN_FORM)
            return
        if view.screen == PurpleScreen.LOGGING_IN:
            log.info("FIND_LINEAGE: still logging in — wait")
            return
        if view.screen == PurpleScreen.UNKNOWN:
            log.info("FIND_LINEAGE: screen unknown — wait (no click)")
            return
        if self.dismiss_launcher_toast():
            self._purple_watcher().invalidate()
            return
        # 1) Start already visible → click it.
        if view.screen == PurpleScreen.START_READY:
            if self._try_click_run_game():
                self._game_proc_seen = False
                self._game_proc_logged = False
                self._set_phase(Phase.WAIT_GAME)
                return
        # 2) Launcher home: nav → card → wait for Start.
        if view.screen in LAUNCHER_SCREENS:
            self._try_lineage_nav()
            if not getattr(self, "_lineage_card_clicked", False):
                if getattr(self, "_lineage_nav_clicked", 0) >= 1:
                    attempts = getattr(self, "_lineage_card_attempts", 0)
                    if attempts < 8:
                        self._lineage_card_attempts = attempts + 1
                        if self._try_click_lineage_card():
                            self._lineage_card_clicked = True
                            time.sleep(self._lineage_card_pause())
                            ready = self._wait_purple_screens(
                                (PurpleScreen.START_READY,), timeout=3.5)
                            if ready.screen != PurpleScreen.START_READY:
                                log.info("card clicked but Start not confirmed yet")
                                return
                        else:
                            return
            if (getattr(self, "_lineage_card_clicked", False)
                    or view.screen == PurpleScreen.START_READY):
                if self._try_click_run_game():
                    self._game_proc_seen = False
                    self._game_proc_logged = False
                    self._set_phase(Phase.WAIT_GAME)
                    return
        if time.time() - self.phase_start > 60:
            log.warning("timeout finding %s / %s (last view=%r)",
                        self.LABEL_LINEAGE_CARD, self.LABEL_RUN_GAME,
                        getattr(self, "_last_launch_view", ""))
            self._set_phase(Phase.ERROR)

    def _wait_for_game_process(self, timeout=60.0) -> bool:
        """Poll for LC.exe/Lineage.exe process. Returns True if found."""
        names = {"lc.exe", "lineage.exe", "lineageclassic.exe"}
        start = time.time()
        while time.time() - start < timeout:
            try:
                for p in psutil.process_iter(["name"]):
                    try:
                        if p.info["name"] and p.info["name"].lower() in names:
                            if not getattr(self, "_game_proc_logged", False):
                                log.info("game process detected: %s pid=%s",
                                         p.info["name"], p.pid)
                                self._game_proc_logged = True
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def _purple_covers_game(self) -> bool:
        """True if Purple (or its child) is drawn at the game window center."""
        if not self.game or not getattr(self.game, "valid", False):
            return False
        if not self.purple or not getattr(self.purple, "valid", False):
            return False
        try:
            cx, cy = self.game.rect.center
            top = user32.WindowFromPoint(wt.POINT(cx, cy))
            if not top:
                return False
            if top == self.game.hwnd:
                return False
            GA_ROOT = 2
            root = user32.GetAncestor(top, GA_ROOT) or top
            if root == self.purple.hwnd or top == self.purple.hwnd:
                return True
            # Same process as Purple (CEF children) counts as covered
            pid_top = wt.DWORD()
            user32.GetWindowThreadProcessId(root, ctypes.byref(pid_top))
            pid_p = wt.DWORD()
            user32.GetWindowThreadProcessId(
                self.purple.hwnd, ctypes.byref(pid_p))
            return bool(pid_top.value and pid_top.value == pid_p.value)
        except Exception:
            return False

    def _minimize_purple_via_input(self) -> bool:
        """UIPI-safe Purple minimize: Win32 often fails on elevated Purple.

        Uses Interception to focus the Purple title bar then Win+Down
        (system minimize of the focused window).
        """
        if not self.purple or not getattr(self.purple, "valid", False):
            return False
        if not getattr(self, "_interception_ready", False):
            return False
        try:
            from win import interception
            if not interception.init():
                return False
            r = self.purple.rect
            # 1) Focus Purple via title-bar click (device-level, bypasses UIPI)
            tx = r.left + max(40, r.width // 2)
            ty = r.top + 12
            interception.move(tx, ty)
            time.sleep(0.03)
            interception.click(tx, ty)
            time.sleep(0.15)
            # 2) Win+Down minimizes the focused window
            VK_LWIN, VK_DOWN = 0x5B, 0x28
            interception.key_down(VK_LWIN)
            time.sleep(0.02)
            interception.tap(VK_DOWN)
            time.sleep(0.02)
            interception.key_up(VK_LWIN)
            time.sleep(0.35)
            # 3) Fallback: click caption minimize button (~3rd from right)
            if user32.IsWindowVisible(self.purple.hwnd) and not user32.IsIconic(
                    self.purple.hwnd):
                mx = r.right - 100
                my = r.top + 14
                interception.move(mx, my)
                time.sleep(0.02)
                interception.click(mx, my)
                time.sleep(0.3)
            iconic = bool(user32.IsIconic(self.purple.hwnd))
            log.info("Purple minimize via input: iconic=%s visible=%s",
                     iconic, bool(user32.IsWindowVisible(self.purple.hwnd)))
            return iconic or not self._purple_covers_game()
        except Exception as e:
            log.warning("Purple minimize via input failed: %r", e)
            return False

    def _minimize_purple_for_game(self) -> bool:
        """Minimize Purple so LC can own the foreground.

        Win32 ShowWindow is tried first; elevated Purple often ignores it
        (UIPI). Fall back to Interception Win+Down / caption click.
        """
        if not self.purple or not getattr(self.purple, "valid", False):
            return False
        try:
            self.purple.minimize()
            time.sleep(0.2)
        except Exception as e:
            log.warning("Purple ShowWindow minimize failed: %r", e)
        if user32.IsIconic(self.purple.hwnd):
            log.info("Purple minimized (Win32) hwnd=%s", self.purple.hwnd)
            return True
        if self._minimize_purple_via_input():
            log.info("Purple minimized (Interception) hwnd=%s", self.purple.hwnd)
            return True
        # Last resort: Alt+Esc to push current foreground back (often Purple)
        try:
            from win import interception
            if interception.init():
                for _ in range(2):
                    interception.key_down(0x12)  # Alt
                    interception.tap(0x1B)       # Esc
                    interception.key_up(0x12)
                    time.sleep(0.35)
                    if not self._purple_covers_game():
                        log.info("Purple pushed back via Alt+Esc")
                        return True
        except Exception as e:
            log.warning("Alt+Esc push-back failed: %r", e)
        log.warning("Purple minimize incomplete hwnd=%s iconic=%s",
                    self.purple.hwnd, bool(user32.IsIconic(self.purple.hwnd)))
        return False

    def _activate_game_via_input(self) -> bool:
        """Title-bar click + Alt+Esc — works when Win32 z-order is UIPI-blocked."""
        if not self.game or not getattr(self.game, "valid", False):
            return False
        if not getattr(self, "_interception_ready", False):
            return False
        try:
            from win import interception
            if not interception.init():
                return False
            gr = self.game.rect
            title_x = gr.left + gr.width // 2
            title_y = gr.top + 15
            interception.move(title_x, title_y)
            time.sleep(0.02)
            interception.click(title_x, title_y)
            time.sleep(0.15)
            if self._game_on_top():
                return True
            for _ in range(3):
                interception.key_down(0x12)
                interception.tap(0x1B)
                interception.key_up(0x12)
                time.sleep(0.4)
                if self._game_on_top():
                    log.info("game on top via Alt+Esc")
                    return True
            return self._game_on_top()
        except Exception as e:
            log.warning("activate game via input failed: %r", e)
            return False

    def _prepare_game_foreground(self, attempts: int = 5) -> bool:
        """Minimize Purple, raise LC, verify center pixel is the game."""
        if not self.game or not getattr(self.game, "valid", False):
            return False
        if not self._is_real_game(self.game.hwnd):
            real = self._real_game_hwnd()
            if real is not None:
                self.game = type(self.game)(real)
            else:
                log.warning("prepare foreground: hwnd is not real LC window")
                return False

        for i in range(max(1, attempts)):
            self._minimize_purple_for_game()
            ok = False
            try:
                # Prefer device-level activation under UIPI
                if self._activate_game_via_input():
                    ok = True
                elif self._ensure_game_on_top():
                    ok = True
            except Exception as e:
                log.warning("ensure_game_on_top attempt %d: %r", i + 1, e)
            if ok and self._game_on_top() and not self._purple_covers_game():
                # Re-assert TOPMOST best-effort (ignored if UIPI blocks)
                try:
                    user32.SetWindowPos(
                        self.game.hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001)
                except Exception:
                    pass
                log.info("game foreground verified (attempt %d) purple_iconic=%s",
                         i + 1, bool(user32.IsIconic(self.purple.hwnd))
                         if self.purple else "?")
                return True
            time.sleep(0.4)
        log.warning("game foreground NOT verified after %d attempts "
                    "(on_top=%s purple_covers=%s)",
                    attempts, self._game_on_top(), self._purple_covers_game())
        return False

    def _game_window_ready(self) -> bool:
        """True when a real LC hwnd is attached (not just process alive)."""
        g = getattr(self, "game", None)
        if g is None or not getattr(g, "valid", False):
            return False
        try:
            return bool(self._is_real_game(g.hwnd))
        except Exception:
            return False

    def do_wait_game(self):
        # Non-blocking process gate — never sleep 30s inside one tick.
        if not getattr(self, "_game_proc_seen", False):
            if self._game_process_alive():
                self._game_proc_seen = True
                log.info("game process detected (WAIT_GAME)")
            elif time.time() - self.phase_start > 12.0:
                # First Start click often misses (card not settled / toast).
                # Re-enter FIND_LINEAGE to click Start again before S3 budget dies.
                log.warning("game process did not start within 12s; retry Start")
                self._set_phase(Phase.FIND_LINEAGE)
            return

        # Process started; now wait for the real window
        if self.find_game() and self._game_window_ready():
            log.info(f"game window found: {self.game.title!r} {self.game.rect.size}")
            if self._prepare_game_foreground(attempts=4):
                log.info("  Purple minimized; game on top (verified)")
            else:
                log.warning("  game found but not verified on top — S4 will retry")
            try:
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(self.game.hwnd, ctypes.byref(pid))
                pname = psutil.Process(pid.value).name() if pid.value else "?"
                log.info("game process: pid=%d name=%s", pid.value, pname)
            except Exception as ex:
                log.warning("could not read game process info: %r", ex)
            self.game_step = 0
            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
            self._set_phase(Phase.GAME_LOGIN)
            return
        if time.time() - self.phase_start > 300:
            log.error("timed out waiting for game window")
            self._set_phase(Phase.ERROR)

    # ---- game login phase ---------------------------------------------
    def _solve_game_captcha(self, img, region):
        rx, ry, rw, rh = region
        w, h = img.size
        if rx + rw > w or ry + rh > h:
            captcha_img = img
        else:
            captcha_img = img.crop((rx, ry, rx + rw, ry + rh))
        try:
            captcha_img.save(os.path.join(self.debug_dir, "game_captcha_debug.png"))
        except Exception:
            pass
        text, conf = self.captcha.solve_with_confidence(captcha_img)
        log.info(f"Game CAPTCHA solved: '{text}' (conf={conf:.2f}) region={region}")
        if conf < 0.10 or len(text) < 3:
            log.warning("Low-confidence game CAPTCHA, retrying")
            return
        # Click the input field to the right of the captcha, type, Enter.
        input_x = rx + rw + 20
        input_y = ry + rh // 2
        if self.dry_run:
            log.info(f"[dry-run] would type captcha '{text}' at client ({input_x},{input_y})")
            return
        self.game_click(self.game, input_x, input_y, label="captcha field")
        time.sleep(0.3)
        InputRouter.physical_select_all()
        time.sleep(0.05)
        InputRouter.physical_type_text(text)
        time.sleep(0.3)
        InputRouter.physical_press_enter()
        log.info(f"Submitted game CAPTCHA: {text}")

    def _select_character(self) -> bool:
        """Click the Nth character on the selection screen using window ratios."""
        if not self.game or not self.game.valid:
            return False

        from positions import char_slot_client_xy

        # Force game on top and keep it there
        self._force_game_on_top_for_capture()
        time.sleep(0.3)

        character_number = self.character_number - 1  # convert to 0-indexed
        xy = char_slot_client_xy(self.game, character_number)
        if xy is None:
            log.warning("[char-select] could not resolve slot ratio")
            return False
        cx, cy = xy
        log.info("[char-select] clicking character #%d at client (%d, %d)",
                self.character_number + 1, cx, cy)

        # Use Interception driver directly (bypasses NC Guard)
        # Coordinates are already in CLIENT/GAME WINDOW space
        if self._use_interception and self._interception_ready:
            try:
                # Convert client coords to screen coords for interception
                gr = self.game.rect
                screen_x = gr.left + cx
                screen_y = gr.top + cy

                # Verify game is actually at the click position (not Purple)
                pt_hwnd = user32.WindowFromPoint(wt.POINT(screen_x, screen_y))
                if pt_hwnd != self.game.hwnd:
                    log.warning("[char-select] game not at click point (hwnd=%s), "
                                "re-activating", pt_hwnd)
                    self._ensure_game_on_top()
                    gr = self.game.rect
                    screen_x = gr.left + cx
                    screen_y = gr.top + cy

                # Visual confirmation: move cursor to position first
                interception.move(screen_x, screen_y)
                time.sleep(0.1)
                interception.click(screen_x, screen_y)
                time.sleep(0.2)
                
                # Re-ensure game is on top after click
                self._bring_game_to_front()
                time.sleep(0.1)
                
                log.info("[char-select] int-click character #%d at client (%d, %d) [screen=(%d,%d)]",
                        self.character_number + 1, cx, cy, screen_x, screen_y)
            except Exception as e:
                log.warning("Interception click failed, falling back: %s", e)
                self.game_click(self.game, cx, cy, label=f"character #{self.character_number + 1}")
        else:
            # Fallback to game_click
            self.game_click(self.game, cx, cy, label=f"character #{self.character_number + 1}")
        
        time.sleep(1.0)
        # Keep game on top - don't release topmost
        log.info("[char-select] character #%d clicked, game kept on top", self.character_number + 1)
        return True

    def _is_security_setting(self, img) -> bool:
        """Security splash in EN / KR / zh-TW / zh-CN. Not the two-tile
        인증 수단 선택 / 選擇驗證方法 choice screen."""
        lines = self._ocr_lines(img)
        txt = normalize(" ".join(ln.text for ln in lines))
        choice_title = ("인증수단", "인증수단선택", "選擇驗證方法", "选择验证方法",
                        "selectverificationmethod", "驗證方法", "验证方法",
                        "證方法", "证方法")
        purple_tile = ("퍼플간편", "purple簡易", "簡易驗證", "简易验证",
                       "simpleauthentication", "purplesimple")
        if any(t in txt for t in choice_title) and any(t in txt for t in purple_tile):
            return False
        en = ("securitysetting", "security settings")
        kr = ("보안설정", "안전설정", "보안인증", "보안 인증", "보안등록", "보안 등록")
        cn = ("安全设置", "安全設定", "安全设定", "安全設定登錄中",
              "安全设定登绿中")
        if any(p in txt for p in (*en, *kr, *cn)):
            return True
        if "安全" in txt and any(t in txt for t in (
                "設", "设", "登", "錄", "录", "绿", "鷄")):
            return True
        reg_tokens = ("등록", "인증", "보안", "기기", "확인", "좋료", "활인")
        if "하시겠습니까" in txt and any(t in txt for t in reg_tokens):
            return True
        for p in ("보안설정", "안전설정", "보안인증",
                  "securitysetting", "安全設定", "安全设置"):
            for ln in lines:
                for w in ln.words:
                    if _ratio(p, w.text) >= 0.4:
                        return True
        return False

    def _sec_wait_auto(self, wait: float = 20.0):
        """The embedded device check may auto-complete (deferred callback);
        give it time before poking the window."""
        log.info("  security: waiting %.0fs for deferred device check", wait)
        time.sleep(wait)

    def _handle_security_splash(self) -> bool:
        """Called each tick while the device-verification splash may be up.
        Returns True when the splash is present (step machine paused).
        Shake the window for 2 seconds to nudge the check into passing."""
        now = time.time()
        last = getattr(self, "_sec_check_at", 0.0)
        if now - last < 2.0:
            return False
        self._sec_check_at = now
        img = self.capture_game()
        if img is None:
            return False
        if not self._is_security_setting(img):
            self._sec_seen_at = 0.0
            return False
        # Shake once
        if getattr(self, "_sec_shaken", False):
            return True
        self._sec_shaken = True
        log.info("Security Setting splash detected; shaking window ~2s")
        try:
            InputRouter.shake_window(self.game, duration=2.0)
        except Exception as ex:
            log.warning("shake error: %r", ex)
        time.sleep(2.0)
        return True

    def handle_security_setting(self) -> bool:
        """Shake the game window for 2 seconds to nudge device check."""
        return self._handle_security_splash()

    def _hwnd_info(self, hwnd: int) -> str:
        if not hwnd:
            return "(none)"
        cn = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cn, 256)
        rc = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        return (f"hwnd={hwnd} cls={cn.value!r} "
                f"rect=({rc.left},{rc.top},{rc.right - rc.left}x"
                f"{rc.bottom - rc.top})")

    def _agree_postmessage(self, sx: int, sy: int):
        """Background click: PostMessage to the real topmost window at the
        point (the agreement overlay if it sits above the game)."""
        target = InputRouter.topmost_hwnd_at(sx, sy)
        log.info("  agree postmessage target: %s", self._hwnd_info(target))
        left, top, _w, _h = InputRouter.window_rect(target)
        InputRouter.postmessage_click(target, sx - left, sy - top)

    def _locate_agree_click(self) -> Optional[Tuple[OcrLine, int, int]]:
        """Locate the '동의합니다' button on the agreement dialog. Returns
        (line, click_x, click_y) or None. The terms row shows BOTH '동의합니다'
        and '동의 안합니다' on one OCR line; we click the CENTER of the word
        matching a positive term (never the disagree text or the gap)."""
        spec = self.game_steps.get(0) or {}
        hits = self.find_lines(self.game, spec.get("words", ["동의합니다"]),
                               fuzzy=spec.get("fuzzy", 0.0), game=True)
        if not hits:
            return None
        excl = spec.get("exclude", ["안"])
        pos = ("동의합니다", "동의함", "agree", "I agree", "Accept", "同意", "我同意")
        agreed = []
        for qw, ln in hits:
            if any(tok in ln.text for tok in excl) and not any(
                    p in ln.text for p in pos):
                continue
            agreed.append((qw, ln))
        if not agreed:
            return None
        # Prefer the hit on the longest query word (the actual button row),
        # then the shortest line width.
        agreed.sort(key=lambda t: (-len(normalize(t[0])), t[1].w))
        _q, line = agreed[0]
        pos_terms = [normalize(p) for p in pos]
        best_word, best_ratio = None, 0.0
        for wd in line.words:
            wtxt = normalize(wd.text)
            for pt in pos_terms:
                r = _ratio(wtxt, pt)
                if r > best_ratio:
                    best_ratio, best_word = r, wd
        if best_word is not None and best_ratio >= 0.35 \
                and best_word.w < line.w * 0.75:
            click_x = best_word.x + best_word.w // 2
            click_y = best_word.y + best_word.h // 2
        else:
            click_x = line.x + int(line.w * 0.25)
            click_y = line.y + line.h // 2
        return line, click_x, click_y

    @staticmethod
    def _game_process_alive() -> bool:
        """True if any LC/Lineage game process is still running (used to
        distinguish window churn during load from a dead game client)."""
        names = {"lc.exe", "lineage.exe", "lineage"}
        try:
            for p in psutil.process_iter(["name"]):
                try:
                    if p.info["name"] and p.info["name"].lower() in names:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _close_game(self, wait: float = 1.5) -> None:
        """Close the game client quickly (whole process tree: LC.exe plus
        GameGuard children) so the device-verification splash gets a fresh
        relaunch. Falls back to terminating the LC/Lineage processes if the
        window pid cannot be resolved."""
        # Kill any running heavy OCR process
        if hasattr(self, '_heavy_ocr_proc') and self._heavy_ocr_proc is not None:
            try:
                self._heavy_ocr_proc.kill()
            except Exception:
                pass
            self._heavy_ocr_proc = None
        pid = None
        if self.game and self.game.valid:
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(self.game.hwnd, ctypes.byref(p))
            if p.value:
                pid = int(p.value)
        if pid:
            log.info("  closing game pid %d (tree)", pid)
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           creationflags=subprocess.CREATE_NO_WINDOW,
                           capture_output=True)
        else:
            log.info("  no game hwnd pid; terminating LC/Lineage processes")
            for proc in psutil.process_iter(["name"]):
                try:
                    if proc.info["name"] and proc.info["name"].lower() in {
                            "lc.exe", "lineage.exe", "lineage"}:
                        proc.terminate()
                except Exception:
                    pass
        self.game = None
        self.game_step = 0
        self.game_step_deadline = 0.0
        self._agree_step0_time = None
        self._game_fronted = False
        time.sleep(wait)

    def _bring_game_to_front(self):
        """Force game window above Purple using multi-layer activation.

        Tries Interception first (kernel-level, same as clicks), 
        then Win32 as fallback. Verifies game is actually on top.
        """
        if not self.game or not self.game.valid:
            return
        self._ensure_game_on_top()

    def _fix_game_window_size(self, target_w: int = 816, target_h: int = 639):
        """Deprecated: clicks are window-ratio based; do not force resize."""
        return

    def _force_game_on_top_for_capture(self):
        """Strongly force game on top + wait for render, for screen capture.
        Uses multi-layer activation (Interception -> Win32) so Purple can't steal focus.
        Called before quest_ocr.exe to ensure the game is visible on screen."""
        self._ensure_game_on_top()
        time.sleep(0.3)
        self._ensure_game_on_top()
        time.sleep(0.3)
        # Verify game is actually on top; if not, retry
        if not self._game_on_top():
            self._ensure_game_on_top()
            time.sleep(0.3)

    def _release_game_topmost(self):
        """Remove TOPMOST flag so game can go behind normally."""
        if not self.game or not self.game.valid:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            user32.SetWindowPos(self.game.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE)
        except Exception:
            pass


    def _activate_via_interception(self) -> bool:
        """Activate game window using Interception driver (kernel-level).
        
        Uses the same kernel driver that powers our clicks - same trust level,
        bypasses UIPI and foreground lock. Returns True if successful.
        """
        if not self._interception_ready or not self._use_interception or not self.game:
            return False
        
        try:
            gr = self.game.rect
            # Click title bar center via Interception (kernel-level, bypasses UIPI)
            title_x = gr.left + gr.width // 2
            title_y = gr.top + 15
            
            # Move + click via Interception (kernel-level, same as game clicks)
            interception.move(title_x, title_y)
            time.sleep(0.02)
            interception.click(title_x, title_y)
            time.sleep(0.08)
            
            # Verify game is actually on top
            return self._game_on_top()
        except Exception as e:
            log.warning(f'Interception activation failed: {e}')
            return False

    def _ensure_game_on_top(self) -> bool:
        """Multi-layer activation: Interception title click -> Alt+Esc -> Win32.

        Elevated LC ignores SetWindowPos from a medium-integrity bot (UIPI);
        device-level input is the reliable path.
        """
        if not self.game or not self.game.valid:
            return False

        if self._activate_via_interception():
            log.debug("Game activated via Interception title click")
            return True

        if self._activate_game_via_input():
            log.debug("Game activated via Interception Alt+Esc")
            return True

        # Layer 3: Win32 (works when bot is elevated)
        try:
            import ctypes
            user32_l = ctypes.windll.user32
            hwnd = self.game.hwnd
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            user32_l.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                  SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32_l.BringWindowToTop(hwnd)
            user32_l.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            if self._game_on_top():
                return True
        except Exception:
            pass

        return self._game_on_top()


    def do_game_login(self):
        self._bring_game_to_front()

        if not self.game or not self.game.valid:
            if self.find_game():
                self.game_step = 0
                self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                self._game_lost_at = 0.0
                # Enable interception for in-game clicks (NC Guard blocks SendInput)
                if self._interception_ready and not self._use_interception:
                    self._use_interception = True
                    log.info("enabling Interception for in-game clicks")
            else:
                now = time.time()
                lost_at = getattr(self, "_game_lost_at", 0.0)
                if lost_at == 0.0:
                    self._game_lost_at = now
                elif now - lost_at > 60:
                    if not self._game_process_alive():
                        # Option A: the controller owns the crash restart
                        # (kill session -> relaunch auto-login). bot2 must
                        # NOT relaunch on its own - it exits and lets the
                        # controller spawn a clean fresh flow.
                        log.warning("game process is gone (killed/crashed); "
                                    "controller watchdog owns the restart - "
                                    "bot2 exiting")
                        self.request_shutdown()
                        return
                    self._game_lost_at = now
                    log.warning("game window churning but process alive; "
                                "still waiting")
                if now - getattr(self, "_lost_log_at", 0.0) > 15:
                    log.warning("game window (real GLFW30) not found yet; "
                                "waiting (GameGuard dummy window ignored) "
                                "proc_alive=%s", self._game_process_alive())
                    self._lost_log_at = now
                time.sleep(1.0)
                return
        else:
            self._game_lost_at = 0.0
            # Re-target: if we are somehow still holding the GameGuard dummy
            # window and the real game window has appeared, switch to it now.
            if not self._is_real_game(self.game.hwnd):
                real = self._real_game_hwnd()
                if real is not None:
                    log.info("re-targeting to real game window (was holding "
                             "the anti-cheat dummy)")
                    self.game = WinWindow(real)
                    self.game_step = 0
                    self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
        if self.game_step >= 6:
            log.info("game login sequence complete")
            backup_device_tag(self.session_backup_dir)
            self._set_phase(Phase.DONE)
            return

        # Device-verification "Security Setting" splash (EN/KR/CN): on the
        # first launch we close the game quickly and relaunch (a clean start
        # usually clears the deferred device check). If the splash persists on
        # the restarted client, micro-shake the window to nudge the check into
        # auto-passing. Clicking "기기등록" makes the client exit, so that path
        # stays DISABLED. Only check at step 0 (before agree), not step 1+.
        if self.game_step == 0:
            if self._handle_security_splash():
                return

        # --- Page-number click (step 1): ratios from page_positions config.
        if self.game_step == 1:
            from positions import page_client_xy
            page_target = self.words_cfg.get("page_number", ["2"])[0]
            xy = page_client_xy(self.cfg.get("page_positions", {}),
                                page_target, self.game)
            if xy is not None and self.game and self.game.valid:
                cx, cy = xy
                log.info("page %s: click (%d,%d) [window %dx%d]",
                         page_target, cx, cy,
                         self.game.rect.width, self.game.rect.height)
                self.game_click(self.game, cx, cy, label="page %s" % page_target)
                time.sleep(1.0)
                self.game_step = 2
                self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                return

        # Membership-guide / notice popups ("회원가입 -안내서" with
        # 계속합니다/취소합니다) appear mid-login; click "계속합니다" to proceed.
        # Cooldown: 3s between clicks to avoid killing the game.
        if 1 <= self.game_step < 4:
            now_cc = time.time()
            last_cc = getattr(self, "_continue_click_time", 0)
            if now_cc - last_cc >= 3.0:
                continue_words = ["계속합니다", "계속", "Continue"]
                chits = self.find_lines(self.game, continue_words, fuzzy=0.4, game=True)
                if chits:
                    chits.sort(key=lambda t: t[1].w)
                    _q, cln = chits[0]
                    if cln.w <= 200:
                        self.game_click_line(self.game, cln, "center",
                                             label="계속합니다 (continue)")
                        self._continue_click_time = now_cc
                        time.sleep(2.0)
                        return

        # --- Agree dialog (step 0): click "동의합니다" immediately -----
        if self.game_step == 0:
            step = self.game_step
            spec = self.game_steps.get(step)
            if spec:
                words = spec.get("words", [])
                click_type = spec.get("click", "center")
                exclude = spec.get("exclude", [])
                fuzzy = spec.get("fuzzy", 0.0)
                if words:
                    lines = self.find_lines(self.game, words, fuzzy=fuzzy, game=True)
                    if lines:
                        lines = [ln for ln in lines if not any(
                            normalize(x) in normalize(ln[1].text) for x in exclude
                        )]
                        if lines:
                            lines.sort(key=lambda t: t[1].w)
                            _q, line = lines[0]
                            self.game_click_line(self.game, line, click_type,
                                                 label="동의합니다 (agree)")
                            time.sleep(1.0)
                            self.game_step = 1
                            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                            self._agree_step0_time = None
                            return
            # Fallback: wait for auto-advance (24s countdown)
            if not hasattr(self, "_agree_step0_time") or self._agree_step0_time is None:
                self._agree_step0_time = time.time()
            elapsed = time.time() - self._agree_step0_time
            if elapsed >= 24.0:
                log.info("agree dialog auto-advanced after %.1fs", elapsed)
                self.game_step = 1
                self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                self._agree_step0_time = None
                return
            return

        step = self.game_step

        # Character selection (step 4): after server confirm OK, before final OK.
        # Detect cartoon-style human characters with YOLO, click the Nth from left.
        if step == 4:
            if self._select_character():
                time.sleep(1.0)
                self.game_step = 5
                self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                return
            # If detection failed, still advance — OK button might be visible
            log.warning("character selection failed; advancing to OK step")
            self.game_step = 5
            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
            return

        spec = self.game_steps.get(step)
        if spec is None:
            self.game_step += 1
            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
            return

        # OCR-based clicking for steps 2, 3, 4 (server name, etc.)
        if step in self.game_steps:
            spec = self.game_steps[step]
            words = spec.get("words", [])
            click_type = spec.get("click", "center")
            label = spec.get("label", f"step{step}")
            fuzzy = spec.get("fuzzy", 0.0)
            exclude = spec.get("exclude", [])

            if words:
                lines = []
                # For server name (step 2), use quest_ocr.exe with forced game-on-top.
                # Standard capture (PrintWindow/ImageGrab/dxcam) cannot see the
                # DirectX game content — only the title bar. quest_ocr.exe uses
                # PaddleOCR on a full-screen capture and CAN see the game.
                if step == 2 and self._interception_ready:
                    if not hasattr(self, '_heavy_ocr_proc') or self._heavy_ocr_proc is None:
                        # First tick: force game on top, save rect, launch quest_ocr.exe
                        self._force_game_on_top_for_capture()
                        time.sleep(0.3)
                        # Save the game rect AT capture time — OCR coords are screen-relative
                        if self.game and self.game.valid:
                            gr = self.game.rect
                            self._ocr_capture_rect = (gr.left, gr.top, gr.width, gr.height)
                        self.run_heavy_ocr(words)
                    else:
                        # Subsequent ticks: re-force game on top periodically
                        # so Purple doesn't steal focus during the OCR
                        self._bring_game_to_front()
                    # Check if quest_ocr.exe finished
                    if hasattr(self, '_heavy_ocr_proc') and self._heavy_ocr_proc is not None:
                        proc = self._heavy_ocr_proc
                        if proc.poll() is None:
                            return  # still running
                        # Done — parse results
                        self._heavy_ocr_proc = None
                        from pathlib import Path
                        result_file = Path(__file__).parent / "heavy_OCR" / "result.json"
                        hits = self._parse_heavy_ocr_result(result_file)
                        # Use the SAVED rect from OCR capture time (window may have moved)
                        ocr_rect = getattr(self, '_ocr_capture_rect', None)
                        if hits and ocr_rect:
                            ocr_left, ocr_top, _, _ = ocr_rect
                            for h in hits:
                                # Use SCREEN coords directly — game_click_line
                                # would reconvert via client_to_screen with the
                                # wrong (moved) window rect.
                                screen_cx = h['cx']
                                screen_cy = h['cy']
                                log.info("[quest-ocr] step%d found %d hits via quest_ocr.exe "
                                         "screen=(%d,%d) capture_rect=%s",
                                         step, len(lines), screen_cx, screen_cy, ocr_rect)
                                lines.append((h['word'], None, screen_cx, screen_cy))
                            log.info("[quest-ocr] step%d found %d hits via quest_ocr.exe",
                                     step, len(lines))
                        self._release_game_topmost()
                        # Click directly using OCR screen coords (bypass client roundtrip)
                        if lines:
                            _q, _line, scx, scy = lines[0]
                            # Ensure game is on top at the OCR click point
                            pt_hwnd = user32.WindowFromPoint(wt.POINT(scx, scy))
                            if self.game and pt_hwnd != self.game.hwnd:
                                log.warning("[quest-ocr] game not at OCR point, "
                                            "re-activating (pt_hwnd=%s)", pt_hwnd)
                                self._ensure_game_on_top()
                            if self._use_interception and self._interception_ready:
                                try:
                                    interception.click(scx, scy)
                                    log.info("[quest-ocr] int-click '%s' at screen=(%d,%d)",
                                             _q, scx, scy)
                                except Exception as ex:
                                    log.warning("[quest-ocr] interception click failed: %r", ex)
                            else:
                                InputRouter.click_screen(scx, scy)
                                log.info("[quest-ocr] click '%s' at screen=(%d,%d)",
                                         _q, scx, scy)
                            time.sleep(1.0)
                            self.game_step = 3
                            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                            lines = []  # consumed — skip the general handler below
                    else:
                        return  # started but not yet tracked
                # Fall back to window/screen OCR for other steps
                if not lines:
                    lines = self.find_lines(self.game, words, fuzzy=fuzzy, game=True)
                if lines:
                    lines = [ln for ln in lines if not any(
                        normalize(x) in normalize(ln[1].text) for x in exclude
                    )]
                    if lines:
                        lines.sort(key=lambda t: t[1].w)
                        _q, line = lines[0]
                        self.game_click_line(self.game, line, click_type, label=label)
                        time.sleep(1.0)
                        # Advance to next step after clicking
                        # NEW FLOW: step 2 (server) -> step 3 (OK) -> step 4 (character) -> step 5 (OK final) -> DONE
                        if step == 2:
                            # After server name click, advance to OK step
                            self.game_step = 3
                            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                        elif step == 3:
                            # After OK click, advance to character position
                            self.game_step = 4
                            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                        elif step == 4:
                            # After character click, advance to final OK
                            self.game_step = 5
                            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT
                        elif step == 5:
                            # Final OK - advance to DONE
                            self.game_step = 6
                            self._set_phase(Phase.DONE)
                            backup_device_tag(self.session_backup_dir)
                            return
                        return

        # Step timeout - advance anyway
        if time.time() > self.game_step_deadline:
            log.warning("step %d timeout, advancing", step)
            self.game_step += 1
            self.game_step_deadline = time.time() + GAME_STEP_TIMEOUT

    # ---- main loop ----------------------------------------------------
    def tick(self):
        handlers = {
            Phase.FIND_PURPLE: self.do_find_purple,
            Phase.WAIT_LOGIN_FORM: self.do_wait_login_form,
            Phase.ENTER_CREDENTIALS: self.do_enter_credentials,
            Phase.WAIT_MAIN: self.do_wait_main,
            Phase.FIND_LINEAGE: self.do_find_lineage,
            Phase.WAIT_GAME: self.do_wait_game,
            Phase.GAME_LOGIN: self.do_game_login,
        }
        fn = handlers.get(self.phase)
        if fn:
            try:
                fn()
            except Exception as e:
                log.exception(f"error in phase {self.phase}")
                self._set_phase(Phase.ERROR)

    def run(self, max_seconds: int = 3600, dry_run: bool = False, learn: bool = False):
        self.dry_run = dry_run
        self.learn = learn
        if learn:
            log.info("LEARN mode: captcha is detected+solved, screens OCR-logged "
                     "and saved to learn_*.png so we can tune the state machine")
        t0 = time.time()
        _last_beat = [0.0]
        while time.time() - t0 < max_seconds:
            if self._shutdown_requested:
                log.info("Shutdown requested, exiting...")
                self._cleanup()
                return 130  # SIGTERM exit code
            if self.phase == Phase.DONE:
                log.info("DONE")
                self._cleanup()
                return 0
            if self.phase == Phase.ERROR:
                log.error("ERROR phase reached")
                self._cleanup()
                return 1
            now = time.time()
            if now - _last_beat[0] >= 30.0:
                _last_beat[0] = now
                log.info("heartbeat: phase=%s elapsed=%.0fs", self.phase, now - t0)
            self.tick()
            # GameFlow.tick() already sleeps. Extra 1s here doubled game login.
            if self.phase == Phase.GAME_LOGIN:
                time.sleep(0.02)
            elif self.phase in (Phase.ENTER_CREDENTIALS, Phase.FIND_LINEAGE,
                                Phase.WAIT_MAIN):
                time.sleep(0.12)
            else:
                time.sleep(0.25)
        log.warning("time budget exhausted")
        self._cleanup()
        return 2


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Option D - window-targeted LC auto-login")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate window discovery/OCR without clicking")
    ap.add_argument("--seconds", type=int, default=3600,
                    help="max run time in seconds")
    ap.add_argument("--learn", action="store_true",
                    help="solve captchas as they appear and log/save screens "
                         "to learn the login states")
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    _fh = logging.FileHandler(os.path.join(here, "bot_run.log"),
                              mode="a", encoding="utf-8")
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_fh)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _excepthook(exc_type, exc_value, exc_tb):
        log.error("UNHANDLED EXCEPTION:\n%s",
                  "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

    sys.excepthook = _excepthook

    config_path = os.path.join(here, "purple_login.json")
    bot = Bot(config_path)
    
    # Set up signal handlers for graceful shutdown
    def _signal_handler(signum, frame):
        log.info(f"Received signal {signum}, requesting shutdown...")
        bot.request_shutdown()
    
    import signal
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    # Windows doesn't have SIGHUP but we can try
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, _signal_handler)

    try:
        rc = bot.run(max_seconds=args.seconds, dry_run=args.dry_run, learn=args.learn)
    except Exception:
        log.exception("bot.run crashed")
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
