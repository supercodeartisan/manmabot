"""Match a live cursor BGRA crop against ``cursors/*.png`` templates."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from app._05_action.cursor_catalog import (
    CURSOR_LABEL_CATEGORY,
    CursorCategory,
)

# Default repo-root relative folder.
DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "cursors"


@dataclass(frozen=True)
class CursorMatch:
    label: str
    category: CursorCategory
    score: float
    handle: int = 0


@dataclass
class _Template:
    label: str
    category: CursorCategory
    bgra: np.ndarray


def _image_score(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity on 32×32 alpha-weighted BGRA."""

    def prep(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        side = max(h, w, 1)
        canvas = np.zeros((side, side, 4), dtype=np.uint8)
        y0 = (side - h) // 2
        x0 = (side - w) // 2
        canvas[y0 : y0 + h, x0 : x0 + w] = img
        return cv2.resize(canvas, (32, 32), interpolation=cv2.INTER_AREA).astype(
            np.float32
        )

    fa, fb = prep(a), prep(b)
    wa = fa[:, :, 3:4] / 255.0
    wb = fb[:, :, 3:4] / 255.0
    va = np.concatenate([fa[:, :, :3] * wa, wa], axis=2).reshape(-1)
    vb = np.concatenate([fb[:, :, :3] * wb, wb], axis=2).reshape(-1)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.dot(va / na, vb / nb))


class CursorMatcher:
    """Template matcher over the on-disk cursor catalog."""

    def __init__(
        self,
        templates_dir: Path | str | None = None,
        *,
        min_score: float = 0.72,
    ) -> None:
        self.templates_dir = Path(templates_dir or DEFAULT_TEMPLATES_DIR)
        self.min_score = float(min_score)
        self._templates: list[_Template] = []
        self.reload()

    @property
    def loaded(self) -> bool:
        return bool(self._templates)

    def reload(self) -> int:
        self._templates.clear()
        if not self.templates_dir.is_dir():
            return 0
        for path in sorted(self.templates_dir.glob("*.png")):
            label = path.stem.lower()
            if label not in CURSOR_LABEL_CATEGORY:
                continue
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            if img.ndim == 2:
                bgra = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
            elif img.shape[2] == 3:
                bgr = img
                alpha = np.full(bgr.shape[:2], 255, dtype=np.uint8)
                bgra = np.dstack([bgr, alpha])
            else:
                bgra = img
            self._templates.append(
                _Template(
                    label=label,
                    category=CURSOR_LABEL_CATEGORY[label],
                    bgra=bgra,
                )
            )
        return len(self._templates)

    def match(
        self,
        bgra: np.ndarray | None,
        *,
        handle: int = 0,
        min_score: float | None = None,
    ) -> CursorMatch | None:
        if bgra is None or not self._templates:
            return None
        thr = self.min_score if min_score is None else float(min_score)
        best: CursorMatch | None = None
        for tmpl in self._templates:
            score = _image_score(bgra, tmpl.bgra)
            if best is None or score > best.score:
                best = CursorMatch(
                    label=tmpl.label,
                    category=tmpl.category,
                    score=score,
                    handle=handle,
                )
        if best is None or best.score < thr:
            return None
        return best

    def match_labels(
        self,
        bgra: np.ndarray | None,
        labels: Iterable[str],
        *,
        handle: int = 0,
        min_score: float | None = None,
    ) -> CursorMatch | None:
        """Score only ``labels`` (used for the fast attack-cursor hunt)."""
        if bgra is None or not self._templates:
            return None
        wanted = {str(label).strip().lower() for label in labels if str(label).strip()}
        if not wanted:
            return self.match(bgra, handle=handle, min_score=min_score)
        thr = self.min_score if min_score is None else float(min_score)
        best: CursorMatch | None = None
        for tmpl in self._templates:
            if tmpl.label not in wanted:
                continue
            score = _image_score(bgra, tmpl.bgra)
            if best is None or score > best.score:
                best = CursorMatch(
                    label=tmpl.label,
                    category=tmpl.category,
                    score=score,
                    handle=handle,
                )
        if best is None or best.score < thr:
            return None
        return best

    def match_allows(
        self,
        bgra: np.ndarray | None,
        *,
        categories: Iterable[CursorCategory] | None = None,
        labels: Iterable[str] | None = None,
        handle: int = 0,
        min_score: float | None = None,
    ) -> tuple[bool, CursorMatch | None]:
        """Return (ok, match). Match may be set even when ok is False."""
        # Always score; then apply allow-lists (use a soft floor for reporting).
        floor = 0.0 if min_score is None else min(0.0, float(min_score))
        # Match with low threshold so we can report wrong-category rejections.
        m = self.match(bgra, handle=handle, min_score=0.0)
        if m is None:
            return False, None
        thr = self.min_score if min_score is None else float(min_score)
        if m.score < thr:
            return False, m
        label_ok = True
        cat_ok = True
        if labels is not None:
            label_ok = m.label in set(labels)
        if categories is not None:
            cat_ok = m.category in set(categories)
        del floor
        return (label_ok and cat_ok), m


# Module-level singleton configured by configure_action / ActionExecutor.
_matcher: CursorMatcher | None = None


def get_cursor_matcher() -> CursorMatcher:
    global _matcher
    if _matcher is None:
        _matcher = CursorMatcher()
    return _matcher


def configure_cursor_matcher(
    *,
    templates_dir: Path | str | None = None,
    min_score: float | None = None,
) -> CursorMatcher:
    global _matcher
    m = get_cursor_matcher()
    if templates_dir is not None:
        m.templates_dir = Path(templates_dir)
        m.reload()
    if min_score is not None:
        m.min_score = float(min_score)
    _matcher = m
    return m


__all__ = [
    "CursorMatch",
    "CursorMatcher",
    "DEFAULT_TEMPLATES_DIR",
    "get_cursor_matcher",
    "configure_cursor_matcher",
]
