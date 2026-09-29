"""Final Vision inference module for real game use.

Input:  one game screen image (OpenCV BGR).
Output: normalized world state list for the World Model.

Pipeline:
    Screen Image -> YOLO Detector -> SimpleTracker (tracker_pipeline.py)
                 -> TrackObject -> Classifier -> World Model Output

Tracking is handled ENTIRELY by tracker_pipeline.SimpleTracker, which drives
the ByteTrack sources in the tracker/ package:
    tracker/byte_tracker.py   (BYTETracker)
    tracker/kalman_filter.py  (KalmanFilter)
    tracker/matching.py       (IoU / linear assignment)
    tracker/basetrack.py      (BaseTrack, TrackState)

YOLO-first mode (default): ByteTrack is used ONLY for stable track_id
association. The reported box/center/size/confidence are the raw YOLO
detection values, and occluded (Kalman-predicted) tracks are not emitted
unless include_occluded=True.

Tracking uses DetectionTracker by default: YOLO boxes are matched
frame-to-frame (IoU + camera-shifted center distance). No Kalman motion
model — better when the player stays centered and the world scrolls.
ByteTrack (SimpleTracker) remains available via tracker_backend="bytetrack".
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# F5 / `python path/to/test_vision.py` loads this file as a top-level script,
# not as package `_02_vision`. Relative imports (from .) fail in that mode.
_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from box_merge import (
    find_part_pairs,
    is_single_yolo_class,
    merge_part_detections,
    same_resnet_class,
    same_yolo_class,
)
from detector import Detector, resolve_device
from tracker_pipeline import DetectionTracker, SimpleTracker
from classifier import Classifier, resolve_classifier_path
from for_world_model import (
    DEFAULT_WORLD_OUTPUT_DIR,
    build_world_entry_from_detection,
    build_world_entry_from_track,
    is_background_classification,
    save_world_state_json,
)


class TrackObject:
    """Stores the state of one tracked object across frames."""

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
    """Convert detection dicts into SimpleTracker's (N, 5) format.

    Columns: (x, y, w, h, conf) with (x, y) the TOP-LEFT corner.
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


class _ClassifyStub:
    """Minimal object for Classifier.predict_batch (YOLO-only sightings)."""

    __slots__ = ("track_id", "bbox", "classification")

    def __init__(self, bbox: Dict) -> None:
        self.track_id = -1
        self.bbox = bbox
        self.classification: Optional[Dict] = None


def bbox_key(bbox: Dict) -> tuple:
    """Hashable box key for per-frame classification highlights."""
    return (
        int(bbox["x1"]), int(bbox["y1"]),
        int(bbox["x2"]), int(bbox["y2"]),
    )


def _norm_label(label: Optional[str]) -> str:
    return (label or "").strip().lower()


# YOLO is 1-class ("object"). Display names come from ResNet coarse output.
RESNET_TO_LABEL = {
    "window": "Win",
    "win": "Win",
    "player": "Player",
    "npc": "NPC",
    "grounditem": "Item",
    "item": "Item",
    "monster": "Monster",
}


def _label_from_resnet(classification: Optional[Dict]) -> Optional[str]:
    name = _norm_label((classification or {}).get("class_name"))
    return RESNET_TO_LABEL.get(name)


class VisionSystem:
    """Runs the full vision pipeline and returns normalized world data."""

    def __init__(
        self,
        include_occluded: bool = False,
        # YOLO score floor (code default; not config.yaml conf_threshold).
        detector_conf: float = 0.15,
        detector_iou: float = 0.7,
        detector_device: str = "cpu",
        detector_imgsz: int = 960,
        frame_rate: int = 30,
        track_thresh: float = 0.5,
        track_buffer: int = 3,
        match_thresh: float = 0.8,
        mot20: bool = False,


        low_thresh: float = 0.4,
        yolo_conf_low: float = 0.50,
        roi_conf: float = 0.1,
        focus_conf: float = 0.1,


        second_match_thresh: float = 0.5,
        unconfirmed_match_thresh: float = 0.7,
        tracker_backend: str = "yolo_iou",
        track_iou_thresh: float = 0.2,
        track_max_center_dist: float = 100.0,
        yolo_conf_high: float = 0.70,
        detail_conf_low: float = 0.55,
        monster_reclassify_interval: int = 20,
        max_reclassify_per_frame: int = 2,
        # Tracks alive this long get a periodic force-ResNet (bypasses freeze).
        stable_reclassify_after_s: float = 5.0,
        stable_reclassify_interval_s: float = 5.0,
        # Local character sits at relative WCS (0,0) ≈ battle player UV.
        # Force-refresh that track so a wrong first label cannot freeze forever.
        ego_reclassify_interval_s: float = 2.0,
        ego_center_x: float = 0.5,
        ego_center_y: float = 0.41427826993225636,  # battle player_v * height
        ego_match_radius: float = 0.08,
        roi_boost_enabled: bool = False,
        roi_expand_ratio: float = 1.4,
        roi_expand_px: int = 32,
        focus_enabled: bool = False,
        focus_center_x: float = 0.5,
        focus_center_y: float = 0.37,
        focus_radius_x: float = 0.30,
        focus_radius_y: float = 0.25,
        enable_timing_print: bool = False,
        classifier_device: str = "auto",
        classifier_edition: Optional[str] = None,
        classifier_model_path: Optional[str] = None,
        detector_model_path: Optional[str] = None,
        world_output_dir: Optional[str] = None,
        save_world_json: bool = False,
    ) -> None:
        # Aggressive YOLO-first mode: only objects YOLO actually sees this
        # frame are reported (no Kalman-predicted ghost boxes). Set to True
        # to also emit occluded (tracker-only) tracks marked occluded=true.
        self.include_occluded = include_occluded

        # Tracker tuning knobs (see tracker_pipeline.SimpleTracker / ByteTrack).
        self.frame_rate = frame_rate
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.mot20 = mot20
        self.low_thresh = low_thresh
        self.second_match_thresh = second_match_thresh
        self.unconfirmed_match_thresh = unconfirmed_match_thresh
        self.tracker_backend = tracker_backend
        self.track_iou_thresh = track_iou_thresh
        self.track_max_center_dist = track_max_center_dist
        self.yolo_conf_high = yolo_conf_high
        self.yolo_conf_low = yolo_conf_low
        self.detail_conf_low = detail_conf_low
        self.monster_reclassify_interval = max(1, int(monster_reclassify_interval))
        self.max_reclassify_per_frame = max(1, int(max_reclassify_per_frame))
        self.stable_reclassify_after_s = max(0.0, float(stable_reclassify_after_s))
        self.stable_reclassify_interval_s = max(0.0, float(stable_reclassify_interval_s))
        self.ego_reclassify_interval_s = max(0.1, float(ego_reclassify_interval_s))
        self.ego_center_x = float(ego_center_x)
        self.ego_center_y = float(ego_center_y)
        self.ego_match_radius = max(0.01, float(ego_match_radius))
        self._last_ego_reclassify_time = 0.0
        self._ego_force_track_id: Optional[int] = None
        self._stable_force_track_ids: set = set()
        self.roi_boost_enabled = roi_boost_enabled
        self.roi_conf = roi_conf
        self.roi_expand_ratio = roi_expand_ratio
        self.roi_expand_px = roi_expand_px
        self.detector_conf = detector_conf
        self.detector_iou = detector_iou
        self.detector_imgsz = detector_imgsz
        self.focus_enabled = focus_enabled
        self.focus_center_x = focus_center_x
        self.focus_center_y = focus_center_y
        self.focus_radius_x = max(0.05, float(focus_radius_x))
        self.focus_radius_y = max(0.05, float(focus_radius_y))
        self.focus_conf = focus_conf
        self.enable_timing_print = enable_timing_print
        self.classifier_device = classifier_device
        self.classifier_edition = classifier_edition
        self.classifier_model_path = resolve_classifier_path(
            edition=classifier_edition,
            model_path=classifier_model_path,
        )
        self.detector_model_path = detector_model_path
        self.save_world_json = save_world_json
        self.world_output_dir = (
            Path(world_output_dir)
            if world_output_dir is not None
            else DEFAULT_WORLD_OUTPUT_DIR
        )
        self.detector_device = resolve_device(detector_device)
        self._world_json_index = 0
        self.last_world_json_path: Optional[Path] = None
        self._vision_region = ""
        self._detector_by_path: Dict[str, Detector] = {}
        self._classifier_by_path: Dict[str, Classifier] = {}

        # Load all pipeline models once.
        self.load_models(
            detector_conf, detector_iou, self.detector_device, detector_imgsz
        )

        # Frame counter used by the tracker.
        self.frame_id = 0

        # Duration (seconds) of each stage from the last process() call.
        self.timing: Dict[str, float] = {}

        # Per-track state that SimpleTracker does not keep for us:
        # track_id -> {center, classification, last_seen, class_id, label}.
        self.track_meta: Dict[int, Dict] = {}

        # One-shot classification cache. Matched by box IoU (not YOLO class:
        # the 1-class detector has only class_id 0).
        # Each entry: {bbox, class_id, classification, attempted, last_seen,
        #              bound_track_id}.
        # TTL matches track_buffer: a gap longer than that means a new identity
        # (new spawn in the same spot must be re-classified).
        self.det_cache: List[Dict] = []
        self._det_cache_iou = 0.5
        self._identity_max_lost = max(1, int(track_buffer))

        self.ego_motion = (0.0, 0.0)
        self._prev_det_boxes: List[Dict] = []  # ByteTrack ego-motion only

        # Set each classify() call: ids / boxes that ran ResNet this frame (UI).
        self.classified_track_ids_this_frame: set = set()
        self.classified_bbox_keys_this_frame: set = set()
        self.scene_crowded: bool = False
        # Previous-frame detection ROIs (1-frame memory) for roi_boost.
        self._prev_frame_rois: List[Dict] = []

    def load_models(
        self,
        detector_conf=0.5,
        detector_iou=0.45,
        detector_device="cpu",
        detector_imgsz=960,
    ) -> None:
        """Create the detector, tracker and classifier."""
        # YOLO detector (path from config or detector.py MODEL_PATH).
        det_kwargs = dict(
            conf=detector_conf,
            iou=detector_iou,
            device=detector_device,
            imgsz=detector_imgsz,
        )
        if self.detector_model_path:
            det_kwargs["model_path"] = self.detector_model_path
        self.detector = Detector(**det_kwargs)
        if self.detector_model_path:
            try:
                det_key = str(Path(self.detector_model_path).resolve())
            except OSError:
                det_key = str(self.detector_model_path)
            self._detector_by_path[det_key] = self.detector

        # ByteTrack tracker from tracker_pipeline.py (created lazily once
        # the frame size is known; it needs the frame dimensions).
        self.tracker = None

        # ResNet18 multi-head classifier (app/models/1400+bestclassify+0.97.pt).
        clf_dev = (
            self.classifier_device
            if self.classifier_device != "auto"
            else self.detector_device
        )
        self.classifier = Classifier(self.classifier_model_path, device=clf_dev)
        if self.classifier_model_path:
            try:
                clf_key = str(Path(self.classifier_model_path).resolve())
            except OSError:
                clf_key = str(self.classifier_model_path)
            self._classifier_by_path[clf_key] = self.classifier

        # Current pipeline state.
        self.detections = []
        self.tracks = []
        self.image_width = 0
        self.image_height = 0
        self._warmed_up = False

    def _reset_tracks_for_model_swap(self) -> None:
        self.tracker = None
        self.track_meta = {}
        self.det_cache = []
        self._prev_frame_rois = []
        self._prev_det_boxes = []
        self._warmed_up = False

    def _swap_detector(self, model_path: str) -> None:
        try:
            path = str(Path(model_path).resolve())
        except OSError:
            path = str(model_path)
        cached = self._detector_by_path.get(path)
        if cached is None:
            cached = Detector(
                model_path=path,
                conf=self.detector_conf,
                iou=self.detector_iou,
                device=self.detector_device,
                imgsz=self.detector_imgsz,
            )
            self._detector_by_path[path] = cached
        self.detector = cached
        self.detector_model_path = path
        self._reset_tracks_for_model_swap()

    def _swap_classifier(self, model_path: str) -> None:
        try:
            path = str(Path(model_path).resolve())
        except OSError:
            path = str(model_path)
        cached = self._classifier_by_path.get(path)
        if cached is None:
            clf_dev = (
                self.classifier_device
                if self.classifier_device != "auto"
                else self.detector_device
            )
            cached = Classifier(path, device=clf_dev)
            self._classifier_by_path[path] = cached
        self.classifier = cached
        self.classifier_model_path = path

    def set_region(
        self,
        region: str,
        config: Optional[dict] = None,
    ) -> bool:
        """Load YOLO + classifier for an area ``region``. True if either changed."""
        key = str(region or "").strip()
        if key == self._vision_region:
            return False
        try:
            from region_models import resolve_region_models
        except ImportError:
            from app._02_vision.region_models import resolve_region_models

        models = resolve_region_models(key, config)
        changed = False

        def _same(a: Optional[str], b: Optional[str]) -> bool:
            if not a or not b:
                return not a and not b
            try:
                return Path(a).resolve() == Path(b).resolve()
            except OSError:
                return str(a) == str(b)

        if models.detector_path and not _same(
            models.detector_path, self.detector_model_path
        ):
            self._swap_detector(models.detector_path)
            changed = True
        if models.classifier_path and not _same(
            models.classifier_path, self.classifier_model_path
        ):
            self._swap_classifier(models.classifier_path)
            changed = True
        self._vision_region = key
        return changed

    def process(self, screen_image) -> List[dict]:
        """Run the complete pipeline on one screen image.

        Input:  screen_image (OpenCV BGR).
        Output: normalized world state list.
        """
        if screen_image is None or getattr(screen_image, "size", 0) == 0:
            self.detections = []
            self.tracks = []
            self.timing = {}
            return []

        self.timing = {}

        # Detect objects in the screen image.
        t0 = time.perf_counter()
        self.detect(screen_image)
        self.timing["detect"] = time.perf_counter() - t0

        # Track the detections across frames.
        t0 = time.perf_counter()
        self.track()
        self.timing["track"] = time.perf_counter() - t0

        # Classify only the new objects.
        t0 = time.perf_counter()
        self.classify(screen_image)
        self.timing["classify"] = time.perf_counter() - t0

        # Build and return the normalized world state.
        t0 = time.perf_counter()
        world = self.create_world_state()
        self.timing["world"] = time.perf_counter() - t0

        if self.save_world_json:
            self._world_json_index += 1
            self.last_world_json_path = save_world_state_json(
                world,
                self.world_output_dir,
                f"frame_{self._world_json_index:06d}.json",
            )

        # Print how long every stage took.
        if self.enable_timing_print:
            self.print_stage_timing()
        return world

    def print_stage_timing(self) -> None:
        """Print the per-stage duration of the last process() call."""
        if not self.timing:
            return
        parts = [f"{name}={value * 1000:.1f}ms" for name, value in self.timing.items()]
        total = sum(self.timing.values()) * 1000
        print("timing: " + " ".join(parts) + f" | total={total:.1f}ms")

    def detect(self, screen_image) -> None:
        """Run YOLO detection on the screen image.

        Input:  screen_image (OpenCV BGR).
        Output: detections stored in self.detections.
        """
        # Remember only the screen size (no image data is stored).
        self.image_height, self.image_width = screen_image.shape[:2]

        # Create the tracker on the first frame (it needs the frame size).
        if self.tracker is None:
            if self.tracker_backend == "bytetrack":
                self.tracker = SimpleTracker(
                    self.image_height, self.image_width,
                    frame_rate=self.frame_rate,
                    track_thresh=self.track_thresh,
                    track_buffer=self.track_buffer,
                    match_thresh=self.match_thresh,
                    mot20=self.mot20,
                    low_thresh=self.low_thresh,
                    second_match_thresh=self.second_match_thresh,
                    unconfirmed_match_thresh=self.unconfirmed_match_thresh,
                )
            else:
                self.tracker = DetectionTracker(
                    self.image_height, self.image_width,
                    track_buffer=self.track_buffer,
                    iou_thresh=self.track_iou_thresh,
                    max_center_dist=self.track_max_center_dist,
                )

        # Run YOLO; keep low-conf dets in prev-frame ROIs and/or character focus zone.
        if not self._warmed_up:
            self.detector.warmup(screen_image)
            self._warmed_up = True

        use_low_pass = self.roi_boost_enabled and (
            bool(self._prev_frame_rois) or self.focus_enabled
        )
        if use_low_pass:
            infer_conf = min(self.detector_conf, self.roi_conf)
            if self.focus_enabled:
                infer_conf = min(infer_conf, self.focus_conf)
            raw = self.detector.detect(screen_image, conf=infer_conf)
            self.detections = self._apply_roi_boost_filter(raw)
        else:
            self.detections = self.detector.detect(screen_image)

        # Collapse fragments of a LARGE object (Godon-scale) before tracking.
        # Small nearby monsters are not merged. Player/item crops stay.
        self.detections = self._merge_monster_parts(
            self.detections, screen_image
        )

        self.scene_crowded = self._scene_is_crowded(self.detections)
        self._prev_frame_rois = self._build_rois_from_detections(self.detections)

    def _expand_bbox(self, bbox: Dict) -> Dict:
        """Expand a box around its center for the 1-frame ROI boost region."""
        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        half_w = max((x2 - x1) * self.roi_expand_ratio / 2.0, self.roi_expand_px)
        half_h = max((y2 - y1) * self.roi_expand_ratio / 2.0, self.roi_expand_px)
        return {
            "x1": int(round(cx - half_w)),
            "y1": int(round(cy - half_h)),
            "x2": int(round(cx + half_w)),
            "y2": int(round(cy + half_h)),
        }

    def _build_rois_from_detections(self, detections: List[Dict]) -> List[Dict]:
        """Build per-class ROIs from this frame (used on the next frame only)."""
        rois = []
        for det in detections:
            rois.append({
                "class_id": det["class_id"],
                "label": det["label"],
                "bbox": self._expand_bbox(det["bbox"]),
            })
        return rois

    @staticmethod
    def _center_in_bbox(center: Dict, bbox: Dict) -> bool:
        return (
            bbox["x1"] <= center["x"] <= bbox["x2"]
            and bbox["y1"] <= center["y"] <= bbox["y2"]
        )

    def _in_prev_frame_roi(self, det: Dict) -> bool:
        """True if det center lies in an ROI from the previous frame."""
        for roi in self._prev_frame_rois:
            if self._center_in_bbox(det["center"], roi["bbox"]):
                return True
        return False

    def _merge_monster_parts(
        self, detections: List[Dict], screen_image
    ) -> List[Dict]:
        """Drop part-boxes of a large object; keep a nearby player/item."""
        if len(detections) < 2:
            return detections
        frame_w = float(self.image_width)
        frame_h = float(self.image_height)

        if is_single_yolo_class(detections) and self.classifier is not None:
            pairs = find_part_pairs(detections, frame_w, frame_h)
            if not pairs:
                return detections
            idxs = sorted({i for pair in pairs for i in pair})
            stubs = [_ClassifyStub(detections[i]["bbox"]) for i in idxs]
            self.classifier.predict_batch(stubs, screen_image)
            for stub, i in zip(stubs, idxs):
                cls = stub.classification or {}
                detections[i]["part_class"] = _norm_label(cls.get("class_name"))
            return merge_part_detections(
                detections, frame_w, frame_h, same_class=same_resnet_class
            )

        return merge_part_detections(
            detections, frame_w, frame_h, same_class=same_yolo_class
        )

    def _in_focus_zone(self, det: Dict) -> bool:
        """True if det center lies in the fixed character focus ellipse."""
        if not self.focus_enabled or self.image_width <= 0 or self.image_height <= 0:
            return False
        nx = float(det["center"]["x"]) / self.image_width
        ny = float(det["center"]["y"]) / self.image_height
        dx = (nx - self.focus_center_x) / self.focus_radius_x
        dy = (ny - self.focus_center_y) / self.focus_radius_y
        return (dx * dx + dy * dy) <= 1.0

    def _focus_distance(self, det_or_track) -> float:
        """Normalized distance to character focus center (lower = more important)."""
        if self.image_width <= 0 or self.image_height <= 0:
            return 1.0
        if hasattr(det_or_track, "center"):
            cx, cy = det_or_track.center
        else:
            c = det_or_track["center"]
            cx, cy = c["x"], c["y"]
        nx = float(cx) / self.image_width - self.focus_center_x
        ny = float(cy) / self.image_height - self.focus_center_y
        return (nx * nx + ny * ny) ** 0.5

    def _apply_roi_boost_filter(self, detections: List[Dict]) -> List[Dict]:
        """Keep global-conf dets everywhere; low-conf in prev ROIs or focus zone."""
        low_floor = self.roi_conf
        if self.focus_enabled:
            low_floor = min(low_floor, self.focus_conf)
        kept: List[Dict] = []
        for det in detections:
            conf = float(det["confidence"])
            if conf >= self.detector_conf:
                kept.append(det)
                continue
            if conf < low_floor:
                continue
            in_prev = self._in_prev_frame_roi(det)
            in_focus = self._in_focus_zone(det)
            if not in_prev and not in_focus:
                continue
            boosted = dict(det)
            if in_prev:
                boosted["roi_boosted"] = True
            if in_focus:
                boosted["focus_boosted"] = True
            kept.append(boosted)
        return self._nms_detections(kept, iou_thresh=0.5)

    @staticmethod
    def _nms_detections(detections: List[Dict], iou_thresh: float = 0.5) -> List[Dict]:
        """Greedy NMS; prefer higher confidence when boxes overlap."""
        order = sorted(
            range(len(detections)),
            key=lambda i: float(detections[i]["confidence"]),
            reverse=True,
        )
        kept = []
        for i in order:
            box_i = detections[i]["bbox"]
            suppress = False
            for j in kept:
                box_j = detections[j]["bbox"]
                if VisionSystem._det_bbox_iou_static(box_i, box_j) >= iou_thresh:
                    suppress = True
                    break
            if not suppress:
                kept.append(i)
        return [detections[i] for i in kept]

    @staticmethod
    def _det_bbox_iou_static(a: Dict, b: Dict) -> float:
        return box_iou(a["x1"], a["y1"], a["x2"], a["y2"], {"bbox": b})

    def track(self) -> None:
        """Advance the tracker by one frame.

        Input:  self.detections.
        Output: tracked objects stored in self.tracks.
        """
        # Increase the frame counter.
        self.frame_id += 1

        if self.tracker_backend == "bytetrack":
            dx, dy = self._estimate_ego_motion(self.detections)
            self.ego_motion = (dx, dy)
            self.tracker.apply_ego_motion(dx, dy)
            dets_array = detections_to_array(self.detections)
            raw = self.tracker.update_with_occlusion(dets_array)
            self._remember_prev_det_boxes()
        else:
            raw = self.tracker.update_with_occlusion(
                self.detections, crowded=self.scene_crowded
            )
            self.ego_motion = getattr(
                self.tracker, "last_ego_motion", (0.0, 0.0)
            )

        self.tracks = self._build_tracks(raw)

    def _remember_prev_det_boxes(self) -> None:
        """Store detection geometry for ByteTrack ego-motion (legacy backend)."""
        self._prev_det_boxes = [
            {
                "class_id": det["class_id"],
                "bbox": dict(det["bbox"]),
                "center": (
                    float(det["center"]["x"]),
                    float(det["center"]["y"]),
                ),
            }
            for det in self.detections
        ]

    def _estimate_ego_motion(
        self,
        detections: List[Dict],
        min_matches: int = 2,
        max_center_dist: float = 180.0,
    ) -> tuple:
        """Estimate camera scroll as the median displacement of matched dets.

        Returns (dx, dy) in pixels: current_center - previous_center.
        With a centered character, this is mostly world scroll from walking.
        """
        if not self._prev_det_boxes or not detections:
            return (0.0, 0.0)

        prev_unused = list(range(len(self._prev_det_boxes)))
        deltas = []

        # Greedy nearest-center match (1-class YOLO has no type to filter on).
        curr_order = sorted(
            detections,
            key=lambda d: float(d.get("confidence", 0.0)),
            reverse=True,
        )
        for det in curr_order:
            cx = float(det["center"]["x"])
            cy = float(det["center"]["y"])
            best_j = None
            best_dist = max_center_dist
            for j in prev_unused:
                prev = self._prev_det_boxes[j]
                px, py = prev["center"]
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_j = j
            if best_j is None:
                continue
            prev = self._prev_det_boxes[best_j]
            prev_unused.remove(best_j)
            deltas.append((cx - prev["center"][0], cy - prev["center"][1]))

        if len(deltas) < min_matches:
            # Single match is weak (could be one moving monster); ignore.
            return (0.0, 0.0)

        dx = float(np.median([d[0] for d in deltas]))
        dy = float(np.median([d[1] for d in deltas]))
        return (dx, dy)

    @staticmethod
    def _det_bbox_iou(a: Dict, b: Dict) -> float:
        return box_iou(
            a["bbox"]["x1"], a["bbox"]["y1"], a["bbox"]["x2"], a["bbox"]["y2"],
            b,
        )

    def _scene_is_crowded(self, detections: List[Dict]) -> bool:
        """True when nearby boxes risk id / label bleed (different classes overlap)."""
        if len(detections) < 2:
            return False
        for i in range(len(detections)):
            for j in range(i + 1, len(detections)):
                a, b = detections[i], detections[j]
                if self._det_bbox_iou(a, b) < 0.12:
                    continue
                if a["class_id"] != b["class_id"]:
                    return True
                ca = (a["center"]["x"], a["center"]["y"])
                cb = (b["center"]["x"], b["center"]["y"])
                if ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5 < 90:
                    return True
        return False

    def _apply_classification_safety(
        self, yolo_label: str, classification: Optional[Dict]
    ) -> Optional[Dict]:
        """Return ResNet classification unchanged (never overwrite with YOLO)."""
        return classification

    def _build_tracks(self, raw: Dict) -> List[TrackObject]:
        """Convert SimpleTracker's {visible, occluded} output to TrackObjects."""
        tracks = self._build_visible(raw["visible"])
        if self.include_occluded:
            tracks.extend(self._build_occluded(raw["occluded"]))
        self._prune_meta()
        return tracks

    def _build_visible(self, raw_tracks) -> List[TrackObject]:
        """Convert matched (visible) tracks into TrackObjects.

        YOLO-first: the reported box/center/size/confidence are the raw YOLO
        detection values. ByteTrack is used ONLY to assign a stable track_id
        (association), never to smooth the box geometry.
        """
        tracks: List[TrackObject] = []

        # Working copy so each YOLO detection is used by at most one track
        # (overlapping boxes must not steal the same detection).
        available = list(self.detections)

        for raw in raw_tracks:
            track_id = raw["track_id"]

            det_index = raw.get("det_index")
            if det_index is not None:
                det = self.detections[det_index]
            else:
                # ByteTrack fallback: re-match Kalman box to a YOLO detection.
                x1, y1, w, h = raw["tlwh"]
                det = best_detection(x1, y1, x1 + w, y1 + h, available)
                if det is None:
                    continue
                available.remove(det)

            # Rebuild a pipeline detection record from the RAW YOLO box:
            # geometry + class/label + confidence all come from the detection.
            detection = dict(det)
            detection["confidence"] = det["confidence"]

            # Build the track data container (tracking engine = SimpleTracker).
            track = TrackObject(track_id, detection, self.frame_id)

            # Restore persisted state (velocity + classification).
            meta = self.track_meta.get(track_id)
            attempted = bool(meta.get("attempted")) if meta is not None else False
            if meta is not None:
                prev_center = meta["center"]
                ego_dx, ego_dy = self.ego_motion
                # Screen delta minus camera scroll => object motion in world.
                track.velocity = (
                    track.center[0] - prev_center[0] - ego_dx,
                    track.center[1] - prev_center[1] - ego_dy,
                )
                track.classification = meta["classification"]

            track.classification = self._apply_classification_safety(
                track.label, track.classification
            )

            # Merge with prior meta so classify policy state (coarse_frozen,
            # mismatch streak, monster retry schedule) survives every frame.
            prev = self.track_meta.get(track_id, {})
            self.track_meta[track_id] = {
                "center": track.center,
                "classification": track.classification,
                "last_seen": self.frame_id,
                "class_id": track.class_id,
                "label": track.label,
                "attempted": attempted or prev.get("attempted", False),
                "coarse_frozen": prev.get("coarse_frozen", False),
                "next_eligible_frame": prev.get("next_eligible_frame", 0),
                "force_reclassify": prev.get("force_reclassify", False),
                "born_at": prev.get("born_at", time.time()),
                "last_stable_reclassify_at": prev.get("last_stable_reclassify_at"),
            }
            tracks.append(track)
        return tracks

    def _build_occluded(self, raw_occluded) -> List[TrackObject]:
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
            track = TrackObject(track_id, detection, self.frame_id)
            track.occluded = True
            track.frames_lost = raw["frames_lost"]
            track.time_since_update = raw["frames_lost"]
            track.classification = meta["classification"]
            track.classification = self._apply_classification_safety(
                track.label, track.classification
            )

            # Velocity from the last known real center to the predicted one,
            # with camera scroll removed.
            prev_center = meta["center"]
            ego_dx, ego_dy = self.ego_motion
            track.velocity = (
                track.center[0] - prev_center[0] - ego_dx,
                track.center[1] - prev_center[1] - ego_dy,
            )
            tracks.append(track)
        return tracks

    def _bbox_iou(self, a: Dict, b: Dict) -> float:
        """IoU between two {x1,y1,x2,y2} boxes."""
        return box_iou(a["x1"], a["y1"], a["x2"], a["y2"], {"bbox": b})

    def _lookup_det_cache(
        self,
        bbox: Dict,
        class_id: int,
        iou_thresh: Optional[float] = None,
        for_track_id: Optional[int] = None,
        unbound_only: bool = False,
    ) -> Optional[Dict]:
        """Find a cached sighting that overlaps this box.

        YOLO class is ignored (1-class detector). Identity is IoU + track_id.
        for_track_id: allow entries bound to this track, or still unbound.
        unbound_only: only entries not yet claimed by any track_id (YOLO-only
        bridge into the first track assignment).
        """
        thresh = self._det_cache_iou if iou_thresh is None else iou_thresh
        if self.scene_crowded:
            thresh = max(thresh, 0.55)
        best = None
        best_iou = 0.0
        for entry in self.det_cache:
            bound = entry.get("bound_track_id")
            if unbound_only and bound is not None:
                continue
            if for_track_id is not None and bound is not None and bound != for_track_id:
                # Another track already owns this classification identity.
                continue
            iou = self._bbox_iou(bbox, entry["bbox"])
            if iou > best_iou and iou >= thresh:
                best_iou = iou
                best = entry
        return best

    def _store_det_cache(
        self,
        bbox: Dict,
        class_id: int,
        classification: Optional[Dict],
        attempted: bool = True,
        bound_track_id: Optional[int] = None,
    ) -> Dict:
        """Insert or refresh a one-shot classification cache entry."""
        entry = self._lookup_det_cache(
            bbox,
            class_id,
            for_track_id=bound_track_id,
            unbound_only=(bound_track_id is None),
        )
        if entry is None and bound_track_id is not None:
            # Fall back to any overlapping unbound entry to claim it.
            entry = self._lookup_det_cache(bbox, class_id, unbound_only=True)
        if entry is None:
            entry = {
                "bbox": dict(bbox),
                "class_id": class_id,
                "classification": classification,
                "attempted": attempted,
                "last_seen": self.frame_id,
                "bound_track_id": bound_track_id,
            }
            self.det_cache.append(entry)
            return entry

        entry["bbox"] = dict(bbox)
        entry["last_seen"] = self.frame_id
        if attempted:
            entry["attempted"] = True
        if classification is not None or attempted:
            # Keep the first successful classification; never re-infer.
            if entry.get("classification") is None:
                entry["classification"] = classification
        if bound_track_id is not None and entry.get("bound_track_id") is None:
            entry["bound_track_id"] = bound_track_id
        return entry

    def _attach_cached_classification(self, track: TrackObject) -> bool:
        """Copy a cached YOLO sighting classification onto a track if any."""
        if track.classification is not None:
            return True
        # Prefer unbound YOLO-only cache (first assignment), else this track's.
        entry = self._lookup_det_cache(
            track.bbox, track.class_id, unbound_only=True
        )
        if entry is None:
            entry = self._lookup_det_cache(
                track.bbox, track.class_id, for_track_id=track.track_id
            )
        if entry is None or not entry.get("attempted"):
            return False

        track.classification = entry.get("classification")
        meta = self.track_meta.setdefault(track.track_id, {
            "center": track.center,
            "classification": None,
            "last_seen": self.frame_id,
            "class_id": track.class_id,
            "label": track.label,
            "attempted": False,
        })
        meta["classification"] = track.classification
        meta["attempted"] = True
        entry["last_seen"] = self.frame_id
        entry["bbox"] = dict(track.bbox)
        entry["bound_track_id"] = track.track_id
        return True

    def _find_ego_track(self) -> Optional[TrackObject]:
        """Visible track nearest the local-character UV (relative WCS origin)."""
        if self.image_width <= 0 or self.image_height <= 0:
            return None
        ax, ay = self.ego_center_x, self.ego_center_y
        best: Optional[TrackObject] = None
        best_d = self.ego_match_radius
        for track in self.tracks:
            if track.occluded:
                continue
            nx = float(track.center[0]) / float(self.image_width)
            ny = float(track.center[1]) / float(self.image_height)
            dist = max(abs(nx - ax), abs(ny - ay))
            if dist <= best_d:
                best_d = dist
                best = track
        return best

    def _arm_ego_reclassify(self) -> None:
        """Every ``ego_reclassify_interval_s``, force ResNet on the ego track."""
        self._ego_force_track_id = None
        ego = self._find_ego_track()
        if ego is None:
            return
        now = time.time()
        if now - self._last_ego_reclassify_time < self.ego_reclassify_interval_s:
            return
        meta = self.track_meta.setdefault(
            ego.track_id,
            {
                "center": ego.center,
                "classification": ego.classification,
                "last_seen": self.frame_id,
                "class_id": ego.class_id,
                "label": ego.label,
                "attempted": False,
                "coarse_frozen": False,
                "next_eligible_frame": 0,
                "force_reclassify": False,
                "born_at": time.time(),
                "last_stable_reclassify_at": None,
            },
        )
        meta["coarse_frozen"] = False
        meta["force_reclassify"] = True
        self._ego_force_track_id = ego.track_id

    def _arm_stable_reclassify(self) -> None:
        """Force ResNet on long-lived tracks every ``stable_reclassify_interval_s``.

        After a track has been alive for ``stable_reclassify_after_s``, refresh it
        periodically (bypasses ``coarse_frozen``). Caps arms to
        ``max_reclassify_per_frame`` (nearest focus first) so the budget is shared
        with other retries.
        """
        self._stable_force_track_ids = set()
        if self.stable_reclassify_interval_s <= 0:
            return

        now = time.time()
        candidates: List[TrackObject] = []
        for track in self.tracks:
            if track.occluded:
                continue
            meta = self.track_meta.get(track.track_id)
            if meta is None or not meta.get("attempted"):
                continue

            born_at = meta.get("born_at")
            if born_at is None:
                meta["born_at"] = now
                continue
            if now - float(born_at) < self.stable_reclassify_after_s:
                continue

            last = meta.get("last_stable_reclassify_at")
            if last is not None and (
                now - float(last) < self.stable_reclassify_interval_s
            ):
                continue
            candidates.append(track)

        if not candidates:
            return

        candidates.sort(key=self._focus_distance)
        for track in candidates[: self.max_reclassify_per_frame]:
            # Skip if ego already claimed this frame's force slot on this id —
            # ego still runs; just don't double-count the stable clock until
            # after the shared classify completes.
            meta = self.track_meta[track.track_id]
            meta["coarse_frozen"] = False
            meta["force_reclassify"] = True
            self._stable_force_track_ids.add(track.track_id)

    def _det_overlaps_track(self, det: Dict, iou_thresh: float = 0.3) -> bool:
        """True if this YOLO det is already represented by a visible track."""
        box = det["bbox"]
        for track in self.tracks:
            if track.occluded:
                continue
            if self._bbox_iou(box, track.bbox) >= iou_thresh:
                return True
        return False

    def _should_classify(self, track: TrackObject, meta: Dict) -> bool:
        """Return True if this track should run ResNet this frame.

        ResNet coarse/detail labels are authoritative. YOLO is used only for
        detection geometry and the exported ``label`` field — never to replace
        or override ``classification`` after ResNet has run.
        """
        # One-shot override for the local-character track (see _arm_ego_reclassify).
        if meta.pop("force_reclassify", False):
            return True

        cls = track.classification or meta.get("classification") or {}
        resnet_coarse = cls.get("class_name")
        detail_conf = cls.get("detail_confidence")
        yolo_conf = float(track.confidence)

        if meta.get("coarse_frozen"):
            return False

        # First sighting: mandatory classify.
        if not meta.get("attempted"):
            return True

        # Empty / failed classify — retry once pipeline allows it.
        if not resnet_coarse:
            return True

        # Trust ResNet coarse: freeze all non-monsters after the first pass.
        if _norm_label(resnet_coarse) != "monster":
            meta["coarse_frozen"] = True
            return False

        # Monster: optional detail retries when YOLO + detail conf are low.
        if yolo_conf >= self.yolo_conf_high:
            meta["coarse_frozen"] = True
            return False

        if self.frame_id < meta.get("next_eligible_frame", 0):
            return False

        if yolo_conf > self.yolo_conf_low:
            return False

        if detail_conf is not None and detail_conf >= self.detail_conf_low:
            meta["coarse_frozen"] = True
            return False

        return True

    def classify(self, screen_image) -> None:
        """Classify tracks with first-pass mandatory + selective retries.

        Input:  screen_image (OpenCV BGR).
        Output: classification on TrackObjects + det_cache (and on det dicts).
        """
        self.classified_track_ids_this_frame = set()
        self.classified_bbox_keys_this_frame = set()
        self._arm_ego_reclassify()
        self._arm_stable_reclassify()

        pending_tracks: List[TrackObject] = []
        retry_tracks: List[TrackObject] = []
        ego_force_tracks: List[TrackObject] = []
        stable_force_tracks: List[TrackObject] = []

        for track in self.tracks:
            if track.occluded:
                continue

            meta = self.track_meta.setdefault(track.track_id, {
                "center": track.center,
                "classification": None,
                "last_seen": self.frame_id,
                "class_id": track.class_id,
                "label": track.label,
                "attempted": False,
                "coarse_frozen": False,
                "next_eligible_frame": 0,
                "force_reclassify": False,
                "born_at": time.time(),
                "last_stable_reclassify_at": None,
            })
            if meta.get("born_at") is None:
                meta["born_at"] = time.time()
            meta["last_seen"] = self.frame_id
            meta["label"] = track.label
            meta["class_id"] = track.class_id

            if track.classification is None and meta.get("classification"):
                track.classification = meta["classification"]
            if track.classification is None:
                self._attach_cached_classification(track)

            track.classification = self._apply_classification_safety(
                track.label, track.classification
            )
            meta["classification"] = track.classification

            if not self._should_classify(track, meta):
                if track.classification is not None:
                    self._store_det_cache(
                        track.bbox, track.class_id, track.classification,
                        attempted=True, bound_track_id=track.track_id,
                    )
                continue
            is_ego_force = (
                self._ego_force_track_id is not None
                and track.track_id == self._ego_force_track_id
            )
            if is_ego_force:
                ego_force_tracks.append(track)
            elif track.track_id in self._stable_force_track_ids:
                stable_force_tracks.append(track)
            elif meta.get("attempted"):
                retry_tracks.append(track)
            else:
                pending_tracks.append(track)

        # Cap retry load; first-pass always runs. Ego force is never capped.
        # Stable periodic refresh shares max_reclassify_per_frame with monster retries
        # but wins priority over them once armed.
        pending_tracks.sort(key=self._focus_distance)
        retry_tracks.sort(key=self._focus_distance)
        stable_force_tracks.sort(key=self._focus_distance)
        if len(stable_force_tracks) > self.max_reclassify_per_frame:
            stable_force_tracks = stable_force_tracks[: self.max_reclassify_per_frame]
        remaining = self.max_reclassify_per_frame - len(stable_force_tracks)
        if len(retry_tracks) > remaining:
            retry_tracks = retry_tracks[:remaining]
        pending_tracks = (
            ego_force_tracks + pending_tracks + stable_force_tracks + retry_tracks
        )

        # YOLO-only dets: classify once into det_cache (first sight mandatory).
        pending_orphans: List[_ClassifyStub] = []
        orphan_dets: List[Dict] = []
        for det in self.detections:
            entry = self._lookup_det_cache(
                det["bbox"], det["class_id"], unbound_only=True
            )
            if entry is not None and entry.get("attempted"):
                if entry.get("classification") is not None:
                    det["classification"] = self._apply_classification_safety(
                        det["label"], entry["classification"]
                    )
                entry["last_seen"] = self.frame_id
                entry["bbox"] = dict(det["bbox"])
                continue
            if self._det_overlaps_track(det):
                continue
            pending_orphans.append(_ClassifyStub(det["bbox"]))
            orphan_dets.append(det)

        pending = list(pending_tracks) + pending_orphans
        if pending:
            self.classifier.predict_batch(pending, screen_image)

        for track in pending_tracks:
            meta = self.track_meta[track.track_id]
            meta["attempted"] = True
            track.classification = self._apply_classification_safety(
                track.label, track.classification
            )
            meta["classification"] = track.classification

            resnet_coarse = (track.classification or {}).get("class_name")
            if _norm_label(resnet_coarse) != "monster":
                meta["coarse_frozen"] = True
            if _norm_label(resnet_coarse) == "monster":
                meta["next_eligible_frame"] = (
                    self.frame_id + self.monster_reclassify_interval
                )

            if (
                self._ego_force_track_id is not None
                and track.track_id == self._ego_force_track_id
            ):
                # Ego refresh ran: restart the 2s clock even if label is still wrong.
                self._last_ego_reclassify_time = time.time()
                self._ego_force_track_id = None

            if track.track_id in self._stable_force_track_ids:
                meta["last_stable_reclassify_at"] = time.time()

            self.classified_track_ids_this_frame.add(track.track_id)
            self.classified_bbox_keys_this_frame.add(bbox_key(track.bbox))
            self._store_det_cache(
                track.bbox, track.class_id, track.classification,
                attempted=True, bound_track_id=track.track_id,
            )

        for stub, det in zip(pending_orphans, orphan_dets):
            stub.classification = self._apply_classification_safety(
                det["label"], stub.classification
            )
            entry = self._store_det_cache(
                det["bbox"], det["class_id"], stub.classification,
                attempted=True, bound_track_id=None,
            )
            self.classified_bbox_keys_this_frame.add(bbox_key(det["bbox"]))
            if entry.get("classification") is not None:
                det["classification"] = entry["classification"]

        for det in self.detections:
            if det.get("classification") is not None:
                continue
            entry = self._lookup_det_cache(
                det["bbox"], det["class_id"], unbound_only=True
            )
            if entry is None:
                for track in self.tracks:
                    if track.occluded:
                        continue
                    if self._bbox_iou(det["bbox"], track.bbox) < 0.3:
                        continue
                    entry = self._lookup_det_cache(
                        det["bbox"], det["class_id"],
                        for_track_id=track.track_id,
                    )
                    break
            if entry is not None and entry.get("classification") is not None:
                det["classification"] = self._apply_classification_safety(
                    det["label"], entry["classification"]
                )

        self._apply_resnet_labels()
        self._prune_det_cache()

    def _prune_meta(self, max_lost: Optional[int] = None) -> None:
        """Drop state for track ids gone long enough to count as a new identity."""
        limit = self._identity_max_lost if max_lost is None else max_lost
        stale = [
            track_id for track_id, meta in self.track_meta.items()
            if self.frame_id - meta["last_seen"] > limit
        ]
        for track_id in stale:
            del self.track_meta[track_id]
            # Drop any spatial cache claimed by this dead track so a later
            # spawn in the same place cannot inherit its classification.
            self.det_cache = [
                entry for entry in self.det_cache
                if entry.get("bound_track_id") != track_id
            ]

    def _prune_det_cache(self, max_lost: Optional[int] = None) -> None:
        """Drop cached sightings not refreshed recently (new identity after gap)."""
        limit = self._identity_max_lost if max_lost is None else max_lost
        live_ids = {t.track_id for t in self.tracks}
        kept = []
        for entry in self.det_cache:
            if self.frame_id - entry["last_seen"] > limit:
                continue
            bound = entry.get("bound_track_id")
            # If the owning track is already gone past the identity window,
            # do not keep a free-floating label at that screen location.
            if bound is not None and bound not in live_ids:
                meta = self.track_meta.get(bound)
                if meta is None:
                    continue
            kept.append(entry)
        self.det_cache = kept

    def _apply_resnet_labels(self) -> None:
        """Replace generic YOLO 'object' labels with ResNet coarse names.

        Do not write ResNet ids onto class_id: the tracker still matches
        detections with class_id 0 from the 1-class detector.
        """
        for track in self.tracks:
            name = _label_from_resnet(track.classification)
            if not name:
                continue
            track.label = name
            meta = self.track_meta.get(track.track_id)
            if meta is not None:
                meta["label"] = name
        for det in self.detections:
            name = _label_from_resnet(det.get("classification"))
            if name:
                det["label"] = name

    def create_world_state(self) -> List[dict]:
        """Build normalized world state from tracks + YOLO-only detections.

        Tracked objects keep their track_id. YOLO detections the tracker has
        not claimed yet are still emitted (track_id=None) so new first-frame
        sightings are visible to the World Model immediately, including any
        one-shot classification already stored on the detection.

        ResNet ``background`` boxes stay in ``self.tracks`` / detections for
        vision debug overlays, but are not emitted to the World Model.
        """
        w, h = self.image_width, self.image_height
        world = [
            build_world_entry_from_track(track, w, h)
            for track in self.tracks
            if not is_background_classification(track.classification)
        ]

        # Append YOLO-only dets (not IoU-matched to any current track).
        for det in self.detections:
            if self._det_overlaps_track(det):
                continue
            if is_background_classification(det.get("classification")):
                continue
            world.append(build_world_entry_from_detection(det, w, h))

        return world


def main() -> None:
    """Test the vision system with one screen image."""
    import cv2

    # Create the vision system.
    system = VisionSystem(save_world_json=True)

    # Load one screen image (relative to this file).
    data_folder = Path(__file__).resolve().parents[3] / "datasets" / "pipline_data"
    screen_image = cv2.imread(str(sorted(data_folder.glob("*.jpg"))[0]))

    # Run the full pipeline.
    world_state = system.process(screen_image)

    # Print the world state in the output format.
    print(json.dumps(world_state, ensure_ascii=False, indent=2))
    if system.last_world_json_path:
        print("Saved to:", system.last_world_json_path)


if __name__ == "__main__":
    main()
