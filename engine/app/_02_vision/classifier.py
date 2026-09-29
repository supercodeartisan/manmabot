"""Classifies detected objects using the trained ResNet18 model.

Pipeline position:
    Screen -> YOLO Detector -> ByteTrack Tracker -> Classifier -> World Model

Takes a TrackObject and the current screen image, crops the object,
and fills the track's ``classification`` with the model prediction.

Input:  TrackObject + OpenCV BGR screen image (crop region = track.bbox).
Output: In-place write track_object.classification =
        {class_name, class_id, confidence} plus, for multi-head models,
        {detail_class_name, detail_class_id, detail_confidence} (the other
        head's top prediction and its own confidence). Also returns
        {track_id, classification} (None for empty crops).
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms

# Reuse the training-time model definitions (two-head ResNet18).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from classify_model.model_architectures import (
    ModelFactory,
    architecture_from_state,
    remap_legacy_state_dict,
)
from classify_model.preprocess_v2 import LetterboxLongSide

# Truth for classifier weights lives HERE only — not in config.yaml.
# Flip DEFAULT_CLASSIFY_EDITION (or pass edition= / model_path=) to switch.
CLASSIFY_EDITIONS = {
    "v1": str(_PROJECT_ROOT / "app" / "models" / "1400+bestclassify+0.97.pt"),
    "v2": str(
        _PROJECT_ROOT
        / "app"
        / "models"
        / "regions"
        / "talking_island"
        / "talking_island.pt"
    ),
}
DEFAULT_CLASSIFY_EDITION = "v2"
CLASSIFY_MODEL_PATH = CLASSIFY_EDITIONS[DEFAULT_CLASSIFY_EDITION]


def resolve_classifier_path(
    edition: Optional[str] = None,
    model_path: Optional[str] = None,
) -> str:
    """Pick a classifier .pt from code only.

    Priority: explicit ``model_path`` argument, then ``edition`` argument,
    then ``DEFAULT_CLASSIFY_EDITION``. Never reads config.yaml or env vars.
    """
    if model_path:
        path = Path(str(model_path))
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return str(path)

    chosen = (edition or "").strip() or DEFAULT_CLASSIFY_EDITION
    if chosen not in CLASSIFY_EDITIONS:
        raise ValueError(
            f"Unknown classifier edition {chosen!r}. "
            f"Known: {sorted(CLASSIFY_EDITIONS)}"
        )
    path = Path(CLASSIFY_EDITIONS[chosen])
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return str(path)


class Classifier:
    """Runs the trained classification model on a tracked object."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cpu",
        edition: Optional[str] = None,
    ) -> None:
        # Path to the trained weights (.pt).
        self.model_path = resolve_classifier_path(
            edition=edition, model_path=model_path
        )
        self.device = torch.device(
            "cuda:0" if device in ("0", "cuda", "cuda:0") and torch.cuda.is_available()
            else "cpu"
        )

        # Fixed input size used during training.
        self.input_size = 224
        self.letterbox_mode = "short_side"

        # Model and class names are filled by load_model().
        self.model: Optional[nn.Module] = None
        self.class_names: List[str] = []
        self.detail_class_names: List[str] = []
        self.fine_to_level: List[Optional[int]] = []
        self.multihead = False

        # Load the weights once at construction.
        self.load_model()

    def _load_label_names(self, checkpoint: dict) -> None:
        """Load class names from the checkpoint, then JSON next to v1 weights."""
        schema = checkpoint.get("schema") if isinstance(checkpoint, dict) else None
        if isinstance(schema, dict):
            self.class_names = list(schema.get("main_classes") or [])
            self.detail_class_names = list(schema.get("fine_classes") or [])
            self.fine_to_level = list(schema.get("fine_to_level") or [])
        else:
            self.fine_to_level = []

        ckpt_names = checkpoint.get("class_names") if isinstance(checkpoint, dict) else None
        ckpt_detail = (
            checkpoint.get("detail_class_names") if isinstance(checkpoint, dict) else None
        )
        if ckpt_names and not self.class_names:
            self.class_names = list(ckpt_names)
        if ckpt_detail and not self.detail_class_names:
            self.detail_class_names = list(ckpt_detail)

        # v2 names live in the infer checkpoint. Do not fall back to v1 JSON.
        if schema:
            if not self.class_names:
                raise ValueError(f"v2 checkpoint has no class names: {self.model_path}")
            return

        names_path = Path(self.model_path).parent / "class_names.json"
        detail_names_path = Path(self.model_path).parent / "detail_class_names.json"
        if not self.class_names:
            if names_path.exists():
                with open(names_path, "r", encoding="utf-8") as handle:
                    self.class_names = json.load(handle)
            else:
                raise FileNotFoundError(
                    f"No class names in checkpoint or at {names_path}"
                )
        if not self.detail_class_names and detail_names_path.exists():
            with open(detail_names_path, "r", encoding="utf-8") as handle:
                self.detail_class_names = json.load(handle)

    def load_model(self) -> None:
        """Build the model architecture and load the trained weights."""
        model_file = Path(self.model_path)
        if not model_file.is_file():
            raise FileNotFoundError(f"Classifier weights not found: {model_file}")

        # v2 stores schema / names next to the tensors; v1 tensors still load.
        checkpoint = torch.load(self.model_path, map_location="cpu", weights_only=False)
        if not isinstance(checkpoint, dict):
            checkpoint = {"model_state_dict": checkpoint}

        self._load_label_names(checkpoint)
        self.letterbox_mode = str(checkpoint.get("letterbox") or "short_side")

        state = (
            checkpoint["model_state_dict"]
            if "model_state_dict" in checkpoint
            else checkpoint
        )
        state = remap_legacy_state_dict(state)
        model = ModelFactory.from_checkpoint(checkpoint)
        architecture = checkpoint.get("architecture") or architecture_from_state(state)
        self.multihead = architecture in (
            "resnet18_multihead",
            "resnet18_twohead_v2",
        )

        if architecture == "resnet18_twohead_v2":
            # Coarse 5-way on class_name; species on detail_*.
            self.use_main_head = True
        elif architecture == "resnet18_multihead":
            main_classes = state["main_head.fc.bias"].shape[0]
            detail_classes = state["detail_head.fc.bias"].shape[0]
            if len(self.class_names) == detail_classes:
                self.use_main_head = False
            elif len(self.class_names) == main_classes:
                self.use_main_head = True
            else:
                raise ValueError(
                    f"class_names.json has {len(self.class_names)} names but the "
                    f"model main head has {main_classes} and detail head has "
                    f"{detail_classes} outputs; cannot choose a head"
                )
        else:
            self.use_main_head = False

        model.load_state_dict(state)
        model.eval()
        self.model = model.to(self.device)

    def crop_image(self, screen_image, bbox: Dict[str, int]):
        """Crop the object region out of the screen image."""
        height, width = screen_image.shape[:2]

        # Clamp the box to the image boundaries.
        x1 = max(0, int(bbox["x1"]))
        y1 = max(0, int(bbox["y1"]))
        x2 = min(width, int(bbox["x2"]))
        y2 = min(height, int(bbox["y2"]))
        crop = screen_image[y1:y2, x1:x2]
        # Return the cropped region (BGR numpy array).
        return crop
    

    def predict(self, track_object, screen_image) -> Optional[Dict]:
        """Classify a tracked object and store the result back into it."""
        # Skip tracks that were already classified (do not run every frame).
        if track_object.classification is not None:
            return {
                "track_id": track_object.track_id,
                "classification": track_object.classification,
            }

        # Crop the object out of the screen.
        crop = self.crop_image(screen_image, track_object.bbox)

        # Ignore empty crops.
        if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
            return None

        # Prepare the crop and run inference.
        tensor = self._preprocess(crop)
        class_id, confidence, detail_id, detail_conf = self._infer(tensor)

        # Build the classification record. For multi-head models the primary
        # head matches class_names.json; the detail head's top prediction is
        # attached as detail_* fields with its own confidence.
        classification = self._make_classification(
            class_id, confidence, detail_id, detail_conf
        )

        # Store the result back into the track.
        track_object.classification = classification

        return {
            "track_id": track_object.track_id,
            "classification": classification,
        }

    def _preprocess(self, crop) -> torch.Tensor:
        """Convert a BGR crop into the model input tensor."""
        # The model was trained on RGB images.
        image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))

        if self.letterbox_mode == "long_side":
            image = LetterboxLongSide(self.input_size)(image)
        else:
            # v1: scale the shortest side, then center-pad to a square.
            width, height = image.size
            scale = self.input_size / min(width, height)
            new_width = max(1, round(width * scale))
            new_height = max(1, round(height * scale))
            image = transforms.functional.resize(image, (new_height, new_width))
            pad_left = (self.input_size - new_width) // 2
            pad_top = (self.input_size - new_height) // 2
            pad_right = self.input_size - new_width - pad_left
            pad_bottom = self.input_size - new_height - pad_top
            image = transforms.functional.pad(
                image, (pad_left, pad_top, pad_right, pad_bottom), fill=0.0
            )

        # Same [0,1] tensor format used during training.
        return transforms.ToTensor()(image)

    @torch.no_grad()
    def _infer(self, tensor: torch.Tensor):
        """Run the model on one image tensor and return its result tuple."""
        return self._infer_batch(tensor.unsqueeze(0))[0]

    @torch.no_grad()
    def _infer_batch(self, tensor: torch.Tensor):
        """Run the model on a batch (B, 3, 224, 224) in one forward pass.

        Returns a list with one tuple per sample:
        (class_id, confidence, detail_id, detail_confidence). For multi-head
        models the primary result comes from the head that matches
        class_names.json (see load_model / use_main_head); the other head's
        top prediction is returned as the detail_* values. Single-head models
        return detail_id=None, detail_confidence=None.
        """
        outputs = self.model(tensor)

        if not self.multihead:
            probs = torch.softmax(outputs, dim=1)
            ids = probs.argmax(1).tolist()
            confs = probs[range(probs.size(0)), ids].tolist()
            return [(int(id_), float(conf), None, None)
                    for id_, conf in zip(ids, confs)]

        # Two-head model: main_out (coarse) + detail_out (fine).
        main_out, detail_out = outputs
        main_probs = torch.softmax(main_out, dim=1)
        detail_probs = torch.softmax(detail_out, dim=1)
        main_ids = main_probs.argmax(1).tolist()
        detail_ids = detail_probs.argmax(1).tolist()
        main_confs = main_probs[range(main_probs.size(0)), main_ids].tolist()
        detail_confs = detail_probs[range(detail_probs.size(0)), detail_ids].tolist()

        results = []
        for i in range(tensor.size(0)):
            if self.use_main_head:
                results.append((main_ids[i], main_confs[i],
                                detail_ids[i], detail_confs[i]))
            else:
                results.append((detail_ids[i], detail_confs[i],
                                main_ids[i], main_confs[i]))
        return results

    def _make_classification(self, class_id, confidence, detail_id, detail_conf) -> Dict:
        """Build the classification record from one inference result."""
        classification = {
            "class_name": self.class_names[class_id],
            "class_id": int(class_id),
            "confidence": confidence,
        }
        if self.multihead and detail_id is not None:
            detail_name = None
            if detail_id < len(self.detail_class_names):
                detail_name = self.detail_class_names[detail_id]
            classification["detail_class_name"] = detail_name
            classification["detail_class_id"] = int(detail_id)
            classification["detail_confidence"] = detail_conf
            if detail_id < len(self.fine_to_level):
                level = self.fine_to_level[detail_id]
                if level is not None:
                    classification["monster_level"] = int(level)
        return classification

    def predict_batch(self, track_objects, screen_image) -> None:
        """Classify many tracked objects in ONE batched forward pass."""
        if not track_objects:
            return

        # Preprocess every valid crop; remember which track each slot belongs to.
        crops = []
        valid = []
        for i, track in enumerate(track_objects):
            crop = self.crop_image(screen_image, track.bbox)
            if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
                continue
            crops.append(self._preprocess(crop))
            valid.append(i)

        if not crops:
            return

        # Single batched inference for all crops.
        batch = torch.stack(crops).to(self.device, non_blocking=False)
        results = self._infer_batch(batch)

        # Write the classification back into the matching track.
        for slot, track_index in enumerate(valid):
            track_objects[track_index].classification = self._make_classification(
                *results[slot]
            )


def main() -> None:
    """Test model loading and a single prediction."""
    from vision_system import TrackObject

    print("Model path:", resolve_classifier_path())

    # Load the model.
    classifier = Classifier()
    print("Classes:", classifier.class_names)

    # Load one screen frame for the test.
    data_dir = Path(__file__).resolve().parents[3] / "datasets" / "pipline_data"
    frame_path = sorted(data_dir.glob("*.jpg"))[0]
    screen_image = cv2.imread(str(frame_path))
    height, width = screen_image.shape[:2]

    # Build a fake tracked object with a box in the middle of the frame.
    box_x1 = width // 2 - 100
    box_x2 = width // 2 + 50
    box_y1 = height // 2 - 60
    box_y2 = height // 2 + 60
    detection = {
        "class_id": 4,
        "label": "Monster",
        "confidence": 0.93,
        "bbox": {"x1": box_x1, "y1": box_y1, "x2": box_x2, "y2": box_y2},
        "center": {"x": (box_x1 + box_x2) / 2, "y": (box_y1 + box_y2) / 2},
        "width": box_x2 - box_x1,
        "height": box_y2 - box_y1,
        "area": (box_x2 - box_x1) * (box_y2 - box_y1),
    }
    track = TrackObject(track_id=15, detection=detection, frame_id=1)

    # Run one prediction.
    result = classifier.predict(track, screen_image)

    # Print the output format and result.
    print("=== Output Format ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("=== TrackObject updated ===")
    print(json.dumps(track.classification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
