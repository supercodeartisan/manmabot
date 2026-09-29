"""Vision pipeline package.

Screen Image -> YOLO Detector -> ByteTrack Tracker -> Classifier -> World Model
"""

from .vision_system import VisionSystem

__all__ = ["VisionSystem"]
