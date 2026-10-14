"""Preprocessing and augmentation for the v2 classifier.

Two deliberate differences from the v1 pipeline:

1. Letterboxing scales the LONG side, not the short one. The v1 transform
   scaled the short side to the target and then padded, which for a tall
   sprite means the resized image is larger than the canvas and the head or
   the feet get cut off -- exactly the parts that tell one monster from
   another. Scaling the long side always fits, so nothing is ever lost.

2. No saturation or hue jitter. Several species in this game are recolours of
   the same sprite (돌 골렘 13급 vs 라바 골렘 43급, 고블린 2급 vs 홉고블린
   14급) and colour is the only cue that separates them. Randomising it
   teaches the network to ignore the one signal that matters, and getting
   those pairs wrong is the dangerous kind of error: attacking a level-43
   monster with a level-13 plan.

Brightness and contrast jitter stay, because in-game lighting really does
vary and it does not destroy hue.
"""
from __future__ import annotations

import random
from io import BytesIO

from PIL import Image
from torchvision import transforms

LETTERBOX_MODE = "long_side"


class LetterboxLongSide:
    """Fit the whole image into a ``size`` x ``size`` canvas, centred.

    The long side is scaled to ``size`` and the short side is padded, so the
    aspect ratio is preserved and no pixel is ever cropped away.
    """

    def __init__(self, size: int, fill: int = 0):
        self.size = size
        self.fill = fill

    def __call__(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        scale = self.size / max(width, height)
        new_width = max(1, min(self.size, round(width * scale)))
        new_height = max(1, min(self.size, round(height * scale)))
        image = transforms.functional.resize(
            image, (new_height, new_width),
            interpolation=transforms.InterpolationMode.BILINEAR,
        )
        pad_left = (self.size - new_width) // 2
        pad_top = (self.size - new_height) // 2
        pad_right = self.size - new_width - pad_left
        pad_bottom = self.size - new_height - pad_top
        return transforms.functional.pad(
            image, (pad_left, pad_top, pad_right, pad_bottom), fill=self.fill
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(size={self.size}, fill={self.fill})"


class JpegNoise:
    """Re-encode as JPEG at a random quality to mimic capture compression."""

    def __init__(self, quality_range=(88, 96)):
        self.quality_range = quality_range

    def __call__(self, image: Image.Image) -> Image.Image:
        quality = random.randint(*self.quality_range)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        return Image.open(buffer).convert("RGB")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(quality_range={self.quality_range})"


def build_transforms(input_size: int, train: bool) -> transforms.Compose:
    """Training or validation transform pipeline.

    No horizontal flip: a sprite's facing direction is real information and
    mirroring it invents samples the game never produces.
    """
    ops = [LetterboxLongSide(input_size)]
    if train:
        ops += [
            transforms.RandomApply([
                transforms.ColorJitter(brightness=0.15, contrast=0.15),
            ], p=0.8),
            transforms.RandomRotation(degrees=(-3, 3), fill=0),
            transforms.RandomAffine(degrees=0, translate=(0.03, 0.03), fill=0),
            transforms.RandomApply([
                transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 0.4)),
            ], p=0.2),
            transforms.RandomApply([JpegNoise((88, 96))], p=0.2),
        ]
    ops.append(transforms.ToTensor())
    return transforms.Compose(ops)
