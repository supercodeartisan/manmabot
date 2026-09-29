"""Post-agreement game-login engine.

Replaces bot.py's OCR-step machine (do_game_login steps 0..5), which was
fragile: heavy OCR of DirectX content, blind step timeouts that cascaded
failures, and hardcoded client coordinates.

Design goals
------------
- window-size independent : multi-scale anchor template matching on a live
  screen grab + window-RATIO clicks (no fixed pixels)
- noise tolerant          : act only on positive detection, verify every
  click by watching the screen change, re-sync state from scratch whenever
  reality diverges from the expectation
- fast                    : whole engine budget is 150 s, keeping the
  end-to-end run inside the 3-minute target
- input                   : EVERYTHING goes through the Interception driver
  (clicks, wheel, keys). No silent SendInput fallback - if the driver is
  unavailable the engine raises instead of degrading.
- languages               : ko / zh-TW / zh-CN / en word tables for OCR
  detection; ratio clicks are language-independent.

Flow (measured from ScreenRecorderProject1.mp4, see FLOW_ANALYSIS.md):
  AGREEMENT -> scroll bottom -> click agree button
  SERVER_SELECT -> click page "2" (verify list changed) -> click server row
  CONNECT_WAIT -> LOADING -> CHARACTER (select + start) -> INGAME
"""
import logging
import os
import re
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab

import ctypes
import ctypes.wintypes as wt

from win import interception
from win.winocr import OcrLine, _ratio
from uilang import LANGS, detect_ui_lang, has_cjk, has_hangul
from game_geom import (
    GEOM_AUTO,
    GEOM_DIALOG,
    GEOM_WINDOW,
    dialog_ratio_pt,
    normalize_geom_mode,
    window_ratio_to_screen,
)
import json

log = logging.getLogger("gameflow")

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------------------
# Reference geometry: the video the anchors/ratios were measured from had the
# game window at 806x631 (config's reference window is 816x639; the ratios
# agree within ~0.3% - see FLOW_ANALYSIS.md).
REF_W = 806.0
REF_H = 631.0
# Legacy reference size for comments / old recordings (clicks use ratios).
REF_PAGE_W = 816.0
REF_PAGE_H = 639.0
# Splash (e.g. 1296x999) vs login dialog (e.g. 816x639). Use this, not a
# single magic width, so a larger/smaller saved dialog still counts.
DIALOG_MAX_W = 1100
DIALOG_MAX_H = 850

# Korean 동의합니다 and Chinese 同意 are the LEFT button at the same
# window ratio. Measured on 816x639 last_click.png: 同意 center (362,423)
# = (0.444, 0.662); 不同意 center (454,423). Do not move this left/up —
# (0.38, 0.61) landed in the terms body, 52px left and 34px above 同意.
R_AGREE_BTN = (0.444, 0.662)
R_AGREE_BTN_ZH = (0.444, 0.662)
# 同意 is this fraction of window width left of 不同意 (92/816).
AGREE_LEFT_OF_DISAGREE = 0.113
R_PAGE2_BTN = (0.463, 0.630)        # page "2" button (center; config's
                                    # (373,384) sits on the button's top edge)
R_SERVER_ROW = (0.717, 0.507)       # fallback server row (video click pos)
R_DIALOG_CENTER = (0.34, 0.45)      # agreement text area (scroll point)
R_LIST_REGION = (0.28, 0.27, 0.80, 0.60)   # server list x0,y0,x1,y1
R_CHAR_SLOTS = [(0.215, 0.313), (0.490, 0.313), (0.741, 0.313)]
# Right-side login column: ok / credit / exit. Measured on last_click.png
# 816x639: ok=(645,484)= (0.790, 0.757). The left parchment is NOT ok.
R_LOGIN_OK = (0.790, 0.757)
R_LOGIN_OK_XMIN = 0.62          # ignore everything left of Account/Password

ANCHOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anchors")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Where each anchor template was cropped from in the reference video
# (full-screen coords of the 1920x1080 recording).
ANCHOR_ORIGINS = {
    "security_splash": (500.0, 380.0),
    "agreement_title": (500.0, 398.0),
    "server_title": (500.0, 393.0),
    "connecting": (507.0, 450.0),
    "loading": (440.0, 330.0),
}

# Element positions in the same reference space, expressed as offsets from
# their anchor origin (see FLOW_ANALYSIS.md measurements).
OFF_AGREE_BTN = (100.0, 247.0)        # 동의합니다 button from agreement_title
OFF_DIALOG_CENTER = (14.0, 107.0)     # agreement text area (scroll point)
OFF_PAGE2_BTN = (113.0, 226.0)        # page "2" button from server_title
OFF_SERVER_ROW = (318.0, 148.0)       # fallback server row from server_title
OFF_LIST_REGION = (7.0, 22.0, 343.0, 182.0)   # list x0,y0,x1,y1 from origin

# Per-language OCR word tables. "server_name" comes from the config
# (words.server_name) because it is an account-specific proper noun.
WORDS = {
    "agree_dialog": {
        "ko": ["동의서", "동의합니다", "이용자", "이용약관", "약관"],
        "zh-TW": ["同意書", "使用者協議", "服務協議", "同意", "使用者條款"],
        "zh-CN": ["同意书", "用户协议", "服务协议", "同意", "用户条款"],
        "en": ["User Agreement", "Agreement", "Terms", "Terms of Service"],
    },
    "agree_button": {
        "ko": ["동의합니다", "동의함", "동의"],
        "zh-TW": ["同意", "我同意", "同意並繼續"],
        "zh-CN": ["同意", "我同意", "同意并继续"],
        "en": ["Agree", "I agree", "I Agree", "Accept"],
    },
    "agree_exclude": {
        "ko": ["안", "동의 안", "하지 않", "동의하지"],
        "zh-TW": ["不同意", "拒絕", "取消"],
        "zh-CN": ["不同意", "拒绝", "取消"],
        "en": ["Disagree", "Decline", "Cancel", "Refuse"],
    },
    "server_dialog": {
        "ko": ["서버", "선택", "서버 선택"],
        "zh-TW": ["伺服器", "選擇", "伺服器選擇"],
        "zh-CN": ["服务器", "选择", "服务器选择"],
        "en": ["Server", "select", "Select Server"],
    },
    "server_confirm": {
        "ko": ["확인", "예", "예스", "네", "승인", "OK", "Ok", "ok"],
        "zh-TW": ["確定", "確認", "是", "好"],
        "zh-CN": ["确定", "确认", "是", "好"],
        "en": ["OK", "Ok", "Confirm", "Yes"],
    },
    "device_reg": {
        "ko": ["기기등록", "기기 등록", "기기등록하기"],
        "zh-TW": ["裝置登錄", "裝置註冊", "設備註冊", "設備登錄", "裝置登入"],
        "zh-CN": ["装置登录", "设备注册", "装置注册", "设备登录", "装置登入",
                  "设备登录", "设备註册"],
        "en": ["Register device", "Device registration", "Register Device"],
    },
    "device_reg_context": {
        # Title of the auth-method CHOICE screen. Do NOT include "간편" —
        # that token also appears on the 퍼플 간편 인증 button/QR screen.
        "ko": ["인증 수단", "인증수단", "인증 수단 선택", "수단 선택",
               "본인확인", "인증방법", "인증 방법"],
        "zh-TW": ["選擇驗證方法", "選擇認証方法", "選擇認證方法", "驗證方法",
                  "認證方式", "驗證方式", "認證 手段", "選擇驗證方式"],
        "zh-CN": ["选择验证方法", "选择认证方法", "验证方法", "认证方式",
                  "验证方式", "认证手段", "选择验证方式", "认证方法"],
        "en": ["authentication method", "verify method", "choose authentication",
               "Select verification method", "Verification method"],
    },
    "device_reg_avoid": {
        "ko": ["폰 간편", "폰간편", "휴대폰"],
        "zh-TW": ["手機", "手機簡易"],
        "zh-CN": ["手机", "手机简易"],
        "en": ["phone", "mobile"],
    },
    "sms_verify": {
        "ko": ["인증번호", "본인확인", "SMS", "문자"],
        "zh-TW": ["驗證碼", "簡訊", "簡訊驗證"],
        "zh-CN": ["验证码", "短信", "短信验证"],
        "en": ["verification code", "SMS", "OTP"],
    },
    "purple_auth": {
        "ko": ["퍼플간편인증", "퍼플 간편인증", "퍼플 간편 인증",
               "퍼플간편 인증", "Purple 간편인증", "퍼플 간편"],
        "zh-TW": ["PURPLE簡易驗證", "PURPLE簡易認証", "PURPLE簡便認證",
                  "簡易驗證", "簡易認証", "簡便認證", "Purple簡便認證",
                  "Purple簡易驗證", "PURPLE簡易證"],
        "zh-CN": ["PURPLE简易验证", "PURPLE简便认证", "PURPLE简易認証",
                  "简易验证", "简便认证", "Purple简易验证", "简易認証"],
        "en": ["Purple simple authentication", "simple authentication",
               "PURPLE simple verification", "Purple Easy Auth"],
    },
    "security_splash": {
        "ko": ["보안설정", "보안 설정", "안전설정", "안전 설정"],
        "zh-TW": ["安全設定", "安全设置", "安全設定中"],
        "zh-CN": ["安全设定", "安全设置", "安全设定中"],
        "en": ["security setting", "Security Settings", "Security setting"],
    },
    "connecting": {
        "ko": ["접속 중", "접속중", "접속", "연결 중"],
        "zh-TW": ["連線中", "連線", "登入", "連接中"],
        "zh-CN": ["连接中", "连接", "登录", "连线中"],
        "en": ["Connecting", "Connect", "Logging in"],
    },
    "ok_button": {
        "ko": ["확인", "OK", "Ok", "ok", "예", "예스", "네", "승인"],
        "zh-TW": ["確定", "確認", "是", "好"],
        "zh-CN": ["确定", "确认", "是", "好"],
        "en": ["OK", "Ok", "Confirm", "Yes"],
    },
    "start_button": {
        "ko": ["시작", "확인", "게임 시작", "Start Game", "플레이"],
        "zh-TW": ["開始", "開始遊戲", "確定", "確認", "進入"],
        "zh-CN": ["开始", "开始游戏", "确定", "确认", "进入"],
        "en": ["Start", "Start Game", "OK", "Confirm", "Enter", "PLAY", "Play"],
    },
    "continue_popup": {
        "ko": ["계속합니다", "계속", "계속하기"],
        "zh-TW": ["繼續", "繼續進行", "繼續遊戲"],
        "zh-CN": ["继续", "继续进行", "继续游戏"],
        "en": ["Continue", "Proceed"],
    },
    # After server row click: notice that asks to reconnect (stay on server UI)
    "reconnect_notice": {
        "ko": ["재접속", "다시 접속", "다시 연결", "접속을 다시",
               "연결이 끊", "연결 끊김", "재연결", "다시 시도"],
        "zh-TW": ["重新連線", "重新連接", "請重新", "連線中斷", "再次連接",
                  "重新登入", "請再試"],
        "zh-CN": ["重新连接", "重新连线", "请重新", "连接中断", "再次连接",
                  "重新登录", "请再试"],
        "en": ["reconnect", "re-connect", "connection lost", "disconnected",
               "try again", "please reconnect", "connection failed"],
    },
    "ingame": {
        "ko": ["인벤토리", "미니맵", "경험치", "채팅"],
        "zh-TW": ["道具", "背包", "小地圖", "經驗", "聊天"],
        "zh-CN": ["背包", "道具", "小地图", "经验", "聊天"],
        "en": ["Inventory", "Menu", "Map", "EXP", "Chat"],
    },
}

# Common RapidOCR / WinOCR substitutions for the device-auth screens.
_OCR_VARIANTS = {
    "수단": ("슈단", "수탄", "수딘"),
    "선택": ("선텍", "선텍", "선책"),
    "퍼플": ("프플", "퍼를", "퍼블", "피플", "purple", "PURPLE"),
    "간편": ("간현", "간변", "간번"),
    "인증": ("인중", "인즈", "인중"),
    "기기": ("키기", "기기"),
    "등록": ("동록", "둥록"),
    "驗證": ("認証", "验证", "證", "证", "験証"),
    "验证": ("驗證", "認証", "證", "证"),
    "選擇": ("选择", "遥摆", "選择"),
    "选择": ("選擇", "選择"),
    "登錄": ("登录", "註冊", "注册", "登入"),
    "登录": ("登錄", "登入", "注册"),
    "簡易": ("简易", "簡便", "简便", "简便"),
    "简易": ("簡易", "简便", "簡便"),
    "裝置": ("装置", "设备", "設備"),
    "装置": ("裝置", "设备", "設備"),
    "設備": ("设备", "裝置", "装置"),
    "设备": ("設備", "裝置", "装置"),
    "安全": ("安裝", "安金"),
    "設定": ("设置", "设定", "設定"),
    "设置": ("設定", "设定"),
    "设定": ("設定", "设置"),
}

# anchor logical name -> candidate file names (per-lang dir first, then default)
_ANCHOR_FILES = {
    "security_splash": ["game_security_splash.png"],
    "device_reg": ["device_reg_body.png", "device_reg.png"],
    "auth_choice": ["auth_choice_ko.png", "auth_choice_tw.png"],
    # Post-AUTH-relaunch flash status (tw): shake the instant these appear.
    # 安全設定登録中 / 裝置登錄確認中 — window flips to AUTH in a blink.
    "boot_shake": [
        "boot_shake_security.png",  # 安全設定登録中 (white+green)
        "boot_shake_device.png",    # 裝置登錄確認中
    ],

    "agreement_title": ["game_agreement_title.png"],
    "server_title": ["game_server_title.png"],
    "connecting": ["game_connecting.png"],
    "loading": ["game_loading_title.png"],
}
# Anchors that keep every matching PNG (not first-hit-wins).
_MULTI_FILE_ANCHORS = frozenset({"auth_choice", "boot_shake"})

TOTAL_BUDGET = 240.0          # engine self-destruct deadline (s) - allows
                              # for manual SMS verification if it appears
STATE_TIMEOUTS = {
    "SECURITY": 120.0,
    "DEVICE_REG": 240.0,
    "PURPLE_AUTH": 30.0,
    "AGREEMENT": 45.0,
    "SERVER_SELECT": 40.0,
    "CONNECT_WAIT": 45.0,
    "LOADING": 75.0,
    "CHARACTER": 45.0,
}
TICK_SLEEP = 0.22
# After a confirmed character double-click, wait this long then hand off
# to Manmabot so the world can finish loading.
CHAR_HANDOFF_SECONDS = 5.0
TICK_SLEEP_SHAKE = 0.06
OCR_MAX_SIDE = 640
MATCH_THRESH = 0.78
SCALE_SWEEP = (0.80, 0.90, 1.00, 1.10, 1.25)
# Tiny status crops (安全設定登録中 / 裝置登錄確認中) — dense scales, OCR-free.
BOOT_SHAKE_THRESH = 0.70
BOOT_SHAKE_SCALES = (
    0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.30,
)
BOOT_SHAKE_HUNT_S = 25.0  # template hunt after familiar size is pinned
# True maximize / Aero-snap — not the normal splash (1296x999).
SHELL_MAX_W = 1600
SHELL_MAX_H = 900
CLICK_SETTLE = 0.7
MAX_RETRIES = 4
# AUTH_CHOICE close+relaunch budget per session (퍼플 간편 인증)
AUTH_RELAUNCH_MAX = 2
# Reconnect notice after server click → OK + reselect server
SERVER_RECONNECT_MAX = 5
POPUP_COOLDOWN = 2.0
PERSON_INTERVAL = 1.0
SHAKE_DURATION = 10.0
BOOT_SHAKE_CYCLES = 24
BOOT_SHAKE_AMP = 10
BOOT_SHAKE_INTERVAL = 0.04
CHAR_TM_THRESH = 0.62         # min CCOEFF for the character template match
CHAR_TM_SCALES = (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.05)


def _now() -> float:
    return time.time()


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def lookup_server_in_table(table, target):
    """Return (page, row, col) for an exact normalized name, or None."""
    if not table or not isinstance(table, dict):
        return None
    norm = _norm(target)
    if not norm:
        return None
    for page, rows in table.items():
        if not isinstance(rows, dict):
            continue
        for row, cols in rows.items():
            if not isinstance(cols, dict):
                continue
            for col in ("left", "right"):
                if _norm(cols.get(col, "")) == norm:
                    return (str(page), str(row), col)
    return None


def _btn_norm(s) -> str:
    """Strip whitespace and CJK/ASCII punctuation so OCR '同意。' == '同意'."""
    t = _norm(s)
    return re.sub(r"[。．.、，,!！?？:：;；'\"“”‘’·•]+", "", t)


class GameFlowError(RuntimeError):
    pass


class GameFlow:
    """7:04 AM Chinese game login (the only Sept 1 run that reached IN GAME),
    plus the 7:07 right-ok-after-character click.

    RapidOCR drives 選擇驗證方法 / PURPLE簡易驗證 / 同意. PNG templates
    never close LC. After the character image, only the right-column ok.
    """

    def __init__(self, bot, lang: str = "auto"):
        self.bot = bot
        hint = (getattr(bot, "lang", None) or lang or "auto")
        self.lang = hint if hint in LANGS else "ko"
        # L0: language-invariant clicks + OR-list verify — do not chase UI lang
        # every tick (that churn caused wrong WinOCR packs / wrong word lists).
        cfg = getattr(bot, "cfg", None) or {}
        policy = str(cfg.get("lang_policy") or "").strip().upper()
        self._lang_auto = policy not in ("L0", "LOCK", "FIXED")
        if not self._lang_auto:
            log.info("lang_policy=%s — UI lang auto-detect disabled (locked=%s)",
                     policy or "L0", self.lang)
        self.state = "SECURITY"        # splash may still be up at start
        self.state_since = _now()
        self.deadline = _now() + TOTAL_BUDGET
        self.retries = 0
        self.done = False
        self.error = None
        self._agreement_seen = False   # lets the caller stop security-splash handling
        self._security_passed = False  # once we leave SECURITY, never re-enter
        self._topmost = False
        self._sec_shaken = False
        self._sec_shaken_at = 0.0
        self._sec_shake_count = 0
        self._devreg_shake_count = 0
        self._devreg_shaken_at = 0.0
        self._sec_misses = 0
        self._tick_det = ""
        self._device_reg_clicked = False
        self._sms_told = False
        self._restart_requested = False
        self._resize_shaken = False
        self._boot_shake_done = False  # one shake after AUTH relaunch
        self._boot_dialog_since = 0.0  # when dialog-size shell first seen
        self._boot_screen_sig = None   # frame sig at dialog-size entry
        self._boot_auth_wait_logged = False
        self._boot_hunt_since = 0.0    # armed template-hunt start
        self._game_size_normalized = False
        self._game_size_normalize_at = 0.0
        self._device_reg_ignore_count = 0
        self._auth_escape_relaunch = False
        self._agree_fixed_fails = 0
        self._agree_fixed_pending = False
        # After page + server-name clicks the remaining dialogs (OK / Yes /
        # Confirm / Start) are English-only. Stop matching 是/確認/확인.
        self._buttons_en_only = False
        # per-state memory (reset on every state change)
        self._scroll_rounds = 0
        self._page_clicks = 0
        self._page_sig = None
        self._server_clicks = 0
        self._server_ok_clicks = 0
        self._server_reconnect_count = 0
        self._char_clicks = 0
        self._start_clicked = False
        self._start_at = 0.0
        self._loading_char_clicked = False
        self._loading_ok_clicked = False
        self._loading_final_ok_clicked = False
        self._loading_char_at = 0.0
        self._char_ok_clicked = False
        # cross-tick caches
        self._ocr_cache = None          # full-frame OCR lines for this tick
        self._last_anchor = None
        self._last_popup_at = 0.0
        self.anchors = self._load_anchors()
        self._server_table = self._load_server_table()
        self._char_templates = self._load_char_templates()
        missing = [k for k in _ANCHOR_FILES if k not in self.anchors]
        if missing:
            log.warning("anchors missing (OCR fallback will be used): %s", missing)
        log.info("character templates loaded: %d", len(self._char_templates))
        if not interception.ready() and not interception.init():
            raise GameFlowError(
                "Interception driver is REQUIRED for gameflow but failed to init")
        # Claim topmost IMMEDIATELY: the game must be the visible, focused
        # window for the whole flow (splash -> dialogs -> character). Other
        # topmost overlays (ToDesk, Purple overlay agents) and windows raised
        # during the splash sequence can steal the top band at any time, so
        # tick() re-asserts it continuously. Released only by release().
        if not self._ensure_on_top():
            log.warning("could not bring game window to top on start")
        log.info("GameFlow ready: lang=%s (auto-detect ko/en/zh-TW/zh-CN) "
                 "anchors=%s server_table=%s",
                 self.lang, sorted(self.anchors.keys()),
                 "loaded" if self._server_table else "none")

    @property
    def restart_requested(self) -> bool:
        return bool(self._restart_requested)

    # ------------------------------------------------------------------
    # resources
    # ------------------------------------------------------------------
    def _load_anchors(self) -> dict:
        out = {}
        dirs = [ANCHOR_DIR] + [os.path.join(ANCHOR_DIR, lg) for lg in LANGS]
        for name, files in _ANCHOR_FILES.items():
            multi = name in _MULTI_FILE_ANCHORS
            for d in dirs:
                for fn in files:
                    p = os.path.join(d, fn)
                    if os.path.exists(p):
                        img = cv2.imread(p)
                        if img is not None:
                            if multi:
                                out.setdefault(name, []).append(img)
                            else:
                                out[name] = img
                                break
                if name in out and not multi:
                    break
        return out

    def _load_char_templates(self) -> list:
        """Load the character-select sprites (RGBA renders of the class
        avatars) as (name, filled_bgr) pairs for template matching. The
        alpha channel is opaque so the sprite is used directly."""
        out = []
        d = os.path.dirname(ANCHOR_DIR) + os.sep + "character"
        cfg_dir = self.bot.cfg.get("character_dir")
        for base in (cfg_dir, d):
            if not base or not os.path.isdir(base):
                continue
            for fn in os.listdir(base):
                if not fn.lower().endswith((".png", ".jpg", ".bmp")):
                    continue
                try:
                    im = cv2.imread(os.path.join(base, fn), cv2.IMREAD_UNCHANGED)
                    if im is None:
                        continue
                    if im.ndim == 3 and im.shape[2] == 4:
                        im = im[:, :, :3]
                    if im.ndim != 3 or im.shape[2] != 3:
                        continue
                    out.append((fn, im))
                except Exception as e:
                    log.warning("bad char template %s: %r", fn, e)
            if out:
                break
        return out

    def _load_server_table(self) -> dict:
        """Load the per-language server-name table. Prefer the detected UI
        language, then other langs that actually have names filled in."""
        order = (self.lang,) + tuple(lg for lg in LANGS if lg != self.lang)
        bases = (SCRIPT_DIR, os.path.join(SCRIPT_DIR, "data"))
        for lang in order:
            for base in bases:
                p = os.path.join(base, "servers_%s.json" % lang)
                data = self._read_server_json(p)
                if data:
                    log.info("loaded server table from %s", p)
                    return data
        return {}

    @staticmethod
    def _read_server_json(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            raw = re.sub(r',\s*([}\]])', r'\1', raw)
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            named = False
            for rows in data.values():
                if not isinstance(rows, dict):
                    continue
                for cols in rows.values():
                    if not isinstance(cols, dict):
                        continue
                    if any((cols.get(c) or "").strip()
                           for c in ("left", "right")):
                        named = True
                        break
                if named:
                    break
            return data if named else {}
        except Exception as e:
            log.warning("failed to load server table %s: %r", path, e)
            return {}

    def _iter_server_table_paths(self):
        """Preferred language first, then every other locale file on disk."""
        lang = getattr(self, "lang", None)
        order = tuple(
            lg for lg in ((lang,) if lang else ()) + LANGS if lg
        )
        seen_lang = set()
        langs = []
        for lg in order:
            if lg in seen_lang:
                continue
            seen_lang.add(lg)
            langs.append(lg)
        bases = (SCRIPT_DIR, os.path.join(SCRIPT_DIR, "data"))
        seen_path = set()
        for lg in langs:
            for base in bases:
                path = os.path.join(base, "servers_%s.json" % lg)
                if path in seen_path:
                    continue
                seen_path.add(path)
                yield path

    def _lookup_server(self, target: str):
        """Find (page, row, col) for the configured server name.

        Search the already-loaded table first, then every servers_*.json
        so a Chinese name still resolves when GameFlow.lang is ko.
        """
        hit = lookup_server_in_table(getattr(self, "_server_table", None), target)
        if hit:
            return hit
        for path in self._iter_server_table_paths():
            data = self._read_server_json(path)
            if not data:
                continue
            hit = lookup_server_in_table(data, target)
            if not hit:
                continue
            self._server_table = data
            log.info("server %r found in %s -> page %s row %s %s",
                     target, path, hit[0], hit[1], hit[2])
            return hit
        return None

    @property
    def win(self):
        return self.bot.game

    # ------------------------------------------------------------------
    # capture / focus
    # ------------------------------------------------------------------
    def _game_at_point(self, sx: int, sy: int) -> bool:
        """True when the game's own process owns whatever is visible at the
        point. Tolerates the game's own child/splash windows (GameGuard's
        $GIVEmeMINT dummy belongs to LC.exe too) but NOT other
        applications - a foreign window on top is reported explicitly."""
        if not self.win or not self.win.valid:
            return False
        hwnd = user32.WindowFromPoint(wt.POINT(sx, sy))
        if not hwnd:
            return False
        GA_ROOT = 2
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root == self.win.hwnd:
            return True
        # same process (GameGuard dummy / splash children) counts as ours
        pid_here = wt.DWORD()
        user32.GetWindowThreadProcessId(root, ctypes.byref(pid_here))
        pid_game = wt.DWORD()
        user32.GetWindowThreadProcessId(self.win.hwnd, ctypes.byref(pid_game))
        if pid_here.value and pid_here.value == pid_game.value:
            return True
        # foreign window on top - name it so the log says WHO covers us
        try:
            import psutil
            pname = psutil.Process(pid_here.value).name()
        except Exception:
            pname = "?"
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(root, cls, 256)
        if not getattr(self, "_cover_warned", False):
            log.warning("game covered at its center by %s (pid=%s, "
                        "class=%s, root=%s)", pname, pid_here.value,
                        cls.value, root)
            self._cover_warned = True
        return False

    def _activate_game_by_input(self) -> bool:
        """Input-only activation for the UIPI case: the bot at medium
        integrity cannot z-order an elevated game's window (SetWindowPos is
        silently ignored), but DEVICE-level input is never blocked.
        Alt+Esc sends the current foreground window (Purple) to the back,
        which surfaces the game - the input equivalent of clicking the
        game's taskbar button."""
        for _ in range(3):
            if not interception.key_down(0x12):    # Alt
                return False
            interception.tap(0x1B)                 # Esc
            interception.key_up(0x12)
            time.sleep(0.5)
            r = self.win.rect
            if self._game_at_point(r.left + r.width // 2,
                                   r.top + r.height // 2):
                log.info("game brought to front via Alt+Esc")
                return True
        return False

    def _ensure_on_top(self) -> bool:
        """Force the GAME window (LC.exe / GLFW30 - never Purple) to the
        foreground and keep it topmost.

        Fast path: if the game already owns its center pixel, only re-assert
        HWND_TOPMOST (no sleep, no Alt+Esc). Heavy uncover (minimize Purple +
        Alt+Esc) runs at most once per ~1.5s to stop flicker thrash.
        """
        if not self.win or not self.win.valid:
            return False
        HWND_TOPMOST = -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        r = self.win.rect
        cx = r.left + r.width // 2
        cy = r.top + r.height // 2
        if self._game_at_point(cx, cy):
            user32.SetWindowPos(self.win.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self._topmost = True
            return True

        now = time.time()
        last = getattr(self, "_last_uncover_at", 0.0)
        if now - last < 1.5:
            # Still covered but cooldown — avoid Alt+Esc spam
            return False
        self._last_uncover_at = now

        # Best-effort TOPMOST (may be ignored under UIPI)
        user32.SetWindowPos(self.win.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self._topmost = True
        time.sleep(0.08)
        if self._game_at_point(cx, cy):
            return True

        # Purple often covers LC under UIPI — minimize via Interception first
        mini = getattr(self.bot, "_minimize_purple_for_game", None)
        if callable(mini):
            try:
                mini()
            except Exception:
                pass
        ok = self._activate_game_by_input()
        if ok:
            user32.SetWindowPos(self.win.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            try:
                import psutil
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(self.win.hwnd,
                                                ctypes.byref(pid))
                pname = psutil.Process(pid.value).name()
            except Exception:
                pname = "?"
            r2 = self.win.rect
            log.info("game uncovered: hwnd=%s (%s) rect=%dx%d",
                     self.win.hwnd, pname, r2.width, r2.height)
        return ok

    def release(self):
        """Drop the TOPMOST flag (call when the flow finishes or fails)."""
        if getattr(self, "_topmost", False) and self.win and self.win.valid:
            HWND_NOTOPMOST = -2
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
            user32.SetWindowPos(self.win.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self._topmost = False

    def _grab(self) -> Optional[np.ndarray]:
        """Screen grab of the game window rect (DirectX content is only
        visible on screen, not via PrintWindow). BGR ndarray in WINDOW
        coordinates, or None."""
        if not self.win or not self.win.valid:
            return None
        for _ in range(2):
            r = self.win.rect
            cx, cy = r.left + r.width // 2, r.top + r.height // 2
            if not self._game_at_point(cx, cy):
                self._ensure_on_top()
            try:
                img = ImageGrab.grab(
                    bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
            except Exception as e:
                log.warning("grab failed: %r", e)
                time.sleep(0.3)
                continue
            arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            if arr.mean() < 4.0:  # black frame -> covered / not rendered yet
                self._ensure_on_top()
                time.sleep(0.3)
                continue
            return arr
        return None

    # ------------------------------------------------------------------
    # coordinates
    # ------------------------------------------------------------------
    def _game_click_geom(self) -> str:
        cfg = getattr(self.bot, "cfg", None) or {}
        return normalize_geom_mode(cfg.get("game_click_geom"), GEOM_AUTO)

    def _window_ratio_pt(self, rx: float, ry: float) -> Tuple[int, int]:
        r = self.win.rect
        return window_ratio_to_screen(rx, ry, r.left, r.top, r.width, r.height)

    def _dialog_ratio_pt(self, rx: float, ry: float) -> Tuple[int, int]:
        r = self.win.rect
        hwnd = int(getattr(self.win, "hwnd", 0) or 0)
        return dialog_ratio_pt(
            rx,
            ry,
            hwnd=hwnd,
            outer_left=r.left,
            outer_top=r.top,
            outer_w=r.width,
            outer_h=r.height,
            img=getattr(self, "_last_img", None),
            anchor_match=getattr(self, "_last_anchor", None),
        )

    def _ratio_pt(self, rx: float, ry: float) -> Tuple[int, int]:
        """Map a measured 816x639 window ratio to a live screen point.

        Familiar 816x639 shells keep the original GetWindowRect path.
        Other sizes use the dialog/client mapper (game_click_geom).
        """
        mode = self._game_click_geom()
        if mode == GEOM_WINDOW:
            return self._window_ratio_pt(rx, ry)
        if mode == GEOM_DIALOG:
            return self._dialog_ratio_pt(rx, ry)
        if self._shell_is_familiar():
            return self._window_ratio_pt(rx, ry)
        return self._dialog_ratio_pt(rx, ry)

    def _img_pt_to_screen(self, px: float, py: float) -> Tuple[int, int]:
        """Map a point in the current grab onto the live window.

        The grab is the window rect, but DPI / a mid-shake move can make
        grab size != GetWindowRect. Always scale so OCR/template hits
        stay on the same UI element after a resize."""
        r = self.win.rect
        img = getattr(self, "_last_img", None)
        if img is not None:
            h, w = img.shape[:2]
            if w > 0 and h > 0:
                return (int(r.left + px * r.width / float(w)),
                        int(r.top + py * r.height / float(h)))
        return (int(r.left + px), int(r.top + py))

    def _is_dialog_size(self, r=None) -> bool:
        r = r or (self.win.rect if self.win else None)
        if r is None:
            return False
        return r.width < DIALOG_MAX_W and r.height < DIALOG_MAX_H

    def _shell_is_maximized(self, r=None) -> bool:
        """True when LC is maximized / Aero-snapped (not normal splash)."""
        r = r or (self.win.rect if self.win else None)
        if r is None:
            return False
        try:
            if self.win and user32.IsZoomed(self.win.hwnd):
                return True
        except Exception:
            pass
        return (
            r.width >= SHELL_MAX_W or r.height >= SHELL_MAX_H
            or r.left < -4 or r.top < -4
        )

    def _shell_is_familiar(self, r=None, tol: int = 40) -> bool:
        """True when outer size is near the measured dialog (816x639)."""
        r = r or (self.win.rect if self.win else None)
        if r is None:
            return False
        return (
            abs(r.width - REF_PAGE_W) <= tol
            and abs(r.height - REF_PAGE_H) <= tol
            and r.left >= -2 and r.top >= -2
        )

    def _pin_familiar_shell(self, reason: str = "") -> bool:
        """SW_RESTORE + force 816x639. Required before boot-shake templates.

        Live: LC self-maximizes to 1936x1056@(-8,-8); templates cropped at
        dialog scale never match until the shell is pinned.
        """
        if self._shell_is_maximized():
            try:
                user32.ShowWindow(self.win.hwnd, 9)  # SW_RESTORE
                time.sleep(0.12)
            except Exception:
                pass
        fn = getattr(self.bot, "_normalize_game_shell_size", None)
        if not callable(fn):
            return self._shell_is_familiar()
        ok = bool(fn(reason=reason or "pin_familiar"))
        self._ocr_cache = None
        self._page_sig = None
        return ok or self._shell_is_familiar()

    def _region_px(self, region) -> Tuple[int, int, int, int]:
        r = self.win.rect
        x0, y0, x1, y1 = region
        return (int(x0 * r.width), int(y0 * r.height),
                int(x1 * r.width), int(y1 * r.height))

    # ------------------------------------------------------------------
    # input (Interception only - no fallback by design)
    # ------------------------------------------------------------------
    def _click(self, sx: int, sy: int, label: str = "",
               key: Optional[str] = None, clicks: int = 1) -> bool:
        from positions import canonical_key
        store = getattr(self.bot, "positions", None)
        # key=None → derive from label; key="" → keep absolute coords (table cells)
        if key is None:
            key = canonical_key(label)
        if store and store.is_fixed_game and key:
            xy = store.screen_xy("game", key, self.win)
            if xy:
                sx, sy = xy
                log.info("fixed-position game/%s -> screen %s", key, xy)
        r = self.win.rect if (self.win and self.win.valid) else None
        if r is None:
            log.error("REFUSED click %-14s - game window invalid", label)
            return False
        if not (r.left <= sx < r.right and r.top <= sy < r.bottom):
            # NEVER click blind outside the game window - it would raise
            # whatever window sits there and cascade into focus chaos.
            log.error("REFUSED click %-14s screen=(%d,%d) outside game "
                      "rect=(%d,%d,%d,%d)", label, sx, sy,
                      r.left, r.top, r.right, r.bottom)
            return False
        if not self._game_at_point(sx, sy):
            self._ensure_on_top()
        if int(clicks) >= 2:
            ok = interception.double_click(sx, sy)
            verb = "double-click"
        else:
            ok = interception.click(sx, sy)
            verb = "click"
        if not ok:
            raise GameFlowError(
                "interception.click failed at (%d,%d)" % (sx, sy))
        log.info("%s %-18s screen=(%d,%d) win-rel=(%d,%d)", verb, label, sx, sy,
                 sx - r.left, sy - r.top)
        if store and store.is_dynamic_game and key:
            store.record_screen("game", key, self.win, sx, sy)
        # diagnostic: dump the grab with the click point marked so failed
        # clicks can be post-mortemed (skip in fixed: no locate to debug)
        img = getattr(self, "_last_img", None)
        if img is not None and not (store and store.is_fixed_game):
            try:
                dbg = img.copy()
                px, py = sx - r.left, sy - r.top
                cv2.circle(dbg, (px, py), 12, (0, 0, 255), 2)
                cv2.line(dbg, (px - 18, py), (px + 18, py), (0, 0, 255), 1)
                cv2.line(dbg, (px, py - 18), (px, py + 18), (0, 0, 255), 1)
                cv2.imwrite(os.path.join(self.bot.debug_dir,
                                         "last_click.png"), dbg)
            except Exception:
                pass
        return True

    def _click_ratio(self, rx: float, ry: float, label: str):
        sx, sy = self._ratio_pt(rx, ry)
        self._click(sx, sy, label)

    def _try_fixed(self, key: str, label: str, clicks: int = 1) -> bool:
        """Click a saved game-window ratio. State detection still selected
        this handler; only the control locate step is skipped."""
        store = getattr(self.bot, "positions", None)
        if not store or not store.is_fixed_game:
            return False
        xy = store.screen_xy("game", key, self.win)
        if not xy:
            return False
        log.info("fixed-position skip-detect game/%s", key)
        # Pass key explicitly so labels like ok(server-confirm-fixed) are
        # not remapped to game/server by canonical_key.
        return self._click(xy[0], xy[1], label, key=key, clicks=clicks)

    def _fixed_mode(self) -> bool:
        store = getattr(self.bot, "positions", None)
        return bool(store and store.is_fixed_game)

    def _has_fixed(self, key: str) -> bool:
        store = getattr(self.bot, "positions", None)
        return bool(store and store.is_fixed_game and store.lookup("game", key))

    def _settle(self, slow: float) -> None:
        time.sleep(0.18 if self._fixed_mode() else slow)

    # ------------------------------------------------------------------
    # detection
    # ------------------------------------------------------------------
    def _match_anchor(self, img: np.ndarray, name: str,
                      thresh: float = MATCH_THRESH) -> Optional[dict]:
        tpl = self.anchors.get(name)
        if tpl is None:
            return None
        templates = tpl if isinstance(tpl, list) else [tpl]
        # candidate scales: window-height-relative sweep (proportional UI)
        # PLUS absolute scales (fixed-size dialogs) and width-relative
        base_h = img.shape[0] / REF_H
        base_w = img.shape[1] / REF_W
        cands = {round(base_h * m, 4) for m in SCALE_SWEEP}
        cands |= {round(base_w * m, 4) for m in SCALE_SWEEP}
        cands |= {1.0}
        best = None
        for tpl in templates:
            for s in sorted(cands):
                if s <= 0.05:
                    continue
                t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                th, tw = t.shape[:2]
                if th < 8 or tw < 8 or th >= img.shape[0] or tw >= img.shape[1]:
                    continue
                res = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if best is None or mv > best[0]:
                    best = (mv, ml, tw, th, s)
        if best and best[0] >= thresh:
            found = {"score": float(best[0]), "x": best[1][0], "y": best[1][1],
                     "w": best[2], "h": best[3], "scale": best[4]}
            self._last_anchor = found
            return found
        return None

    def _match_boot_shake_status(self, img: np.ndarray) -> Optional[dict]:
        """OCR-free match of 安全設定登録中 / 裝置登錄確認中 status crops.

        Templates were cropped at familiar dialog scale. Sweep absolute scales
        PLUS grab-height-relative scales so a still-large shell can match.
        """
        tpl = self.anchors.get("boot_shake")
        if tpl is None:
            return None
        templates = tpl if isinstance(tpl, list) else [tpl]
        kinds = ("security", "device")
        base_h = float(img.shape[0]) / float(REF_PAGE_H)
        scales = set(BOOT_SHAKE_SCALES)
        for m in (0.80, 0.90, 1.00, 1.10, 1.20, 1.35, 1.50):
            scales.add(round(base_h * m, 4))
        best = None  # (score, loc, tw, th, scale, kind)
        for idx, t0 in enumerate(templates):
            kind = kinds[idx] if idx < len(kinds) else "boot"
            for s in sorted(scales):
                if s <= 0.05:
                    continue
                t = cv2.resize(t0, None, fx=s, fy=s,
                               interpolation=cv2.INTER_AREA)
                th, tw = t.shape[:2]
                if th < 6 or tw < 6 or th >= img.shape[0] or tw >= img.shape[1]:
                    continue
                res = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if best is None or mv > best[0]:
                    best = (mv, ml, tw, th, s, kind)
        if best and best[0] >= BOOT_SHAKE_THRESH:
            return {
                "score": float(best[0]),
                "x": best[1][0], "y": best[1][1],
                "w": best[2], "h": best[3],
                "scale": best[4],
                "kind": best[5],
            }
        return None

    def _anchor_pt(self, img: np.ndarray, name: str,
                   ref_offset: Tuple[float, float],
                   fallback_ratio: Optional[Tuple[float, float]] = None
                   ) -> Tuple[int, int]:
        """Screen point for a UI element measured relative to a matched
        anchor.

        The anchor match gives the origin's position IN THE GRAB (window
        coords); the element sits at ref_offset (reference pixels, already
        element_video - origin_video) from it, scaled by the matched scale.
        Falls back to a window ratio when the anchor doesn't match."""
        m = self._match_anchor(img, name)
        if m:
            s = m["scale"]
            px = m["x"] + ref_offset[0] * s
            py = m["y"] + ref_offset[1] * s
            return self._img_pt_to_screen(px, py)
        if fallback_ratio is not None:
            return self._ratio_pt(*fallback_ratio)
        return self._ratio_pt(0.5, 0.5)

    def _tick_ocr(self, img: np.ndarray):
        """One RapidOCR pass per tick. Skip WinOCR when Hangul/CJK is already
        on screen — the extra engine (and lazy language-pack init) is what
        made 기기등록/보안설정 shake too late.

        After the server row is clicked the remaining buttons are English,
        so English WinOCR is forced even if the title bar still has CJK."""
        if self._ocr_cache is None:
            rapid = getattr(self.bot, "rapid_ocr", None)
            try:
                if rapid is not None:
                    self._ocr_cache = self._rapid_ocr_img(img, rapid) or []
                else:
                    self._ocr_cache = []
            except Exception as e:
                log.warning("rapid ocr failed: %r", e)
                self._ocr_cache = []
            blob = "".join(getattr(ln, "text", "") or ""
                           for ln in (self._ocr_cache or []))
            detected = detect_ui_lang(blob) if self._lang_auto else None
            if detected and self._lang_auto and not self._buttons_en_only:
                self._apply_detected_lang(detected)
            body = has_hangul(blob) or has_cjk(blob)
            need_win = self._buttons_en_only or not body
            if need_win:
                # 7 AM Chinese: RapidOCR already reads 選擇驗證方法 /
                # PURPLE簡易驗證 / 同意. Do not overlay Korean WinOCR on
                # a CJK screen. If RapidOCR is empty, use the detected
                # UI language (zh-TW / zh-CN / ko / en), not a ko-first loop.
                win_lang = "en" if self._buttons_en_only else (
                    detected or (self.lang if self.lang in LANGS else "en"))
                pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                extra = self._winocr_recognize(pil, win_lang)
                if extra:
                    self._ocr_cache = list(self._ocr_cache or []) + list(extra)
                if self._lang_auto and not self._buttons_en_only:
                    blob2 = "".join(getattr(ln, "text", "") or ""
                                    for ln in (self._ocr_cache or []))
                    detected2 = detect_ui_lang(blob2)
                    if detected2:
                        self._apply_detected_lang(detected2)
            self._ocr_cache = self._cluster_ocr_rows(self._ocr_cache)
        return self._ocr_cache

    def _rapid_ocr_img(self, img: np.ndarray, rapid,
                       max_side: Optional[int] = None) -> list:
        """Downscale the grab so RapidOCR finishes in time for a shake.
        max_side=0 keeps native resolution (needed for the tiny 同意 button)."""
        h, w = img.shape[:2]
        scale = 1.0
        work = img
        m = max(h, w)
        cap = OCR_MAX_SIDE if max_side is None else max_side
        if cap and m > cap:
            scale = cap / float(m)
            work = cv2.resize(work, (max(1, int(w * scale)),
                                     max(1, int(h * scale))),
                              interpolation=cv2.INTER_AREA)
        pil = Image.fromarray(cv2.cvtColor(work, cv2.COLOR_BGR2RGB))
        lines = rapid.recognize(pil) or []
        if scale != 1.0 and lines:
            inv = 1.0 / scale
            for ln in lines:
                for wd in getattr(ln, "words", []) or []:
                    wd.x = int(wd.x * inv)
                    wd.y = int(wd.y * inv)
                    wd.w = int(wd.w * inv)
                    wd.h = int(wd.h * inv)
        return lines

    def _winocr_recognize(self, pil, lang: str):
        fn = getattr(self.bot, "winocr_for", None)
        try:
            if callable(fn):
                eng = fn(lang)
            else:
                eng = getattr(self.bot, "ocr", None)
            if eng is None:
                return []
            return eng.recognize(pil) or []
        except Exception as e:
            log.warning("winocr(%s) failed: %r", lang, e)
            return []

    def _lock_en_buttons(self):
        """Page number + server name have been clicked. Later dialogs
        (confirm / loading / character / start) are English-only."""
        if self._buttons_en_only:
            return
        self._buttons_en_only = True
        self._lang_auto = False
        prev = self.lang
        self.lang = "en"
        try:
            self.bot.lang = "en"
        except Exception:
            pass
        self._ocr_cache = None
        log.info("post-server buttons locked to English (was %s)", prev)

    def _apply_detected_lang(self, lang: str):
        if not getattr(self, "_lang_auto", True):
            return
        if self._buttons_en_only:
            return
        if lang not in LANGS:
            return
        if lang == self.lang:
            return
        prev = self.lang
        self.lang = lang
        try:
            self.bot.lang = lang
        except Exception:
            pass
        table = self._load_server_table()
        if table:
            self._server_table = table
        log.info("UI language auto-detected: %s -> %s", prev, lang)

    def _words(self, key: str) -> List[str]:
        """Word list for OCR. Pre-server screens are multilingual; after
        the page + server-name clicks only English button labels are used."""
        if self._buttons_en_only:
            d = WORDS.get(key, {}) or {}
            return list(d.get("en") or [])
        return self._all_words(key)

    def _all_words(self, key: str) -> List[str]:
        """Phrases for every UI language. The launcher config may be ko
        while the game splash is zh-TW (選擇驗證方法 / PURPLE簡易驗證)."""
        d = WORDS.get(key, {}) or {}
        out = []
        for v in d.values():
            out.extend(v)
        return out

    @staticmethod
    def _line_text(ln) -> str:
        return _norm("".join(w.text for w in ln.words))

    @staticmethod
    def _cluster_ocr_rows(lines):
        """RapidOCR emits one box per OcrLine, so phrases like '인증 수단'
        never sit on a single line. Group boxes that share a row (similar
        y-center) into reading-order lines. WinOCR already returns rows;
        leave those alone."""
        if not lines or len(lines) < 2:
            return lines
        multi = sum(1 for ln in lines if len(getattr(ln, "words", []) or []) > 1)
        if multi >= max(2, len(lines) // 3):
            return lines
        boxes = []
        for ln in lines:
            boxes.extend(getattr(ln, "words", None) or [])
        if not boxes:
            return lines
        boxes.sort(key=lambda w: (w.y, w.x))
        rows = []
        for w in boxes:
            cy = w.y + w.h / 2.0
            placed = False
            for row in rows:
                rcy = sum(x.y + x.h / 2.0 for x in row) / len(row)
                rh = sum(x.h for x in row) / len(row)
                if abs(cy - rcy) <= max(8.0, rh * 0.55):
                    row.append(w)
                    placed = True
                    break
            if not placed:
                rows.append([w])
        out = []
        for row in rows:
            row.sort(key=lambda w: w.x)
            out.append(OcrLine(words=row))
        return out

    def _ocr_tokens(self, lines) -> List[str]:
        return [_norm(w.text) for ln in lines
                for w in getattr(ln, "words", []) if _norm(w.text)]

    def _ocr_blob(self, lines) -> str:
        ordered = sorted(lines, key=lambda ln: (ln.y, ln.x))
        return _norm("".join(self._line_text(ln) for ln in ordered))

    @staticmethod
    def _token_hit(needle: str, tokens: List[str], fuzzy: float = 0.7) -> bool:
        n = _norm(needle)
        if not n:
            return False
        variants = {n}
        for src, alts in _OCR_VARIANTS.items():
            if src in n:
                for alt in alts:
                    variants.add(n.replace(src, alt))
            for alt in alts:
                if alt in n:
                    variants.add(n.replace(alt, src))
        for v in variants:
            for t in tokens:
                if v in t:
                    return True
                if min(len(v), len(t)) >= 2 and _ratio(v, t) >= fuzzy:
                    return True
        return False

    def _phrase_present(self, lines, phrases, token_groups=None,
                        fuzzy: float = 0.74) -> bool:
        """Match a phrase even when OCR splits it across boxes.

        1) exact substring on the full-screen concatenated blob
        2) fuzzy window on that blob / per-box text (OCR substitutions)
        3) all tokens in a group present somewhere on screen
        """
        needles = [_norm(p) for p in (phrases or []) if _norm(p)]
        expanded = []
        for n in needles:
            variants = {n}
            for src, alts in _OCR_VARIANTS.items():
                extra = set()
                for s in variants:
                    if src in s:
                        for alt in alts:
                            extra.add(s.replace(src, alt))
                variants |= extra
            expanded.extend(variants)
        needles = list(dict.fromkeys(expanded))
        blob = self._ocr_blob(lines)
        tokens = self._ocr_tokens(lines)
        for n in needles:
            if n in blob:
                return True
            if len(n) < 4:
                continue
            for t in tokens:
                if n in t or (len(t) >= 4 and _ratio(n, t) >= fuzzy):
                    return True
            L = len(n)
            if blob and L <= len(blob):
                for i in range(0, len(blob) - L + 1):
                    if _ratio(n, blob[i:i + L]) >= fuzzy:
                        return True
        for group in (token_groups or []):
            gn = [_norm(t) for t in group if _norm(t)]
            if gn and all(self._token_hit(g, tokens) for g in gn):
                return True
        return False

    @staticmethod
    def _latin_label(text: str) -> bool:
        t = _btn_norm(text)
        if not t or has_cjk(t) or has_hangul(t):
            return False
        return bool(re.search(r"[A-Za-z]", t))

    @staticmethod
    def _en_btn_match(ocr_text: str, needle: str) -> bool:
        """Whole-word English match. Rejects CJK (是/確認) and 'OK' inside
        unrelated tokens."""
        t = _btn_norm(ocr_text)
        n = _btn_norm(needle)
        if not t or not n:
            return False
        if has_cjk(t) or has_hangul(t):
            return False
        tl, nl = t.lower(), n.lower()
        if tl == nl:
            return True
        return re.search(r"(?i)(?:^|[^a-z])" + re.escape(nl) + r"(?:[^a-z]|$)",
                         t) is not None

    def _find_words(self, img: np.ndarray, key: str,
                    lines=None, region=None) -> List[tuple]:
        """[(word, cx, cy, w, h)] image-pixel hits for a word table."""
        words = [_norm(w) for w in self._words(key) if _norm(w)]
        if not words:
            return []
        if lines is None:
            lines = self._tick_ocr(img)
        off_x = off_y = 0
        if region is not None:
            x0, y0, x1, y1 = region
        else:
            x0 = y0 = 0
            x1, y1 = img.shape[1], img.shape[0]
        off_x, off_y = x0, y0
        en_only = self._buttons_en_only
        btn_keys = ("ok_button", "server_confirm", "start_button",
                    "continue_popup")
        y_min = int(img.shape[0] * 0.40) if (en_only and key in btn_keys) else 0
        hits = []
        for ln in lines:
            lt = self._line_text(ln)
            if not lt:
                continue
            for w in ln.words:
                wt_ = _norm(w.text)
                if not wt_:
                    continue
                cx = off_x + w.x + w.w // 2
                cy = off_y + w.y + w.h // 2
                if not (x0 <= cx < x1 and y0 <= cy < y1):
                    continue
                if cy < y_min:
                    continue
                if en_only:
                    if not self._latin_label(wt_) and not self._latin_label(lt):
                        continue
                    for t in words:
                        if self._en_btn_match(wt_, t) or self._en_btn_match(lt, t):
                            hits.append((t, cx, cy, w.w, w.h))
                            break
                else:
                    for t in words:
                        if t in lt or t in wt_:
                            hits.append((t, cx, cy, w.w, w.h))
                            break
        return hits

    def _detect_persons(self, img: np.ndarray) -> list:
        det = getattr(self.bot, "_person_detector", None)
        if det is None:
            return []
        try:
            # detect() expects an HxWx3 uint8 RGB ndarray — NOT a PIL image
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return det.detect(rgb) or []
        except Exception:
            return []

    def _match_char_template(self, img: np.ndarray) -> Optional[dict]:
        """Multi-scale alpha-filled CCOEFF match of the character select
        sprites. Searches the top-left character-holder band and returns
        {score, x, y, w, h, scale, name} in IMAGE coords, or None."""
        if not self._char_templates:
            return None
        # the character renders sit in the top-left holder band; searching
        # the full frame wastes time and can latch onto chrome (OK/Cancel)
        H, W = img.shape[:2]
        x1 = int(W * 0.60)
        y1 = int(H * 0.72)
        roi = img[:y1, :x1]
        best = None
        for name, tpl in self._char_templates:
            th, tw = tpl.shape[:2]
            for s in CHAR_TM_SCALES:
                t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                th2, tw2 = t.shape[:2]
                if th2 < 8 or tw2 < 8 or th2 >= roi.shape[0] or tw2 >= roi.shape[1]:
                    continue
                res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(res)
                if best is None or v > best["score"]:
                    best = {"score": float(v), "x": int(loc[0]), "y": int(loc[1]),
                            "w": int(tw2), "h": int(th2), "scale": float(s),
                            "name": name}
        if best and best["score"] >= CHAR_TM_THRESH:
            # offset from roi back to full-image coords
            best["x"] += 0
            best["y"] += 0
            log.info("char tm match %s score=%.3f scale=%.2f center=(%d,%d) in=%dx%d",
                     best["name"], best["score"], best["scale"],
                     best["x"] + best["w"] // 2, best["y"] + best["h"] // 2,
                     W, H)
            return best
        return None

    _ANCHOR_STATE = {
        "security_splash": "SECURITY",
        # auth_choice templates are NOT used to close (7 AM Chinese OCR path).
        "auth_choice": "PURPLE_AUTH",
        # 기기등록 body/form — shake only, never close+relaunch.
        "device_reg": "DEVICE_REG",
        "agreement_title": "AGREEMENT",
        "server_title": "SERVER_SELECT",
        "connecting": "CONNECT_WAIT",
        "loading": "LOADING",
    }

    def _detect(self, img: np.ndarray) -> str:
        """Hierarchical gates: AUTH OCR (close safety) → templates → OCR confirm.

        Clicks stay ratio/fixed; OCR here is for situation recognition only.
        Full-window auth_choice templates must never alone trigger close.
        """
        armed = getattr(self.bot, "_shake_after_relaunch", False)

        # Confirmed character double-click: wait CHAR_HANDOFF_SECONDS for
        # world load, then INGAME so Manmabot can start the farm bot.
        if self._char_login_committed():
            ok_at = float(getattr(self, "_start_at", 0.0) or 0.0)
            waited = (_now() - ok_at) if ok_at else 0.0
            if waited >= CHAR_HANDOFF_SECONDS:
                log.info("char double-click settled (%.1fs) → INGAME "
                         "(hand off to farm bot)", waited)
                return "INGAME"
            return ""  # keep waiting; do not force LOADING/CHARACTER

        # --- Gate A: post-AUTH-relaunch boot flash (template-only, OCR-free) ---
        # 安全設定登録中 / 裝置登錄確認中 flash briefly before AUTH. Hunt with
        # dense template match only — OCR here would miss the window.
        # Hunt clock is owned by tick() (starts only at familiar 816x639).
        if armed and not getattr(self, "_boot_shake_done", False):
            m_boot = self._match_boot_shake_status(img)
            if m_boot:
                kind = m_boot.get("kind") or "boot"
                st = "SECURITY" if kind == "security" else "DEVICE_REG"
                log.info("boot_shake status tpl=%s score=%.3f → %s",
                         kind, m_boot["score"], st)
                return st
            m_sec = self._match_anchor(img, "security_splash")
            if (m_sec and m_sec["score"] >= MATCH_THRESH
                    and not self._security_passed):
                log.info("SECURITY via template (post-relaunch boot) "
                         "score=%.3f", m_sec["score"])
                return "SECURITY"
            m_dev = self._match_anchor(img, "device_reg")
            if m_dev and m_dev["score"] >= MATCH_THRESH:
                log.info("DEVICE_REG via template (post-relaunch boot) "
                         "score=%.3f", m_dev["score"])
                return "DEVICE_REG"
            # Stay OCR-free while hunting the flash status bar.
            hunt_t0 = float(getattr(self, "_boot_hunt_since", 0) or 0)
            if hunt_t0 and (_now() - hunt_t0) < BOOT_SHAKE_HUNT_S:
                return self.state if self.state in (
                    "SECURITY", "DEVICE_REG", "LOADING") else "SECURITY"

        # --- Gate B: 퍼플간편인증 / PURPLE簡易驗證 alone → close+relaunch ---
        # Title (인증 수단 선택) is helpful but no longer required; ko/zh
        # purple-simple text is enough. After relaunch, never close again
        # while still inside the boot-shake hunt window above.
        if not armed and (
                self._auth_choice_screen(img) or self._purple_auth_screen(img)):
            log.info("PURPLE_AUTH (퍼플간편인증 / PURPLE簡易驗證) → close+relaunch")
            return "PURPLE_AUTH"

        # --- Gate C: template / anchor (language-invariant layout) ---
        best_name, best_score = None, 0.0
        for name in self._ANCHOR_STATE:
            if name == "auth_choice":
                continue  # never close from template alone
            m = self._match_anchor(img, name)
            if m and m["score"] > best_score:
                best_name, best_score = name, m["score"]

        if best_name is not None and best_score >= MATCH_THRESH:
            if best_name == "security_splash" and not self._security_passed:
                # Soft OCR confirm when available (avoid mistaking AUTH)
                if self._auth_choice_screen(img) or self._purple_auth_screen(img):
                    return "PURPLE_AUTH"
                log.info("SECURITY via template score=%.3f", best_score)
                return "SECURITY"
            if best_name == "device_reg":
                # Pre-relaunch AUTH_CHOICE UI has a 기기등록 *tile* that
                # matches this template — prefer close+relaunch over ignore.
                if not armed:
                    if self._auth_choice_screen(img) or self._purple_auth_screen(img):
                        log.info("device_reg template on AUTH_CHOICE → PURPLE_AUTH")
                        self._device_reg_ignore_count = 0
                        return "PURPLE_AUTH"
                    # Soft OCR: auth-method title OR purple tile alone
                    lines = self._tick_ocr(img)
                    has_ctx = self._phrase_present(
                        lines,
                        list(self._all_words("device_reg_context")),
                        token_groups=[
                            ["인증", "수단"],
                            ["選擇", "驗證"],
                            ["选择", "验证"],
                            ["驗證", "方法"],
                            ["验证", "方法"],
                            ["认证", "方法"],
                            ["認證", "方式"],
                            ["인증", "방법"],
                        ],
                    )
                    has_purple = self._phrase_present(
                        lines,
                        list(self._all_words("purple_auth")),
                        token_groups=[
                            ["퍼플", "간편"],
                            ["퍼플", "인증"],
                            ["purple", "簡易"],
                            ["purple", "简易"],
                            ["簡易", "驗證"],
                            ["简易", "验证"],
                        ],
                    )
                    if has_ctx or has_purple:
                        log.info("device_reg template + soft AUTH OCR "
                                 "(ctx=%s purple=%s) → PURPLE_AUTH",
                                 has_ctx, has_purple)
                        self._device_reg_ignore_count = 0
                        self._auth_escape_relaunch = True
                        return "PURPLE_AUTH"
                    n = int(getattr(self, "_device_reg_ignore_count", 0) or 0) + 1
                    self._device_reg_ignore_count = n
                    log.info("DEVICE_REG template ignored until AUTH relaunch "
                             "(score=%.3f count=%d)", best_score, n)
                    # Live failure mode: tile matches forever, AUTH OCR misses.
                    # After a few ignores on dialog size → close+relaunch once.
                    if n >= 3 and self._is_dialog_size():
                        log.warning(
                            "device_reg template x%d (no AUTH OCR) → "
                            "PURPLE_AUTH escape (close+relaunch)", n)
                        self._device_reg_ignore_count = 0
                        self._auth_escape_relaunch = True
                        return "PURPLE_AUTH"
                    # fall through to Gate D / other anchors
                else:
                    if (self._auth_choice_screen(img)
                            or self._purple_auth_screen(img)):
                        return "PURPLE_AUTH"
                    log.info("DEVICE_REG via template score=%.3f", best_score)
                    self._device_reg_ignore_count = 0
                    return "DEVICE_REG"
            if best_name == "agreement_title":
                log.info("AGREEMENT via template score=%.3f", best_score)
                return "AGREEMENT"
            if best_name == "server_title":
                # After confirm OK, server_title template often still matches
                # while the character-login UI is already up — advance.
                if self._post_server_char_ready(img):
                    log.info("SERVER_SELECT template but char UI ready → CHARACTER")
                    return "CHARACTER"
                if int(getattr(self, "_server_ok_clicks", 0) or 0) >= 2:
                    log.info("SERVER_SELECT after confirm x%d → LOADING/CHAR",
                             self._server_ok_clicks)
                    return "LOADING"
                log.info("SERVER_SELECT via template score=%.3f", best_score)
                return "SERVER_SELECT"
            if best_name == "connecting":
                return "CONNECT_WAIT"
            if best_name == "loading":
                if getattr(self, "_char_ok_clicked", False):
                    return ""
                if self._post_server_char_ready(img):
                    return "CHARACTER"
                # Fixed mode used to skip CHARACTER forever here — allow it
                # whenever we already confirmed a server.
                if int(getattr(self, "_server_ok_clicks", 0) or 0) >= 1:
                    if self._has_fixed("char") or self._match_char_template(img):
                        return "CHARACTER"
                return "LOADING"
            if best_name != "device_reg":
                state = self._ANCHOR_STATE.get(best_name)
                if state:
                    return state

        # --- Gate D: OCR confirm / fallback (OR lists, all langs) ---
        if self._device_reg_screen(img):
            return "DEVICE_REG"
        if self._security_splash_screen(img) and not self._security_passed:
            return "SECURITY"
        if self._find_words(img, "agree_dialog"):
            return "AGREEMENT"
        if self._find_words(img, "server_dialog"):
            return "SERVER_SELECT"
        if self._find_words(img, "ingame"):
            return "INGAME"
        # Post-server: sticky server OCR must not block character select
        if self._post_server_char_ready(img):
            return "CHARACTER"
        if (int(getattr(self, "_server_ok_clicks", 0) or 0) >= 2
                and getattr(self, "_agreement_seen", False)
                and not self._char_login_committed()):
            return "LOADING"
        return ""

    def _char_login_committed(self) -> bool:
        """True after the character was double-clicked into the world."""
        return bool(getattr(self, "_char_ok_clicked", False)
                    or getattr(self, "_start_clicked", False))

    def _post_server_char_ready(self, img: np.ndarray) -> bool:
        """True when server was confirmed and character-select UI is present."""
        if int(getattr(self, "_server_clicks", 0) or 0) <= 0:
            return False
        if int(getattr(self, "_server_ok_clicks", 0) or 0) < 1:
            return False
        if getattr(self, "_char_ok_clicked", False):
            return False
        try:
            if self._match_char_template(img) is not None:
                return True
        except Exception:
            pass
        try:
            if self._detect_persons(img):
                return True
        except Exception:
            pass
        # Fixed dict path: after confirm, char screen is expected even if
        # templates/YOLO are empty — let CHARACTER handler use fixed coords.
        if (int(getattr(self, "_server_ok_clicks", 0) or 0) >= 2
                and self._has_fixed("char")):
            return True
        return False

    # ------------------------------------------------------------------
    # popups (may overlay any state)
    # ------------------------------------------------------------------
    def _dismiss_popups(self, img: np.ndarray):
        if _now() - self._last_popup_at < POPUP_COOLDOWN:
            return
        self._last_popup_at = _now()      # throttle the OCR cost too
        hits = [h for h in self._find_words(img, "continue_popup")
                if h[3] <= 220]
        if hits:
            _, cx, cy, _, _ = hits[0]
            sx, sy = self._img_pt_to_screen(cx, cy)
            self._click(sx, sy, "popup:" + hits[0][0])
            self._ocr_cache = None
            time.sleep(0.4)

    # ------------------------------------------------------------------
    # state handlers - act only when the dialog is really there
    # ------------------------------------------------------------------
    def _agree_btn_ratio(self) -> Tuple[float, float]:
        cmap = getattr(self.bot, "click_map", None) or {}
        entry = cmap.get("agree_zh") or cmap.get("agree")
        if entry and "rx" in entry and "ry" in entry:
            return (float(entry["rx"]), float(entry["ry"]))
        if self.lang in ("zh-TW", "zh-CN"):
            return R_AGREE_BTN_ZH
        return R_AGREE_BTN

    def _label_is_disagree(self, text: str) -> bool:
        t = _btn_norm(text)
        if not t:
            return False
        for x in self._words("agree_exclude"):
            n = _btn_norm(x)
            if n and len(n) >= 2 and n in t:
                return True
        if "同意" in t and ("不" in t or "拒" in t):
            return True
        tl = t.lower()
        if "agree" in tl and "dis" in tl:
            return True
        if "동의" in t and ("안" in t or "않" in t):
            return True
        return False

    def _label_is_agree(self, text: str) -> bool:
        t = _btn_norm(text)
        if not t or self._label_is_disagree(t):
            return False
        # Button labels are 2–8 chars. Longer hits are the terms body
        # (e.g. 「若同意所有事項時」), not 同意 / 不同意.
        if len(t) > 8:
            return False
        for w in self._words("agree_button"):
            n = _btn_norm(w)
            if n and (t == n or n in t):
                return True
        return False

    def _ocr_agree_buttons(self, img: np.ndarray) -> list:
        """Full-resolution OCR of the dialog footer only.

        Window-wide RapidOCR is downscaled to OCR_MAX_SIDE=640; at that
        size the 24px 同意 glyph disappears while 32px 不同意 remains, so
        the picker either clicks 不同意 or falls back to a bad ratio."""
        H, W = img.shape[:2]
        y0, y1 = int(H * 0.58), min(H, int(H * 0.78))
        x0, x1 = int(W * 0.25), int(W * 0.75)
        if y1 <= y0 or x1 <= x0:
            return []
        crop = img[y0:y1, x0:x1]
        rapid = getattr(self.bot, "rapid_ocr", None)
        if rapid is None or crop.size == 0:
            return []
        try:
            lines = self._rapid_ocr_img(crop, rapid, max_side=0) or []
        except Exception as e:
            log.warning("agree footer ocr failed: %r", e)
            return []
        for ln in lines:
            for w in getattr(ln, "words", []) or []:
                w.x += x0
                w.y += y0
        return lines

    def _agree_button_hit(self, img: np.ndarray, lines) -> Optional[tuple]:
        """Pick 同意 / 동의합니다 / Agree. Never 不同意 / Disagree.

        同意 sits LEFT of 不同意. Ignore terms-body lines; only the bottom
        button row. If OCR sees only 不同意, click a fixed gap to its left."""
        H, W = img.shape[:2]
        y_min = int(H * 0.52)
        x_max = int(W * 0.52)
        hits = []  # (exact, cx, cy, text)
        disagree = []
        for ln in lines:
            for w in getattr(ln, "words", []) or []:
                cx = w.x + w.w // 2
                cy = w.y + w.h // 2
                if cy < y_min:
                    continue
                wt = _btn_norm(w.text)
                if not wt:
                    continue
                if self._label_is_disagree(wt):
                    disagree.append((cx, cy, wt))
                    continue
                if not self._label_is_agree(wt):
                    continue
                if self.lang in ("zh-TW", "zh-CN") and cx > x_max:
                    continue
                exact = any(_btn_norm(a) == wt for a in self._words("agree_button"))
                hits.append((exact, cx, cy, wt))
        if hits:
            hits.sort(key=lambda h: (not h[0], h[1]))
            exact, cx, cy, text = hits[0]
            log.info("agree button: %r exact=%s at img=(%d,%d) lang=%s",
                     text, exact, cx, cy, self.lang)
            return (text, cx, cy)
        if disagree:
            dx = int(W * AGREE_LEFT_OF_DISAGREE)
            cx, cy, text = min(disagree, key=lambda p: p[0])
            ax, ay = cx - dx, cy
            log.info("agree inferred left of %r by %dpx -> img=(%d,%d)",
                     text, dx, ax, ay)
            return ("left-of:" + text, ax, ay)
        return None

    def _h_agreement(self, img: np.ndarray):
        """Agree: fixed/ratio first (same tick); OCR only after fails.

        Familiar 816x639 shells must not burn ticks on multi-round wheel OCR.
        """
        if getattr(self, "_agree_fixed_pending", False):
            self._agree_fixed_pending = False
            self._agree_fixed_fails = int(
                getattr(self, "_agree_fixed_fails", 0) or 0) + 1
            log.info("agree: still on AGREEMENT after fixed/ratio "
                     "(fails=%d) → %s",
                     self._agree_fixed_fails,
                     "OCR next" if self._agree_fixed_fails >= 2 else "retry fixed")

        prefer_fixed = (
            self._has_fixed("agree")
            or self._fixed_mode()
            or bool((getattr(self.bot, "cfg", {}) or {}).get(
                "game_force_size", True))
        )

        # Fixed/ratio path: at most one quick wheel, then click in THIS tick.
        if prefer_fixed:
            if self._scroll_rounds < 1:
                sx, sy = self._ratio_pt(*R_DIALOG_CENTER)
                if interception.wheel(-12, sx, sy):
                    log.info("wheel agreement(fixed) once at (%d,%d)", sx, sy)
                self._scroll_rounds = 1
                time.sleep(0.08)
            fails = int(getattr(self, "_agree_fixed_fails", 0) or 0)
            if fails < 2:
                if self._try_fixed("agree", "agree(fixed)"):
                    self._agree_fixed_pending = True
                    self.retries += 1
                    self._last_act = _now()
                    self._settle(0.35)
                    return
                sx, sy = self._ratio_pt(*self._agree_btn_ratio())
                self._click(sx, sy, "agree(ratio)", key="")
                self._agree_fixed_pending = True
                self.retries += 1
                self._last_act = _now()
                self._settle(0.35)
                return
            log.info("agree: fixed/ratio failed %d times → OCR fallback", fails)
            det = self._match_anchor(img, "agreement_title")
            lines = self._tick_ocr(img)
            btn = self._agree_button_hit(img, self._ocr_agree_buttons(img))
            if btn is None:
                btn = self._agree_button_hit(img, lines)
            if btn is not None:
                label, cx, cy = btn
                sx, sy = self._img_pt_to_screen(cx, cy)
                self._click(sx, sy, "agree(ocr):" + label, key="")
            elif det or self._find_words(img, "agree_dialog"):
                sx, sy = self._ratio_pt(*self._agree_btn_ratio())
                self._click(sx, sy, "agree(ratio-fallback:%s)" % self.lang,
                            key="")
            else:
                return
            self.retries += 1
            self._last_act = _now()
            time.sleep(0.35)
            return

        # Dynamic path: short scroll loop, then OCR/ratio
        scroll_need = 2
        if self._scroll_rounds < scroll_need:
            sx, sy = self._anchor_pt(
                img, "agreement_title", OFF_DIALOG_CENTER, R_DIALOG_CENTER)
            if interception.wheel(-15, sx, sy):
                log.info("wheel agreement round=%d at (%d,%d)",
                         self._scroll_rounds + 1, sx, sy)
            self._scroll_rounds += 1
            time.sleep(0.2)
            sig = self._text_signature(img)
            img2 = self._grab()
            if sig is not None and img2 is not None and \
                    self._text_signature(img2) == sig:
                self._scroll_rounds = scroll_need
            return

        det = self._match_anchor(img, "agreement_title")
        lines = self._tick_ocr(img)
        btn = self._agree_button_hit(img, self._ocr_agree_buttons(img))
        if btn is None:
            btn = self._agree_button_hit(img, lines)
        if btn is not None:
            label, cx, cy = btn
            sx, sy = self._img_pt_to_screen(cx, cy)
            self._click(sx, sy, "agree(ocr):" + label, key="")
        elif det or self._find_words(img, "agree_dialog"):
            sx, sy = self._ratio_pt(*self._agree_btn_ratio())
            self._click(sx, sy, "agree(ratio-fallback:%s)" % self.lang, key="")
        else:
            return
        self.retries += 1
        self._last_act = _now()
        time.sleep(CLICK_SETTLE)

    def _text_signature(self, img: np.ndarray) -> Optional[bytes]:
        m = self._match_anchor(img, "agreement_title")
        if not m:
            return None
        s = m["scale"]
        x0 = int(m["x"] + 8 * s)
        y0 = int(m["y"] + 100 * s)
        x1 = int(min(m["x"] + 280 * s, img.shape[1]))
        y1 = int(min(m["y"] + 230 * s, img.shape[0]))
        if x1 <= x0 or y1 <= y0:
            return None
        crop = img[y0:y1, x0:x1]
        return cv2.resize(crop, (32, 48)).tobytes()

    def _anchor_region(self, img: np.ndarray, name: str,
                       ref_region: Tuple[float, float, float, float],
                       fallback_ratio_region):
        """Pixel region (x0,y0,x1,y1) in the grab, relative to a matched
        anchor; falls back to window ratios when the anchor is not found."""
        m = self._match_anchor(img, name)
        if m:
            s = m["scale"]
            x0, y0, x1, y1 = ref_region
            return (int(m["x"] + x0 * s), int(m["y"] + y0 * s),
                    int(m["x"] + x1 * s), int(m["y"] + y1 * s))
        return self._region_px(fallback_ratio_region)

    def _list_signature(self, img: np.ndarray) -> Optional[bytes]:
        x0, y0, x1, y1 = self._anchor_region(
            img, "server_title", OFF_LIST_REGION, R_LIST_REGION)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        return cv2.resize(crop, (48, 48)).tobytes()

    def _find_server_row(self, img: np.ndarray):
        """Find the target server row by OCR + fuzzy matching.

        Returns (img_x, img_y, score, matched_text) or None.
        Matching strategy (in order):
          1. Exact normalized substring (n in ocr_text)
          2. First + last char match on individual OCR words
          3. Common-char ratio >= 0.6 on individual OCR words
        """
        names = [_norm(n) for n in
                 (self.bot.words_cfg.get("server_name", []) or []) if _norm(n)]
        if not names:
            return None
        m = self._match_anchor(img, "server_title")
        if not m:
            return None
        x0, y0, x1, y1 = self._anchor_region(
            img, "server_title", OFF_LIST_REGION, R_LIST_REGION)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        crop3 = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3),
                           interpolation=cv2.INTER_CUBIC)
        try:
            lines = self._ocr_lines_crop(crop3)
        except Exception as e:
            log.warning("server list ocr failed: %r", e)
            return None
        words = []
        for ln in lines:
            lt = self._line_text(ln)
            if not lt:
                continue
            for w in ln.words:
                wt = _norm(w.text)
                if not wt:
                    continue
                cx = (w.x + w.w // 2) / 3.0
                cy = (w.y + w.h // 2) / 3.0
                words.append({"text": wt, "raw": w.text, "cx": cx, "cy": cy})
        log.info("server list OCR words: %s", [w["text"] for w in words])
        best = None
        best_score = 0.0
        for w in words:
            t = w["text"]
            for n in names:
                score = 0.0
                if n in t or t in n:
                    score = 1.0
                elif len(n) >= 2 and len(t) >= 2:
                    if n[0] == t[0] and n[-1] == t[-1]:
                        score = 0.75
                    common = sum(1 for a, b in zip(n, t) if a == b)
                    ratio = common / max(len(n), len(t))
                    if ratio > score:
                        score = ratio
                if score > best_score:
                    best_score = score
                    best = w
        log.info("server fuzzy match: score=%.2f target=%s result=%s",
                 best_score, names, best["text"] if best else "none")
        if best and best_score >= 0.50:
            ix = int(x0 + best["cx"])
            iy = int(y0 + best["cy"])
            return (ix, iy, best_score, best["raw"])
        return None

    def _ocr_lines_crop(self, crop: np.ndarray):
        """OCR a crop with RapidOCR, falling back to WinOcr when RapidOCR
        is unavailable OR returns nothing (its onnxruntime DLL can fail to
        load in the elevated process)."""
        pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        rapid = getattr(self.bot, "rapid_ocr", None)
        if rapid is not None:
            try:
                lines = rapid.recognize(pil)
                if lines:
                    return lines
            except Exception as e:
                log.warning("rapid ocr failed: %r", e)
        return self.bot.ocr.recognize(pil)

    def _auth_relaunch_max(self) -> int:
        cfg = getattr(self.bot, "cfg", None) or {}
        return int(cfg.get("auth_relaunch_max", AUTH_RELAUNCH_MAX) or AUTH_RELAUNCH_MAX)

    def _auth_relaunch_count(self) -> int:
        return int(getattr(self.bot, "_auth_relaunch_count", 0) or 0)

    def _auth_relaunch_exhausted(self) -> bool:
        return self._auth_relaunch_count() >= self._auth_relaunch_max()

    def _note_auth_relaunch(self) -> int:
        """Increment AUTH relaunch count; sync exhausted flag for pipeline."""
        n = self._auth_relaunch_count() + 1
        self.bot._auth_relaunch_count = n
        # True only when budget is fully used (abort on next AUTH)
        self.bot._auth_relaunch_used = n >= self._auth_relaunch_max()
        return n

    def _persist_auth_relaunch_state(self) -> None:
        """Disk marker so shake/count survive controller killing bot2."""
        try:
            from auth_relaunch_state import save_auth_relaunch_state
            save_auth_relaunch_state(self.bot)
        except Exception as e:
            log.warning("persist auth relaunch state failed: %r", e)

    def _reconnect_notice_present(self, img: np.ndarray) -> bool:
        """True when a reconnect / try-again notice is on the server UI."""
        lines = self._tick_ocr(img)
        return self._phrase_present(
            lines,
            list(self._all_words("reconnect_notice")),
            token_groups=[
                ["재", "접속"],
                ["다시", "접속"],
                ["다시", "연결"],
                ["연결", "끊"],
                ["재", "연결"],
                ["重新", "連"],
                ["重新", "连"],
                ["請", "重新"],
                ["请", "重新"],
                ["reconnect"],
                ["connection", "lost"],
                ["try", "again"],
            ],
        )

    def _dismiss_reconnect_and_reselect_server(self, img: np.ndarray) -> bool:
        """After server click: OK the reconnect notice, then re-click the row.

        Returns True when this tick consumed the reconnect exception.
        """
        if int(getattr(self, "_server_clicks", 0) or 0) <= 0:
            return False
        if not self._reconnect_notice_present(img):
            return False
        n = int(getattr(self, "_server_reconnect_count", 0) or 0)
        if n >= SERVER_RECONNECT_MAX:
            self.error = ("reconnect notice loop after server click "
                          "(%d times)" % n)
            log.error(self.error)
            return True
        log.warning("reconnect notice after server select — OK then "
                    "re-click server [%d/%d]", n + 1, SERVER_RECONNECT_MAX)
        dismissed = False
        if self._try_fixed("ok_right", "ok(reconnect-notice)"):
            dismissed = True
        else:
            hits = (self._find_words(img, "ok_button")
                    + self._find_words(img, "server_confirm"))
            if hits:
                _, cx, cy, _, _ = hits[0]
                sx, sy = self._img_pt_to_screen(cx, cy)
                self._click(sx, sy, "ok(reconnect):" + hits[0][0], key="")
                dismissed = True
            else:
                sx, sy = self._ratio_pt(*R_LOGIN_OK)
                self._click(sx, sy, "ok(reconnect-ratio)", key="")
                dismissed = True
        self._server_reconnect_count = n + 1
        # Re-arm table cell click on the next SERVER_SELECT tick
        self._server_clicks = 0
        self._server_ok_clicks = 0
        self._last_act = _now()
        self._settle(0.55)
        self._ocr_cache = None
        return dismissed

    def _h_server_select(self, img: np.ndarray):
        """Page 1|2 are fixed ratios; server name comes from the table
        (page, row, left|right) — never a single blind game/server click."""
        # Exception: reconnect notice after a prior server click
        if self._dismiss_reconnect_and_reselect_server(img):
            return

        targets = list(self.bot.words_cfg.get("server_name", []) or [])
        lookup = None
        for tgt in targets:
            lookup = self._lookup_server(tgt)
            if lookup:
                break

        # Structured path whenever the name is in servers_*.json
        if lookup:
            page, row, col = lookup
            if self._page_clicks == 0:
                if not self._ensure_page_tab(img, page, "page %s (fixed)" % page):
                    return
                self._on_page = str(page)
                self._page_clicks = MAX_RETRIES + 1
                self._last_act = _now()
                self._settle(0.45)
                return
            if self._server_clicks == 0:
                name = targets[0] if targets else "?"
                self._click_server_cell(img, page, row, col, name)
                return
            self._lock_en_buttons()
            # Prefer reconnect handling if notice appeared between ticks
            if self._dismiss_reconnect_and_reselect_server(img):
                return
            if self._try_fixed("ok_right", "ok(server-confirm-fixed)"):
                self._server_ok_clicks = int(
                    getattr(self, "_server_ok_clicks", 0) or 0) + 1
                self._last_act = _now()
                self._settle(0.35)
                return
            ok_hits = (self._find_words(img, "ok_button")
                       + self._find_words(img, "server_confirm"))
            if ok_hits:
                _, cx, cy, _, _ = ok_hits[0]
                osx, osy = self._img_pt_to_screen(cx, cy)
                self._click(osx, osy,
                            "ok(server-confirm):" + ok_hits[0][0], key="")
                self._server_ok_clicks = int(
                    getattr(self, "_server_ok_clicks", 0) or 0) + 1
                self._last_act = _now()
                self._settle(0.35)
            return

        det = self._match_anchor(img, "server_title")
        dlg = self._find_words(img, "server_dialog")
        if not det and not dlg:
            if self._server_clicks > 0:
                if self._dismiss_reconnect_and_reselect_server(img):
                    return
                self._lock_en_buttons()
                if self._try_fixed("ok_right", "ok(server-confirm-fixed)"):
                    self._server_ok_clicks = int(
                        getattr(self, "_server_ok_clicks", 0) or 0) + 1
                    return
                hits = self._find_words(img, "ok_button")
                if hits:
                    _, cx, cy, _, _ = hits[0]
                    sx, sy = self._img_pt_to_screen(cx, cy)
                    self._click(sx, sy, "ok(server-confirm):" + hits[0][0],
                                key="")
                    self._server_ok_clicks = int(
                        getattr(self, "_server_ok_clicks", 0) or 0) + 1
            return
        if self._page_clicks == 0:
            target_page = None
            for tgt in targets:
                lu = self._lookup_server(tgt)
                if lu:
                    target_page = str(lu[0])
                    break
            if target_page is None:
                log.warning(
                    "server %s not in any servers_*.json — skip blind page-1",
                    targets)
                self._page_clicks = MAX_RETRIES + 1
            else:
                if not self._ensure_page_tab(
                        img, target_page, "page %s (init)" % target_page):
                    return
                self._on_page = target_page
                self._page_clicks += 1
                self._page_sig = self._list_signature(img)
                self._last_act = _now()
                time.sleep(0.45)
                return
        if self._page_clicks <= MAX_RETRIES:
            sig = self._list_signature(img)
            if sig is not None and sig == self._page_sig:
                m = self._match_anchor(img, "server_title")
                log.info("page-click no list change; anchor=%s",
                         ("score=%.3f pos=(%d,%d) scale=%.3f" %
                          (m["score"], m["x"], m["y"], m["scale"])) if m
                         else "none")
                self._click_page_button(
                    img, getattr(self, "_on_page", "2"),
                    "page %s retry" % getattr(self, "_on_page", "2"))
                self._page_clicks += 1
                self._last_act = _now()
                time.sleep(0.45)
                return
            self._page_clicks = MAX_RETRIES + 1   # list changed -> proceed
        self._find_and_click_server(img)

    def _ensure_page_tab(self, img: np.ndarray, page, label: str) -> bool:
        """Click the 1|2 tab for the looked-up server page. Never assume page 1."""
        page = str(page)
        if self._click_page_button(img, page, label):
            return True
        if page == "2":
            if self._try_fixed("page", "page(fixed)"):
                return True
            self._click_page2(img)
            return True
        log.warning("page %s click failed (no page_positions)", page)
        self.error = "page %s button not configured" % page
        return False

    def _click_page_button(self, img: np.ndarray, page: str, label: str):
        from positions import normalize_page_key, normalize_page_positions
        rec = normalize_page_positions(
            self.bot.cfg.get("page_positions", {})).get(
                normalize_page_key(page))
        if rec:
            sx, sy = self._ratio_pt(rec["rx"], rec["ry"])
            # key="" — do not remap page1/page2 through a single game/page key
            return self._click(sx, sy, label, key="")
        return False

    def _click_page2(self, img: np.ndarray):
        """Click the page-'2' button. PRIMARY: page_positions ratios from
        config (any recording resolution). FALLBACK: anchor-guided offset."""
        if self._click_page_button(img, "2", "page 2 (config)"):
            return
        sx, sy = self._anchor_pt(img, "server_title", OFF_PAGE2_BTN,
                                 R_PAGE2_BTN)
        self._click(sx, sy, "page 2 (anchor)", key="")

    def _scroll_list_down(self, img: np.ndarray):
        """Scroll the server list down by 3 notches. The cursor is moved to
        the center of the list region so the scroll lands on the list."""
        m = self._match_anchor(img, "server_title")
        if not m:
            return
        x0, y0, x1, y1 = self._anchor_region(
            img, "server_title", OFF_LIST_REGION, R_LIST_REGION)
        cx = self.win.rect.left + (x0 + x1) // 2
        cy = self.win.rect.top + (y0 + y1) // 2
        interception.wheel(-3, cx, cy)
        log.info("scrolled server list down at (%d,%d)", cx, cy)

    def _find_and_click_server(self, img: np.ndarray):
        """Click the target server using the table (page/row/col).

        Blind game/server fixed coords are intentionally unused — every
        server name maps through servers_*.json to a cell instead.
        """
        if self._server_table:
            self._click_server_from_table(img)
        else:
            self._click_server_from_ocr(img)

    def _click_server_cell(self, img: np.ndarray, page, row, col,
                           name: str = "") -> bool:
        """Click one list cell from (page, row, left|right) geometry."""
        cur_page = str(getattr(self, "_on_page", "1") or "1")
        page = str(page)
        if cur_page != page:
            log.info("switching from page %s to page %s for %s",
                     cur_page, page, name or "?")
            self._click_page_button(img, page, "page %s (table)" % page)
            self._on_page = page
            self._last_act = _now()
            time.sleep(0.55)
            return False  # next tick with fresh grab on correct page

        row_int = int(row)
        if row_int > 6:
            scroll_needed = (row_int - 6 + 2) // 3
            scroll_count = getattr(self, "_scroll_count", 0)
            if scroll_count < scroll_needed:
                self._scroll_list_down(img)
                self._scroll_count = scroll_count + 1
                self._last_act = _now()
                time.sleep(0.6)
                return False

        m = self._match_anchor(img, "server_title")
        if not m:
            log.warning("cannot find server_title anchor to click row")
            self.error = "server title anchor not found"
            return False
        row_int_0 = row_int - 1
        ROW_START_Y = 29.0
        ROW_HEIGHT = 16.5
        COL_LEFT_X = 62.0
        COL_RIGHT_X = 176.0
        cx_offset = COL_LEFT_X if col == "left" else COL_RIGHT_X
        cy_offset = ROW_START_Y + row_int_0 * ROW_HEIGHT
        sx = self.win.rect.left + int(m["x"] + cx_offset * m["scale"])
        sy = self.win.rect.top + int(m["y"] + cy_offset * m["scale"])
        log.info("table click: %s page=%s row=%s col=%s -> screen=(%d,%d)",
                 name or "?", page, row, col, sx, sy)
        # key="" keeps table geometry; do not remap to game/server
        self._click(sx, sy,
                    "server(table) %s p%s r%s %s" % (name, page, row, col),
                    key="")
        self._server_clicks += 1
        self._lock_en_buttons()
        self._last_act = _now()
        self._settle(0.4)
        return True

    def _click_server_from_table(self, img: np.ndarray):
        """Use the server name table to click the target row directly."""
        targets = list(self.bot.words_cfg.get("server_name", []) or [])
        if not targets:
            self.error = "no server_name configured"
            log.error(self.error)
            return
        lookup = None
        for tgt in targets:
            lookup = self._lookup_server(tgt)
            if lookup:
                break
        if not lookup:
            self.error = (
                "server %s not in any servers_*.json" % targets)
            log.error(self.error)
            return
        page, row, col = lookup
        log.info("table lookup: %s -> page %s, row %s, col %s",
                 targets[0], page, row, col)
        if not self._click_server_cell(img, page, row, col, targets[0]):
            return
        ok_img = self._grab()
        if ok_img is not None:
            self._ocr_cache = None
            ok_hits = (self._find_words(ok_img, "ok_button")
                       + self._find_words(ok_img, "server_confirm"))
            if ok_hits:
                _, cx, cy, _, _ = ok_hits[0]
                osx, osy = self._img_pt_to_screen(cx, cy)
                self._click(osx, osy, "ok(server-confirm):" + ok_hits[0][0],
                            key="")
            elif self._try_fixed("ok_right", "ok(server-confirm-fixed)"):
                pass
            else:
                log.info("server-confirm: no OK found, retrying in 0.5s")
                time.sleep(0.5)
                ok_img2 = self._grab()
                if ok_img2 is not None:
                    self._ocr_cache = None
                    ok_hits2 = (self._find_words(ok_img2, "ok_button")
                                + self._find_words(ok_img2, "server_confirm"))
                    if ok_hits2:
                        _, cx, cy, _, _ = ok_hits2[0]
                        osx, osy = self._img_pt_to_screen(cx, cy)
                        self._click(osx, osy,
                                    "ok(server-confirm2):" + ok_hits2[0][0],
                                    key="")
                    elif not self._try_fixed(
                            "ok_right", "ok(server-confirm-fixed)"):
                        log.warning("server-confirm: OK button not found "
                                    "after 2 attempts")
                        try:
                            cv2.imwrite(os.path.join(
                                self.bot.debug_dir,
                                "server_confirm_fail.png"), ok_img2)
                        except Exception:
                            pass
        time.sleep(CLICK_SETTLE)

    def _click_server_from_ocr(self, img: np.ndarray):
        """Fallback: find server by OCR + scroll + page cycling."""
        row = self._find_server_row(img)
        if row is not None:
            sx, sy = self._img_pt_to_screen(*row)
            self._click(sx, sy, "server(ocr)", key="")
            self._server_clicks += 1
            self._lock_en_buttons()
            self._last_act = _now()
            time.sleep(0.4)
            ok_img = self._grab()
            if ok_img is not None:
                self._ocr_cache = None
                ok_hits = (self._find_words(ok_img, "ok_button")
                           + self._find_words(ok_img, "server_confirm"))
                if ok_hits:
                    _, cx, cy, _, _ = ok_hits[0]
                    osx, osy = self._img_pt_to_screen(cx, cy)
                    self._click(osx, osy,
                                "ok(server-confirm-ocr):" + ok_hits[0][0],
                                key="")
                else:
                    self._try_fixed("ok_right", "ok(server-confirm-fixed)")
            time.sleep(CLICK_SETTLE)
            return
        scroll_count = getattr(self, "_scroll_count", 0)
        if scroll_count < 3:
            self._scroll_list_down(img)
            self._scroll_count = scroll_count + 1
            self._last_act = _now()
            time.sleep(0.6)
            return
        self._scroll_count = 0
        self._page_search_rounds = getattr(self, "_page_search_rounds", 0) + 1
        if self._page_search_rounds > 4:
            names = list(self.bot.words_cfg.get("server_name", []) or [])
            self.error = ("server %s not found on either page (list OCR "
                          "read the names logged above)" % names)
            log.error(self.error)
            return
        other = "1" if getattr(self, "_on_page", "2") == "2" else "2"
        log.info("server not on page %s; switching to page %s (round %d)",
                 getattr(self, "_on_page", "2"), other,
                 self._page_search_rounds)
        self._on_page = other
        if not self._click_page_button(img, other, "page %s" % other):
            sx, sy = self._anchor_pt(img, "server_title",
                                     OFF_PAGE2_BTN if other == "2" else
                                     (88.0, 226.0), R_PAGE2_BTN)
            self._click(sx, sy, "page %s (anchor)" % other, key="")
        self._last_act = _now()
        time.sleep(0.55)

    def _device_reg_tile(self, img: np.ndarray) -> bool:
        """True when the 기기등록 / 裝置登錄 / 设备注册 control is on screen.
        Used after relaunch so the two-tile choice still gets a shake."""
        lines = self._tick_ocr(img)
        hit = self._phrase_present(
            lines,
            list(self._all_words("device_reg")),
            token_groups=[
                ["기기", "등록"],
                ["裝置", "登錄"],
                ["装置", "登录"],
                ["设备", "注册"],
                ["設備", "註冊"],
                ["装置", "登"],
                ["裝置", "登"],
                ["设备", "登"],
            ],
        )
        if hit and not getattr(self, "_devreg_tile_logged", False):
            log.info("기기등록 tile present blob=%s",
                     self._ocr_blob(lines)[:160])
            self._devreg_tile_logged = True
        return hit

    def _security_splash_screen(self, img: np.ndarray) -> bool:
        """보안설정 / 安全设定 / Security Settings — never 기기등록 or AUTH_CHOICE."""
        if self._auth_choice_screen(img) or self._device_reg_tile(img):
            return False
        lines = self._tick_ocr(img)
        return self._phrase_present(
            lines,
            list(self._all_words("security_splash")),
            token_groups=[
                ["보안", "설정"],
                ["안전", "설정"],
                ["安全", "設定"],
                ["安全", "设置"],
                ["安全", "设定"],
                ["security", "setting"],
            ],
        )

    def _auth_choice_screen(self, img: np.ndarray) -> bool:
        """Strong AUTH signal: auth-method title AND Purple simple auth
        (ko / zh-TW / zh-CN / en). Close also fires on purple alone."""
        lines = self._tick_ocr(img)
        blob = self._ocr_blob(lines)
        has_title = self._phrase_present(
            lines,
            list(self._all_words("device_reg_context")),
            token_groups=[
                ["인증", "수단", "선택"],
                ["인증", "수단"],
                ["수단", "선택"],
                ["인증", "방법"],
                ["選擇", "驗證", "方法"],
                ["选择", "验证", "方法"],
                ["选择", "认证", "方法"],
                ["選擇", "認證", "方法"],
                ["驗證", "方法"],
                ["验证", "方法"],
                ["认证", "方法"],
                ["認證", "方式"],
                ["验证", "方式"],
                ["證", "方法"],
                ["证", "方法"],
            ],
        )
        has_purple = self._phrase_present(
            lines,
            list(self._all_words("purple_auth")),
            token_groups=[
                ["퍼플", "간편", "인증"],
                ["퍼플", "인증"],
                ["간편", "인증"],
                ["purple", "簡易", "驗證"],
                ["purple", "简易", "验证"],
                ["purple", "简便", "认证"],
                ["簡易", "驗證"],
                ["简易", "验证"],
                ["简便", "认证"],
            ],
        )
        if has_title and has_purple:
            log.info("AUTH_CHOICE detected (auth method + purple simple) "
                     "blob=%s", blob[:160])
            return True
        return False

    def _device_reg_screen(self, img: np.ndarray) -> bool:
        """기기등록 / 裝置登錄 / 设备注册 form (not the two-tile AUTH_CHOICE)."""
        # AUTH_CHOICE also contains 기기등록 tile + 인증수단 title — never
        # classify that as DEVICE_REG (armed or not), or boot shake fires
        # on 퍼플간편인증.
        if self._auth_choice_screen(img):
            return False
        lines = self._tick_ocr(img)
        has_purple = self._phrase_present(
            lines,
            list(self._all_words("purple_auth")),
            token_groups=[
                ["퍼플", "간편", "인증"],
                ["purple", "簡易", "驗證"],
                ["purple", "简易", "验证"],
            ],
        )
        if has_purple:
            return False
        has_reg = self._phrase_present(
            lines,
            list(self._all_words("device_reg")),
            token_groups=[
                ["기기", "등록"],
                ["裝置", "登錄"],
                ["装置", "登录"],
                ["设备", "注册"],
                ["設備", "註冊"],
            ],
        )
        has_ctx = self._phrase_present(
            lines,
            list(self._all_words("device_reg_context")),
            token_groups=[
                ["인증", "수단"],
                ["驗證", "方法"],
                ["验证", "方法"],
                ["认证", "方法"],
            ],
        )
        if has_reg and has_ctx:
            log.info("DEVICE_REG detected (auth context + device reg) blob=%s",
                     self._ocr_blob(lines)[:160])
            return True
        return False

    def _purple_auth_screen(self, img: np.ndarray) -> bool:
        """퍼플간편인증 / PURPLE簡易驗證 / PURPLE简易验证 alone (close trigger).
        Full two-tile choice is also covered via _auth_choice_screen."""
        if self._device_reg_screen(img):
            return False
        # Do not treat as "purple alone" when the stronger two-tile match
        # already applies — caller ORs both.
        lines = self._tick_ocr(img)
        hit = self._phrase_present(
            lines,
            list(self._all_words("purple_auth")),
            token_groups=[
                ["퍼플", "간편", "인증"],
                ["purple", "간편", "인증"],
                ["purple", "簡易", "驗證"],
                ["purple", "简易", "验证"],
                ["簡易", "驗證"],
                ["简易", "验证"],
                ["简便", "认证"],
            ],
        )
        if hit:
            log.info("PURPLE_AUTH detected blob=%s",
                     self._ocr_blob(lines)[:160])
        return hit

    def _shake_game_window(self, duration: float = SHAKE_DURATION, amp: int = 8):
        """Nudge the game window WITHOUT title-bar mouse drag.

        Live failure: Interception title-bar drag for ~6s caused Windows to
        snap/maximize LC (1296x999 -> 1936x1056 at -8,-8). wake_window uses
        SetWindowPos+SWP_NOSIZE and returns to the original origin.
        """
        try:
            from input.inputrouter import InputRouter
        except ImportError:
            from bot.input.inputrouter import InputRouter
        cycles = max(12, int(float(duration) / max(BOOT_SHAKE_INTERVAL, 0.02)))
        InputRouter.wake_window(
            self.win,
            cycles=cycles,
            amp=max(4, min(int(amp), BOOT_SHAKE_AMP)),
            interval=BOOT_SHAKE_INTERVAL,
        )

    def _restore_size_after_shake(self, before_w: int, before_h: int,
                                  before_left: int, before_top: int) -> None:
        """Always re-pin familiar dialog size after wake-nudge.

        Do not restore a pre-shake maximized rect (1936@-8,-8) — that was the
        bug. Prefer 816x639 at a safe origin.
        """
        if self._pin_familiar_shell(reason="post_shake_restore"):
            return
        try:
            r = self.win.rect
        except Exception:
            return
        blown = (
            self._shell_is_maximized(r)
            or abs(r.width - before_w) > 40
            or abs(r.height - before_h) > 40
        )
        if not blown and self._shell_is_familiar(r):
            return
        log.warning("post-shake size abnormal %dx%d@(%d,%d) "
                    "(was %dx%d) — restoring familiar",
                    r.width, r.height, r.left, r.top, before_w, before_h)
        try:
            user32.ShowWindow(self.win.hwnd, 9)  # SW_RESTORE
            time.sleep(0.1)
        except Exception:
            pass
        if self._pin_familiar_shell(reason="post_shake_fallback"):
            return
        try:
            left = max(0, before_left if before_w < SHELL_MAX_W else 0)
            top = max(0, before_top if before_h < SHELL_MAX_H else 0)
            tw = int(REF_PAGE_W) if before_w >= SHELL_MAX_W else before_w
            th = int(REF_PAGE_H) if before_h >= SHELL_MAX_H else before_h
            self.win.resize(tw, th, left=left, top=top)
        except Exception as e:
            log.warning("post-shake resize fallback failed: %r", e)

    def _h_purple_auth(self, img: np.ndarray):
        """Close+relaunch when 퍼플간편인증 / PURPLE簡易驗證 (ko/zh) appears.

        Auth-method title is optional. After relaunch, do not close again —
        boot shake is handled on 보안설정 / 기기등록, not here.
        """
        if getattr(self, "_restart_requested", False):
            return
        if getattr(self.bot, "_shake_after_relaunch", False):
            log.info("AUTH after prior relaunch; not closing "
                     "(boot shake runs on next game window)")
            return
        # Re-check purple alone (ko/zh). Title is optional.
        choice_hit = self._auth_choice_screen(img)
        purple_hit = choice_hit or self._purple_auth_screen(img)
        escape = bool(getattr(self, "_auth_escape_relaunch", False))
        if not (purple_hit or escape):
            log.info("no 퍼플간편인증 / PURPLE簡易驗證; not closing")
            if self._security_splash_screen(img):
                self._h_security(img)
            elif self._device_reg_screen(img) or self._device_reg_tile(img):
                self._h_device_reg(img)
            return
        if escape and not purple_hit:
            log.warning("PURPLE_AUTH escape relaunch "
                        "(AUTH OCR incomplete; device_reg tile path)")
        # Hard cap: at most auth_relaunch_max close+relaunches per session.
        if self._auth_relaunch_exhausted():
            cap = self._auth_relaunch_max()
            log.error("AUTH again after %d relaunches — abort (no loop)",
                      cap)
            self.error = ("AUTH loop prevented "
                          "(relaunch budget %d exhausted)" % cap)
            try:
                from base import Phase
                self.bot._set_phase(Phase.ERROR)
            except Exception:
                pass
            return
        n = self._note_auth_relaunch()
        self._restart_requested = True
        self.bot._shake_after_relaunch = True
        self._auth_escape_relaunch = False
        self._boot_shake_done = False
        self._boot_hunt_since = 0.0
        # MUST persist before close — watchdog may kill bot2 during sleep.
        self._persist_auth_relaunch_state()
        log.warning("=" * 60)
        log.warning("퍼플간편인증 / PURPLE簡易驗證 - closing+relaunch [%d/%d]; "
                    "shake on 安全設定登録中/裝置登錄確認中 template",
                    n, self._auth_relaunch_max())
        log.warning("=" * 60)
        self.release()
        try:
            self.bot._close_game(wait=1.5)
            self.bot._restart()
        except Exception as e:
            log.error("restart failed: %r", e)
            self.error = "restart after 퍼플 간편 인증 failed: %r" % e

    def _boot_frame_sig(self, img: np.ndarray) -> Optional[bytes]:
        """Tiny grayscale fingerprint to detect post-normalize UI change."""
        try:
            if img is None or getattr(img, "size", 0) == 0:
                return None
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
            return cv2.resize(g, (48, 32)).tobytes()
        except Exception:
            return None

    def _boot_auth_ui(self, img: Optional[np.ndarray]) -> bool:
        """True on 퍼플간편인증 / AUTH_CHOICE — never a boot-shake target."""
        if img is None:
            return False
        try:
            return bool(
                self._auth_choice_screen(img) or self._purple_auth_screen(img))
        except Exception:
            return False

    def _boot_shake_target_ui(self, img: Optional[np.ndarray]) -> bool:
        """True when boot-shake status templates are visible (OCR-free)."""
        if img is None:
            return False
        return self._match_boot_shake_status(img) is not None

    def _boot_shake_gates_ready(self, img: Optional[np.ndarray] = None) -> bool:
        """Ready when 安全設定登録中 / 裝置登錄確認中 templates hit."""
        return self._boot_shake_target_ui(img)

    def _maybe_post_relaunch_boot_shake(self, label: str,
                                         img: Optional[np.ndarray] = None) -> bool:
        """One wake-nudge when boot status templates appear after AUTH relaunch.

        Order: pin 816x639 → match template → wake_nudge → pin again.
        Never shake while maximized.
        """
        if not getattr(self.bot, "_shake_after_relaunch", False):
            return False
        if getattr(self, "_boot_shake_done", False):
            return False
        if img is None:
            return False
        # Pin familiar size first — templates are dialog-scale crops.
        if not self._shell_is_familiar():
            self._pin_familiar_shell(reason="pre_boot_shake_match")
            # Grab was at old size; caller must re-grab next tick.
            return False
        m = self._match_boot_shake_status(img)
        if not m:
            return False
        try:
            r = self.win.rect if self.win else None
        except Exception:
            r = None
        if r is None or r.width < 200 or r.height < 150:
            return False
        if self._shell_is_maximized(r):
            self._pin_familiar_shell(reason="pre_wake_undo_max")
            return False
        if not self._game_at_point(*self._ratio_pt(0.5, 0.5)):
            self._ensure_on_top()
        if not self._game_at_point(*self._ratio_pt(0.5, 0.5)):
            log.warning("%s: game not on top - boot shake deferred", label)
            return False
        before = (r.width, r.height, r.left, r.top)
        try:
            log.info("%s: boot_shake tpl=%s score=%.3f scale=%.2f @%dx%d → "
                     "wake_nudge %dx%d@(%d,%d) (~%.1fs)",
                     label, m.get("kind"), m["score"], m.get("scale", 1.0),
                     m["w"], m["h"], r.width, r.height, r.left, r.top,
                     SHAKE_DURATION)
            self._shake_game_window(
                duration=SHAKE_DURATION, amp=BOOT_SHAKE_AMP)
            self._restore_size_after_shake(*before)
        except Exception as e:
            log.warning("boot shake failed: %r", e)
            try:
                self._restore_size_after_shake(*before)
            except Exception:
                pass
            return False
        self._boot_shake_done = True
        self._resize_shaken = True
        self._sec_shake_count = max(int(getattr(self, "_sec_shake_count", 0)), 1)
        self._devreg_shake_count = max(
            int(getattr(self, "_devreg_shake_count", 0)), 1)
        self._sec_shaken_at = _now()
        self._devreg_shaken_at = _now()
        try:
            from auth_relaunch_state import disarm_shake_keep_count
            disarm_shake_keep_count(self.bot)
        except Exception:
            pass
        return True

    def _h_device_reg(self, img: np.ndarray):
        """기기등록 boot UI — shake on status template if armed."""
        if not getattr(self.bot, "_shake_after_relaunch", False):
            logged = "_noshake_logged_device_reg"
            if not getattr(self, logged, False):
                log.info("기기등록: shake skipped (no AUTH relaunch yet)")
                setattr(self, logged, True)
            return
        try:
            dump = os.path.join(self.bot.debug_dir, "device_reg_dump.png")
            if not os.path.exists(dump) or \
                    _now() - os.path.getmtime(dump) > 10:
                cv2.imwrite(dump, img)
        except Exception:
            pass
        self._maybe_post_relaunch_boot_shake("기기등록", img=img)

    def _h_security(self, img: np.ndarray):
        """보안설정 boot UI — shake on status template if armed."""
        try:
            dump = os.path.join(self.bot.debug_dir, "security_dump.png")
            if not os.path.exists(dump) or \
                    _now() - os.path.getmtime(dump) > 10:
                cv2.imwrite(dump, img)
        except Exception:
            pass
        if getattr(self.bot, "_shake_after_relaunch", False):
            self._maybe_post_relaunch_boot_shake("보안설정", img=img)
            return
        self._do_nudge_shake(
            kind="security",
            confirmed=getattr(self, "_tick_det", "") == "SECURITY",
            label="보안설정",
            timeout_key="SECURITY",
            max_shakes=1,
        )

    def _shake_on_relaunch_resize(self):
        """Deprecated: boot shake waits for normalize + screen change."""
        self._resize_shaken = True
        return

    def _maybe_normalize_game_size(self, reason: str = "") -> bool:
        """After 보안설정, pin LC to the familiar dialog size (816x639).

        Splash (e.g. 1296x999) is left alone until security is done. Then we
        force the size used by page_positions / agree / server-table geometry.
        """
        if not self._security_passed and not getattr(
                self, "_agreement_seen", False):
            return False
        now = _now()
        if (self._game_size_normalized
                and now - float(self._game_size_normalize_at or 0) < 8.0):
            r = self.win.rect if self.win else None
            if r and abs(r.width - REF_PAGE_W) <= 16 and abs(
                    r.height - REF_PAGE_H) <= 16:
                return True
        fn = getattr(self.bot, "_normalize_game_shell_size", None)
        if not callable(fn):
            return False
        ok = bool(fn(reason=reason or ("post_" + (self.state or "?").lower())))
        self._game_size_normalize_at = now
        if ok:
            self._game_size_normalized = True
            self._ocr_cache = None
            self._page_sig = None
        return ok

    def _do_nudge_shake(self, kind: str, confirmed: bool, label: str,
                        timeout_key: str, max_shakes: int = 1, gap: float = 25.0):
        """Shake only while this tick still classifies as the splash, at
        most `max_shakes` times, with `gap` seconds between shake *ends*."""
        count_attr = "_%s_shake_count" % ("sec" if kind == "security" else "devreg")
        at_attr = "_%s_shaken_at" % ("sec" if kind == "security" else "devreg")
        if not confirmed:
            return
        if not getattr(self.bot, "_shake_after_relaunch", False):
            logged = "_noshake_logged_%s" % kind
            if not getattr(self, logged, False):
                log.info("%s: shake skipped (no AUTH relaunch yet)",
                         label)
                setattr(self, logged, True)
            return
        if self._security_passed and kind == "security":
            return
        n = getattr(self, count_attr, 0)
        if n >= max_shakes:
            return
        timeout = STATE_TIMEOUTS.get(timeout_key, 120.0)
        if _now() - self.state_since > timeout:
            return
        last = getattr(self, at_attr, 0.0)
        if last and _now() - last < gap:
            return
        if not self._game_at_point(*self._ratio_pt(0.5, 0.5)):
            self._ensure_on_top()
        if not self._game_at_point(*self._ratio_pt(0.5, 0.5)):
            log.warning("%s: game not on top - shake skipped", label)
            return
        try:
            log.info("%s: shaking the GAME window (~%.0fs) [%d/%d]",
                     label, SHAKE_DURATION, n + 1, max_shakes)
            if not self._shell_is_familiar():
                self._pin_familiar_shell(reason="pre_nudge_%s" % kind)
            before = (self.win.rect.width, self.win.rect.height,
                      self.win.rect.left, self.win.rect.top)
            self._shake_game_window(duration=SHAKE_DURATION, amp=8)
            self._restore_size_after_shake(*before)
        except Exception as e:
            log.warning("shake failed: %r", e)
            return
        setattr(self, at_attr, _now())
        setattr(self, count_attr, n + 1)

    def _h_connect_wait(self, img: np.ndarray):
        if self._server_clicks > 0:
            self._lock_en_buttons()
        hits = self._find_words(img, "ok_button") + self._find_words(img, "server_confirm")
        if hits:
            _, cx, cy, _, _ = hits[0]
            sx, sy = self._img_pt_to_screen(cx, cy)
            self._click(sx, sy, "ok(connect):" + hits[0][0])
            self._pending_server_ok = False
            return
        if getattr(self, "_pending_server_ok", False):
            ocr_lines = self._tick_ocr(img)
            all_words = [w.text for ln in ocr_lines for w in ln.words]
            log.info("server-confirm OCR (connect): %s",
                     " ".join(all_words)[:200])
            self._pending_server_ok = False

    def _right_ok_hit(self, img: np.ndarray):
        """ok / credit / exit live on the RIGHT of the character-login screen.

        Full-window OCR previously returned a fake 'OK' on the left parchment
        (page 11 at ~191,490). Only the right strip is searched, at native
        resolution, and credit/exit are never clicked."""
        H, W = img.shape[:2]
        x0 = int(W * R_LOGIN_OK_XMIN)
        crop = img[:, x0:]
        rapid = getattr(self.bot, "rapid_ocr", None)
        lines = []
        if rapid is not None and crop.size:
            try:
                lines = self._rapid_ocr_img(crop, rapid, max_side=0) or []
            except Exception as e:
                log.warning("right-ok ocr failed: %r", e)
        ok = credit = None
        dumped = []
        for ln in lines:
            for w in getattr(ln, "words", []) or []:
                t = _btn_norm(w.text).lower()
                cx = x0 + w.x + w.w // 2
                cy = w.y + w.h // 2
                dumped.append("%s@(%d,%d)" % (w.text, cx, cy))
                if t in ("ok", "okay"):
                    ok = (cx, cy, w.text)
                elif "credit" in t or "crebit" in t:
                    credit = (cx, cy)
                elif t == "exit":
                    pass
        if dumped:
            log.info("right-side labels: %s", " ".join(dumped[:12]))
        if ok:
            return ok
        if credit:
            return (credit[0], credit[1] - int(H * 0.106), "above-credit")
        return None

    def _click_right_ok(self, img: np.ndarray, tag: str) -> bool:
        """Click the right-column ok: ratio first, OCR only if ratio fails."""
        sx, sy = self._ratio_pt(*R_LOGIN_OK)
        if self._click(sx, sy, tag + ":ratio"):
            return True
        hit = self._right_ok_hit(img)
        if hit is not None:
            cx, cy, lab = hit
            sx, sy = self._img_pt_to_screen(cx, cy)
            return self._click(sx, sy, tag + ":" + lab)
        return False

    def _h_loading(self, img: np.ndarray):
        """Post-server login: confirm the server, then double-click the character.

        The portrait double-click enters the world, so the confirm button
        after the character is not pressed.
        """
        if self._char_login_committed():
            return
        if not getattr(self, "_agreement_seen", False):
            return
        if int(getattr(self, "_server_clicks", 0) or 0) <= 0:
            return
        if self._server_clicks > 0:
            self._lock_en_buttons()
        if not getattr(self, "_loading_ok_clicked", False):
            # Server confirm already clicked — go straight to character.
            if int(getattr(self, "_server_ok_clicks", 0) or 0) >= 1:
                self._loading_ok_clicked = True
            elif self._try_fixed("ok_right", "ok(right-fixed)"):
                self._loading_ok_clicked = True
                self._last_act = _now()
                self._settle(0.45)
                return
            else:
                # Fixed → ratio first; OCR only if ratio click fails.
                sx, sy = self._ratio_pt(*R_LOGIN_OK)
                if self._click(sx, sy, "ok(right-ratio)"):
                    self._loading_ok_clicked = True
                    self._last_act = _now()
                    time.sleep(0.45)
                    return
                hit = self._right_ok_hit(img)
                if hit is not None:
                    cx, cy, lab = hit
                    sx, sy = self._img_pt_to_screen(cx, cy)
                    if self._click(sx, sy, "ok(right):" + lab):
                        self._loading_ok_clicked = True
                        self._last_act = _now()
                    time.sleep(0.45)
                return

        if not getattr(self, "_loading_char_clicked", False):
            if self._select_character(img):
                self._loading_char_clicked = True
                self._loading_char_at = _now()
                self._commit_character_login()
                self._settle(0.9)
            return

        if not getattr(self, "_loading_final_ok_clicked", False):
            if self._try_fixed("ok_after_char", "ok(after-char-fixed)"):
                self._loading_final_ok_clicked = True
                self._start_at = _now()
                self._char_ok_clicked = True
                self._last_act = _now()
                self._settle(0.4)
                return
            if self._click_right_ok(img, "ok(after-char)"):
                self._loading_final_ok_clicked = True
                self._start_at = _now()
                self._char_ok_clicked = True
                self._last_act = _now()
            time.sleep(0.4)
            return

    def _commit_character_login(self) -> None:
        """Double-click enters the world, so do not press the confirm button."""
        self._loading_final_ok_clicked = True
        self._char_ok_clicked = True
        self._start_clicked = True
        self._start_at = _now()
        self._last_act = _now()

    def _select_character(self, img: np.ndarray) -> bool:
        """Double-click the portrait: fixed → ratio → template/YOLO last."""
        n_char = int(getattr(self.bot, "character_number", 1) or 1)
        if self._try_fixed("char", "char(fixed)", clicks=2):
            return True
        idx = max(0, min(n_char - 1, len(R_CHAR_SLOTS) - 1))
        sx, sy = self._ratio_pt(*R_CHAR_SLOTS[idx])
        if self._click(
            sx, sy, "character(ratio slot#%d)" % n_char, key="", clicks=2,
        ):
            return True
        # Fixed/ratio refused (e.g. outside window) — vision last.
        return bool(self._click_char_image(img))

    def _click_char_image(self, img: np.ndarray) -> bool:
        """Vision fallback only: class-sprite template, then YOLO persons."""
        n_char = int(getattr(self.bot, "character_number", 1) or 1)
        tm = self._match_char_template(img)
        if tm is not None:
            sx, sy = self._img_pt_to_screen(
                tm["x"] + tm["w"] // 2, tm["y"] + tm["h"] // 2)
            self._click(
                sx, sy, "char(tm:%s #%d)" % (tm["name"], n_char), clicks=2,
            )
            return True
        dets = self._detect_persons(img)
        if dets:
            if hasattr(dets[0], "cx"):
                sd = sorted(dets, key=lambda d: d.cx)
                d = sd[max(0, min(n_char - 1, len(sd) - 1))]
                px, py = d.cx, d.cy
            else:
                sd = sorted(dets, key=lambda d: d[0])
                d = sd[max(0, min(n_char - 1, len(sd) - 1))]
                px, py = d[0], d[1]
            sx, sy = self._img_pt_to_screen(px, py)
            self._click(sx, sy, "char(person #%d)" % n_char, clicks=2)
            return True
        return False

    def _h_character(self, img: np.ndarray):
        if self._char_login_committed() and self._char_clicks > 0:
            return
        if self._server_clicks > 0:
            self._lock_en_buttons()
        if self._char_clicks == 0:
            if not self._select_character(img):
                return
            self._char_clicks += 1
            self._commit_character_login()
            self._settle(0.9)
            return
        if not self._start_clicked:
            if self._try_fixed("ok_after_char", "ok(after-char-fixed)"):
                self._start_clicked = True
                self._start_at = _now()
                self._char_ok_clicked = True
                self._last_act = _now()
                self._settle(0.4)
                return
            if self._click_right_ok(img, "ok(after-char)"):
                self._start_clicked = True
                self._start_at = _now()
                self._char_ok_clicked = True
                self._last_act = _now()
            time.sleep(0.4)

    def _h_ingame(self, img: np.ndarray):
        self.done = True

    _HANDLERS = {
        "SECURITY": _h_security,
        "DEVICE_REG": _h_device_reg,
        "PURPLE_AUTH": _h_purple_auth,
        "AGREEMENT": _h_agreement,
        "SERVER_SELECT": _h_server_select,
        "CONNECT_WAIT": _h_connect_wait,
        "LOADING": _h_loading,
        "CHARACTER": _h_character,
        "INGAME": _h_ingame,
    }

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    def tick(self) -> str:
        """One engine iteration; returns the current state id."""
        if self.done:
            return "INGAME"
        if self.error:
            raise GameFlowError(self.error)
        now = _now()
        if now > self.deadline:
            self.error = "engine budget (%.0fs) exhausted in %s" % (
                TOTAL_BUDGET, self.state)
            raise GameFlowError(self.error)
        # the game resizes itself when the splash sequence finishes (user's
        # saved window size, e.g. 1296x999 -> 816x639): every cached match,
        # signature and sub-state is invalid afterwards
        r = self.win.rect
        prev = getattr(self, "_last_rect", None)
        size_changed = False
        if prev is not None:
            pw, ph = prev[2], prev[3]
            size_changed = abs(pw - r.width) > 8 or abs(ph - r.height) > 8
            moved = (prev[0], prev[1]) != (r.left, r.top)
            if size_changed:
                log.info("game window size %dx%d -> %dx%d at (%d,%d) "
                         "(keeping click progress)",
                         pw, ph, r.width, r.height, r.left, r.top)
                self._page_sig = None
                self._ocr_cache = None
                # Splash -> dialog is a new layout; agreement wheel restarts.
                # Do NOT wipe page/server/ok/char clicks: shake only MOVES
                # the window and used to reset the whole flow.
                if pw >= DIALOG_MAX_W and r.width < DIALOG_MAX_W:
                    self._scroll_rounds = 0
                # Undo maximize immediately (before template hunt / clicks).
                if self._shell_is_maximized(r):
                    log.warning("shell maximized %dx%d@(%d,%d) — pin 816x639",
                                r.width, r.height, r.left, r.top)
                    self._pin_familiar_shell(reason="undo_maximize")
                    try:
                        r = self.win.rect
                    except Exception:
                        pass
            elif moved:
                log.debug("game window moved to (%d,%d), size still %dx%d",
                          r.left, r.top, r.width, r.height)
        # Resize-based shake removed: post-AUTH shake is template-driven.
        self._last_rect = (r.left, r.top, r.width, r.height)

        # keep the game on top continuously (overlays steal the top band);
        # also re-find the window if the game recreated it during the splash
        if not self.win.valid:
            log.warning("game window invalid - re-finding")
            if not self.bot.find_game():
                time.sleep(TICK_SLEEP)
                return self.state
        # Re-assert topmost every tick (cheap if already on top; uncover throttled)
        self._ensure_on_top()

        armed = getattr(self.bot, "_shake_after_relaunch", False)
        hunting = armed and not getattr(self, "_boot_shake_done", False)

        # After AUTH relaunch: ALWAYS pin familiar size while hunting.
        # Previous bug: only normalized when already dialog-sized, so a
        # maximized 1936 shell never got pinned and boot_shake timed out.
        if hunting:
            if self._shell_is_maximized(r) or not self._shell_is_familiar(r):
                self._pin_familiar_shell(reason="pre_boot_shake")
                try:
                    r = self.win.rect
                except Exception:
                    pass
            # Start / keep hunt clock only once shell is familiar.
            if self._shell_is_familiar(r):
                if not getattr(self, "_boot_hunt_since", 0):
                    self._boot_hunt_since = _now()
                    log.info("boot_shake hunt start at familiar %dx%d",
                             r.width, r.height)
            else:
                # Wrong size — do not burn the hunt timeout.
                self._boot_hunt_since = 0.0
        # Post-security: keep LC at familiar dialog size for ratio/table clicks
        if self._security_passed or getattr(self, "_agreement_seen", False):
            self._maybe_normalize_game_size(reason="tick")
        # Also undo maximize during early boot states even before AUTH relaunch.
        elif self.state in ("SECURITY", "DEVICE_REG", "PURPLE_AUTH"):
            if self._shell_is_maximized(r):
                self._pin_familiar_shell(reason="boot_undo_max")
                try:
                    r = self.win.rect
                except Exception:
                    pass

        # Keep last_rect in sync after any pin this tick.
        try:
            r = self.win.rect
            self._last_rect = (r.left, r.top, r.width, r.height)
        except Exception:
            pass

        st_timeout = STATE_TIMEOUTS.get(self.state)
        if st_timeout and now - self.state_since > st_timeout:
            if self.retries >= MAX_RETRIES:
                self.error = "state %s stuck (%d retries)" % (
                    self.state, self.retries)
                raise GameFlowError(self.error)
            log.warning("state %s past %.0fs; will keep retrying (r=%d)",
                        self.state, st_timeout, self.retries)

        img = self._grab()
        if img is None:
            time.sleep(TICK_SLEEP_SHAKE if hunting else TICK_SLEEP)
            return self.state
        self._last_img = img

        # AUTH relaunch: pin → OCR-free template hunt → shake
        if hunting:
            if not self._shell_is_familiar():
                self._pin_familiar_shell(reason="pre_boot_grab")
                img2 = self._grab()
                if img2 is not None:
                    img = img2
                    self._last_img = img
            if self._shell_is_familiar() and not getattr(self, "_boot_hunt_since", 0):
                self._boot_hunt_since = _now()
                log.info("boot_shake hunt start at familiar shell")
            if self._shell_is_familiar():
                self._maybe_post_relaunch_boot_shake("boot-tpl", img=img)

        self._ocr_cache = None          # fresh OCR pass for this tick
        if not self._fixed_mode() and not (
                hunting and self._is_dialog_size()):
            self._dismiss_popups(img)

        # While hunting status flash, skip OCR-heavy detect — templates only.
        if hunting and not getattr(self, "_boot_shake_done", False):
            # Do not timeout while shell is still wrong size.
            if not self._shell_is_familiar():
                time.sleep(TICK_SLEEP_SHAKE)
                return self.state
            det = ""
            m_boot = self._match_boot_shake_status(img)
            if m_boot:
                det = ("SECURITY" if m_boot.get("kind") == "security"
                       else "DEVICE_REG")
                self._maybe_post_relaunch_boot_shake("boot-tpl", img=img)
            else:
                m_sec = self._match_anchor(img, "security_splash")
                if (m_sec and m_sec["score"] >= MATCH_THRESH
                        and not self._security_passed):
                    det = "SECURITY"
                else:
                    m_dev = self._match_anchor(img, "device_reg")
                    if m_dev and m_dev["score"] >= MATCH_THRESH:
                        det = "DEVICE_REG"
            self._tick_det = det or ""
            if det and det != self.state:
                log.info("state %s -> %s", self.state, det)
                self.state = det
                self.state_since = _now()
            if getattr(self, "_boot_shake_done", False):
                pass  # fall through to handler below with current state
            else:
                hunt_t0 = float(getattr(self, "_boot_hunt_since", 0) or 0)
                if hunt_t0 and (_now() - hunt_t0) < BOOT_SHAKE_HUNT_S:
                    time.sleep(TICK_SLEEP_SHAKE)
                    return self.state
                if hunt_t0:
                    log.info("boot_shake hunt timeout (%.0fs) — resume OCR detect",
                             BOOT_SHAKE_HUNT_S)

        det = self._detect(img)
        self._tick_det = det or ""
        # GameFlow starts in SECURITY. Empty detect must not keep shaking:
        # after the splash window resizes (1296x999 -> 816x639) OCR often
        # returns nothing, state stays SECURITY, and the handler used to
        # re-shake every ~10s until the engine budget died.
        if self.state == "SECURITY" and self._tick_det != "SECURITY":
            misses = getattr(self, "_sec_misses", 0) + 1
            self._sec_misses = misses
            # Leave SECURITY when splash is gone — even before any shake.
            if misses >= 4:
                if not self._security_passed:
                    self._security_passed = True
                    log.info("security splash no longer detected "
                             "(%d misses); stopping SECURITY idle", misses)
                    self._maybe_normalize_game_size(reason="security_gone")
                # Empty detect while stuck in SECURITY: do not keep shaking /
                # burning retries on a dead state — wait for next real screen.
                if not self._tick_det and misses >= 6:
                    log.info("SECURITY idle escape → LOADING (wait next UI)")
                    self.state = "LOADING"
                    self.state_since = _now()
                    self.retries = 0
        else:
            self._sec_misses = 0
        if det == "AGREEMENT":
            self._agreement_seen = True
        if det and det != self.state:
            log.info("state %s -> %s", self.state, det)
            if self.state == "SECURITY" and det != "SECURITY":
                self._security_passed = True
                log.info("security passed — will not re-enter SECURITY")
                self._maybe_normalize_game_size(reason="left_security")
            # Reset shake cooldowns on state entry so we shake each time
            if det == "SECURITY":
                if getattr(self, "_sec_shake_count", 0) < 1:
                    self._sec_shaken_at = 0.0
                self._sec_misses = 0
            elif det == "DEVICE_REG":
                # Do NOT wipe shake_count — flicker DEVICE_REG↔other used to
                # re-arm infinite shakes. Only allow first shake of the epoch.
                if getattr(self, "_devreg_shake_count", 0) < 1:
                    self._devreg_shaken_at = 0.0
                self._devreg_tile_logged = False
            elif det == "PURPLE_AUTH":
                self._device_reg_ignore_count = 0
            elif det == "AGREEMENT":
                self._agree_fixed_fails = 0
                self._agree_fixed_pending = False
            self.state = det
            self.state_since = _now()
            self.retries = 0
            self._scroll_rounds = 0
            self._page_clicks = 0
            self._page_sig = None
            # Keep server progress when advancing to login/char — wiping it
            # made sticky server_title re-click forever and skip character.
            if det in ("SERVER_SELECT", "AGREEMENT"):
                self._server_clicks = 0
                self._server_ok_clicks = 0
                self._server_reconnect_count = 0
            # Do not wipe char-OK progress on CHARACTER↔LOADING flicker —
            # that re-clicked char forever after the user was already in-game.
            if not self._char_login_committed() and det not in ("INGAME",):
                self._char_clicks = 0
                self._start_clicked = False
                self._loading_char_clicked = False
                self._loading_ok_clicked = False
                self._loading_final_ok_clicked = False
                self._loading_char_at = 0.0
            self._sec_enter = False
            self._sec_space = False
            self._sec_click = False
            self._sec_shaken = False
            self._device_reg_clicked = False
            self._sms_told = False
            if det != "AGREEMENT":
                self._agree_fixed_fails = 0
                self._agree_fixed_pending = False
        if det == "INGAME":
            self.done = True
            return "INGAME"

        # After security_passed, never run SECURITY handler on empty detect
        if (self.state == "SECURITY" and self._security_passed
                and self._tick_det != "SECURITY"):
            time.sleep(TICK_SLEEP)
            return self.state

        self._HANDLERS[self.state](self, img)
        armed = getattr(self.bot, "_shake_after_relaunch", False)
        if (armed and not getattr(self, "_boot_shake_done", False)) or (
                armed and self.state in ("SECURITY", "DEVICE_REG", "PURPLE_AUTH")):
            time.sleep(TICK_SLEEP_SHAKE)
        else:
            time.sleep(TICK_SLEEP)
        return self.state
