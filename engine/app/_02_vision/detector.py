"""Detects game objects in a screen image using a 1-class YOLO model.

YOLO only answers object vs background. Type names (Player/Monster/...)
come from ResNet in VisionSystem, not from this detector.

Pipeline position:
    Screen -> YOLO Detector -> ByteTrack Tracker -> Classifier -> World Model

Input:  OpenCV BGR image (numpy array).
Output: List of detection dicts in pixel coordinates:
        {class_id, label, confidence, bbox{x1,y1,x2,y2},
         center{x,y}, width, height, area}.
        class_id is always 0 and label is always "object".
"""
from pathlib import Path
from typing import List, Dict, Any

import cv2
import numpy as np
from ultralytics import YOLO

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "960+1400+1_label.pt"
# YOLO weights path is hardcoded above — not read from config.yaml.
OBJECT_LABEL = "object"
OBJECT_CLASS_ID = 0


def resolve_device(device: str = "auto") -> str:
    """Return a YOLO/torch device string ('cpu', '0', 'cuda:0', ...)."""
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "0"
    except ImportError:
        pass
    return "cpu"


class Detector:
    """Detects game objects in a screen image using the trained YOLO model."""

    def __init__(
        self,
        model_path: str = str(MODEL_PATH),
        conf: float = 0.1,
        iou: float = 0.7,
        device: str = "cpu",
        imgsz: int = 960,
    ) -> None:
        model_file = Path(model_path)
        if not model_file.is_file():
            raise FileNotFoundError(f"YOLO weights not found: {model_file}")

        # Load the trained YOLO model once at construction.
        self.model = YOLO(str(model_file))
        try:
            self.model.fuse()
        except Exception:
            pass

        # Confidence threshold: lower values detect more objects.
        self.conf = conf

        # NMS IoU: lower values suppress more overlapping boxes.
        # Higher values keep more overlapping boxes (does not merge parts).
        self.iou = iou
        self.agnostic_nms = True

        # Device for inference: "cpu", "0", or "cuda:0".
        self.device = device
        self.use_half = device not in ("cpu", "auto") and str(device).startswith(
            ("0", "cuda")
        )

        # Must match training size for 960best.pt (default was ultralytics 640).
        self.imgsz = imgsz

        # 1-class detector: names in the checkpoint may still be leftover
        # 5-class strings (e.g. names[0] == "Win"). Never use them.
        self.names = {OBJECT_CLASS_ID: OBJECT_LABEL}

    def detect(
        self, image: np.ndarray, conf: float = None
    ) -> List[Dict[str, Any]]:
        """Run YOLO inference on the input image and return parsed detections."""
        infer_conf = self.conf if conf is None else conf
        kwargs = dict(
            conf=infer_conf,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
            augment=False,
            max_det=100,
            agnostic_nms=self.agnostic_nms,
        )
        if self.use_half:
            kwargs["half"] = True
        results = self.model(image, **kwargs)
        # Parse the first (and only) result into the pipeline data format.
        return self.parse_results(results[0])

    def warmup(self, image: np.ndarray) -> None:
        """Prime YOLO weights/kernels (first real frame is faster)."""
        self.detect(image, conf=min(self.conf, 0.01))
        
    def parse_results(self, result) -> List[Dict[str, Any]]:
        """Convert YOLO output into a clean list of detection dictionaries."""
        detections = []

        # No boxes means nothing was found.
        if result.boxes is None:
            return detections

        # Extract tensors once to avoid repeated GPU/CPU transfers.
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()

        for box, conf in zip(boxes, confs):
            # Convert box coordinates to integers.
            x1 = int(box[0])
            y1 = int(box[1])
            x2 = int(box[2])
            y2 = int(box[3])

            # Calculate width and height of the bounding box.
            width = x2 - x1
            height = y2 - y1

            # Calculate the center point of the bounding box.
            center_x = (x1 + x2) / 2.0
            center_y = (y1 + y2) / 2.0

            # 1-class model: ignore checkpoint class names (often still "Win").
            detections.append({
                "class_id": OBJECT_CLASS_ID,
                "label": OBJECT_LABEL,
                "confidence": float(conf),
                "bbox": {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                },
                "center": {
                    "x": center_x,
                    "y": center_y,
                },
                "width": width,
                "height": height,
                "area": width * height,
            })

        return detections

    def draw_detection(self, image: np.ndarray, detections: List[Dict[str, Any]]) -> np.ndarray:
        """Draw bounding boxes and labels on the image and return the annotated image."""
        annotated = image.copy()

        for det in detections:
            # Read the bounding box coordinates.
            bbox = det["bbox"]
            x1 = bbox["x1"]
            y1 = bbox["y1"]
            x2 = bbox["x2"]
            y2 = bbox["y2"]

            # Read the label and confidence.
            label = det["label"]
            confidence = det["confidence"]

            # Build the text shown above the box.
            text = f"{label} {confidence:.2f}"

            # Draw the bounding box rectangle.
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Draw the label text above the box.
            cv2.putText(annotated, text, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        return annotated


if __name__ == "__main__":
    # Test code: detect objects in one sample image and save the annotated result.
    import os
    import time

    # Build the sample image path relative to this file (no config.yaml).
    sample_dir = Path(__file__).resolve().parents[3] / "datasets" / "data_2" / "images"
    sample_name = os.listdir(sample_dir)[0]
    sample_path = os.path.join(sample_dir, sample_name)

    # Load the sample image as a numpy array.
    sample_image = cv2.imread(sample_path)

    if sample_image is None:
        print("Sample image not found:", sample_path)
    else:
        # Create the detector.
        detector = Detector()

        # Run detection on the sample image.
        detections = detector.detect(sample_image)

        # Print every detection.
        for detection in detections:
            print(detection)

        # Print a short summary.
    """    print(f"Detected {len(detections)} objects")

        # Benchmark inference speed with a fixed number of runs.
        runs = 10
        start = time.time()
        for _ in range(runs):
            detector.detect(sample_image)
        elapsed = time.time() - start
        avg_ms = elapsed * 1000 / runs
        fps = runs / elapsed
        print(f"Benchmark: {runs} runs in {elapsed:.2f}s")
        print(f"Average inference: {avg_ms:.1f} ms per image ({fps:.1f} FPS)")

        # Draw the detections on the image.
        annotated_image = detector.draw_detection(sample_image, detections)

        # Save the annotated image next to the detector module.
        output_path = Path(__file__).resolve().parent / "detector_result.png"
        cv2.imwrite(str(output_path), annotated_image)
        print("Saved annotated image to:", output_path)
    """
