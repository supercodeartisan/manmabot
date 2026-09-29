"""Dump VisionSystem frames so _03_world can iterate without GPU or vision code.

The World owner should only read ``objects`` from each JSON. That list is the
same dicts ``vision_to_perception`` already accepts (v1 class names and
monster_XX-YY bands). Vision keeps species names on the overlay, not in this
list.

    python app/_02_vision/export_for_world.py --images D:\\path\\to\\frames
    python app/_02_vision/export_for_world.py --images D:\\path\\to\\frames --out D:\\Works\\manma\\results\\vision_for_world --limit 20

Output layout:

    <out>/<timestamp>/
        manifest.json
        frames/frame_000001.json     # envelope; World uses ['objects']
        overlay/frame_000001.jpg     # annotated picture, optional
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

import cv2

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from for_world_model import (
    DEFAULT_HANDOFF_ROOT,
    HANDOFF_SCHEMA,
    save_handoff_json,
)
from test_vision import annotate_frame, load_image_paths
from vision_system import VisionSystem

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def write_manifest(run_dir: Path, rows: List[dict], extra: dict) -> Path:
    path = run_dir / "manifest.json"
    payload = {
        "schema": HANDOFF_SCHEMA,
        "run_dir": str(run_dir),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "frame_count": len(rows),
        "how_world_loads": (
            "for path in frames/*.json: "
            "objects = json.load(open(path, encoding='utf-8'))['objects']; "
            "GameState.update_from_vision(objects)"
        ),
        "frames": rows,
        **extra,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def export_images(
    image_dir: Path,
    out_root: Path,
    *,
    limit: Optional[int] = None,
    save_overlay: bool = True,
    vision_kwargs: Optional[dict] = None,
) -> Path:
    paths = load_image_paths(image_dir)
    if not paths:
        raise FileNotFoundError(f"No images in {image_dir}")
    if limit is not None:
        paths = paths[: max(0, limit)]

    run_dir = out_root / time.strftime("%Y%m%d_%H%M%S")
    frames_dir = run_dir / "frames"
    overlay_dir = run_dir / "overlay"
    frames_dir.mkdir(parents=True, exist_ok=True)
    if save_overlay:
        overlay_dir.mkdir(parents=True, exist_ok=True)

    params = dict(vision_kwargs or {})
    params["save_world_json"] = False
    system = VisionSystem(**params)

    rows: List[dict] = []
    for index, image_path in enumerate(paths, start=1):
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"skip unreadable: {image_path}")
            continue
        height, width = frame.shape[:2]
        world = system.process(frame)
        json_path = save_handoff_json(
            world,
            frames_dir,
            f"frame_{index:06d}.json",
            source_image=image_path,
            frame_index=index,
            image_width=width,
            image_height=height,
        )
        overlay_name = None
        if save_overlay:
            annotated, _, _, _ = annotate_frame(frame, system, width, height)
            overlay_name = f"frame_{index:06d}.jpg"
            cv2.imwrite(str(overlay_dir / overlay_name), annotated)
        rows.append({
            "frame_index": index,
            "source_image": str(image_path),
            "json": json_path.name,
            "overlay": overlay_name,
            "object_count": len(world),
            "image_width": width,
            "image_height": height,
        })
        print(f"{index:4d}/{len(paths)}  objects={len(world):3d}  {image_path.name}")

    write_manifest(
        run_dir,
        rows,
        extra={"image_dir": str(image_dir), "limit": limit},
    )
    print(f"Handoff run saved to: {run_dir}")
    return run_dir


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", required=True, help="Folder of screenshots")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_HANDOFF_ROOT),
        help="Parent folder for timestamped runs",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-overlay", action="store_true")
    args = parser.parse_args(argv)

    export_images(
        Path(args.images),
        Path(args.out),
        limit=args.limit,
        save_overlay=not args.no_overlay,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
