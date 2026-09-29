import os
import yaml
from tqdm import tqdm
from pathlib import Path
import cv2
import numpy as np


def _is_path_key(key):
    if not isinstance(key, str):
        return False
    if key.endswith(("folder", "path", "input", "output", "dir", "_file")):
        return True
    return key in ("terrain_map", "image_path", "weight_folder", "home_file")


def _resolve_config_paths(config, base_dir):
    if isinstance(config, dict):
        for key, value in config.items():
            if _is_path_key(key) and isinstance(value, str):
                if not os.path.isabs(value):
                    config[key] = os.path.normpath(os.path.join(base_dir, value))
            else:
                _resolve_config_paths(value, base_dir)
    elif isinstance(config, list):
        for item in config:
            _resolve_config_paths(item, base_dir)


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` into ``base`` (dicts only; lists replace)."""
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_image_files(image_folder):
    return [x for x in os.listdir(image_folder) if x.lower().endswith((".png", ".jpg", ".jpeg"))]


def load_config(config_dir: str | None = None):
    """Load and merge YAML settings.

    Prefers ``<project>/config/*.yaml`` (split by responsibility). Falls back
    to a monolithic ``config.yaml`` if the directory has no YAML files.
    """
    project_root = get_project_root()
    directory = config_dir or os.path.join(project_root, "config")

    merged: dict = {}
    yaml_files: list[str] = []
    if os.path.isdir(directory):
        yaml_files = sorted(
            f
            for f in os.listdir(directory)
            if f.lower().endswith((".yaml", ".yml"))
        )

    if yaml_files:
        print(f"Config dir: {directory} ({len(yaml_files)} files)")
        for name in yaml_files:
            path = os.path.join(directory, name)
            with open(path, "r", encoding="utf-8") as f:
                chunk = yaml.safe_load(f) or {}
            if not isinstance(chunk, dict):
                raise ValueError(f"Config file must be a mapping: {path}")
            _deep_merge(merged, chunk)
    else:
        legacy = os.path.join(project_root, "config.yaml")
        print("Config path:", legacy)
        with open(legacy, "r", encoding="utf-8") as f:
            merged = yaml.safe_load(f) or {}
        if not isinstance(merged, dict):
            raise ValueError(f"Config file must be a mapping: {legacy}")

    _resolve_config_paths(merged, project_root)
    return merged


def see_progress(iterable, desc="Processing"):
    return tqdm(iterable, desc=desc)

def read_yolo_labels(label_folder):
    """
    YOLO label 파일을 읽고 이미지별 객체 정보를 반환한다.
    return:{"image_name": {"counts": {class_id: count},"objects": total_count }}
    """
    label_data = {}
    label_folder = Path(label_folder)
    for label_file in label_folder.glob("*.txt"):
        class_counts = {}
        total_count = 0
        with open(label_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                class_id = int(float(line.split()[0]))
                class_counts[class_id] = class_counts.get(class_id, 0) + 1
                total_count += 1
        image_name = label_file.stem
        label_data[image_name] = {
            "counts": class_counts,
            "objects": total_count}

    return label_data
def _read_label_file(path):
    objects = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            data = line.strip().split()
            if len(data) == 5:
                objects.append(data)
    return objects

def load_yolo_labels(label_folder):
    """
    YOLO label 파일 읽기
    Input:
        label_folder: YOLO txt 파일 폴더 경로
    Output:
        labels: {image_name: [[class_id, x, y, w, h], ...]}
    """
    labels = {}

    for name in os.listdir(label_folder):
        if not name.endswith(".txt"):
            continue
        labels[os.path.splitext(name)[0]] = _read_label_file(os.path.join(label_folder, name))

    return labels
def yolo_bbox_to_pixels(label, height, width):
    """
    YOLO 정규화 좌표를 픽셀 좌표로 변환한다.
    Input:
        label: [class_id, x_center, y_center, width, height]
        height: 이미지 높이
        width: 이미지 너비
    Output:
        x1, y1, x2, y2: 픽셀 좌표 (이미지 경계로 클램프됨)
    """
    cx = float(label[1]) * width
    cy = float(label[2]) * height
    bw = float(label[3]) * width
    bh = float(label[4]) * height

    x1 = int(cx - bw / 2)
    y1 = int(cy - bh / 2)
    x2 = int(cx + bw / 2)
    y2 = int(cy + bh / 2)

    x1 = max(x1, 0)
    y1 = max(y1, 0)
    x2 = min(x2, width)
    y2 = min(y2, height)

    return x1, y1, x2, y2

def draw_yolo_boxes(image, labels, names=None):
    h, w = image.shape[:2]
    for label in labels:
        cls = int(label[0])
        x1, y1, x2, y2 = yolo_bbox_to_pixels(label, h, w)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
        text = str(cls)
        if names and cls in names:
            text = names[cls]
        cv2.putText(image, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return image

def draw_yolo_label_file(image, label_path, names=None):
    """
    단일 YOLO label 파일을 읽어 이미지에 박스를 그린다.
    Input:
        image: BGR 이미지
        label_path: YOLO txt 파일 경로
        names: {class_id: class_name}
    Output:
        박스가 그려진 이미지
    """
    labels = _read_label_file(label_path)
    return draw_yolo_boxes(image, labels, names)

def concat_images(images, axis=1):
    """
    여러 이미지를 이어붙인다.
    Input:
        images: BGR 이미지 리스트
        axis: 0(세로) 또는 1(가로)
    Output:
        이어붙인 이미지
    """
    images = [img for img in images if img is not None]
    if not images:
        return None

    if axis == 1:
        height = max(img.shape[0] for img in images)
        width = sum(img.shape[1] for img in images)
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        x = 0
        for img in images:
            canvas[:img.shape[0], x:x + img.shape[1]] = img
            x += img.shape[1]
        return canvas

    width = max(img.shape[1] for img in images)
    height = sum(img.shape[0] for img in images)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    y = 0
    for img in images:
        canvas[y:y + img.shape[0], :img.shape[1]] = img
        y += img.shape[0]
    return canvas