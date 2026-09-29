"""
tracker_pipeline.py

A thin wrapper around the ByteTrack files you uploaded
(byte_tracker.py, kalman_filter.py, matching.py, basetrack.py)
so you can feed it raw YOLO output in (x, y, w, h, conf) format
and get back tracked objects with stable IDs, frame by frame.

Directory layout expected (so the relative imports in byte_tracker.py work):

    your_project/
        yolox/
            __init__.py
            tracker/
                __init__.py
                byte_tracker.py
                kalman_filter.py
                matching.py
                basetrack.py
        tracker_pipeline.py   <-- this file
        run_demo.py           <-- your own script

byte_tracker.py does:
    from .kalman_filter import KalmanFilter
    from yolox.tracker import matching
    from .basetrack import BaseTrack, TrackState

So it must live inside a package literally called "yolox.tracker".
Two empty __init__.py files (in yolox/ and yolox/tracker/) are enough.
"""

import os
import sys
import numpy as np

# Make sure this folder (which holds the tracker/ package) is importable
# no matter where or how this script is launched.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ByteTrack (BYTETracker / STrack) is imported lazily inside SimpleTracker
# so DetectionTracker (default) works without lap / cython_bbox.


def _tlwh_iou(a, b) -> float:
    """IoU between two (x, y, w, h) top-left boxes."""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class DetectionTracker:
    """Match YOLO detections frame-to-frame (no Kalman).

    Designed for games where the player stays screen-centered and the world
    scrolls: IDs are assigned by IoU + camera-shifted center matching, not
    by motion prediction. Each visible detection gets exactly one track_id.
    """

    def __init__(
        self,
        frame_height,
        frame_width,
        track_buffer: int = 3,
        iou_thresh: float = 0.2,
        max_center_dist: float = 160.0,
    ):
        self.frame_height = frame_height
        self.frame_width = frame_width
        self.track_buffer = max(1, int(track_buffer))
        self.iou_thresh = float(iou_thresh)
        self.max_center_dist = float(max_center_dist)
        self.frame_id = 0
        self.next_id = 1
        # track_id -> slot dict
        self.slots: dict = {}
        self.last_ego_motion = (0.0, 0.0)

    def apply_ego_motion(self, dx: float, dy: float) -> None:
        """No-op for API compatibility with SimpleTracker."""
        self.last_ego_motion = (float(dx), float(dy))

    @staticmethod
    def _det_tlwh(det) -> tuple:
        box = det["bbox"]
        return (
            float(box["x1"]),
            float(box["y1"]),
            float(box["x2"] - box["x1"]),
            float(box["y2"] - box["y1"]),
        )

    @staticmethod
    def _det_center(det) -> tuple:
        c = det["center"]
        return (float(c["x"]), float(c["y"]))

    def _greedy_iou_match(self, prev_ids, curr_indices, detections, thresh):
        pairs = []
        for pid in prev_ids:
            slot = self.slots[pid]
            for di in curr_indices:
                iou = _tlwh_iou(slot["tlwh"], self._det_tlwh(detections[di]))
                if iou >= thresh:
                    pairs.append((iou, pid, di))
        if not pairs:
            return [], prev_ids, curr_indices

        best_prev = {}
        best_curr = {}
        for iou, pid, di in pairs:
            if pid not in best_prev or iou > best_prev[pid][0]:
                best_prev[pid] = (iou, di)
            if di not in best_curr or iou > best_curr[di][0]:
                best_curr[di] = (iou, pid)

        mutual = []
        for pid, (iou, di) in best_prev.items():
            if best_curr.get(di) == (iou, pid):
                mutual.append((iou, pid, di))
        mutual.sort(reverse=True)

        matched = []
        used_prev, used_curr = set(), set()
        for iou, pid, di in mutual:
            if pid in used_prev or di in used_curr:
                continue
            used_prev.add(pid)
            used_curr.add(di)
            matched.append((pid, di, iou))
        u_prev = [p for p in prev_ids if p not in used_prev]
        u_curr = [d for d in curr_indices if d not in used_curr]
        return matched, u_prev, u_curr

    @staticmethod
    def _scene_is_crowded(detections) -> bool:
        """Nearby / overlapping boxes — do not merge identities loosely."""
        n = len(detections)
        if n < 2:
            return False
        for i in range(n):
            for j in range(i + 1, n):
                a, b = detections[i], detections[j]
                ba, bb = a["bbox"], b["bbox"]
                ix1 = max(ba["x1"], bb["x1"])
                iy1 = max(ba["y1"], bb["y1"])
                ix2 = min(ba["x2"], bb["x2"])
                iy2 = min(ba["y2"], bb["y2"])
                iou = 0.0
                if ix2 > ix1 and iy2 > iy1:
                    inter = (ix2 - ix1) * (iy2 - iy1)
                    area_a = (ba["x2"] - ba["x1"]) * (ba["y2"] - ba["y1"])
                    area_b = (bb["x2"] - bb["x1"]) * (bb["y2"] - bb["y1"])
                    union = area_a + area_b - inter
                    iou = inter / union if union > 0 else 0.0
                if a["class_id"] != b["class_id"] and iou >= 0.12:
                    return True
                ca = a["center"]
                cb = b["center"]
                dist = ((ca["x"] - cb["x"]) ** 2 + (ca["y"] - cb["y"]) ** 2) ** 0.5
                if dist < 90:
                    return True
        return False

    def _greedy_center_match(self, prev_ids, curr_indices, detections, ego):
        ego_dx, ego_dy = ego
        pairs = []
        for pid in prev_ids:
            slot = self.slots[pid]
            px = slot["center"][0] + ego_dx
            py = slot["center"][1] + ego_dy
            for di in curr_indices:
                cx, cy = self._det_center(detections[di])
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if dist <= self.max_center_dist:
                    pairs.append((dist, pid, di))
        pairs.sort()
        matched = []
        used_prev, used_curr = set(), set()
        for dist, pid, di in pairs:
            if pid in used_prev or di in used_curr:
                continue
            used_prev.add(pid)
            used_curr.add(di)
            matched.append((pid, di))
        u_prev = [p for p in prev_ids if p not in used_prev]
        u_curr = [d for d in curr_indices if d not in used_curr]
        return matched, u_prev, u_curr

    def update_with_occlusion(self, detections, crowded: bool = False):
        """Assign stable track_ids to this frame's YOLO detections.

        detections: list of detection dicts from the vision pipeline.
        crowded: when True, use strict IoU-only matching (no loose center match).
        Returns {"visible": [...], "occluded": [...]} like SimpleTracker.
        Each visible entry includes det_index into ``detections``.
        """
        self.frame_id += 1
        detections = list(detections)
        n = len(detections)
        crowded = crowded or self._scene_is_crowded(detections)
        iou_thresh = max(self.iou_thresh, 0.35) if crowded else self.iou_thresh

        # Slots that were visible last frame (candidates for re-association).
        prev_visible = [
            tid for tid, s in self.slots.items() if s["frames_lost"] == 0
        ]
        # Also try to re-acquire recently lost tracks within the buffer.
        prev_lost = [
            tid for tid, s in self.slots.items()
            if 0 < s["frames_lost"] <= self.track_buffer
        ]
        prev_ids = prev_visible + prev_lost
        curr_indices = list(range(n))

        matched_pairs = []  # (track_id, det_index)

        if prev_ids and curr_indices:
            iou_matches, u_prev, u_curr = self._greedy_iou_match(
                prev_ids, curr_indices, detections, iou_thresh
            )
            for pid, di, _ in iou_matches:
                matched_pairs.append((pid, di))

            # Camera scroll estimate from confident overlaps only.
            ego = (0.0, 0.0)
            if len(iou_matches) >= 2:
                deltas = []
                for pid, di, iou in iou_matches:
                    if iou < 0.25:
                        continue
                    slot = self.slots[pid]
                    cx, cy = self._det_center(detections[di])
                    deltas.append((
                        cx - slot["center"][0],
                        cy - slot["center"][1],
                    ))
                if len(deltas) >= 2:
                    ego = (
                        float(np.median([d[0] for d in deltas])),
                        float(np.median([d[1] for d in deltas])),
                    )
            self.last_ego_motion = ego

            if u_prev and u_curr and not crowded:
                center_matches, u_prev, u_curr = self._greedy_center_match(
                    u_prev, u_curr, detections, ego
                )
                matched_pairs.extend(center_matches)
            elif u_prev and u_curr and crowded:
                # Crowded scene: never loose-match by center — new ids instead.
                pass

            # New identities for unmatched detections.
            for di in u_curr:
                tid = self.next_id
                self.next_id += 1
                matched_pairs.append((tid, di))

            matched_prev = {pid for pid, _ in matched_pairs}
            for pid in prev_ids:
                if pid not in matched_prev:
                    self.slots[pid]["frames_lost"] += 1
        elif curr_indices:
            # First frame or no prior tracks: every det is new.
            self.last_ego_motion = (0.0, 0.0)
            for di in curr_indices:
                tid = self.next_id
                self.next_id += 1
                matched_pairs.append((tid, di))
        else:
            self.last_ego_motion = (0.0, 0.0)
            for tid in list(self.slots.keys()):
                self.slots[tid]["frames_lost"] += 1

        visible = []
        for tid, di in matched_pairs:
            det = detections[di]
            tlwh = self._det_tlwh(det)
            center = self._det_center(det)
            self.slots[tid] = {
                "class_id": det["class_id"],
                "tlwh": tlwh,
                "center": center,
                "score": float(det["confidence"]),
                "frames_lost": 0,
                "last_frame": self.frame_id,
            }
            visible.append({
                "track_id": tid,
                "tlwh": tlwh,
                "score": float(det["confidence"]),
                "det_index": di,
            })

        # Drop slots lost for too long.
        stale = [
            tid for tid, s in self.slots.items()
            if s["frames_lost"] > self.track_buffer
        ]
        for tid in stale:
            del self.slots[tid]

        occluded = []
        for tid, slot in self.slots.items():
            if slot["frames_lost"] <= 0 or slot["frames_lost"] > self.track_buffer:
                continue
            occluded.append({
                "track_id": tid,
                "tlwh": slot["tlwh"],
                "score": slot["score"],
                "frames_lost": slot["frames_lost"],
            })

        return {"visible": visible, "occluded": occluded}


class TrackerArgs:
    """Container for the knobs BYTETracker reads off self.args."""
    def __init__(self, track_thresh=0.5, track_buffer=3,
                 match_thresh=0.8, mot20=False,
                 low_thresh=0.1, second_match_thresh=0.5,
                 unconfirmed_match_thresh=0.7):
        self.track_thresh = track_thresh             # high-score cutoff
        self.track_buffer = track_buffer             # frames a lost track survives
        self.match_thresh = match_thresh             # IoU threshold, 1st association
        self.mot20 = mot20                           # disables score fusion if True
        self.low_thresh = low_thresh                 # score floor, 2nd association
        self.second_match_thresh = second_match_thresh  # IoU, 2nd association
        self.unconfirmed_match_thresh = unconfirmed_match_thresh  # IoU, unconfirmed


class SimpleTracker:
    """
    Wraps BYTETracker so you can pass YOLO's native (x, y, w, h, conf)
    format directly, instead of the x1y1x2y2 format byte_tracker.py
    expects internally.
    """

    def __init__(self, frame_height, frame_width, frame_rate=30,
                 track_thresh=0.5, track_buffer=3, match_thresh=0.8,
                 mot20=False, low_thresh=0.1, second_match_thresh=0.5,
                 unconfirmed_match_thresh=0.7):
        # Lazy: only ByteTrack needs lap / cython_bbox.
        from tracker.byte_tracker import BYTETracker

        args = TrackerArgs(
            track_thresh, track_buffer, match_thresh, mot20,
            low_thresh, second_match_thresh, unconfirmed_match_thresh,
        )
        self.tracker = BYTETracker(args, frame_rate=frame_rate)
        # If your detections are already in original-image pixel coords
        # (no letterbox/resize before YOLO), keep img_info == img_size.
        self.img_info = (frame_height, frame_width)
        self.img_size = (frame_height, frame_width)
        # Last applied camera ego-motion (pixels); set by apply_ego_motion.
        self.last_ego_motion = (0.0, 0.0)

    def apply_ego_motion(self, dx: float, dy: float) -> None:
        """Shift all Kalman track states by the estimated camera motion.

        Call this BEFORE update() when the character is screen-centered and
        the camera scrolls with the player. dx/dy are the median on-screen
        displacement of matched detections (current - previous). Stationary
        world objects then stay still in the tracker's coordinate frame.
        """
        self.last_ego_motion = (float(dx), float(dy))
        if dx == 0.0 and dy == 0.0:
            return

        tracks = list(self.tracker.tracked_stracks) + list(self.tracker.lost_stracks)
        for track in tracks:
            if track.mean is not None:
                mean = track.mean.copy()
                # xyah center position
                mean[0] += dx
                mean[1] += dy
                # Strip ego component from velocity so predict() does not
                # re-apply camera scroll as object motion.
                mean[4] -= dx
                mean[5] -= dy
                track.mean = mean
            else:
                tlwh = np.asarray(track._tlwh, dtype=np.float64).copy()
                tlwh[0] += dx
                tlwh[1] += dy
                track._tlwh = tlwh

    @staticmethod
    def _xywh_conf_to_x1y1x2y2_conf(dets_xywh_conf):
        """
        dets_xywh_conf: np.ndarray, shape (N, 5) -> (x, y, w, h, conf)
        (x, y) is assumed to be the TOP-LEFT corner, matching typical
        YOLO box output. If your (x, y) is the box CENTER instead,
        adjust the two lines below accordingly.
        """
        dets = np.asarray(dets_xywh_conf, dtype=np.float64).copy()
        if dets.shape[0] == 0:
            return dets.reshape(0, 5)
        x1 = dets[:, 0]
        y1 = dets[:, 1]
        x2 = dets[:, 0] + dets[:, 2]
        y2 = dets[:, 1] + dets[:, 3]
        conf = dets[:, 4]
        return np.stack([x1, y1, x2, y2, conf], axis=1)

    def update(self, yolo_dets):
        """
        yolo_dets: np.ndarray or list, shape (N, 5) = (x, y, w, h, conf)
                   x, y = top-left corner. Pass an empty array/list if
                   YOLO found nothing this frame.

        Returns: list of dicts, one per currently active track:
            {
              "track_id": int,
              "tlwh": (x, y, w, h),   # top-left, w, h  -- CURRENT box
              "score": float,
            }
        """
        dets_xyxy_conf = self._xywh_conf_to_x1y1x2y2_conf(np.asarray(yolo_dets))

        if dets_xyxy_conf.shape[0] == 0:
            # BYTETracker.update indexes output_results[:, 4] etc, so it
            # needs the right shape even when there are 0 detections.
            dets_xyxy_conf = np.zeros((0, 5), dtype=np.float64)

        online_targets = self.tracker.update(
            dets_xyxy_conf, self.img_info, self.img_size
        )

        results = []
        for t in online_targets:
            results.append({
                "track_id": t.track_id,
                "tlwh": tuple(t.tlwh),   # (x, y, w, h) -- current estimate
                "score": t.score,
            })
        return results

    def get_occluded_tracks(self):
        """
        Returns tracks that are currently NOT matched to any detection
        (e.g. hidden behind a tree) but are still being extrapolated by
        the Kalman filter and haven't exceeded track_buffer yet.

        These are NOT included in update()'s return value, since
        BYTETracker only reports actively-matched tracks. Call this
        right after update() if you want "last known / predicted"
        positions for objects currently out of sight.

        Returns: list of dicts like update(), plus:
            "frames_lost": int  -- how many frames since last seen
        """
        results = []
        for t in self.tracker.lost_stracks:
            results.append({
                "track_id": t.track_id,
                "tlwh": tuple(t.tlwh),
                "score": t.score,
                "frames_lost": self.tracker.frame_id - t.end_frame,
            })
        return results

    def update_with_occlusion(self, yolo_dets):
        """
        Convenience wrapper: calls update() then attaches currently
        occluded tracks too. Use this as your main per-frame call for
        a "don't lose the object behind the tree" use case.

        Returns: {"visible": [...], "occluded": [...]}
        each list has the same dict shape as update()'s return value
        ("occluded" additionally has "frames_lost").
        """
        visible = self.update(yolo_dets)
        occluded = self.get_occluded_tracks()
        return {"visible": visible, "occluded": occluded}

    def predict_next(self):
        """
        Advances every currently tracked object one step forward using
        ONLY the Kalman motion model (no new detection yet). Useful when
        you want "where will this object be at t+1" BEFORE you've run
        YOLO on the next frame -- e.g. to pre-crop a search region.

        NOTE: this mutates the tracker's internal state (mean/covariance),
        same as the predict step inside update(). Call update() with the
        real next-frame detections afterwards as usual; it will run its
        own predict + correct internally, so don't treat this as "free" --
        it's meant for read-only look-ahead use cases.
        """
        active = [t for t in self.tracker.tracked_stracks if t.is_activated]
        from tracker.byte_tracker import STrack

        STrack.multi_predict(active)
        return [
            {"track_id": t.track_id, "tlwh": tuple(t.tlwh), "score": t.score}
            for t in active
        ]


if __name__ == "__main__":
    # ---- minimal runnable demo with fake YOLO output ----
    # Replace this loop with: for frame in video: dets = yolo(frame)
    H, W = 720, 1280
    tracker = SimpleTracker(frame_height=H, frame_width=W, frame_rate=30)

    fake_yolo_frames = [
        np.array([[100, 200, 50, 80, 0.91]]),   # frame 1: one object
        np.array([[104, 202, 50, 80, 0.89]]),   # frame 2: moved slightly
        np.array([[108, 205, 50, 80, 0.85]]),   # frame 3
    ]

    for i, dets in enumerate(fake_yolo_frames, start=1):
        result = tracker.update_with_occlusion(dets)
        print(f"frame {i}:")
        for tr in result["visible"]:
            x, y, w, h = tr["tlwh"]
            print(f"  VISIBLE id={tr['track_id']}  box=({x:.1f},{y:.1f},{w:.1f},{h:.1f})"
                  f"  score={tr['score']:.2f}")
        for tr in result["occluded"]:
            x, y, w, h = tr["tlwh"]
            print(f"  OCCLUDED id={tr['track_id']}  predicted box=({x:.1f},{y:.1f},{w:.1f},{h:.1f})"
                  f"  frames_lost={tr['frames_lost']}")

    # Look ahead one more step with no new detection yet:
    next_guess = tracker.predict_next()
    print("predicted next-frame positions (motion model only):")
    for tr in next_guess:
        x, y, w, h = tr["tlwh"]
        print(f"  id={tr['track_id']}  predicted box=({x:.1f},{y:.1f},{w:.1f},{h:.1f})")