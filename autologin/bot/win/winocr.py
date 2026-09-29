"""OCR via Windows.Media.Ocr (built-in, ko model) on a window-captured image.

All coordinates returned are in the *image* pixel space, which equals the
window client area (Option D: window-targeted, not full screen).
"""
import asyncio
import ctypes
import io
import logging
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image
log = logging.getLogger("winocr")


def normalize(text: str) -> str:
    """Strip spaces and punctuation so '동의 하십 니다' matches '동의합니다'."""
    return "".join(ch for ch in text if not ch.isspace()).lower()


def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


# Common OCR substitutions for Purple zh-CN labels.
_OCR_VARIANTS = {
    "邮": ("郵", "由"),
    "户": ("戶",),
    "运": ("運",),
    "戏": ("戲",),
    "电": ("電",),
    "子": ("孑",),
    "名": ("各",),
    "用": ("甩",),
    "游": ("遊",),
}

USERNAME_EMAIL_KEYWORDS = (
    "用户名/电子邮箱", "用户名", "电子邮箱",
    "idoreemail", "idoremail", "idemail", "emailaddress",
    "id/e-mailaddress", "id/e-mail", "idoremailaddress",
)

RUN_GAME_KEYWORDS = (
    "运行游戏", "運行遊戲", "运行游", "startgame",
)

LINEAGE_CARD_KEYWORDS = (
    "Lineage Classic", "Lineage classic", "Lineage",
    "天堂经典", "天堂經典", "리니지 클래식", "经典", "經典",
)


def label_normalize(text: str) -> str:
    """Normalize UI labels: drop spaces and common separators."""
    t = normalize(text)
    for ch in "/|·:：;；-_":
        t = t.replace(ch, "")
    return t


def _expand_variants(text: str) -> set:
    out = {text}
    for src, alts in _OCR_VARIANTS.items():
        extra = set()
        for s in list(out):
            if src in s:
                for alt in alts:
                    extra.add(s.replace(src, alt))
            for alt in alts:
                if alt in s:
                    extra.add(s.replace(alt, src))
        out |= extra
    return out


def fuzzy_match_label(text: str, needles, fuzzy: float = 0.68) -> Optional[str]:
    """Return the first matching needle for OCR text, or None."""
    raw = label_normalize(text)
    if not raw:
        return None
    norm_needles = [label_normalize(n) for n in needles if label_normalize(n)]
    for needle in norm_needles:
        for variant in _expand_variants(needle):
            if variant in raw or raw in variant:
                return needle
            if len(variant) >= 3 and _ratio(variant, raw) >= fuzzy:
                return needle
            if len(variant) >= 4 and len(raw) >= len(variant):
                L = len(variant)
                for i in range(0, len(raw) - L + 1):
                    if _ratio(variant, raw[i:i + L]) >= fuzzy:
                        return needle
    # Component match for combined zh label: 用户名 + 邮*
    if any(label_normalize(k) in ("用户名", "用户名电子邮箱") for k in needles):
        if "用户名" in raw and any(x in raw for x in ("邮", "郵", "email", "e-mail")):
            return "用户名/电子邮箱"
        if "用户名" in raw and len(raw) <= 8:
            return "用户名"
    if any(label_normalize(k) == "运行游戏" for k in needles):
        if "运行" in raw and ("游戏" in raw or "游" in raw):
            return "运行游戏"
        if len(raw) >= 3 and _ratio("运行游戏", raw) >= fuzzy - 0.05:
            return "运行游戏"
    if any("lineage" in label_normalize(k) or "经典" in label_normalize(k)
           or "經典" in label_normalize(k) for k in needles):
        raw_low = label_normalize(line_text)
        if "lineage" in raw_low and "classic" in raw_low:
            return "Lineage Classic"
        if "天堂" in raw and ("经典" in raw or "經典" in raw):
            return "天堂经典"
        if "经典" in raw or "經典" in raw:
            if "lineage" in raw_low or "天堂" in raw or "리니지" in raw:
                return "Lineage Classic"
    return None


def _line_matches_query(query: str, line_text: str, exact: bool,
                        fuzzy: float) -> bool:
    ql = label_normalize(query)
    t = label_normalize(line_text)
    if not ql or not t:
        return False
    if exact:
        return t == ql
    if ql in t or t in ql:
        return True
    if fuzzy_match_label(line_text, [query], fuzzy=fuzzy):
        return True
    if fuzzy > 0:
        if _ratio(ql, t) >= fuzzy:
            return True
        if len(ql) >= 4 and len(t) >= len(ql):
            L = len(ql)
            for i in range(0, len(t) - L + 1):
                if _ratio(ql, t[i:i + L]) >= fuzzy:
                    return True
    return False


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


@dataclass
class OcrWord:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass
class OcrLine:
    words: List[OcrWord] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x(self) -> int:
        return min(w.x for w in self.words) if self.words else 0

    @property
    def y(self) -> int:
        return min(w.y for w in self.words) if self.words else 0

    @property
    def w(self) -> int:
        if not self.words:
            return 0
        return max(w.x + w.w for w in self.words) - self.x

    @property
    def h(self) -> int:
        if not self.words:
            return 0
        return max(w.y + w.h for w in self.words) - self.y

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


class WinOcr:
    """Thin wrapper around Windows.Media.Ocr operating on PIL images.

    OCR runs on a dedicated worker thread with its own asyncio loop. That
    keeps Windows.Media.Ocr working even after the main thread's COM
    apartment has been changed by other libraries (comtypes/uiautomation
    CoInitialize the main thread, which otherwise makes the WinRT async
    OCR await hang forever).
    """

    def __init__(self, lang: str = "ko", cache_dir: str | None = None):
        self.lang = lang
        self.cache_dir = cache_dir or tempfile.gettempdir()
        self._engine = None
        self._req_q: queue.Queue[bytes] = queue.Queue()
        self._res_q: queue.Queue[tuple[list[OcrLine] | None, Exception | None]] = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        engine = None
        try:
            engine = OcrEngine.try_create_from_language(Language(self.lang))
        except Exception as e:
            log.warning(f"try_create_from_language({self.lang}) failed: {e}")
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        self._engine = engine
        return engine

    @staticmethod
    def _image_to_bytes(img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            item = self._req_q.get()
            if item is None:
                break
            data = item
            try:
                result = loop.run_until_complete(self._run_bytes(data))
            except Exception as e:
                self._res_q.put((None, e))
                continue
            self._res_q.put((result, None))

    def recognize(self, img: Image.Image) -> List[OcrLine]:
        """Run OCR on a PIL image; returns lines of words in image coords."""
        data = self._image_to_bytes(img)
        with self._lock:
            self._req_q.put(data)
            result, err = self._res_q.get()
        if err is not None:
            log.error(f"OCR recognize failed: {err}")
            return []
        return result or []

    async def _run_bytes(self, data: bytes) -> List[OcrLine]:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import InMemoryRandomAccessStream

        stream = InMemoryRandomAccessStream()
        writer = await _write_all(stream, data)
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await self._get_engine().recognize_async(bitmap)

        lines = []
        for line in result.lines:
            words = []
            for w in line.words:
                r = w.bounding_rect
                words.append(OcrWord(
                    text=w.text,
                    x=int(round(r.x)), y=int(round(r.y)),
                    w=int(round(r.width)), h=int(round(r.height)),
                ))
            if words:
                lines.append(OcrLine(words=words))
        return lines

    def find(self, img: Image.Image, words: List[str],
             exact: bool = False) -> List[Tuple[str, OcrWord]]:
        """Return (query_word, OcrWord) matches in the image.
        exact=False does substring containment (case-insensitive)."""
        lines = self.recognize(img)
        hits = []
        for qw in words:
            ql = normalize(qw)
            for line in lines:
                for w in line.words:
                    t = normalize(w.text)
                    if exact:
                        ok = t == ql
                    else:
                        ok = ql in t
                    if ok:
                        hits.append((qw, w))
        return hits

    def find_lines(self, img: Image.Image, words: List[str],
                   exact: bool = False, fuzzy: float = 0.0) -> List[Tuple[str, OcrLine]]:
        """Return (query_word, OcrLine) matches (line-level, space-insensitive).
        More robust for Korean: Windows OCR splits '동의합니다' into
        '동의 하십 니다' as separate words, so match whole lines instead.
        fuzzy: min SequenceMatcher ratio (0..1) to also accept near-matches
        (e.g. OCR reading '린델' as '린덴')."""
        lines = self.recognize(img)
        hits = []
        for qw in words:
            for line in lines:
                if _line_matches_query(qw, line.text, exact, fuzzy):
                    hits.append((qw, line))
        return hits


class RapidOcr:
    """PaddleOCR/ONNX-based OCR with much better Korean recognition than
    Windows.Media.Ocr for game-rendered text. Produces the same OcrLine/OcrWord
    output so it's a drop-in replacement for WinOcr.recognize / find_lines."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
            self._np = np
        except Exception as e:
            log.warning("RapidOCR unavailable: %s", e)
            self._engine = None
        return self._engine

    def recognize(self, img: Image.Image) -> List[OcrLine]:
        """Run RapidOCR on a PIL image; returns lines of words in image coords."""
        engine = self._get_engine()
        if engine is None:
            return []
        np = self._np
        import cv2
        arr = np.array(img)
        result, _ = engine(arr)
        if not result:
            return []
        lines = []
        for box, text, conf in result:
            # box is [[x0,y0],[x1,y1],[x2,y2],[x3,y3]] (quadrilateral)
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x0, y0 = int(min(xs)), int(min(ys))
            w = int(max(xs)) - x0
            h = int(max(ys)) - y0
            lines.append(OcrLine(words=[OcrWord(text=text, x=x0, y=y0, w=w, h=h)]))
        return lines

    def find(self, img: Image.Image, words: List[str],
             exact: bool = False) -> List[tuple]:
        """Same interface as WinOcr.find: (query_word, OcrWord)."""
        hits = []
        for qw, line in self.find_lines(img, words, exact=exact):
            if line.words:
                hits.append((qw, line.words[0]))
        return hits

    def find_lines(self, img: Image.Image, words: List[str],
                   exact: bool = False, fuzzy: float = 0.0) -> List[Tuple[str, OcrLine]]:
        """Same interface as WinOcr.find_lines."""
        lines = self.recognize(img)
        hits = []
        for qw in words:
            for line in lines:
                if _line_matches_query(qw, line.text, exact, fuzzy):
                    hits.append((qw, line))
        return hits


async def _write_all(stream, data: bytes):
    from winrt.windows.storage.streams import DataWriter
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    writer.detach_stream()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "ko"
    img = Image.open(path).convert("RGB")
    ocr = WinOcr(lang)
    t0 = time.time()
    lines = ocr.recognize(img)
    print(f"{len(lines)} lines in {time.time()-t0:.1f}s")
    for ln in lines:
        print(f"  [{ln.x},{ln.y},{ln.w},{ln.h}] {ln.text}")
