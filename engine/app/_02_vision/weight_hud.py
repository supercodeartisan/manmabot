"""Lineage Classic HUD weight(%) via template matching.

Port of ``weight_tm_v2/Tm_w_v2.py``. The live loop feeds the captured BGR
frame; a successful read writes ``PlayerState.inventory.weight_ratio``.
Memory snapshots supply weight/maxWeight; HUD OCR is fallback only.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import cv2
import numpy as np

from app._03_world.player import memory_weight_ready

if TYPE_CHECKING:
    from app._03_world.gamestate import GameState

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "app" / "models" / "weight" / "numeric_config.json"

TARGET_RATIO = 8.0 / 6.0
RATIO_TOLERANCE = 0.01
MIN_RATIO = TARGET_RATIO * (1 - RATIO_TOLERANCE)
MAX_RATIO = TARGET_RATIO * (1 + RATIO_TOLERANCE)
MARKER_MAX_HEIGHT_RATIO = 0.075
MAX_ITERATIONS = 1
STANDARD_WIDTH = 1440
STANDARD_HEIGHT = 1080

_CANON_H = 48
_CANON_W = 36
_EDGE_K = np.ones((3, 3), np.uint8)
_HYPOT_CANON = math.hypot(_CANON_W, _CANON_H)

WHITE_PIXEL_THRESHOLD = 220
WHITE_CHANNEL_SPREAD = 35
ROW_WHITE_RATIO_THRESHOLD = 0.70
MIN_BAND_HEIGHT_RATIO = 0.00
EXPECTED_BAND_HEIGHT_RATIO = 0.035
MAX_BAND_HEIGHT_RATIO = 0.075
MAX_BAND_START_RATIO = 0.015
MIN_HORIZONTAL_CONTINUITY = 0.70
MIN_BRIGHTNESS_CONTRAST = 30.0
INSPECT_TOP_RATIO = 0.10
BAND_BRIDGE_WHITE_RATIO = 0.50

_CONFIG: dict[str, Any] | None = None
_CONFIG_PATH: Path | None = None
_TEMPLATES: dict[str, Any] | None = None
_TEMPLATE_KEY: str | None = None

DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_INTERVAL_FRAMES = 1


@dataclass(frozen=True)
class WeightReading:
    """One HUD bag-fill estimate. ``percent`` is None when unread."""

    raw: str
    percent: Optional[int]
    confidence: float

    @property
    def ratio(self) -> Optional[float]:
        if self.percent is None:
            return None
        return max(0.0, min(1.0, self.percent / 100.0))


def _get_config(config_path: Path | str | None = None) -> dict[str, Any]:
    global _CONFIG, _CONFIG_PATH
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    path = path.resolve()
    if _CONFIG is None or _CONFIG_PATH != path:
        with open(path, "r", encoding="utf-8") as handle:
            _CONFIG = json.load(handle)
        _CONFIG_PATH = path
    return _CONFIG


def _detect_marker_band_bgr(bgr: np.ndarray) -> tuple[Optional[int], Optional[int]]:
    h, w = bgr.shape[:2]
    limit = max(1, int(h * INSPECT_TOP_RATIO))
    top = bgr[:limit]
    step = 2 if w >= 8 else 1
    sl = top[:, ::step]
    b = sl[..., 0]
    g = sl[..., 1]
    r = sl[..., 2]
    mx = cv2.max(cv2.max(r, g), b)
    mn = cv2.min(cv2.min(r, g), b)
    white = (
        (r >= WHITE_PIXEL_THRESHOLD)
        & (g >= WHITE_PIXEL_THRESHOLD)
        & (b >= WHITE_PIXEL_THRESHOLD)
        & ((mx - mn) <= WHITE_CHANNEL_SPREAD)
    )
    row_white = white.mean(axis=1)
    row_luma = cv2.cvtColor(top, cv2.COLOR_BGR2GRAY).mean(axis=1)

    vals = row_white
    n = len(vals)
    runs = []
    start = None
    thr = ROW_WHITE_RATIO_THRESHOLD
    for y in range(n):
        if vals[y] >= thr:
            if start is None:
                start = y
        elif start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, n - 1))

    if len(runs) > 1:
        merged = [runs[0]]
        for run in runs[1:]:
            prev_end = merged[-1][1]
            gap_start = prev_end + 1
            if run[0] > gap_start and gap_start < n:
                gap_white = float(row_white[gap_start:run[0]].mean())
            else:
                gap_white = 0.0
            if gap_white >= BAND_BRIDGE_WHITE_RATIO:
                merged[-1] = (merged[-1][0], run[1])
            else:
                merged.append(run)
        runs = merged

    if not runs:
        return None, None

    start, end = max(runs, key=lambda p: p[1] - p[0] + 1)
    band_h = end - start + 1
    white_ratio = float(row_white[start:end + 1].mean())
    continuity = band_h / h
    start_ratio = start / h

    below_start = end + 2
    below_height = max(10, int(h * EXPECTED_BAND_HEIGHT_RATIO))
    below_end = min(limit, below_start + below_height)
    band_luma = float(row_luma[start:end + 1].mean())
    if below_start < below_end:
        contrast = band_luma - float(row_luma[below_start:below_end].mean())
    else:
        contrast = 0.0

    height_ok = MIN_BAND_HEIGHT_RATIO <= continuity <= MAX_BAND_HEIGHT_RATIO
    start_ok = start_ratio <= MAX_BAND_START_RATIO
    continuity_ok = white_ratio >= MIN_HORIZONTAL_CONTINUITY
    contrast_ok = contrast >= MIN_BRIGHTNESS_CONTRAST

    if height_ok and start_ok and continuity_ok and contrast_ok:
        return start, end
    return None, None


def _aspect_ratio_ok(width: int, height: int) -> bool:
    if height <= 0:
        return False
    return MIN_RATIO <= width / height <= MAX_RATIO


def _detect_black_sides_bgr(
    bgr: np.ndarray,
    black_threshold: float = 30.0,
    black_ratio: float = 0.80,
    symmetry: float = 0.20,
) -> Optional[int]:
    h, w = bgr.shape[:2]
    target_w = h * TARGET_RATIO
    if target_w >= w:
        return None
    left_w = int(round((w - target_w) / 2))
    if left_w <= 0:
        return None

    rs = 2 if h >= 8 else 1
    cs = 2 if left_w >= 8 else 1
    left = bgr[::rs, :left_w:cs]
    right = bgr[::rs, w - left_w::cs]
    left_gray = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
    left_ratio = float((left_gray < black_threshold).mean())
    right_ratio = float((right_gray < black_threshold).mean())
    if left_ratio < black_ratio or right_ratio < black_ratio:
        return None
    if abs(left_ratio - right_ratio) > symmetry:
        return None
    return left_w


def _content_crop_bgr(bgr: np.ndarray) -> np.ndarray:
    image = bgr
    marker_removed = False
    for _ in range(MAX_ITERATIONS):
        changed = False
        if not marker_removed:
            start, end = _detect_marker_band_bgr(image)
            if start is not None and end is not None:
                h = image.shape[0]
                band_h = end - start + 1
                if band_h <= h * MARKER_MAX_HEIGHT_RATIO:
                    new_top = end + 1
                    if 0 < new_top < h:
                        image = image[new_top:]
                        marker_removed = True
                        changed = True
        h, w = image.shape[:2]
        if not _aspect_ratio_ok(w, h):
            left_w = _detect_black_sides_bgr(image)
            if left_w is not None:
                image = image[:, left_w:w - left_w]
                changed = True
        h, w = image.shape[:2]
        if _aspect_ratio_ok(w, h) or not changed:
            break
    return image


def _map_numeric_roi(content_bgr: np.ndarray, cfg: dict[str, Any]) -> Optional[np.ndarray]:
    ch, cw = content_bgr.shape[:2]
    x1, y1, x2, y2 = cfg["NUMERIC_ROI"]
    tw = max(1, int(x2) - int(x1))
    th = max(1, int(y2) - int(y1))
    sx = cw / STANDARD_WIDTH
    sy = ch / STANDARD_HEIGHT
    rx1 = max(0, min(cw - 1, int(round(x1 * sx))))
    ry1 = max(0, min(ch - 1, int(round(y1 * sy))))
    rx2 = max(rx1 + 1, min(cw, int(round(x2 * sx))))
    ry2 = max(ry1 + 1, min(ch, int(round(y2 * sy))))
    roi_src = content_bgr[ry1:ry2, rx1:rx2]
    if roi_src.size == 0:
        return None
    if roi_src.shape[1] != tw or roi_src.shape[0] != th:
        interp = (
            cv2.INTER_AREA
            if (roi_src.shape[1] > tw or roi_src.shape[0] > th)
            else cv2.INTER_LINEAR
        )
        roi_src = cv2.resize(roi_src, (tw, th), interpolation=interp)
    return roi_src


def extract_numeric_roi(bgr: np.ndarray, cfg: dict[str, Any]) -> Optional[np.ndarray]:
    content = _content_crop_bgr(bgr)
    return _map_numeric_roi(content, cfg)


def _to_canon(bin_u8: np.ndarray) -> np.ndarray:
    h, w = bin_u8.shape[:2]
    scale = min(_CANON_H / h, _CANON_W / w)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = cv2.resize(bin_u8, (nw, nh), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((_CANON_H, _CANON_W), np.uint8)
    x0 = (_CANON_W - nw) // 2
    y0 = (_CANON_H - nh) // 2
    out[y0:y0 + nh, x0:x0 + nw] = resized
    return out


def _moments_centroid(bin_u8: np.ndarray) -> tuple[float, float, bool]:
    m = cv2.moments(bin_u8, binaryImage=True)
    if m["m00"] < 1:
        return 0.0, 0.0, False
    return m["m10"] / m["m00"], m["m01"] / m["m00"], True


def _pack_label(imgs: list[np.ndarray]) -> dict[str, Any]:
    bins, counts, cx, cy, valid, edges, ecounts = [], [], [], [], [], [], []
    for img in imgs:
        b = _to_canon(((img > 0).astype(np.uint8)) * 255)
        b01 = (b > 0).astype(np.uint8)
        bins.append(b01)
        counts.append(int(b01.sum()))
        x, y, ok = _moments_centroid(b)
        cx.append(x)
        cy.append(y)
        valid.append(ok)
        e = cv2.morphologyEx(b, cv2.MORPH_GRADIENT, _EDGE_K)
        e01 = (e > 0).astype(np.uint8)
        edges.append(e01)
        ecounts.append(int(e01.sum()))
    bin_arr = np.stack(bins, axis=0)
    edge_arr = np.stack(edges, axis=0)
    n = bin_arr.shape[0]
    return {
        "flat": bin_arr.reshape(n, -1).astype(np.int32),
        "count": np.asarray(counts, dtype=np.int32),
        "cx": np.asarray(cx, dtype=np.float32),
        "cy": np.asarray(cy, dtype=np.float32),
        "valid": np.asarray(valid, dtype=np.bool_),
        "eflat": edge_arr.reshape(n, -1).astype(np.int32),
        "ecount": np.asarray(ecounts, dtype=np.int32),
    }


def load_templates(template_dir: str | Path) -> dict[str, Any]:
    templates: dict[str, Any] = {}
    for lbl in os.listdir(template_dir):
        d = os.path.join(str(template_dir), lbl)
        if not os.path.isdir(d):
            continue
        imgs = []
        for name in os.listdir(d):
            if not name.endswith(".png"):
                continue
            data = np.fromfile(os.path.join(d, name), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            imgs.append(img)
        if imgs:
            templates[lbl] = _pack_label(imgs)
    return templates


def get_templates(cfg: dict[str, Any], *, config_path: Path | None = None) -> dict[str, Any]:
    global _TEMPLATES, _TEMPLATE_KEY
    key = cfg["MATCHER"]["template_dir"]
    if not os.path.isabs(key):
        base = config_path if config_path is not None else _CONFIG_PATH
        if base is None:
            base = _DEFAULT_CONFIG_PATH
        key = os.path.join(os.path.dirname(str(base)), key)
    if _TEMPLATES is None or _TEMPLATE_KEY != key:
        _TEMPLATES = load_templates(key)
        _TEMPLATE_KEY = key
    return _TEMPLATES


def build_glyph_mask(roi_bgr: np.ndarray, mask_cfg: dict[str, Any]) -> np.ndarray:
    gray_threshold = mask_cfg["gray_threshold"]
    sat_max = mask_cfg.get("sat_max")

    if roi_bgr.ndim == 3:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        _, bright = cv2.threshold(gray, gray_threshold, 255, cv2.THRESH_BINARY)
        if sat_max is not None:
            hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
            low_sat = (hsv[..., 1] <= sat_max).astype(np.uint8) * 255
            return cv2.bitwise_and(bright, low_sat)
        return bright
    _, mask = cv2.threshold(roi_bgr, gray_threshold, 255, cv2.THRESH_BINARY)
    return mask


def segment_bands(mask: np.ndarray, bands: list[list[int]]) -> list[Optional[np.ndarray]]:
    h, w = mask.shape[:2]
    glyphs: list[Optional[np.ndarray]] = []
    for x0, x1 in bands:
        x0 = max(0, min(x0, w))
        x1 = max(x0 + 1, min(x1, w))
        band = mask[:, x0:x1]
        rows = np.flatnonzero(band.any(axis=1))
        if rows.size == 0:
            glyphs.append(None)
            continue
        cols = np.flatnonzero(band.any(axis=0))
        glyphs.append(band[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1])
    return glyphs


def _score_glyph(glyph: np.ndarray, templates: dict[str, Any]) -> dict[str, float]:
    g = _to_canon(((glyph > 0).astype(np.uint8)) * 255)
    g01 = (g > 0).astype(np.uint8)
    gcount = int(g01.sum())
    gcx, gcy, gok = _moments_centroid(g)
    ge = (cv2.morphologyEx(g, cv2.MORPH_GRADIENT, _EDGE_K) > 0).astype(np.uint8)
    gecount = int(ge.sum())
    gflat = g01.ravel().astype(np.int32)
    eflat = ge.ravel().astype(np.int32)

    scores: dict[str, float] = {}
    for label, pack in templates.items():
        inter = pack["flat"] @ gflat
        total = pack["count"] + gcount
        pixel = np.divide(
            2.0 * inter,
            total,
            out=np.zeros(inter.shape, dtype=np.float64),
            where=total != 0,
        )

        if gok:
            d = np.hypot(pack["cx"] - gcx, pack["cy"] - gcy)
            shape = np.maximum(0.0, 1.0 - d / _HYPOT_CANON)
            shape = np.where(pack["valid"], shape, 0.0)
        else:
            shape = 0.0

        einter = pack["eflat"] @ eflat
        etotal = pack["ecount"] + gecount
        edges = np.divide(
            2.0 * einter,
            etotal,
            out=np.zeros(einter.shape, dtype=np.float64),
            where=etotal != 0,
        )

        v = pixel * 0.5 + shape * 0.3 + edges * 0.2
        scores[label] = float(v.max()) if v.size else -1.0
    return scores


def _resolve(digits: list[str], glyph_scores: list[dict[str, float]], min_score: float) -> str:
    text = "".join(digits)
    text = text.replace("%", "")
    kept = "".join(ch for ch in text if ch.isdigit())

    if kept == "00":
        return "100"

    if len(kept) >= 2 and kept[0] == "0":
        first_scores = glyph_scores[0] if glyph_scores else {}
        candidates = [
            (lbl, s)
            for lbl, s in first_scores.items()
            if lbl.isdigit() and lbl != "0" and s >= min_score
        ]
        if candidates:
            best = max(candidates, key=lambda x: x[1])[0]
            kept = best + kept[1:]

    if kept == "":
        return "UNKNOWN"
    return kept


def recognize_roi(
    roi: np.ndarray,
    cfg: dict[str, Any] | None = None,
    templates: dict[str, Any] | None = None,
) -> WeightReading:
    cfg = cfg if cfg is not None else _get_config()
    templates = templates if templates is not None else get_templates(cfg)
    mask = build_glyph_mask(roi, cfg["MASK"])
    bands = cfg["SEGMENT"]["bands"]
    glyphs = [g for g in segment_bands(mask, bands) if g is not None]

    if not glyphs:
        return WeightReading(raw="UNKNOWN", percent=None, confidence=0.0)

    digits = []
    glyph_scores = []
    conf = []
    min_score = cfg["MATCH"]["min_score"]
    conf_thr = cfg.get("CONFIDENCE_THRESHOLD", DEFAULT_MIN_CONFIDENCE)

    for glyph in glyphs:
        scores = _score_glyph(glyph, templates)
        best_label = max(scores, key=scores.get)
        best_score = scores[best_label]
        glyph_scores.append(scores)
        char = "%" if best_label == "percent" else best_label
        digits.append(char)
        if best_score >= conf_thr:
            conf.append(best_score)

    result = _resolve(digits, glyph_scores, min_score)
    confidence = min(conf) if conf else 0.0
    percent = int(result) if result.isdigit() else None
    return WeightReading(raw=result, percent=percent, confidence=float(confidence))


def recognize_frame(
    image_bgr: np.ndarray,
    *,
    config_path: Path | str | None = None,
) -> WeightReading:
    """Recognize HUD bag % from a captured BGR frame of any size."""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return WeightReading(raw="PREPROCESS_FAILED", percent=None, confidence=0.0)
    cfg = _get_config(config_path)
    templates = get_templates(cfg)
    roi = extract_numeric_roi(image_bgr, cfg)
    if roi is None:
        return WeightReading(raw="PREPROCESS_FAILED", percent=None, confidence=0.0)
    return recognize_roi(roi, cfg, templates)


def apply_weight_reading(
    game_state: "GameState",
    reading: WeightReading,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> bool:
    """Write HUD percent onto ``inventory.weight_ratio`` only if memory has none."""
    if reading.percent is None or reading.confidence < min_confidence:
        return False
    ratio = reading.ratio
    if ratio is None:
        return False
    player = game_state.player
    if player is None:
        return False
    if memory_weight_ready(player):
        return False
    player.inventory.weight_ratio = ratio
    return True


class WeightHud:
    """Cached templates + optional frame skip for the live bot loop."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        interval_frames: int = DEFAULT_INTERVAL_FRAMES,
        config_path: Path | str | None = None,
    ) -> None:
        self.enabled = enabled
        self.min_confidence = float(min_confidence)
        self.interval_frames = max(1, int(interval_frames))
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.last_reading: WeightReading | None = None
        self._tick = 0
        if self.enabled:
            cfg = _get_config(self.config_path)
            get_templates(cfg, config_path=self.config_path)

    def update(self, game_state: "GameState", frame: np.ndarray) -> WeightReading | None:
        if not self.enabled:
            return None
        if memory_weight_ready(getattr(game_state, "player", None)):
            return None
        self._tick += 1
        if (self._tick - 1) % self.interval_frames != 0:
            return self.last_reading
        reading = recognize_frame(frame, config_path=self.config_path)
        self.last_reading = reading
        apply_weight_reading(
            game_state, reading, min_confidence=self.min_confidence
        )
        return reading


def configure_weight_hud(config: Optional[dict[str, Any]] = None) -> WeightHud:
    """Build a ``WeightHud`` from ``vision.weight_hud`` (defaults: off)."""
    section = ((config or {}).get("vision") or {}).get("weight_hud") or {}
    raw_path = section.get("config_path")
    config_path = Path(raw_path) if raw_path else _DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = _PROJECT_ROOT / config_path
    return WeightHud(
        enabled=bool(section.get("enabled", False)),
        min_confidence=float(section.get("min_confidence", DEFAULT_MIN_CONFIDENCE)),
        interval_frames=int(section.get("interval_frames", DEFAULT_INTERVAL_FRAMES)),
        config_path=config_path,
    )


__all__ = [
    "WeightReading",
    "WeightHud",
    "recognize_frame",
    "recognize_roi",
    "apply_weight_reading",
    "configure_weight_hud",
    "extract_numeric_roi",
    "DEFAULT_MIN_CONFIDENCE",
]
