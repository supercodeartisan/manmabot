"""Pair a bot perception frame with the realtime_monitor player world coord."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from paths import OUTPUT_DIR


def player_world_from_snapshot(snapshot: dict[str, Any] | None) -> Optional[dict[str, Any]]:
    """Extract raw LC world coordinates from a monitor snapshot."""
    raw = (snapshot or {}).get("player") or {}
    pos = raw.get("pos")
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        return None
    try:
        gx, gy = int(pos[0]), int(pos[1])
    except (TypeError, ValueError):
        return None
    if gx == 0 and gy == 0:
        return None
    world: dict[str, Any] = {"x": gx, "y": gy}
    if len(pos) >= 3:
        try:
            world["z"] = int(pos[2])
        except (TypeError, ValueError):
            pass
    zone = raw.get("zone")
    if zone:
        world["zone"] = str(zone)
    return world


def format_world(world: Optional[dict[str, Any]]) -> str:
    if not world:
        return "no coord"
    text = f"{world['x']}, {world['y']}"
    if "z" in world:
        text += f", {world['z']}"
    zone = world.get("zone")
    if zone:
        text += f"  {zone}"
    return text


def annotate_frame(frame: np.ndarray, world: Optional[dict[str, Any]], extra: str = "") -> np.ndarray:
    """Draw world coord on a preview copy. Saved captures stay unannotated."""
    import cv2

    canvas = frame.copy()
    label = format_world(world)
    if extra:
        label = f"{label}  {extra}"
    cv2.rectangle(canvas, (8, 8), (min(canvas.shape[1] - 8, 8 + 14 * len(label)), 42), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        label,
        (14, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return canvas


def save_png(path: Path, frame: np.ndarray) -> None:
    import cv2

    # Compression 1 is lossless and much faster than the default (3).
    ok, buf = cv2.imencode(
        ".png",
        frame,
        [int(cv2.IMWRITE_PNG_COMPRESSION), 1],
    )
    if not ok:
        raise RuntimeError(f"png encode failed: {path.name}")
    buf.tofile(str(path))


@dataclass
class CaptureRecord:
    index: int
    stamp: str
    png_path: Path
    json_path: Path
    world: Optional[dict[str, Any]]
    ok: bool
    error: str = ""


class CaptureSession:
    """One recording run: numbered PNG + JSON pairs under a session folder."""

    def __init__(self, output_dir: Path | None = None, mode: str = "space", fps: float = 2.0) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = Path(output_dir) if output_dir is not None else OUTPUT_DIR
        self.dir = root / f"session_{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.jsonl"
        self.mode = mode
        self.fps = float(fps)
        self.index = 0
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def save_pair(
        self,
        frame: np.ndarray,
        snapshot: dict[str, Any] | None,
        *,
        world: Optional[dict[str, Any]],
        elapsed_ms: float,
        error: str = "",
    ) -> CaptureRecord:
        self.index += 1
        now = datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        if world:
            stem = f"{self.index:05d}_{stamp}_x{world['x']}_y{world['y']}"
        else:
            stem = f"{self.index:05d}_{stamp}_nocoord"
        png_path = self.dir / f"{stem}.png"
        json_path = self.dir / f"{stem}.json"
        save_png(png_path, frame)
        h, w = frame.shape[:2]
        payload = {
            "index": self.index,
            "saved_at": now.isoformat(timespec="milliseconds"),
            "unix_time": time.time(),
            "mode": self.mode,
            "fps": self.fps if self.mode == "fps" else None,
            "ok": bool(world) and not error,
            "error": error,
            "elapsed_ms": round(float(elapsed_ms), 2),
            "frame_size": [int(w), int(h)],
            "world": world,
            "image": png_path.name,
            "monitor": {
                "frame": None if snapshot is None else snapshot.get("frame"),
                "ts": None if snapshot is None else snapshot.get("ts"),
                "player": None if snapshot is None else (snapshot.get("player") or {}),
            },
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        with self.manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return CaptureRecord(
            index=self.index,
            stamp=stamp,
            png_path=png_path,
            json_path=json_path,
            world=world,
            ok=bool(world) and not error,
            error=error,
        )
