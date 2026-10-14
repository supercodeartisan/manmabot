"""Purple launcher screen-state watcher.

Fixed-ratio clicks are fast on a familiar 1642x1026 shell, but DPI / CEF
offset / locale chrome make them miss on other PCs. This module:

  1. Classifies the *current* Purple view (email form, password form,
     logging-in, launcher, start-ready) from OCR + optional templates.
  2. Exposes a cheap fingerprint so the bot can wait for a real transition
     instead of firing the next click blindly.
  3. Locates a control via template match when a PNG exists.

Clicks still *may* use saved ratios as a last resort — but only after the
expected screen is confirmed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

log = logging.getLogger("purple_state")

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE_DIR = os.path.join(_BOT_DIR, "data", "purple")
LINEAGE_CARD_PNG = os.path.join(_BOT_DIR, "data", "lineage_classic_card.png")

SCALE_SWEEP = (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.25)
PURPLE_REF_W = 1642.0
PURPLE_REF_H = 1026.0
TM_THRESH = 0.72
# Small text crops (用户名/电子邮箱) need a slightly lower floor.
TM_THRESH_TEXT = 0.62
FP_SIZE = (48, 28)
# Hamming bits (of 48*28=1344) that must flip to count as a screen change.
FP_CHANGE_BITS = 70


class PurpleScreen(str, Enum):
    UNKNOWN = "unknown"
    LOGIN_EMAIL = "login_email"
    LOGIN_PASSWORD = "login_password"
    LOGGING_IN = "logging_in"
    LOGIN_ERROR = "login_error"
    LAUNCHER = "launcher"
    START_READY = "start_ready"


LOGIN_SCREENS = (PurpleScreen.LOGIN_EMAIL, PurpleScreen.LOGIN_PASSWORD)
LAUNCHER_SCREENS = (PurpleScreen.LAUNCHER, PurpleScreen.START_READY)

# Optional PNG filenames (stem) → control / screen they confirm.
CONTROL_TEMPLATES = {
    # Seeded first-click: 用户名/电子邮箱 (username_email.png). Harvested
    # id_field/email_field are fallbacks only.
    "purple_id_field": ("username_email", "id_or_email", "id_field",
                        "email_field", "username_field"),
    "purple_next": ("next", "next_btn"),
    "purple_password": ("password", "password_field"),
    "purple_login": ("login", "login_btn", "signin"),
    "purple_address": ("address_tab", "email_tab", "id_email_tab"),
    "purple_lineage": ("lineage_nav", "nav_lineage"),
    "purple_lineage_card": ("lineage_card", "lineage_classic_card"),
    "purple_start_game": ("start_game", "run_game"),
}
SCREEN_TEMPLATES = {
    PurpleScreen.LOGIN_EMAIL: ("email_form", "login_email"),
    PurpleScreen.LOGIN_PASSWORD: ("password_form", "login_password"),
    PurpleScreen.LOGGING_IN: ("logging_in",),
    PurpleScreen.LAUNCHER: ("launcher", "my_games"),
    PurpleScreen.START_READY: ("start_ready", "run_game_bar"),
}


def alnum(text: str) -> str:
    return "".join(c for c in (text or "").lower() if c.isalnum())


def _compact(text: str) -> str:
    return (text or "").replace(" ", "")


def classify_blob(raw: str) -> PurpleScreen:
    """Language-tolerant classifier from OCR text. No window required.

    Priority: logging-in → error → password form → email form → start-ready
    → launcher → unknown. Unknown must never be treated as a click target.
    """
    raw = raw or ""
    t = alnum(raw)
    compact = _compact(raw)

    if _is_logging_in(t, compact):
        return PurpleScreen.LOGGING_IN
    if _is_login_error(t, compact):
        return PurpleScreen.LOGIN_ERROR
    if _is_password_form(t, compact):
        return PurpleScreen.LOGIN_PASSWORD
    if _is_email_form(t, compact):
        return PurpleScreen.LOGIN_EMAIL
    if _is_start_ready(t, compact, raw):
        return PurpleScreen.START_READY
    if _is_launcher(t, compact, raw):
        return PurpleScreen.LAUNCHER
    return PurpleScreen.UNKNOWN


def _is_logging_in(t: str, compact: str) -> bool:
    if "loggingin" in t and "password" not in t:
        return True
    if any(k in compact for k in ("登录中", "登彔中", "登錄中", "로그인중")):
        if "password" not in t and "密码" not in compact and "密碼" not in compact:
            return True
    return False


def _is_login_error(t: str, compact: str) -> bool:
    if any(k in t for k in ("incorrect", "wrongpassword", "invalidpassword")):
        return True
    if any(k in compact for k in ("잘못", "오류", "실패", "密码错误", "密碼錯誤")):
        return True
    return False


def _is_password_form(t: str, compact: str) -> bool:
    if "resetpassword" in t and "login" not in t and "signin" not in t:
        return False
    if "password" in t and any(k in t for k in (
            "login", "signin", "anotheraccount", "resetpassword")):
        return True
    if any(k in compact for k in ("비밀번호", "密碼", "密码")) and any(
            k in compact for k in ("로그인", "登入", "登录", "Login")):
        if any(k in compact for k in ("재설정", "重置", "忘记")):
            return False
        return True
    return False


def _is_email_form(t: str, compact: str) -> bool:
    if any(k in t for k in ("emailaddress", "emailadress", "idoremail",
                            "ide-mail", "idemail")):
        return True
    if any(k in compact for k in (
            "用户名", "电子邮箱", "電子郵件", "이메일",
            "免費註冊", "免费注册", "保持登錄", "保持登录",
            "二維碼登錄", "二维码登录", "還不是", "还不是")):
        return True
    if "email" in t and "password" in t:
        return True
    keys = ("email", "qrcode", "signin", "keepme", "joinpurple",
            "phonenumber", "logwithanemail", "idoremail")
    hits = [k for k in keys if k in t]
    if len(hits) >= 2:
        return True
    if "email" in t and ("phone" in t or "qrcode" in t or "qr" in t):
        return True
    return False


def _is_start_ready(t: str, compact: str, raw: str) -> bool:
    if any(k in t for k in ("startgame", "statgame", "stargame")):
        return True
    if any(k in compact for k in ("运行游戏", "開始遊戲", "开始游戏", "게임시작")):
        return True
    return False


def _is_launcher(t: str, compact: str, raw: str) -> bool:
    if any(k in t for k in ("mygames", "installedgames", "lineageclassic",
                            "recommendedgames", "purchasedgames")):
        return True
    if "lineage" in t and any(k in t for k in ("classic", "game")):
        return True
    if any(k in compact for k in ("我的游戏", "安装的游戏", "購買的遊戲",
                                  "내게임", "설치한게임", "天堂经典", "天堂經典")):
        return True
    return False


def fingerprint_pil(img) -> bytes:
    """Average-hash of a downscaled grayscale capture (OCR-free)."""
    if img is None:
        return b""
    try:
        g = img.convert("L").resize(FP_SIZE)
    except Exception:
        return b""
    pixels = list(g.getdata())
    if not pixels:
        return b""
    avg = sum(pixels) / float(len(pixels))
    return bytes(1 if p > avg else 0 for p in pixels)


def hamming(a: bytes, b: bytes) -> int:
    if not a or not b or len(a) != len(b):
        return 10 ** 6
    return sum(x != y for x, y in zip(a, b))


def fingerprint_changed(before: bytes, after: bytes,
                        min_bits: int = FP_CHANGE_BITS) -> bool:
    if not before or not after:
        return False
    return hamming(before, after) >= min_bits


@dataclass
class PurpleView:
    screen: PurpleScreen = PurpleScreen.UNKNOWN
    blob: str = ""
    fingerprint: bytes = b""
    width: int = 0
    height: int = 0
    template_score: float = 0.0
    template_name: str = ""


@dataclass
class TemplateHit:
    name: str
    score: float
    cx: int
    cy: int
    scale: float
    x: int
    y: int
    w: int
    h: int


class PurpleTemplates:
    """Lazy-load optional PNGs from data/purple (+ lineage card)."""

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or DEFAULT_TEMPLATE_DIR
        self._bgr: Dict[str, object] = {}
        self._missing: set = set()
        self._scanned = False

    def _scan(self) -> None:
        if self._scanned:
            return
        self._scanned = True
        try:
            import cv2  # noqa: F401
        except ImportError:
            log.info("cv2 unavailable; Purple templates disabled")
            return
        extra = []
        if os.path.isdir(self.directory):
            for fn in os.listdir(self.directory):
                stem, ext = os.path.splitext(fn)
                if ext.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                    extra.append(os.path.join(self.directory, fn))
        if os.path.isfile(LINEAGE_CARD_PNG):
            extra.append(LINEAGE_CARD_PNG)
        for path in extra:
            stem = os.path.splitext(os.path.basename(path))[0].lower()
            self._load(stem, path)

    def _load(self, stem: str, path: str) -> None:
        if stem in self._bgr or stem in self._missing:
            return
        try:
            import cv2
            tpl = cv2.imread(path)
        except Exception as e:
            log.warning("template load %s failed: %r", path, e)
            self._missing.add(stem)
            return
        if tpl is None:
            self._missing.add(stem)
            return
        self._bgr[stem] = tpl
        log.info("Purple template loaded %s (%dx%d)",
                 stem, tpl.shape[1], tpl.shape[0])

    def reload(self) -> None:
        self._bgr.clear()
        self._missing.clear()
        self._scanned = False
        self._scan()

    def get(self, stem: str):
        self._scan()
        return self._bgr.get(stem.lower())

    def names(self) -> Tuple[str, ...]:
        self._scan()
        return tuple(self._bgr.keys())

    def match(self, img_bgr, stems: Sequence[str],
              thresh: float = TM_THRESH,
              roi: Optional[Tuple[float, float, float, float]] = None,
              first_above: bool = False
              ) -> Optional[TemplateHit]:
        """Multi-scale CCOEFF match. roi is (rx0, ry0, rx1, ry1) fractions.

        When first_above is True, return the first stem that clears thresh
        (stem list order), instead of the global best score.
        """
        self._scan()
        if img_bgr is None:
            return None
        try:
            import cv2
        except ImportError:
            return None
        h, w = img_bgr.shape[:2]
        x0 = y0 = 0
        roi_img = img_bgr
        if roi:
            x0 = int(w * roi[0]); y0 = int(h * roi[1])
            x1 = int(w * roi[2]); y1 = int(h * roi[3])
            roi_img = img_bgr[y0:y1, x0:x1]
            if roi_img.size == 0:
                return None
        rh, rw = roi_img.shape[:2]
        base_h = h / PURPLE_REF_H
        base_w = w / PURPLE_REF_W
        scales = {round(base_h * m, 4) for m in SCALE_SWEEP}
        scales |= {round(base_w * m, 4) for m in SCALE_SWEEP}
        scales.add(1.0)
        best = None  # (score, loc, tw, th, scale, stem)
        for stem in stems:
            tpl = self.get(stem)
            if tpl is None:
                continue
            stem_best = None
            for s in sorted(scales):
                if s <= 0.05:
                    continue
                t = cv2.resize(tpl, None, fx=s, fy=s,
                               interpolation=cv2.INTER_AREA)
                th, tw = t.shape[:2]
                if th < 8 or tw < 8 or th >= rh or tw >= rw:
                    continue
                res = cv2.matchTemplate(roi_img, t, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if stem_best is None or mv > stem_best[0]:
                    stem_best = (mv, ml, tw, th, s, stem)
            if stem_best is None:
                continue
            if first_above and stem_best[0] >= thresh:
                best = stem_best
                break
            if best is None or stem_best[0] > best[0]:
                best = stem_best
        if not best or best[0] < thresh:
            if best:
                log.debug("template best=%.3f below %.2f (%s)",
                          best[0], thresh, best[5])
            return None
        mx, my = best[1][0] + x0, best[1][1] + y0
        tw, th = best[2], best[3]
        return TemplateHit(
            name=best[5], score=float(best[0]),
            cx=mx + tw // 2, cy=my + th // 2,
            scale=float(best[4]), x=mx, y=my, w=tw, h=th)


class PurpleWatcher:
    """Per-bot cache of the last Purple view + template bank."""

    def __init__(self, bot, template_dir: Optional[str] = None):
        self.bot = bot
        cfg = getattr(bot, "cfg", None) or {}
        directory = template_dir or cfg.get("purple_template_dir") or ""
        if directory and not os.path.isabs(directory):
            directory = os.path.join(_BOT_DIR, directory)
        self.templates = PurpleTemplates(directory or DEFAULT_TEMPLATE_DIR)
        self._view: Optional[PurpleView] = None
        self._at = 0.0
        self.ttl = float(cfg.get("purple_view_ttl_sec", 0.35) or 0.35)

    def invalidate(self) -> None:
        self._view = None
        self._at = 0.0

    def cached(self) -> Optional[PurpleView]:
        return self._view

    def classify_from_blob(self, raw: str, width: int = 0,
                           height: int = 0) -> PurpleView:
        screen = classify_blob(raw)
        return PurpleView(screen=screen, blob=raw or "",
                          width=width, height=height)

    def match_control(self, key: str, img_bgr) -> Optional[TemplateHit]:
        stems = list(CONTROL_TEMPLATES.get(key) or (key,))
        if key == "purple_lineage_card":
            stems.append("lineage_classic_card")
        thresh = float((getattr(self.bot, "cfg", None) or {}).get(
            "purple_tm_thresh", TM_THRESH) or TM_THRESH)
        if key == "purple_id_field":
            thresh = float((getattr(self.bot, "cfg", None) or {}).get(
                "purple_tm_thresh_text", TM_THRESH_TEXT) or TM_THRESH_TEXT)
        roi = None
        if key == "purple_lineage":
            roi = (0.0, 0.12, 0.32, 0.85)
        elif key == "purple_lineage_card":
            roi = (0.10, 0.08, 0.95, 0.92)
        elif key == "purple_start_game":
            roi = (0.55, 0.70, 1.0, 1.0)
        elif key in ("purple_id_field", "purple_next", "purple_password",
                     "purple_login", "purple_address"):
            roi = (0.18, 0.10, 0.82, 0.72)
        # Prefer seeded stems in listed order (username_email before harvested
        # band crops) so a large id_field crop cannot steal the click.
        ordered = key == "purple_id_field"
        return self.templates.match(
            img_bgr, stems, thresh=thresh, roi=roi, first_above=ordered)

    def match_screen_template(self, img_bgr) -> Optional[Tuple[PurpleScreen, TemplateHit]]:
        thresh = float((getattr(self.bot, "cfg", None) or {}).get(
            "purple_tm_thresh", TM_THRESH) or TM_THRESH)
        best = None
        for screen, stems in SCREEN_TEMPLATES.items():
            hit = self.templates.match(img_bgr, stems, thresh=thresh)
            if hit and (best is None or hit.score > best[1].score):
                best = (screen, hit)
        return best


def _login_card_roi(img_bgr):
    h, w = img_bgr.shape[:2]
    x0 = int(w * 0.18)
    x1 = int(w * 0.82)
    y0 = int(h * 0.08)
    y1 = int(h * 0.78)
    return img_bgr[y0:y1, x0:x1], (x0, y0)


def _find_login_cta(card):
    """Locate the Next/Login bar: HSV + BGR blue/navy/cyan, then row chroma."""
    import cv2
    import numpy as np
    if card is None or card.size == 0:
        return None
    ch, cw = card.shape[:2]
    hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, (70, 20, 30), (160, 255, 255)),
        cv2.inRange(hsv, (85, 40, 40), (145, 255, 255)),
    )
    b = card[:, :, 0].astype(np.int16)
    g = card[:, :, 1].astype(np.int16)
    r = card[:, :, 2].astype(np.int16)
    rgb_mask = ((b > 55) & (b > r + 8) & (b >= g - 15)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask, rgb_mask)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    min_bw = max(48, int(cw * 0.10))
    for c in cnts:
        bx, by, bw, bh = cv2.boundingRect(c)
        if bw < min_bw or bh < 10 or bh > 96:
            continue
        if by < ch * 0.10:
            continue
        area = bw * bh
        if best is None or area > best[0]:
            best = (area, bx, by, bw, bh)
    if best is not None:
        return best[1:]
    return _find_login_cta_by_rows(card)


def _find_login_cta_by_rows(card):
    """Fallback: light input band, then the first colored bar below it."""
    import numpy as np
    ch, cw = card.shape[:2]
    x0, x1 = int(cw * 0.08), int(cw * 0.92)
    strip = card[:, x0:x1]
    if strip.size == 0:
        return None
    mean = strip.reshape(ch, -1, 3).mean(axis=1)
    b, g, r = mean[:, 0], mean[:, 1], mean[:, 2]
    luma = 0.114 * b + 0.587 * g + 0.299 * r
    chroma = np.maximum(np.maximum(np.abs(b - g), np.abs(g - r)), np.abs(r - b))
    light = (luma > 185) & (chroma < 22)
    colored = (chroma > 14) & (luma > 35) & (luma < 235)

    def _clusters(flags):
        out = []
        run = None
        for i, on in enumerate(flags):
            if on:
                if run is None:
                    run = [i, i]
                else:
                    run[1] = i
            elif run is not None:
                out.append(tuple(run))
                run = None
        if run is not None:
            out.append(tuple(run))
        return out

    lights = [c for c in _clusters(light) if (c[1] - c[0] + 1) >= 16]
    bars = [c for c in _clusters(colored) if 10 <= (c[1] - c[0] + 1) <= 70]
    pair = None
    for lf in lights:
        below = [br for br in bars if br[0] >= lf[1] + 4]
        if below:
            pair = (lf, below[0])
            break
    if pair is None and bars:
        # lowest mid-card bar (Next sits under the ID field)
        mid = [br for br in bars if br[0] > ch * 0.18]
        br = (mid or bars)[-1]
        hgt = br[1] - br[0] + 1
        fy1 = br[0] - 8
        fy0 = max(0, fy1 - max(28, hgt + 8))
        pair = ((fy0, fy1), br)
    if pair is None:
        return None
    _lf, br = pair
    by, bh = br[0], br[1] - br[0] + 1
    bx, bw = x0, x1 - x0
    return (bx, by, bw, bh)


def harvest_login_email_templates(img_bgr, directory: str) -> Dict[str, str]:
    """Crop Address tab / email field / Next from a live login capture.

    Uses the colored CTA (or the bar under the light ID field) as the
    anchor — no OCR. Writes PNG stems that CONTROL_TEMPLATES looks up.
    """
    import cv2
    import numpy as np
    if img_bgr is None:
        return {}
    os.makedirs(directory, exist_ok=True)
    card, _origin = _login_card_roi(img_bgr)
    if card.size == 0:
        return {}
    found = _find_login_cta(card)
    if found is None:
        dbg = os.path.join(directory, "_harvest_debug.png")
        try:
            cv2.imwrite(dbg, img_bgr)
            mean = card.reshape(-1, 3).mean(axis=0)
            log.warning("harvest: no Next/CTA in login card meanBGR=%.0f,%.0f,%.0f saved %s",
                        mean[0], mean[1], mean[2], dbg)
        except Exception:
            log.warning("harvest: no Next/CTA in login card")
        return {}
    bx, by, bw, bh = found
    ch, cw = card.shape[:2]
    written: Dict[str, str] = {}

    def _save(stem: str, crop) -> None:
        if crop is None or crop.size == 0:
            return
        path = os.path.join(directory, stem + ".png")
        cv2.imwrite(path, crop)
        written[stem] = path
        log.info("harvested login template %s %dx%d -> %s",
                 stem, crop.shape[1], crop.shape[0], path)

    nx0 = max(0, bx - 6)
    ny0 = max(0, by - 4)
    nx1 = min(cw, bx + bw + 6)
    ny1 = min(ch, by + bh + 4)
    _save("next", card[ny0:ny1, nx0:nx1])
    _save("next_btn", card[ny0:ny1, nx0:nx1])

    gap = max(8, int(bh * 0.35))
    fhgt = max(28, min(52, int(bh * 1.35)))
    fy1 = max(fhgt + 2, by - gap)
    fy0 = max(0, fy1 - fhgt)
    fx0 = max(0, bx - int(bw * 0.08))
    fx1 = min(cw, bx + bw + int(bw * 0.08))
    if fy1 - fy0 >= 20 and fx1 - fx0 >= 80:
        # Keep the seeded 用户名/电子邮箱 crop; do not replace with a band crop.
        seed = os.path.join(directory, "username_email.png")
        if not os.path.isfile(seed):
            _save("id_field", card[fy0:fy1, fx0:fx1])
            _save("email_field", card[fy0:fy1, fx0:fx1])
        else:
            log.info("keep seeded username_email.png; skip harvested id_field")

    thgt = max(22, min(40, int(bh * 0.95)))
    ty1 = max(thgt + 2, fy0 - 6)
    ty0 = max(0, ty1 - thgt)
    tx0 = max(0, fx0)
    tx1 = min(cw, fx0 + max(90, int((fx1 - fx0) * 0.62)))
    if ty1 - ty0 >= 16 and tx1 - tx0 >= 60:
        _save("address_tab", card[ty0:ty1, tx0:tx1])
        _save("email_tab", card[ty0:ty1, tx0:tx1])
        _save("id_email_tab", card[ty0:ty1, tx0:tx1])
    return written


def expected_screens_for(key: str) -> Tuple[PurpleScreen, ...]:
    return {
        "purple_address": LOGIN_SCREENS,
        "purple_id_field": (PurpleScreen.LOGIN_EMAIL,),
        "purple_next": (PurpleScreen.LOGIN_EMAIL,),
        "purple_password": (PurpleScreen.LOGIN_PASSWORD,),
        "purple_login": (PurpleScreen.LOGIN_PASSWORD,),
        "purple_lineage": LAUNCHER_SCREENS,
        "purple_lineage_card": LAUNCHER_SCREENS,
        "purple_start_game": (PurpleScreen.START_READY,),
    }.get(key, (PurpleScreen.UNKNOWN,))
