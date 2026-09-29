"""Adapts the ByteTrack wrapper (tracker_pipeline.SimpleTracker) to the
TrackObject data format used by the rest of the vision pipeline.

Data format differences bridged here:
    Input  (this pipeline)  : list of detection dicts
                              {class_id, label, confidence, bbox{x1,y1,x2,y2},
                               center{x,y}, width, height, area}
    Input  (SimpleTracker)  : np.ndarray (N, 5) = (x, y, w, h, conf)
                              with (x, y) the TOP-LEFT corner.

    Output (SimpleTracker)  : list of dicts {track_id, tlwh:(x,y,w,h), score}
    Output (this pipeline)  : list of TrackObject (defined in this module).

SimpleTracker does not carry class/label or velocity, and it reports no
classification, so this adapter:
    * re-matches each tracked box to its source YOLO detection (by IoU) to
      recover class_id/label;
    * computes velocity from the center movement between frames;
    * persists the classification by track_id so it survives the fact that a
      fresh TrackObject is rebuilt on every frame.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np


class TrackObject:
    """Stores the state of one tracked object across frames.

    This data container replaces the old ``bytetrack.TrackObject`` so the
    pipeline no longer depends on bytetrack.py (tracking runs entirely on
    tracker_pipeline.SimpleTracker).
    """

    def __init__(self, track_id: int, detection: Dict, frame_id: int) -> None:
        # Unique id for this track (independent of class_id).
        self.track_id = track_id

        # Object type information from YOLO.
        self.class_id = detection["class_id"]
        self.label = detection["label"]

        # Detection confidence.
        self.confidence = detection["confidence"]

        # Bounding box as {x1, y1, x2, y2}.
        self.bbox = detection["bbox"]

        # Center point of the box as a tuple (x, y).
        self.center = (detection["center"]["x"], detection["center"]["y"])

        # Box dimensions.
        self.width = detection["width"]
        self.height = detection["height"]
        self.area = detection["area"]

        # Movement vector (px per frame), starts at zero.
        self.velocity = (0.0, 0.0)

        # Frame age in updates.
        self.age = 0

        # Frame id where the object was last seen.
        self.last_seen = frame_id

        # Frames since the object was last matched.
        self.time_since_update = 0

        # Reserved for the classifier; filled by a later stage.
        self.classification: Optional[Dict] = None

        # True when this box is a Kalman PREDICTION (object currently out of
        # sight / occluded), not a fresh detection.
        self.occluded: bool = False

        # Frames since the object was last seen (0 for visible tracks).
        self.frames_lost: int = 0

    def to_dict(self) -> Dict:
        """Return a compact dictionary for downstream systems."""
        return {
            "track_id": self.track_id,
            "class_id": self.class_id,
            "label": self.label,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "center": self.center,
            "velocity": self.velocity,
            "width": self.width,
            "height": self.height,
            "area": self.area,
            "age": self.age,
            "last_seen": self.last_seen,
            "time_since_update": self.time_since_update,
            "classification": self.classification,
            "occluded": self.occluded,
            "frames_lost": self.frames_lost,
        }


def detections_to_array(detections) -> np.ndarray:
    """Convert pipeline detection dicts into SimpleTracker's (N, 5) format.

    (x, y) = top-left corner, (w, h) = box size, last column = confidence.
    """
    dets = []
    for det in detections:
        box = det["bbox"]
        dets.append([
            float(box["x1"]),
            float(box["y1"]),
            float(box["x2"] - box["x1"]),
            float(box["y2"] - box["y1"]),
            float(det["confidence"]),
        ])
    return np.asarray(dets, dtype=np.float64).reshape(-1, 5)


def box_iou(x1: float, y1: float, x2: float, y2: float, det: Dict) -> float:
    """IoU between a tracked box and one detection box."""
    box = det["bbox"]
    ix1 = max(x1, box["x1"])
    iy1 = max(y1, box["y1"])
    ix2 = min(x2, box["x2"])
    iy2 = min(y2, box["y2"])

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = (x2 - x1) * (y2 - y1)
    area_b = (box["x2"] - box["x1"]) * (box["y2"] - box["y1"])
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def best_detection(x1, y1, x2, y2, detections) -> Optional[Dict]:
    """Return the YOLO detection with the highest IoU for the given box."""
    best = None
    best_iou = 0.0
    for det in detections:
        iou = box_iou(x1, y1, x2, y2, det)
        if iou > best_iou:
            best_iou = iou
            best = det
    return best


class TrackerAdapter:
    """Wraps SimpleTracker and returns TrackObject-compatible tracks."""

    def __init__(self, frame_height: int, frame_width: int, frame_rate: int = 30) -> None:
        # The real ByteTrack engine (from the updated tracker_pipeline.py).
        from tracker_pipeline import SimpleTracker

        self.tracker = SimpleTracker(
            frame_height=frame_height, frame_width=frame_width, frame_rate=frame_rate
        )

        # Current frame id (mirrors vision_system.frame_id).
        self.frame_id = 0

        # Per-track state that SimpleTracker does not keep for us:
        # track_id -> {center, classification, last_seen, class_id, label}.
        self.track_meta: Dict[int, Dict] = {}

    def update(self, detections, frame_id: int) -> List[TrackObject]:
        """Advance the tracker and convert the raw output to TrackObjects.

        Returns visible tracks plus currently occluded (lost-but-predicted)
        tracks, each marked with ``track.occluded`` and ``track.frames_lost``.
        """
        self.frame_id = frame_id

        # Feed SimpleTracker the (x, y, w, h, conf) array it expects.
        dets_array = detections_to_array(detections)
        raw = self.tracker.update_with_occlusion(dets_array)

        tracks = self._build_visible(raw["visible"], detections, frame_id)
        tracks.extend(self._build_occluded(raw["occluded"], frame_id))

        self._prune(frame_id)
        return tracks

    def _build_visible(self, raw_tracks, detections, frame_id: int) -> List[TrackObject]:
        """Convert matched (visible) tracks into TrackObjects."""
        tracks: List[TrackObject] = []
        for raw in raw_tracks:
            track_id = raw["track_id"]
            x1, y1, w, h = raw["tlwh"]

            # Recover class/label from the matching YOLO detection.
            det = best_detection(x1, y1, x1 + w, y1 + h, detections)
            if det is None:
                continue

            # Rebuild a pipeline detection record with the tracked box.
            x2, y2 = x1 + w, y1 + h
            detection = dict(det)
            detection["bbox"] = {
                "x1": round(x1), "y1": round(y1),
                "x2": round(x2), "y2": round(y2),
            }
            detection["width"] = round(w)
            detection["height"] = round(h)
            detection["center"] = {"x": (x1 + x2) / 2.0, "y": (y1 + y2) / 2.0}
            detection["area"] = round(w * h)
            detection["confidence"] = raw["score"]

            # Build the track data container (tracking engine = SimpleTracker).
            track = TrackObject(track_id, detection, frame_id)

            # Restore persisted state (velocity + classification).
            meta = self.track_meta.get(track_id)
            if meta is not None:
                prev_center = meta["center"]
                track.velocity = (track.center[0] - prev_center[0],
                                  track.center[1] - prev_center[1])
                track.classification = meta["classification"]

            # Store state for the next frame.
            self.track_meta[track_id] = {
                "center": track.center,
                "classification": track.classification,
                "last_seen": frame_id,
                "class_id": track.class_id,
                "label": track.label,
            }
            tracks.append(track)
        return tracks

    def _build_occluded(self, raw_occluded, frame_id: int) -> List[TrackObject]:
        """Convert lost-but-predicted tracks into occluded TrackObjects.

        There is no detection to match these to, so class/label come from the
        last time the track was seen (track_meta). ``last_seen`` is NOT
        refreshed so stale tracking state is still pruned correctly.
        """
        tracks: List[TrackObject] = []
        for raw in raw_occluded:
            track_id = raw["track_id"]
            meta = self.track_meta.get(track_id)
            if meta is None or meta.get("label") is None:
                continue  # never seen this frame, cannot rebuild it

            x1, y1, w, h = raw["tlwh"]
            x2, y2 = x1 + w, y1 + h
            detection = {
                "class_id": meta["class_id"],
                "label": meta["label"],
                "confidence": raw["score"],
                "bbox": {
                    "x1": round(x1), "y1": round(y1),
                    "x2": round(x2), "y2": round(y2),
                },
                "center": {"x": (x1 + x2) / 2.0, "y": (y1 + y2) / 2.0},
                "width": round(w),
                "height": round(h),
                "area": round(w * h),
            }
            track = TrackObject(track_id, detection, frame_id)
            track.occluded = True
            track.frames_lost = raw["frames_lost"]
            track.time_since_update = raw["frames_lost"]
            track.classification = meta["classification"]

            # Velocity from the last known real center to the predicted one.
            prev_center = meta["center"]
            track.velocity = (track.center[0] - prev_center[0],
                              track.center[1] - prev_center[1])
            tracks.append(track)
        return tracks

    def remember_classification(self, track: TrackObject) -> None:
        """Persist a track's classification so it survives across frames."""
        meta = self.track_meta.setdefault(track.track_id, {
            "center": track.center,
            "classification": None,
            "last_seen": self.frame_id,
            "class_id": track.class_id,
            "label": track.label,
        })
        meta["classification"] = track.classification

    def _prune(self, frame_id: int, max_lost: int = 60) -> None:
        """Drop state for track ids gone for too long (ids never come back)."""
        stale = [
            track_id for track_id, meta in self.track_meta.items()
            if frame_id - meta["last_seen"] > max_lost
        ]
        for track_id in stale:
            del self.track_meta[track_id]
