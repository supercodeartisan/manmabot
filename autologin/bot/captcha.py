"""Game/launcher CAPTCHA solver (ONNX model, ported from the legacy project)."""
import logging
from typing import Tuple

import numpy as np
from PIL import Image

log = logging.getLogger("captcha")

try:
    import onnxruntime as ort
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False


class CaptchaSolver:
    def __init__(self, model_path: str):
        self.session = None
        self.charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.input_name = None
        self.output_name = None
        if not HAS_ONNX:
            log.error("onnxruntime not installed, CAPTCHA solving unavailable")
            return
        try:
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.inter_op_num_threads = 2
            opts.intra_op_num_threads = 4
            self.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
            self.input_name = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name
            log.info(f"CAPTCHA model loaded: input={self.session.get_inputs()[0].shape} "
                     f"output={self.session.get_outputs()[0].shape}")
        except Exception as e:
            log.error(f"Failed to load CAPTCHA model: {e}")

    @property
    def available(self) -> bool:
        return self.session is not None

    def preprocess(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGB").resize((180, 60), Image.Resampling.LANCZOS)
        arr = np.array(img, dtype=np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr.transpose(2, 0, 1)
        return arr[np.newaxis, ...]

    def solve_with_confidence(self, img: Image.Image) -> Tuple[str, float]:
        if not self.available:
            return "", 0.0
        assert self.session is not None
        blob = self.preprocess(img)
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        logits = outputs[0]
        if logits.ndim != 3:
            return "", 0.0
        chars = []
        confs = []
        for pos in range(logits.shape[1]):
            row = logits[0, pos]
            idx = int(np.argmax(row))
            confs.append(float(np.max(row)))
            if idx < len(self.charset):
                chars.append(self.charset[idx])
        confidence = float(np.mean(confs)) if confs else 0.0
        return "".join(chars), confidence


def detect_captcha_region(img: Image.Image):
    """Return (x, y, w, h) of a compact framed noisy strip (CAPTCHA), or None."""
    arr = np.array(img)
    hgt, wdt = arr.shape[:2]
    gray = np.mean(arr, axis=2)
    best = None
    for rw_ratio in [0.3, 0.25, 0.2]:
        rw = int(wdt * rw_ratio)
        for rh_ratio in [0.11, 0.13, 0.16]:
            rh = int(hgt * rh_ratio)
            if not (1.5 < rw / rh < 4.0):
                continue
            for y_ratio in [0.3, 0.4, 0.5, 0.6, 0.7]:
                for x_ratio in [0.2, 0.3, 0.4, 0.5]:
                    x_start = int(wdt * x_ratio)
                    y_start = int(hgt * y_ratio)
                    if x_start + rw > wdt or y_start + rh > hgt:
                        continue
                    region = arr[y_start:y_start + rh, x_start:x_start + rw]
                    if region.size == 0:
                        continue
                    std = np.std(region)
                    edges = np.std(np.diff(region.astype(float), axis=0))
                    if not (std > 40 and edges > 15):
                        continue
                    g = gray[y_start:y_start + rh, x_start:x_start + rw]
                    top_edges = np.sum(np.abs(np.diff(g[0:3], axis=0)) > 40)
                    bottom_edges = np.sum(np.abs(np.diff(g[-3:], axis=0)) > 40)
                    left_edges = np.sum(np.abs(np.diff(g[:, 0:3], axis=1)) > 40)
                    right_edges = np.sum(np.abs(np.diff(g[:, -3:], axis=1)) > 40)
                    min_side = min(top_edges, bottom_edges, left_edges, right_edges)
                    if min_side < 3:
                        continue
                    mid = g[rh // 3:2 * rh // 3, rw // 3:2 * rw // 3]
                    mid_edges = float(np.mean(np.abs(np.diff(mid, axis=1)) > 40))
                    if mid_edges < 0.02:
                        continue
                    score = std + edges + min_side * 20 + mid_edges * 100
                    if best is None or score > best[0]:
                        best = (score, x_start, y_start, rw, rh)
    if best is not None:
        return best[1], best[2], best[3], best[4]
    return None
