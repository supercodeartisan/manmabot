"""Window-relative click positions for Dynamic / Fixed search methods.

Dynamic: OCR/template detection finds the control, then the click is saved
to position_dict.json as a ratio of the Purple or game window.

Fixed: the state engine still classifies the screen; the click itself uses
the saved ratio (scaled to the live window). Missing keys fall back to
detection so a first run without a dict still works.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Optional, Tuple

log = logging.getLogger("positions")

MODE_DYNAMIC = "dynamic"
MODE_FIXED = "fixed"

# Character-select slots as fractions of the live game window (matches GameFlow).
CHAR_SLOT_RATIOS = [
    (0.215, 0.313),
    (0.490, 0.313),
    (0.741, 0.313),
]


def _parse_size_key(key: str) -> Optional[Tuple[float, float]]:
    m = re.match(r"^(\d+)x(\d+)$", str(key).strip(), re.I)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def normalize_page_key(page) -> str:
    s = str(page or "").strip()
    if s.lower().startswith("pos_"):
        s = s[4:]
    return s


def normalize_page_positions(raw) -> dict:
    """Return {page_id: {"rx": float, "ry": float}} for any supported format.

    Supported shapes:
      - {"pages": {"2": {"rx": 0.46, "ry": 0.60}}}
      - {"2": {"rx": 0.46, "ry": 0.60}}
      - {"816x639": {"2": [373, 384]}}  (legacy pixels; converted via key)
      - {"816x639": {"pos_2": [373, 384]}}
    """
    if not raw or not isinstance(raw, dict):
        return {}

    out: dict = {}

    def _store(page_id: str, rx: float, ry: float) -> None:
        page_id = normalize_page_key(page_id)
        if not page_id:
            return
        out[page_id] = {"rx": float(rx), "ry": float(ry)}

    pages = raw.get("pages")
    if isinstance(pages, dict):
        for page_id, val in pages.items():
            if isinstance(val, dict) and "rx" in val and "ry" in val:
                _store(page_id, val["rx"], val["ry"])

    for key, val in raw.items():
        if key in ("pages", "ref_w", "ref_h") or not isinstance(val, dict):
            continue
        if "rx" in val and "ry" in val:
            _store(key, val["rx"], val["ry"])
            continue
        size = _parse_size_key(key)
        if size is None:
            continue
        rw, rh = size
        if rw <= 0 or rh <= 0:
            continue
        for page_id, pos in val.items():
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                _store(page_id, float(pos[0]) / rw, float(pos[1]) / rh)
            elif isinstance(pos, dict) and "rx" in pos and "ry" in pos:
                _store(page_id, pos["rx"], pos["ry"])

    return out


def window_client_rect(win):
    return getattr(win, "client_rect", None) or getattr(win, "rect", None)


def client_ratio_xy(win, rx: float, ry: float) -> Optional[Tuple[int, int]]:
    """Map window-relative ratios to client pixel coordinates."""
    r = window_client_rect(win)
    if r is None or r.width <= 0 or r.height <= 0:
        return None
    return int(float(rx) * r.width), int(float(ry) * r.height)


def page_client_xy(page_positions_raw, page, win) -> Optional[Tuple[int, int]]:
    """Resolve a page button click for the live window size."""
    norms = normalize_page_positions(page_positions_raw)
    rec = norms.get(normalize_page_key(page))
    if rec is None:
        return None
    return client_ratio_xy(win, rec["rx"], rec["ry"])


def char_slot_client_xy(win, slot_index: int) -> Optional[Tuple[int, int]]:
    """0-based character slot index -> client pixels on the live game window."""
    if slot_index < 0 or slot_index >= len(CHAR_SLOT_RATIOS):
        slot_index = 0
    return client_ratio_xy(win, *CHAR_SLOT_RATIOS[slot_index])

_LOCK = threading.Lock()

_DEFAULT_NAME = "position_dict.json"


def default_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        _DEFAULT_NAME)


def canonical_key(label: str) -> str:
    """Stable dict key from a click label."""
    s = re.sub(r"\s+", " ", str(label or "")).strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("agree"):
        return "agree"
    # page 1 / page 2 use page_positions ratios — do not collapse to one key
    if low.startswith("page ") or low.startswith("page("):
        return ""
    if low == "page" or low.startswith("page"):
        return "page"
    if "after-char" in low:
        return "ok_after_char"
    # Must precede the generic "server" match — labels like
    # ok(server-confirm-fixed) contain "server" but mean ok_right.
    if ("server-confirm" in low
            or low.startswith("ok(server")
            or low.startswith("ok(right")
            or "ok(right" in low):
        return "ok_right"
    if low.startswith("char") or low.startswith("character"):
        return "char"
    # Table cell clicks are absolute (row/col from servers_*.json)
    if "table" in low:
        return ""
    if "server" in low:
        return "server"
    if "address" in low or "adress" in low:
        return "purple_address"
    if "用户名" in s or "电子邮箱" in s:
        return "purple_id_field"
    if "id or e-mail" in low or "id or email" in low:
        return "purple_id_field"
    if low.startswith("next") or " next" in low or low == "next (blue)":
        return "purple_next"
    if "password" in low:
        return "purple_password"
    if "blue button" in low or low in ("login", "sign in") or "ocr login" in low:
        return "purple_login"
    if "lineage" in low:
        if "card" in low or "classic" in low:
            return "purple_lineage_card"
        return "purple_lineage"
    if low == "lineage" or "lineage nav" in low:
        return "purple_lineage"
    if "天堂" in s or "经典" in s or "經典" in s:
        return "purple_lineage_card"
    if "start game" in low or low in ("start_game", "startgame"):
        return "purple_start_game"
    if "运行游戏" in s:
        return "purple_start_game"
    key = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
    return key[:48]


class PositionStore:
    def __init__(self, path: Optional[str] = None, mode: str = MODE_DYNAMIC,
                 cfg: Optional[dict] = None):
        self.path = path or default_path()
        cfg = cfg or {}
        raw = (cfg.get("click_mode") or mode or MODE_DYNAMIC).strip().lower()
        purple_raw = (cfg.get("purple_click_mode") or "").strip().lower()
        game_raw = (cfg.get("game_click_mode") or "").strip().lower()

        def _parse_mode(s: str) -> str:
            return MODE_FIXED if s.startswith("fix") else MODE_DYNAMIC

        if raw in ("hybrid", "split"):
            self.purple_mode = MODE_DYNAMIC
            self.game_mode = MODE_FIXED
        elif purple_raw or game_raw:
            self.purple_mode = _parse_mode(purple_raw or raw)
            self.game_mode = _parse_mode(game_raw or raw)
        else:
            m = _parse_mode(raw)
            self.purple_mode = m
            self.game_mode = m

        self.mode = raw
        self.data = {"purple": {}, "game": {}}
        # Operate / L0: default read-only so consumer runs never corrupt ratios.
        # Enable writes with cfg position_dict_writable=true or bot.learn.
        writable_cfg = cfg.get("position_dict_writable")
        if writable_cfg is None:
            # dynamic purple historically recorded clicks; keep that unless
            # explicitly operating fixed/L0 pipeline.
            policy = str(cfg.get("lang_policy") or "").strip().upper()
            use_pipe = bool(cfg.get("use_pipeline"))
            self._writable = not (
                policy in ("L0", "LOCK", "FIXED") or use_pipe
                or self.purple_mode == MODE_FIXED)
        else:
            self._writable = bool(writable_cfg)
        self.load()
        if self.purple_mode != self.game_mode:
            log.info("click search purple=%s game=%s file=%s writable=%s",
                     self.purple_mode, self.game_mode, self.path, self._writable)
        else:
            log.info("click search method=%s file=%s writable=%s",
                     self.purple_mode, self.path, self._writable)

    def set_writable(self, writable: bool) -> None:
        self._writable = bool(writable)
        log.info("position_dict writable=%s (%s)", self._writable, self.path)

    @property
    def writable(self) -> bool:
        return bool(getattr(self, "_writable", True))

    @property
    def is_fixed(self) -> bool:
        return self.purple_mode == MODE_FIXED and self.game_mode == MODE_FIXED

    @property
    def is_dynamic(self) -> bool:
        return self.purple_mode == MODE_DYNAMIC and self.game_mode == MODE_DYNAMIC

    @property
    def is_fixed_purple(self) -> bool:
        return self.purple_mode == MODE_FIXED

    @property
    def is_fixed_game(self) -> bool:
        return self.game_mode == MODE_FIXED

    @property
    def is_dynamic_purple(self) -> bool:
        return self.purple_mode == MODE_DYNAMIC

    @property
    def is_dynamic_game(self) -> bool:
        return self.game_mode == MODE_DYNAMIC

    def is_fixed_space(self, space: str) -> bool:
        return self.is_fixed_purple if space == "purple" else self.is_fixed_game

    def is_dynamic_space(self, space: str) -> bool:
        return self.is_dynamic_purple if space == "purple" else self.is_dynamic_game

    def load(self) -> None:
        try:
            if os.path.isfile(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
                if isinstance(raw, dict):
                    if "purple" in raw or "game" in raw:
                        self.data["purple"] = dict(raw.get("purple") or {})
                        self.data["game"] = dict(raw.get("game") or {})
                    else:
                        # flatten recorded_clicks-style keys into purple/game
                        for k, v in raw.items():
                            if not isinstance(v, dict):
                                continue
                            space = "purple" if str(k).startswith("purple") else "game"
                            self.data[space][k] = v
        except Exception as e:
            log.warning("position_dict load failed: %r", e)

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            log.warning("position_dict save failed: %r", e)

    def lookup(self, space: str, key: str) -> Optional[dict]:
        if not key:
            return None
        bucket = self.data.get(space) or {}
        rec = bucket.get(key)
        return rec if isinstance(rec, dict) and "rx" in rec and "ry" in rec else None

    def record_client(self, space: str, key: str, win, cx: float, cy: float) -> None:
        if not self.is_dynamic_space(space) or not key or win is None:
            return
        if not self.writable:
            log.debug("skip save %s/%s: position_dict read-only (operate)",
                      space, key)
            return
        r = getattr(win, "client_rect", None) or getattr(win, "rect", None)
        if r is None or r.width <= 0 or r.height <= 0:
            return
        # Purple login positions must come from the main shell (1642x1026),
        # not the 450x773 / 962x670 popup — bad ratios break later runs.
        if space == "purple" and r.width < 900:
            log.debug("skip save %s/%s: Purple window too narrow (%dx%d)",
                      space, key, r.width, r.height)
            return
        entry = {
            "rx": round(float(cx) / float(r.width), 4),
            "ry": round(float(cy) / float(r.height), 4),
            "cx": int(cx),
            "cy": int(cy),
            "win_w": int(r.width),
            "win_h": int(r.height),
        }
        with _LOCK:
            self.data.setdefault(space, {})[key] = entry
            self.save()
        log.info("saved %s/%s rx=%.3f ry=%.3f on %dx%d",
                 space, key, entry["rx"], entry["ry"], r.width, r.height)

    def record_screen(self, space: str, key: str, win, sx: float, sy: float) -> None:
        if win is None:
            return
        r = getattr(win, "rect", None)
        if r is None:
            return
        self.record_client(space, key, win, sx - r.left, sy - r.top)

    def client_xy(self, space: str, key: str, win) -> Optional[Tuple[int, int]]:
        rec = self.lookup(space, key)
        if rec is None or win is None:
            return None
        r = getattr(win, "client_rect", None) or getattr(win, "rect", None)
        if r is None or r.width <= 0 or r.height <= 0:
            return None
        return (int(float(rec["rx"]) * r.width),
                int(float(rec["ry"]) * r.height))

    def screen_xy(self, space: str, key: str, win) -> Optional[Tuple[int, int]]:
        xy = self.client_xy(space, key, win)
        if xy is None or win is None:
            return None
        r = getattr(win, "rect", None)
        if r is None:
            return None
        return (r.left + xy[0], r.top + xy[1])
