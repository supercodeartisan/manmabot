#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""리니지 클래식 아이콘 찾기.

다른 프로젝트에는 이 파일과 icons_unique/ 만 복사하면 된다.

    from icon_matcher import IconMatcher
    ui = IconMatcher()                 # 시작 시 1회
    hits = ui.match(그림)              # 경로 / PIL / OpenCV
    bar  = ui.hotbar_map(그림)         # {'F6': hit, 'F9': hit, ...}
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(_DIR, "icons_unique")

# 화면에서 볼 영역. 값은 (왼쪽, 오른쪽, 위, 아래) 비율.
REGION = {
    "full":         (0.0, 1.0, 0.0, 1.0),
    "right":        (0.5, 1.0, 0.0, 1.0),
    "bottom-right": (0.5, 1.0, 0.5, 1.0),
    "hotbar":       (0.77, 1.0, 0.78, 0.95),
}

# 핫바: 위 줄 F5~F8, 아래 줄 F9~F12
HOTBAR_ROWS, HOTBAR_COLS = 2, 4
HOTBAR_ONLY = (
    "items/주문서/",
    "items/활/화살",
    "items/활/은 화살",
    "items/물약/",
    "spells/",
)


# ---------------------------------------------------------------------------
# 결과 한 건
# ---------------------------------------------------------------------------

@dataclass
class IconHit:
    name: str
    kr_name: str
    zh_name: str
    x: int
    y: int
    w: int
    h: int
    score: float
    fkey: str | None = None
    row: int | None = None
    col: int | None = None

    @property
    def center(self):
        return (self.x + self.w / 2, self.y + self.h / 2)

    def __str__(self):
        key = f"{self.fkey} " if self.fkey else ""
        zh = f"/{self.zh_name}" if self.zh_name else ""
        return f"{key}{self.kr_name}{zh}  {self.score:.3f}  ({self.x},{self.y})"


# ---------------------------------------------------------------------------
# 그림 입력 → 항상 OpenCV BGR
# ---------------------------------------------------------------------------

def _read_png(path, with_alpha=False):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    flag = cv2.IMREAD_UNCHANGED if with_alpha else cv2.IMREAD_COLOR
    # libpng iCCP 경고가 콘솔을 가리지 않게 stderr만 잠시 닫는다
    stderr = os.dup(2)
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 2)
        return cv2.imdecode(data, flag)
    finally:
        os.dup2(stderr, 2)
        os.close(stderr)
        os.close(null)


def to_bgr(image, color="bgr"):
    """경로 / PIL.Image / numpy 행렬 → BGR uint8."""
    if isinstance(image, (str, os.PathLike)):
        img = _read_png(os.fspath(image))
        if img is None:
            raise FileNotFoundError(image)
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    # PIL
    if hasattr(image, "mode") and hasattr(image, "convert"):
        arr = np.array(image)
        if arr.ndim == 2:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        if arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    # numpy / OpenCV
    if isinstance(image, np.ndarray):
        arr = image
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        if arr.shape[2] == 4:
            code = cv2.COLOR_RGBA2BGR if color == "rgb" else cv2.COLOR_BGRA2BGR
            return cv2.cvtColor(arr, code)
        if color == "rgb":
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return np.ascontiguousarray(arr)

    raise TypeError(f"지원하지 않는 그림 타입: {type(image)}")


def _cut_transparent(bgra):
    """알파가 0인 테두리를 잘라낸다."""
    if bgra.ndim == 2:
        bgra = cv2.cvtColor(bgra, cv2.COLOR_GRAY2BGRA)
    elif bgra.shape[2] == 3:
        bgra = cv2.cvtColor(bgra, cv2.COLOR_BGR2BGRA)
    ys, xs = np.where(bgra[:, :, 3] > 0)
    if ys.size == 0:
        return None
    return bgra[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()


# ---------------------------------------------------------------------------
# 마스크 NCC — 투명 픽셀은 점수에서 빼 버린다
# ---------------------------------------------------------------------------

def _ncc(image_gray, tpl_gray, tpl_mask, tw, th):
    t = cv2.resize(tpl_gray, (tw, th), interpolation=cv2.INTER_AREA).astype(np.float32)
    m = cv2.resize(tpl_mask, (tw, th), interpolation=cv2.INTER_AREA)
    m = (m > 127).astype(np.float32)
    n = m.sum()
    if n < 10:
        return np.zeros((1, 1), np.float32)

    t = (t - (t * m).sum() / n) * m
    t_var = (t ** 2).sum()
    if t_var < 1e-6:
        return np.zeros((1, 1), np.float32)

    I = image_gray.astype(np.float32)
    H, W = I.shape
    sum_I = cv2.filter2D(I, -1, m, anchor=(0, 0))
    sum_I2 = cv2.filter2D(I ** 2, -1, m, anchor=(0, 0))
    var_I = sum_I2 - sum_I ** 2 / n
    num = cv2.filter2D(I, -1, t, anchor=(0, 0))
    den = np.sqrt(np.maximum(var_I, 0) * t_var)
    score = np.where(den > 1e-6, num / den, -1.0)
    score[H - th + 1:, :] = -1.0
    score[:, W - tw + 1:] = -1.0
    return score


def _best(image_gray, tpl, tw, th):
    """한 크기에서 최고 점수와 그 위치."""
    _min, score, _minloc, (x, y) = cv2.minMaxLoc(
        _ncc(image_gray, tpl["gray"], tpl["mask"], tw, th)
    )
    return score, x, y


def _best_color(image_bgr, tpl, tw, th):
    """Mean masked NCC over B/G/R; position from the strongest channel.

    Replaces gray-only NCC when color discrimination matters (shop sell icons).
    """
    best_xy = None
    best_ch = -1.0
    scores = []
    for c in range(3):
        ch = {"gray": tpl["bgr"][:, :, c], "mask": tpl["mask"]}
        score, x, y = _best(image_bgr[:, :, c], ch, tw, th)
        scores.append(float(score))
        if score > best_ch:
            best_ch = score
            best_xy = (x, y)
    if best_xy is None:
        return -1.0, 0, 0
    return float(np.mean(scores)), best_xy[0], best_xy[1]


def _overlap(a, b):
    x0 = max(a["x"], b["x"])
    y0 = max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"])
    y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# 공개 클래스
# ---------------------------------------------------------------------------

class IconMatcher:
    """아이콘 PNG를 한 번 읽고, 이후 그림마다 match()만 호출하면 된다."""

    def __init__(self, icon_root=None, threads=None, slot_layout=None, allow_empty=False):
        self.icon_root = icon_root or ICON_DIR
        self.threads = threads or max(1, (os.cpu_count() or 2) // 2)
        self.templates = self._load_icons(self.icon_root, allow_empty=allow_empty)
        self.hotbar_templates = [
            t for t in self.templates
            if any(t["name"].startswith(p) for p in HOTBAR_ONLY)
        ]
        self.zh = self._load_zh()
        # None → try load from userdata/debug; explicit {} disables calibrated slots.
        if slot_layout is None:
            from manmabot_v1.hotbar.slot_layout import load_slot_layout

            self.slot_layout = load_slot_layout()
        else:
            self.slot_layout = slot_layout or None

    def reload_slot_layout(self) -> bool:
        """Reload calibrated F5–F12 layout from disk. Returns True if loaded."""
        from manmabot_v1.hotbar.slot_layout import load_slot_layout

        self.slot_layout = load_slot_layout()
        return self.slot_layout is not None

    def __repr__(self):
        n_slots = len(self.slot_layout) if self.slot_layout else 0
        return f"IconMatcher({len(self.templates)} icons, slots={n_slots or 'default'})"

    def match(self, image, region="hotbar", color="bgr", threshold=0.65):
        """그림을 받아 아이콘 목록을 돌려준다.

        image  : 파일 경로, PIL.Image, OpenCV/numpy 행렬
        region : "hotbar" | "bottom-right" | "right" | "full"
        color  : 행렬이 RGB이면 "rgb", cv2 기본은 "bgr"
        """
        if region not in REGION:
            raise ValueError(f"region 은 {list(REGION)} 중 하나: {region!r}")
        screen = to_bgr(image, color=color)

        if region == "hotbar":
            raw = self._match_hotbar(screen, threshold)
            hits = []
            for d in raw:
                kr, zh = self._names(d["name"])
                hits.append(IconHit(
                    name=d["name"], kr_name=kr, zh_name=zh,
                    x=int(round(d["x"])),
                    y=int(round(d["y"])),
                    w=int(round(d["w"])),
                    h=int(round(d["h"])),
                    score=float(d["score"]),
                    fkey=d.get("fkey"),
                    row=d.get("row"),
                    col=d.get("col"),
                ))
            hits.sort(key=lambda h: (
                h.row if h.row is not None else 99,
                h.col if h.col is not None else 99,
            ))
            return hits

        crop, ox, oy = self._crop(screen, region)
        raw = self._find_anywhere(crop, threshold)
        hits = []
        for d in raw:
            kr, zh = self._names(d["name"])
            hits.append(IconHit(
                name=d["name"], kr_name=kr, zh_name=zh,
                x=int(round(d["x"] + ox)),
                y=int(round(d["y"] + oy)),
                w=int(round(d["w"])),
                h=int(round(d["h"])),
                score=float(d["score"]),
                fkey=d.get("fkey"),
                row=d.get("row"),
                col=d.get("col"),
            ))
        hits.sort(key=lambda h: (h.row if h.row is not None else 99,
                                 h.col if h.col is not None else 99))
        return hits

    def hotbar_map(self, image, **kw):
        """F키 → IconHit.  예: bar['F9'].kr_name"""
        return {h.fkey: h for h in self.match(image, region="hotbar", **kw) if h.fkey}

    def _match_hotbar(self, screen, threshold):
        """Match hotbar icons; use calibrated F5–F12 boxes when available."""
        from manmabot_v1.hotbar.slot_layout import (
            SLOT_KEYS,
            default_slot_layout,
            fkey_for_point,
        )

        H, W = screen.shape[:2]
        if self.slot_layout:
            return self._match_hotbar_calibrated(
                screen, self.slot_layout, threshold
            )

        crop, ox, oy = self._crop(screen, "hotbar")
        raw = self._find_hotbar(crop, threshold)
        slots = default_slot_layout(W, H)
        out = []
        for d in raw:
            abs_x = d["x"] + ox
            abs_y = d["y"] + oy
            cx = (abs_x + d["w"] / 2) / max(W, 1)
            cy = (abs_y + d["h"] / 2) / max(H, 1)
            # Prefer default-grid fkey from _find_hotbar; keep as fallback.
            fkey = d.get("fkey") or fkey_for_point(cx, cy, slots)
            row = col = None
            if fkey and fkey in SLOT_KEYS:
                idx = SLOT_KEYS.index(fkey)
                row, col = divmod(idx, 4)
            out.append({
                **d,
                "x": abs_x,
                "y": abs_y,
                "fkey": fkey,
                "row": row,
                "col": col,
            })
        return out

    def match_slot_boxes(
        self,
        image,
        slots: dict,
        slot_keys: tuple[str, ...] | list[str],
        *,
        threshold: float = 0.7,
        templates: list | None = None,
        color: str = "bgr",
        use_color: bool = True,
    ) -> list[IconHit]:
        """Best icon hit per calibrated box (same ROI search as hotbar calibrate).

        ``templates`` defaults to all loaded icons. Pass a filtered list for sell
        (e.g. items-only or garbage-only) to speed matching.

        ``use_color`` (default True): score with mean B/G/R masked NCC instead of
        gray-only — better for distinguishing similar item icons.
        """
        screen = to_bgr(image, color=color)
        pool = templates if templates is not None else self.templates
        raw = self._match_calibrated_boxes(
            screen, slots, slot_keys, threshold, pool, use_color=use_color
        )
        hits: list[IconHit] = []
        for d in raw:
            kr, zh = self._names(d["name"])
            hits.append(
                IconHit(
                    name=d["name"],
                    kr_name=kr,
                    zh_name=zh,
                    x=int(round(d["x"])),
                    y=int(round(d["y"])),
                    w=int(round(d["w"])),
                    h=int(round(d["h"])),
                    score=float(d["score"]),
                    fkey=d.get("fkey"),
                    row=d.get("row"),
                    col=d.get("col"),
                )
            )
        hits.sort(
            key=lambda h: (
                h.row if h.row is not None else 99,
                h.fkey or "",
            )
        )
        return hits

    def item_templates(
        self,
        *,
        names: set[str] | frozenset[str] | None = None,
    ) -> list:
        """Templates under ``items/``; optional KR-name allowlist (garbage_only)."""
        items = [
            t
            for t in self.templates
            if str(t.get("name") or "").startswith("items/")
        ]
        if names is None:
            return items
        want = {str(n).strip() for n in names if str(n).strip()}
        if not want:
            return []
        out = []
        for tpl in items:
            kr, _zh = self._names(tpl["name"])
            if kr in want:
                out.append(tpl)
        return out

    def _match_calibrated_boxes(
        self, screen, slots, slot_keys, threshold, pool, *, use_color: bool = False
    ):
        """Search each calibrated ROI; ``fkey`` is the slot key."""
        H, W = screen.shape[:2]
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        out = []
        keys = tuple(slot_keys)

        for key in keys:
            box = slots.get(key)
            if not box:
                continue
            x0 = max(0, int(round(box["x0"] * W)))
            x1 = min(W, int(round(box["x1"] * W)))
            y0 = max(0, int(round(box["y0"] * H)))
            y1 = min(H, int(round(box["y1"] * H)))
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            roi_gray = gray[y0:y1, x0:x1]
            roi_bgr = screen[y0:y1, x0:x1]
            rh, rw = roi_gray.shape
            slot_size = float(min(rh, rw))
            best = None

            def one(tpl, _slot_size=slot_size, _rw=rw, _rh=rh):
                # Scale template to current slot size so one pack works across resolutions.
                scale = (0.85 * _slot_size) / max(1.0, (tpl["w"] + tpl["h"]) / 2)
                local = None
                for s in (scale * 0.95, scale, scale * 1.05):
                    tw = max(3, int(round(tpl["w"] * s)))
                    th = max(3, int(round(tpl["h"] * s)))
                    if tw > _rw or th > _rh:
                        continue
                    if use_color:
                        score, x, y = _best_color(roi_bgr, tpl, tw, th)
                    else:
                        score, x, y = _best(roi_gray, tpl, tw, th)
                    if score < threshold:
                        continue
                    mask = cv2.resize(
                        tpl["mask"], (tw, th), interpolation=cv2.INTER_AREA
                    )
                    if (mask > 127).sum() / (tw * th) < 0.2:
                        continue
                    if local is None or score > local["score"]:
                        local = {
                            "name": tpl["name"],
                            "x": x,
                            "y": y,
                            "w": tw,
                            "h": th,
                            "score": score,
                        }
                return local

            with ThreadPoolExecutor(max_workers=min(self.threads, 8)) as pool_ex:
                for hit in pool_ex.map(one, pool):
                    if hit is None:
                        continue
                    if best is None or hit["score"] > best["score"]:
                        best = hit

            if best is None:
                continue
            try:
                row = keys.index(key)
            except ValueError:
                row = None
            out.append(
                {
                    "name": best["name"],
                    "x": best["x"] + x0,
                    "y": best["y"] + y0,
                    "w": best["w"],
                    "h": best["h"],
                    "score": best["score"],
                    "fkey": key,
                    "row": row,
                    "col": 0,
                }
            )
        return out

    def _match_hotbar_calibrated(self, screen, slots, threshold):
        """Search each calibrated F-key ROI separately (absolute frame coords)."""
        from manmabot_v1.hotbar.slot_layout import SLOT_KEYS

        raw = self._match_calibrated_boxes(
            screen,
            slots,
            SLOT_KEYS,
            threshold,
            self.hotbar_templates,
            use_color=False,
        )
        for d in raw:
            key = d.get("fkey")
            if key in SLOT_KEYS:
                idx = SLOT_KEYS.index(key)
                d["row"], d["col"] = divmod(idx, 4)
        return raw

    # ----- 템플릿 / 이름 -----------------------------------------------------

    def _load_icons(self, root, allow_empty=False):
        if not os.path.isdir(root):
            raise FileNotFoundError(root)
        out = []
        for folder, _, files in os.walk(root):
            for fn in sorted(files):
                if not fn.lower().endswith(".png"):
                    continue
                path = os.path.join(folder, fn)
                name = os.path.relpath(path, root).replace(os.sep, "/")
                bgra = _read_png(path, with_alpha=True)
                if bgra is None:
                    continue
                sprite = _cut_transparent(bgra)
                if sprite is None:
                    continue
                gray = cv2.cvtColor(sprite[:, :, :3], cv2.COLOR_BGR2GRAY)
                mask = (sprite[:, :, 3] > 0).astype(np.uint8) * 255
                out.append({
                    "name": name,
                    "bgr": sprite[:, :, :3],
                    "gray": gray,
                    "mask": mask,
                    "w": gray.shape[1],
                    "h": gray.shape[0],
                })
        if not out and not allow_empty:
            raise RuntimeError(f"아이콘 PNG가 없습니다: {root}")
        return out

    def _load_zh(self):
        """파일 경로·한국어 이름 → 중국어."""
        zh = {}
        for path in (
            os.path.join(_DIR, "icons_unique", "zh_names.json"),
            os.path.join(_DIR, "hotbar_icons_zh.json"),
        ):
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            zh.update(data.get("icons") or {})
            zh.update(data.get("itemNameToZh") or {})
            zh.update(data.get("spellNameToZh") or {})
            zh.update(data.get("spells") or {})
            for cat in (data.get("items") or {}).values():
                if isinstance(cat, dict):
                    zh.update(cat)
        return zh

    def _names(self, template_name):
        kr = os.path.splitext(template_name.split("/")[-1])[0]
        zh = self.zh.get(template_name) or self.zh.get(kr, "")
        if "spells" in template_name:
            for k, v in self.zh.items():
                if k.replace(":", "") == kr.replace(":", ""):
                    kr, zh = k, zh or v
                    break
        return kr, zh or ""

    # ----- 영역 --------------------------------------------------------------

    @staticmethod
    def _crop(img, region):
        H, W = img.shape[:2]
        x0, x1, y0, y1 = REGION[region]
        x0, x1 = int(round(x0 * W)), int(round(x1 * W))
        y0, y1 = int(round(y0 * H)), int(round(y1 * H))
        return img[y0:y1, x0:x1], x0, y0

    # ----- 핫바 --------------------------------------------------------------

    def _find_hotbar(self, crop, threshold):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape
        found = []

        def one(tpl):
            # 핫바 칸 안 아이콘은 대략 33px
            scale = 33.0 / max(1.0, (tpl["w"] + tpl["h"]) / 2)
            best = None
            for s in (scale * 0.9, scale, scale * 1.1):
                tw, th = max(3, int(round(tpl["w"] * s))), max(3, int(round(tpl["h"] * s)))
                if tw > W or th > H:
                    continue
                score, x, y = _best(gray, tpl, tw, th)
                if score < threshold:
                    continue
                mask = cv2.resize(tpl["mask"], (tw, th), interpolation=cv2.INTER_AREA)
                if (mask > 127).sum() / (tw * th) < 0.2:
                    continue
                if best is None or score > best["score"]:
                    best = {"name": tpl["name"], "x": x, "y": y, "w": tw, "h": th, "score": score}
            return best

        with ThreadPoolExecutor(max_workers=min(self.threads, 8)) as pool:
            for hit in pool.map(one, self.hotbar_templates):
                if hit:
                    found.append(hit)

        # 겹치면 점수 높은 것만
        found.sort(key=lambda d: d["score"], reverse=True)
        kept = []
        for d in found:
            if any(_overlap(d, k) > 0.45 for k in kept):
                continue
            kept.append(d)

        # 칸 위치로 F키
        cell_w = crop.shape[1] / HOTBAR_COLS
        cell_h = crop.shape[0] / HOTBAR_ROWS
        by_key = {}
        for d in kept:
            r = min(HOTBAR_ROWS - 1, int((d["y"] + d["h"] / 2) / cell_h))
            c = min(HOTBAR_COLS - 1, int((d["x"] + d["w"] / 2) / cell_w))
            d["row"], d["col"] = r, c
            d["fkey"] = f"F{5 + r * HOTBAR_COLS + c}"
            if d["fkey"] not in by_key or d["score"] > by_key[d["fkey"]]["score"]:
                by_key[d["fkey"]] = d
        return list(by_key.values())

    # ----- 화면 전체 (축소 탐색 → 원본에서 보정) ----------------------------

    def _find_anywhere(self, img, threshold):
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        work_h = 180
        sizes = [12 * (1.35 ** i) for i in range(8)]
        coarse = []

        for aspect in (0.85, 0.95, 1.0, 1.1, 1.2):
            ww = max(4, int(round(W * work_h / H * aspect)))
            small = cv2.cvtColor(
                cv2.resize(img, (ww, work_h), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            )
            sh, sw = small.shape
            jobs = []
            for size in sizes:
                th = int(round(size))
                for tpl in self.templates:
                    tw = max(3, int(round(tpl["w"] * th / max(tpl["h"], 1))))
                    if tw > sw - 2 or th > sh - 2:
                        continue
                    jobs.append((tpl, tw, th))

            def coarse_one(job):
                tpl, tw, th = job
                score, x, y = _best(small, tpl, tw, th)
                return score, x, y, tw, th, tpl

            with ThreadPoolExecutor(max_workers=self.threads) as pool:
                for score, x, y, tw, th, tpl in pool.map(coarse_one, jobs):
                    if score >= 0.55:
                        coarse.append((score, tpl,
                                       x * W / ww, y * H / work_h,
                                       tw * W / ww, th * H / work_h))

        coarse.sort(key=lambda t: t[0], reverse=True)
        seen = set()
        out = []
        for _s, tpl, x, y, w, h in coarse[:2000]:
            d = self._refine(tpl, gray, img, x, y, w, h, threshold)
            if not d:
                continue
            key = (d["name"], round(d["x"]), round(d["y"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(d)

        out.sort(key=lambda d: d["score"], reverse=True)
        kept = []
        for d in out:
            if any(k["name"] == d["name"] and _overlap(d, k) > 0.45 for k in kept):
                continue
            kept.append(d)
        return kept

    def _refine(self, tpl, gray, bgr, x, y, w, h, threshold):
        """후보 주변을 원본 해상도에서 다시 맞춘다."""
        H, W = gray.shape
        x0, y0 = max(0, int(x - 8)), max(0, int(y - 8))
        x1, y1 = min(W, int(x + w + 8)), min(H, int(y + h + 8))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        patch = gray[y0:y1, x0:x1]
        ph, pw = patch.shape
        best = None
        for s in (0.9, 0.95, 1.0, 1.05, 1.1):
            tw, th = max(3, int(round(w * s))), max(3, int(round(h * s)))
            if tw > pw - 2 or th > ph - 2:
                continue
            score, lx, ly = _best(patch, tpl, tw, th)
            if best is None or score > best[0]:
                best = (score, lx, ly, tw, th)
        if best is None or best[0] < threshold:
            return None
        score, lx, ly, tw, th = best

        # 색 채널 평균으로 흑백 오탐을 줄인다
        color = bgr[y0:y1, x0:x1]
        color_scores = []
        for c in range(3):
            ch = {"gray": tpl["bgr"][:, :, c], "mask": tpl["mask"]}
            cs, _, _ = _best(color[:, :, c], ch, tw, th)
            color_scores.append(cs)
        return {
            "name": tpl["name"],
            "x": x0 + lx, "y": y0 + ly, "w": tw, "h": th,
            "score": float(np.mean(color_scores)),
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용: python icon_matcher.py <화면.png> [hotbar|full|right|bottom-right]")
        sys.exit(1)
    region = sys.argv[2] if len(sys.argv) > 2 else "hotbar"
    for hit in IconMatcher().match(sys.argv[1], region=region):
        print(hit)
