"""Merge YOLO part-boxes of a LARGE object (head/body/legs/shadow).

Only a boss-scale parent may swallow fragments. Two small monsters that
touch are left as two objects. Player/item/NPC/window crops are never
dropped even when they sit on the large box.
"""
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Parent must cover this much of the frame (or be this wide/tall).
LARGE_SCREEN_FRAC = 0.06
LARGE_WIDTH_FRAC = 0.22
LARGE_HEIGHT_FRAC = 0.32
# Drop child if this fraction of its area sits inside the parent.
CONTAIN_THRESH = 0.65
# Do not merge neighbors of similar size (small mob next to a boss).
MAX_AREA_RATIO = 0.5
# Attached remnant: overlap or near-touch.
ATTACH_IOU = 0.05
ATTACH_GAP_PX = 8.0


def _bbox(det: Dict) -> Dict:
    return det["bbox"]


def _area(box: Dict) -> float:
    return max(0.0, float(box["x2"] - box["x1"])) * max(
        0.0, float(box["y2"] - box["y1"])
    )


def _intersection(a: Dict, b: Dict) -> float:
    ix1 = max(float(a["x1"]), float(b["x1"]))
    iy1 = max(float(a["y1"]), float(b["y1"]))
    ix2 = min(float(a["x2"]), float(b["x2"]))
    iy2 = min(float(a["y2"]), float(b["y2"]))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def _iou(a: Dict, b: Dict) -> float:
    inter = _intersection(a, b)
    if inter <= 0:
        return 0.0
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _gap_px(a: Dict, b: Dict) -> float:
    """Distance between boxes (0 if they overlap)."""
    ax1, ay1, ax2, ay2 = float(a["x1"]), float(a["y1"]), float(a["x2"]), float(a["y2"])
    bx1, by1, bx2, by2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
    dx = max(0.0, bx1 - ax2, ax1 - bx2)
    dy = max(0.0, by1 - ay2, ay1 - by2)
    return (dx * dx + dy * dy) ** 0.5


def _center(box: Dict) -> Tuple[float, float]:
    return (
        (float(box["x1"]) + float(box["x2"])) / 2.0,
        (float(box["y1"]) + float(box["y2"])) / 2.0,
    )


def _center_projects_onto(child: Dict, parent: Dict) -> bool:
    """True if the child's center lines up with the parent on x or y."""
    cx, cy = _center(child)
    return (
        float(parent["x1"]) <= cx <= float(parent["x2"])
        or float(parent["y1"]) <= cy <= float(parent["y2"])
    )


def same_yolo_class(a: Dict, b: Dict) -> bool:
    return int(a.get("class_id", -1)) == int(b.get("class_id", -2))


PROTECTED_CHILD_CLASSES = frozenset({
    "player",
    "grounditem",
    "item",
    "npc",
    "window",
    "win",
})


def same_resnet_class(a: Dict, b: Dict) -> bool:
    ca = (a.get("part_class") or "").strip().lower()
    cb = (b.get("part_class") or "").strip().lower()
    if not ca or not cb:
        return False
    return ca == cb


def child_is_protected(child: Dict) -> bool:
    """Player/item/NPC/window overlapping a monster must not be dropped."""
    name = (child.get("part_class") or child.get("label") or "").strip().lower()
    return name in PROTECTED_CHILD_CLASSES


def is_single_yolo_class(detections: Sequence[Dict]) -> bool:
    ids = {int(d.get("class_id", -1)) for d in detections}
    return len(ids) <= 1


def is_large_parent(box: Dict, frame_w: float, frame_h: float) -> bool:
    """True if this box is boss-scale on the current screen."""
    fw, fh = float(frame_w), float(frame_h)
    if fw <= 0 or fh <= 0:
        return False
    w = max(0.0, float(box["x2"] - box["x1"]))
    h = max(0.0, float(box["y2"] - box["y1"]))
    if (w * h) / (fw * fh) >= LARGE_SCREEN_FRAC:
        return True
    return (w / fw) >= LARGE_WIDTH_FRAC or (h / fh) >= LARGE_HEIGHT_FRAC


def has_large_parent(
    detections: Sequence[Dict], frame_w: float, frame_h: float
) -> bool:
    return any(is_large_parent(_bbox(d), frame_w, frame_h) for d in detections)


def is_part_of(
    parent: Dict,
    child: Dict,
    frame_w: float,
    frame_h: float,
) -> bool:
    """True if child is a fragment of a LARGE parent (geometry only)."""
    pb, cb = _bbox(parent), _bbox(child)
    if not is_large_parent(pb, frame_w, frame_h):
        return False
    parent_area = _area(pb)
    child_area = _area(cb)
    if parent_area <= 0 or child_area <= 0:
        return False
    if child_area / parent_area > MAX_AREA_RATIO:
        return False
    contain = _intersection(pb, cb) / child_area
    if contain >= CONTAIN_THRESH:
        return True
    if (
        (_iou(pb, cb) >= ATTACH_IOU or _gap_px(pb, cb) <= ATTACH_GAP_PX)
        and _center_projects_onto(cb, pb)
    ):
        return True
    return False


def find_part_pairs(
    detections: Sequence[Dict],
    frame_w: float,
    frame_h: float,
    *,
    same_class: Optional[Callable[[Dict, Dict], bool]] = None,
) -> List[Tuple[int, int]]:
    """Return (parent_index, child_index) pairs, parent = larger box."""
    n = len(detections)
    pairs: List[Tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = detections[i], detections[j]
            if same_class is not None and not same_class(a, b):
                continue
            if _area(_bbox(a)) >= _area(_bbox(b)):
                parent_i, child_i = i, j
            else:
                parent_i, child_i = j, i
            if is_part_of(
                detections[parent_i], detections[child_i], frame_w, frame_h
            ):
                pairs.append((parent_i, child_i))
    return pairs


def merge_part_detections(
    detections: List[Dict],
    frame_w: float,
    frame_h: float,
    *,
    same_class: Optional[Callable[[Dict, Dict], bool]] = None,
) -> List[Dict]:
    """Drop fragments of a large parent. Small-vs-small is never merged.

    `same_class(a, b)` must be True to allow a merge. None = geometry only.
    """
    if len(detections) < 2:
        return detections
    if not has_large_parent(detections, frame_w, frame_h):
        return detections

    order = sorted(
        range(len(detections)),
        key=lambda i: _area(_bbox(detections[i])),
        reverse=True,
    )
    kept: List[int] = []
    for i in order:
        child = detections[i]
        if child_is_protected(child):
            kept.append(i)
            continue
        drop = False
        for j in kept:
            parent = detections[j]
            if same_class is not None and not same_class(parent, child):
                continue
            if is_part_of(parent, child, frame_w, frame_h):
                drop = True
                break
        if not drop:
            kept.append(i)
    return [detections[i] for i in kept]
