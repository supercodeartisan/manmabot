"""YOLOv8n-based person detector using ONNX Runtime.

Detects human-like figures (COCO class 0) in images. Used for
character selection in Lineage Classic where characters look like
cartoon-style humans arranged left-to-right.
"""
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

log = logging.getLogger(__name__)

# Model path can be overridden via environment variable
MODEL_PATH = os.environ.get("YOLO_MODEL") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "yolov8n.onnx"
)
PERSON_CLASS = 0  # COCO class 0 = person
INPUT_SIZE = 640


@dataclass
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float
    cx: int  # center x
    cy: int  # center y

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def height(self):
        return self.y2 - self.y1


class PersonDetector:
    """Lightweight person detector using YOLOv8n ONNX + onnxruntime."""

    def __init__(self, model_path: str = MODEL_PATH, conf_threshold: float = 0.25):
        self.conf_threshold = conf_threshold
        self._session: "ort.InferenceSession | None" = None
        self._input_name: str | None = None
        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"]
            )
            self._input_name = self._session.get_inputs()[0].name
            log.info("PersonDetector loaded: %s", model_path)
        except Exception as e:
            log.warning("PersonDetector unavailable: %s", e)

    @property
    def available(self) -> bool:
        return self._session is not None

    def _letterbox(self, img: np.ndarray, new_shape: int = INPUT_SIZE):
        """Resize image with letterbox padding to model input size."""
        h, w = img.shape[:2]
        r = min(new_shape / h, new_shape / w)
        new_unpad = (int(round(w * r)), int(round(h * r)))
        dw = (new_shape - new_unpad[0]) / 2
        dh = (new_shape - new_unpad[1]) / 2

        if (w, h) != new_unpad:
            img = np.ascontiguousarray(
                img if img.shape[:2] == new_unpad else
                __import__("cv2").resize(img, new_unpad, interpolation=__import__("cv2").INTER_LINEAR)
            )

        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = __import__("cv2").copyMakeBorder(img, top, bottom, left, right,
                                               __import__("cv2").BORDER_CONSTANT,
                                               value=(114, 114, 114))
        return img, r, (dw, dh)

    def detect(self, img_rgb: np.ndarray,
               region: Optional[tuple] = None) -> List[Detection]:
        """Detect persons in an RGB image.

        Args:
            img_rgb: HxWx3 uint8 RGB image.
            region: Optional (x, y, w, h) to restrict detection area
                    (in original image coords). Only detections whose
                    center falls inside region are kept.

        Returns:
            List of Detection objects sorted by x-coordinate (left to right).
        """
        if not self.available:
            return []

        import cv2

        assert self._session is not None
        assert self._input_name is not None

        src_h, src_w = img_rgb.shape[:2]
        # Letterbox resize
        img, ratio, (dw, dh) = self._letterbox(img_rgb)
        # HWC -> CHW, float32, 0-1
        blob = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = np.expand_dims(blob, axis=0)

        # Inference
        outputs = self._session.run(None, {self._input_name: blob})[0]
        # outputs shape: (1, 84, 8400) -> transpose to (8400, 84)
        outputs = outputs[0].T  # (8400, 84)

        # Extract boxes and scores
        boxes = outputs[:, :4]   # cx, cy, w, h
        scores = outputs[:, 4:]  # 80 class scores

        # Person class scores
        person_scores = scores[:, PERSON_CLASS]
        mask = person_scores > self.conf_threshold
        if not mask.any():
            return []

        boxes = boxes[mask]
        person_scores = person_scores[mask]

        # Convert from center format to xyxy, mapping back to original coords
        x1 = (boxes[:, 0] - boxes[:, 2] / 2 - dw) / ratio
        y1 = (boxes[:, 1] - boxes[:, 3] / 2 - dh) / ratio
        x2 = (boxes[:, 0] + boxes[:, 2] / 2 - dw) / ratio
        y2 = (boxes[:, 1] + boxes[:, 3] / 2 - dh) / ratio

        # Clip to image bounds
        x1 = np.clip(x1, 0, src_w).astype(int)
        y1 = np.clip(y1, 0, src_h).astype(int)
        x2 = np.clip(x2, 0, src_w).astype(int)
        y2 = np.clip(y2, 0, src_h).astype(int)

        # NMS
        dets_np = np.column_stack([x1, y1, x2, y2, person_scores])
        indices = _nms(dets_np, iou_threshold=0.5)

        results = []
        for i in indices:
            cx = int((x1[i] + x2[i]) / 2)
            cy = int((y1[i] + y2[i]) / 2)
            # Filter by region if provided
            if region is not None:
                rx, ry, rw, rh = region
                if not (rx <= cx <= rx + rw and ry <= cy <= ry + rh):
                    continue
            results.append(Detection(
                x1=int(x1[i]), y1=int(y1[i]),
                x2=int(x2[i]), y2=int(y2[i]),
                conf=float(person_scores[i]),
                cx=cx, cy=cy
            ))

        # Sort left to right
        results.sort(key=lambda d: d.cx)
        return results


def _nms(dets: np.ndarray, iou_threshold: float = 0.5) -> List[int]:
    """Simple Non-Maximum Suppression."""
    if len(dets) == 0:
        return []
    x1 = dets[:, 0]
    y1 = dets[:, 1]
    x2 = dets[:, 2]
    y2 = dets[:, 3]
    scores = dets[:, 4]

    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while len(order) > 0:
        i = order[0]
        keep.append(int(i))
        if len(order) == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep
